#!/usr/bin/env bash
# Fresh clone to running, idempotently. Safe to run again at any time, and safe
# to run from a second worktree while the first one's stack is up: compose.yaml
# pins the project name, so every checkout of this repository sees the same
# three containers instead of trying to start its own on the same ports.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

step() { printf '\n== %s\n' "$1"; }

# --- Guarded temp files, fixed as a class ----------
# EVERY temp file this script makes holds a live credential: `env_set` stages
# the whole of .env (the Zitadel PAT included) on each call, `pat_file` holds
# the machine PAT, and `seed_log` is the tee of a first run's freshly-minted
# OAuth client secrets. Each site used to carry a bare `mktemp` with an `rm` on
# its happy path only, so under `set -euo pipefail` any failure — or a Ctrl-C —
# between the two lines walked past the `rm` and left the credential in $TMPDIR
# for nobody to rotate. Three sites, one bug, so one fix: this helper, and
# nobody calls `mktemp` directly.
#
# The registry is a private DIRECTORY rather than a list of paths, which is what
# lets the whole thing live inside one function: every call appends a file to
# it, cleanup is one `rm -rf` covering every call past and future, and there is
# no array to keep in step (nor bash 3.2's unset-array trap under `set -u`).
# `mktemp -d` makes it 0700, so the credentials are owner-only for their whole
# life rather than sitting in a world-readable /tmp between two lines.
#
# The trap is armed at FIRST USE — inside the helper, before it hands back a
# path — so no failure can land between creating a file and arming its removal.
# It is armed exactly once and never re-armed, because `trap` REPLACES rather
# than accumulates: a second `trap ... EXIT` anywhere below would silently
# disarm this one. Do not add one. INT/TERM/HUP `exit` rather than clean up
# themselves, which runs the EXIT trap on the way out — one cleanup path, not
# four.
#
# **It writes into a variable you name and prints nothing, and that is not a
# style choice.** `path="$(make_tmp)"` would run the whole helper in a command
# substitution — a SUBSHELL — where `DJB_TMP_DIR` and the trap are set on a
# shell that exits one microsecond later. Every call would make its own
# directory, arm a trap nobody will ever run, and leave the lot behind: the
# guard reading as coverage while covering nothing, which is worse than the bare
# `mktemp` it replaced. `printf -v` assigns in THIS shell; bash's dynamic
# scoping means the name may be a caller's `local`, which is what `env_set`
# relies on.
#
# What survives this: `kill -9`. SIGKILL cannot be trapped by any shell, so a
# hard kill still strands whatever was live at that instant. That is the
# irreducible residue, and it is why the per-site `rm` on the happy path stays:
# it keeps the window two adjacent lines wide rather than the whole run.
DJB_TMP_DIR=""

# Usage: make_tmp <variable-name>   — sets that variable to a fresh 0700 path.
make_tmp() {
    local __djb_target="$1"
    if [ -z "${DJB_TMP_DIR}" ]; then
        DJB_TMP_DIR="$(mktemp -d)"
        trap 'rm -rf "${DJB_TMP_DIR}"' EXIT
        trap 'exit 130' INT
        trap 'exit 143' TERM HUP
    fi
    printf -v "$__djb_target" '%s' "$(mktemp "${DJB_TMP_DIR}/tmp.XXXXXXXX")"
}

# The compose services this repository needs, and where each publishes.
# The stack a fresh clone needs up. MAILPIT IS IN THIS LIST BECAUSE
# `compose.yaml` SAYS IT IS THE CONTRACT: "every email the product sends
# on a laptop, caught and readable at http://127.0.0.1:8025 instead of
# delivered". A setup that brought up everything except the mail catcher left
# that promise true only for whoever thought to start it by hand — and the
# failure it exists to prevent is a laptop sending a real invitation to a real
# customer, which is exactly the kind of thing nobody starts a container for
# until after it has happened. It declares a healthcheck like every other
# service here, so `wait_healthy` covers it with no special case.
# MINIO AND MEILISEARCH JOINED LATER, each in the rung that gave it a reader —
# NOT when the containers themselves were first added, deliberately: adding a
# container to `compose.yaml` with nothing dialling it does not make a service
# a fresh clone is told it needs. Real storage tests put real bytes through
# MinIO; real engine tests drive Meilisearch live — a laptop without
# them up now FAILS those tests rather than skipping them, which is the whole
# reason they belong here.
SERVICES=(db redis temporal zitadel mailpit minio meilisearch)

# Health of one compose service, as compose reports it. Empty when the service
# is not running at all.
service_health() {
    docker compose ps --format '{{.Health}}' "$1" 2>/dev/null | head -1
}

# True when every service is already up and healthy — which is the normal case
# in a second worktree, and the case `docker compose up` used to make worse.
stack_is_healthy() {
    local service
    for service in "${SERVICES[@]}"; do
        [ "$(service_health "$service")" = "healthy" ] || return 1
    done
    return 0
}

# Sets KEY=VALUE in .env, in place: replacing the line if the key is already
# there, appending it if it is not. Never duplicates a key, never reorders the
# file, and never touches .env.example.
env_set() {
    local key="$1" value="$2" tmp
    # Site 1 of 3. The `rm` below is the happy path; `make_tmp`'s registry is
    # what covers the failing one — the redirect into .env going wrong, a
    # Ctrl-C, an `awk` that dies — each of which used to strand a full copy of
    # .env, PAT and all.
    make_tmp tmp
    if grep -q "^${key}=" .env; then
        awk -v k="$key" -v v="$value" '
            index($0, k "=") == 1 { print k "=" v; next }
            { print }
        ' .env >"$tmp"
    else
        cat .env >"$tmp"
        printf '%s=%s\n' "$key" "$value" >>"$tmp"
    fi
    cat "$tmp" >.env
    rm -f "$tmp"
}

# Waits for a compose service to report healthy. Every service in compose.yaml
# declares a healthcheck, so "up" is never mistaken for "ready".
wait_healthy() {
    local service="$1" attempts="${2:-90}"
    printf 'waiting for %s' "$service"
    for _ in $(seq 1 "$attempts"); do
        if [ "$(service_health "$service")" = "healthy" ]; then
            printf ' ready\n'
            return 0
        fi
        printf '.'
        sleep 1
    done
    printf '\n'
    echo "${service} did not become healthy; check 'docker compose logs ${service}'" >&2
    return 1
}

step "environment file"
if [ -f .env ]; then
    echo ".env already present, leaving it alone"
else
    cp .env.example .env
    echo "copied .env.example to .env"
fi
# Owner-only, every run and not just the run that created it (SEC-1's INFO,
# ridden here because this is where the file's owner is). Everything this
# script goes on to write into .env is a credential — the Zitadel PAT above
# all — and `cp` gives the copy the umask's mode, which on a normal laptop is
# world-readable. `chmod` on a file that is already 600 is a no-op, so this is
# safe to re-run and safe on a .env somebody else made.
chmod 600 .env

step "python dependencies"
uv sync

step "services"
if stack_is_healthy; then
    # The ports this line names are what it is vouching for; mailpit's 8025
    # belongs here too, or the message under-reports the stack it just called
    # healthy. MinIO's 9000 (S3 API) and 9001 (console) and Meilisearch's 7700
    # joined under the same rule.
    echo "reusing running stack (compose project djangobootstrap, ports 5432/6379/7233/8081/8025/9000/9001/7700)"
else
    docker compose up -d "${SERVICES[@]}"
    for service in "${SERVICES[@]}"; do
        # Zitadel's first start on an empty database runs every migration and
        # then the first-instance bootstrap; it is the slow one here.
        wait_healthy "$service" 180
    done
fi

step "zitadel machine credential"
# Zitadel mints the platform service account's personal access token exactly
# once, on its first start, into a named docker volume — never into this tree.
# It belongs in .env, which is gitignored, because that is where settings and
# the management client read it from.
# Site 2 of 3: the machine PAT. `make_tmp` arms the one EXIT trap on this first
# call, so the file is covered before this line has finished returning — and
# the trap it arms covers `seed_log` further down, and `env_set`'s per-call
# staging file, without any of them being named here (see `make_tmp`).
pat_file=""   # the out-parameter make_tmp fills; declared so `set -u` and shellcheck both see it
make_tmp pat_file
# THE OPERATOR'S VALUE IS ASKED ABOUT FIRST, and that ordering is the
# whole fix. This used to test the compose volume first and write
# unconditionally when it answered — so on any machine whose Zitadel had
# bootstrapped a PAT (which is every laptop running this stack) the
# "already in .env; leaving it alone" branch below was UNREACHABLE, and an
# operator pointing this checkout at an externally-managed Zitadel had their
# credential overwritten by the local container's on every run of a script
# whose whole promise is that it is safe to re-run.
#
# The same shape as a pin elsewhere in this repository, refused for the same
# reason: a value a human put somewhere is not this script's to replace
# without being asked.
# `.env` wins; the volume fills a gap.
if grep -q "^ZITADEL_PAT=." .env; then
    echo "ZITADEL_PAT already in .env; leaving it alone"
    # Said out loud, because "leaving it alone" is only reassuring if the
    # reader knows there WAS something else on offer. A silent no-op and a
    # no-op nobody could have noticed look identical in a transcript.
    if docker compose cp zitadel:/zitadel/bootstrap/machine.pat "$pat_file" >/dev/null 2>&1; then
        echo "  (this compose Zitadel offers its own bootstrap PAT; .env's value wins —"
        echo "   delete the ZITADEL_PAT line and re-run to adopt the container's)"
    fi
elif docker compose cp zitadel:/zitadel/bootstrap/machine.pat "$pat_file" >/dev/null 2>&1; then
    env_set ZITADEL_PAT "$(tr -d '\r\n' <"$pat_file")"
    echo "ZITADEL_PAT written to .env from the zitadel_bootstrap volume"
else
    echo "no PAT: this Zitadel instance was bootstrapped without one." >&2
    echo "Issue one for the machine user, or reset the instance (drop the" >&2
    echo "zitadel database and the zitadel_bootstrap volume), then run this again." >&2
fi
rm -f "$pat_file"

step "sign-in door (classic login)"
# THE INSTANCE HALF, and it exists because the compose line is
# only the OTHER half. `compose.yaml` pins
# ZITADEL_DEFAULTINSTANCE_FEATURES_LOGINV2_REQUIRED=false; `DefaultInstance` is
# applied WHEN THE INSTANCE IS CREATED, so that line is the whole fix on a
# fresh volume and does NOTHING to an instance that already exists — Zitadel's
# own defaults.yaml: once a feature is set on the instance, system-level
# feature settings are ignored until instance features are reset. Every laptop
# that ran this stack before the compose line landed carries such an instance,
# and on it the browser sign-in button redirects to
# `/ui/v2/login/login?authRequest=…` and gets a 404, because Login V2 is a
# separate container this stack does not ship: the quickstart's first step,
# invitation acceptance and the /mcp OAuth flow are all dead behind it. The
# feature API is the only route into an existing instance, so this step drives
# it. The reasoning, the spelling read out of the image, and the adoption
# trigger live at `deploy/compose.yaml`'s copy of that key — one home.
#
# IDEMPOTENT: it reads first and writes only when it finds the defect, so the
# normal case is one line saying nothing needed doing.
#
# NEVER FATAL, argued the other way. Identity may legitimately
# be unbootstrapped on this laptop — no PAT, no instance, an operator pointing
# at something that is not up yet — and `zitadel_seed` below is already the step
# that reports a shut identity door. A failure to READ or WRITE the feature here
# prints the manual command on stderr and carries on; it never fails setup.
# Single-quoted ON PURPOSE: this string is printed for a human to paste, so the
# `$ZITADEL_PAT` and `$ZITADEL_ISSUER` in it must survive as names they can read
# out of their own .env — expanding them here would print the credential.
# shellcheck disable=SC2016
login_v2_manual='curl -X PUT -H "Authorization: Bearer $ZITADEL_PAT" -H "Content-Type: application/json" -d "{\"loginV2\":{\"required\":false}}" "$ZITADEL_ISSUER/v2/features/instance"'
zitadel_pat="$(sed -n 's/^ZITADEL_PAT=//p' .env | tail -1)"
zitadel_base="$(sed -n 's/^ZITADEL_ISSUER=//p' .env | tail -1)"
if [ -z "$zitadel_base" ]; then
    zitadel_port="$(sed -n 's/^ZITADEL_EXTERNALPORT=//p' .env | tail -1)"
    zitadel_base="http://localhost:${zitadel_port:-8081}"
fi
# The PAT goes in on STDIN, through curl's own config format, rather than in an
# argument: `curl -H "Authorization: Bearer $PAT"` puts a live credential in the
# process table for anyone with `ps` for as long as the request takes. `printf`
# is a shell builtin, so it never appears in an argument list either.
if ! command -v curl >/dev/null 2>&1; then
    echo "sign-in door: curl not found, so loginV2 was not checked on this instance." >&2
    echo "  Check and repair by hand: ${login_v2_manual}" >&2
elif [ -z "$zitadel_pat" ]; then
    echo "sign-in door: no ZITADEL_PAT in .env, so loginV2 was not checked." >&2
    echo "  Repair once identity is bootstrapped: ${login_v2_manual}" >&2
else
    features="$(printf 'header = "Authorization: Bearer %s"\n' "$zitadel_pat" |
        curl -sS -K - -w '\n%{http_code}' "${zitadel_base}/v2/features/instance" 2>/dev/null || true)"
    features_code="$(printf '%s' "$features" | tail -1)"
    features_body="$(printf '%s' "$features" | sed '$d')"
    if [ "$features_code" != "200" ]; then
        echo "sign-in door: could not read ${zitadel_base}/v2/features/instance (HTTP ${features_code:-none});" >&2
        echo "  loginV2 was NOT checked. If browser sign-in 404s at /ui/v2/login/…, repair by hand:" >&2
        echo "  ${login_v2_manual}" >&2
    elif ! printf '%s' "$features_body" | grep -q '"loginV2"'; then
        # Said out loud rather than read as "already correct": a feature API that
        # stopped naming loginV2 is a shape change, and the one answer this step
        # must never give on a shape it does not recognise is reassurance.
        echo "sign-in door: the feature API answered without a loginV2 field — shape not recognised," >&2
        echo "  so nothing was checked. Read it yourself: ${zitadel_base}/v2/features/instance" >&2
    else
        login_v2="$(printf '%s' "$features_body" | tr -d ' \n' | sed -n 's/.*"loginV2":{\([^}]*\)}.*/\1/p')"
        case "$login_v2" in
        *'"required":true'*)
            echo "sign-in door: loginV2 required=true found on this instance — repairing (classic-login-pin)"
            repair_code="$(printf 'header = "Authorization: Bearer %s"\n' "$zitadel_pat" |
                curl -sS -K - -X PUT -H 'Content-Type: application/json' \
                    -d '{"loginV2":{"required":false}}' \
                    -o /dev/null -w '%{http_code}' \
                    "${zitadel_base}/v2/features/instance" 2>/dev/null || true)"
            if [ "$repair_code" = "200" ]; then
                echo "sign-in door: loginV2 required=false — classic login restored"
            else
                echo "sign-in door: the repair PUT failed (HTTP ${repair_code:-none}); browser sign-in" >&2
                echo "  will still 404 at /ui/v2/login/…. Repair by hand:" >&2
                echo "  ${login_v2_manual}" >&2
            fi
            ;;
        *)
            echo "sign-in door: loginV2 not required on this instance — already correct"
            ;;
        esac
    fi
fi

step "database for this worktree"
# shellcheck source=scripts/db.sh
source "${ROOT}/scripts/db.sh"
db_create
# Persist the derivation into .env, so a BARE `manage.py` — one that never
# sourced db.sh — resolves the same database every script here does. Without
# this line .env keeps whatever .env.example shipped and a stray
# `manage.py migrate` lands somewhere else entirely.
#
# RECONCILE ON EVERY RUN, UNLESS THE PIN SAYS IT MEANT IT. This line
# already wrote the derived name unconditionally — which is the reconciliation
# the build contract promises, and also, for a checkout that pinned a name on
# purpose, the same silent clobber as above (a value a human put there,
# replaced without being asked). The marker `# pinned` on the DATABASE_NAME
# line is the one-grep escape: a checkout that carries it keeps its name and
# is told that it did.
#
# The disagreement itself is NOT silenced by the marker — `db.sh` still prints
# its notice on every source, because a pinned checkout still has two
# databases and that fact does not stop being true because somebody meant it.
# The marker governs what this script WRITES, not what any script SAYS.
if grep -qE '^DATABASE_NAME=.*#[[:space:]]*pinned' .env; then
    env_pin="$(grep -E '^DATABASE_NAME=' .env | tail -1)"
    echo "DATABASE_NAME left alone — .env carries the \`# pinned\` marker"
    echo "  .env:       ${env_pin}"
    echo "  derivation: ${DATABASE_NAME}"
    echo "  This checkout's scripts will use the derivation and a bare manage.py"
    echo "  will use the pin. Remove the marker and re-run to reconcile them."
else
    env_set DATABASE_NAME "${DATABASE_NAME}"
    echo "DATABASE_NAME=${DATABASE_NAME}"
fi

step "migrations"
DATABASE_NAME="${DATABASE_NAME}" uv run python manage.py migrate

step "zitadel identity configuration"
# Idempotent: the project, the browser client, the MCP resource, the
# pre-registered MCP client and a dev person. A second run — which is every run
# after the first, in every worktree sharing this instance — creates nothing and
# says `exists` for each. That is why it can live here rather than in a
# README step somebody has to remember (ADR ident-2).
#
# NOT FATAL, AND NOT SILENT EITHER. This step used to be "not fatal"
# in the strongest sense available: the failure was named on stderr, the script
# carried on, and the closing banner said "Setup complete." with exit 0. Both
# halves of that are a lie a caller acts on. A human skims for the banner; CI
# reads `$?`; and the one state a setup script must never report is "the
# machine is now what you asked for" when it is not — the identity door is shut
# and every OAuth path through /mcp is dead.
#
# So the two behaviours are separated rather than traded off. The REST of setup
# still runs — the database, the migrations, the hooks, the guidance — because
# a laptop with no PAT genuinely should end up with a working stack, and
# stopping here would take that away. What changes is the VERDICT: the failure
# is remembered in `SETUP_INCOMPLETE`, the closing banner names what did not
# happen instead of claiming completion, and the script exits non-zero.
#
# Exit 1, not 2: this script LOOKED. It ran `zitadel_seed`, the command
# answered, and the answer was a failure — "I looked and it is wrong", which is
# exit 1 everywhere in this repository. Exit 2 here stays what it is elsewhere
# (`docs/product/instruments.md`): could not look at all.
SETUP_INCOMPLETE=""
# Site 3 of 3. Live credentials again: on a first run the seed prints the OAuth
# client secrets it has just minted, and this is the tee of that output. The
# `rm` after the block is the happy path; every other exit is covered by the
# single EXIT trap `make_tmp` armed. Do not arm a second trap here — it would
# replace that one and un-guard the PAT.
seed_log=""   # likewise
make_tmp seed_log
if DATABASE_NAME="${DATABASE_NAME}" uv run python manage.py zitadel_seed | tee "$seed_log"; then
    # The OAuth door, armed from what the seed just resolved.
    #
    # `ZITADEL_MCP_AUDIENCE` empty does not mean "accept any audience", it means
    # the /mcp OAuth door is OFF (`apps/accounts/oauth.py`) — so every fresh
    # clone shipped with that door shut until a human read .env.example and
    # pasted an id by hand. The id is not a secret and is not a choice: it is
    # the project the line above either created or found, and Zitadel puts it
    # in every access token's `aud` for this project. The one thing this script
    # cannot know is whether an operator is pointing at an externally-managed
    # Zitadel with an audience of their own, which is what the
    # already-set branch below is for.
    #
    # Read off the seed's own `created`/`exists  project <name>  (<id>)` line
    # rather than asked for again, because a second lookup is a second answer:
    # what belongs in .env is the id the run that just configured this instance
    # actually used.
    #
    # Pinned to the verb as well as the noun, and to the FIRST such line: the
    # command prints that line early and prints prose afterwards, and prose
    # that happened to put "project" in its second word would otherwise hand
    # this an English word to write into .env.
    project_id="$(awk '
        $1 ~ /^(created|exists)$/ && $2 == "project" && id == "" { id = $NF }
        END { gsub(/[()]/, "", id); print id }
    ' "$seed_log")"
    if [ -z "${project_id}" ]; then
        echo "could not read the project id from zitadel_seed's output;" >&2
        echo "set ZITADEL_MCP_AUDIENCE in .env by hand (see .env.example)." >&2
    elif grep -q "^ZITADEL_MCP_AUDIENCE=." .env; then
        echo "ZITADEL_MCP_AUDIENCE already set in .env; leaving it alone"
    else
        env_set ZITADEL_MCP_AUDIENCE "${project_id}"
        echo "ZITADEL_MCP_AUDIENCE written to .env (${project_id})"
    fi
else
    echo "zitadel_seed did not complete; the rest of the stack is fine." >&2
    echo "Fix the PAT above and run: uv run python manage.py zitadel_seed" >&2
    SETUP_INCOMPLETE="zitadel_seed did not complete, so identity configuration was not applied"
fi
rm -f "$seed_log"

step "object storage bucket for this worktree"
# THE SAME PROBLEM AS THE DATABASE, AND THE SAME ANSWER. Agents build in
# parallel worktrees against ONE compose
# MinIO. Two checkouts writing `t/<tenant>/` into one bucket would see each
# other's objects, and a prefix delete in one would take the other's away — so
# the bucket follows the CHECKOUT, named for the SHA-256 of its own absolute
# path exactly as `DATABASE_NAME` is, and a name already in `.env` wins exactly
# as `DATABASE_NAME`'s does.
#
# THE DERIVATION IS NOT MIRRORED HERE, and that is the whole shape of this step.
# `db.sh` re-implements its hash in shell because it must work before `uv sync`
# has run; this one runs after it, so it can ASK the seam that owns the answer
# (`apps/files/storage.py::derived_bucket_name`) instead of keeping a second
# copy of the arithmetic in a second language for the two to drift apart in.
# `manage.py ensure_bucket` prints the name on stdout and nothing else, for
# exactly this line to capture; it also CREATES the bucket if it is absent,
# which is the other half — a name in `.env` pointing at no bucket makes
# /readyz report `storage: false`, which is a worse lie than reporting nothing.
#
# WHAT IT UNLOCKS, so nobody has to guess why this step exists: naming a bucket
# is the whole switch to S3 (`config/settings/base.py`), so after this line
# `/readyz` grows a `storage` member (`apps/core/health.py::checks` adds it only
# when a bucket is named) and `apps/files` can store, sign and stream for real
# on a laptop. Before it, every one of those was configured-as-absent.
#
# NOT FATAL, AND NOT SILENT (the same shape as at the seed above): a laptop
# whose MinIO is not up should still finish setup with a database, migrations
# and hooks. The failure is named on stderr, joins the verdict rather than
# replacing it — `${SETUP_INCOMPLETE:+…; }` appends, so identity's failure and
# this one can both be true — and the script exits non-zero at the end.
if bucket_name="$(DATABASE_NAME="${DATABASE_NAME}" uv run python manage.py ensure_bucket)"; then
    env_set AWS_STORAGE_BUCKET_NAME "${bucket_name}"
    echo "AWS_STORAGE_BUCKET_NAME=${bucket_name}"
else
    echo "no object storage: the bucket could not be made, so AWS_STORAGE_BUCKET_NAME" >&2
    echo "  was left alone. /readyz will carry no \`storage\` member and apps/files" >&2
    echo "  will refuse. Bring MinIO up and run: uv run python manage.py ensure_bucket" >&2
    SETUP_INCOMPLETE="${SETUP_INCOMPLETE:+${SETUP_INCOMPLETE}; }the object storage bucket was not made, so this checkout has no object storage"
fi

step "integrations"
# THE CENSUS, AT MINUTE ONE — the first of its four surfaces (INTEG-1).
#
# Everything above this line configured ONE thing each and said so in its own
# words; this says what the whole deployment now talks to, in one place, in the
# same words `manage.py integrations`, `deploy/release.sh`'s wall and the
# standing prober use. A person's first hour used to be spent discovering, one
# refusal at a time, which slots were filled by something real and which by a
# stand-in that succeeds quietly — the SMS transport being the worst of them
# (a fresh clone keeps `FakeSmsChannel` and nothing anywhere says so).
#
# NOT FATAL, AND NOT SILENT, exactly as the two steps above are: a fresh clone
# is SUPPOSED to be standing on some fakes, and a setup script that failed
# because the console mail backend is set would be crying wolf on every first
# run. So the report is printed and the exit status is not consulted — the
# refusing surface is the DEPLOY (`release.sh --wall`), where a fake is a
# genuine finding and where refusing costs nobody a first afternoon.
#
# `|| true` because `--wall` is deliberately absent here and the plain command
# still exits 2 if a seam could not be read; that is a finding for the report to
# carry rather than a reason to stop a laptop's setup.
DATABASE_NAME="${DATABASE_NAME}" uv run python manage.py integrations || true

step "git hooks"
if [ -d scripts/githooks ]; then
    git config core.hooksPath scripts/githooks
    chmod +x scripts/githooks/* 2>/dev/null || true
    echo "core.hooksPath set to scripts/githooks"
else
    echo "scripts/githooks does not exist yet; skipping hook wiring"
fi

# The verdict. Two banners and two exit codes, because "what this machine now
# has" is the one thing this script is asked, and there is no honest way to
# answer it with a single sentence that fits both outcomes. The guidance below
# is printed either way — it is still what to do next — but the FIRST line and
# `$?` agree with each other, which is what a skimming human and a CI runner
# each read.
if [ -n "${SETUP_INCOMPLETE}" ]; then
    cat <<INCOMPLETE >&2

Setup did NOT complete: ${SETUP_INCOMPLETE}
This worktree uses database ${DATABASE_NAME}; the database, the migrations and
the stack are fine, and the identity door is shut — /mcp's OAuth paths and
anything that needs a Zitadel project will not work until the seed succeeds.

  uv run python manage.py zitadel_seed     # after fixing ZITADEL_PAT in .env
INCOMPLETE
fi

cat <<NEXT

$(if [ -n "${SETUP_INCOMPLETE}" ]; then
    printf 'The rest of setup ran. This worktree uses database %s.' "${DATABASE_NAME}"
else
    printf 'Setup complete. This worktree uses database %s.' "${DATABASE_NAME}"
fi)

Next:
  source scripts/db.sh                     # export DATABASE_NAME in your shell
  uv run python manage.py seed             # a tenant, an owner, a member, an API token — start here
  uv run python manage.py createsuperuser  # a way in to /admin/
  uv run python manage.py issue_token --email you@example.com --name laptop --scope '*'
                                           # --scope is required; '*' means no limit.
                                           # Narrow it with --scope widgets:read (repeat per scope).
  ./scripts/serve.sh                       # http://127.0.0.1:8000/api/v1/docs
  ./scripts/worker.sh                      # the Temporal worker, in another shell
  ./scripts/test.sh                        # the test suite

  Temporal's web UI is on http://127.0.0.1:8233
  Zitadel is on http://localhost:8081 — console /ui/console, discovery
  /.well-known/openid-configuration. Sign in as ${ZITADEL_ADMIN_USERNAME:-zitadel-admin@djangobootstrap.localhost}
  with the password in .env. Identity CONFIGURATION goes through our services,
  never through that console.
NEXT

# Exit 1, not 2: this script looked, and what it found is wrong (the header at
# the seed step). Last statement in the file, so a failure anywhere above still
# reaches here through `set -e` with its own status rather than this one.
[ -z "${SETUP_INCOMPLETE}" ] || exit 1
