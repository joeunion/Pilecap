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
# A backup of a database, and a copy of it somewhere the database is not.
#
#   ./scripts/backup.sh                    # -> backups/<db>-<timestamp>.dump
#   ./scripts/backup.sh /tmp/mine.dump     # somewhere else
#
#   ./scripts/backup.sh --to-dir /tmp/off  # ...and copy the object into a directory
#   ./scripts/backup.sh --to-s3 bkt/prefix # ...and copy the object to S3
#
#   ./scripts/backup.sh --stack djb-b1a --env-file deploy/.env.b1a --to-dir /tmp/off
#                                          # dump a DEPLOYMENT stack's database
#                                          # (deploy/compose.yaml) rather than
#                                          # this checkout's development one
#
# `pg_dump -Fc` — the custom format, not plain SQL — because that is what
# `pg_restore` can restore selectively, in parallel, and into a differently
# named database. A `.sql` file can only be replayed whole, into whatever
# database the `psql` session happens to be connected to.
#
# It runs `pg_dump` **inside the compose container**, for the same reason
# `db.sh` runs `psql` there: there is no `pg_dump` on the host, and a host one
# would be whatever version Homebrew last installed — a client older than the
# server refuses outright, and a newer one produces a dump the server's
# `pg_restore` cannot read.
#
# This is a laptop's backup, and its job is to make the restore drill real.
# A deployment's backups are its platform's — a managed snapshot, a WAL archive,
# a retention policy, an off-site copy — and none of that belongs in a script in
# an application repository. What DOES belong here is the drill
# (`restore_drill.sh`): an untested backup is a hypothesis.
#
# --- THE THREE THINGS ADDED FOR DEPLOYMENT, AND WHY EACH IS HERE --------------
#
# `--to-s3 <bucket/prefix>` and `--to-dir <path>` are ONE mechanism with two
# targets. Everything above the copy is identical — same `pg_dump`, same size
# refusal, same object — and only the last line differs. That is deliberate:
# the property a backup posture actually needs is "the dump leaves the machine
# the database is on", and a laptop has no S3. `--to-dir` is the laptop's
# stand-in for the copy, so the drill that proves the round trip can be
# performed by anyone, any time, with no account and no cost, and the S3 leg
# stays the same code path rather than a second one nobody exercises.
#
# `--stack <project>` exists because `deploy/compose.yaml` is a different
# database from this checkout's. Without it, "back up the deployment" means
# typing a `docker compose exec` line by hand, and a backup you type by hand is
# a backup with a typo in it on the night you need it. It reads the deployment's
# own environment file for the database name and the master role, and points
# `docker compose` at that project — the containers, not the host.
#
# THE `.origin` SIDECAR — the file that makes `restore_drill.sh --into-project`
# safe. A dump taken with `--stack` gets a companion `<dump>.origin` naming the
# project it came from. `restore_drill.sh` refuses to restore a dump into the
# stack that produced it, and it can only refuse if the dump remembers where it
# was born. Nothing else in this repository knows: a `.dump` is opaque, and the
# filename is a string an operator can retype wrong. The sidecar is written ONLY
# for `--stack` dumps — the no-flag laptop path produces exactly the file it
# always produced, and a dump that cannot be aimed at a live stack needs no
# guard rail.
set -euo pipefail

cd "$(dirname "$0")/.."

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

# Exit 2 is "I could not look" — an absent tool, an unreadable file, a flag
# nobody defined. Exit 1 is "I looked and it is wrong". The two are different
# causes and a caller may not treat them alike (docs/product/instruments.md).
cannot_look() {
    echo "$*" >&2
    exit 2
}

OUTPUT=""
TO_DIR=""
TO_S3=""
STACK=""
ENV_FILE="deploy/.env"

need_value() {
    [ -n "${2:-}" ] || cannot_look "$1 needs a value"
}

while [ $# -gt 0 ]; do
    case "$1" in
    --to-dir)
        need_value "$1" "${2:-}"
        TO_DIR="$2"
        shift 2
        ;;
    --to-s3)
        need_value "$1" "${2:-}"
        TO_S3="$2"
        shift 2
        ;;
    --stack)
        need_value "$1" "${2:-}"
        STACK="$2"
        shift 2
        ;;
    --env-file)
        need_value "$1" "${2:-}"
        ENV_FILE="$2"
        shift 2
        ;;
    -h | --help)
        usage
        exit 0
        ;;
    -* )
        # Never a silent default: an unknown flag is enforcement broken, exactly
        # as it is for the gate (CLAUDE.md, "a mistyped flag is never a silent
        # full run").
        cannot_look "unknown flag ${1}. Run $0 --help."
        ;;
    *)
        [ -z "$OUTPUT" ] || cannot_look "two output paths given: ${OUTPUT} and ${1}"
        OUTPUT="$1"
        shift
        ;;
    esac
done

# One value out of a `KEY='value'` environment file, without sourcing it. A
# `deploy/.env` carries every secret the deployment has; this script needs two
# non-secret names out of it and has no business exporting the rest into its own
# process, where a `set -x` or a crash dump would carry them.
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

# --- WHERE IS POSTGRES? The two answers, and the script asks ----------
#
# `--stack` used to assume ONE answer: a `db` service in `deploy/compose.yaml`,
# under the `laptop` profile, reachable as `docker compose exec -T db`. That is
# true of a laptop's deployment rehearsal and FALSE OF EVERY REAL BOX, where
# Postgres is RDS on the far end of a network socket and there is no `db`
# service to exec into. So `backup.sh --stack` could not back up the thing it
# existed for: it asked a container that was not there whether the database
# existed, got "no", and reported `database djb_staging does not exist` — which
# is how a staging bucket stayed empty while a backup script sat in the tree
# looking finished — the first real dump had to be taken by hand.
#
# THE ENV FILE ALREADY KNOWS. A box's env file carries `DATABASE_HOST`; a
# laptop rehearsal's does not (compose resolves `db` by service name). So the
# mode is DERIVED from the deployment's own environment rather than from a
# flag somebody has to remember — and the mode is PRINTED, because a backup
# that silently took the other path is the failure this is fixing.
#
# BOX MODE RUNS THE CLIENT IN A THROWAWAY CONTAINER, not on the host. There is
# no `pg_dump` on this host and a Homebrew one would be whatever version was
# last installed — a client older than the server refuses outright, and a newer
# one produces a dump the server's `pg_restore` cannot read (the reason
# `db.sh` runs `psql` in the container too). Pinning the client to the image
# `compose.yaml` already pins keeps ONE writer for the version.
#
# CROSS-MAJOR IS NOT THIS SCRIPT'S TO SOLVE, and it is not hidden either: if
# the server is a newer major than the pinned client, `pg_dump` says so in its
# own words and that status is this script's. Which major the template targets
# is ADR deploy-1's decision, not a backup script's.
PG_CLIENT_IMAGE="${DJB_PG_CLIENT_IMAGE:-}"
if [ -z "$PG_CLIENT_IMAGE" ]; then
    PG_CLIENT_IMAGE="$(sed -n 's/^[[:space:]]*image:[[:space:]]*\(postgres:[^[:space:]]*\).*/\1/p' compose.yaml | head -1)"
fi

BOX_HOST=""
BOX_PORT=""
BOX_PASSWORD=""
if [ -n "$STACK" ]; then
    [ -f "$ENV_FILE" ] || cannot_look "no environment file at ${ENV_FILE}: --stack needs the deployment's own env (--env-file <path>)"
    DATABASE_NAME="$(env_value DATABASE_NAME "$ENV_FILE")" ||
        cannot_look "no DATABASE_NAME in ${ENV_FILE}"
    POSTGRES_USER="$(env_value POSTGRES_USER "$ENV_FILE")" ||
        cannot_look "no POSTGRES_USER in ${ENV_FILE}"
    export DATABASE_NAME POSTGRES_USER
    BOX_HOST="$(env_value DATABASE_HOST "$ENV_FILE" || true)"
    if [ -n "$BOX_HOST" ]; then
        # BOX MODE. The master role does the dump (it is the one that can read
        # every table); its password is the one the env file pairs with it.
        BOX_PORT="$(env_value DATABASE_PORT "$ENV_FILE" || true)"
        BOX_PORT="${BOX_PORT:-5432}"
        BOX_PASSWORD="$(env_value POSTGRES_PASSWORD "$ENV_FILE" || true)"
        [ -n "$BOX_PASSWORD" ] ||
            cannot_look "no POSTGRES_PASSWORD in ${ENV_FILE}: box mode dumps as ${POSTGRES_USER} over the network and libpq needs its password"
        [ -n "$PG_CLIENT_IMAGE" ] ||
            cannot_look "no postgres image pinned in compose.yaml and no DJB_PG_CLIENT_IMAGE set: box mode needs a version-pinned client, and guessing one is how a dump becomes unrestorable"
        case "$BOX_HOST" in
        localhost | 127.0.0.1 | ::1 | 0.0.0.0)
            cannot_look "$(
                printf 'DATABASE_HOST=%s in %s, and box mode dumps from a container.\n' "$BOX_HOST" "$ENV_FILE"
                printf '   Inside that container %s is the CONTAINER'"'"'s loopback, not this\n' "$BOX_HOST"
                printf '   machine'"'"'s — so it would reach nothing, or something else entirely.\n'
                printf '   Name the host as the network sees it (an RDS endpoint), or use\n'
                printf '   host.docker.internal to mean the machine Docker runs on.\n'
            )"
            ;;
        esac
        # Host and length, never the value (the secrets doctrine).
        echo "- box mode: ${DATABASE_NAME} on ${BOX_HOST}:${BOX_PORT} as ${POSTGRES_USER}"
        echo "  client ${PG_CLIENT_IMAGE} (throwaway container; no host psql exists)"
        echo "  password from ${ENV_FILE}: ${#BOX_PASSWORD} characters"
    else
        # LAPTOP-REHEARSAL MODE, unchanged: the deployment's compose stack.
        # `docker compose` reads all three of these from the environment, so
        # every `docker compose` line below — including `db.sh`'s — reaches the
        # deployment stack instead of the development one, and no call site has
        # to know.
        echo "- compose mode: ${DATABASE_NAME} in project ${STACK} (no DATABASE_HOST in ${ENV_FILE})"
        export COMPOSE_PROJECT_NAME="$STACK"
        export COMPOSE_FILE="deploy/compose.yaml"
        export COMPOSE_PROFILES="laptop"
        export COMPOSE_ENV_FILES="$ENV_FILE"
    fi
fi

# One psql/pg_dump invocation, wherever Postgres turned out to be. In box mode
# it is a throwaway pinned client on the host network; otherwise it is the
# compose service, exactly as before.
# NO `--network host`: the shape this mode exists for is a managed Postgres at
# a real DNS name (RDS), which the default bridge resolves fine. Host
# networking would be a Docker-Desktop-shaped assumption bought for nothing.
#
# THE CONSEQUENCE IS REFUSED RATHER THAN DISCOVERED: inside a container,
# `localhost` and `127.0.0.1` are the CONTAINER'S loopback. A `DATABASE_HOST`
# of either would connect to nothing, or — worse on a box that happens to run
# something on 5432 — to the wrong Postgres. Neither is a dump. `host.docker
# .internal` is the documented way to mean "the machine Docker is running on",
# and it is what a laptop rehearsal of this mode uses.
box_client() {
    docker run --rm -i \
        -e PGPASSWORD="$BOX_PASSWORD" \
        -e PGSSLMODE="${PGSSLMODE:-prefer}" \
        "$PG_CLIENT_IMAGE" \
        "$@" -h "$BOX_HOST" -p "$BOX_PORT" -U "$POSTGRES_USER"
}

# shellcheck source=scripts/db.sh
source scripts/db.sh

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT="${OUTPUT:-backups/${DATABASE_NAME}-${STAMP}.dump}"

mkdir -p "$(dirname "$OUTPUT")"
if [ ! -e "$(dirname "$OUTPUT")/.gitignore" ]; then
    # A database dump is the last thing that should ever reach a git remote:
    # it is every customer's data, in one file, with no access control on it.
    printf '# Database dumps. Never committed — this is customer data in one file.\n*\n' \
        > "$(dirname "$OUTPUT")/.gitignore"
fi

# The existence question, asked wherever Postgres is. `db_exists` goes through
# `db.sh`'s compose exec and cannot see a box at all — asking it about RDS
# produced a false "does not exist" for a database that was right there.
db_present() {
    if [ -n "$BOX_HOST" ]; then
        local found
        found="$(printf 'SELECT 1 FROM pg_database WHERE datname = :%s\n' "'name'" \
            | box_client psql -v ON_ERROR_STOP=1 -d postgres -v name="$DATABASE_NAME" -tA 2>/dev/null || true)"
        [ "$found" = "1" ]
    else
        db_exists "$DATABASE_NAME"
    fi
}

if ! db_present; then
    # Exit 2, not 1. "There is no such database" is an I-COULD-NOT-LOOK
    # answer: this script never got as far as making a backup, so it has no
    # verdict about one. Reported as exit 1 — "I looked and it is wrong" — a
    # nightly that lost its database name reads identically to a nightly that
    # produced a bad dump, and only one of those is a backup problem. The
    # too-small-dump refusal below stays exit 1, because there the script DID
    # look: it made an object and the object is not a backup.
    cannot_look "database ${DATABASE_NAME} does not exist, so there is nothing to back up and no backup to judge"
fi

echo "Dumping ${DATABASE_NAME}..."
if [ -n "$BOX_HOST" ]; then
    box_client pg_dump --format=custom --no-owner --no-privileges \
        -d "$DATABASE_NAME" > "$OUTPUT"
else
    docker compose exec -T db \
        pg_dump --format=custom --no-owner --no-privileges \
        -U "$POSTGRES_USER" -d "$DATABASE_NAME" > "$OUTPUT"
fi

SIZE="$(wc -c < "$OUTPUT" | tr -d ' ')"
if [ "$SIZE" -lt 1024 ]; then
    # A dump of a database that was not there, or a container that printed an
    # error onto stdout, is a small file — and a small file that nobody looks at
    # is a backup everyone believes in. Refuse it here, at backup time, rather
    # than discovering it during the restore.
    echo "refusing a ${SIZE}-byte dump: that is not a backup" >&2
    rm -f "$OUTPUT"
    exit 1
fi

echo "  -> ${OUTPUT} (${SIZE} bytes)"

# The origin sidecar. Only for `--stack`: see the header.
ORIGIN=""
if [ -n "$STACK" ]; then
    ORIGIN="${OUTPUT}.origin"
    {
        printf '# Where this dump came from. Read by scripts/restore_drill.sh --into-project,\n'
        printf '# which refuses to restore a dump into the stack that produced it.\n'
        printf 'project=%s\n' "$STACK"
        printf 'database=%s\n' "$DATABASE_NAME"
        printf 'env_file=%s\n' "$ENV_FILE"
        printf 'taken_at=%s\n' "$STAMP"
        printf 'tree=%s\n' "$(git rev-parse 'HEAD^{tree}' 2>/dev/null || echo unknown)"
    } > "$ORIGIN"
    echo "  -> ${ORIGIN} (origin: project ${STACK}, database ${DATABASE_NAME})"
fi

# --- The copy. One mechanism, two targets; everything above was identical. ----

if [ -n "$TO_DIR" ]; then
    mkdir -p "$TO_DIR"
    cp "$OUTPUT" "$TO_DIR/"
    if [ -n "$ORIGIN" ]; then cp "$ORIGIN" "$TO_DIR/"; fi
    echo "  copied to ${TO_DIR}/$(basename "$OUTPUT") ($(wc -c < "${TO_DIR}/$(basename "$OUTPUT")" | tr -d ' ') bytes)"
fi

if [ -n "$TO_S3" ]; then
    command -v aws > /dev/null 2>&1 ||
        cannot_look "no aws client on PATH: --to-s3 cannot look. On a laptop use --to-dir, which is the same code path to a different target."
    # `s3://` is added here rather than demanded, so the flag's argument is the
    # `bucket/prefix` the criteria and the runbook name and not a URL scheme
    # somebody has to remember to type.
    TARGET="s3://${TO_S3#s3://}"
    TARGET="${TARGET%/}/$(basename "$OUTPUT")"
    aws s3 cp "$OUTPUT" "$TARGET"
    if [ -n "$ORIGIN" ]; then aws s3 cp "$ORIGIN" "${TARGET}.origin"; fi
    echo "  copied to ${TARGET}"
fi
