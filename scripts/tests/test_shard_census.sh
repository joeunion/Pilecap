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
# drives: apps/ scripts/check.sh scripts/gate_member_durations.ci.json scripts/pm_fold.sh scripts/pytest_durations.json
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

# THE SELFTEST HALF OF THE SAME QUESTION. `scripts/gate_member_durations.ci.json`
# is what the selftest partition balances by and what `--list-legs --ci` derives
# the selftest shard count from. It is HARVESTED, never typed — the fold's
# `walls` step writes it from a green CI run's own shard lines — so the question
# here is the durations file's: is it still about this population, and does it
# say whose walls these are. The same half-coverage floor, for the same reason:
# a new drive sits at the median until the next green run is harvested, which
# is legal; a table that names almost nothing of the population is not.
case_the_ci_walls_table_is_about_this_selftest_population() {
    local f="${ROOT}/scripts/gate_member_durations.ci.json" listing="${WORK}/listing.tsv" pop="${WORK}/selftest-pop"
    local rc=0 members named stale pct
    CURRENT="scripts/gate_member_durations.ci.json is in the tree and says whose walls it holds"
    if [ ! -f "$f" ]; then
        bad "scripts/gate_member_durations.ci.json is not in this tree — the selftest partition falls back to the Mac table"
        return 0
    fi
    if python3 - "$f" <<'PYMETA'; then
import json, re, sys
d = json.load(open(sys.argv[1]))
assert re.fullmatch(r"run:[0-9]+ tree:[0-9a-f]{40}", d["measured_at"]), d["measured_at"]
assert d["machine"], "no machine"
assert d["members"] and all(isinstance(v, int) for v in d["members"].values())
PYMETA
        ok "parses; measured_at names a run and a tree, machine names the runner"
    else
        bad "it does not parse, or its measured_at is not 'run:<id> tree:<40 hex>', or it names no machine"
        return 0
    fi

    CURRENT="it names at least ${DURATIONS_COVERAGE_FLOOR}% of the selftest population, and no member the population lacks"
    (cd "$ROOT" && ./scripts/check.sh --list-legs) >"$listing" 2>&1 || rc=$?
    [ "$rc" = "0" ] || cannot_look "./scripts/check.sh --list-legs exited ${rc} — there is no selftest population to compare the table with"
    awk -F'\t' '$1 == "selftest" { n = split($4, m, ","); for (i = 1; i <= n; i++) print (m[i] == "selftest" ? "house-rules-engine" : m[i]) }' "$listing" >"$pop"
    members=$(grep -c . "$pop" || true)
    [ "${members:-0}" -gt 0 ] || cannot_look "the listing's selftest row composes no member"
    named=$(python3 -c "import json,sys; t=json.load(open(sys.argv[1]))['members']; p=[l.strip() for l in open(sys.argv[2]) if l.strip()]; print(sum(1 for m in p if m in t))" "$f" "$pop")
    stale=$(python3 -c "import json,sys; t=json.load(open(sys.argv[1]))['members']; p={l.strip() for l in open(sys.argv[2]) if l.strip()}; print(' '.join(sorted(m for m in t if m not in p)))" "$f" "$pop")
    pct=$((named * 100 / members))
    if [ "$pct" -lt "$DURATIONS_COVERAGE_FLOOR" ]; then
        bad "it names ${named} of ${members} member(s) (${pct}%) — it is no longer about this population. Re-harvest: ./scripts/pm_fold.sh --only walls"
    elif [ -n "$stale" ]; then
        bad "it names member(s) the population no longer has: ${stale} — re-harvest after the next green run: ./scripts/pm_fold.sh --only walls"
    else
        ok "${named} of ${members} member(s) (${pct}%), none stale"
    fi

    CURRENT="and the step that rewrites it is the fold's, named where it is read"
    if grep -q '^FOLD_WALLS_PATH=.scripts/gate_member_durations.ci.json.$' "${ROOT}/scripts/pm_fold.sh" &&
        grep -q 'scripts/gate_member_durations.ci.json' "${ROOT}/scripts/check.sh"; then
        ok "pm_fold.sh's walls step writes it; check.sh's partition reads it"
    else
        bad "either the fold no longer writes it or the gate no longer reads it"
    fi
}

# THE READER, NOT THE FILE. The table the fold writes is multi-line, and the
# gate's reader (`always_on__read_durations`, scripts/check.sh) was
# line-oriented: the same table written compactly on ONE line — a hand, or a
# `json.dumps` with no indent — parsed as nothing, the reader returned 1, and
# the partition line said there was no CI table at all. The case compacts the
# committed table and asks the gate's own two functions, extracted from
# check.sh and sourced in a subshell, to read both forms: the rows, the run and
# the machine must come back identical.
case_a_one_line_ci_walls_table_reads_as_the_same_table() {
    local f="${ROOT}/scripts/gate_member_durations.ci.json" compact="${WORK}/ci-walls-compact.json"
    local fns="${WORK}/walls-reader.sh" multi_out="${WORK}/walls-multi.out" one_out="${WORK}/walls-one.out" rc=0
    CURRENT="a compact one-line CI walls table reads as the same table"
    [ -f "$f" ] || cannot_look "scripts/gate_member_durations.ci.json is not in this tree"
    python3 -c 'import json, sys; json.dump(json.load(open(sys.argv[1])), open(sys.argv[2], "w"), separators=(",", ":"))' \
        "$f" "$compact" || cannot_look "python3 could not compact the committed table"
    [ "$(grep -c . "$compact")" = "1" ] || cannot_look "the compacted table is not one line"
    sed -n '/^always_on__read_durations() {/,/^}/p; /^always_on__json_lines() {/,/^}/p' \
        "${ROOT}/scripts/check.sh" >"$fns"
    grep -q '^always_on__read_durations() {' "$fns" ||
        cannot_look "scripts/check.sh defines no always_on__read_durations — the reader is gone"
    for form in multi one; do
        local table="$f" out="$multi_out"
        [ "$form" = "one" ] && table="$compact" && out="$one_out"
        rc=0
        (
            # shellcheck source=/dev/null
            . "$fns"
            always_on__read_durations "$table" || exit 1
            printf 'at=%s\nmachine=%s\n' "$ALWAYS_ON_MEASURED_AT" "$ALWAYS_ON_MACHINE"
            LC_ALL=C sort "$ALWAYS_ON_TABLE"
        ) >"$out" 2>&1 || rc=$?
        if [ "$rc" != "0" ]; then
            bad "the ${form}-line form was NOT READ (exit ${rc}) — the partition would say there is no CI table"
            return 0
        fi
    done
    if cmp -s "$multi_out" "$one_out"; then
        ok "both forms read $(($(grep -c . "$one_out") - 2)) member(s), $(sed -n 1p "$one_out"), $(sed -n 2p "$one_out")"
    else
        bad "the one-line form read differently: $(diff "$multi_out" "$one_out" | sed -n 1,4p | tr '\n' ' ')"
    fi
}

# --- the run ------------------------------------------------------------------

case_the_durations_file_covers_the_collection_it_balances
case_the_durations_file_is_derived_and_regenerable
case_the_ci_walls_table_is_about_this_selftest_population
case_a_one_line_ci_walls_table_reads_as_the_same_table

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
