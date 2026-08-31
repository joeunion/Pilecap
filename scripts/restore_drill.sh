#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made. Measured on this tree:
#
#   zsh scripts/queue_cited.sh   exit 2 blaming the TREE ("this is not a
#                                checkout root") for zsh's word-splitting
#   zsh scripts/kill_mine.sh     an ordinary-looking census of nothing
#   sh  scripts/sweep.sh         "lifecycle.sh: line 152: syntax error"
#
# A wrong shell here does not crash. It ANSWERS, and the answer looks like the
# tree's fault.
#
# TWO TESTS, because on macOS `/bin/sh` IS bash: BASH_VERSION is set under
# `sh x.sh` and only POSIX MODE tells the two apart (SHELLOPTS carries
# `posix`). On Linux `/bin/sh` is dash and the first test is the one that
# fires. Neither test alone covers both machines.
#
# A SOURCED library must never carry this. There the interpreter is the
# caller's ON PURPOSE and an `exit` would kill the caller's shell — the
# argument is scripts/db.sh's, at scripts/db.sh:50-57, and it is why db.sh is
# the one executable in this tree deliberately without a belt.
[ -n "${BASH_VERSION:-}" ] || {
    echo "${0##*/}: must run under bash — not sh, not zsh. Try \`bash ${0}\`." >&2
    exit 2
}
case ":${SHELLOPTS:-}:" in
*:posix:*)
    echo "${0##*/}: bash is in POSIX mode — which is what \`sh ${0}\` does on a" >&2
    echo "  machine whose /bin/sh is bash. Try \`bash ${0}\`." >&2
    exit 2
    ;;
esac
# Restore a backup, prove it is real, and never become the hazard.
#
#   ./scripts/restore_drill.sh                     # the newest dump in backups/
#   ./scripts/restore_drill.sh path/to/one.dump    # a specific one
#
#   ./scripts/restore_drill.sh path/to/one.dump \
#       --into-project djb-b1b --env-file deploy/.env.b1b
#                                                  # restore into a SECOND
#                                                  # deployment stack's own
#                                                  # database — not a scratch one
#
# **An untested backup is a hypothesis.** The failure this exists to catch is
# not "the backup job did not run" — that one gets noticed — it is the backup
# that runs nightly for a year and turns out to restore into an empty schema,
# or a schema the current code cannot migrate, or one where a column the
# application needs was added after the dump. None of that is visible in the
# file. It is visible here.
#
# --- TWO MODES, AND THE SAME REFUSAL UNDER BOTH -------------------------------
#
# DEFAULT (scratch): restores into `<db>_drill`, created and dropped by this
# script, never the worktree's own database. Nothing it does can touch real
# data. This mode is unchanged from the day it was written.
#
# `--into-project <project>`: restores into a *deployment* stack's live
# application database — `deploy/compose.yaml` under that compose project. This
# is the mode that turns "backups that restore" from a claim about a scratch
# database into a claim about a deployment: the dump comes off stack A and the
# row comes back through stack B's own REST door. It is DESTRUCTIVE to the
# target stack's application database, by design, and it is therefore the mode
# that needs a guard rail:
#
#   **THE RESTORE TARGET IS NEVER THE SOURCE.** A dump taken with
#   `backup.sh --stack` carries a `<dump>.origin` sidecar naming the project it
#   came from. This script reads it and REFUSES BY NAME when the target project
#   is that project — because the failure being prevented is not a typo in a
#   database name, it is a tired operator at 3am aiming the drill at the stack
#   they are trying to protect. A dump with no `.origin` cannot be aimed at a
#   live stack AT ALL (exit 2, "I could not look"): unable to prove the target
#   is not the source is not the same as proving it is not.
#
# What it asserts, in order, under both modes:
#   1. `pg_restore` completes;
#   2. the restored database has tables, and specifically the ones this
#      application cannot start without;
#   3. `migrate --check` says the restored schema is what today's code expects.
#
# (3) is the one that earns the drill. A dump that restores cleanly but is three
# migrations behind is a backup you cannot deploy onto without a migration
# window nobody has planned.
#
# --- AND IT SAYS WHEN IT DIED -------------------------------------------------
#
# Three states, all three legible: `RESTORE DRILL PASSED` (one of two forms),
# `RESTORE DRILL DID NOT FINISH (exit N)`, or neither — which then means the
# drill is still running. See the death guard beside the cleanup trap.
set -euo pipefail

cd "$(dirname "$0")/.."

# Exit 2 is "I could not look"; exit 1 is "I looked and it is wrong"
# (docs/product/instruments.md). A refused restore is a 1: the script looked at
# the origin, at the target, and said no.
cannot_look() {
    echo "$*" >&2
    exit 2
}

DUMP=""
INTO_PROJECT=""
ENV_FILE="deploy/.env"

need_value() {
    [ -n "${2:-}" ] || cannot_look "$1 needs a value"
}

while [ $# -gt 0 ]; do
    case "$1" in
    --into-project)
        need_value "$1" "${2:-}"
        INTO_PROJECT="$2"
        shift 2
        ;;
    --env-file)
        need_value "$1" "${2:-}"
        ENV_FILE="$2"
        shift 2
        ;;
    -h | --help)
        sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    -*)
        cannot_look "unknown flag ${1}. Run $0 --help."
        ;;
    *)
        [ -z "$DUMP" ] || cannot_look "two dumps given: ${DUMP} and ${1}"
        DUMP="$1"
        shift
        ;;
    esac
done

if [ -z "$DUMP" ]; then
    # Newest first, and the glob is quoted out of `ls` so a missing directory is
    # an empty result rather than a shell error.
    DUMP="$(find backups -name '*.dump' -type f 2>/dev/null | sort | tail -1)"
fi

if [ -z "$DUMP" ] || [ ! -f "$DUMP" ]; then
    echo "no dump to drill with. Run ./scripts/backup.sh first." >&2
    exit 1
fi

# One value out of a `KEY=value` file, without sourcing it (see backup.sh).
env_value() {
    local key="$1" file="$2" line
    line="$(grep -E "^${key}=" "$file" | tail -1 || true)"
    [ -n "$line" ] || return 1
    line="${line#*=}"
    case "$line" in
    \'*\')
        line="${line#\'}"
        line="${line%\'}"
        ;;
    \"*\")
        line="${line#\"}"
        line="${line%\"}"
        ;;
    esac
    printf '%s' "$line"
}

# --- The refusal, before anything is created or dropped ----------------------

if [ -n "$INTO_PROJECT" ]; then
    ORIGIN="${DUMP}.origin"
    if [ ! -f "$ORIGIN" ]; then
        cannot_look "$(
            printf 'refusing to restore into a LIVE stack from a dump with no origin.\n'
            printf '   %s has no %s beside it, so this script cannot prove the target\n' "$DUMP" "$(basename "$ORIGIN")"
            printf '   stack %s is not the stack the dump came from. Take the dump with\n' "$INTO_PROJECT"
            printf '   `backup.sh --stack <project>`, which writes the sidecar.\n'
        )"
    fi
    SOURCE_PROJECT="$(env_value project "$ORIGIN")" ||
        cannot_look "no project= line in ${ORIGIN}: the origin is unreadable, so the target cannot be cleared"
    SOURCE_DATABASE="$(env_value database "$ORIGIN" || true)"
    if [ "$SOURCE_PROJECT" = "$INTO_PROJECT" ]; then
        printf '!! REFUSED: the restore target is the source.\n' >&2
        printf '   dump      %s\n' "$DUMP" >&2
        printf '   origin    project %s (database %s)\n' "$SOURCE_PROJECT" "${SOURCE_DATABASE:-?}" >&2
        printf '   target    project %s\n' "$INTO_PROJECT" >&2
        printf '   A restore drill that can overwrite the thing it is protecting is a\n' >&2
        printf '   worse risk than not drilling. Bring up a second stack\n' >&2
        printf '   (deploy/compose.second.yaml) and aim at that instead.\n' >&2
        exit 1
    fi

    [ -f "$ENV_FILE" ] || cannot_look "no environment file at ${ENV_FILE}: --into-project needs the target stack's own env (--env-file <path>)"
    DATABASE_NAME="$(env_value DATABASE_NAME "$ENV_FILE")" ||
        cannot_look "no DATABASE_NAME in ${ENV_FILE}"
    POSTGRES_USER="$(env_value POSTGRES_USER "$ENV_FILE")" ||
        cannot_look "no POSTGRES_USER in ${ENV_FILE}"
    export DATABASE_NAME POSTGRES_USER
    # Every `docker compose` below — this file's and `db.sh`'s — now reaches the
    # target stack rather than the development one.
    export COMPOSE_PROJECT_NAME="$INTO_PROJECT"
    export COMPOSE_FILE="deploy/compose.yaml"
    export COMPOSE_PROFILES="laptop"
    export COMPOSE_ENV_FILES="$ENV_FILE"
fi

# shellcheck source=scripts/db.sh
source scripts/db.sh

if [ -n "$INTO_PROJECT" ]; then
    TARGET_DB="$DATABASE_NAME"
else
    TARGET_DB="${DATABASE_NAME}_drill"
fi

cleanup() {
    if [ -z "$INTO_PROJECT" ] && db_exists "$TARGET_DB"; then
        db_drop "$TARGET_DB" > /dev/null
    fi
}

# --- THE DEATH GUARD ---------------------------------------------------------
#
# A drill has three states and only two of them were legible. It could PASS,
# saying so in one of the two sentences at the bottom of this file. It could be
# STILL RUNNING. And it could be GONE — killed at 3am, or tripped by `set -e`
# on `pg_restore` or on `migrate --check` — in which case the transcript ended
# at whatever the failing command last said and looked exactly like a drill
# still working. "No PASSED line yet" meant either "wait" or "this proved
# nothing", and nothing in the output told them apart.
#
# The sentinel covers everything BELOW this line, which is precisely the region
# where the drill creates, restores and asserts. Every refusal ABOVE it is
# declared to fire "before anything is created or dropped", exits with its own
# sentence, and runs with no trap installed — so those transcripts are byte-for-
# byte what they were. Below it, a deliberate `exit 1` or `exit 2` gets the
# sentinel too, and that is deliberate: those runs also did not finish, and a
# guard with a per-site flag to remember is a guard somebody forgets on the one
# site that mattered.
DRILL_FINISHED=0

on_exit() {
    local status=$?
    # The sentence comes BEFORE cleanup speaks: a death has to be legible even
    # when what follows it is noisy, and cleanup runs real commands.
    if [ "$DRILL_FINISHED" -eq 0 ]; then
        printf '\nRESTORE DRILL DID NOT FINISH (exit %s)\n' "$status" >&2
        printf '   Neither PASSED line was reached, so nothing has been proven about\n' >&2
        printf '   %s. This is a death, not a pass and not a drill still running.\n' "$DUMP" >&2
    fi
    # The scratch database is dropped whether the drill passed, failed or died:
    # one left behind is the one somebody eventually points an application at. A
    # stack's own database is NOT dropped on the way out — it is the stack's,
    # and the operator who asked for the restore wants what the restore
    # produced. `|| true` because `set -e` inside an EXIT trap would skip the
    # line below, and losing the exit code to a cleanup hiccup is the bug this
    # function exists to not have.
    cleanup || true
    # Captured first, re-raised last: cleanup cannot overwrite the status a
    # caller branches on. The 0/1/2 grammar is untouched by this trap.
    exit "$status"
}

# A signal has to become an exit before the EXIT trap can see it at all. 128+n
# is the shell's own grammar for "died on signal n", so the sentinel names the
# code the caller would have seen anyway.
on_signal() {
    trap - INT TERM HUP
    exit "$((128 + $1))"
}
trap 'on_signal 2' INT
trap 'on_signal 15' TERM
trap 'on_signal 1' HUP
trap on_exit EXIT

if [ -n "$INTO_PROJECT" ]; then
    echo "Restoring ${DUMP} into the LIVE database of stack ${INTO_PROJECT} (${TARGET_DB})"
    echo "  origin: project ${SOURCE_PROJECT} — different stack, so the drill may proceed."
    # The application holds connections and would reconnect the instant the
    # database came back with a half-restored schema. Stop the two containers
    # that speak to it, restore, start them again — the stack's organs (db,
    # redis, temporal, zitadel, caddy) stay up throughout.
    docker compose stop web worker > /dev/null
    db_drop "$TARGET_DB" > /dev/null
    db_create "$TARGET_DB" > /dev/null
else
    cleanup
    db_create "$TARGET_DB" > /dev/null
    echo "Restoring ${DUMP} into ${TARGET_DB}..."
fi

docker compose exec -T db \
    pg_restore --no-owner --no-privileges --exit-on-error \
    -U "$POSTGRES_USER" -d "$TARGET_DB" < "$DUMP"

if [ -n "$INTO_PROJECT" ]; then
    # THE PRIVILEGES WENT WITH THE OLD DATABASE. A restore does not replace a
    # schema in place; it drops a database and builds another one, and GRANTs
    # are per-database. `--no-privileges` on both sides is deliberate (a dump
    # must be restorable into a cluster that never heard of this deployment's
    # roles), so the restored tables are owned by the master role and readable
    # by nobody else — and the app, which connects as its own role, would come
    # back up unable to read a single row it just restored. That is the
    # "restore that looked like it worked" this drill exists to make impossible,
    # so the release grant step is part of the restore and not a line in a
    # runbook somebody performs from memory at 3am.
    #
    # WITHOUT `--create-role`, and that is the point: a Postgres role is
    # CLUSTER-wide and survives its database being dropped, so the role the
    # stack's release step created is still there. Re-creating it would need its
    # password, and this script would then have to read a secret out of the
    # deployment's environment file. It reads a name instead. If the role is
    # genuinely absent, psql says so by name and the operator runs the release
    # step — a loud, correct failure rather than a secret in a process.
    APP_ROLE="$(env_value DATABASE_USER "$ENV_FILE")" ||
        cannot_look "no DATABASE_USER in ${ENV_FILE}: cannot re-grant the restored database"
    echo "Re-granting the restored database to the application role ${APP_ROLE}..."
    docker compose run --rm -T web python /deploy/grants.sql.py --role "$APP_ROLE" \
        > /tmp/djb-restore-grants.sql
    docker compose exec -T db \
        psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$TARGET_DB" -f - \
        < /tmp/djb-restore-grants.sql > /dev/null
    rm -f /tmp/djb-restore-grants.sql
    GRANTED="$(db_psql -d "$TARGET_DB" -tAc \
        "SELECT has_table_privilege('${APP_ROLE}', 'core_tenant', 'SELECT')")"
    if [ "$GRANTED" != "t" ]; then
        echo "the restored database is not readable by ${APP_ROLE}: the grant step did not take" >&2
        exit 1
    fi
    echo "  ${APP_ROLE} can read the restored tables"
fi

TABLES="$(db_psql -d "$TARGET_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")"
echo "  restored ${TABLES} tables"
if [ "${TABLES:-0}" -lt 1 ]; then
    echo "the restore produced no tables: that dump is not a backup" >&2
    exit 1
fi

# The tables the application genuinely cannot start without. Not an exhaustive
# list — an exhaustive list would have to be edited by every rung that adds a
# model, and would then be edited without being thought about.
for required in accounts_user core_tenant core_membership django_migrations; do
    found="$(db_psql -d "$TARGET_DB" -tAc \
        "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '${required}'")"
    if [ "$found" != "1" ]; then
        echo "the restored database has no ${required} table" >&2
        exit 1
    fi
done

echo "Checking the restored schema against today's migrations..."
if [ -n "$INTO_PROJECT" ]; then
    # Inside the stack's own web image, against the stack's own database, with
    # the stack's own settings — the host's `uv` environment can neither see
    # that database nor speak for that deployment.
    docker compose start web worker > /dev/null
    docker compose run --rm -T web python manage.py migrate --check
else
    DATABASE_NAME="$TARGET_DB" DATABASE_URL="" \
        DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.local}" \
        uv run python manage.py migrate --check
fi

echo ""
# The one place this is set. Everything above here that exits — a refusal, a
# failed assertion, a killed process — leaves it 0 and gets the sentinel.
DRILL_FINISHED=1
if [ -n "$INTO_PROJECT" ]; then
    echo "RESTORE DRILL PASSED: ${DUMP} restores into stack ${INTO_PROJECT}'s own"
    echo "database and today's code can run the schema it produced."
else
    echo "RESTORE DRILL PASSED: ${DUMP} restores into a schema today's code can run."
fi
