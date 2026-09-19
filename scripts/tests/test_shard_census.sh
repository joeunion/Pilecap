#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh.
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
# drives: apps/ scripts/check.sh scripts/pytest_durations.json
# cites: scripts/tests/test_list_legs.sh scripts/tests/fixtures/collection_world/
# The drive for THE ONE SHARD-CENSUS QUESTION WHOSE SUBJECT IS THE REAL TREE.
#
#   ./scripts/tests/test_shard_census.sh          run every case
#   ./scripts/tests/test_shard_census.sh --list   name them and stop
#
# WHY IT IS ITS OWN DRIVE. `scripts/tests/test_list_legs.sh` owns the shard
# census — that the shards the gate would run PARTITION the collection, for
# three N under two seeds, with a stale durations file and with none at all.
# Every one of those is a property of `pytest-split`'s grouping composed with
# this gate's flags, and a mechanism proven over fifty items is proven, so that
# census now runs over `scripts/tests/fixtures/collection_world/` and that
# drive no longer reads `apps/` at all.
#
# ONE QUESTION DID NOT MOVE WITH IT, because moving it would have emptied it:
# whether `scripts/pytest_durations.json` — the file shipped in this tree, the
# one the `pytest-x2` unit hands `--durations-path` — still names the suite it
# is balancing. That is not a property of pytest-split. It is a property of
# THIS tree's collection against THIS tree's recorded timings, and it can only
# be asked of the real suite. So it is here, alone, and this drive declares
# `apps/` for exactly that reason and costs one `--collect-only`.
#
# WHAT A STALE DURATIONS FILE ACTUALLY DOES, so the floor below is read for
# what it is: it cannot move the PARTITION — `test_list_legs.sh`'s census is
# what proves that, and it proves it in both directions — it can only
# UNBALANCE the groups. A file that has gone wholly stale leaves pytest-split
# chunking by count, which is legal, silent, and turns the sharded unit's whole
# reason for existing into a coin flip. Nothing else in this repository would
# notice; hence this.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE RECORDED TIMES ARE ANY GOOD. A duration recorded on a
#     different box, or before a test got ten times slower, is a number this
#     census counts as coverage. It reads which tests the file names, never how
#     long they took.
#   * THE BALANCE ITSELF. How evenly three groups come out is a wall-clock
#     question the unit's own trigger owns; a coverage floor is the cheapest
#     thing that fails when the file stops being about this suite.
#   * EVERY PARTITION PROPERTY. Disjointness, the union, the stale-file and
#     missing-file behaviour, the outside-the-rootdir refusal and the composed
#     xdist half are all `test_list_legs.sh`'s, over the fixture world.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_shard_census: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0
CURRENT=""
ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    FAILED=$((FAILED + 1))
}
cannot_look() {
    echo "!! test_shard_census: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_shard_census.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree"

ROOT="$PWD"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-shardcensus.XXXXXX") || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

#: THE ONE COLLECTION. Read-only: pytest imports the tree, prints node ids and
#: exits. Derived once and reused by every case below, because the whole point
#: of this drive is that it costs one.
COLLECTED=""
collect_the_real_suite() {
    [ -z "$COLLECTED" ] || return 0
    COLLECTED="${WORK}/collected.out"
    local rc=0
    (cd "$ROOT" && uv run pytest --collect-only -q -p no:randomly -p no:cacheprovider) \
        >"$COLLECTED" 2>&1 || rc=$?
    [ "$rc" = "0" ] ||
        cannot_look "the real suite would not collect (exit ${rc}, see ${COLLECTED}) — this drive has no subject"
}

#: THE FLOOR, AND WHY IT IS A HALF. A regenerated file names very nearly the
#: whole collection; a file that stopped being about this suite names almost
#: none of it. Anything in between is a suite that moved and a file that was
#: not regenerated, and the question the floor has to answer is only "is this
#: file still about this suite" — a floor tuned to today's coverage would
#: redden on the next honest batch of new tests, which is the failure mode that
#: teaches a reader to raise the number instead of running the command. Half is
#: far below any honest tree and far above a stale one.
DURATIONS_COVERAGE_FLOOR=50

case_the_durations_file_covers_the_collection_it_balances() {
    # THE CENSUS THIS DRIVE EXISTS FOR. Two readings of one collection: how
    # much of the suite the file can weigh, and how much of the file is still
    # about the suite. Both numbers are printed, because a floor that prints no
    # number is a floor nobody can see approaching.
    local f="${ROOT}/scripts/pytest_durations.json" report
    CURRENT="scripts/pytest_durations.json parses and names tests"
    if [ ! -f "$f" ]; then
        bad "scripts/pytest_durations.json is not in this tree — the split has nothing to balance by"
        return 0
    fi
    collect_the_real_suite
    report="${WORK}/coverage.txt"
    # THE READING IS INLINE, not a second file: one `uv run python -` with the
    # two paths as arguments, so this drive adds no executable to the tree for
    # the instrument census to have an opinion about.
    if ! (cd "$ROOT" && uv run python - "$f" "$COLLECTED" <<'READER'
import json
import pathlib
import sys

recorded = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
keys = set(recorded)
collected = {
    line.strip()
    for line in pathlib.Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
    if "::" in line and not line.startswith(" ")
}
if not collected:
    sys.stderr.write("the collection transcript held no node ids\n")
    raise SystemExit(2)
covered = collected & keys
print(f"collected={len(collected)}")
print(f"keys={len(keys)}")
print(f"covered={len(covered)}")
print(f"stale={len(keys - collected)}")
print(f"pct={(100 * len(covered)) // len(collected)}")
READER
    ) >"$report" 2>&1; then
        bad "the coverage reading refused: $(sed -n 1p "$report")"
        return 0
    fi
    local collected covered keys stale pct
    collected=$(sed -n 's/^collected=//p' "$report")
    covered=$(sed -n 's/^covered=//p' "$report")
    keys=$(sed -n 's/^keys=//p' "$report")
    stale=$(sed -n 's/^stale=//p' "$report")
    pct=$(sed -n 's/^pct=//p' "$report")
    if [ -z "${collected:-}" ] || [ -z "${pct:-}" ]; then
        bad "the coverage reading printed no numbers: $(sed -n 1p "$report")"
        return 0
    fi
    ok "${keys} recorded duration(s) against ${collected} collected item(s)"

    CURRENT="the file still weighs this suite"
    if [ "$pct" -ge "$DURATIONS_COVERAGE_FLOOR" ]; then
        ok "${covered} of ${collected} collected item(s) carry a recorded duration (${pct}%, floor ${DURATIONS_COVERAGE_FLOOR}%)"
    else
        bad "only ${covered} of ${collected} collected item(s) carry a recorded duration (${pct}%, under the floor of ${DURATIONS_COVERAGE_FLOOR}%) — the shards are being chunked by count, so the sharded unit is balancing nothing. Regenerate: ./scripts/check.sh --leg pytest-x2 --store-durations"
    fi

    # THE OTHER DIRECTION, and it is not the same number: the reading above
    # counts collected items the file can weigh, this one counts recorded names
    # the collection no longer has. A file regenerated on another branch scores
    # well on the first and badly on this one.
    CURRENT="and the file is not mostly about tests that are gone"
    if [ "$keys" -lt 1 ]; then
        bad "the durations file records nothing at all"
    elif [ $((stale * 2)) -lt "$keys" ]; then
        ok "${stale} of ${keys} recorded name(s) name a test the collection no longer has — under half"
    else
        bad "${stale} of ${keys} recorded name(s) are for tests this tree no longer collects — this file is mostly about another tree. Regenerate: ./scripts/check.sh --leg pytest-x2 --store-durations"
    fi
}

case_the_durations_file_is_derived_and_regenerable() {
    # G10.5. It is derived, it parses, it lives OUTSIDE `quality/**` (that
    # directory is inside the platform partition's input closure, and a
    # regenerated durations file there would move the skip key), and the command
    # that rewrites it is named where a reader of the leg will meet it.
    local f="${ROOT}/scripts/pytest_durations.json"
    CURRENT="scripts/pytest_durations.json is in the tree and parses"
    if [ ! -f "$f" ]; then
        bad "scripts/pytest_durations.json is not in this tree — the split has nothing to balance by"
        return 0
    fi
    if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f" >/dev/null 2>&1; then
        ok "$(wc -c <"$f" | tr -d ' ') bytes of JSON, $(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))))" "$f") entries"
    else
        bad "it does not parse as JSON"
    fi

    CURRENT="it is outside quality/ (the partition's input closure)"
    case "$f" in
    */quality/*) bad "it is under quality/ — a regenerated durations file would move the partition's skip key" ;;
    *) ok "scripts/, not quality/" ;;
    esac

    CURRENT="and the regeneration command is named in the leg that reads it"
    if grep -q -- './scripts/check.sh --leg pytest-x2 --store-durations' "${ROOT}/scripts/check.sh"; then
        ok "the leg prints the command that rewrites the file it is reading"
    else
        bad "nothing in check.sh names the command that regenerates the durations file"
    fi
}

# --- the run ------------------------------------------------------------------

case_the_durations_file_covers_the_collection_it_balances
case_the_durations_file_is_derived_and_regenerable

echo "test_shard_census: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! the durations file the sharded unit balances by is no longer about this" >&2
    echo "   suite. The shards still partition it — that is test_list_legs.sh's census —" >&2
    echo "   but they are chunked by count, so a shard is no longer a share of the wall" >&2
    echo "   clock. Regenerate with ./scripts/check.sh --leg pytest-x2 --store-durations." >&2
    exit 1
fi
exit 0
