#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
# The test suite. Never pipe this: a pipe replaces pytest's exit status with the
# pipe's, and a green-looking red run is the one failure mode a gate cannot
# survive. Run it directly and read its exit code.
#
# Everything after the script name goes to pytest, so the three shapes worth
# knowing (ADR gate-1):
#
#   ./scripts/test.sh                       serial, RANDOM order, fresh seed
#   ./scripts/test.sh -n <share>            the slot share — what both gate legs
#                                           in check.sh run (`-n $GATE_SLOT_WORKERS`,
#                                           quality/djb/hold.py::worker_count); `-n auto` is REFUSED
#   ./scripts/test.sh --randomly-seed=N     replay the order a red run printed
#   ./scripts/test.sh -p no:randomly        declared collection order
#
# `-n auto` IS REFUSED HERE, and the sentence it used to carry — "one worker per
# core, what both gate legs run" — was stale: the gate legs run `-n
# $GATE_SLOT_WORKERS`, the SHARE of this box's cores that one pytest slot owns
# (`quality/djb/hold.py`'s `slot_workers`). `auto` takes
# every core, beside gates that are each holding a share, and mints one
# `test_$DATABASE_NAME_gwN` database per worker while it does it — the
# shared-box contention this refusal exists to stop.
#
# Workers are also not a default here or in pyproject's `addopts`: each xdist
# worker creates and migrates its own test database, so a ten-core machine would
# pay ten database creations to run `./scripts/test.sh apps/core/tests/
# test_ids.py`. The gate wants the workers; a builder narrowing one failure does
# not. Per-worker databases nest inside this checkout's own: pytest-django
# suffixes the derived name, giving `test_$DATABASE_NAME_gw0..gwN`.
#
# Those per-worker databases are DROPPED at the end of the run, and the drop is
# not free: a thread that still holds a connection makes Postgres refuse it, and
# pytest-django turns that refusal into a warning rather than a failure — a
# green run with a database left on disk. `apps/conftest.py` releases the
# long-lived pools before the drop is attempted; `scripts/db_sweep.sh` is the
# census that proves it stayed released, and the broom for anything older.
#
# pytest-randomly prints `Using --randomly-seed=<n>` at the top of every run.
# That line is the whole reproduction story — a red order is replayed by handing
# the number back, and the full gate's two passes share one seed on purpose so
# that a pass-2 red means state left behind rather than a different order.
set -uo pipefail

cd "$(dirname "$0")/.."

if [ -f scripts/db.sh ]; then
    # shellcheck source=scripts/db.sh
    source scripts/db.sh
fi

# --- the slot share: one number, derived where the gate derives it -----------
#
# WHAT THIS CLOSES. A direct `uv run pytest … -n auto` takes no pytest slot and
# reads no ceiling, so on a ten-core box it starts ten workers beside two gates
# that are each running their five — load that put a sibling platform's Postgres
# into recovery, and ten `_gwN` databases created to run one module. The slot
# semaphore is the mechanism; the only thing missing was that a builder's own
# run never asked it anything.
#
# ONE DERIVATION, NEVER A SECOND OPINION: `gate_slots_total` and
# `gate_slot_workers` are `quality/djb/hold.py`'s own verbs over its own
# constants, and they are the same two calls
# `gate_slot_acquire` makes. An inherited value wins over deriving one, which is
# what lets a caller that already took a slot hand its share down rather than
# have this re-answer the question.
DJB_PYTEST_SHARE=""
if [ -n "${DJB_GATE_SLOT_WORKERS:-}" ]; then
    DJB_PYTEST_SHARE="$DJB_GATE_SLOT_WORKERS"
elif [ -n "${DJB_PYTEST_MAX_WORKERS:-}" ]; then
    DJB_PYTEST_SHARE="$DJB_PYTEST_MAX_WORKERS"
else
    DJB_PYTEST_SLOTS=$(python3 -E -S -m quality.djb.hold gate_slots_total 2>/dev/null || true)
    if [ -n "$DJB_PYTEST_SLOTS" ]; then
        DJB_PYTEST_SHARE=$(python3 -E -S -m quality.djb.hold gate_slot_workers "$DJB_PYTEST_SLOTS" 2>/dev/null || true)
    fi
    unset DJB_PYTEST_SLOTS
fi
if [ -n "$DJB_PYTEST_SHARE" ]; then
    DJB_PYTEST_MAX_WORKERS="$DJB_PYTEST_SHARE"
    export DJB_PYTEST_MAX_WORKERS
fi

# `-n auto` (and `logical`, its bigger sibling) is REFUSED — exit 2, naming the
# derivation and the number it would have used. Exit 2 and not 1: nothing was
# judged, and a refusal that reads as a test failure is a refusal somebody
# re-runs instead of reading. Every spelling pytest-xdist accepts is checked,
# because a refusal that only knows `-n auto` teaches `-nauto`.
DJB_PREV_ARG=""
DJB_REFUSE_AUTO=""
for DJB_ARG in "$@"; do
    case "$DJB_ARG" in
    -nauto | -nlogical | --numprocesses=auto | --numprocesses=logical)
        DJB_REFUSE_AUTO=1
        ;;
    auto | logical)
        case "$DJB_PREV_ARG" in
        -n | --numprocesses) DJB_REFUSE_AUTO=1 ;;
        esac
        ;;
    esac
    DJB_PREV_ARG="$DJB_ARG"
done
if [ -n "$DJB_REFUSE_AUTO" ]; then
    echo "!! REFUSING '-n auto': this box's cores are already shared." >&2
    echo "   The gate splits them into pytest SLOTS and each slot holder runs its share:" >&2
    echo "   gate_slot_workers (quality/djb/hold.py) says ${DJB_PYTEST_SHARE:-(underivable: python3 -m quality.djb.hold did not answer)} on this box." >&2
    echo "   'auto' takes every core beside them and mints one" >&2
    echo "   test_\$DATABASE_NAME_gwN database per worker." >&2
    echo "   Run it with the share:  ./scripts/test.sh -n ${DJB_PYTEST_SHARE:-<share>} \"\$@\"" >&2
    echo "   Nothing ran." >&2
    exit 2
fi
unset DJB_ARG DJB_PREV_ARG DJB_REFUSE_AUTO

# --- the per-worker test databases CLONE a template when one exists ---
#
# WHAT THIS FUNDS. Every xdist worker creates and migrates its own
# `test_<DATABASE_NAME>_gwN`. A measurement found the bill is the same shape on
# every run: ten `--durations` setup entries of ~4.5-6s, one per worker, before a
# single assertion — ~60 CPU-seconds a pass, paid twice by the full gate. An
# earlier pass built the cure (a migrated, machine-global template published as
# `djb_tmpl_<migration key>`) and wired it to `db_create` only, so the SUITE went
# on migrating ten times. This is the line that was specified in
# `apps/conftest.py` and never written; a later verification pass found it
# missing.
#
# WHY HERE AND NOT IN `scripts/db.sh`. Knowing whether a template EXISTS costs a
# `docker compose exec … psql` round trip (`db_psql`), and db.sh is sourced by
# things that have no server at all — `quality/tests/test_db.py` and
# `test_pm_merge.sh` build scratch checkouts under `mktemp -d` and source it
# there. Paying a docker round trip at SOURCE time would put a slow failure into
# every one of those cases. This script is the one place that is about to run
# the suite, so the server is up by construction and the round trip is paid
# exactly when it buys something.
#
# WHY NOT IN `config/settings/test.py`. Settings must not open a connection at
# import: `manage.py`, every management command and every worker would pay it,
# and a settings module that cannot be imported without a live database is a
# settings module that breaks `check --deploy`. So the shell — which already has
# the socket — decides, and settings only reads the answer.
#
# THE NAME IS ASKED FOR, NEVER DERIVED TWICE. `db_template_name` is db.sh's own
# function over db.sh's own migration key. A second copy of that derivation in
# Python is the drift class the whole rules engine exists against.
#
# A MISS IS NOT AN ERROR, and that is the hazard this guard exists for: a fresh
# clone, a moved migration state, or a `docker compose down` has no template, and
# Django REFUSES OUTRIGHT if `TEST["TEMPLATE"]` names a database that is not
# there. So the variable is exported only when the template really exists, and
# its absence means each worker migrates exactly as it always did. Both
# directions are driven in `quality/tests/test_db.py`.
#
# `DJB_DB_TEMPLATE=off` turns it off, the same escape db.sh already honours for
# `db_create`; an already-exported `DJB_TEST_DB_TEMPLATE` wins, which is what
# lets the drive aim this at a template it built itself.
if [ -z "${DJB_TEST_DB_TEMPLATE:-}" ] &&
    [ "${DJB_DB_TEMPLATE:-on}" != "off" ] &&
    command -v db_template_name >/dev/null 2>&1; then
    djb_tmpl="$(db_template_name 2>/dev/null || true)"
    if [ -n "$djb_tmpl" ] && db_exists "$djb_tmpl" >/dev/null 2>&1; then
        DJB_TEST_DB_TEMPLATE="$djb_tmpl"
        export DJB_TEST_DB_TEMPLATE
        echo "test.sh: each worker's test database is CLONED from ${djb_tmpl}."
    else
        echo "test.sh: no published template for this migration set — each worker migrates its"
        echo "         own test database. \`./scripts/db.sh\` publishes one; nothing is wrong."
    fi
    unset djb_tmpl
fi

uv run pytest "$@"
exit $?
