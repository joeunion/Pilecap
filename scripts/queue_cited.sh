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
# THE QUEUE-CITATION CENSUS — which N-rows the TREE cites, and what the QUEUE
# says about them.
#
#   ./scripts/queue_cited.sh            the census
#   ./scripts/queue_cited.sh --help     what it is, and stop
#
# WHY IT EXISTS. A full-backlog triage once checked every open row against the
# tree and found **58% of the backlog was already paid** — most of it never
# marked so, carrying its own id somewhere in the tree already: a docstring
# naming the incident, a test named after the finding, a `does_not_cover`
# clause citing the row it declared. The fix cites the row. The row never
# cites the fix. So a backlog that had actually been drained by more than half
# read as if it had not been touched, and the PM's ordering ran on a
# denominator that was wrong by more than half.
#
# A triage is how that was found, and a triage is a person reading every open row.
# This is the cheap standing form of the same read: grep the tree for row ids,
# ask the queue what each one's row says, and print the disagreement.
#
# IT IS A RITUAL INSTRUMENT, NOT A GATE LEG. It exits 0 whatever it finds and
# `scripts/check.sh` does not run it. A citation is EVIDENCE that somebody
# worked on a row, never proof the row is finished — a docstring may cite the
# row it only partly paid, and a fix may cite the row it made worse. Turning
# that into a build failure would be turning a lead into a verdict, and the only
# thing a builder could do about a wrong verdict is delete the citation, which
# is the one behaviour this census exists to encourage. So it informs the PM's
# CLOSE (`.claude/skills/product-manager/references/operations.md`, "The
# queue-citation census, at every CLOSE") and decides nothing.
#
# THREE VERDICTS PER ID, and the middle one is the finding:
#
#   CITED AND CLOSED     the tree cites it and the queue agrees it is paid —
#                        struck inline (`~~N<id>~~`) or named in the queue's
#                        own triage verdict block's DONE/STALE lists. Counted, not listed: this is the
#                        healthy shape and a census that printed it would bury
#                        the other two.
#   CITED BUT UNSTRUCK   the tree cites it and the row is still open. THE
#                        FINDING. Each one is a row to read: either the work
#                        landed and the row owes a strike, or the citation is a
#                        promise the tree is making that nobody has checked.
#   CITED WITH NO ROW    an id the queue does not carry at all. A typo, an id
#                        from another ledger, or a row deleted rather than
#                        struck. Rare and worth a look either way.
#
# PARTIAL rows are printed in their own block rather than folded into either.
# The queue's own triage verdict block names eight ids as "split, do not
# strike" — each about half paid — and a partial row IS still open, so a
# citation of one is genuinely unstruck.
# It is a different action for the PM (split the row) from an ordinary unstruck
# one (strike it or read it), which is the whole reason for the separate block.
#
# THE QUEUE IS READ WITH ITS OWN TRIAGE VERDICT BLOCK AS THE AUTHORITY, exactly
# as that block says of itself: "Rows named DONE or STALE here are CLOSED even
# where their inline text is unstruck — the physical reconciliation is [the
# restructure row]." So an id in the DONE list is closed however its own row
# still reads, and the rows waiting on that restructure do not each become a
# finding here.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. WHETHER A CITATION MEANS THE WORK IS DONE. It does not, and this census
#      never claims it does. It reports a disagreement between two documents and
#      hands the reading to a person. Every line of output is a question.
#   2. A ROW PAID WITH NO CITATION ANYWHERE. The commonest shape in that first
#      triage was a row whose fix DID cite it; the shape this cannot see is a
#      fix that cited nothing, and there is no way to find those but to read the
#      row against the tree. This census narrows a triage; it does not replace
#      one.
#   3. `docs/product/` ITSELF, deliberately. The scope is `apps/ quality/
#      scripts/ config/ docs/runbooks/` — the places a FIX lives. Reports,
#      ledgers, cycle plans and in-flight rows cite ids constantly and by
#      design, and including them would make every open row cite itself.
#   4. THE TWO-ROWS-UNDER-ONE-ID POPULATION. The triage verdict block names eight ids
#      carrying two rows apiece, one half DONE and one half OPEN. This census
#      carries ONE status per id and takes whichever the queue states last for
#      it, so a citation of the open half of a split id can read as closed.
#      Renumbering is the restructure row's job; until then the census reads
#      that list OFF THE QUEUE and prints it in its own footer, so a reader can
#      discount those ids by name. It is read rather than written down here for
#      the reason in the pass-1 note: an id spelled in this file's own prose
#      would become a citation of itself the next time it ran.
#   5. AN ID INSIDE PROSE THAT IS NOT A CITATION. `N` followed by digits at a
#      word boundary is the whole of the match. A tree that grew a variable
#      shaped the same way (bare `N` plus digits) would be counted; nothing in
#      the tree does today, and the CITED-WITH-NO-ROW block is where such a
#      thing would surface.
#   6. LINE NUMBERS AGE. `file:line` is where the citation was when the census
#      ran. Nothing pins it and nothing re-checks it later.
set -euo pipefail

cd "$(dirname "$0")/.."

SELF="queue_cited"

cannot_look() {
    echo "!! ${SELF}: $*" >&2
    echo "   Nothing was censused. An instrument that could not look has not" >&2
    echo "   reported a clean tree." >&2
    exit 2
}

usage() {
    cat <<'USAGE'
scripts/queue_cited.sh — the queue-citation census

  ./scripts/queue_cited.sh          print the census; always exit 0
  ./scripts/queue_cited.sh --help   this text

Greps apps/ quality/ scripts/ config/ docs/runbooks/ for queue row ids (shaped
like `N` plus digits), asks docs/product/queue.md what each row says, and prints the ones the tree
cites and the queue still carries as open. It is a ritual instrument for the
PM's CLOSE, not a gate leg: it never fails a build.
USAGE
}

case "${1:-}" in
"") ;;
--help | -h)
    usage
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': queue_cited.sh takes nothing or --help" >&2
    exit 2
    ;;
esac

QUEUE="docs/product/queue.md"
[ -r "$QUEUE" ] || cannot_look "${QUEUE} is not readable from $PWD — there is nothing to check citations against"

# The places a FIX lives. Blind spot 3 is why `docs/product/` is not here.
SCOPE="apps quality scripts config docs/runbooks"
PRESENT=""
for dir in $SCOPE; do
    [ -d "$dir" ] && PRESENT="${PRESENT}${PRESENT:+ }${dir}"
done
[ -n "$PRESENT" ] ||
    cannot_look "none of the scope directories (${SCOPE}) exist from $PWD — this is not a checkout root"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-queue-cited.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
trap 'rm -rf "$WORK"' EXIT

CITES="${WORK}/cites.txt"

# `-o` with `-n` gives one line per OCCURRENCE, which is what makes the
# "(+N more)" count honest. The id is re-extracted from the matched text
# because the boundary characters are part of the match.
# shellcheck disable=SC2086
grep -rnoE --binary-files=without-match \
    --exclude-dir=__pycache__ --exclude-dir=.venv --exclude-dir=node_modules \
    '(^|[^A-Za-z0-9_])N[0-9]{1,3}[a-z]?([^A-Za-z0-9_]|$)' \
    $PRESENT 2>/dev/null |
    awk -F: '
        {
            file = $1; line = $2;
            rest = $0;
            sub(/^[^:]*:[^:]*:/, "", rest);
            if (match(rest, /N[0-9]+[a-z]?/)) {
                print substr(rest, RSTART, RLENGTH) "\t" file ":" line;
            }
        }' |
    LC_ALL=C sort -u >"$CITES" || true

[ -s "$CITES" ] ||
    cannot_look "the scope (${PRESENT}) cites no row id at all. This tree has always cited
   hundreds; an empty census is a broken grep, never a clean tree."

# LC_ALL=C, deliberately: the queue is full of em-dashes and interpuncts, and
# BSD awk under a UTF-8 locale dies on a multibyte character it meets inside a
# bracket expression rather than reading the line. Bytes are all this census
# needs — every id it matches is ASCII.
LC_ALL=C awk -F'\t' -v queue="$QUEUE" -v scope="$PRESENT" '
    # ---- pass 1: what the queue says ----------------------------------------
    #
    # Two maps, resolved at the end. The H3 block is "THE AUTHORITY ON ROW
    # STATUS BELOW THIS LINE" by its own declaration, so it wins over the
    # inline row text wherever the two disagree.
    FNR == NR {
        line = $0;

        if (line ~ /^\*\*DONE \(/)    { collect(line, "done (H3)");    next }
        if (line ~ /^\*\*STALE \(/)   { collect(line, "stale (H3)");   next }
        if (line ~ /^\*\*PARTIAL/)    { collect(line, "partial (H3)"); next }

        # The two-rows-under-one-id advisory, DERIVED rather than typed: this
        # script must not spell a row id in its own prose, because it censuses
        # the tree it lives in and every id it wrote down would become a
        # citation of itself (rung-execution §5, the phantom-registration
        # class).
        if (line ~ /^\*\*QUEUE-INTEGRITY/) { splits = ids_in(line); next }

        # A row-defining line: a table row whose FIRST cell is the id, or a
        # bullet whose first bold token is the id. Anything else mentioning an
        # id is prose about it, not its row.
        #
        # A bullet may carry a lane prefix before the id — `- **U-B / Nxxx (…`
        # is how some queue lanes book theirs — so the id is looked for in the
        # leading 40 characters rather than immediately after the bold marker.
        # Forty because that is comfortably past every prefix in this file and
        # comfortably short of the first sentence, where an id would be prose
        # about another row rather than this row.
        head = substr(line, 1, 40);
        if (match(line, /^\| *~~N[0-9]+[a-z]?~~/) ||
            (line ~ /^- \*\*/ && head ~ /~~N[0-9]+[a-z]?~~/)) {
            note(idof(head), "struck");
            next
        }
        if (match(line, /^\| *N[0-9]+[a-z]?[ )]/) ||
            (line ~ /^- \*\*/ && head ~ /N[0-9]+[a-z]?[ (:]/)) {
            note(idof(head), "open");
            next
        }
        next
    }

    # ---- pass 2: what the tree cites ---------------------------------------
    {
        id = $1; where = $2;
        n[id]++;
        if (!(id in first)) { first[id] = where }
    }

    END {
        closed = 0; unstruck = 0; partial = 0; norow = 0; above = 0;

        # An id-shaped match above the highest id the queue carries is not this
        # numbering at all: the pep8-naming rule codes ruff suppressions carry
        # live up there, and they are the only population that reaches the
        # grep. The ceiling is DERIVED from the queue, so a queue that grows
        # past it starts counting those ids again with no edit here.
        for (id in n) { if (num(id) > maxid) { above++; continue } ids[++k] = id }
        # A plain sort would put a three-digit id before a two-digit one, out of
        # numeric order. Sorting on the numeric part is the only order a reader
        # can scan.
        for (i = 1; i <= k; i++) {
            for (j = i + 1; j <= k; j++) {
                if (num(ids[j]) < num(ids[i]) ||
                    (num(ids[j]) == num(ids[i]) && ids[j] < ids[i])) {
                    t = ids[i]; ids[i] = ids[j]; ids[j] = t;
                }
            }
        }

        for (i = 1; i <= k; i++) {
            id = ids[i];
            st = status(id);
            verdict = st;
            sub(/ \(via N[0-9]+\)$/, "", verdict);
            if (verdict == "done (H3)" || verdict == "stale (H3)" || verdict == "struck") {
                closed++;
            } else if (verdict == "partial (H3)") {
                partial++;
                partial_rows[partial] = render(id, st);
            } else if (verdict == "") {
                norow++;
                norow_rows[norow] = render(id, "no row");
            } else {
                unstruck++;
                unstruck_rows[unstruck] = render(id, st);
            }
        }

        printf "== the queue-citation census — what the tree cites, what the queue says\n";
        printf "   scope: %s\n", scope;
        printf "   queue: %s\n\n", queue;

        emit("CITED BUT UNSTRUCK — the tree names the row; the row is still open",
             unstruck, "unstruck_rows");
        emit("PARTIAL (the H3 block: split, do not strike) — half-paid and cited",
             partial, "partial_rows");
        emit("CITED WITH NO ROW — an id the queue does not carry",
             norow, "norow_rows");

        printf "== %d ids cited · %d closed (struck, or named DONE/STALE by the triage block) · %d CITED-BUT-UNSTRUCK · %d partial · %d with no row\n",
               k, closed, unstruck, partial, norow;
        printf "   Each unstruck line is a QUESTION, never a verdict: the work may have landed\n";
        printf "   and the row owe a strike, or the citation may be a promise nobody checked.\n";
        printf "   Read the row. This instrument never fails a build.\n";
        if (splits != "") {
            printf "   Discount by name where a split id is in play (blind spot 4): %s\n", splits;
        }
        if (above > 0) {
            printf "   Dropped as not this numbering, being above the highest row the queue\n";
            printf "   carries (N%d): %d id-shaped match(es). Pep8-naming rule codes live there.\n", maxid, above;
        }
    }

    # ---- helpers ------------------------------------------------------------
    function collect(line, verdict,   parts, i, tok) {
        # The triage verdict lists are space-separated ids with the occasional
        # annotation (`Nxxx(update)`, `Nxxxc`). Take the leading id off each token.
        n_parts = split(line, parts, /[ ·]+/);
        for (i = 1; i <= n_parts; i++) {
            tok = parts[i];
            if (match(tok, /^N[0-9]+[a-z]?/)) {
                h3[substr(tok, RSTART, RLENGTH)] = verdict;
            }
        }
    }

    # One row status, and the ceiling the census is bounded by, recorded
    # together so the two can never drift apart.
    function note(id, verdict) {
        if (id == "") { return }
        row[id] = verdict;
        if (num(id) > maxid) { maxid = num(id) }
    }

    # Every id on one line, as a space-delimited string. Used for the
    # split-id advisory, which is read off the queue rather than typed here.
    function ids_in(line,   rest, out, tok) {
        rest = line; out = " ";
        while (match(rest, /N[0-9]+[a-z]?/)) {
            tok = substr(rest, RSTART, RLENGTH);
            if (index(out, " " tok " ") == 0) { out = out tok " " }
            rest = substr(rest, RSTART + RLENGTH);
        }
        return out;
    }

    function idof(line,   m) {
        m = line;
        gsub(/~/, "", m);
        if (match(m, /N[0-9]+[a-z]?/)) { return substr(m, RSTART, RLENGTH) }
        return "";
    }

    # Exact id first, then the base row a sub-letter id hangs off: a tree citing
    # a sub-lettered id is citing its base row when the queue carries no
    # sub-lettered row of its own.
    function status(id,   base) {
        if (id in h3)  { return h3[id] }
        if (id in row) { return row[id] }
        base = id;
        sub(/[a-z]$/, "", base);
        if (base != id) {
            if (base in h3)  { return h3[base] " (via " base ")" }
            if (base in row) { return row[base] " (via " base ")" }
        }
        return "";
    }

    function num(id,   m) {
        m = id;
        sub(/^N/, "", m);
        sub(/[a-z]$/, "", m);
        return m + 0;
    }

    function render(id, st,   more) {
        more = (n[id] > 1) ? sprintf(" (+%d more)", n[id] - 1) : "";
        return sprintf("  %-7s %-22s %s%s", id, st, first[id], more);
    }

    function emit(title, count, which,   i) {
        if (count == 0) {
            printf "%s\n  (none)\n\n", title;
            return;
        }
        printf "%s\n", title;
        for (i = 1; i <= count; i++) {
            if (which == "unstruck_rows") { print unstruck_rows[i] }
            else if (which == "partial_rows") { print partial_rows[i] }
            else { print norow_rows[i] }
        }
        printf "\n";
    }
' "$QUEUE" "$CITES"

exit 0
