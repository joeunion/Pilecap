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
# drives: docs/product/in-flight.md docs/product/readouts.md scripts/loop_metrics.py scripts/pm_push.sh
# cites: scripts/check.sh
# The drive for `scripts/loop_metrics.py` — the velocity reader that derives
# the cost-baseline row from the dispatch ledger's stamps, from git, and from
# the bank and loop logs.
#
#   ./scripts/tests/test_loop_metrics.sh          run every case
#   ./scripts/tests/test_loop_metrics.sh --list   name them and stop
#
# WHY IT EXISTS. The numbers under `readouts.md` § COST BASELINE were typed by
# hand from a usage screen and from memory, and a typed number cannot be
# disagreed with — it has no input to re-read. The reader this drives replaces
# the typing with a derivation, which moves the failure mode: it can now be
# WRONG rather than merely unverifiable, and wrong in two ways that both look
# like an answer. It can read a stamp that says something impossible and print
# a plausible minute count from it, and it can quietly skip the rows that have
# no stamps at all and report a median over the convenient half of the ledger.
# So the cases below feed it a broken clock and expect a refusal, and feed it
# an unstamped row and expect the row to be COUNTED and NAMED in the output
# rather than dropped. A green case here is a reader that either measured or
# said out loud what it could not measure.
#
# IT BUILDS ITS OWN VICTIMS. Every case writes its ledger, its logs and its
# readouts fixture under `mktemp -d` and destroys them at exit. ONE case copies
# this checkout's real dispatch ledger into that scratch directory to measure
# the reader at real scale and to prove it survives a ledger whose rows predate
# the stamp grammar entirely — a destructive demonstration builds its own
# victim, and the real ledger is never the victim.
#
# THE FIXTURE IDS ARE `RUNG-A`, `WAVE-1` AND SO ON, ON PURPOSE. This file lives
# under `scripts/`, which ships, and the archaeology census counts ledger
# coordinates and finding ids wherever they appear — a fixture row carrying an
# ordinary-shaped id would be a citation of work that resolves nowhere in the
# published artifact. The shapes here are invisible to it by construction.
#
# THE INTERPRETER IS THIS CHECKOUT'S, NEVER `python3` OFF PATH. The reader is a
# python file this repository ships and pins at the version the venv holds; on
# a verifier box the system `python3` is 3.9 and the drive would report the
# interpreter's syntax error as a finding about the file it was driving.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER A STAMP IS TRUE. The reader arithmetics what the ledger says; a
#     stamp written from memory an hour late is a correct calculation over a
#     wrong input, and nothing here can tell the two apart.
#   * THE REAL BANK AND LOOP LOGS. The log cases are fed synthetic logs carrying
#     the grammar this checkout's gate prints (`scope   rule:`, the per-leg
#     `(<leg>: Ns)` line, `ok: loop checks passed (Ns)`, `ok: all checks passed
#     (Ns)`). A gate that changed one of those lines would leave this drive
#     green and the reader blind, which is why the reader counts and PRINTS the
#     logs it could not classify instead of ignoring them.
#   * THE COLUMNS THEMSELVES. Whether the cost-baseline table asks for the
#     right measures is a judgment, not a property; the cases assert only that
#     the header is READ from the readouts file rather than carried in the
#     reader's own text.
#   * REGISTRATION. Whether `scripts/check.sh` invokes this drive at all is the
#     gate's own business and is asserted in `test_drive_preamble.sh`, not here.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_loop_metrics: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the scratch guards and the finished-sentinel. Refusing to" >&2
    echo "   run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_loop_metrics: $*" >&2
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
    echo "!! unknown argument '$1': test_loop_metrics.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

# THE CHECKOUT'S OWN INTERPRETER, for the python file this repository ships and
# this drive runs. See the header.
DRIVE_PY="$PWD/.venv/bin/python"
[ -x "$DRIVE_PY" ] ||
    cannot_look "this checkout has no .venv/bin/python, and the python file this drive
   runs is written at the version that venv holds. Run ./scripts/setup.sh first"
READER="$PWD/scripts/loop_metrics.py"
# The one site that PRINTS the docs-only road's own line, read by the case
# that asserts this reader still matches it.
PUSHER="$PWD/scripts/pm_push.sh"
[ -f "$READER" ] || cannot_look "scripts/loop_metrics.py is not a file in this tree — there is nothing to drive"
REAL_LEDGER="$PWD/docs/product/in-flight.md"
REAL_READOUTS="$PWD/docs/product/readouts.md"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-loop-metrics-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
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

# --- the fixtures ------------------------------------------------------------
#
# THE LEDGER. The dispatch table's seven columns, with the stamps cell in the
# last one — three rungs across two waves, one verification row, and one row
# with no stamps cell at all so that every case measures the reader against a
# ledger that is half-migrated, which is the only state the real one will ever
# be in on the day this first runs.
fresh() {
    CURRENT="$1"
    N=$((N + 1))
    DIR="${WORK}/case${N}"
    OUT="${WORK}/out${N}.log"
    mkdir -p "$DIR/banks" "$DIR/loops"
    cat >"$DIR/in-flight.md" <<'LEDGER'
# The dispatch ledger — fixture

Some prose above the table, which is not a row.

| # | Task | Role · model | State | Sent | Returned | Result |
|---|---|---|---|---|---|---|
| RUNG-A | alpha | development · opus | merged | 2026-09-17 08:00 | 2026-09-17 09:40 | DONE. stamps: sent=2026-09-17 08:00 done=09:40 met=10:05 merged=1a2b3c4d 10:20 pushed=— staged=— |
| RUNG-B | beta | development · opus | merged | 2026-09-17 08:05 | 2026-09-17 10:10 | DONE. stamps: sent=2026-09-17 08:05 done=10:10 met=10:50 merged=2b3c4d5e 11:00 pushed=— staged=— |
| WAVE-1 | the first wave | wave | pushed | — | — | stamps: sent=— done=— met=— merged=— pushed=2026-09-17 11:30 staged=2026-09-17 11:52 |
| RUNG-C | gamma | development · opus | merged | 2026-09-17 12:00 | 2026-09-17 13:00 | DONE. stamps: sent=2026-09-17 12:00 done=13:00 met=13:20 merged=3c4d5e6f 13:35 pushed=— staged=— |
| WAVE-2 | the second wave | wave | pushed | — | — | stamps: sent=— done=— met=— merged=— pushed=2026-09-17 14:00 staged=— |
| VERIFY-A | prove alpha | verification · opus | returned | 2026-09-17 09:45 | 2026-09-17 10:05 | PASS. stamps: sent=2026-09-17 09:45 done=10:05 met=10:05 merged=— pushed=— staged=— |
| RUNG-D | delta | development · opus | returned | 2026-09-17 15:00 | 2026-09-17 16:00 | DONE — this row predates the stamp grammar and carries no stamps cell |
| RUNG-E | epsilon | development · opus | killed | 2026-09-17 15:00 | — | killed by the platform; no report |
LEDGER
    # THE READOUTS FIXTURE. Only the section the reader reads, so a case that
    # asserts the header was read cannot be satisfied by the reader carrying
    # its own copy of the real one.
    cat >"$DIR/readouts.md" <<'READOUTS'
# Readouts — fixture

## COST BASELINE — fixture

| Measure | Fixture column two | Fixture column three |
|---|---|---|
| opus | some spend | some lever |
READOUTS
}

# THE LOOP LOGS. The three change classes the gate's own `scope   rule:` line
# distinguishes, plus one log with no such line at all.
loop_log() {
    local name=$1 reason=$2 wall=$3
    {
        echo "== check.sh --loop"
        [ -n "$reason" ] && echo "  scope   rule: ${reason}"
        echo "  (house-rules: 22s)"
        echo "  (pytest: $((wall - 40))s)"
        echo "ok: loop checks passed (${wall}s)"
    } >"${DIR}/loops/${name}.log"
}

# THE BANK LOGS. A bank that went green and pushed, and a bank the gate refused.
bank_log_green() {
    local name=$1 wall=$2
    {
        echo "== check.sh (full)"
        echo "  (house-rules: 25s)"
        echo "  (supply-chain: 76s)"
        echo "  (pytest-x2: 480s)"
        echo "  (selftest: 900s)"
        echo "ok: all checks passed (${wall}s)"
        echo "pre-push: every pushed tree (6d03b4f9864dd3a087d4eb984cada3e6774b4b6d) is measured green by a full gate run — verdict honoured"
    } >"${DIR}/banks/${name}.log"
}
bank_log_red() {
    local name=$1
    {
        echo "== check.sh (full)"
        echo "  (house-rules: 25s)"
        echo "!! pm_push --bank: the full gate exited 1."
        echo "   Nothing was pinned and nothing was pushed."
    } >"${DIR}/banks/${name}.log"
}

# A bank that took the DOCS-ONLY ROAD. It has no leg banner and no
# "all checks passed", because it ran no full gate: it ran the readers the
# changed documentation has and wrote the same row a bank writes. A reader
# that only knew the full banner counted such a push as a bank that launched
# and never went green — the cheapest green in the population dragging the
# green percentage down every time it worked.
bank_log_docs_only() {
    local name=$1 wall=$2
    {
        echo "pm_push --bank: docs-only? yes — 3 path(s) changed since the"
        echo "  measured tree 1111111111111111111111111111111111111111, every one of them on the declared list."
        echo "  readers, DERIVED from what those paths are read by:"
        echo "    static"
        echo "  reader static: 41s (exit 0)"
        echo "pm_push --bank: docs-only reuse of 1111111111111111111111111111111111111111 — readers 41 s, total ${wall} s"
        echo "  source + delta + row: 2 s"
        echo "pre-push: every pushed tree (6d03b4f9864dd3a087d4eb984cada3e6774b4b6d) is measured green by a full gate run — verdict honoured"
    } >"${DIR}/banks/${name}.log"
}

run() {
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    "$DRIVE_PY" "$READER" "$@" >"$OUT" 2>&1 || RC=$?
}

# Every case's ordinary invocation, so a flag added to the reader is added in
# one place here rather than in nine.
run_fixture() {
    run --in-flight "$DIR/in-flight.md" --readouts "$DIR/readouts.md" \
        --bank-logs "$DIR/banks" --loop-logs "$DIR/loops" "$@"
}

# --- 1 · the two clocks -------------------------------------------------------

case_the_two_clocks_are_derived_from_the_stamps() {
    fresh case_the_two_clocks_are_derived_from_the_stamps
    run_fixture
    exits 0
    # Stage 3, per rung: done → met. 25, 40 and 20 minutes.
    says "RUNG-A"
    says "done→met"
    says "25 min"
    says "40 min"
    says "20 min"
    # Stage 4 and 5, per WAVE: the wave's LAST met → pushed → staged.
    says "WAVE-1"
    says "WAVE-2"
    # WAVE-1's last met is RUNG-B's 10:50; pushed 11:30 is 40 minutes later,
    # and staged 11:52 is 22 minutes after that.
    says "last met→pushed"
    says "pushed→staged"
    says "22 min"
    # A wave whose staged stamp is not reached says so rather than printing a
    # number: WAVE-2's staged is the em dash.
    says "not reached"
}

case_the_wave_of_a_rung_is_derived_from_the_clocks() {
    fresh case_the_wave_of_a_rung_is_derived_from_the_clocks
    run_fixture
    exits 0
    # A rung belongs to the first wave pushed after it merged. RUNG-A (10:20)
    # and RUNG-B (11:00) are WAVE-1's; RUNG-C (13:35) is WAVE-2's.
    says "WAVE-1: RUNG-A, RUNG-B"
    says "WAVE-2: RUNG-C"
}

# --- 2 · the inner loop, by change class --------------------------------------

case_the_inner_loop_is_reported_by_change_class() {
    fresh case_the_inner_loop_is_reported_by_change_class
    loop_log leaf-1 "the fast tier NARROWED to the active rung's scope — its own app(s) [example], which run IN FULL, plus the reverse-transitive depends_on closure [-], which runs its fast tier — plus the always-on cross-app set" 100
    loop_log leaf-2 "the fast tier NARROWED to the active rung's scope — its own app(s) [example], which run IN FULL, plus the reverse-transitive depends_on closure [-], which runs its fast tier — plus the always-on cross-app set" 140
    loop_log core-1 "the fast tier NARROWED to the active rung's scope — its own app(s) [core], which run IN FULL, plus the reverse-transitive depends_on closure [example], which runs its fast tier — plus the always-on cross-app set" 300
    loop_log shared-1 "the active rung changed shared test infrastructure or a file no app owns that every test stands on — so --loop runs the FULL suite, not a scope" 900
    loop_log nothing-said "" 61
    run_fixture
    exits 0
    says "leaf"
    says "core"
    says "shared"
    says "120 s"
    says "300 s"
    says "900 s"
    # A log with no `scope rule:` line is counted and NAMED, never dropped.
    says "unclassified"
    says "nothing-said.log"
    says_not "61 s"
}

# --- 3 · a malformed stamp cannot be measured ---------------------------------

case_a_malformed_stamp_cannot_be_measured() {
    fresh case_a_malformed_stamp_cannot_be_measured
    # An hour that does not exist on any clock.
    sed -i.bak 's/met=10:05 merged=1a2b3c4d/met=25:99 merged=1a2b3c4d/' "$DIR/in-flight.md"
    run_fixture
    exits 2
    says "RUNG-A"
    says "met"
    # Nothing is printed as a number once the reader has refused.
    says_not "done→met"
    says "Nothing was measured"
}

case_a_merged_rung_with_no_met_stamp_cannot_be_measured() {
    fresh case_a_merged_rung_with_no_met_stamp_cannot_be_measured
    sed -i.bak 's/met=10:05 merged=1a2b3c4d/met=— merged=1a2b3c4d/' "$DIR/in-flight.md"
    run_fixture
    exits 2
    says "RUNG-A"
    says "met"
    says_not "done→met"
}

case_a_note_row_that_was_merged_and_never_dispatched_is_named_as_one() {
    # THE SHAPE A HAND-TYPED LEDGER REALLY GROWS. A note, a ruling or a merge
    # record gets a `merged=` stamp because somebody merged something, and it
    # has no `sent` because nothing was ever dispatched. The generic
    # missing-earlier-stage refusal names the field and reads as "backfill
    # `sent`", which is the one remedy that cannot be right here — so this row
    # gets its own sentence and the opposite instruction.
    fresh case_a_note_row_that_was_merged_and_never_dispatched_is_named_as_one
    sed -i.bak \
        's/| RUNG-C | gamma | development · opus | merged | 2026-09-17 12:00 | 2026-09-17 13:00 | DONE. stamps: sent=2026-09-17 12:00 done=13:00 met=13:20 merged=3c4d5e6f 13:35 pushed=— staged=— |/| NOTE-1 | a ruling nobody built | note | — | — | — | stamps: sent=— done=— met=— merged=3c4d5e6f 2026-09-17 13:35 pushed=— staged=— |/' \
        "$DIR/in-flight.md"
    run_fixture
    exits 2
    says "NOTE-1"
    says "NOT A RUNG ROW"
    says "WITHHOLD THE"
    says_not "done→met"
}

case_a_wave_with_no_pushed_stamp_cannot_be_measured() {
    fresh case_a_wave_with_no_pushed_stamp_cannot_be_measured
    sed -i.bak 's/pushed=2026-09-17 11:30/pushed=—/' "$DIR/in-flight.md"
    run_fixture
    exits 2
    says "WAVE-1"
    says "pushed"
}

case_a_second_clock_in_a_stamp_is_refused() {
    fresh case_a_second_clock_in_a_stamp_is_refused
    # Two clocks in one ledger is a measured defect of the old rows: CEST and
    # unlabelled-PDT side by side, normalised by nobody.
    sed -i.bak 's/done=13:00 met=13:20/done=13:00 CEST met=13:20/' "$DIR/in-flight.md"
    run_fixture
    exits 2
    says "RUNG-C"
    says "one clock"
}

# --- the unstamped population -------------------------------------------------

case_a_row_with_no_stamps_is_counted_never_dropped() {
    fresh case_a_row_with_no_stamps_is_counted_never_dropped
    run_fixture
    exits 0
    says "unstamped"
    says "RUNG-D"
    says "RUNG-E"
    # And it says how many of how many, so a reader can tell a ledger that is
    # nearly migrated from one that is nearly not.
    says "2 of 8"
}

case_a_ledger_with_no_stamped_row_measures_nothing_and_says_so() {
    fresh case_a_ledger_with_no_stamped_row_measures_nothing_and_says_so
    # Strip every stamps cell. The reader must not median over an empty set and
    # must not exit 2 either: an unmigrated ledger is a ledger to backfill, not
    # a broken instrument.
    sed -i.bak 's/stamps: [^|]*//' "$DIR/in-flight.md"
    run_fixture
    exits 0
    says "8 of 8"
    says "no stamped row"
}

# --- 4 · read-only and deterministic ------------------------------------------

case_metrics_are_read_only_and_deterministic() {
    fresh case_metrics_are_read_only_and_deterministic
    loop_log leaf-1 "the fast tier NARROWED to the active rung's scope — its own app(s) [example], which run IN FULL, plus the reverse-transitive depends_on closure [-], which runs its fast tier — plus the always-on cross-app set" 100
    bank_log_green bank-1 1879
    bank_log_red bank-2
    run_fixture
    exits 0
    cp "$OUT" "${WORK}/first-${N}.out"
    # The whole fixture world goes read-only, directories included: a reader
    # that opens anything for writing cannot survive this, and one that only
    # reads cannot tell the difference.
    chmod -R a-w "$DIR"
    run_fixture
    if chmod -R u+rwX "$DIR"; then :; fi
    exits 0
    if diff -q "${WORK}/first-$((N - 1)).out" "$OUT" >/dev/null 2>&1; then
        ok "two runs over one world are byte-identical"
    else
        bad "two runs over one world differ: $(diff "${WORK}/first-$((N - 1)).out" "$OUT" | head -5)"
    fi
    says "banks launched"
    # One green-and-pushed bank, one refused: 1 of 2 green.
    says "2 / 1 / 50%"
}

# --- the readouts header ------------------------------------------------------

case_the_cost_baseline_header_is_read_not_retyped() {
    fresh case_the_cost_baseline_header_is_read_not_retyped
    run_fixture
    exits 0
    # The fixture's header, which exists nowhere but the fixture.
    says "| Measure | Fixture column two | Fixture column three |"
    # And the reader's own text does not carry the real one.
    if grep -qF "The lever it measures" "$READER"; then
        bad "the reader carries the real header in its own text — it is retyped, not read"
    else
        ok "the reader carries no copy of the real header"
    fi
}

case_a_readouts_file_with_no_cost_baseline_section_is_exit_2() {
    fresh case_a_readouts_file_with_no_cost_baseline_section_is_exit_2
    printf '# Readouts — fixture\n\nNo section here at all.\n' >"$DIR/readouts.md"
    run_fixture
    exits 2
    says "COST BASELINE"
}

# --- refusals and real scale ---------------------------------------------------

case_an_unknown_flag_is_exit_2() {
    fresh case_an_unknown_flag_is_exit_2
    run --in-flight "$DIR/in-flight.md" --readouts "$DIR/readouts.md" --wat
    exits 2
    says_not "done→met"
}

case_an_absent_ledger_is_exit_2() {
    fresh case_an_absent_ledger_is_exit_2
    run --in-flight "$DIR/nowhere.md" --readouts "$DIR/readouts.md"
    exits 2
    says "nowhere.md"
}

case_the_real_ledger_reads_and_names_what_it_could_not_measure() {
    fresh case_the_real_ledger_reads_and_names_what_it_could_not_measure
    if [ ! -r "$REAL_LEDGER" ] || [ ! -r "$REAL_READOUTS" ]; then
        echo "  skipped  ${CURRENT} — this checkout has no dispatch ledger to copy"
        return 0
    fi
    cp "$REAL_LEDGER" "$DIR/real-in-flight.md"
    cp "$REAL_READOUTS" "$DIR/real-readouts.md"
    run --in-flight "$DIR/real-in-flight.md" --readouts "$DIR/real-readouts.md" \
        --bank-logs "$DIR/banks" --loop-logs "$DIR/loops"
    exits 0
    # The real ledger's rows predate the grammar, so the honest answer is a
    # count of what could not be measured and not a median over nothing.
    says "unstamped"
    says "COST BASELINE"
}

case_the_json_carries_the_same_numbers() {
    fresh case_the_json_carries_the_same_numbers
    run_fixture --json
    exits 0
    says '"stage3"'
    says '"unstamped"'
    if "$DRIVE_PY" -c 'import json,sys; json.load(open(sys.argv[1]))' "$OUT"; then
        ok "the json parses"
    else
        bad "the json does not parse"
    fi
}

case_a_docs_only_bank_is_a_green_bank_with_its_own_wall() {
    fresh case_a_docs_only_bank_is_a_green_bank_with_its_own_wall
    bank_log_green bank-1 1879
    bank_log_docs_only bank-2 43
    bank_log_red bank-3
    run_fixture
    exits 0

    CURRENT="a docs-only push is a bank that went green, and is named as one"
    says "3 / 2 / 67%"
    says "(1 docs-only)"

    CURRENT="and its own total is the wall that goes into the population"
    # The median of 1879 and 43. A reader that dropped the docs-only wall
    # would report the full bank's alone, and the whole point of the road is
    # that the population now has two very different kinds of member in it.
    says "961"

    CURRENT="the line the reader matches is the line the road PRINTS"
    # A fixture typed here and a printer over there is exactly how a reader
    # goes blind while its own drive stays green. The shape is asserted
    # against the one site that writes it.
    if grep -F 'docs-only reuse of ${GATE_DOCS_ONLY_SOURCE} — readers ' "$PUSHER" >/dev/null; then
        ok "the push script prints the line this reader matches"
    else
        bad "the push script no longer prints 'docs-only reuse of <M> — readers …' — the reader is matching a line nothing writes"
    fi
}

case_this_drive_cites_no_ledger_coordinate() {
    CURRENT=case_this_drive_cites_no_ledger_coordinate
    OUT=""
    # The fixture ids in this file and in the reader must be invisible to the
    # archaeology census, which counts ledger coordinates and finding ids in
    # every file that ships. Asserted rather than trusted.
    local hits raw
    # `grep -c` exits 1 when it counts nothing, which under `pipefail` is the
    # answer this case WANTS and a dead shell either way. Captured, then read.
    raw=$(grep -cE '\bP[0-9]{1,2}-[A-Za-z0-9]+\b|\bN[0-9]{2,3}\b' "$0" "$READER" 2>/dev/null || true)
    hits=$(printf '%s\n' "$raw" | awk -F: '{s+=$2} END {print s+0}')
    if [ "$hits" = "0" ]; then
        ok "neither this drive nor the reader carries a ledger coordinate"
    else
        bad "${hits} ledger-coordinate-shaped token(s) in this drive or the reader"
    fi
}

case_the_two_clocks_are_derived_from_the_stamps
case_the_wave_of_a_rung_is_derived_from_the_clocks
case_the_inner_loop_is_reported_by_change_class
case_a_malformed_stamp_cannot_be_measured
case_a_merged_rung_with_no_met_stamp_cannot_be_measured
case_a_note_row_that_was_merged_and_never_dispatched_is_named_as_one
case_a_wave_with_no_pushed_stamp_cannot_be_measured
case_a_second_clock_in_a_stamp_is_refused
case_a_row_with_no_stamps_is_counted_never_dropped
case_a_ledger_with_no_stamped_row_measures_nothing_and_says_so
case_metrics_are_read_only_and_deterministic
case_the_cost_baseline_header_is_read_not_retyped
case_a_readouts_file_with_no_cost_baseline_section_is_exit_2
case_an_unknown_flag_is_exit_2
case_an_absent_ledger_is_exit_2
case_the_real_ledger_reads_and_names_what_it_could_not_measure
case_the_json_carries_the_same_numbers
case_a_docs_only_bank_is_a_green_bank_with_its_own_wall
case_this_drive_cites_no_ledger_coordinate

echo "test_loop_metrics: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property of the velocity reader did not hold. The numbers it derives" >&2
    echo "   go into the cost-baseline table that every cycle is measured against:" >&2
    echo "   a median over the convenient half of the ledger reads exactly like a" >&2
    echo "   median over all of it." >&2
    exit 1
fi
exit 0
