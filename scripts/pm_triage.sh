#!/usr/bin/env bash
# The crash-triage cross-check — THE ARTIFACT HALF, and only that half.
#
#   ./scripts/pm_triage.sh                 # read docs/product/in-flight.md
#   ./scripts/pm_triage.sh <ledger.md>     # read another ledger file
#
# WHAT IT DOES. It reads the dispatch ledger's table rows, finds every row whose
# State is `dispatching` or `sent`, and prints them with their rung ids. That is
# the list of dispatches the FILES believe are outstanding.
#
# WHAT IT CANNOT DO, AND THIS IS THE POINT RATHER THAN A LIMITATION. **It cannot
# see the agent list.** A shell script has no way to ask which agents are alive
# or which reports came back; that lives in the session, in ListAgents and in
# the returned reports. So this script is exactly one half of a two-half
# discipline, and the other half is the PM's hands:
#
#   the ARTIFACT half (here)  — what the ledger says is outstanding
#   the AGENT half (the PM)   — what ListAgents and the returned reports say
#
# A row printed here with no live agent and no returned report behind it is a
# CRASHED DISPATCH: work nobody is doing that the files believe is in progress.
# That is the finding, and no script can reach it alone — which is why this one
# says so in its own header and again in its footer rather than letting a clean
# run read as an all-clear.
#
# WHY IT EXISTS.
# `docs/product/in-flight.md` already carries the rule — "at CLOSE, sweep the
# table: any row still at `dispatching` or `sent` with no live or returned agent
# behind it is a finding" — and, immediately after it, the reason a rule is not
# enough: **"When checking whether the loop is alive, ask the agent list — never
# this table."** The sweep is prose, done from memory, at the end of a cycle
# when there is the most to hold in one's head. This mechanises the half that
# can be mechanised so the PM spends their attention on the half that cannot.
#
# EXIT STATUS. **0 always** — it is a report, not a judge. Open rows are the
# normal state of a live cycle and are not a violation of anything; calling them
# one would train people to stop running it. The single exception is **exit 2,
# could-not-look**: the ledger is missing, unreadable, has no rows this reader
# recognises, or holds a row whose State column cannot be located. A parse this
# reader got wrong must never print a short list that reads like a clean one.
#
# HOW IT PARSES, declared because a markdown table is not a data format:
#
#   * A dispatch row is a line beginning with `|` that has AT LEAST 7 cells and
#     is neither the header (first cell `#`) nor a separator (`---`).
#   * The State column is found by ANCHORING ON THE STATE VOCABULARY, not by
#     counting, because the live ledger breaks counting in both directions:
#     one row carries a literal `|` inside its Task cell
#     (`TEMPORAL_MACHINERY_LIFETIME deployment|process`), which shifts every
#     column to its left; another carries an EXTRA eighth cell after
#     Result, which shifts every column counted from the right. So: try the
#     4th cell from the left, then the 4th from the right, then a scan of the
#     whole row for exactly one cell whose first word is a known state. Two
#     candidates, or none, is exit 2 for that row — never a guess.
#   * The State cell is matched on its FIRST WORD, because real states carry
#     tails: `returned — merging (2cad120)`, `returned — HOLDING for
#     merges-last`. An unknown first word is exit 2, not a silent skip.
#   * A line with fewer than 7 cells is a continuation/annotation row (the
#     `| P5-15b | (result) ... |` shape the ledger uses for overflow) and is
#     counted and reported as skipped, never silently dropped.
#
# WHAT IT DOES NOT COVER, beyond the agent half:
#
#   * WHETHER A `returned` ROW IS TRUE. A row marked returned whose agent
#     crashed before reporting is invisible here by construction — this reader
#     believes the state column.
#   * CLOSED CYCLES. It reads every table in the file it is given, including the
#     closed-cycle sections, and says which heading each row lives under. A
#     stale `sent` row in a closed cycle is a real finding and is printed; the
#     heading is how the PM tells it from a live one. It reports the NEAREST
#     `##` HEADING ABOVE the row and calls it that, rather than claiming the
#     row belongs to a section: the live ledger's own rows currently sit below
#     `## Friction log — P3`, and a reader that smoothed that over would be
#     inventing a structure the file does not have. Rows already moved out of
#     the live ledger into the closed-cycle archive are not read at all.
#   * ROLE. It does not care whether the row is a builder, a field test or a
#     reviewer; every open row owes the same cross-check.
set -euo pipefail

LEDGER="${1:-docs/product/in-flight.md}"
case "${1:-}" in
-h | --help)
    sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
-*)
    # A mistyped flag must never be a silently different report.
    echo "!! pm_triage: unknown flag '$1'. Usage: $0 [ledger.md]" >&2
    exit 2
    ;;
esac
if [ "$#" -gt 1 ]; then
    echo "!! pm_triage: one ledger at most; got: $*" >&2
    exit 2
fi

# Resolve relative to the checkout, not to the caller's cwd — this script is run
# from wherever the PM happens to be standing.
if [ ! -e "$LEDGER" ] && ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    [ -e "$ROOT/$LEDGER" ] && LEDGER="$ROOT/$LEDGER"
fi
if [ ! -r "$LEDGER" ]; then
    echo "!! pm_triage: cannot read '${LEDGER}'." >&2
    echo "   A ledger this reader could not open is not an empty ledger." >&2
    exit 2
fi

set +e
awk -v ledger="$LEDGER" '
function trim(s) { gsub(/^[ \t]+|[ \t]+$/, "", s); return s }
function word(s,   w) {                      # the first word of a State cell
    w = s
    sub(/[ \t].*$/, "", w)
    sub(/[^A-Za-z].*$/, "", w)
    return w
}
function known(s) {                          # the declared state vocabulary
    return (s == "dispatching" || s == "sent" || s == "returned" ||
            s == "merged" || s == "redirected" || s == "stopped" ||
            s == "struck" || s == "held")
}

/^##[^#]/ { heading = trim(substr($0, 3)); next }
!/^[ \t]*\|/ { next }

{
    line = $0
    sub(/^[ \t]*\|/, "", line)
    sub(/\|[ \t]*$/, "", line)
    n = split(line, cell, "|")
    for (i = 1; i <= n; i++) cell[i] = trim(cell[i])

    if (n < 7) { skipped++; next }               # continuation / annotation row
    if (cell[1] == "#") next                     # header
    if (cell[1] ~ /^-+$/) next                   # separator

    rows++

    # The anchor, in the declared order: 4th from the left, 4th from the right,
    # then one unambiguous scan.
    s = 0
    if (known(word(cell[4]))) s = 4
    else if (known(word(cell[n - 3]))) s = n - 3
    else {
        hits = 0
        for (i = 2; i <= n; i++) if (known(word(cell[i]))) { hits++; s = i }
        if (hits != 1) {
            broken[++nbroken] = cell[1] ": " (hits == 0 ? "no cell" : hits " cells") \
                " in this " n "-cell row read as a State — this reader will not guess which"
            next
        }
    }

    state = cell[s]
    first = word(state)
    if (first == "dispatching" || first == "sent") {
        open_n++
        open_id[open_n] = cell[1]
        open_state[open_n] = state
        open_role[open_n] = cell[s - 1]
        open_sent[open_n] = cell[s + 1]
        open_head[open_n] = heading
        task = cell[2]
        for (i = 3; i <= s - 2; i++) task = task "|" cell[i]      # the embedded-pipe row
        if (length(task) > 96) task = substr(task, 1, 93) "..."
        open_task[open_n] = task
    }
}

END {
    if (rows == 0) {
        printf("!! pm_triage: %s holds no dispatch row this reader recognises.\n", ledger) > "/dev/stderr"
        printf("   A ledger with no rows is this reader looking at the wrong file, not\n") > "/dev/stderr"
        printf("   a cycle with nothing in flight.\n") > "/dev/stderr"
        exit 2
    }
    if (nbroken > 0) {
        printf("!! pm_triage: %d row(s) whose State this reader could not read:\n", nbroken) > "/dev/stderr"
        for (i = 1; i <= nbroken; i++) printf("     %s\n", broken[i]) > "/dev/stderr"
        printf("   A partial list of open dispatches reads exactly like a short one.\n") > "/dev/stderr"
        exit 2
    }

    printf("pm_triage: the ARTIFACT half of the crash-triage cross-check.\n")
    printf("  ledger        %s\n", ledger)
    printf("  read          %d dispatch row(s)", rows)
    if (skipped > 0) printf(" (+%d continuation row(s) with fewer than 7 cells, skipped)", skipped)
    printf("\n")
    printf("  OPEN          %d row(s) at dispatching/sent\n\n", open_n)

    if (open_n == 0) {
        printf("No row is at dispatching or sent. The LEDGER believes nothing is outstanding.\n")
        printf("That is not the same as nothing being outstanding — see the footer.\n\n")
    } else {
        printf("EVERY ROW BELOW MUST BE MATCHED, BY HAND, AGAINST A LIVE OR RETURNED AGENT:\n\n")
        for (i = 1; i <= open_n; i++) {
            printf("  %-8s %-12s sent %-12s %s\n", open_id[i], open_state[i], open_sent[i], open_role[i])
            printf("           %s\n", open_task[i])
            if (open_head[i] != "") printf("           nearest ## above: %s\n", open_head[i])
            printf("\n")
        }
    }

    printf("---------------------------------------------------------------------------\n")
    printf("THIS SCRIPT CANNOT SEE THE AGENT LIST. It read a markdown table and nothing\n")
    printf("else: it does not know which agents are alive, which reports came back, or\n")
    printf("whether any row above has anybody behind it. That half is the PM'\''s, by hand,\n")
    printf("now:\n")
    printf("\n")
    printf("  1. ListAgents — which of the rows above has a LIVE agent?\n")
    printf("  2. The returned reports — which has a report the ledger never recorded?\n")
    printf("  3. Anything left over is a CRASHED DISPATCH: work nobody is doing that\n")
    printf("     these files believe is in progress. Re-dispatch it or close the row.\n")
    printf("\n")
    printf("A clean run of this script is NOT an all-clear, and the exit status is 0\n")
    printf("whatever it printed — it is a report, not a judge. The only exit 2 here is\n")
    printf("\"could not read the ledger\". (in-flight.md: \"When checking whether the loop\n")
    printf("is alive, ask the agent list — never this table.\")\n")
}
' "$LEDGER"
AWK_RC=$?
set -e
if [ "$AWK_RC" != "0" ]; then
    # 2 is could-not-look and is the only nonzero this script produces on its
    # own account; anything else out of awk is awk itself failing, which is
    # also a could-not-look.
    exit 2
fi
exit 0
