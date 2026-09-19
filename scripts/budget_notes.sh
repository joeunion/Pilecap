#!/usr/bin/env bash
# THE BUDGET SENTENCE READER. Sourced by `scripts/pm_fold.sh` (which applies the
# LOWERINGS) and by `scripts/rung_tidy.sh` (which applies the two PASTEABLE
# PROBLEM shapes). BASH ONLY, for the reason `scripts/gate_ledger.sh` states:
# sourced into an interactive zsh, `local path` ties to $PATH and every helper
# dies silently.
#
# NOT EXECUTABLE, AND THAT IS THE DECLARATION, not an oversight: this file
# reports no verdict of its own. It runs the engine's own budget check, hands
# back its whole output and a parse of it, and the CALLER owns the refusal and
# the exit status. It is a library beside `scripts/secrets_scan.sh`, not an
# instrument beside them.
#
# ---------------------------------------------------------------------------
# WHY IT EXISTS AS ONE FILE. `quality/gate.py::check_budgets` prints three
# shapes and only three, and two different instruments act on them:
#
#   LOWERING   `budget note: <section> … a human may commit the lower number:`
#              followed by `  <key>: <n>`. The FOLD's, and only the fold's:
#              lowering a ceiling is a decision that belongs in the bank's own
#              commit under its own subject (pm_fold.sh clause 3).
#   RAISE      `budget: <section> … The line to paste, verbatim:`
#   NEW SUBJECT `budget: <section> has no recorded ceiling for … The line to
#              paste under `<section>:` in quality/budgets.yaml:`
#              Both followed by `  <key>: <n>`. The TIDY's: they are what a
#              red house-rules leg is refusing on, and they land in the RUNG's
#              own diff where a reviewer reads them.
#
# A SECOND COPY OF THE PARSER IS THE DEFECT THIS FILE PREVENTS. The engine's
# sentences are an INTERFACE between quality/ and scripts/, and an interface
# read in two places drifts in one of them silently: a parser reading a
# sentence nobody prints any more reports "nothing to do", which looks exactly
# like a clean tree. The cross-check below is what makes that loud in BOTH
# callers at once — the engine states its own counts and each caller asserts
# that what it recognised is what the engine said it wrote.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER A NUMBER IS RIGHT. It reads what the engine printed. Whether the
#     measurement is honest about the tree is `quality/gate.py`'s own canary
#     population's question; whether a raise is LEGITIMATE is a reviewer's,
#     which is why the tidy writes it into the working tree rather than
#     committing it.
#   * THE COMPARISON AGAINST THE STANDING CEILING. That is the APPLY's, and it
#     stays with each caller: the fold owns "never raises" (its clause 3) and
#     the tidy owns "only what a sentence named". A library that applied would
#     be a library with an opinion about a tree it cannot see.
#   * A FOURTH SHAPE. If `check_budgets` grows one, the count cross-check makes
#     it a could-not-look in both callers on the first run. That is the
#     intended outcome and not a gap.

# budget_notes_collect <uv-command> <work-dir>
#
# Runs the engine's OWN budget check — called directly, so the sentences parsed
# below are the sentences the gate prints and never a reimplementation that can
# drift from them — and leaves its whole output in `<work-dir>/budget.out`.
# Returns the interpreter's status; the caller decides what a non-zero means.
budget_notes_collect() {
    local uv="$1" work="$2"
    cat >"${work}/budget_notes.py" <<'READER'
import sys

sys.path.insert(0, ".")
import quality.gate as gate  # noqa: E402

problems = gate.check_budgets()
for problem in problems:
    print(problem)
for note in gate.notes:
    print(note)
print("### budget-check: notes=%d problems=%d" % (len(gate.notes), len(problems)))
READER
    "$uv" run python "${work}/budget_notes.py" >"${work}/budget.out" 2>&1
}

# budget_notes_summary_lines <budget.out> — how many summary lines the run
# printed. Exactly one is the only shape this reader recognises; zero or two is
# a could-not-look at the caller.
budget_notes_summary_lines() {
    grep -c '^### budget-check: ' "$1" || true
}

# budget_notes_claimed <budget.out> <notes|problems> — the count the ENGINE
# stated it wrote, which is the other half of every cross-check here.
# awk over `<name>=<count>` fields rather than a regex with a word boundary:
# `\b` is a GNU extension and this repository's BSD sed does not carry it, so a
# sed spelling would print nothing on the owner's machine and read as "the
# summary named no count" — a could-not-look for the reader's own reason.
budget_notes_claimed() {
    awk -v want="$2" '
        $1 == "###" && $2 == "budget-check:" {
            for (i = 3; i <= NF; i++) {
                split($i, kv, "=")
                if (kv[1] == want) print kv[2]
            }
        }
    ' "$1"
}

# THE TWO PARSERS. Both anchored on a sentence that must END the line, and both
# reading the record line that follows: two leading spaces, then `<key>: <n>`.
# `match(..., /: [0-9]+[ \t]*$/)` finds the LAST `": N"`, so a key carrying `::`
# (every `out_schema_fields` key does: `apps/x/schemas.py::ThingOut`) splits
# correctly. Output is `<section>\t<key>\t<value>`, one per line.

# budget_notes_lowerings <budget.out> <out.tsv> — the FOLD's half.
budget_notes_lowerings() {
    awk '
        /a human may commit the lower number:$/ {
            if ($1 == "budget" && $2 == "note:") { sect = $3; pend = 1; next }
            pend = 0; next
        }
        pend == 1 {
            pend = 0
            line = $0
            if (substr(line, 1, 2) != "  ") next
            if (match(line, /: [0-9]+[ \t]*$/) == 0) next
            key = substr(line, 3, RSTART - 3)
            val = substr(line, RSTART + 2)
            sub(/[ \t]+$/, "", val)
            printf "%s\t%s\t%s\n", sect, key, val
        }
    ' "$1" >"$2"
}

# budget_notes_pastables <budget.out> <out.tsv> — the TIDY's half: the RAISE and
# the NEW SUBJECT, which are the two shapes that END in a pasteable line. The
# lowering sentence is deliberately not among them — there is no branch here in
# which the tidy reads one.
budget_notes_pastables() {
    awk '
        /The line to paste, verbatim:$/ || /in quality\/budgets\.yaml:$/ {
            if ($1 == "budget:") { sect = $2; pend = 1; next }
            pend = 0; next
        }
        pend == 1 {
            pend = 0
            line = $0
            if (substr(line, 1, 2) != "  ") next
            if (match(line, /: [0-9]+[ \t]*$/) == 0) next
            key = substr(line, 3, RSTART - 3)
            val = substr(line, RSTART + 2)
            sub(/[ \t]+$/, "", val)
            printf "%s\t%s\t%s\n", sect, key, val
        }
    ' "$1" >"$2"
}

# budget_notes_count <tsv> — the recognised count, the near half of the
# cross-check. `grep -c .` and not `wc -l`, so a trailing blank line cannot be
# counted as a record.
budget_notes_count() {
    grep -c . "$1" || true
}
