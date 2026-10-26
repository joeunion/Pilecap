#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
# road: compose_organs — bring the compose organs up under a runner, its database derived first · example: quality/tests/test_ci_stack.py::test_up_derives_the_database_and_waits_on_the_named_organs
# THE STACK A RUNNER STANDS UP — the one recipe for "derive this checkout's
# database, then bring the named compose organs up and wait until each is
# healthy", run by both workflows (`ci.yml`'s legs, `nightly-proof.yml`'s
# proof) and safe for `scripts/setup.sh` on a laptop's one shared stack.
#
#   scripts/ci_stack.sh up [<service>…]        derive, pull, `docker compose up -d --wait`, then create the database when db is named
#   scripts/ci_stack.sh diagnose [<service>…]  `ps` and the last 200 log lines
#
# With no service named, `up` brings up the population `compose.yaml` itself
# declares (`docker compose config --services` — the services no profile
# gates), never a typed list.
#
# Exit: 0 the organs are up and healthy (and the database exists when db is
# named) · 1 an organ did not come up (the diagnostics tail is printed) or the
# database could not be created · 2 could not look: no derived database name,
# no docker, an unknown subcommand, or an image that would not pull twice
# (`could not look: <image> pull failed (<registry>)` — the registry's, never
# the tree's).
#
# THE DATABASE NAME IS DERIVED, NEVER TYPED, AND IT REFUSES RATHER THAN FALLS
# BACK. It is `scripts/db.sh`'s `db_name` — the one derivation a laptop, a
# worktree and a runner all run — and it must be the derived SHAPE
# (`scripts/lifecycle.sh::lc_derived_shape`): a name of any other shape leaves
# the own-tree census asserting over an empty scope and passing. Under GitHub
# Actions it is written to `$GITHUB_ENV`, so every later step (the gate, the
# backup drive, the restore drill) reads this one value rather than deriving
# its own.
# The name is the CHECKOUT's database, created on the running server by
# `db_create` — never the container's POSTGRES_DB, which on a laptop's one shared
# stack would differ per checkout and recreate the db container.
#
# THE CREDENTIALS are the caller's `DATABASE_USER`/`DATABASE_PASSWORD` (the
# workflows' `env:` blocks), handed to compose as POSTGRES_USER/PASSWORD — so
# the value Django dials and the value the container is created with are one.
#
# `--wait` is what makes "up" a precondition rather than a race: compose blocks
# until every long-running organ named reports healthy on its own healthcheck,
# and until every one-shot named (`compose_once_members`' once lines —
# zitadel-init, zitadel-setup, which declare no healthcheck) has exited 0, which
# `--wait` accepts as done by compose's own grace on the pinned compose
# (`BAKE_COMPOSE_VERSION`, deploy/verifier/bake.sh).
#
# WHAT IT DOES NOT COVER
# does-not-cover: the registry login a pinned image needs (the MinIO mirror's ECR Public pull) — that is a workflow step, an action, and stays one in each workflow.
# does-not-cover: tearing anything down — a runner is destroyed with its job; a laptop tears down with deploy/teardown.sh.
# does-not-cover: the profile-gated organs (`observability`) — `config --services` omits them, so the default population is the always-on set; a caller that wants one names it.

set -euo pipefail

CI_STACK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/gate_refuse.sh
. "$CI_STACK_ROOT/scripts/gate_refuse.sh"

# ci_stack_database — derive this checkout's database name (scripts/db.sh),
# refuse a non-derived shape, export it, and hand it to later Actions steps.
ci_stack_database() {
    # Sourced in a subshell-free way on purpose: the export IS the product.
    # shellcheck source=scripts/db.sh
    DB_PIN_NOTE_OFF=1 . "$CI_STACK_ROOT/scripts/db.sh" >/dev/null ||
        gate_die "" "ci_stack: could not source scripts/db.sh — the one derivation of this checkout's database name"
    # shellcheck source=scripts/lifecycle.sh
    . "$CI_STACK_ROOT/scripts/lifecycle.sh" ||
        gate_die "" "ci_stack: could not source scripts/lifecycle.sh — the derived-shape judge"
    if [ -z "${DATABASE_NAME:-}" ] || ! lc_derived_shape "$DATABASE_NAME"; then
        gate_die "" "ci_stack: this checkout has no derived database name (DATABASE_NAME is '${DATABASE_NAME:-<empty>}')." \
            "The own-tree census narrows every verdict to a derived identity, so a name of any other" \
            "shape leaves it asserting over an empty scope and passing. Nothing was started."
    fi
    export DATABASE_NAME
    if [ -n "${GITHUB_ENV:-}" ]; then
        echo "DATABASE_NAME=${DATABASE_NAME}" >>"$GITHUB_ENV"
    fi
    echo "ci_stack: this checkout's database: ${DATABASE_NAME} (derived by scripts/db.sh)"
}

# compose_once_members — the services a rendered compose file (stdin) runs once, one per line:
#   once<TAB><one-shot><TAB><dependant>  another service's `depends_on` waits on it with
#                                        `condition: service_completed_successfully`
#   door<TAB><service>                   `restart: "no"` and nothing waits on it: a `compose run`
#                                        door, never `up`ped
# The one reader of both facts; setup.sh, deploy/provision.sh and envelope.sh take what they need.
compose_once_members() {
    awk '
        /^[^ ]/ { in_services = ($0 == "services:"); next }
        !in_services { next }
        /^  [^ ]/ { service = $1; sub(/:$/, "", service); order[++n] = service; deps = 0; next }
        /^    [^ ]/ {
            deps = ($1 == "depends_on:")
            if ($0 ~ /^    restart: "?no"?$/) runs_once[service] = 1
            next
        }
        deps && /^      [^ ]/ { needed = $1; sub(/:$/, "", needed); next }
        deps && $0 ~ /^        condition: service_completed_successfully$/ {
            print "once\t" needed "\t" service; waited[needed] = 1
        }
        END { for (i = 1; i <= n; i++) if ((order[i] in runs_once) && !(order[i] in waited)) print "door\t" order[i] }
    '
}

# ci_stack_services — the organs `compose.yaml` declares outside any profile.
ci_stack_services() {
    (cd "$CI_STACK_ROOT" && docker compose config --services)
}

# ci_stack_diagnose [<service>…] — the tail a reader needs when an organ did
# not come up: what is running, and the last 200 lines of the named organs.
ci_stack_diagnose() {
    (
        cd "$CI_STACK_ROOT" || exit 0
        docker compose ps || true
        docker compose logs --no-color --tail=200 "$@" || true
    )
}

# ci_stack_compose_up <service>… — one `docker compose up -d --wait` under the caller's credentials.
ci_stack_compose_up() {
    (
        cd "$CI_STACK_ROOT"
        POSTGRES_USER="${DATABASE_USER:-${POSTGRES_USER:-}}" \
            POSTGRES_PASSWORD="${DATABASE_PASSWORD:-${POSTGRES_PASSWORD:-}}" \
            docker compose up -d --wait "$@"
    )
}

# ci_stack_organs <service>… — `up -d --wait` the named organs, ONE retry after a pause; the diagnostics tail on failure.
# Exit 0 every organ done (healthy, or a one-shot exited 0) · 1 one was not, twice. It derives and creates no database — setup.sh's own step owns its pin.
# One retry, never more: the population is a registry's or token endpoint's transient refusal.
ci_stack_organs() {
    local rc=0 pause="${CI_STACK_RETRY_PAUSE:-15}"
    [ "$#" -gt 0 ] || gate_die "" "ci_stack: ci_stack_organs names no organ — nothing to bring up"
    echo "ci_stack: up --wait $*"
    ci_stack_compose_up "$@" || rc=$?
    if [ "$rc" != "0" ]; then
        echo "ci_stack: docker compose up --wait exited ${rc} — retrying once in ${pause}s. The first attempt's tail:" >&2
        ci_stack_diagnose "$@" >&2
        sleep "$pause"
        rc=0
        echo "ci_stack: up --wait $* (the retry)"
        ci_stack_compose_up "$@" || rc=$?
    fi
    if [ "$rc" != "0" ]; then
        echo "RED: ci_stack: docker compose up --wait exited ${rc} — an organ did not come up healthy. The tail:" >&2
        ci_stack_diagnose "$@" >&2
        return 1
    fi
}

# ci_stack_registry <image> — the registry an image reference pulls from (Docker Hub when it names none).
ci_stack_registry() {
    local first="${1%%/*}"
    case "$1" in
    */*) ;;
    *) first="" ;;
    esac
    case "$first" in
    *.* | *:* | localhost) printf '%s\n' "$first" ;;
    *) printf 'docker.io\n' ;;
    esac
}

# ci_stack_pull <service>… — pull each organ's image, ONE retry after a pause; 0 all pulled · 2 could not look.
# A registry that will not serve an image twice is the road's failure, never the tree's: no organ was judged.
ci_stack_pull() {
    local svc image rc pause="${CI_STACK_RETRY_PAUSE:-30}"
    for svc in "$@"; do
        rc=0
        (cd "$CI_STACK_ROOT" && docker compose pull --quiet "$svc") || rc=$?
        if [ "$rc" != "0" ]; then
            echo "ci_stack: docker compose pull ${svc} exited ${rc} — retrying once in ${pause}s" >&2
            sleep "$pause"
            rc=0
            (cd "$CI_STACK_ROOT" && docker compose pull --quiet "$svc") || rc=$?
        fi
        if [ "$rc" != "0" ]; then
            image="$(cd "$CI_STACK_ROOT" && docker compose config --images "$svc" 2>/dev/null | head -n 1)" || image=""
            image="${image:-${svc}}"
            echo "could not look: ${image} pull failed ($(ci_stack_registry "$image"))" >&2
            echo "   the registry refused the pull twice; no organ was started and nothing was judged." >&2
            return 2
        fi
    done
}

# ci_stack_up [<service>…] — derive, pull, then bring the organs up and wait.
ci_stack_up() {
    local services=("$@")
    command -v docker >/dev/null 2>&1 || gate_die "" "ci_stack: no docker on PATH — nothing was started"
    ci_stack_database
    if [ "${#services[@]}" -eq 0 ]; then
        local listed
        listed="$(ci_stack_services)" || gate_die "" "ci_stack: 'docker compose config --services' did not answer — the population is unknown; nothing was started"
        # shellcheck disable=SC2206  # one service name per line, no spaces by compose's own grammar
        services=($listed)
    fi
    [ "${#services[@]}" -gt 0 ] || gate_die "" "ci_stack: compose.yaml declares no service — nothing to bring up"
    local pg_user="${DATABASE_USER:-${POSTGRES_USER:-}}" pulled=0
    ci_stack_pull "${services[@]}" || pulled=$?
    [ "$pulled" = "0" ] || return "$pulled"
    ci_stack_organs "${services[@]}" || return 1
    case " ${services[*]} " in
    *" db "*) ;;
    *) return 0 ;;
    esac
    (
        cd "$CI_STACK_ROOT"
        POSTGRES_USER="${pg_user:-djb}" db_create "$DATABASE_NAME"
    ) || {
        echo "RED: ci_stack: the db organ is healthy and ${DATABASE_NAME} could not be created on it (scripts/db.sh's db_create; its words are above)" >&2
        return 1
    }
}

# Run, not sourced: the subcommand is the first argument.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    case "${1:-}" in
    up)
        shift
        ci_stack_up "$@"
        ;;
    diagnose)
        shift
        ci_stack_diagnose "$@"
        ;;
    *)
        gate_die "" "ci_stack: unknown subcommand '${1:-}' — 'up [<service>…]' or 'diagnose [<service>…]'"
        ;;
    esac
fi
