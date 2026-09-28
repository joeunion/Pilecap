#!/usr/bin/env bash
# The drive for `deploy/release.sh` — the refusals, the stop-at-the-named-act
# behaviour, the exit codes and the re-runnability.
#
#   ./deploy/tests/test_release.sh          run every case
#   ./deploy/tests/test_release.sh --list   name them and stop
#
# WHY IT EXISTS, and it is `scripts/tests/test_pm_merge.sh`'s reason applied to
# the deployment: a sequence script is made of refusals and orderings, and both
# are invisible when they are right. The happy path goes on printing seven acts
# whether or not the migrate still runs before the restart, whether or not a
# failed `psql` still stops the sequence, whether or not the missing-credential
# refusal still refuses. The cost of a release act that quietly does not happen
# is exact: the app role keeps UPDATE and DELETE on an append-only table nothing
# else can see. A guard nobody drives can be deleted by accident and stay
# deleted.
#
# IT BUILDS ITS OWN DEPLOYMENT AND RELEASES THAT. Every case runs against a
# throwaway `deploy/` directory this file creates under `mktemp -d`, carrying a
# COPY of `release.sh`, a stub `compose.yaml`, a generated `.env` full of
# obviously-fake values, a stub `provision.sh` and a stub `apply.py` — and a
# STUB `docker` first on PATH, which records every invocation and answers with
# whatever the case asked for. Nothing here reaches a real deployment, a real
# database, a real sink or a real container runtime.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE ACTS DO WHAT THEY SAY. The stub `docker` does not migrate, does
#     not apply grants and does not restart anything. These cases prove the
#     WIRING and the CONTROL FLOW: that the seven acts happen in that order, that
#     each one's failure stops the sequence naming itself, that the exit status
#     is 0/1/2 as declared, and that the arguments handed to docker are the ones
#     the runbook used to type by hand. What `migrate` does is Django's business,
#     what the SQL grants is `deploy/test_grants_census.py`'s, and what
#     `apply.py` reconciles is its own.
#   * A REAL SINK. `apply.py` is stubbed to an exit code. Its own refusals (a
#     census warning, a missing Logs source) are its file's to prove; what is
#     proven here is that its exit code becomes the release's, verbatim and
#     named.
#   * A COPY, NOT THE FILE ITSELF, IS WHAT RUNS — `scripts/tests/test_pm_merge.sh`'s
#     declared limit, for the same reason: the script derives everything from its
#     own directory, so the scratch deployment has to contain it. The copy is
#     made with `cp` from this tree in every case, so it is the same bytes.
#   * IDEMPOTENCE OF THE UNDERLYING ACTS. That a second `migrate` applies nothing
#     and a second `GRANT` grants the same thing is argued in `release.sh`'s own
#     per-act comments and owned by Django and Postgres. What is proven here is
#     the property the script owns: a run that stopped at an act can be re-run
#     from the top and complete, and two clean runs perform the identical
#     sequence.
set -euo pipefail

cd "$(dirname "$0")/../.."

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_release: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    # A mistyped flag is never a silently different run.
    echo "!! unknown argument '$1': test_release.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v bash >/dev/null 2>&1 || cannot_look "no bash on PATH"
command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH — the stub apply.py is a python file"
[ -f deploy/release.sh ] || cannot_look "deploy/release.sh is not in this tree — there is nothing to drive"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-release-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
trap 'rm -rf "$WORK"' EXIT

SOURCE="$PWD/deploy/release.sh"

# --- the assertions every case makes (test_pm_merge.sh's helpers) -------------
DRIVE_OUT=""
DRIVE_EXIT=0
CURRENT=""
drive() {
    local label="$1" want="$2"
    shift 3
    CURRENT="$label"
    DRIVE_OUT="${WORK}/$(printf '%s' "$label" | tr -c 'a-zA-Z0-9' '_').log"
    set +e
    "$@" >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    set -e
    if [ "$DRIVE_EXIT" -eq "$want" ]; then
        echo "  ok       ${label} — exit ${DRIVE_EXIT}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted exit ${want}, got ${DRIVE_EXIT}"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -30
        FAILED=$((FAILED + 1))
    fi
}

# A refusal with the right code and the wrong sentence is a refusal nobody can
# act on, so both are asserted about the same run.
says() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        echo "  ok       ${CURRENT} — says \"$1\""
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — does not say \"$1\""
        sed 's/^/             | /' "$DRIVE_OUT" | tail -30
        FAILED=$((FAILED + 1))
    fi
}

says_not() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        echo "  FAILED   ${CURRENT} — says \"$1\" and must not"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -30
        FAILED=$((FAILED + 1))
    else
        echo "  ok       ${CURRENT} — does not say \"$1\""
        PASSED=$((PASSED + 1))
    fi
}

holds() {
    local label="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then
        echo "  ok       ${label} — ${got}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted '${want}', got '${got}'"
        FAILED=$((FAILED + 1))
    fi
}

# --- the scratch deployment ---------------------------------------------------
#
# One per case, so a case can never read the docker log another case wrote.
CASE_DIR=""
DEPLOY=""
DOCKER_LOG=""
ALERTS_LOG=""
PIN_LOG=""

# THE REGISTRY'S DEFAULT ANSWERS, per case. Build-once/promote-by-digest makes
# "the registry has the image this tree names" a precondition of every release
# (ADR deploy-4), so an ordinary case needs a registry that says yes — and the
# cases that drive the two refusals blank or contradict these.
DRIVE_TAG="tree-stub00000000"
DRIVE_DIGEST_WEB="sha256:1111111111111111111111111111111111111111111111111111111111111111"
DRIVE_DIGEST_WORKER="sha256:2222222222222222222222222222222222222222222222222222222222222222"
N=0
fresh_deploy() {
    N=$((N + 1))
    CASE_DIR="${WORK}/case${N}"
    DEPLOY="${CASE_DIR}/deploy"
    DOCKER_LOG="${CASE_DIR}/docker.log"
    ALERTS_LOG="${CASE_DIR}/alerts.log"
    PIN_LOG="${CASE_DIR}/pin.log"
    mkdir -p "$DEPLOY/observability/alerts" "$CASE_DIR/bin"
    # Same reason as the docker log: "nothing was pinned" must be an empty file
    # rather than a missing one.
    : >"${CASE_DIR}/pin.log"
    # The box's TREE marker. `release.sh` pins into it only where one exists, so
    # its presence here is what makes the pin reachable at all — and the file's
    # FIRST LINE is the tag, per the grammar `deploy/provision.sh image_tag()`
    # declares.
    printf '%s\n' "$DRIVE_TAG" >"${CASE_DIR}/TREE"
    # Reset the registry's answers, so a case that blanked one cannot leak into
    # the next.
    DRIVE_DIGEST_WEB="sha256:1111111111111111111111111111111111111111111111111111111111111111"
    DRIVE_DIGEST_WORKER="sha256:2222222222222222222222222222222222222222222222222222222222222222"
    # Created empty, so "docker was never invoked" is an empty file rather than a
    # missing one — an absent file and zero invocations read the same to `wc`,
    # and only one of them is the property being asserted.
    : >"$DOCKER_LOG"

    cp "$SOURCE" "$DEPLOY/release.sh"
    chmod +x "$DEPLOY/release.sh"

    # The stub compose file. Only two things in it are read by release.sh: that
    # it exists, and the `postgres:` image pin the psql client version derives
    # from. The pin here is deliberately NOT the runbook's old hand-typed
    # `postgres:16.10`, so `case_the_psql_client_is_the_compose_pin` fails if the
    # value is ever typed back into the script.
    cat >"$DEPLOY/compose.yaml" <<'YAML'
services:
  db:
    image: postgres:18.6
  web:
    image: djb-web:tree-stub
YAML

    # Every host here is under `.invalid` (RFC 2606: guaranteed never to
    # resolve) and every password says what it is. The three `pragma` comments
    # are trailing shell comments, so they are invisible when the file is
    # sourced and visible to `detect-secrets`, which reads the line rather than
    # the value: a scanner cannot tell a fake password from a real one, and it
    # should not try.
    cat >"$DEPLOY/.env" <<'ENV'
COMPOSE_PROJECT_NAME='djb_deploy_stubbed'
SITE_ADDRESS='drive.invalid'
O11Y_ADDRESS='o11y.drive.invalid'
POSTGRES_USER='drive_master'
POSTGRES_PASSWORD='not-a-real-password'  # pragma: allowlist secret
DATABASE_USER='drive_app'
DATABASE_PASSWORD='not-a-real-password-either'  # pragma: allowlist secret
DATABASE_NAME='drive_db'
DATABASE_HOST='db.drive.invalid'
DATABASE_PORT='5432'
PGSSLMODE='require'
CLICKSTACK_ADMIN_EMAIL='operator@drive.invalid'
CLICKSTACK_ADMIN_PASSWORD='not-a-real-password-3'  # pragma: allowlist secret
SLACK_WEBHOOK_URL='https://hooks.drive.invalid/services/stub'
DJB_DEPLOY_NAMESPACE='drivenamespace'
PROBE_INSECURE='0'
PROBE_CONNECT_TO=''
ENV

    # THE STUB provision.sh. `project-name` is reached only when the env file
    # names no project; the five image arms are reached on EVERY run, because
    # build-once/promote-by-digest (ADR deploy-4) makes "does the registry have
    # the image this tree names" a precondition of every release.
    #
    # Each arm answers from a case knob, so a case can drive the registry's
    # answer without a registry: an empty digest knob IS "the registry has no
    # such tag" and is the exit 2 the real `image-digest` performs. `pin-digest`
    # records rather than writes, which is how a case asserts WHAT was pinned
    # without reading a file the real script would have rewritten.
    cat >"$DEPLOY/provision.sh" <<'PROVISION'
#!/usr/bin/env bash
service="${2:-}"
upper="$(printf '%s' "$service" | tr '[:lower:]' '[:upper:]')"
case "${1:-}" in
project-name) echo "djb_deploy_derived" ;;
image-tag)    echo "${DJB_DRIVE_IMAGE_TAG:-tree-stub00000000}" ;;
image-ref)    echo "${DJB_DRIVE_REGISTRY:-drive.invalid/ns}/djb-${service}:${3:-${DJB_DRIVE_IMAGE_TAG:-tree-stub00000000}}" ;;
image-digest)
    eval "answer=\${DJB_DRIVE_REGISTRY_DIGEST_${upper}:-}"
    if [ -z "$answer" ]; then
        echo "stub provision: the registry has no djb-${service} at that tag" >&2
        exit 2
    fi
    echo "$answer"
    ;;
tree-digest)
    eval "answer=\${DJB_DRIVE_TREE_PIN_${upper}:-}"
    [ -z "$answer" ] || echo "$answer"
    ;;
pin-digest)
    [ -z "${DJB_DRIVE_PIN_LOG:-}" ] || echo "$service ${3:-}" >>"$DJB_DRIVE_PIN_LOG"
    ;;
*) echo "stub provision: unexpected $*" >&2; exit 2 ;;
esac
PROVISION
    chmod +x "$DEPLOY/provision.sh"

    # The stub apply.py. It records the environment it was handed — which is how
    # `case_the_alerts_act_is_handed_the_sink_and_the_slot` sees that the sink
    # address and the webhook slot reached it — and exits with the case's code.
    cat >"$DEPLOY/observability/alerts/apply.py" <<'PY'
#!/usr/bin/env python3
import os
import sys

log = os.environ.get("DJB_DRIVE_ALERTS_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(f"CLICKSTACK_URL={os.environ.get('CLICKSTACK_URL', '')}\n")
        handle.write(f"SLACK_WEBHOOK_URL={os.environ.get('SLACK_WEBHOOK_URL', '')}\n")
        handle.write(f"CLICKSTACK_ADMIN_EMAIL={os.environ.get('CLICKSTACK_ADMIN_EMAIL', '')}\n")
print("[stub apply.py] reconciled")
sys.exit(int(os.environ.get("DJB_DRIVE_ALERTS_RC", "0")))
PY

    # THE STUB DOCKER, first on PATH. It records every invocation in order — the
    # log IS the sequence, which is what lets a case assert that nothing after a
    # failed act ran — classifies the invocation by what the release asked for,
    # and answers.
    cat >"$CASE_DIR/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_DOCKER_LOG"

what="unknown"
case "$*" in
*grants.sql.py*) what="grants-generate" ;;
*alerts/apply.py*) what="alerts-apply" ;;
*"manage.py integrations"*) what="integrations" ;;
*"manage.py migrate"*) what="migrate" ;;
*" psql "*) what="grants-apply" ;;
*readyz-prober*) what="readyz" ;;
*"up -d"*) what="recreate" ;;
# Kept AFTER the recreate arm on purpose: act 6 was once a `restart`, and a
# regression to it must show up in `acts_in_order` under its own name rather
# than as an unclassified `?` nobody can read.
*restart*) what="restart" ;;
esac

if [ "$what" = "${DJB_DRIVE_FAIL_ACT:-}" ]; then
    echo "stub docker: the case asked ${what} to fail" >&2
    exit "${DJB_DRIVE_FAIL_RC:-1}"
fi

case "$what" in
integrations)
    # The census's own shape: a row per integration, and `--wall` exits 1 when
    # one of them is not configured. The knob is what lets a case drive the
    # refusal without a deployment that is actually standing on a fake.
    echo "configured      object-storage - bucket drive-bucket answered a HEAD from this process."
    echo "configured      outbound-email - smtp - mail leaves this process."
    # THE ACCEPTANCE, as `manage.py integrations` performs it:
    # an accepted key is ANNOUNCED, every run, forever — and everything else in
    # the census is still a wall. What the real command does with the key is
    # `apps/core/tests/test_integrations.py`'s to prove; what is proven here is
    # that release.sh hands the key over at all, and that the announcement
    # reaches the release transcript rather than being swallowed by the act.
    prev=""
    for word in "$@"; do
        if [ "$prev" = "--accept-fake" ]; then
            echo "ACCEPTED FAKE  ${word} - a stand-in this operator named in the vault."
            echo "               remedy: point it at a real gateway."
        fi
        prev="$word"
    done
    if [ "${DJB_DRIVE_STALE_ACCEPTANCE:-}" = "1" ]; then
        # The acceptance named a key that is no longer FAKE. Exit 1, exactly as a
        # standing fake does: a stale acceptance is a slot the operator believes
        # is guarded and is not.
        echo "REFUSED: 1 acceptance(s) do not name a fake." >&2
        exit 1
    fi
    if [ "${DJB_DRIVE_FAKE_INTEGRATION:-}" = "1" ]; then
        echo "FAKE            outbound-email - console - mail is printed to stdout and never reaches anybody."
        echo "REFUSED: 1 integration(s) are not configured - outbound-email." >&2
        exit 1
    fi
    echo "All 2 integrations are configured."
    ;;
migrate) echo "Operations to perform: Apply all migrations. Running migrations: No migrations to apply." ;;
alerts-apply)
    # Act 5 runs as a one-off container beside the stack, so the ENVIRONMENT
    # apply.py is handed arrives here — in this stub's own environment, because
    # release.sh passes it in the `-e NAME` passthrough form and the value never
    # appears in argv. Recording it here is the same assertion the host-python
    # stub used to make, moved to where the invocation now happens.
    if [ -n "${DJB_DRIVE_ALERTS_LOG:-}" ]; then
        {
            echo "CLICKSTACK_URL=${CLICKSTACK_URL:-}"
            echo "SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL:-}"
            echo "CLICKSTACK_ADMIN_EMAIL=${CLICKSTACK_ADMIN_EMAIL:-}"
            echo "DJB_DEPLOY_NAMESPACE=${DJB_DEPLOY_NAMESPACE:-}"
        } >>"$DJB_DRIVE_ALERTS_LOG"
    fi
    echo "[stub apply.py, in-container] reconciled"
    exit "${DJB_DRIVE_ALERTS_RC:-0}"
    ;;
grants-generate)
    if [ "${DJB_DRIVE_EMPTY_GRANTS:-}" = "1" ]; then exit 0; fi
    echo "-- Generated by deploy/grants.sql.py. Do not edit; re-generate."
    echo 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "public" TO "drive_app";'
    echo 'REVOKE UPDATE, DELETE ON "core_auditentry" FROM "drive_app";'
    ;;
grants-apply)
    cat >/dev/null
    echo "GRANT"
    echo "REVOKE"
    ;;
readyz) printf '%s' "${DJB_DRIVE_READYZ_CODE:-200}" ;;
recreate) echo "Container djb-web-1  Recreated" ; echo "Container djb-worker-1  Recreated" ;;
restart) echo "Restarting web ... done" ;;
*) echo "stub docker: unclassified invocation: $*" >&2 ;;
esac
exit 0
DOCKER
    chmod +x "$CASE_DIR/bin/docker"
}

# Run something with the stub docker first on PATH and this case's knobs set.
# Leading `KEY=VALUE` arguments are the case's own knobs and are applied last, so
# a case can override a default. `env` rather than exports, so no knob survives
# into the next case; `env -u COMPOSE_PROJECT_NAME` because one case DELETES that
# name from the env file to reach the derivation, and a value inherited from the
# operator's own shell would silently answer for it.
#
# `-u DJB_IMAGE_TAG` for the same reason and it is not hypothetical: runbook
# steps 30, 33 and 2360 all say `export DJB_IMAGE_TAG="$(./deploy/provision.sh
# image-tag)"`, so an operator who ran the runbook in this shell has a REAL
# box's tag in the environment — and `release.sh` compares the interpolated
# value, so it would answer for an env file that names none. The cases that
# want a pin write one into the scratch `.env`, which is where compose reads
# it from.
#
# The readyz bound is two attempts, zero seconds apart: the length of the wait is
# the deployment's property and is argued in release.sh's header (recorded,
# never gated), while paying two real minutes per failing case would make this
# drive too expensive to run at push.
release() {
    local envs=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
        *=*)
            envs+=("$1")
            shift
            ;;
        *) break ;;
        esac
    done
    env -u COMPOSE_PROJECT_NAME -u DJB_IMAGE_TAG \
        PATH="${CASE_DIR}/bin:$PATH" \
        DJB_DRIVE_DOCKER_LOG="$DOCKER_LOG" \
        DJB_DRIVE_ALERTS_LOG="$ALERTS_LOG" \
        DJB_DRIVE_PIN_LOG="$PIN_LOG" \
        DJB_READYZ_ATTEMPTS=2 \
        DJB_READYZ_INTERVAL=0 \
        DJB_DRIVE_IMAGE_TAG="$DRIVE_TAG" \
        DJB_DRIVE_REGISTRY_DIGEST_WEB="$DRIVE_DIGEST_WEB" \
        DJB_DRIVE_REGISTRY_DIGEST_WORKER="$DRIVE_DIGEST_WORKER" \
        ${envs[@]+"${envs[@]}"} "$@"
}

docker_calls() { wc -l <"$DOCKER_LOG" | tr -d ' '; }
docker_saw() { grep -cF -- "$1" "$DOCKER_LOG" || true; }
acts_in_order() {
    # The classification the stub makes, in the order it made it — one word per
    # invocation, joined by spaces. The whole ordering property in one string.
    local out=""
    while IFS= read -r line; do
        case "$line" in
        *grants.sql.py*) out="$out grants-generate" ;;
        *alerts/apply.py*) out="$out alerts-apply" ;;
        *"manage.py integrations"*) out="$out integrations" ;;
        *"manage.py migrate"*) out="$out migrate" ;;
        *" psql "*) out="$out grants-apply" ;;
        *readyz-prober*) out="$out readyz" ;;
        *"up -d"*) out="$out recreate" ;;
        *restart*) out="$out restart" ;;
        *) out="$out ?" ;;
        esac
    done <"$DOCKER_LOG"
    printf '%s' "${out# }"
}

# =============================================================================
# The refusals — exit 2, and NOTHING ran
# =============================================================================

case_an_unknown_flag_is_refused() {
    fresh_deploy
    drive "unknown flag" 2 -- release "$DEPLOY/release.sh" --skip-grants
    says "unknown argument"
    holds "unknown flag: docker was never invoked" "0" "$(docker_calls)"
}

# The pipe refusal, in the deployment's vocabulary: you cannot filter the output
# of the thing whose exit status is the whole verdict.
case_a_piped_stdout_is_refused() {
    fresh_deploy
    drive "piped stdout" 2 -- release bash -c "set -o pipefail; '$DEPLOY/release.sh' | cat"
    says "refuses pipes"
    holds "piped stdout: docker was never invoked" "0" "$(docker_calls)"
}

case_a_missing_env_file_is_refused() {
    fresh_deploy
    rm -f "$DEPLOY/.env"
    drive "no env file" 2 -- release "$DEPLOY/release.sh"
    says "/.env"
    says "secrets-fetch"
    says "Nothing was released"
    holds "no env file: docker was never invoked" "0" "$(docker_calls)"
}

case_an_empty_required_slot_is_refused_before_the_first_act() {
    fresh_deploy
    # The slot every act after the first would have needed, emptied.
    sed -i.bak "s/^DATABASE_HOST=.*/DATABASE_HOST=''/" "$DEPLOY/.env"
    drive "empty required slot" 2 -- release "$DEPLOY/release.sh"
    says "DATABASE_HOST"
    says "Nothing was released"
    holds "empty required slot: docker was never invoked" "0" "$(docker_calls)"
}

# THE CENSUS'S OWN POINT, as a refusal. The alert route is the act most easily
# left out, so leaving it out has to be a sentence somebody types.
case_missing_alert_credentials_are_a_refusal_not_a_skip() {
    fresh_deploy
    sed -i.bak "s/^CLICKSTACK_ADMIN_PASSWORD=.*/CLICKSTACK_ADMIN_PASSWORD=''/" "$DEPLOY/.env"
    drive "alerts credentials missing" 2 -- release "$DEPLOY/release.sh"
    says "REFUSED"
    says "CLICKSTACK_ADMIN_PASSWORD"
    says "--without-alerts"
    says "Nothing was released"
    holds "alerts credentials missing: docker was never invoked" "0" "$(docker_calls)"
}

case_an_unreadable_postgres_pin_is_refused() {
    fresh_deploy
    cat >"$DEPLOY/compose.yaml" <<'YAML'
services:
  web:
    image: djb-web:tree-stub
YAML
    drive "no postgres pin" 2 -- release "$DEPLOY/release.sh"
    says "postgres image pin"
    holds "no postgres pin: docker was never invoked" "0" "$(docker_calls)"
}

case_a_missing_apply_py_is_refused_before_the_first_act() {
    fresh_deploy
    rm -f "$DEPLOY/observability/alerts/apply.py"
    drive "no apply.py" 2 -- release "$DEPLOY/release.sh"
    says "apply.py"
    says "Nothing was released"
    holds "no apply.py: docker was never invoked" "0" "$(docker_calls)"
}

# =============================================================================
# The clean run
# =============================================================================

case_a_clean_release_performs_seven_acts_in_order() {
    fresh_deploy
    drive "clean release" 0 -- release "$DEPLOY/release.sh"
    says "[1/7]"
    says "[2/7]"
    says "[3/7]"
    says "[4/7]"
    says "[5/7]"
    says "[6/7]"
    says "[7/7]"
    says "RELEASED. 7/7 acts complete."
    # The good half of the step this replaced was "generate the release SQL AND
    # READ IT". The SQL reaches the operator's eyes, or the instruction was lost
    # in the demotion.
    says 'REVOKE UPDATE, DELETE ON "core_auditentry"'
    # THE ORDERING PROPERTY, and it is the half this script owns: the
    # schema is migrated before anything is restarted, in one string.
    holds "clean release: the acts happened in the declared order" \
        "integrations migrate grants-generate grants-apply alerts-apply recreate readyz" \
        "$(acts_in_order)"
}

case_the_psql_client_is_the_compose_pin() {
    fresh_deploy
    drive "psql client derived" 0 -- release "$DEPLOY/release.sh"
    holds "the psql client is compose's own postgres pin" "1" "$(docker_saw 'postgres:18.6')"
    holds "the psql client is not the runbook's old hand-typed 16.10" "0" "$(docker_saw 'postgres:16.10')"
}

# THE MIGRATE ACT'S WALL. The migrate is the one act of a deploy whose length
# is the schema's and not the script's, and the closing line `stage.sh` prints
# carries it — so the release prints it, on its own line, under act 2 and
# before act 3, as `migrate: <n>s`.
case_the_migrate_act_prints_its_wall() {
    fresh_deploy
    drive "the migrate wall" 0 -- release "$DEPLOY/release.sh"
    local at2 wall at3
    at2="$(grep -n '^release: \[2/7\]' "$DRIVE_OUT" | sed -n '1s/:.*//p' || true)"
    wall="$(grep -nE '^release: migrate: [0-9]+s$' "$DRIVE_OUT" | sed -n '1s/:.*//p' || true)"
    at3="$(grep -n '^release: \[3/7\]' "$DRIVE_OUT" | sed -n '1s/:.*//p' || true)"
    holds "the migrate wall is printed exactly once" "1" \
        "$(grep -cE '^release: migrate: [0-9]+s$' "$DRIVE_OUT" || true)"
    if [ -n "$at2" ] && [ -n "$wall" ] && [ -n "$at3" ] && [ "$at2" -lt "$wall" ] && [ "$wall" -lt "$at3" ]; then
        echo "  ok       the migrate wall sits under act 2 (line ${wall}, between ${at2} and ${at3})"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   the migrate wall is not between act 2 and act 3 (act 2 ${at2:-never}, wall ${wall:-never}, act 3 ${at3:-never})"
        FAILED=$((FAILED + 1))
    fi
    # A dry run migrated nothing, so it has no wall to print.
    fresh_deploy
    drive "the dry run has no migrate wall" 0 -- release "$DEPLOY/release.sh" --dry-run
    says_not "release: migrate: "
}

# THE PSQL CLIENT CARRIES THE COMPOSE LINE'S DIGEST. The db service is pinned
# `postgres:<version>@sha256:<64 hex>` (house rule 61), and a client pulled by
# the tag alone is a client the registry may answer differently tomorrow.
case_the_psql_client_carries_the_compose_digest() {
    fresh_deploy
    local digest="sha256:5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a5a"
    cat >"$DEPLOY/compose.yaml" <<YAML
services:
  db:
    image: postgres:18.6@${digest}
  web:
    image: djb-web:tree-stub
YAML
    drive "psql client pinned by digest" 0 -- release "$DEPLOY/release.sh"
    holds "the psql client is pulled by the compose line's digest" "1" \
        "$(docker_saw "postgres:18.6@${digest}")"
    fresh_deploy
    cat >"$DEPLOY/compose.yaml" <<YAML
services:
  db:
    image: postgres:18.6@${digest}
YAML
    drive "the dry run names the pinned client" 0 -- release "$DEPLOY/release.sh" --dry-run
    says "psql client  postgres:18.6@${digest}"
}

# The project name comes from the env file, which is where
# `provision.sh up` writes the ADOPTED name on a box.
case_the_network_is_the_env_files_project() {
    fresh_deploy
    drive "project from the env file" 0 -- release "$DEPLOY/release.sh"
    holds "the psql container joins the env file's project network" "1" \
        "$(docker_saw '--network djb_deploy_stubbed_default')"
}

case_the_project_falls_back_to_the_derivation() {
    fresh_deploy
    sed -i.bak "/^COMPOSE_PROJECT_NAME=/d" "$DEPLOY/.env"
    drive "project from the derivation" 0 -- release "$DEPLOY/release.sh"
    holds "with no name in the env file the derivation is used" "1" \
        "$(docker_saw '--network djb_deploy_derived_default')"
}

case_the_alerts_act_is_handed_the_sink_and_the_slot() {
    fresh_deploy
    drive "alerts act environment" 0 -- release "$DEPLOY/release.sh"
    # The sink address is the IN-NETWORK one — `O11Y_ADDRESS` names
    # the walled public address and is no longer derived from here at all. The
    # case below (`…runs_in_container_on_the_stack_network`) is the one that
    # holds that line; this one holds that the act is handed an environment.
    holds "apply.py was handed the sink address" "1" \
        "$(grep -cF 'CLICKSTACK_URL=http://clickstack:8080' "$ALERTS_LOG" || true)"
    holds "apply.py was handed the webhook slot's value" "1" \
        "$(grep -cF 'SLACK_WEBHOOK_URL=https://hooks.drive.invalid' "$ALERTS_LOG" || true)"
    # AND THE NAMESPACE, ASSERTED ON THE ARGV RATHER THAN ON THE ENVIRONMENT.
    # apply.py composes the alert bundle's name and the slot it names from
    # `DJB_DEPLOY_NAMESPACE` and REFUSES when it is unset, so a passthrough list
    # that omitted it would refuse on every box with the value sitting right
    # there in `deploy/.env`.
    #
    # THE ENVIRONMENT CANNOT SEE THAT, and the drive found it out: the stub
    # docker is a bash script, so it inherits everything release.sh's own
    # `set -a; . deploy/.env` exported and the variable arrives whether or not
    # it was passed. That is the stub's declared limit (control flow, not
    # containment) showing up as a vacuous assertion. The argv is the thing a
    # real `docker run` would actually carry, so that is what is pinned.
    holds "act 5 passes the namespace through to the container" "1" \
        "$(docker_saw '-e DJB_DEPLOY_NAMESPACE')"
}

# The sink's public address is behind Caddy's basic-auth wall, the
# wall's plaintext is printed once at env-file time and STORED NOWHERE (only the
# bcrypt hash exists), and `apply.py` sends no basic auth — so as long as act 5
# aimed at `https://${O11Y_ADDRESS}` it could not succeed on any box, and the
# only credential that would have made it succeed is one nobody may mint. The
# ruling is that the act goes to the sink the way every other act goes to the
# database: from INSIDE the stack, where the wall is not in the path at all.
#
# Both halves are asserted, because either alone can pass while the defect
# stands: that the invocation is a one-off container on the project's network,
# and that the address it carries is the service name rather than the public
# one.
case_the_alerts_act_runs_in_container_on_the_stack_network() {
    fresh_deploy
    drive "alerts in-container" 0 -- release "$DEPLOY/release.sh"
    # `--no-deps` is GONE from the invocation and that is the fix, not a
    # regression: the `oneoff` service declares no dependencies, so the property
    # moved from a flag a caller can forget into the compose file. What is
    # asserted is the one-off container AND the door it lands on.
    holds "act 5 ran apply.py in a one-off container beside the stack" "1" \
        "$(grep -cE 'run --rm.*alerts/apply\.py' "$DOCKER_LOG" || true)"
    # All four one-off acts — 1, 2, 3 and 5 — land on the bounded door.
    holds "every one-off act runs as the bounded door" "4" \
        "$(docker_saw 'oneoff python')"
    holds "no act reserves web's pool for a one-off" "0" \
        "$(grep -cE 'run .*[[:space:]]web[[:space:]]' "$DOCKER_LOG" || true)"
    holds "act 5 named the image's own copy of apply.py" "1" \
        "$(docker_saw '/app/deploy/observability/alerts/apply.py')"
    holds "the sink is the in-network service address" "1" \
        "$(grep -cF 'CLICKSTACK_URL=http://clickstack:8080' "$ALERTS_LOG" || true)"
    holds "the operator credentials still reach the act" "1" \
        "$(grep -cF 'CLICKSTACK_ADMIN_EMAIL=operator@drive.invalid' "$ALERTS_LOG" || true)"
    # THE ABSENT CASE. A fallback to the walled public address is the defect,
    # so it is asserted absent from both the transcript and the act's own
    # environment — not merely "the good value is present too".
    says_not "https://o11y.drive.invalid"
    holds "the walled public address never reaches the act" "0" \
        "$(grep -cF 'o11y.drive.invalid' "$ALERTS_LOG" || true)"
}

# Closed by the same move rather than by a flag. Act 5 used to run
# `python3 deploy/observability/alerts/apply.py` on the BOX's interpreter, which
# wrote five `__pycache__` files into the shipped tree — so the file set on the
# box stopped equalling the archive manifest the moment the first release ran,
# and `ship.sh`'s landed-file census had a permanent, meaningless delta.
# `PYTHONDONTWRITEBYTECODE=1` was the row's own fallback; running no host python
# at all is the durable answer, and this is the property that says so.
case_the_release_runs_no_host_python_against_the_tree() {
    fresh_deploy
    # A stub `python` and `python3` first on PATH, recording every invocation.
    # An empty log is created up front for `fresh_deploy`'s own reason: a
    # missing file and zero invocations read the same to `wc`.
    local pylog="${CASE_DIR}/python.log"
    : >"$pylog"
    local name
    for name in python python3; do
        {
            echo '#!/usr/bin/env bash'
            echo 'printf "%s\n" "$*" >>"$DJB_DRIVE_PYTHON_LOG"'
            echo 'exit 0'
        } >"${CASE_DIR}/bin/${name}"
        chmod +x "${CASE_DIR}/bin/${name}"
    done
    drive "no host python" 0 -- release DJB_DRIVE_PYTHON_LOG="$pylog" \
        "$DEPLOY/release.sh"
    holds "the release invoked no host python at all" "0" \
        "$(wc -l <"$pylog" | tr -d ' ')"
}

# The release half of the same window. Act 6 was `compose restart web worker`,
# and a restart
# cannot change the image a container runs — so once the runbook's step 34 stops
# recreating the app pair (which is what closes the window), a restart would
# leave the box serving the PREVIOUS tree forever with nothing anywhere saying
# so. The recreate has to move here, after act 2's migrate, or the window is
# closed by breaking the deploy.
case_act_six_recreates_the_app_rather_than_restarting_it() {
    fresh_deploy
    drive "act six recreates" 0 -- release "$DEPLOY/release.sh"
    says "[6/7] recreate"
    holds "act 6 brought the app pair up onto the new image" "1" \
        "$(docker_saw 'up -d --no-deps web worker')"
    holds "act 6 is not a restart — a restart cannot change the image" "0" \
        "$(docker_saw 'restart web worker')"
}

case_the_readyz_probe_carries_the_probers_own_posture() {
    fresh_deploy
    sed -i.bak "s/^PROBE_INSECURE=.*/PROBE_INSECURE='1'/" "$DEPLOY/.env"
    sed -i.bak "s|^PROBE_CONNECT_TO=.*|PROBE_CONNECT_TO='localhost:443:caddy:443'|" "$DEPLOY/.env"
    drive "readyz probe posture" 0 -- release "$DEPLOY/release.sh"
    holds "the probe skips verification exactly when the prober does" "1" "$(docker_saw ' -k ')"
    holds "the probe carries the prober's --connect-to" "1" \
        "$(docker_saw '--connect-to localhost:443:caddy:443')"
    holds "the probe target is the prober's target" "1" \
        "$(docker_saw 'https://drive.invalid/readyz')"
}

case_without_alerts_skips_exactly_one_act_and_says_so() {
    fresh_deploy
    drive "--without-alerts" 0 -- release "$DEPLOY/release.sh" --without-alerts
    says "[5/7]"
    says "SKIPPED"
    says "typed on purpose"
    says "RELEASED"
    holds "--without-alerts: apply.py never ran" "no" \
        "$([ -f "$ALERTS_LOG" ] && echo yes || echo no)"
    holds "--without-alerts: the other six acts still happened" \
        "integrations migrate grants-generate grants-apply recreate readyz" "$(acts_in_order)"
}

case_dry_run_touches_nothing() {
    fresh_deploy
    drive "--dry-run" 0 -- release "$DEPLOY/release.sh" --dry-run
    says "DRY RUN"
    says "nothing was touched."
    says_not "RELEASED"
    holds "--dry-run: docker was never invoked" "0" "$(docker_calls)"
    holds "--dry-run: apply.py never ran" "no" \
        "$([ -f "$ALERTS_LOG" ] && echo yes || echo no)"
}

# =============================================================================
# The failures — exit 1, the act NAMED, and nothing after it
# =============================================================================

case_a_fake_integration_stops_the_release_before_anything_changed() {
    # THE WALL, driven. A production release that reaches the console mail
    # backend, `FakeSmsChannel` or a bucket nobody can reach is a deployment
    # whose password resets, consent signals and uploads all SUCCEED and go
    # nowhere — the fake that succeeds, which is the whole failure class the
    # integrations census exists for.
    #
    # The two halves this asserts are the two the wall is worth: the release
    # stops, and it stops at act ONE, with NOTHING migrated, granted, reconciled
    # or restarted. A wall that refused after the migration would still be
    # right about the fake and would have already changed the world.
    fresh_deploy
    drive "a fake integration" 1 -- release DJB_DRIVE_FAKE_INTEGRATION=1 \
        "$DEPLOY/release.sh"
    says "STOPPED at act 1/7 — integrations"
    says "No act after this one ran."
    says_not "RELEASED"
    holds "the wall: nothing but the census ran" "integrations" "$(acts_in_order)"
}

case_an_unreadable_seam_stops_the_release_with_its_own_code() {
    # Exit 2 out of `manage.py integrations` is "a seam could not be read", not
    # "the seam is empty". It stops the release exactly as a fake does, and the
    # NUMBER is reported verbatim — the `apply.py` precedent — so an operator
    # can tell "this deployment is standing on a fake" from "this deployment
    # cannot tell you what it is standing on" without re-running anything.
    fresh_deploy
    drive "an unreadable seam" 1 -- release DJB_DRIVE_FAIL_ACT=integrations DJB_DRIVE_FAIL_RC=2 \
        "$DEPLOY/release.sh"
    says "STOPPED at act 1/7 — integrations (exit 2)"
    says_not "RELEASED"
    holds "an unreadable seam: nothing but the census ran" "integrations" "$(acts_in_order)"
}

case_a_failed_migrate_stops_at_act_one() {
    fresh_deploy
    drive "migrate fails" 1 -- release DJB_DRIVE_FAIL_ACT=migrate DJB_DRIVE_FAIL_RC=1 \
        "$DEPLOY/release.sh"
    says "STOPPED at act 2/7 — migrate"
    says "No act after this one ran."
    says "RE-RUN THIS SCRIPT FROM THE TOP"
    says_not "RELEASED"
    holds "migrate fails: nothing after it ran" "integrations migrate" "$(acts_in_order)"
}

case_an_empty_generated_sql_stops_at_act_two() {
    fresh_deploy
    drive "empty grants SQL" 1 -- release DJB_DRIVE_EMPTY_GRANTS=1 \
        "$DEPLOY/release.sh"
    says "STOPPED at act 3/7 — grants generate"
    says_not "RELEASED"
    holds "empty grants SQL: the apply never ran" "integrations migrate grants-generate" "$(acts_in_order)"
}

# THE ONE THE CENSUS PRICED. A failed grants apply must not be followed by a
# restart that puts the new code in front of the wrong privileges.
case_a_failed_grants_apply_stops_at_act_three() {
    fresh_deploy
    drive "grants apply fails" 1 -- release DJB_DRIVE_FAIL_ACT=grants-apply DJB_DRIVE_FAIL_RC=3 \
        "$DEPLOY/release.sh"
    says "STOPPED at act 4/7 — grants apply (exit 3)"
    says_not "RELEASED"
    holds "grants apply fails: no alerts, no recreate, no probe" \
        "integrations migrate grants-generate grants-apply" "$(acts_in_order)"
}

# apply.py's own exit codes are reported verbatim: 3 is "the census raised a
# warning; fix the declaration first" and must not be flattened to 1.
case_a_failed_alerts_apply_stops_at_act_four_with_its_own_code() {
    fresh_deploy
    drive "alerts apply fails" 1 -- release DJB_DRIVE_ALERTS_RC=3 \
        "$DEPLOY/release.sh"
    says "STOPPED at act 5/7 — alerts apply (exit 3)"
    says_not "RELEASED"
    holds "alerts apply fails: no recreate, no probe" \
        "integrations migrate grants-generate grants-apply alerts-apply" "$(acts_in_order)"
}

case_a_failed_recreate_stops_at_act_five() {
    fresh_deploy
    drive "recreate fails" 1 -- release DJB_DRIVE_FAIL_ACT=recreate DJB_DRIVE_FAIL_RC=1 \
        "$DEPLOY/release.sh"
    says "STOPPED at act 6/7 — recreate"
    says_not "RELEASED"
    holds "recreate fails: the probe never ran" \
        "integrations migrate grants-generate grants-apply alerts-apply recreate" \
        "$(acts_in_order)"
}

# The act that turns "the commands ran" into "the deployment answers". A release
# whose last act is `restart` reports success over a crash loop.
case_a_deployment_that_never_becomes_ready_is_a_failed_release() {
    fresh_deploy
    drive "never ready" 1 -- release DJB_DRIVE_READYZ_CODE=503 \
        "$DEPLOY/release.sh"
    says "did not answer 200"
    says "the deployment is not serving"
    says "last answer: 503"
    says_not "RELEASED"
    holds "never ready: the probe was tried the declared number of times" "2" "$(docker_saw 'readyz-prober')"
}

# =============================================================================
# The acceptance slot
# =============================================================================
#
# `DJB_ACCEPTED_FAKES` is a vault-managed string in `deploy/.env`. This script
# expands it into `--accept-fake <key>` arguments and does NOTHING else with it:
# every judgment about whether a key may be accepted is the census command's,
# because release.sh reading the census's human-readable report to decide would
# be filtering the output of a thing whose exit status is the verdict.

case_an_empty_acceptance_slot_is_the_whole_wall() {
    # The default, and the one that must never quietly widen. A deployment that
    # names nothing gets the wall exactly as it was before this flag existed.
    fresh_deploy
    drive "no acceptance slot" 0 -- release "$DEPLOY/release.sh"
    holds "an empty slot passes no acceptance at all" "0" "$(docker_saw '--accept-fake')"
    says_not "ACCEPTED FAKE"
}

case_an_accepted_fake_proceeds_past_act_one_and_says_so() {
    fresh_deploy
    sed -i.bak "\$a\\
DJB_ACCEPTED_FAKES='stub-standin-a'
" "$DEPLOY/.env"
    drive "one accepted fake" 0 -- release "$DEPLOY/release.sh"
    holds "the key reached the census command" "1" "$(docker_saw '--accept-fake stub-standin-a')"
    # PERMANENT LOUDNESS. The announcement is worth exactly as much as its
    # reaching the transcript: an acceptance nobody sees is the silent fake with
    # a permission slip.
    says "ACCEPTED FAKE"
    says "stub-standin-a"
    says "RELEASED"
    says "stood on 1 accepted fake(s)"
}

case_two_accepted_fakes_are_two_flags_in_order() {
    fresh_deploy
    sed -i.bak "\$a\\
DJB_ACCEPTED_FAKES='stub-standin-a stub-standin-b'
" "$DEPLOY/.env"
    drive "two accepted fakes" 0 -- release "$DEPLOY/release.sh"
    holds "the first key reached the command" "1" "$(docker_saw '--accept-fake stub-standin-a')"
    holds "the second key reached the command" "1" "$(docker_saw '--accept-fake stub-standin-b')"
    says "stood on 2 accepted fake(s)"
}

case_an_accepted_fake_beside_an_unaccepted_one_still_stops_at_act_one() {
    # THE PROPERTY THE RULING RESTS ON: acceptance is not a mode. A deployment
    # that named one stand-in and grew a second is refused again, and it is
    # refused at act ONE with nothing migrated, granted or restarted.
    fresh_deploy
    sed -i.bak "\$a\\
DJB_ACCEPTED_FAKES='stub-standin-a'
" "$DEPLOY/.env"
    drive "accepted plus unaccepted" 1 -- release DJB_DRIVE_FAKE_INTEGRATION=1 \
        "$DEPLOY/release.sh"
    says "ACCEPTED FAKE"
    says "STOPPED at act 1/7 — integrations"
    says "No act after this one ran."
    says_not "RELEASED"
    holds "a second fake: nothing but the census ran" "integrations" "$(acts_in_order)"
}

case_a_stale_acceptance_stops_at_act_one() {
    # The acceptance names a key that is no longer FAKE. It is refused rather
    # than ignored, because an acceptance left standing over a now-real
    # integration is a slot the operator believes is guarded and is not.
    fresh_deploy
    sed -i.bak "\$a\\
DJB_ACCEPTED_FAKES='stub-standin-a'
" "$DEPLOY/.env"
    drive "a stale acceptance" 1 -- release DJB_DRIVE_STALE_ACCEPTANCE=1 \
        "$DEPLOY/release.sh"
    holds "the stale key was handed over rather than filtered here" "1" \
        "$(docker_saw '--accept-fake stub-standin-a')"
    says "STOPPED at act 1/7 — integrations"
    says_not "RELEASED"
    holds "a stale acceptance: nothing but the census ran" "integrations" "$(acts_in_order)"
}

case_the_dry_run_names_the_acceptance_without_touching_anything() {
    fresh_deploy
    sed -i.bak "\$a\\
DJB_ACCEPTED_FAKES='stub-standin-a'
" "$DEPLOY/.env"
    drive "--dry-run with an acceptance" 0 -- release "$DEPLOY/release.sh" --dry-run
    says "stub-standin-a"
    says "nothing was touched."
    holds "--dry-run with an acceptance: docker was never invoked" "0" "$(docker_calls)"
}

# =============================================================================
# The alert route's two questions
# =============================================================================
#
# `SLACK_WEBHOOK_URL` and the ClickStack operator pair answer DIFFERENT
# questions and were lumped into one refusal. The pair is DEFERRED (the account
# does not exist until a human completes the sink's first-run setup); the webhook
# is a route with nowhere to deliver, on a box whose sink may be perfectly up.
# Both still refuse before any act; the sentences are no longer interchangeable.

case_an_empty_webhook_slot_refuses_in_its_own_words() {
    fresh_deploy
    sed -i.bak "s|^SLACK_WEBHOOK_URL=.*|SLACK_WEBHOOK_URL=''|" "$DEPLOY/.env"
    drive "empty webhook slot" 2 -- release "$DEPLOY/release.sh"
    says "REFUSED"
    says "SLACK_WEBHOOK_URL"
    says "nowhere to deliver"
    says "route unreconciled"
    says "Nothing was released"
    # THE LUMPING, AS AN ABSENCE. The deferred-credentials sentences are about an
    # account that does not exist yet; on a box whose sink is up and keyed they
    # are false, and a refusal that says something false is a refusal that
    # teaches the operator to stop reading refusals.
    says_not "step 53"
    says_not "no sink yet"
    holds "empty webhook slot: docker was never invoked" "0" "$(docker_calls)"
}

case_the_deferred_clickstack_pair_keeps_its_own_message() {
    fresh_deploy
    sed -i.bak "s/^CLICKSTACK_ADMIN_EMAIL=.*/CLICKSTACK_ADMIN_EMAIL=''/" "$DEPLOY/.env"
    drive "deferred sink credentials" 2 -- release "$DEPLOY/release.sh"
    says "REFUSED"
    says "CLICKSTACK_ADMIN_EMAIL"
    says "step 53"
    says "no sink yet"
    says_not "nowhere to deliver"
    holds "deferred sink credentials: docker was never invoked" "0" "$(docker_calls)"
}

case_without_alerts_still_releases_with_an_empty_webhook_slot() {
    # The escape still works, and it is the same sentence typed on purpose — but
    # what it MEANS on this box is "the route is unreconciled", not "there is no
    # sink". The refusal above is where that distinction is made; here it is only
    # that the escape is not blocked by the new precondition.
    fresh_deploy
    sed -i.bak "s|^SLACK_WEBHOOK_URL=.*|SLACK_WEBHOOK_URL=''|" "$DEPLOY/.env"
    drive "--without-alerts, empty webhook" 0 -- release "$DEPLOY/release.sh" --without-alerts
    says "[5/7]"
    says "SKIPPED"
    says "RELEASED"
}

# =============================================================================
# The pins and the transcript — read off the REAL tree, not the stub
# =============================================================================

case_the_meili_pin_is_the_root_composes_own() {
    # C4. Two compose files, one engine, and a drift between them is a staging
    # box proving a version the laptop never ran. Read from both files rather
    # than typed here, so this cannot pass by agreeing with itself.
    local root deploy
    root="$(sed -n 's|^[[:space:]]*image:[[:space:]]*\(getmeili/meilisearch:[^[:space:]]*\).*|\1|p' compose.yaml | head -n1)"
    deploy="$(sed -n 's|^[[:space:]]*image:[[:space:]]*\(getmeili/meilisearch:[^[:space:]]*\).*|\1|p' deploy/compose.yaml | head -n1)"
    if [ -z "$root" ]; then
        echo "  FAILED   the meili pin — compose.yaml declares no getmeili image"
        FAILED=$((FAILED + 1))
        return
    fi
    holds "deploy/compose.yaml pins the same engine the laptop runs" "$root" "$deploy"
}

# =============================================================================
# The compose-run census, and why it is a census rather than a list
# =============================================================================
#
# `compose run --rm web python manage.py …` inherits the `web` service's
# environment, `DJB_SERVICE_NAME=web` included, so the settings module derives a
# pool of TWENTY for a command that wants two. On a loaded box that meant no
# slots left: `revoke_token` PoolTimeout'd with zero free, and release acts 1, 2,
# 3 and 5 are the same shape — a release refused by its own box's load,
# recovered only by a force-recreate, and it recurs until the door exists.
#
# The fix is a dedicated `oneoff` service (`deploy/compose.yaml`) plus
# `"oneoff": 2` in `config/settings/base.py`'s pool map. What THIS case buys is
# that the fix stays applied: the set of one-off invocations is OPEN — four
# release acts, seventeen runbook lines, and every command anybody adds later —
# and a single forgotten `oneoff` silently reserves twenty slots again with
# nothing anywhere saying so. A hand list of call sites is the checklist's
# most-recurrent miss shape; a census over the population is a closed question.
#
# IT READS THE SERVICE POSITION, NOT THE WORD. A grep for `web` matches prose,
# and it matches `compose exec web`, which is a different act. This parses the
# invocation the way compose does: the subcommand is the first bare token after
# `compose` (its value-taking global flags skipped), and the SERVICE is the first
# bare token after `run` (its value-taking flags skipped). That is the argument
# which decides which image — and therefore which `DJB_SERVICE_NAME` — a one-off
# inherits, so it is the argument the census reads.
#
# WHAT IT DOES NOT COVER, declared:
#
#   * `docker compose exec web …`. Attaching to the RUNNING web container is a
#     different act with a different failure mode (it cannot be moved to a
#     service that is never `up`), and `oneoff` is not a place to exec into.
#     `docs/runbooks/deploy.md` still carries two of those deliberately.
#   * A COMMAND SOMEBODY TYPES ON THE BOX. Nothing in a repository can see an
#     operator hand-typing `run --rm web`; the teachable surface is the runbook
#     paragraph beside the first one-off, which names `oneoff` and says why.
#   * A SERVICE ADDED LATER that should also be off-limits. The refused set is
#     named here — `web` and `worker` — and grows by editing this line.
census_compose_run_services() {
    # Joins backslash continuations first: three of the sites this was written
    # against put the service name on the line AFTER the `run`, and a
    # line-at-a-time reader scores those green while they are red.
    awk '
    BEGIN {
        split("-p --project-name -f --file --env-file --profile --project-directory --parallel --progress --ansi", g, " ")
        for (i in g) if (g[i] != "") GLOBAL[g[i]] = 1
        split("-e --env -v --volume -w --workdir -u --user -l --label -p --publish --name --entrypoint", r, " ")
        for (i in r) if (r[i] != "") RUNFLAG[r[i]] = 1
    }
    {
        if (buf == "") { start = FNR; buf = $0 } else { buf = buf " " $0 }
        if (buf ~ /\\[[:space:]]*$/) { sub(/\\[[:space:]]*$/, " ", buf); next }
        line = buf; buf = ""
        n = split(line, t, /[[:space:]]+/)
        at = 0
        for (i = 1; i <= n; i++) {
            # `docker compose …`, or the bare `compose` shell helper
            # deploy/release.sh defines for itself.
            if (t[i] == "docker" && t[i+1] == "compose") { at = i + 2; break }
            if (t[i] == "compose") { at = i + 1; break }
        }
        if (at == 0) next
        sub_ = ""
        for (i = at; i <= n; i++) {
            tok = t[i]
            if (tok == "") continue
            # An elided command in a runbook example ("compose -p x ... run") is
            # still an invocation somebody copies; the ellipsis is skipped
            # rather than mistaken for the subcommand.
            if (tok == "..." || tok == "\xe2\x80\xa6") continue
            if (tok ~ /^-/) { if (tok !~ /=/ && (tok in GLOBAL)) i++; continue }
            sub_ = tok; at = i + 1; break
        }
        if (sub_ != "run") next
        svc = ""
        for (i = at; i <= n; i++) {
            tok = t[i]
            if (tok == "") continue
            if (tok ~ /^-/) { if (tok !~ /=/ && (tok in RUNFLAG)) i++; continue }
            svc = tok; break
        }
        if (svc == "web" || svc == "worker")
            printf "%s:%d: `compose run` names `%s`\n", FILENAME, start, svc
    }' "$@"
}

case_no_one_off_runs_as_web_or_worker() {
    local population found count
    # The population is DISCOVERED, not listed: every runbook, plus the release
    # script. A runbook added tomorrow is censused the day it lands.
    population=(deploy/release.sh docs/runbooks/*.md)
    if [ "${#population[@]}" -lt 2 ]; then
        echo "  FAILED   the compose-run census — found no runbooks to read"
        FAILED=$((FAILED + 1))
        return
    fi
    found="$(census_compose_run_services "${population[@]}" || true)"
    count="$(printf '%s' "$found" | grep -c . || true)"
    if [ "$count" = "0" ]; then
        echo "  ok       the compose-run census — ${#population[@]} files, no one-off runs as web or worker"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   the compose-run census — ${count} one-off(s) still name web or worker"
        printf '%s\n' "$found" | sed 's/^/             | /'
        echo "             | Move the service argument to \`oneoff\` (deploy/compose.yaml)."
        echo "             | A one-off that runs as web derives a pool of 20 and can be"
        echo "             | refused on a loaded box."
        FAILED=$((FAILED + 1))
    fi
}

# THE CENSUS IS ITSELF PROVEN, both directions, because a census that cannot fire
# is worse than no census: it reads green forever and nobody looks again. A
# planted victim, never found state (rung-execution §2).
case_the_compose_run_census_can_actually_fire() {
    local victim
    victim="${WORK}/planted-runbook.md"
    cat >"$victim" <<'MD'
Prose that says the word web, and mentions docker compose run in a sentence.
```bash
docker compose -f deploy/compose.yaml run --rm -T web python manage.py migrate
docker compose -f deploy/compose.yaml run --rm -T -e A -e B worker python -c pass
docker compose -f deploy/compose.yaml exec web uv run python manage.py shell
docker compose -f deploy/compose.yaml run --rm -T oneoff python manage.py migrate
docker compose -f deploy/compose.yaml \
  run --rm -T \
  web python manage.py check --deploy
docker compose -p djb-b1a ... run --rm -T web python manage.py introspect
MD
    # The victim's lines, so the assertions below can name them:
    #   1  prose containing the words "compose", "run" and "web"   -> silent
    #   3  run … web                                               -> FIRES
    #   4  run … -e A -e B worker                                  -> FIRES
    #   5  compose exec web                                        -> silent
    #   6  run … oneoff                                            -> silent
    #   7  run … web, the service on a CONTINUATION line           -> FIRES at 7
    #   10 run … web behind an elided flag list                    -> FIRES
    holds "the census fires on a planted run-as-web" "4" \
        "$(census_compose_run_services "$victim" | grep -c . || true)"
    holds "the census is silent on \`exec\`, on prose, and on oneoff" "0" \
        "$(census_compose_run_services "$victim" | grep -cE ':1:|:5:|:6:' || true)"
    # And the line numbers are real, so a failure can be acted on without a grep.
    holds "the census names the continued invocation by its FIRST line" "1" \
        "$(census_compose_run_services "$victim" | grep -c ':7:' || true)"
    holds "the census sees through an elided flag list" "1" \
        "$(census_compose_run_services "$victim" | grep -c ':10:' || true)"
}

case_the_runbook_documents_as_many_acts_as_the_script_performs() {
    # C7. The runbook said "Six acts" while the script performed seven, and the
    # transcript it printed was the six-act one — the exact shape of a document
    # that stops being read. The count is DERIVED from the script's own ACTS
    # array, so an eighth act reddens the runbook rather than being noticed.
    local total i
    total="$(
        awk '/^ACTS=\(/{inside=1;next} inside&&/^\)/{exit} inside&&/^ *"/{n++} END{print n+0}' \
            deploy/release.sh
    )"
    if [ "$total" -lt 2 ]; then
        echo "  FAILED   the act count — could not read the ACTS array out of deploy/release.sh"
        FAILED=$((FAILED + 1))
        return
    fi
    holds "the runbook names the script's own act count" "1" \
        "$(grep -cF "${total} acts" docs/runbooks/deploy.md || true)"
    i=0
    while [ "$i" -lt "$total" ]; do
        i=$((i + 1))
        holds "the runbook's transcript carries [${i}/${total}]" "1" \
            "$(grep -cF "[${i}/${total}]" docs/runbooks/deploy.md || true)"
    done
    # And the old count is gone rather than sitting one paragraph away.
    holds "the runbook no longer prints the previous act count" "0" \
        "$(grep -cF "[1/$((total - 1))]" docs/runbooks/deploy.md || true)"
}

# =============================================================================
# Re-runnability — the property the script itself owns
# =============================================================================

# The sentence the failure path prints ("RE-RUN THIS SCRIPT FROM THE TOP") is
# only worth printing if it is true.
case_a_release_that_stopped_can_be_re_run_from_the_top() {
    fresh_deploy
    drive "stopped run" 1 -- release DJB_DRIVE_FAIL_ACT=grants-apply DJB_DRIVE_FAIL_RC=1 \
        "$DEPLOY/release.sh"
    says "STOPPED at act 4/7"
    : >"$DOCKER_LOG"
    drive "re-run after the fix" 0 -- release "$DEPLOY/release.sh"
    says "RELEASED"
    holds "the re-run performed the whole sequence from the top" \
        "integrations migrate grants-generate grants-apply alerts-apply recreate readyz" \
        "$(acts_in_order)"
}

# =============================================================================
# BUILD ONCE, PROMOTE BY DIGEST (ADR deploy-4)
# =============================================================================
# The box builds nothing. `release.sh` therefore has to answer, BEFORE act 1,
# the question compose would otherwise answer at act 6 with the schema already
# migrated: does the registry have the image this tree names, and is it the same
# image this box last released?
#
# Both refusals are asserted in BOTH directions — the status a caller branches
# on and the sentence a human acts on — and each has a canary case below that
# severs the guard and shows the release sail past, because a refusal nothing
# can make fire is a refusal that can be deleted by accident and stay deleted.

case_a_tag_the_registry_lacks_stops_before_act_one() {
    fresh_deploy
    # The registry answers about neither image. `image-digest` exits 2 and this
    # is the whole reason the question is asked here rather than at act 6.
    DRIVE_DIGEST_WEB="" DRIVE_DIGEST_WORKER=""
    drive "no such tag" 2 -- release DJB_DRIVE_REGISTRY_DIGEST_WEB= DJB_DRIVE_REGISTRY_DIGEST_WORKER= \
        "$DEPLOY/release.sh"
    says "REFUSED — the registry does not have"
    says "djb-web:tree-stub00000000"
    says "THE BOX DOES NOT BUILD"
    says "Nothing was released; no act ran."
    holds "no such tag: docker was never invoked" "0" "$(docker_calls)"
    holds "no such tag: nothing was pinned" "0" "$(wc -l <"$PIN_LOG" | tr -d ' ')"
}

case_a_registry_digest_that_contradicts_the_pin_stops_before_act_one() {
    fresh_deploy
    # The box last released one digest under this tag; the registry now answers
    # a different one. Same tree tag, two images — somebody pushed over an
    # immutable name, and a quiet re-pull is the one thing that must not happen.
    drive "digest mismatch" 1 -- release \
        DJB_DRIVE_TREE_PIN_WEB="sha256:9999999999999999999999999999999999999999999999999999999999999999" \
        "$DEPLOY/release.sh"
    says "THE REGISTRY AND THIS BOX DISAGREE"
    says "the registry says   sha256:1111"
    says "this box pinned     sha256:9999"
    says "Nothing was released; no act ran."
    holds "digest mismatch: docker was never invoked" "0" "$(docker_calls)"
}

case_a_pin_that_agrees_with_the_registry_is_not_a_mismatch() {
    fresh_deploy
    # The ordinary re-release: the box has a pin and it is the registry's own
    # answer. A guard that fired here would make every second release refuse.
    drive "pin agrees" 0 -- release \
        DJB_DRIVE_TREE_PIN_WEB="$DRIVE_DIGEST_WEB" \
        DJB_DRIVE_TREE_PIN_WORKER="$DRIVE_DIGEST_WORKER" \
        "$DEPLOY/release.sh"
    says "RELEASED. 7/7 acts complete."
    says_not "DISAGREE"
}

case_an_unpinned_box_is_not_a_mismatch() {
    fresh_deploy
    # A freshly shipped tree has never been released here, so `tree-digest`
    # prints nothing. Absence is not disagreement.
    drive "no pin yet" 0 -- release "$DEPLOY/release.sh"
    says "RELEASED. 7/7 acts complete."
    says_not "DISAGREE"
}

case_the_release_pins_the_registrys_digest_after_the_recreate() {
    fresh_deploy
    drive "pinning release" 0 -- release "$DEPLOY/release.sh"
    says "pinned both digests into"
    holds "the pin names web with the registry's digest" \
        "web ${DRIVE_DIGEST_WEB}" "$(sed -n 1p "$PIN_LOG")"
    holds "the pin names worker with the registry's digest" \
        "worker ${DRIVE_DIGEST_WORKER}" "$(sed -n 2p "$PIN_LOG")"
    # THE ORDER IS THE ASSERTION. A pin written before the containers were on
    # the image would be recording an intention as a fact — so the recreate must
    # already be in the docker log when the pin happens, and the transcript is
    # where that is visible.
    local recreate_line pin_line
    recreate_line="$(grep -n 'recreate — web and worker' "$DRIVE_OUT" | head -n1 | cut -d: -f1)"
    pin_line="$(grep -n 'pinned both digests into' "$DRIVE_OUT" | head -n1 | cut -d: -f1)"
    if [ -n "$recreate_line" ] && [ -n "$pin_line" ] && [ "$recreate_line" -lt "$pin_line" ]; then
        echo "  ok       the pin is written AFTER the recreate act announced itself"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   the pin must follow the recreate (recreate line ${recreate_line:-none}, pin line ${pin_line:-none})"
        FAILED=$((FAILED + 1))
    fi
}

case_a_checkout_with_no_tree_marker_pins_nothing_and_says_so() {
    fresh_deploy
    rm -f "${CASE_DIR}/TREE"
    drive "no TREE marker" 0 -- release "$DEPLOY/release.sh"
    says "this is a checkout, not a shipped box; nothing pinned"
    holds "no TREE marker: nothing was pinned" "0" "$(wc -l <"$PIN_LOG" | tr -d ' ')"
}

# --- THE ENV FILE'S PIN, AGAINST THE TREE ------------------------------------
#
# The registry guards above ask whether the image this TREE names exists and is
# the one this box last released. Neither of them asks the other half: whether
# the image compose will actually START is that image at all. It is
# `${DJB_IMAGE_REGISTRY}/djb-<service>:${DJB_IMAGE_TAG}` interpolated out of
# `deploy/.env` — for `web`, for `worker`, and for the `oneoff` service every
# act of this release runs inside — and `deploy/.env` is restored from the
# vault at runbook step 31 carrying the tag stored at the LAST deploy.
#
# That disagreement has happened on this deployment's staging box: new images
# built, old ones started, nothing failed, `docker inspect` the only witness.
# `provision.sh up` reconciles it; `release.sh` is a separate command that can
# be run without `up` and, before the guard these two cases drive, would have
# migrated this tree's schema through the previous tree's code.

case_a_stale_env_image_tag_is_refused_before_act_one() {
    fresh_deploy
    # The stale pin, in the one place compose reads it from. The generated
    # `.env` above names no tag at all, so appending one is exactly what a
    # vault restore does to a box.
    printf "DJB_IMAGE_TAG='tree-thelastdeploy'\n" >>"$DEPLOY/.env"
    drive "stale env tag" 2 -- release "$DEPLOY/release.sh"
    says "REFUSED — the env file pins a different tree than this box holds"
    # BOTH TAGS, because a refusal that names only one of two disagreeing
    # values leaves the operator to guess which end is wrong.
    says "this tree is    tree-stub00000000"
    says "the env file    tree-thelastdeploy"
    # AND THE REMEDY, as a command rather than as advice.
    says "./deploy/provision.sh up"
    says "Nothing was released; no act ran."
    holds "stale env tag: docker was never invoked" "0" "$(docker_calls)"
    holds "stale env tag: nothing was pinned" "0" "$(wc -l <"$PIN_LOG" | tr -d ' ')"

    # THE CANARY, and it is the only thing that proves the assertions above are
    # about a guard rather than about a coincidence — the registry guards'
    # canary case, applied to this one and folded in here so the rung stays at
    # the two cases its criteria name. Sever the comparison in a COPY of
    # release.sh (beside the real one, so `HERE` still resolves to this
    # deployment), drive the same case, and assert the release sails past;
    # then re-assert the refusal on the unsevered file in the tree.
    local severed="${DEPLOY}/severed.sh"
    sed 's/^if \[ -n "\${DJB_IMAGE_TAG:-}" \] \&\& \[ "\$DJB_IMAGE_TAG" != "\$IMAGE_TAG" \]; then/if false; then/' \
        "$SOURCE" >"$severed"
    chmod +x "$severed"
    if cmp -s "$SOURCE" "$severed"; then
        echo "  FAILED   the stale-tag canary planted NOTHING — the sever pattern no longer matches release.sh"
        FAILED=$((FAILED + 1))
    else
        drive "severed: stale env tag" 0 -- release "$severed"
        says_not "REFUSED — the env file pins a different tree than this box holds"
    fi

    fresh_deploy
    printf "DJB_IMAGE_TAG='tree-thelastdeploy'\n" >>"$DEPLOY/.env"
    drive "restored: stale env tag" 2 -- release "$DEPLOY/release.sh"
    says "REFUSED — the env file pins a different tree than this box holds"
}

case_an_env_tag_that_agrees_and_a_checkout_that_pins_none_both_release() {
    # AGREEMENT IS THE ORDINARY CASE, and a guard that fired here would refuse
    # every release a box has ever performed correctly. `up` has just run and
    # written this tree's tag into the file: the two agree, and nothing is said
    # about it at all.
    fresh_deploy
    printf "DJB_IMAGE_TAG='%s'\n" "$DRIVE_TAG" >>"$DEPLOY/.env"
    drive "env tag agrees" 0 -- release "$DEPLOY/release.sh"
    says "RELEASED. 7/7 acts complete."
    says_not "the env file pins a different tree"

    # AND ABSENCE IS NOT DISAGREEMENT. A checkout with no `TREE` marker and an
    # env file naming no tag is `deploy/compose.yaml`'s `:?` to refuse, naming
    # the slot itself; a second sentence about it here would be this script
    # answering a question it was not asked. The generated `.env` carries no
    # `DJB_IMAGE_TAG`, so this arm is that state exactly.
    fresh_deploy
    rm -f "${CASE_DIR}/TREE"
    drive "checkout pins no tag" 0 -- release "$DEPLOY/release.sh"
    says "RELEASED. 7/7 acts complete."
    says_not "the env file pins a different tree"
}

case_the_dry_run_names_the_image_and_the_digest_it_would_release() {
    fresh_deploy
    drive "--dry-run names the image" 0 -- release "$DEPLOY/release.sh" --dry-run
    says "tree tag     tree-stub00000000"
    says "djb-web:tree-stub00000000"
    says "$DRIVE_DIGEST_WEB"
    says "nothing was touched."
    holds "--dry-run: nothing was pinned" "0" "$(wc -l <"$PIN_LOG" | tr -d ' ')"
}

case_the_registry_guards_can_actually_fire() {
    # THE CANARY, and it is the only thing that proves the two cases above are
    # about a guard rather than about a coincidence. Sever each guard in a COPY
    # of release.sh, drive the same case, and assert the release sails past —
    # then restore byte-identically and assert the refusal is back.
    fresh_deploy
    # BESIDE the real one, not above it: release.sh derives `HERE` from its own
    # path and reads `compose.yaml` and `.env` out of it, so a copy anywhere
    # else refuses as "not a deployment checkout" and every canary would read
    # as firing while measuring nothing.
    local severed="${DEPLOY}/severed.sh"

    # 1 · the no-such-tag guard. `image-digest`'s non-zero status stops being
    #     consulted, which is exactly what a careless `|| true` would do.
    sed 's/    if \[ "\$release_rc" != "0" \]; then/    if false; then/' "$SOURCE" >"$severed"
    chmod +x "$severed"
    if cmp -s "$SOURCE" "$severed"; then
        echo "  FAILED   the no-such-tag canary planted NOTHING — the sever pattern no longer matches release.sh"
        FAILED=$((FAILED + 1))
    else
        drive "severed: no such tag" 0 -- release DJB_DRIVE_REGISTRY_DIGEST_WEB= DJB_DRIVE_REGISTRY_DIGEST_WORKER= "$severed"
        says_not "REFUSED — the registry does not have"
    fi

    # 2 · the digest-mismatch guard.
    sed 's/    if \[ -n "\$release_pin" \] && \[ "\$release_pin" != "\$release_digest" \]; then/    if false; then/' "$SOURCE" >"$severed"
    chmod +x "$severed"
    if cmp -s "$SOURCE" "$severed"; then
        echo "  FAILED   the digest-mismatch canary planted NOTHING — the sever pattern no longer matches release.sh"
        FAILED=$((FAILED + 1))
    else
        drive "severed: digest mismatch" 0 -- release \
            DJB_DRIVE_TREE_PIN_WEB="sha256:9999999999999999999999999999999999999999999999999999999999999999" "$severed"
        says_not "THE REGISTRY AND THIS BOX DISAGREE"
    fi

    # 3 · restored. The unsevered script is the one in the tree, and it still
    #     refuses — so what cases 1 and 2 measured was the guard and not the
    #     weather.
    fresh_deploy
    drive "restored: no such tag" 2 -- release DJB_DRIVE_REGISTRY_DIGEST_WEB= DJB_DRIVE_REGISTRY_DIGEST_WORKER= "$DEPLOY/release.sh"
    says "REFUSED — the registry does not have"
}

case_promotion_is_a_re_pin_of_the_same_digest_and_never_a_build() {
    # PROMOTION, staging → prod, and the property is that NOTHING IS REBUILT.
    # Two boxes, two projects, two databases, one tree tag — so one digest. The
    # second box is not handed the first box's pin; it resolves the registry
    # itself and arrives at the same answer, which is what makes "the same
    # software is running in both places" a fact rather than a hope.
    fresh_deploy
    drive "staging release" 0 -- release "$DEPLOY/release.sh"
    local staging_pin
    staging_pin="$(cat "$PIN_LOG")"

    fresh_deploy
    drive "prod release, same tree" 0 -- release "$DEPLOY/release.sh"
    holds "prod pinned the identical digests staging did" "$staging_pin" "$(cat "$PIN_LOG")"

    # AND NOTHING WAS BUILT. The docker log is every invocation in order; a
    # `build` or a `buildx` anywhere in it would mean this deployment still
    # manufactures its own image somewhere, which is the defect ADR deploy-4
    # closes.
    if grep -qE '(^| )(build|buildx)( |$)' "$DOCKER_LOG"; then
        echo "  FAILED   a promotion BUILT something:"
        grep -nE '(^| )(build|buildx)( |$)' "$DOCKER_LOG" | sed 's/^/             | /'
        FAILED=$((FAILED + 1))
    else
        echo "  ok       a promotion built nothing — $(docker_calls) docker invocations, no build among them"
        PASSED=$((PASSED + 1))
    fi
}

case_the_deployment_compose_declares_no_build() {
    # THE GREPPABLE HALF, read off the real file rather than the stub. A
    # `build:` stanza anywhere in the deployment compose is a third build site
    # for a tree CI already built once, and it is how the box got its own
    # divergent arm64 image in the first place.
    #
    # `|| true` on every grep here, and it is not laziness: this file runs under
    # `set -euo pipefail`, and `grep -c` exits 1 when it counts zero — which is
    # the PASSING answer for the first assertion. Without it the drive dies
    # silently at this line and every case after it is never run, which is
    # exactly what it did while this case was being written.
    local hits qualified
    hits="$(grep -cE '^[[:space:]]*build:' deploy/compose.yaml deploy/compose.second.yaml | awk -F: '{s+=$2} END {print s+0}' || true)"
    holds "the deployment compose files declare no build:" "0" "$hits"

    # And the one composed name is composed from the registry prefix in all
    # three services, so no service can be a different image from the others.
    qualified="$(grep -c 'image: ${DJB_IMAGE_REGISTRY' deploy/compose.yaml || true)"
    holds "every app image is registry-qualified" "3" "$qualified"
}

case_two_clean_runs_perform_the_identical_sequence() {
    fresh_deploy
    drive "first clean run" 0 -- release "$DEPLOY/release.sh"
    cp "$DOCKER_LOG" "${CASE_DIR}/first.log"
    : >"$DOCKER_LOG"
    drive "second clean run" 0 -- release "$DEPLOY/release.sh"
    if cmp -s "${CASE_DIR}/first.log" "$DOCKER_LOG"; then
        echo "  ok       two clean runs — byte-identical invocation sequences"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   two clean runs — the second run invoked docker differently"
        diff "${CASE_DIR}/first.log" "$DOCKER_LOG" | sed 's/^/             | /' | head -20
        FAILED=$((FAILED + 1))
    fi
}

case_an_unknown_flag_is_refused
case_a_piped_stdout_is_refused
case_a_missing_env_file_is_refused
case_an_empty_required_slot_is_refused_before_the_first_act
case_missing_alert_credentials_are_a_refusal_not_a_skip
case_an_unreadable_postgres_pin_is_refused
case_a_missing_apply_py_is_refused_before_the_first_act
case_a_clean_release_performs_seven_acts_in_order
case_the_psql_client_is_the_compose_pin
case_the_migrate_act_prints_its_wall
case_the_psql_client_carries_the_compose_digest
case_the_network_is_the_env_files_project
case_the_project_falls_back_to_the_derivation
case_the_alerts_act_is_handed_the_sink_and_the_slot
case_the_alerts_act_runs_in_container_on_the_stack_network
case_the_release_runs_no_host_python_against_the_tree
case_act_six_recreates_the_app_rather_than_restarting_it
case_the_readyz_probe_carries_the_probers_own_posture
case_without_alerts_skips_exactly_one_act_and_says_so
case_dry_run_touches_nothing
case_a_fake_integration_stops_the_release_before_anything_changed
case_an_unreadable_seam_stops_the_release_with_its_own_code
case_a_failed_migrate_stops_at_act_one
case_an_empty_generated_sql_stops_at_act_two
case_a_failed_grants_apply_stops_at_act_three
case_a_failed_alerts_apply_stops_at_act_four_with_its_own_code
case_a_failed_recreate_stops_at_act_five
case_a_deployment_that_never_becomes_ready_is_a_failed_release
case_an_empty_acceptance_slot_is_the_whole_wall
case_an_accepted_fake_proceeds_past_act_one_and_says_so
case_two_accepted_fakes_are_two_flags_in_order
case_an_accepted_fake_beside_an_unaccepted_one_still_stops_at_act_one
case_a_stale_acceptance_stops_at_act_one
case_the_dry_run_names_the_acceptance_without_touching_anything
case_an_empty_webhook_slot_refuses_in_its_own_words
case_the_deferred_clickstack_pair_keeps_its_own_message
case_without_alerts_still_releases_with_an_empty_webhook_slot
case_the_meili_pin_is_the_root_composes_own
case_the_runbook_documents_as_many_acts_as_the_script_performs
case_no_one_off_runs_as_web_or_worker
case_the_compose_run_census_can_actually_fire
case_a_release_that_stopped_can_be_re_run_from_the_top
case_a_tag_the_registry_lacks_stops_before_act_one
case_a_registry_digest_that_contradicts_the_pin_stops_before_act_one
case_a_pin_that_agrees_with_the_registry_is_not_a_mismatch
case_an_unpinned_box_is_not_a_mismatch
case_the_release_pins_the_registrys_digest_after_the_recreate
case_a_checkout_with_no_tree_marker_pins_nothing_and_says_so
case_a_stale_env_image_tag_is_refused_before_act_one
case_an_env_tag_that_agrees_and_a_checkout_that_pins_none_both_release
case_the_dry_run_names_the_image_and_the_digest_it_would_release
case_the_registry_guards_can_actually_fire
case_promotion_is_a_re_pin_of_the_same_digest_and_never_a_build
case_the_deployment_compose_declares_no_build
case_two_clean_runs_perform_the_identical_sequence

echo "test_release: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property did not hold. Both halves of a refusal are load-bearing: the" >&2
    echo "   status a caller branches on and the sentence a human acts on — and for" >&2
    echo "   this script a third half, the ORDER, which is the only thing standing" >&2
    echo "   between a migrated schema and a restart that never waited for it." >&2
    exit 1
fi
exit 0
