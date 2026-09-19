#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. A wrong
# shell here does not crash; it ANSWERS, and the answer looks like the tree's
# fault. The two tests below are `test_secrets_scan.sh`'s, for its measured
# reason: on macOS `/bin/sh` IS bash, so only POSIX MODE tells `sh x.sh` from
# `bash x.sh`, while on Linux `/bin/sh` is dash and the first test is the one
# that fires. Neither test alone covers both machines.
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
# drives: docs/product/queue-detail.md docs/product/queue.md scripts/check.sh scripts/queue_cited.sh scripts/queue_index.py
# The drive for `scripts/queue_index.py` — the queue's index/detail split, the
# consistency check that keeps the two halves honest, and both ratchets.
#
#   ./scripts/tests/test_queue_index.sh          run every case
#   ./scripts/tests/test_queue_index.sh --list   name them and stop
#
# WHY IT EXISTS. The migration REPLACES the file that carries the order of all
# the work, and it does it in one pass. Two things can go wrong and neither is
# visible afterwards: the split can lose or reorder bytes (the record is the
# only copy, and a row that vanished cannot be missed by anybody who did not
# already know it was there), and the derived index can drift away from the
# record it claims to summarise (two truths again, in one cycle, which is the
# defect the split exists to close). So every canary here is FED A BROKEN PAIR
# and expected to fire: a canary that does not fire is this drive failing, not
# the generator passing.
#
# IT BUILDS ITS OWN VICTIMS. Every case writes a queue-shaped fixture under
# `mktemp -d` and destroys that. Nothing here reads or writes this checkout's
# own `docs/product/queue.md` except ONE case, which COPIES it into the scratch
# directory to measure the check at real scale — a destructive demonstration
# creates its own victim, and the real ledger is never the victim.
#
# THE IDS IN THE FIXTURES ARE FOUR DIGITS ON PURPOSE. This file lives under
# `scripts/`, which is inside `scripts/queue_cited.sh`'s citation scope, and
# that census matches ids of one to three digits. A fixture id of the ordinary
# shape would become a CITATION of a row that does not exist — a phantom
# registration, the class rung-execution §5 names — and would move the census's
# own counts. Four digits are invisible to it by construction, and the last
# case asserts that rather than trusting it.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER A ROW IS TRUE, in the right order, or held by the right person.
#     This drives a shape check over two files.
#   * THE `--fast` LEG REGISTRATION. Whether `scripts/check.sh` calls
#     `--check` at all is the gate's own business and is asserted nowhere here;
#     this drive would be perfectly green with the leg deleted.
#   * THE REAL MIGRATION'S CONTENT. Case `..._at_real_scale_...` copies this
#     checkout's queue and proves the round trip and the timing on it, but the
#     migration that ships is run once, by hand, at merge, on the file as it
#     stands THEN — and no drive can pre-run a file that has not stopped moving.
#     That is the point of the round-trip case: the property is proven over the
#     file's shape rather than over one snapshot of its content.
#   * RENDERING. An anchor before a table row splits that table where it
#     renders. Declared in the generator's own header as the cost of an
#     addressable record; nothing here looks at rendered Markdown.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_queue_index: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the scratch guards and the finished-sentinel. Refusing to" >&2
    echo "   run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_queue_index: $*" >&2
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
    echo "!! unknown argument '$1': test_queue_index.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH"
# THE CHECKOUT'S OWN INTERPRETER, for every PYTHON FILE THIS REPOSITORY SHIPS
# that this drive runs. `python3` off PATH is some other environment's: on a
# verifier box it is the system 3.9, where `zip(…, strict=True)` — which these
# files use — is `TypeError: zip() takes no keyword arguments`, and the drive
# would report that as a finding about the file it was driving. Inline
# `python3 -c` and heredoc programs below stay as they are: they are stdlib on
# any Python 3, and their own `command -v python3` guard covers their absence.
DRIVE_PY="$PWD/.venv/bin/python"
[ -x "$DRIVE_PY" ] ||
    cannot_look "this checkout has no .venv/bin/python, and the python files this drive
   runs are written at the version that venv holds. Run ./scripts/setup.sh first"
GEN="$PWD/scripts/queue_index.py"
[ -x "$GEN" ] || cannot_look "scripts/queue_index.py is not an executable file in this tree — there is nothing to drive"
REAL_QUEUE="$PWD/docs/product/queue.md"
REAL_DETAIL="$PWD/docs/product/queue-detail.md"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-queue-index-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# --- the assertions ----------------------------------------------------------
CURRENT=""
OUT=""
RC=0
DIR=""
N=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then sed 's/^/             | /' "$OUT" | tail -25; fi
    FAILED=$((FAILED + 1))
}

exits() {
    if [ "$RC" -eq "$1" ]; then
        ok "exit ${RC}"
    else
        bad "wanted exit $1, got ${RC}"
    fi
}

says() {
    if grep -qF -- "$1" "$OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}

says_not() {
    if grep -qF -- "$1" "$OUT"; then
        bad "says \"$1\" and must not"
    else
        ok "does not say \"$1\""
    fi
}

# --- the fixture -------------------------------------------------------------
#
# Queue-shaped, and deliberately carrying every shape the generator has to
# handle: a preamble with a table whose first cell is NOT an id (so it is not a
# row), an open bullet, a struck bullet, an open table row, a heading AFTER the
# first row (so the index has a body heading to carry), and one id that carries
# TWO row lines — the declared "a row and its own later addendum" population.
fresh() {
    CURRENT="$1"
    N=$((N + 1))
    DIR="${WORK}/case${N}"
    OUT="${WORK}/out${N}.log"
    mkdir -p "$DIR"
    cat >"$DIR/queue.md" <<'FIXTURE'
# Queue — the fixture

> Order lives here. Every other document defers to this one on ordering.

## ROW STATUS — how to read this file

> A struck id is closed and carries WHY in the strike itself.

## Live

| # | What | Holder | Evidence | Band |
|---|---|---|---|---|
| 1 | a table row whose first cell is not an id, so it is not a row | PM | — | floor |

## The first section

- **N9001 (MED shape, fixture): the first open row** — it states what is false. Holder: the drive
- **~~N9002~~ CLOSED (merged 0000000, fixture): the struck row** — closed with its artifact.
| N9003 | **a table row that IS a row** | PM | fixture | band |

## The second section

- **N9004 (LOW, fixture): a second open row, held by nobody.** Holder: nobody
- **N9001 ADDENDUM (the same id, a second row line — the declared population): the addendum**

## The end
FIXTURE
}

run() {
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$DIR" && "$DRIVE_PY" "$GEN" "$@") >"$OUT" 2>&1 || RC=$?
}

split_fixture() {
    run --split queue.md queue-detail.md
    [ "$RC" -eq 0 ] || cannot_look "the fixture would not split (exit ${RC}) — every case below is built on it: $(cat "$OUT")"
}

# The one letter that would make a fixture id visible to the citation census
# if it were ever adjacent to digits in this file's own TEXT. Held in a
# variable so that every constructed id below is invisible in the source as
# well as in the fixture — see the header, and the case that asserts it.
FIXTURE_ID_PREFIX="N"

# A row-defining line long enough to be over the generator's 1,500-character
# census threshold. Built, never typed.
long_row() {
    local id="$1"
    printf -- '- **%s (MED, fixture): a report-shaped row** %s\n' "$id" "$(head -c 1600 </dev/zero | tr '\0' 'x')"
}

# --- the cases ---------------------------------------------------------------

case_the_split_reproduces_the_original_bytes() {
    fresh "the split reproduces the original bytes"
    cp "$DIR/queue.md" "$DIR/queue.md.orig"
    split_fixture
    run --unsplit queue-detail.md rebuilt.md
    exits 0
    if cmp -s "$DIR/queue.md.orig" "$DIR/rebuilt.md"; then
        ok "concatenated detail reproduces the original byte for byte (cmp exit 0)"
    else
        bad "cmp found a difference: $(cmp "$DIR/queue.md.orig" "$DIR/rebuilt.md" 2>&1)"
    fi
}

case_rows_appended_after_the_snapshot_still_reproduce() {
    fresh "rows appended after the snapshot still reproduce"
    # The queue moves while the rung runs, so the property has to hold over the
    # file's SHAPE and not over one snapshot: three more rows, then split.
    {
        echo "- **N9005 (LOW, appended after the snapshot): a row the builder never saw** Holder: the PM"
        echo "- **~~N9006~~ CLOSED (merged 1111111, appended after the snapshot): another**"
        echo "| N9007 | **a third, as a table row** | PM | appended | band |"
    } >>"$DIR/queue.md"
    cp "$DIR/queue.md" "$DIR/queue.md.orig"
    split_fixture
    run --unsplit queue-detail.md rebuilt.md
    exits 0
    if cmp -s "$DIR/queue.md.orig" "$DIR/rebuilt.md"; then
        ok "three rows appended after the snapshot still round-trip byte for byte"
    else
        bad "cmp found a difference: $(cmp "$DIR/queue.md.orig" "$DIR/rebuilt.md" 2>&1)"
    fi
    run --check queue.md queue-detail.md
    exits 0
}

case_a_fresh_split_checks_clean() {
    fresh "a fresh split checks clean"
    split_fixture
    run --check queue.md queue-detail.md
    exits 0
    says "rows"
    says_not "!!"
}

case_an_id_that_carries_two_rows_gets_two_anchors() {
    fresh "an id that carries two rows gets two anchors"
    split_fixture
    OUT="${WORK}/anchors.log"
    grep -n '^### ' "$DIR/queue-detail.md" >"$OUT" || true
    if grep -qx '### N9001' "$DIR/queue-detail.md" && grep -qx '### N9001 (2)' "$DIR/queue-detail.md"; then
        ok "the second row line takes '### N9001 (2)', so the anchor set stays a key"
    else
        bad "the two rows under one id did not get distinct anchors"
    fi
    if grep -q 'queue-detail.md#n9001-2' "$DIR/queue.md"; then
        ok "the index addresses the second row at #n9001-2"
    else
        bad "the index does not address the second row separately"
    fi
}

case_an_index_row_with_no_anchor_is_exit_1_naming_the_id() {
    fresh "an index row with no anchor is exit 1 naming the id"
    split_fixture
    # The canary: the record loses one anchor; the index still carries its row.
    grep -vx '### N9004' "$DIR/queue-detail.md" >"$DIR/tmp" && mv "$DIR/tmp" "$DIR/queue-detail.md"
    run --check queue.md queue-detail.md
    exits 1
    says "N9004"
    says "NO anchor"
}

case_an_anchor_with_no_index_row_is_exit_1_naming_the_id() {
    fresh "an anchor with no index row is exit 1 naming the id"
    split_fixture
    # The canary from the other side: the index loses one row.
    grep -v 'queue-detail.md#n9004' "$DIR/queue.md" >"$DIR/tmp" && mv "$DIR/tmp" "$DIR/queue.md"
    run --check queue.md queue-detail.md
    exits 1
    says "N9004"
    says "NO index row"
}

case_a_head_that_is_not_a_prefix_is_exit_1_naming_the_id() {
    fresh "a head that is not a prefix is exit 1 naming the id"
    split_fixture
    # The canary: the index says something the record does not.
    sed -i.bak 's|^\(- \*\*N9004 .*\*\* · \).*\( → queue-detail.md#n9004\)$|\1a paraphrase nobody wrote\2|' "$DIR/queue.md"
    run --check queue.md queue-detail.md
    exits 1
    says "N9004"
    says "not the row's own text"
}

case_a_struck_row_indexed_open_is_exit_1_naming_the_id() {
    fresh "a struck row indexed open is exit 1 naming the id"
    split_fixture
    sed -i.bak 's|^- \*\*~~N9002~~ · struck|- **N9002 · open|' "$DIR/queue.md"
    run --check queue.md queue-detail.md
    exits 1
    says "N9002"
}

case_a_duplicate_anchor_is_exit_1() {
    fresh "a duplicate anchor is exit 1"
    split_fixture
    awk '{print} /^### N9003$/ {print "### N9003"}' "$DIR/queue-detail.md" >"$DIR/tmp" && mv "$DIR/tmp" "$DIR/queue-detail.md"
    run --check queue.md queue-detail.md
    exits 1
    says "DUPLICATE ANCHOR"
}

case_an_absent_record_is_exit_2_and_judges_nothing() {
    fresh "an absent record is exit 2 and judges nothing"
    split_fixture
    rm -f "$DIR/queue-detail.md"
    run --check queue.md queue-detail.md
    exits 2
    says "is absent while"
    says "Nothing was judged"
    # The whole point: the readable half is NOT judged in the record's absence.
    says_not "rows ·"
}

case_a_pre_split_tree_is_a_named_absence_not_a_pass() {
    # THE ORDERING STATE. The gate leg is registered before the migration runs
    # — the migration is one hand, once, at merge — so the check meets trees
    # that were never split. It must not redden them, and it must not go
    # QUIET on them either: the line says nothing was checked, and says what
    # ends that. The discriminator is the generated header, not the file's
    # existence; the two cases below are the halves a `-f` test would merge.
    fresh "a pre-split tree is a named absence, not a pass"
    run --check queue.md queue-detail.md
    exits 0
    says "PRE-SPLIT"
    says "nothing was checked"
    says "--split"
    # It must not read as a clean ledger: no measurement line at all.
    says_not "long rows of"
}

case_a_record_beside_an_ungenerated_index_is_exit_2() {
    fresh "a record beside an ungenerated index is exit 2"
    split_fixture
    # Half-migrated: the record stands, somebody put the old index back.
    "$DRIVE_PY" "$GEN" --unsplit "$DIR/queue-detail.md" "$DIR/queue.md" >/dev/null
    run --check queue.md queue-detail.md
    exits 2
    says "half-migrated"
    says "Nothing was judged"
}

case_an_unreadable_record_is_exit_2() {
    fresh "an unreadable record is exit 2"
    split_fixture
    chmod 000 "$DIR/queue-detail.md"
    run --check queue.md queue-detail.md
    chmod 644 "$DIR/queue-detail.md"
    exits 2
    says "Nothing was judged"
}

case_a_hand_edit_to_the_index_is_exit_1_with_the_remedy() {
    fresh "a hand edit to the index is exit 1 with the remedy"
    split_fixture
    sed -i.bak 's|^## The second section|## The second section, renamed by hand|' "$DIR/queue.md"
    run --check queue.md queue-detail.md
    exits 1
    says "is NOT what scripts/queue_index.py generates"
    says "Remedy"
    says "--index"
}

case_an_index_over_its_ceiling_is_exit_1_with_both_remedies() {
    fresh "an index over its ceiling is exit 1 with both remedies"
    split_fixture
    sed -i.bak 's|^CEILING: .*|CEILING: 64|' "$DIR/queue.md"
    run --check queue.md queue-detail.md
    exits 1
    says "over its recorded ceiling"
    says "Remedy 1"
    says "Remedy 2"
}

case_the_ceiling_ratchets_down_by_machine() {
    fresh "the ceiling ratchets down by machine"
    split_fixture
    sed -i.bak 's|^CEILING: .*|CEILING: 10000000 raised by hand, reason: the fixture says so|' "$DIR/queue.md"
    run --index queue.md queue-detail.md
    exits 0
    OUT="${WORK}/ceiling.log"
    grep '^CEILING: ' "$DIR/queue.md" >"$OUT"
    if [ "$(sed 's/^CEILING: //; s/ .*//' "$OUT")" -lt 10000 ]; then
        ok "the generator lowered the ceiling to $(cat "$OUT")"
    else
        bad "the ceiling did not ratchet down: $(cat "$OUT")"
    fi
}

case_the_ceiling_is_never_raised_by_machine() {
    fresh "the ceiling is never raised by machine"
    split_fixture
    BEFORE="$(grep '^CEILING: ' "$DIR/queue.md")"
    # Grow the record well past the ceiling, anchors and all, then regenerate.
    local grown
    for i in 1 2 3 4 5 6 7 8 9; do
        grown="${FIXTURE_ID_PREFIX}91${i}0"
        {
            echo "### ${grown}"
            long_row "$grown"
        } >>"$DIR/queue-detail.md"
    done
    run --index queue.md queue-detail.md
    exits 0
    AFTER="$(grep '^CEILING: ' "$DIR/queue.md")"
    OUT="${WORK}/ceiling2.log"
    printf 'before: %s\nafter:  %s\n' "$BEFORE" "$AFTER" >"$OUT"
    if [ "$BEFORE" = "$AFTER" ]; then
        ok "the ceiling is unchanged after the index outgrew it ($AFTER)"
    else
        bad "the machine moved the ceiling: ${BEFORE} -> ${AFTER}"
    fi
    run --check queue.md queue-detail.md
    exits 1
    says "over its recorded ceiling"
}

case_the_long_row_census_refuses_a_count_above_its_floor() {
    fresh "the long-row census refuses a count above its floor"
    long_row "N9101" >>"$DIR/queue.md"
    split_fixture
    OUT="${WORK}/floor.log"
    grep '^LONGROWS: ' "$DIR/queue.md" >"$OUT"
    says "LONGROWS: 1"
    {
        echo "### N9102"
        long_row "N9102"
    } >>"$DIR/queue-detail.md"
    run --index queue.md queue-detail.md
    exits 0
    run --check queue.md queue-detail.md
    exits 1
    says "rows over 1500 characters"
    says "the recorded floor is 1"
    says "N9102"
}

case_the_long_row_census_ratchets_down_by_machine() {
    fresh "the long-row census ratchets down by machine"
    long_row "N9101" >>"$DIR/queue.md"
    split_fixture
    grep -vx "### N9101" "$DIR/queue-detail.md" | grep -v "^- \*\*N9101 " >"$DIR/tmp" && mv "$DIR/tmp" "$DIR/queue-detail.md"
    run --index queue.md queue-detail.md
    exits 0
    OUT="${WORK}/floor2.log"
    grep '^LONGROWS: ' "$DIR/queue.md" >"$OUT"
    says "LONGROWS: 0"
}

case_a_line_the_citation_census_would_misread_is_exit_1() {
    fresh "a line the citation census would misread is exit 1"
    # THE PARITY CANARY, and the plant is the shape the design was first
    # DRAFTED in. `scripts/queue_cited.sh` reads an open row's id out of the
    # leading 40 characters and wants a space, `(` or `:` right after the
    # digits; closing the bold immediately after the id puts an asterisk
    # there, and the census then reads the line as NO ROW AT ALL — every open
    # id in the file would move from CITED-BUT-UNSTRUCK to CITED-WITH-NO-ROW
    # and nothing in the gate would say so. Measured on the classifier, which
    # is why the shipped line closes its bold after the STATUS instead.
    split_fixture
    sed -i.bak 's|^- \*\*N9004 · \([^*]*\)\*\* · |- **N9004** · \1 · |' "$DIR/queue.md"
    grep -q '^- \*\*N9004\*\* · open · ' "$DIR/queue.md" ||
        cannot_look "the plant did not take — the index line shape has changed and this canary is aimed at nothing"
    run --check queue.md queue-detail.md
    exits 1
    says "queue-citation parser reads"
    says "rows out of the generated"
}

case_a_source_that_already_carries_an_anchor_is_refused() {
    fresh "a source that already carries an anchor is refused"
    printf '\n### N9010\n' >>"$DIR/queue.md"
    run --split queue.md queue-detail.md
    exits 2
    says "already carries an anchor-shaped line"
    if [ -e "$DIR/queue-detail.md" ]; then
        bad "it wrote the record anyway"
    else
        ok "nothing was written"
    fi
}

case_split_refuses_when_the_record_already_exists() {
    fresh "split refuses when the record already exists"
    split_fixture
    cp "$DIR/queue-detail.md" "$DIR/keep"
    run --split queue.md queue-detail.md
    exits 2
    says "already exists"
    if cmp -s "$DIR/keep" "$DIR/queue-detail.md"; then
        ok "the existing record is byte-identical after the refusal"
    else
        bad "the refusal still touched the record"
    fi
}

case_index_refuses_a_queue_that_was_never_split() {
    fresh "index refuses a queue that was never split"
    run --index queue.md queue-detail.md
    exits 2
    says "Nothing was written"
}

case_an_unknown_flag_is_exit_2() {
    fresh "an unknown flag is exit 2"
    run --pretend-this-is-a-flag
    exits 2
    says "unknown argument"
    says "Nothing was judged"
}

case_the_check_is_under_a_second_at_real_scale() {
    fresh "the check is under a second at real scale"
    if [ ! -r "$REAL_QUEUE" ]; then
        # A product that renamed or dropped the ledger: say so, do not pretend.
        OUT="${WORK}/realscale.log"
        echo "docs/product/queue.md is not in this tree" >"$OUT"
        ok "no queue in this tree — the real-scale case is declared skipped, not passed silently"
        return
    fi
    # TWO SHAPES OF CHECKOUT, BOTH LEGAL, AND BOTH MEASURED. This case was
    # first written against a pre-split tree and returned one `ok` and nothing
    # else the day the migration landed — a green case asserting nothing, which
    # is the one class this whole drive exists to refuse. The split state is
    # permanent from here, so it is the branch that has to carry the
    # measurement.
    if grep -q '^CEILING: ' "$REAL_QUEUE"; then
        [ -r "$REAL_DETAIL" ] || cannot_look \
            "this checkout's queue IS a generated index and its record is not readable — the real-scale case cannot look"
        # THE PATHS ARE PRESERVED, not flattened: the generated header records
        # the paths it was generated with, so a copy under different names is a
        # different file and `--check` would report a difference that is the
        # copy's, not the ledger's.
        mkdir -p "$DIR/docs/product"
        cp "$REAL_QUEUE" "$DIR/docs/product/queue.md"
        cp "$REAL_DETAIL" "$DIR/docs/product/queue-detail.md"
        START=$(date +%s)
        run --check docs/product/queue.md docs/product/queue-detail.md
        ELAPSED=$(($(date +%s) - START))
        exits 0
        says "rows"
        if [ "$ELAPSED" -le 1 ]; then
            ok "--check on this checkout's real pair took ${ELAPSED}s (wall clock, whole-second resolution)"
        else
            bad "--check on this checkout's real pair took ${ELAPSED}s — it runs on every commit"
        fi
        # And the migration is still reversible at real scale: unsplit the
        # record to the pre-split file, re-split it, and the record must come
        # back byte for byte.
        run --unsplit docs/product/queue-detail.md pre.md
        exits 0
        (cd "$DIR" && "$DRIVE_PY" "$GEN" --split pre.md rebuilt-detail.md) >"${WORK}/resplit.log" 2>&1
        if cmp -s "$DIR/docs/product/queue-detail.md" "$DIR/rebuilt-detail.md"; then
            ok "this checkout's real record survives unsplit-and-re-split byte for byte"
        else
            bad "the record did not come back: $(cmp "$DIR/docs/product/queue-detail.md" "$DIR/rebuilt-detail.md" 2>&1)"
        fi
        return
    fi
    cp "$REAL_QUEUE" "$DIR/queue.md"
    cp "$REAL_QUEUE" "$DIR/queue.md.orig"
    split_fixture
    run --unsplit queue-detail.md rebuilt.md
    exits 0
    if cmp -s "$DIR/queue.md.orig" "$DIR/rebuilt.md"; then
        ok "this checkout's own queue round-trips byte for byte"
    else
        bad "cmp found a difference on the real file: $(cmp "$DIR/queue.md.orig" "$DIR/rebuilt.md" 2>&1)"
    fi
    START=$(date +%s)
    run --check queue.md queue-detail.md
    ELAPSED=$(($(date +%s) - START))
    exits 0
    if [ "$ELAPSED" -le 1 ]; then
        ok "--check at real scale took ${ELAPSED}s (wall clock, whole-second resolution)"
    else
        bad "--check at real scale took ${ELAPSED}s — it runs on every commit"
    fi
    says "rows"
}

case_this_drive_cites_no_row_of_the_real_queue() {
    # The phantom-registration guard, asserted rather than trusted: every id in
    # this file must be invisible to the citation census's own pattern.
    CURRENT="this drive cites no row of the real queue"
    OUT="${WORK}/phantom.log"
    if grep -oE '(^|[^A-Za-z0-9_])N[0-9]{1,3}[a-z]?([^A-Za-z0-9_]|$)' "$0" >"$OUT" 2>&1; then
        bad "this drive spells ids the citation census would count: $(tr '\n' ' ' <"$OUT")"
    else
        : >"$OUT"
        ok "no id in this file matches the citation census's pattern"
    fi
    if grep -oE '(^|[^A-Za-z0-9_])N[0-9]{1,3}[a-z]?([^A-Za-z0-9_]|$)' "$GEN" >"$OUT" 2>&1; then
        bad "the generator spells ids the citation census would count: $(tr '\n' ' ' <"$OUT")"
    else
        : >"$OUT"
        ok "no id in the generator matches the citation census's pattern"
    fi
}

case_the_split_reproduces_the_original_bytes
case_rows_appended_after_the_snapshot_still_reproduce
case_a_fresh_split_checks_clean
case_an_id_that_carries_two_rows_gets_two_anchors
case_an_index_row_with_no_anchor_is_exit_1_naming_the_id
case_an_anchor_with_no_index_row_is_exit_1_naming_the_id
case_a_head_that_is_not_a_prefix_is_exit_1_naming_the_id
case_a_struck_row_indexed_open_is_exit_1_naming_the_id
case_a_duplicate_anchor_is_exit_1
case_an_absent_record_is_exit_2_and_judges_nothing
case_a_pre_split_tree_is_a_named_absence_not_a_pass
case_a_record_beside_an_ungenerated_index_is_exit_2
case_an_unreadable_record_is_exit_2
case_a_hand_edit_to_the_index_is_exit_1_with_the_remedy
case_an_index_over_its_ceiling_is_exit_1_with_both_remedies
case_the_ceiling_ratchets_down_by_machine
case_the_ceiling_is_never_raised_by_machine
case_the_long_row_census_refuses_a_count_above_its_floor
case_the_long_row_census_ratchets_down_by_machine
case_a_line_the_citation_census_would_misread_is_exit_1
case_a_source_that_already_carries_an_anchor_is_refused
case_split_refuses_when_the_record_already_exists
case_index_refuses_a_queue_that_was_never_split
case_an_unknown_flag_is_exit_2
case_the_check_is_under_a_second_at_real_scale
case_this_drive_cites_no_row_of_the_real_queue

echo "test_queue_index: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property of the queue's index/detail split did not hold. The record is" >&2
    echo "   the only copy of every row, and the index is the file everybody reads:" >&2
    echo "   a canary that did not fire here is a disagreement nobody downstream sees." >&2
    exit 1
fi
exit 0
