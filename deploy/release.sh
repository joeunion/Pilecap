#!/usr/bin/env bash
# The release sequence, as one script that owns its exit status.
#
#   deploy/release.sh                    integrations, migrate, grants, alerts, restart, readyz
#   deploy/release.sh --dry-run          print the seven acts and touch nothing
#   deploy/release.sh --without-alerts   the first deploy, before Part 9 exists
#
# WHY THIS EXISTS. Until this file, the release was runbook Part 5's numbered
# steps 37, 38, 39 and 40 plus the alert reconcile in
# `docs/runbooks/alerts.md` — four hand-typed commands in order, on a box, at
# the end of a deploy, by somebody who had already been working for an hour.
# The runbook said "every deploy runs part 5, it is idempotent by construction",
# and both halves of that sentence were true; what was missing is that a
# sequence which is idempotent BY CONSTRUCTION is also skippable BY
# CONSTRUCTION. Nothing anywhere notices a release that ran three of its four
# acts. That is the first thing a release census looks for, and the cost is
# named: skip step 38/39 and the application's
# database role keeps UPDATE and DELETE on an append-only table that the
# migration just created — house rule 20's belt, silently unbuckled, with
# nothing in the gate, the logs or `/readyz` able to see it.
#
# `deploy/provision.sh` is the house precedent and this is the same demotion it
# performed: a runbook part becomes a script, and the runbook becomes the
# narration around it. The prose that says WHY stays in the runbook; the acts
# move here, where they can be run in order, exit-coded, and driven by a test.
#
# THE EXIT STATUS IS THE VERDICT, and it is this repository's three:
#
#   0   every act ran. The release is complete.
#   1   an act FAILED. The act is named, nothing after it ran, and the tree,
#       the schema and the containers are in whatever state that act left.
#   2   refused before anything was touched — a missing env file, a missing
#       credential, a piped stdout, an unknown flag. "Could not look", never
#       "looked and found nothing".
#
# A mistyped flag is exit 2, never a silently different release.
#
# IT IS SAFE TO RE-RUN FROM THE TOP, and after a failure that is the fix: no act
# here is additive, so re-running repeats work rather than doubling it. Each act
# states its own idempotence where it is performed, and argues it where the
# property is inherited from the thing being run rather than owned here.
#
# WHAT THIS DOES NOT COVER, declared rather than discovered:
#
#   * BRINGING THE STACK UP. `provision.sh up` (runbook step 34) is Part 4's and
#     stays there: it reconciles the eight or nine services around the app and
#     it owns the project-name adoption. This script owns exactly two services
#     — `web` and `worker` — and act 6 brings that pair up onto the new image.
#     On a box that never deployed, `up` on a stack whose other services are
#     absent fails there with compose's own error, which is the correct answer
#     to "you have not deployed yet".
#   * THE ORDERING WINDOW IS NOW CLOSED ON BOTH PATHS. Within this script the
#     order was always settled: the schema
#     is migrated (act 2) before anything is recreated (act 6). The half that
#     was NOT this file's was the runbook's — step 34's `provision.sh up`
#     recreated `web` on the new image one step BEFORE Part 5 could migrate, so
#     every re-deploy served new code on an old schema for the length of the
#     gap; measured live on staging as three `reconcile_search_index` failures
#     against a missing column, self-healed by Temporal's retry, which is the
#     belt and not the fix. THE RULING: step 34 leaves the app pair alone and
#     the ONE recreate in a deploy is act 6, here, after the migrate.
#     That ruling is why act 6 is `up -d` and no longer `restart` — see the act.
#   * WHETHER ACT 5 CAN REACH THE SINK AT ALL, in two ways it cannot check.
#     The act runs `apply.py` inside a one-off container on the web IMAGE (the
#     `oneoff` service), so it holds only
#     as long as (a) `apply.py` and the `census.py` it imports stay stdlib-only
#     or inside the web image's own dependency set — a new third-party import
#     would fail there and nowhere in the bash drive would notice — and (b) the
#     sink stays a service on this compose project's network under the name
#     `clickstack`. A sink moved off the network is a real deployment shape and
#     the escape is the one that was always there: name `CLICKSTACK_URL` in the
#     environment and this act uses it verbatim. Neither is visible until a
#     release runs on a box.
#   * WHETHER THE RELEASE SHOULD HAPPEN. Which tree, which tag, whether the
#     criteria were met: the PM's judgement and no script's.
#   * ANYTHING ZITADEL. Identity configuration is written through services and
#     materialised by one activity (house rule 27); it is not a release act.
#
# THE READYZ WAIT IS BOUNDED AND THE BOUND IS RECORDED, NEVER GATED.
# 24 attempts, 5 seconds apart — two minutes — over the same target, the same
# `--connect-to` and the same certificate posture the `readyz-prober` container
# already probes with (deploy/compose.yaml). The probe runs INSIDE that
# container rather than from the operator's shell, so a laptop stack (where
# PROBE_CONNECT_TO points the socket at Caddy) and a box (where the value is
# empty and public DNS is genuinely in the path) are the same command with no
# branch in this file.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
set +x  # never; see deploy/entrypoint.sh for the same line and the same reason

# --- it refuses to be piped ---------------------------------------------------
# check.sh's detection and check.sh's CI exemption, deliberately identical
# (scripts/check.sh:38-64, scripts/pm_merge.sh:91-96). A pipe replaces this
# script's exit status with the filter's, and this script's exit status is the
# only thing that says whether the release happened. Redirect to a file and read
# the file; nothing is lost.
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! release refuses pipes — a filter replaces the exit status of the release" >&2
    echo "   with the filter's, and the exit status is the whole verdict. Run" >&2
    echo "   it bare or redirect to a file." >&2
    exit 2
fi

die() {
    # 2 is "could not get as far as releasing". An act that was never attempted
    # must never share an exit code with an act that ran and failed.
    echo "!! release: $*" >&2
    echo "   Nothing was released; no act ran." >&2
    exit 2
}

say() { echo "release: $*"; }

usage() {
    # The three invocation lines and no more. `provision.sh` prints its whole
    # header here because that header IS its subcommand table; this file's is
    # seventy lines of reasoning, and burying a one-word typo under seventy
    # lines is how a person learns to stop reading the output. The reasoning is
    # in the file, where somebody who wants it will be.
    sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo ""
    echo "The header of ${BASH_SOURCE[0]} says what each act is and why."
    exit 2
}

# --- the acts, and the one place their names live -----------------------------
# Named once, counted from the list, and printed from it. An eighth act added
# below without a name here would print `[8/7]`, which is the kind of thing a
# reader notices.
ACTS=(
    "integrations — the wall: no silent fakes in production"
    "migrate — the schema, as the schema owner"
    "grants generate — the release SQL, from the model declarations"
    "grants apply — the app role's privileges, and the append-only revokes"
    "alerts apply — the alert route reconciled to the census"
    "recreate — web and worker, onto the new image and the migrated schema"
    "readyz — wait until the deployment says it is ready"
)
TOTAL="${#ACTS[@]}"
ACT_INDEX=0
ACT_NAME=""

act() {
    ACT_INDEX=$((ACT_INDEX + 1))
    ACT_NAME="${ACTS[$((ACT_INDEX - 1))]%% —*}"
    echo ""
    echo "release: [${ACT_INDEX}/${TOTAL}] ${ACTS[$((ACT_INDEX - 1))]}"
}

# The one failure path. Every act routes through it, so the sentence a human
# reads after a failed release is the same sentence every time, and it always
# names WHICH act stopped and what is safe to do next.
stopped() {
    local status="$1"
    echo "" >&2
    echo "!! release: STOPPED at act ${ACT_INDEX}/${TOTAL} — ${ACT_NAME} (exit ${status})." >&2
    echo "   No act after this one ran." >&2
    echo "   Fix the cause and RE-RUN THIS SCRIPT FROM THE TOP: every act is" >&2
    echo "   idempotent, so the acts that already succeeded will repeat harmlessly" >&2
    echo "   rather than double." >&2
    exit 1
}

WITHOUT_ALERTS=""
DRY_RUN=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    -h | --help)
        sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    --dry-run) DRY_RUN=1; shift ;;
    --without-alerts) WITHOUT_ALERTS=1; shift ;;
    *)
        echo "!! release: unknown argument '$1'." >&2
        echo "" >&2
        usage
        ;;
    esac
done

# --- the preconditions, all of them before any of the acts --------------------
command -v docker >/dev/null 2>&1 || die "no 'docker' on PATH"
[ -f "$HERE/compose.yaml" ] || die "no $HERE/compose.yaml — this is not a deployment checkout"
[ -f "$HERE/.env" ] || die "no $HERE/.env. Generate one (provision.sh env-file) or fetch one (provision.sh secrets-fetch) before releasing."

# THIS SCRIPT RUNS NO HOST PYTHON, AND THE ABSENCE IS DELIBERATE.
# It used to resolve a `PYTHON_BIN` here for exactly one purpose — act 5's
# `apply.py` — and that one host invocation cost twice. It wrote five
# `__pycache__` files into the shipped tree, so the box's file set stopped
# equalling the archive manifest the moment the first release ran; and it
# reached the sink over the PUBLIC address, which is behind Caddy's basic-auth
# wall. Act 5 now runs in a one-off container beside the stack, like
# every other act, so there is no host interpreter left to name.
#
# The tree's own copy is still a precondition, and it still is one for the
# reason it always was: the image was built FROM this tree, so a `deploy/` with
# no `apply.py` in it is a release whose act 5 has nothing to reconcile with.
# What is checked here is the shipped file; what is RUN is the image's copy of
# it, at the path `Dockerfile`'s `COPY . .` puts it (`/app/deploy/…`).
ALERTS_APPLY="$HERE/observability/alerts/apply.py"
ALERTS_APPLY_IN_IMAGE="/app/deploy/observability/alerts/apply.py"
[ -n "$WITHOUT_ALERTS" ] || [ -f "$ALERTS_APPLY" ] || die "no $ALERTS_APPLY — the alerts act has nothing to run"

# THE ENVIRONMENT IS READ HERE AND NOWHERE ELSE. Runbook steps 37 and 39 each
# began `set -a; . deploy/.env; set +a`, which is the same source performed
# twice by hand and skipped once. `set -a` exports, because the compose
# interpolation, the `-e` passthroughs and apply.py all read the environment
# rather than the file.
set -a
# shellcheck disable=SC1091  # generated per environment; not in the tree
. "$HERE/.env"
set +a

# Every name an act will need, checked before the first act rather than
# discovered by the fourth. A release that dies half-way because a slot was
# empty is the failure mode this whole rung exists to remove.
missing=""
for name in POSTGRES_USER POSTGRES_PASSWORD DATABASE_USER DATABASE_PASSWORD \
    DATABASE_NAME DATABASE_HOST DATABASE_PORT SITE_ADDRESS; do
    [ -n "${!name:-}" ] || missing="$missing $name"
done
[ -z "$missing" ] || die "these are empty in $HERE/.env:$missing"

# THE SINK'S OPERATOR CREDENTIALS ARE A REFUSAL, NOT A SKIP. `apply.py` refuses
# without them (its own REQUIRED_ENV), and they are DEFERRED slots: the operator
# account does not exist until a human completes ClickStack's first-run setup at
# runbook Part 9 step 53. So the first deploy of a fresh environment genuinely
# cannot run this act — and the escape for it is a sentence you have to type on
# purpose, `provision.sh up --second`'s precedent exactly. What must never exist
# is a release that quietly leaves the alert route unreconciled.
if [ -z "$WITHOUT_ALERTS" ]; then
    alerts_missing=""
    for name in CLICKSTACK_ADMIN_EMAIL CLICKSTACK_ADMIN_PASSWORD; do
        [ -n "${!name:-}" ] || alerts_missing="$alerts_missing $name"
    done
    if [ -n "$alerts_missing" ]; then
        echo "!! release: REFUSED." >&2
        echo "   empty in $HERE/.env:$alerts_missing" >&2
        echo "" >&2
        echo "   The alert route cannot be reconciled without them, and a release that" >&2
        echo "   silently left the alerts unreconciled is the seam this script exists to" >&2
        echo "   close. Two ways forward, both deliberate:" >&2
        echo "     * fill them — runbook Part 9 step 53 registers the operator account" >&2
        echo "       and step 54 puts it in the environment." >&2
        echo "     * or say out loud that this deploy has no sink yet:" >&2
        echo "           ./deploy/release.sh --without-alerts" >&2
        echo "   Nothing was released; no act ran." >&2
        exit 2
    fi

    # THE WEBHOOK IS ITS OWN PRECONDITION, AND THE UNLUMPING IS THE FIX.
    # It used to sit in the loop above, and the sentence that loop prints is
    # about an account that does not exist yet — which on a box whose sink is
    # UP AND KEYED is simply false. A refusal that says something false is a
    # refusal that teaches the operator to stop reading refusals.
    #
    # The four-site contract this does NOT touch, and must not: an empty
    # `SLACK_WEBHOOK_URL` disarms the readyz-prober's own direct alert and the
    # prober announces that once per start (deploy/compose.yaml, prober.sh,
    # docs/runbooks/alerts.md, provision.sh). That contract is about the PROBER's
    # half. `apply.py`'s half is the alert ROUTE inside the sink, and a route with
    # no delivery URL is a monitor that detects and never delivers, with no
    # per-start announcement anywhere — so `apply.py` is right to refuse, and this
    # is the honest way to say why before it does.
    if [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
        echo "!! release: REFUSED." >&2
        echo "   empty in $HERE/.env: SLACK_WEBHOOK_URL" >&2
        echo "" >&2
        echo "   The sink may be perfectly up. The alert route has nowhere to deliver." >&2
        echo "   Reconciling it without a URL builds a monitor that detects and never" >&2
        echo "   delivers, and nothing anywhere says so afterwards: empty disarms only" >&2
        echo "   the readyz-prober's own half, and the prober announces THAT itself," >&2
        echo "   once per start." >&2
        echo "   Two ways forward, both deliberate:" >&2
        echo "     * fill it — the \$DJB_DEPLOY_NAMESPACE/<env>/env slot (docs/runbooks/alerts.md)." >&2
        echo "     * or skip the act knowing what it means ON THIS BOX:" >&2
        echo "           ./deploy/release.sh --without-alerts" >&2
        echo "       which here means route unreconciled, NOT no sink." >&2
        echo "   Nothing was released; no act ran." >&2
        exit 2
    fi
fi

# --- the operator's accepted fakes, expanded and nothing else -----------------
# `DJB_ACCEPTED_FAKES` is a whitespace-separated list of census keys, typed by
# the operator into the vault-managed environment file. This script EXPANDS it
# into `--accept-fake <key>` arguments and makes no judgment of its own: whether
# a key may be accepted is a question about the LIVE census, and the only honest
# way to ask it is to hand the keys to the command that takes the census and read
# its exit status. Parsing that command's human-readable report to decide here
# would be filtering the output of the thing whose exit status is the verdict,
# which is never done here.
#
# EMPTY OR UNSET IS THE FULL WALL, and that is the default a product inherits.
# `read -a` rather than an unquoted expansion: a `*` in the slot would otherwise
# glob against the deployment directory, which is a wrong key rather than a
# refused one.
ACCEPT_ARGS=()
ACCEPTED_KEYS=()
if [ -n "${DJB_ACCEPTED_FAKES:-}" ]; then
    read -r -a ACCEPTED_KEYS <<<"$DJB_ACCEPTED_FAKES"
    for accepted_key in ${ACCEPTED_KEYS[@]+"${ACCEPTED_KEYS[@]}"}; do
        ACCEPT_ARGS+=(--accept-fake "$accepted_key")
    done
fi
ACCEPTED_COUNT="${#ACCEPTED_KEYS[@]}"

# WHOSE STACK. `provision.sh up` ADOPTS the project name a
# running stack already carries and writes it into deploy/.env, so the env file
# is the truth on a box whose name was adopted, and the derivation is the truth
# everywhere else. Reading the file first is the durable form of what would
# otherwise be four command sites fixed by hand.
project_name() {
    if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then
        printf '%s' "$COMPOSE_PROJECT_NAME"
        return 0
    fi
    [ -x "$HERE/provision.sh" ] || die "no COMPOSE_PROJECT_NAME in $HERE/.env and no $HERE/provision.sh to derive one"
    "$HERE/provision.sh" project-name
}

# The psql client image, READ rather than typed. Runbook step 39 said
# `postgres:16.10` while deploy/compose.yaml pinned `postgres:18.6` — the client
# and the server drifted two majors apart in a file nobody diffs against the
# other. Taking the db service's own pin makes that drift impossible.
psql_image() {
    local pin
    pin="$(sed -n 's/^[[:space:]]*image:[[:space:]]*\(postgres:[0-9][0-9.]*\).*/\1/p' "$HERE/compose.yaml" | head -n1)"
    [ -n "$pin" ] || die "could not read the postgres image pin out of $HERE/compose.yaml; the psql client version is not this script's to guess"
    printf '%s' "$pin"
}

compose() { docker compose --env-file "$HERE/.env" -f "$HERE/compose.yaml" "$@"; }

# EVERY ONE-OFF IN THIS SCRIPT RUNS AS `oneoff`, NEVER AS `web`.
#
# `compose run --rm web …` inherits the `web` service's environment, including
# `DJB_SERVICE_NAME=web`, so the settings module derives a pool of TWENTY for a
# management command that wants two. On a loaded box there were no slots left:
# `revoke_token` PoolTimeout'd, and acts 1, 2, 3 and 5 below are the same shape
# — a release refused by its own box's load, recovered only by a force-recreate,
# and it recurs until the one-off door exists.
#
# `deploy/compose.yaml`'s `oneoff` service is the one seam: same image, same
# entrypoint, `DJB_SERVICE_NAME: oneoff`, and NO `depends_on` — which is why the
# acts below no longer carry `--no-deps`. There is nothing to skip.
#
# `deploy/tests/test_release.sh`'s compose-run census reads this file and the
# runbooks and refuses a surviving `run … web`, so the population stays closed
# rather than being a list somebody has to remember to extend.

# RESOLVED BEFORE THE FIRST ACT, both of them. Either can refuse, and a refusal
# that fires at act 3 would print "Nothing was released" underneath a migration
# that had already run — a sentence the operator would be right to believe and
# wrong to act on. `|| exit 2` because die()'s exit happens inside the command
# substitution's subshell; the message is already on stderr by then.
PROJECT="$(project_name)" || exit 2
PSQL_IMAGE="$(psql_image)" || exit 2

READYZ_ATTEMPTS="${DJB_READYZ_ATTEMPTS:-24}"
READYZ_INTERVAL="${DJB_READYZ_INTERVAL:-5}"
READYZ_TARGET="${PROBE_TARGET:-https://${SITE_ADDRESS}/readyz}"

# --- --dry-run: the plan, and nothing else ------------------------------------
if [ -n "$DRY_RUN" ]; then
    say "DRY RUN — the acts below are what a real run would perform, in this order."
    say "project      ${PROJECT}"
    say "database     ${DATABASE_NAME} on ${DATABASE_HOST}:${DATABASE_PORT}"
    say "app role     ${DATABASE_USER} (created if absent; the password never leaves the environment)"
    say "psql client  ${PSQL_IMAGE}  (read from $HERE/compose.yaml)"
    say "readyz       ${READYZ_TARGET}  (up to ${READYZ_ATTEMPTS} attempts, ${READYZ_INTERVAL}s apart)"
    if [ "$ACCEPTED_COUNT" -gt 0 ]; then
        say "accepted     ${ACCEPTED_COUNT} fake(s) named in DJB_ACCEPTED_FAKES: ${ACCEPTED_KEYS[*]}"
        say "             act 1 will refuse any of them that is not FAKE right now."
    else
        say "accepted     none — the wall refuses every integration that is not configured"
    fi
    i=0
    for line in "${ACTS[@]}"; do
        i=$((i + 1))
        if [ "$i" = "5" ] && [ -n "$WITHOUT_ALERTS" ]; then
            echo "release: [${i}/${TOTAL}] ${line}   << SKIPPED by --without-alerts"
        else
            echo "release: [${i}/${TOTAL}] ${line}"
        fi
    done
    say "nothing was touched."
    exit 0
fi

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-release.XXXXXX")" || die "could not make a scratch directory"
trap 'rm -rf "$WORK"' EXIT
GRANTS_SQL="$WORK/grants.sql"

say "project      ${PROJECT}"
say "database     ${DATABASE_NAME} on ${DATABASE_HOST}:${DATABASE_PORT}"
say "app role     ${DATABASE_USER}"

# =============================================================================
# 1 · integrations — the wall
# =============================================================================
# READ-ONLY, so trivially idempotent, and FIRST on purpose. Every act after this
# one changes the world; this one only looks, so a release that is going to be
# refused for standing on a fake is refused before it has migrated anything.
# `stopped()`'s promise — "no act after this one ran" — is worth most when the
# act that stops is the act that changed nothing.
#
# WHAT IT REFUSES, and why it is a refusal rather than a warning: the census
# (`apps/core/integrations.py`) reports each external service as configured, a
# FAKE, or absent. A fake is a stand-in that SUCCEEDS — the console mail backend
# accepts every password reset and prints it to a log, `FakeSmsChannel` accepts
# every consent-critical STOP and drops it — so in production it is not a
# missing feature, it is a silent one. The failures this whole census exists for
# have all been of that shape, which is why the deploy is where it becomes a
# wall.
#
# IT NAMES THE REMEDY. `manage.py integrations --wall` prints every row with the
# env var, command or console path that fixes it, so an operator refused here
# does not have to go and read the source. That is the instrument checklist's
# line, held by the command itself rather than by this script.
#
# EXIT 2 IS AN UNREADABLE SEAM, not a verdict. If an app's declaration raised,
# the census does not KNOW what that app talks to and says so; the release stops
# for the same reason it stops on a fake, and `stopped` prints the number so the
# operator can look it up in `docs/product/instruments.md` without re-running
# anything. "I could not look" is never quietly turned into "it is fine".
#
# AND WHAT IT LETS PAST, ONE NAMED KEY AT A TIME. A deployment
# may stand on a stand-in it has NAMED — the template's own staging ships
# self-declaring fakes and has no gateway to point them at — and the acceptance
# is a vault artifact somebody wrote down, enumerated per key against the live
# census, refused the moment a key is not FAKE, and printed with its detail and
# its remedy on every release for as long as it is true. "Declared fakes pass"
# was rejected: every fake this census can see is declared by construction, so
# that rule would delete the wall and keep its name.
act
set +e
compose run --rm -T oneoff python manage.py integrations --wall \
    ${ACCEPT_ARGS[@]+"${ACCEPT_ARGS[@]}"}
rc=$?
set -e
[ "$rc" = "0" ] || stopped "$rc"

# =============================================================================
# 2 · migrate
# =============================================================================
# IDEMPOTENT, INHERITED: `migrate` applies the migrations that are not in
# `django_migrations` and no others, so a second run is a no-op that prints "No
# migrations to apply". Nothing here makes that weaker.
#
# AS THE SCHEMA OWNER, not as the app. `POSTGRES_USER` is the RDS master, which
# owns the schema; `DATABASE_USER` is the application's role and by design
# cannot create a table. The two are handed over as DATABASE_USER/PASSWORD
# because that is what config/settings reads, and in the PASSTHROUGH form
# (`-e NAME`, no `=`) so neither value ever lands in argv, `ps` or a history
# file. `DATABASE_URL` is empty in every environment file for this exact reason
# — a URL would win over the parts and make this override silently do nothing.
act
set +e
(
    export DATABASE_USER="$POSTGRES_USER"
    export DATABASE_PASSWORD="$POSTGRES_PASSWORD"
    compose run --rm -T -e DATABASE_USER -e DATABASE_PASSWORD oneoff \
        python manage.py migrate --noinput
)
rc=$?
set -e
[ "$rc" = "0" ] || stopped "$rc"

# =============================================================================
# 3 · grants generate
# =============================================================================
# IDEMPOTENT, AND MORE THAN THAT: PURE. `grants.sql.py` opens no connection,
# reads no clock and emits no timestamp — two runs against one tree are
# byte-identical (its own render() docstring, and `deploy/test_grants_census.py`
# is the census that holds the emitter to the model registry). Generating is not
# a world change at all; act 3 is where anything happens.
#
# THE SQL CARRIES NO SECRET. The CREATE ROLE preamble reads the role and its
# password with psql's `\getenv` at apply time, so the file this writes is
# committable text and the password stays in the environment.
act
set +e
compose run --rm -T oneoff python /deploy/grants.sql.py \
    --role "$DATABASE_USER" --create-role >"$GRANTS_SQL"
rc=$?
set -e
[ "$rc" = "0" ] || stopped "$rc"
[ -s "$GRANTS_SQL" ] || { rc=1; stopped "$rc"; }
say "  $(wc -l <"$GRANTS_SQL" | tr -d ' ') lines, including $(grep -c '^REVOKE' "$GRANTS_SQL" || true) append-only REVOKEs"
# AND IT IS PRINTED, because the step this replaced said "generate the release
# SQL AND READ IT" and that instruction was the good half of the manual step.
# The output is deterministic (no timestamp, no host name) and carries no secret
# — the CREATE ROLE preamble reads the password with psql's own `\getenv` at
# apply time — so it is safe in a terminal and in a redirected release log.
sed 's/^/    /' "$GRANTS_SQL"

# =============================================================================
# 4 · grants apply
# =============================================================================
# IDEMPOTENT BY CONSTRUCTION, and this is the act whose skippability the census
# priced. Every statement is a GRANT or a REVOKE, which are absolute rather than
# additive: applying them twice leaves exactly the privileges applying them once
# does. The CREATE ROLE preamble builds no statement at all when the role is
# already there (`\gexec` over a SELECT with a NOT EXISTS guard).
#
# WHY IT MUST RUN EVERY TIME: `GRANT ... ON ALL TABLES` binds the tables that
# exist WHEN IT RUNS. A migration that created a table leaves the app role with
# no privileges on it; a migration that created an APPEND-ONLY table leaves the
# app role holding UPDATE and DELETE on a ledger. Act 1 then act 3, every
# release, in that order.
#
# `ON_ERROR_STOP=1` so a failed statement is a failed act rather than a warning
# in a log. PGSSLMODE travels in the passthrough form: the environment files
# declare `require`, and libpq's own default (`prefer`) would silently accept an
# unencrypted connection to a server that offered one.
act
set +e
PGPASSWORD="$POSTGRES_PASSWORD" \
    docker run --rm -i --network "${PROJECT}_default" \
    -e PGPASSWORD -e DATABASE_USER -e DATABASE_PASSWORD -e PGSSLMODE \
    "$PSQL_IMAGE" \
    psql -h "$DATABASE_HOST" -p "$DATABASE_PORT" -U "$POSTGRES_USER" -d "$DATABASE_NAME" \
    -v ON_ERROR_STOP=1 -f - <"$GRANTS_SQL"
rc=$?
set -e
[ "$rc" = "0" ] || stopped "$rc"

# =============================================================================
# 5 · alerts apply
# =============================================================================
# IDEMPOTENT, DECLARED BY THE THING BEING RUN: apply.py is a reconciler, not an
# importer — one delivery webhook, one saved search per census member, one alert
# per census member, matched by name and updated in place. Its own header says
# re-applying is the normal case, and `Applied N alerts. Re-run is a no-op.` is
# the line it ends on.
#
# IT BELONGS IN THE RELEASE AND NOT IN A SEPARATE RITUAL, because the census it
# reconciles to is DERIVED FROM THIS TREE (`census.py` walks the code). A release
# that ships a new alert-shaped declaration and does not run this leaves the sink
# reconciled to the previous tree, and nothing anywhere says so.
#
# ITS EXIT CODES ARE ITS OWN AND ARE REPORTED VERBATIM: 3 the census raised a
# warning (fix the declaration first), 2 a required name is missing, 0 applied.
# All of them stop the release; the number is printed so the operator can look it
# up in `docs/product/instruments.md` without re-running anything.
#
# IT RUNS IN-CONTAINER, ON THE STACK'S OWN NETWORK, AND THAT IS THE RULING.
# This act used to run on the operator's interpreter against
# `https://${O11Y_ADDRESS}` — the sink's PUBLIC address, which Caddy guards with
# a basic-auth wall. `apply.py` sends no basic auth, so the act answered 401 on
# every box; and the wall's plaintext is printed once when the env file is
# generated and STORED NOWHERE (only the bcrypt hash exists), so the credential
# that would have made it work does not exist anywhere in the world. Three
# shapes were on the table and two were rejected on their own merits:
#
#   * TEACHING apply.py BASIC AUTH and vaulting the plaintext — rejected. It
#     manufactures a stored secret whose only job is to get past our own wall,
#     from inside our own box, where the wall does not apply. Bcrypt-only
#     storage is the feature; a credential that exists only to be exfiltrated
#     is the bug.
#   * PUBLISHING 8080 on loopback — rejected. It publishes a port that need not
#     exist, against `deploy/compose.yaml`'s own "nothing here publishes … 8080"
#     and the `assert_not_published.sh` discipline that holds it.
#
# So the act joins the stack instead of knocking on its front door: a one-off
# `web` container, which compose attaches to the project's default network, and
# `http://clickstack:8080` — the service name, resolved by compose's own DNS,
# with no wall in the path and no port published. The Caddy wall stays exactly
# what it is: a wall for humans on the public address.
#
# NO `--no-deps`, AND THAT IS NOT A REGRESSION — it is the flag becoming
# STRUCTURAL. This act needs the NETWORK, not the dependency graph, and the flag
# was here because the `web` service declares redis and temporal, neither of
# which has anything to do with reconciling an alert route. The `oneoff` service
# declares no dependencies at all, so there is nothing left to skip; the
# property now lives in the compose file where it cannot be forgotten at a call
# site. `-e NAME` passthroughs (no `=`), act 2's form and act 2's reason: no
# value lands in argv, `ps` or a history file.
#
# THE PATH IS THE IMAGE'S, NOT THE BIND MOUNT'S, and the difference is
# load-bearing. `deploy/` is mounted read-only at `/deploy` (act 3 runs
# `/deploy/grants.sql.py` there), but `census.py` — which `apply.py` imports —
# finds the repository root by walking up from its own file looking for a
# directory holding both `apps/` and `manage.py`. From `/deploy/observability/
# alerts/` that walk finds nothing and the census raises; from
# `/app/deploy/observability/alerts/` it finds `/app`, which is the tree this
# image was built from. The census must be derived from the tree being released,
# and the image's copy is the only copy that satisfies both.
act
if [ -n "$WITHOUT_ALERTS" ]; then
    say "  SKIPPED — --without-alerts was typed on purpose."
    say "  The alert route is NOT reconciled to this tree. Run runbook Part 9, then"
    say "  re-run this script without the flag."
else
    # The default is the in-network service address. An environment that names
    # CLICKSTACK_URL still wins — a sink that has left the compose network is a
    # real deployment shape — but nothing derives a public address here any
    # more, because a public address is the one address this act cannot use.
    export CLICKSTACK_URL="${CLICKSTACK_URL:-http://clickstack:8080}"
    say "  sink ${CLICKSTACK_URL}  (in-network, from a one-off container)"
    set +e
    # `DJB_DEPLOY_NAMESPACE` rides the same whitelist, and it is not optional:
    # `apply.py` composes the alert bundle's name and the slot it points an
    # operator at from it, and REFUSES when it is unset rather than guessing a
    # namespace. A passthrough list that omitted it would refuse on every box,
    # with the value sitting right there in `deploy/.env`.
    compose run --rm -T \
        -e CLICKSTACK_URL -e CLICKSTACK_ADMIN_EMAIL -e CLICKSTACK_ADMIN_PASSWORD \
        -e SLACK_WEBHOOK_URL -e DJB_DEPLOY_NAMESPACE \
        oneoff python "$ALERTS_APPLY_IN_IMAGE"
    rc=$?
    set -e
    [ "$rc" = "0" ] || stopped "$rc"
fi

# =============================================================================
# 6 · recreate
# =============================================================================
# IDEMPOTENT: `up -d` reconciles rather than adds. Run twice against an
# unchanged image and an unchanged environment it recreates nothing and prints
# `up-to-date`; run it after a new image landed and it replaces the two
# containers with containers on that image. Two runs leave one `web` and one
# `worker`, exactly as one run does.
#
# IT IS A RECREATE AND NOT A RESTART, AND THAT IS THE OTHER HALF. `compose
# restart` bounces a container onto the SAME image, which was correct only while
# runbook step 34 had already recreated the app pair on the new image before the
# release began — which is precisely the window that is now closed. With step 34
# leaving `web` and `worker` alone, a restart here would leave the box serving
# the PREVIOUS tree with nothing anywhere saying so. So the one recreate in a
# deploy is this act, and it sits after act 2.
#
# AFTER THE MIGRATION, NEVER BEFORE IT — the ordering half this script owns.
# New code against an old schema is the window; within a release there is now
# no way to open it, because the recreate is act 6 and the migrate is act 2 in
# one process. And the runbook cannot open it either: the
# re-deploy path no longer recreates the pair ahead of this act, so the window
# is zero on both paths rather than on one.
#
# `--no-deps` keeps the blast radius exactly what `restart web worker` had: the
# two services named and nothing else. A release does not create a stack, and a
# `web` that was never started still fails here with compose's own error, which
# remains the correct answer to "you have not deployed yet".
act
set +e
compose up -d --no-deps web worker
rc=$?
set -e
[ "$rc" = "0" ] || stopped "$rc"

# =============================================================================
# 7 · readyz
# =============================================================================
# READ-ONLY, so trivially idempotent, and it is the act that turns "the commands
# ran" into "the deployment answers". A release whose last act is `restart` is a
# release that reports success while the container is in a crash loop.
#
# PROBED FROM INSIDE `readyz-prober`, with that container's own target, its own
# `--connect-to` and its own certificate posture (deploy/compose.yaml). Not a
# second description of where the deployment lives: the prober's is the one the
# alert route already watches, so this act and the 3am page agree by
# construction rather than by review.
act
say "  ${READYZ_TARGET} (up to ${READYZ_ATTEMPTS} attempts, ${READYZ_INTERVAL}s apart)"
# `if` rather than `[ … ] && …`: under `set -e` a bare AND-list whose test is
# false is a failed statement, and the release would end here with no message at
# all on any deployment that does not skip certificate verification.
curl_args=(-sS -o /dev/null -w '%{http_code}' --max-time 10)
if [ "${PROBE_INSECURE:-0}" = "1" ]; then curl_args+=(-k); fi
if [ -n "${PROBE_CONNECT_TO:-}" ]; then curl_args+=(--connect-to "$PROBE_CONNECT_TO"); fi

attempt=0
ready=""
while [ "$attempt" -lt "$READYZ_ATTEMPTS" ]; do
    attempt=$((attempt + 1))
    set +e
    code="$(compose exec -T readyz-prober curl "${curl_args[@]}" "$READYZ_TARGET" 2>/dev/null)"
    set -e
    if [ "$code" = "200" ]; then
        ready=1
        say "  ready after ${attempt} attempt(s) — HTTP 200"
        break
    fi
    say "  not ready yet (${attempt}/${READYZ_ATTEMPTS}, last answer: ${code:-none})"
    if [ "$attempt" -lt "$READYZ_ATTEMPTS" ]; then sleep "$READYZ_INTERVAL"; fi
done

if [ -z "$ready" ]; then
    echo "" >&2
    echo "!! release: STOPPED at act ${ACT_INDEX}/${TOTAL} — ${ACT_NAME}." >&2
    echo "   ${READYZ_TARGET} did not answer 200 within ${READYZ_ATTEMPTS} attempts" >&2
    echo "   (${READYZ_INTERVAL}s apart). The migration, the grants and the alert route" >&2
    echo "   were applied; the deployment is not serving." >&2
    echo "   Look at: docker compose -f $HERE/compose.yaml logs --tail 50 web worker" >&2
    echo "   Re-running this script from the top is safe and is the usual next move." >&2
    exit 1
fi

echo ""
if [ -n "$WITHOUT_ALERTS" ]; then
    say "RELEASED. ${TOTAL}/${TOTAL} acts complete — act 5 skipped by --without-alerts, so the"
    say "alert route is still reconciled to whatever tree last ran it."
else
    say "RELEASED. ${TOTAL}/${TOTAL} acts complete."
fi
# PERMANENTLY LOUD, on the last line a person reads. Act 1 printed each accepted
# fake with its detail and its remedy; this says it again where the verdict is,
# because a release that stood on a stand-in and ended on an unqualified
# "RELEASED" is the silent fake holding a permission slip.
if [ "$ACCEPTED_COUNT" -gt 0 ]; then
    say "…and it stood on ${ACCEPTED_COUNT} accepted fake(s): ${ACCEPTED_KEYS[*]}"
    say "Each is printed in full at act 1/${TOTAL} above, with what to do about it."
fi
exit 0
