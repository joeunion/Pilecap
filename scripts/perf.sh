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
# The seeded-scale harness runner (ADR perf-1).
#
#   ./scripts/perf.sh                       seed-if-stale, then run every perf/measure_*.py
#   ./scripts/perf.sh --seed-only           provision + seed (or report the stamp hit) + census
#   ./scripts/perf.sh --double <axis>       the doubling tier: the world with ONE axis at x2
#   ./scripts/perf.sh --force               seed even though another checkout's world exists
#   ./scripts/perf.sh [modules...]          run only the named measurement modules
#
# ONE SEEDED WORLD PER MACHINE IS THE NORM, AND THIS SCRIPT SAYS SO.
# A world is ~0.6 GB and the harness runs in one checkout at a time anyway, so a
# second one is almost always a checkout that seeded, moved on, and never
# reaped. Left unchecked, enough of them fill a machine's disk: a data volume
# hits 100%, tool calls start failing with ENOSPC, and Docker needs its backend
# killed. Nothing warned, because nothing was looking. So: before creating a
# world, this script counts the `_perf` databases that are NOT the one it is
# about to use, and REFUSES while any exists — naming them, and naming the
# broom. `--force` proceeds, because two worlds is occasionally exactly what
# somebody means; a silent fifteenth never is.
#
# The perf database is `<checkout-derived-name>_perf` — the B2-P1 per-checkout
# discipline extended, so two checkouts never share a perf world either. A
# DATABASE_NAME already in the environment is honoured ONLY if it already ends
# in `_perf`; anything else is refused (exit 2), because this script drops and
# re-creates the database it points at whenever the spec stamp is stale, and a
# refusal beats a guess wherever a drop is on the table. `perf/seed.py` holds
# the same refusal as a belt.
#
# Re-seeding happens exactly when the ScaleSpec changes: the stamp tenant's
# slug embeds the spec hash (`perf-stamp-<hash12>`), `perf/seed.py status`
# reads it, and a miss means drop + re-create + migrate + seed. A hit skips
# seeding entirely — run 2 with an unchanged spec costs one status query.
#
# Measurement modules are passed to pytest as EXPLICIT file arguments:
# `perf/measure_*.py` deliberately does not match `python_files`, so directory
# discovery (the default suite, `--loop`, anyone's stray `uv run pytest`) can
# never collect a measurement. `-m perf` narrows further; `perf/conftest.py`
# marks everything in the package.
#
# Settings are `config.settings.test` for every leg — seeding and measuring
# must agree on the encryption key, the in-memory channel layer, and the
# nothing-dials-Temporal floor. Wall-clock never appears in a criterion; the
# instruments are in `perf/measure.py`, and it governs them.

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

MODE="run"
DOUBLED_AXIS=""
FORCE=0
MODULES=()
while [ $# -gt 0 ]; do
    case "$1" in
        --seed-only) MODE="seed-only" ;;
        --force) FORCE=1 ;;
        --double)
            shift
            [ $# -gt 0 ] || { echo "!! --double needs an axis name" >&2; exit 2; }
            DOUBLED_AXIS="$1"
            ;;
        --*)
            echo "!! unknown flag '$1': perf.sh takes --seed-only, --double <axis>, --force, modules" >&2
            exit 2
            ;;
        *) MODULES+=("$1") ;;
    esac
    shift
done

# --- The database: derived per checkout, always suffixed `_perf` -------------
PRESET="${DATABASE_NAME:-}"
if [ -n "$PRESET" ]; then
    case "$PRESET" in
        *_perf) ;;
        *)
            echo "!! DATABASE_NAME='${PRESET}' does not end in '_perf'." >&2
            echo "   perf.sh drops and re-creates the database it points at when the spec" >&2
            echo "   stamp is stale, so it refuses any name that is not a perf database." >&2
            echo "   Unset DATABASE_NAME to use the derived '<checkout>_perf', or export" >&2
            echo "   one that ends in '_perf' deliberately." >&2
            exit 2
            ;;
    esac
    # shellcheck source=scripts/db.sh
    source scripts/db.sh   # the preset wins inside; functions come along
else
    # shellcheck source=scripts/db.sh
    source scripts/db.sh   # derives djb_<branch>_<pathhash>
    DATABASE_NAME="${DATABASE_NAME}_perf"
    export DATABASE_NAME
fi
case "$DATABASE_NAME" in
    *_perf) ;;
    *) echo "!! internal: perf database name '${DATABASE_NAME}' lacks '_perf'" >&2; exit 2 ;;
esac

export DJANGO_SETTINGS_MODULE="config.settings.test"
# The axis travels as a CLI argument, never as an environment variable (the
# plan's settled "no new env vars" holds). The seeded world is self-describing
# — the stamp names its spec — so the pytest run below needs no flag at all:
# perf/conftest.py reads which world it is in off the stamp.
SEED_ARGS=()
if [ -n "$DOUBLED_AXIS" ]; then
    SEED_ARGS=(--double "$DOUBLED_AXIS")
    echo "- doubling tier: axis '${DOUBLED_AXIS}' at x2 (everything else unchanged)"
fi
echo "- perf database: ${DATABASE_NAME}"

# --- One world per machine, unless somebody says otherwise ------------
#
# Counted from the SERVER, not from a directory listing: a world left by a
# checkout that no longer exists is exactly the kind this is looking for, and
# nothing on disk remembers it. `_` is a LIKE wildcard, so the pattern escapes
# it — the scope must be the names it says, not the names it rhymes with.
#
# Exit 1, not 2: this script LOOKED, and what it found is wrong. (Exit 2 here
# stays what it has always been — a name it cannot trust, a flag nobody defined.
# `restore_drill.sh`'s target-is-the-source refusal is the same shape.)
OTHER_WORLDS="$(db_query "
    SELECT string_agg(datname, E'\n' ORDER BY datname)
    FROM pg_database
    WHERE datname LIKE 'djb\\_%\\_perf' AND datname <> :'mine'
" -v mine="$DATABASE_NAME" -tA || true)"
if [ -n "$OTHER_WORLDS" ] && [ "$FORCE" -eq 0 ]; then
    echo "!! REFUSING to seed a second perf world: this server already carries these." >&2
    printf '%s\n' "$OTHER_WORLDS" | sed 's/^/     /' >&2
    echo "   Each is ~0.6 GB and the harness runs in one checkout at a time, so a" >&2
    echo "   second world is almost always a checkout that seeded and moved on —" >&2
    echo "   enough of them will fill the disk." >&2
    echo "   Reap them:  ./scripts/db_sweep.sh --sweep --perf     (this checkout's own)" >&2
    echo "               ./scripts/db_sweep.sh --all-checkouts --orphans --roots <dir>" >&2
    echo "                   (census first: a world you cannot account for may be a live" >&2
    echo "                    sibling clone's, and that mode drops nothing without" >&2
    echo "                    --sweep --force-foreign)" >&2
    echo "   Or say you meant it:  $0 --force" >&2
    exit 1
fi
if [ -n "$OTHER_WORLDS" ]; then
    echo "- --force: seeding beside $(printf '%s\n' "$OTHER_WORLDS" | wc -l | tr -d ' ') other perf world(s) on this server"
fi

# --- Provision + seed-if-stale ----------------------------------------------
db_create
uv run python manage.py migrate --no-input

STAMP_STATUS=0
uv run python -m perf.seed status ${SEED_ARGS[@]+"${SEED_ARGS[@]}"} || STAMP_STATUS=$?
if [ "$STAMP_STATUS" -eq 0 ]; then
    echo "- world is current; seeding skipped"
elif [ "$STAMP_STATUS" -eq 3 ]; then
    echo "- stamp stale: resetting ${DATABASE_NAME} and seeding the declared world"
    db_drop "$DATABASE_NAME"
    db_create
    uv run python manage.py migrate --no-input
    uv run python -m perf.seed seed ${SEED_ARGS[@]+"${SEED_ARGS[@]}"}
else
    echo "!! perf/seed.py status failed (exit ${STAMP_STATUS})" >&2
    exit "$STAMP_STATUS"
fi

if [ "$MODE" = "seed-only" ]; then
    echo "- census (the world, checked against the spec):"
    uv run python -m perf.seed census ${SEED_ARGS[@]+"${SEED_ARGS[@]}"}
    exit 0
fi

# --- Measure ----------------------------------------------------------------
if [ ${#MODULES[@]} -eq 0 ]; then
    while IFS= read -r module; do
        MODULES+=("$module")
    done < <(ls perf/measure_*.py 2>/dev/null || true)
fi
if [ ${#MODULES[@]} -eq 0 ]; then
    echo "- no measurement modules yet (perf/measure_*.py) — the M-rungs bring them."
    echo "  The world is seeded and current; nothing to run."
    exit 0
fi
echo "- running: ${MODULES[*]}"
uv run pytest -m perf "${MODULES[@]}"
