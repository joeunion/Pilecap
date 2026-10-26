#!/usr/bin/env bash
# The first thing every app container runs, and the last thing between a
# published credential and a listening process (ADR deploy-3b, 3d).
#
#   ENTRYPOINT ["/deploy/entrypoint.sh"]   CMD ["uvicorn", ...]
#
# Three steps, in this order and no other:
#
#   1. MATERIALIZE the environment from wherever this deployment keeps it.
#   2. REFUSE, if anything published is in it — before the command runs.
#   3. EXEC the command, replacing this shell, so the process the container
#      supervises is uvicorn (or the worker) and not a bash wrapper that
#      swallows a signal.
#
# STEP 2 IS BEFORE STEP 3 AND THAT IS THE WHOLE POINT. `exec` is the only way
# out of this script, and it is on the far side of the refusal: there is no
# path from a published SECRET_KEY to a socket that is listening. A belt that
# ran alongside the app instead of in front of it would be a report, not a
# refusal.
#
# WHY THE APP FETCHES ITS OWN SECRETS RATHER THAN BEING HANDED THEM. The
# standing default is Secrets Manager injected as env, and the app reads env
# only — settings never learn there is a vault. `aws:<prefix>` is that
# injection happening as late as possible: at container start, in the
# container's own memory, never in a file on the box, never in `docker
# inspect`, never in an image layer. `file:<path>` is the same shape with the
# vault replaced by a file, which is what makes the laptop proof need no AWS
# and what the runbook uses on a box until the runtime image carries an AWS
# client (see the runbook's secrets section — the seam is declared, not
# hidden).

set -euo pipefail

# Never. A trace of this script is a trace of every secret it materializes,
# and `set -x` inherited from a parent shell is a real way for that to happen.
set +x

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

log() {
    # STDERR, not stdout, and that is not fussiness: the release step runs
    # `docker compose run --rm web python /deploy/grants.sql.py > grants.sql`,
    # and two friendly lines on stdout would be two lines of prose at the top
    # of a file psql is about to execute. Diagnostics go where diagnostics go;
    # stdout belongs to whatever the container was asked to produce.
    #
    # Plain and greppable. This is not `core.log` — nothing Django has been
    # imported yet, and an entrypoint that needed the application's logging
    # stack to say "I refused" would have nothing to say when the application
    # is what failed. `docker compose logs` shows both streams, so the line
    # that proves the belt ran is in the deployment's logs either way.
    echo "entrypoint: $*" >&2
}

die() {
    echo "!! entrypoint: $*" >&2
    exit 2
}

SOURCE="${DJB_SECRETS_SOURCE:-}"
[ -n "$SOURCE" ] || die "DJB_SECRETS_SOURCE is unset. It is 'file:<path>' or 'aws:<prefix>'. There is no default: guessing where a deployment keeps its secrets is how one ends up running on the published ones."

# --- the one value this deployment is allowed to ship UNFILLED ---------------
# THE SENTINEL, DECLARED HERE BECAUSE THIS IS THE FILE THAT REFUSES IT.
# `deploy/provision.sh` reads the two lines below out of this file rather than
# repeating them — two pins that can disagree is one pin (the same discipline
# `caddy_image()` uses on compose.yaml's image tag).
#
# WHY A SENTINEL RATHER THAN AN EMPTY SLOT. `CLICKSTACK_API_KEY` is the one
# credential in this deployment that is MINTED BY THE THING IT AUTHENTICATES TO:
# ClickStack's all-in-one image generates its own ingestion key during the
# first-run setup a human performs in the UI (runbook Part 9, step 53), and
# enforces it. A generated value is therefore not a secret — it is a WRONG
# ANSWER that the sink silently refuses, and every span and log line is dropped
# after its retry budget while the stack looks perfectly healthy (the runbook's
# observability part names the step). The slot cannot simply be empty either:
# `deploy/compose.yaml`
# reads it as `${CLICKSTACK_API_KEY:?...}` on two services, so an empty value
# refuses to bring the stack up at all — and the stack has to be up before the
# UI can mint the key. The sentinel is the honest third answer: the deployment
# boots, the value SAYS it is not filled in, and the runbook's numbered step
# replaces it.
#
# EXACTLY ONE NAME MAY HOLD IT. Anything else carrying the sentinel is a slot
# somebody deferred without a step to fill it, and this refuses rather than
# starts — the guards boundary's shape, one file further out.
DJB_DEFERRED_SENTINEL='DEFERRED-until-the-runbook-fills-it'
DJB_DEFERRED_ALLOWED='CLICKSTACK_API_KEY'

# --- what the CONTAINER owns, and the file may not take back -----------------
# The env file is the ENVIRONMENT's: one file, every organ, every process. A few
# variables are the CONTAINER's instead, and they are set by compose or by
# `docker run -e` on the one container that needs them:
#
#   DJB_SERVICE_NAME     `web` on one, `worker` on the other. A file value would
#                        file half the platform's telemetry under the wrong name.
#   DATABASE_USER/       the release step runs `migrate` as the schema OWNER,
#   DATABASE_PASSWORD    because the application's role cannot create a table
#                        (deploy/grants.sql.py). Every other container runs as
#                        the app role, from the file.
#   DJANGO_SETTINGS_MODULE   compose's (`config.settings.production`, set per
#                        service in deploy/compose.yaml) — or, on a bare
#                        `docker run` with none set, the `setdefault` in
#                        config/asgi.py and apps/workflows/worker.py, which is
#                        production too. Never an environment file's opinion.
#
# So: snapshot these before the file speaks, restore them after. Extend the list
# with DJB_CONTAINER_OWNED rather than editing this file — a deployment that
# needs a fifth one has a reason and should have to write it down.
#
# The alternative — letting the file win — is the failure this exists for: it is
# silent, it looks exactly like success, and it is discovered weeks later by
# somebody asking why the worker never appears in the sink.
DJB_CONTAINER_OWNED="${DJB_CONTAINER_OWNED:-DJB_SERVICE_NAME DJANGO_SETTINGS_MODULE DATABASE_USER DATABASE_PASSWORD}"

MODE="${SOURCE%%:*}"
LOCATION="${SOURCE#*:}"
[ -n "$LOCATION" ] && [ "$LOCATION" != "$SOURCE" ] || die "DJB_SECRETS_SOURCE='$SOURCE' has no location. Expected 'file:<path>' or 'aws:<prefix>'."

PRESET_NAMES=""
for NAME in $DJB_CONTAINER_OWNED; do
    if [ -n "${!NAME+set}" ]; then
        eval "PRESET_${NAME}=\${${NAME}}"
        PRESET_NAMES="$PRESET_NAMES $NAME"
    fi
done

case "$MODE" in
    file)
        # ---------------------------------------------------------------------
        # The laptop seam, and the box's path until the image carries an AWS
        # client. `set -a` exports every assignment the file makes; `set +a`
        # puts that back, so nothing after this line is exported by accident.
        [ -f "$LOCATION" ] || die "DJB_SECRETS_SOURCE names $LOCATION, which is not a file. Generate one with deploy/provision.sh env-file, or fetch one with deploy/provision.sh secrets-fetch."
        set -a
        # shellcheck disable=SC1090  # the path is the deployment's, by design
        . "$LOCATION"
        set +a
        ;;

    aws)
        # ---------------------------------------------------------------------
        # Secrets Manager, per-environment prefix (ADR deploy-3a). Every secret
        # under the prefix becomes an environment variable: a secret whose value
        # is a JSON object contributes one variable per key, and any other
        # secret contributes one variable named after the prefix's last path
        # segment. Both shapes are in the wild and neither is worth a migration.
        #
        # THE VALUES NEVER TOUCH DISK on this path. `aws` writes to a pipe,
        # python turns it into shell-quoted assignments on another pipe, and
        # `eval` puts them in this shell's memory. No temporary file, no `tee`,
        # no `--output-file`.
        command -v aws >/dev/null 2>&1 || die "DJB_SECRETS_SOURCE is '$SOURCE' but there is no 'aws' on PATH inside this container. The runtime image (Dockerfile) carries python and curl and no AWS client. Until it does, fetch on the host — deploy/provision.sh secrets-fetch '$LOCATION' deploy/.env — and set DJB_SECRETS_SOURCE=file:/deploy/.env. The runbook's secrets section says the same thing in the same words."
        command -v python >/dev/null 2>&1 || die "no python on PATH; cannot decode Secrets Manager payloads"

        NAMES="$(aws secretsmanager list-secrets \
            --filters "Key=name,Values=$LOCATION" \
            --query 'SecretList[].Name' --output text)"
        [ -n "$NAMES" ] || die "no secrets under prefix '$LOCATION'. An empty vault is not an empty deployment; it is a deployment that has not been provisioned (deploy/provision.sh secrets-put)."

        for NAME in $NAMES; do
            # One round trip per secret, and the payload goes straight into the
            # decoder. `eval` over shell-quoted output rather than a `.` of a
            # file, because there is no file.
            eval "$(aws secretsmanager get-secret-value --secret-id "$NAME" \
                        --query SecretString --output text \
                    | python -c '
import json, shlex, sys

payload = sys.stdin.read()
slot = sys.argv[1].rsplit("/", 1)[-1]
try:
    parsed = json.loads(payload)
except ValueError:
    parsed = None
if isinstance(parsed, dict):
    pairs = {str(k): "" if v is None else str(v) for k, v in parsed.items()}
else:
    pairs = {slot: payload}
for key, value in pairs.items():
    if not key.replace("_", "").isalnum() or key[:1].isdigit():
        raise SystemExit(f"!! entrypoint: {key!r} is not a usable environment variable name")
    print(f"export {key}={shlex.quote(value)}")
' "$NAME")"
        done
        ;;

    *)
        die "DJB_SECRETS_SOURCE mode '$MODE' is not one this deployment knows. It is 'file' or 'aws'. An unknown mode is refused rather than ignored: ignoring it would start the app on whatever happened to be in the environment already."
        ;;
esac

# The container takes its own back.
for NAME in $PRESET_NAMES; do
    eval "export ${NAME}=\${PRESET_${NAME}}"
    unset "PRESET_${NAME}"
done
unset PRESET_NAMES NAME

# --- Step 1b: the deferred slot, and only the one -----------------------------
# Between materializing and the belt, because a deferred value is not a
# published credential (assert_not_published's subject) and not a missing one
# (compose's `:?` subject): it is a slot whose owner is a numbered runbook step,
# and the only question worth asking here is whether anybody deferred a SECOND
# one without saying so.
#
# `compgen -v` rather than `env`: it enumerates shell variable NAMES, so a value
# containing a newline or an `=` cannot split a line and hide behind the split.
#
# THE DECLARATION IS NOT A SLOT, and this loop has to be told so. `compgen -v`
# enumerates every variable in this shell — which necessarily includes
# `DJB_DEFERRED_SENTINEL`, whose whole job is to HOLD the sentinel. Without the
# two names below the guard reports itself as the offender and every container
# in the deployment exits 2 before the belt, before `exec`, on every boot. It
# did exactly that the first time it was run; the skip is the fix, and it is
# scoped to these two names rather than to a prefix so that a real slot called
# `DJB_ANYTHING_ELSE` is still caught.
DEFERRED_OFFENDERS=""
DEFERRED_ACCEPTED=""
while IFS= read -r NAME; do
    case "$NAME" in
        DJB_DEFERRED_SENTINEL|DJB_DEFERRED_ALLOWED) continue ;;
    esac
    eval "DEFERRED_VALUE=\${${NAME}-}"
    [ "$DEFERRED_VALUE" = "$DJB_DEFERRED_SENTINEL" ] || continue
    case " $DJB_DEFERRED_ALLOWED " in
        *" $NAME "*) DEFERRED_ACCEPTED="$DEFERRED_ACCEPTED $NAME" ;;
        *)           DEFERRED_OFFENDERS="$DEFERRED_OFFENDERS $NAME" ;;
    esac
done <<EOF
$(compgen -v)
EOF
unset NAME DEFERRED_VALUE

if [ -n "$DEFERRED_OFFENDERS" ]; then
    die "these variables carry the deferred sentinel and are not allowed to:${DEFERRED_OFFENDERS}.
   Exactly one slot in this deployment may ship unfilled — ${DJB_DEFERRED_ALLOWED} — because
   ClickStack mints its own ingestion key during the first-run setup a human performs
   (docs/runbooks/deploy.md, Part 9). Every other slot is generated by
   deploy/provision.sh or named in its DEFERRED table with the step that fills it,
   and a slot deferred with no step behind it is a boot that half-works for weeks."
fi
if [ -n "$DEFERRED_ACCEPTED" ]; then
    # Said out loud, once per boot, because "the sink is not authenticated yet"
    # is a fact an operator reading `docker compose logs` should not have to
    # infer from dropped spans an hour later.
    log "deferred slot accepted:${DEFERRED_ACCEPTED} — still the sentinel, so the sink is not authenticated yet (runbook Part 9, step 54)"
fi

# --- Step 1c: BEHIND_PROXY=1 travels with the one peer range uvicorn believes --
case "$(printf '%s' "${BEHIND_PROXY:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|on|ok|y|yes)
        case "${FORWARDED_ALLOW_IPS:-}" in
            "") die "BEHIND_PROXY=1 and FORWARDED_ALLOW_IPS is unset, so uvicorn believes no proxy and every client address is the proxy's. Regenerate the env file (deploy/provision.sh env-file) or set FORWARDED_ALLOW_IPS to this stack's network subnet (deploy/compose.yaml declares it)." ;;
            *"*"*) die "FORWARDED_ALLOW_IPS='${FORWARDED_ALLOW_IPS}' believes X-Forwarded-For from any peer. Name this stack's network subnet (deploy/compose.yaml declares it), never '*'." ;;
        esac
        ;;
esac

# --- Step 2: the belt --------------------------------------------------------
# Over THIS PROCESS'S environment — everything step 1 just materialized, plus
# whatever compose set. Unpiped, so its exit status is its own; `set -e` turns
# a nonzero into an exit here, which is the kill path:
#
#     assert_not_published.sh exits 1  ->  set -e exits this script  ->  the
#     container exits nonzero  ->  `exec` below never runs  ->  no socket ever
#     bound.
#
# The script is silent when it is clean; the line below is this entrypoint's,
# so that a deployment's logs record that the belt RAN, not merely that nothing
# complained. "Nothing complained" is also what a belt that was never wired
# looks like.
"$HERE/assert_not_published.sh"
log "assert_not_published cleared (secrets source: $MODE:$LOCATION)"

# --- Step 3: become the application -----------------------------------------
[ $# -gt 0 ] || die "nothing to exec. deploy/compose.yaml sets both 'entrypoint' and 'command' because Compose clears the image's CMD when the entrypoint is overridden; a container here with no command is that line having been deleted."
log "starting: $*"
exec "$@"
