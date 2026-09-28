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
# THE FOLD. Regenerate this checkout's DERIVED files, and commit exactly those
# — or refuse, loudly, having committed nothing.
#
#   ./scripts/pm_fold.sh        # fold this checkout
#   ./scripts/pm_fold.sh --only <steps> [--no-commit]
#   ./scripts/pm_fold.sh --help
#
# `--bank` and `--no-fold` belong to the two callers (`scripts/pm_push.sh`,
# `scripts/pm_merge.sh`) and are not this script's: a flag that LOOKS like the
# wiring's own flag is still not this script's, and it is refused here like any
# other unknown one.
#
# --ONLY AND --NO-COMMIT, AND WHY THEY ARE HERE RATHER THAN IN A SECOND WRITER.
# `scripts/rung_tidy.sh --secrets` needs the baseline re-scanned INSIDE a rung,
# in the working tree, with nothing committed. The one thing it must not do is
# run `detect-secrets scan --baseline` itself: this file's step (c) is the
# tree's ONE LEGAL BASELINE WRITER (`.claude/skills/rung-execution/SKILL.md` §3,
# `scripts/tests/test_secrets_baseline_guard.sh::case_the_fold_is_the_only_
# baseline_writer_and_names_no_paths`), and a second invocation anywhere is the
# measured hazard that guard exists to refuse. So the tidy INVOKES this script
# with the two flags below and the one line stays where it is, under this
# script's exit guard, its dirty-path rule and its census.
#
#   --only <steps>   a comma-joined subset of the step names, which are a
#                    CLOSED list: contract|schema|secrets|budgets|walls|map (a-f),
#                    plus whatever `scripts/local/fold.d/` declares (see THE
#                    PRODUCT'S DRAWER below). An unknown name is exit 2, never a
#                    silently smaller fold.
#   --no-commit      regenerate and leave the result in the WORKING TREE. The
#                    census still runs — a stray is still exit 2 — and nothing
#                    is staged and nothing is committed. Legal only WITH
#                    `--only`, because a whole fold that commits nothing is a
#                    bank that vouches for a tree nobody wrote down.
#
# WHAT THEY DO NOT LIFT, and it is not an oversight: CLAUSE 1 STANDS. A fold
# folds a COMMITTED tree whichever flags it was handed, so `rung_tidy --secrets`
# is a BOUNDARY command — which is where it is wanted anyway. The sentence that
# sends a builder to it is the previous bank's `BASELINE SHIFTED`, read at the
# START of the next rung, on a tree that has just been reset to main. A flag
# that lifted clause 1 would buy a mid-leg convenience and pay for it with a
# working tree nobody can partition.
#
# EXIT: 0 folded, or nothing to fold · 1 NEVER — no finding this instrument can
# make is a "I looked, and it is wrong"; a derived file that disagrees with the
# checkout is a file to REGENERATE, not a violation to report · 2 REFUSED, or
# COULD NOT LOOK. 2 outranks a pass here as everywhere
# (`docs/product/instruments.md`).
#
# WHY IT EXISTS, and it is a scar the sibling product paid for rather than a
# convenience. Derived files are generated from the tree and committed BACK
# into it, so between two commits they are always potentially stale — and a
# stale derived file is silent. A generated API client that is two schema
# changes old still COMPILES (`frontend/scripts/pin_client.sh`'s header). A
# `.secrets.baseline` that no longer matches the tree passes every scan that
# reads it. A budget ceiling standing above what the tree measures is headroom
# nobody granted. Each of them is discovered at the WORST moment: inside the
# ~8-minute full gate, on the shared push train, by whoever happened to bank.
# The measured cost their side was ~45 minutes and three false-start banks in
# ONE night; ours is the merge-order union-red in the P16 friction log, which is
# the same class' other half. A PM checklist in prose was the cheaper
# alternative and it is the thing that already failed at this job.
#
# So the fold runs ONCE, at the bank, ahead of the gate, and the gate then
# measures the tree the fold left. That ordering is the whole design and it is
# argued at the two call sites: folding AFTER the gate would be worse than not
# folding at all, because the verdict would vouch for a tree the fold then
# changed.
#
# THE FOUR CLAUSES, which are what make an unattended committing script safe to
# have in the ritual at all:
#
#   1. A DIRTY TREE IS REFUSED, EXCEPT AN ABSORBED PATH. A fold folds a
#      COMMITTED tree. With work already in the checkout there is no way to say
#      which of the changes the fold made, and the commit this script writes
#      would carry whatever it swept up. The one exception is the typed
#      ABSORBED list — a derived path written from OUTSIDE this checkout, which
#      no step here can regenerate and which is therefore never somebody's
#      work: today `scripts/test_impact.json`, argued at the list itself.
#   2. IT MAY TOUCH ONLY THE DERIVED LIST. After the generators run, the whole
#      of `git status --porcelain -uall` is partitioned against the typed list
#      below; a single path outside it is exit 2, with NOTHING committed and
#      the evidence left in the tree.
#   3. IT NEVER RAISES A CEILING. The budgets step applies only numbers the
#      gate itself printed under its own lowering sentence, and it cross-checks
#      the count: the engine's note count and this parser's recognised count
#      must agree, or the run is a could-not-look. AND IT OWNS THE COMPARISON
#      ITSELF: at the apply, each number is measured against the ceiling
#      standing in the file being rewritten, and anything not STRICTLY LOWER is
#      a refusal naming section, key, old and new. `quality/gate.py` does
#      compare before printing — but a note is an INPUT, and inputs are not
#      trusted; a crafted note carrying the sentence verbatim and a higher
#      number was once applied and committed as "1 budgets lowered", exit 0.
#      The worst reachable outcome is "I could not look", never a silently
#      raised floor.
#   4. IT REFUSES A PIPE AND AN UNKNOWN FLAG, at exit 2, for the reason
#      `scripts/check.sh` and `scripts/pm_merge.sh` each give at their own
#      guard: a pipe replaces this script's exit status with the filter's, and
#      the exit status is the whole verdict.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE DERIVED FILES ARE RIGHT. It makes them agree with this
#     checkout. Whether the checkout's schema, secrets or budgets are what
#     anybody wanted is the gate's question and the reviewer's, not this
#     script's.
#   * WHETHER THE TREE SHOULD BE PUSHED OR MERGED. That is the caller's.
#   * A FIFTH DERIVED FILE OF THE TEMPLATE'S OWN. `DERIVED_PATHS` below is
#     TYPED, never computed, and that is deliberate on two counts: a computed
#     list is a list that grows whenever a generator misbehaves, which is the
#     one thing clause 2 exists to catch — and every one of those paths is READ
#     BACK BY THE GATE, which is precisely what a `derived-tree-paths`
#     declaration promises they are not (the reason is written out at the list
#     itself). A fifth TEMPLATE derived file is a human edit to this file.
#     A PRODUCT'S derived file is not: it declares itself, in the grammar this
#     tree already speaks, and the union is computed from the declarations —
#     which is what stops a product having to edit this file at all.
#   * WHETHER A DECLARED PATH IS HONEST. A fold-writes declaration says "I
#     write this". This fold believes it — that is what it partitions against
#     — and never checks that the step actually wrote it, only that nothing
#     ELSE appeared. A declared path a step quietly stopped regenerating is a
#     stale derived file this script cannot see.
#   * ANYTHING A LOCAL STEP DOES OUTSIDE THIS TREE. The census is
#     `git status --porcelain -uall` over this checkout, so a step that writes
#     into `/tmp`, into a sibling checkout, into a gitignored path, into a
#     database or over the network leaves NOTHING for clause 2 to partition
#     and is invisible here from start to finish. The drawer requires a step
#     to be TRACKED for exactly this reason — what it does is a reviewer's
#     question, and the tracking is what gives the reviewer the file — but
#     being reviewable is not being checked, and nothing in this script is a
#     sandbox.
#   * A NUMBER THAT IS LOWER BUT WRONG. Clause 3's comparison is arithmetic: a
#     note whose number is lower than the ceiling but is NOT the engine's
#     measurement is invisible here — the fold cannot know what was measured,
#     only what was printed. It reads the ceiling; whether the note is honest
#     about the tree is `quality/gate.py`'s canary population's question.
#   * A SECOND ALWAYS-MOVING FIELD. The `generated_at` strip below closes the
#     one stamp `detect-secrets scan` writes. A second such field, in that file
#     or another, restarts the churn this closes — inherited from the sibling
#     product with its reasoning, declared here rather than discovered. Step
#     (c)'s shape check refuses rather than guessing when the count it expects
#     is not what the scan wrote.
#   * A WRITER RACING THE FOLD. Clause 1 reads the tree once at the start and
#     clause 2 reads it once at the end. Somebody committing into this checkout
#     between them is covered only by those two sequential refusals.
#   * `.rung/introspect.json`. It is REGENERATED by step (b) and never
#     committed, because `/.rung/` is in this repository's `.gitignore`
#     (verified at rung time). It is therefore invisible to clause 2's census
#     BY CONSTRUCTION — `git status` never names it — and that is why it is not
#     in `DERIVED_PATHS`.
set -euo pipefail

# --- it refuses to be piped, for the reason in the header --------------------
# Detection and the CI exemption are check.sh's, deliberately identical
# (`scripts/check.sh`, and `scripts/pm_merge.sh` at its own guard): a pipe
# replaces this script's exit status with the filter's, which is exactly the
# failure this script's clause 4 exists to close. A TTY or a file redirect
# keeps it.
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! pm_fold refuses pipes — its exit status is the whole verdict, and a" >&2
    echo "   pipe replaces it with the filter's. Run it bare or redirect to a file." >&2
    exit 2
fi

# THE CHECKOUT THIS SCRIPT LIVES IN, not the caller's cwd. `pm_push.sh` and
# `pm_merge.sh` both invoke `$ROOT/scripts/pm_fold.sh` by absolute path from a
# checkout they have already proven is their own, so the two always agree; a
# human running it from somewhere else folds the tree the file is in, which is
# the only tree it can name the generators of.
cd "$(dirname "$0")/.." || {
    echo "!! pm_fold: could not reach the checkout this script lives in." >&2
    exit 2
}
ROOT="$(pwd -P)"

# THE BUDGET SENTENCE READER, shared with `scripts/rung_tidy.sh`. Sourced before
# the exit guard is armed so an absent library is a plain bash failure naming
# the file rather than this script's "DIED part-way" banner, which would name a
# cause it had not proven.
[ -r "$ROOT/scripts/budget_notes.sh" ] || {
    echo "!! pm_fold: scripts/budget_notes.sh is not in this checkout." >&2
    echo "   Step (d) reads the engine's budget sentences through it, and so does" >&2
    echo "   scripts/rung_tidy.sh. Without it this run would have to reimplement the" >&2
    echo "   parser — the one thing that file exists to prevent. Nothing was" >&2
    echo "   regenerated and nothing was committed." >&2
    exit 2
}
# shellcheck source=scripts/budget_notes.sh
. "$ROOT/scripts/budget_notes.sh"

# >>> exit-guard >>>
# A DRIVE THAT DIED IS NOT A DRIVE THAT PASSED, and the same sentence for an
# instrument that COMMITS. MEASURED on the bash this repository actually runs
# (GNU bash 3.2.57, macOS): when `set -u` kills the shell on an unbound
# variable, THE EXIT TRAP SEES `$? = 0` — the repro is three lines and it is
# written out in `scripts/tests/drive_preamble.sh` §5, and `scripts/publish.sh`
# carries the same guard for the same reason. So a run that died part-way would
# exit 0 and read to `pm_push --bank` as a clean fold over a half-regenerated
# tree.
#
# The predicate is therefore NOT the status. It is whether a line only a
# completed run reaches was reached: `FOLD_REACHED_THE_END=1` (the three
# completion arms) or `FOLD_REFUSED=1` (every refusal this script authors).
# Neither set, and the run died of its own shell.
FOLD_REACHED_THE_END=""
FOLD_REFUSED=""
FOLD_WORK=""
FOLD_DECL_ERR=""

fold_cleanup() {
    [ -z "${FOLD_WORK:-}" ] || rm -rf "$FOLD_WORK"
    [ -z "${FOLD_DECL_ERR:-}" ] || rm -f "$FOLD_DECL_ERR"
}

fold_on_exit() {
    local status="$1"
    fold_cleanup
    if [ -z "${FOLD_REACHED_THE_END:-}" ] && [ -z "${FOLD_REFUSED:-}" ]; then
        echo "" >&2
        echo "!! pm_fold: DIED part-way (the shell ended it, status ${status})." >&2
        echo "   The shell exited before the last line of this script and before any" >&2
        echo "   refusal this script authors. NOTHING THIS RUN PRINTED IS A VERDICT —" >&2
        echo "   the diagnostic bash printed above this line names the cause. The" >&2
        echo "   working tree may hold a half-regenerated derived file: read" >&2
        echo "   \`git status\` before doing anything else." >&2
        exit 2
    fi
}
trap 'fold_on_exit $?' EXIT
# <<< exit-guard <<<

refuse() {
    FOLD_REFUSED=1
    echo "!! pm_fold: $1" >&2
    shift
    while [ "$#" -gt 0 ]; do
        echo "   $1" >&2
        shift
    done
    exit 2
}

# --- THE STEP NAMES, A CLOSED LIST -------------------------------------------
# Five names for the five steps, in the order they run. TYPED here for the same
# reason `DERIVED_PATHS` is typed: a computed list is a list that grows whenever
# something misbehaves, and the whole value of `--only` is that a name it does
# not recognise is exit 2 rather than a silently smaller fold.
FOLD_STEP_NAMES='contract schema secrets budgets walls map'
FOLD_ONLY=""
FOLD_NO_COMMIT=""

# fold_step_selected <name> — with no `--only`, every step. With one, exactly
# the named subset.
fold_step_selected() {
    [ -n "$FOLD_ONLY" ] || return 0
    case ",${FOLD_ONLY}," in
    *",$1,"*) return 0 ;;
    esac
    return 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
    -h | --help)
        cat <<'USAGE'
THE FOLD. Regenerate this checkout's derived files and commit exactly those.

  ./scripts/pm_fold.sh                        fold this checkout
  ./scripts/pm_fold.sh --only <steps>         run only those steps
  ./scripts/pm_fold.sh --only <steps> --no-commit
                                              …and leave the result in the
                                              working tree, staging nothing
  ./scripts/pm_fold.sh --help

<steps> is a comma-joined subset of a CLOSED list: the six template steps, in
order — contract, schema, secrets, budgets, walls, map — plus every step this checkout's
scripts/local/fold.d/ declares, which run after them in name order. An unknown
name is exit 2, and the refusal prints both halves.

`--no-commit` is legal only WITH `--only`: a whole fold that commits nothing is
a bank that vouches for a tree nobody wrote down. `scripts/rung_tidy.sh
--secrets` is the caller these two exist for — step (c)'s scan line, the tree's
one legal baseline writer, stays in this file rather than being copied into a
second writer. (The command itself is deliberately not spelled here: a censused
string counts wherever it appears, prose included.)

`--bank` and `--no-fold` are the CALLERS' flags (scripts/pm_push.sh,
scripts/pm_merge.sh), never this script's.

Exit: 0 folded, or nothing to fold · 1 never · 2 refused, or could not look.

The four clauses: a dirty tree is refused (except a typed ABSORBED path, which
is a derived file written from outside this checkout); only the typed derived list may be
touched; a ceiling is never raised; a pipe and an unknown flag are refused.
None of them is lifted by the flags above. Read the header of this file for
what each one is made of.
USAGE
        FOLD_REACHED_THE_END=1
        exit 0
        ;;
    --only)
        FOLD_ONLY="${2:-}"
        [ -n "$FOLD_ONLY" ] ||
            refuse "--only takes a comma-joined subset of: ${FOLD_STEP_NAMES}" \
                "It was given nothing. Nothing was regenerated and nothing was committed."
        shift 2
        ;;
    --only=*)
        FOLD_ONLY="${1#--only=}"
        [ -n "$FOLD_ONLY" ] ||
            refuse "--only takes a comma-joined subset of: ${FOLD_STEP_NAMES}" \
                "It was given nothing. Nothing was regenerated and nothing was committed."
        shift
        ;;
    --no-commit)
        FOLD_NO_COMMIT=1
        shift
        ;;
    *)
        refuse "unknown argument '${1}'." \
            "pm_fold takes --only <steps>, --no-commit and --help, and nothing else. It" \
            "folds the checkout it lives in, which is ${ROOT}. \`--bank\` and" \
            "\`--no-fold\` belong to pm_push.sh and pm_merge.sh; a flag that looks like" \
            "the wiring's own flag is still not this script's." \
            "Nothing was regenerated and nothing was committed."
        ;;
    esac
done

# --- THE PRODUCT'S DRAWER: scripts/local/fold.d/<step>.sh --------------------
#
# A PRODUCT HAS DERIVED FILES THIS TEMPLATE HAS NEVER HEARD OF, and before this
# drawer the only way to fold one was to EDIT THIS FILE — which is what the one
# consumer did (their `pm_fold.diff`: `DERIVED_PATHS` rewritten and step (a)'s
# precondition re-spelled, in a file a template release then conflicts with, or
# worse fast-forwards over byte-identically with the edit silently dropped).
# The convention is the one every extension point here uses: a `local/` SIBLING
# of the template directory it extends, discovered by path, and NEVER shipped by
# a release — so absent is byte-identical and present is the product's own.
#
# THE CONTRACT, and each half of it is a refusal rather than a convention:
#
#   executable      a step is EXECUTED, from the checkout root. A `-x` bit that
#                   is not there is a step that silently never runs, which is
#                   the failure mode a drawer makes easy and nothing else here
#                   would catch.
#   declared        it names every path it writes, in the `derived-tree-paths`
#                   sentinel block the gate's own tree reader already reads
#                   (`scripts/tests/test_loop_ledger.sh`'s planted-declaration
#                   cases are the shape). The declaration is what clause 2
#                   partitions against: a step's declared paths are derived, and
#                   ANYTHING ELSE IT WROTE IS THE FOLD'S EXIT 2, naming the step.
#   named           the step's name is its basename without `.sh`, and it joins
#                   `--only`'s closed list. A name that collides with one of the
#                   template's four is exit 2 — a product shadowing `secrets`
#                   would be a product silently replacing the tree's one legal
#                   baseline writer.
#
# WHAT THE DRAWER DOES NOT LIFT. Clause 2 is not relaxed, it is WIDENED BY
# DECLARATION: the union is the typed list plus what each step declared about
# itself, and a step that declares nothing is refused rather than trusted. And
# the blind spot is the product's own and is declared here: whether a local
# step is IDEMPOTENT, and whether what it regenerated is RIGHT, is exactly as
# far outside this script's reach as the same question about `pin_client.sh`.
FOLD_LOCAL_DIR="$ROOT/scripts/local/fold.d"
FOLD_LOCAL_STEPS=""
FOLD_LOCAL_STEP_NAMES=""
FOLD_LOCAL_PATHS=""
FOLD_LOCAL_OWNERS=""
FOLD_DECL_READER="$ROOT/scripts/gate_ledger.sh"

# --- ONE READER, TWO GRAMMARS, AND THEY MUST NOT BE THE SAME ONE ------------
#
# `scripts/gate_ledger.sh::gate__derived_tree_paths` owns the PARSER: sentinels
# honoured only on a COMMENT line; the `<path> — <reason>` entry form with the
# em dash load-bearing (without it a paragraph inside a block declares whatever
# its first word is); the one-repository-relative-subtree validation; the
# tracked-path check; and the refuse-and-say-so answer to anything it cannot
# read. This file CALLS it and copies none of it — a second parser would be a
# second answer to "what did this tree declare", and the second one is the one
# nobody reads.
#
# BUT IT DOES NOT SHARE THE GATE'S SENTINEL, AND THAT IS A RULING RATHER THAN A
# STYLE. A `derived-tree-paths` declaration is SUBTRACTED FROM THE VERDICT KEY,
# and that library states the precondition in its own words: "NOTHING MEASURED
# READS THIS PATH BACK. Declare a path any check reads and the ledger will
# lie." A path THIS script commits is the opposite by construction — it is
# regenerated from the checkout and then read back by something that measures
# it. The consumer's own case is the proof: their generated `events.ts` is
# fold-committed AND compiled by `tsc` inside the gate, so a single grammar
# would have made every verdict key blind to the file the fold had just
# rewritten. So the fold has its OWN sentinel pair, read by this file and by
# nothing else, and the two populations stay disjoint by spelling.
#
#     the gate's:  derived-tree-paths   written after the measurement, never
#                                       read back, subtracted from the key
#     the fold's:  fold-writes          regenerated by the fold, committed,
#                                       and MEASURED like every other file
#
# The two sentinel strings are assembled below rather than written out, for the
# reason that cost this file a red run on its first day: a marker counts
# wherever it appears, so a comment spelling the opening sentinel would open a
# declaration IN THE FILE EXPLAINING IT.
FOLD_WRITES_BEGIN=">>> fold""-writes >>>"
FOLD_WRITES_END="<<< fold""-writes <<<"

# fold_declared_paths [<glob override>] — the paths declared in THE FOLD'S
# grammar, on stdout; the reader's notes on stderr. 0 read cleanly (zero paths
# is a clean read) · 1 the reader REFUSED · 2 the reader could not be reached.
#
# The three globals it overrides are the reader's whole configuration surface,
# which is what makes "one parser, two grammars" a call rather than a fork.
# With no glob override it reads the library's own source list — the places a
# generator lives — so a product's generator declares beside its own write and
# `pm_fold.sh` is never edited.
fold_declared_paths() {
    bash -c '
        set -uo pipefail
        . "$1" >/dev/null 2>&1 || exit 2
        declare -F gate__derived_tree_paths >/dev/null 2>&1 || exit 2
        GATE_TREE_DECL_BEGIN="$3"
        GATE_TREE_DECL_END="$4"
        [ -z "${5:-}" ] || GATE_TREE_DECL_SOURCES="$5"
        gate__derived_tree_paths "$2"
    ' _ "$FOLD_DECL_READER" "$ROOT" "$FOLD_WRITES_BEGIN" "$FOLD_WRITES_END" "${1:-}"
}

[ -r "$FOLD_DECL_READER" ] ||
    refuse "scripts/gate_ledger.sh is not in this checkout." \
        "The fold reads this tree's fold-writes declarations through that library's own" \
        "reader rather than through a second parser, so without it this run cannot say" \
        "what this checkout declares the fold regenerates — could-not-look." \
        "Nothing was regenerated and nothing was committed."

FOLD_DECL_ERR="$(mktemp "${TMPDIR:-/tmp}/djb-pm-fold-decl.XXXXXX")" ||
    refuse "could not make a scratch file for the declaration reader's notes." \
        "Nothing was regenerated and nothing was committed."

if [ -d "$FOLD_LOCAL_DIR" ]; then
    for _fold_local in "$FOLD_LOCAL_DIR"/*.sh; do
        # The glob is literal when the directory holds no `.sh` — an empty
        # drawer is byte-identical to no drawer, and neither is a refusal.
        [ -e "$_fold_local" ] || continue
        _fold_local_name="$(basename "$_fold_local" .sh)"
        _fold_local_rel="scripts/local/fold.d/${_fold_local_name}.sh"
        case " ${FOLD_STEP_NAMES} " in
        *" ${_fold_local_name} "*)
            refuse "${_fold_local_rel} takes the name of one of this fold's own steps." \
                "The template's own are ${FOLD_STEP_NAMES}, and a local step that shadowed" \
                "one would make --only ambiguous and could silently replace a step this" \
                "file's header calls the tree's only legal writer. Rename the local step." \
                "Nothing was regenerated and nothing was committed."
            ;;
        esac
        # TRACKED, AND ASKED BEFORE ANYTHING ELSE. An untracked or ignored file
        # in this drawer runs and commits exactly like a reviewed one, which
        # makes the drawer a way to put an unreviewed writer inside the one
        # unattended committing script in this repository. A step is code a
        # release and a reviewer can both see, or it does not run.
        if ! git ls-files --error-unmatch -- "$_fold_local_rel" >/dev/null 2>&1; then
            refuse "${_fold_local_rel} is not tracked by git." \
                "A step in this drawer is EXECUTED by the one script here that commits" \
                "unattended, so it is code a reviewer and a release can both see, or it does" \
                "not run. An untracked or ignored step is neither — and it would look" \
                "identical in the transcript to one somebody wrote on purpose." \
                "git add it, or take it out of the drawer." \
                "Nothing was regenerated and nothing was committed."
        fi
        [ -x "$_fold_local" ] ||
            refuse "${_fold_local_rel} is not executable." \
                "A step in this drawer is EXECUTED. A missing +x bit is a step that never" \
                "runs and says nothing about it — the one failure a drawer makes easy." \
                "Nothing was regenerated and nothing was committed."
        # THE GATE'S GRAMMAR IS NOT THE FOLD'S, and a step reaching for it is
        # stopped by name rather than quietly read as nothing. A fold.d step
        # declaring in the gate's sentinel would be asking for its own output
        # to be subtracted from the verdict key — the one thing the ruling
        # above says a fold-written path must never be.
        _fold_local_wrong="$(grep -n -e 'derived-''tree-paths' -- "$_fold_local" | sed -n '1p')" || _fold_local_wrong=""
        [ -z "$_fold_local_wrong" ] ||
            refuse "${_fold_local_rel}:${_fold_local_wrong%%:*} spells the GATE's declaration sentinel." \
                "    ${_fold_local_wrong#*:}" \
                "That grammar subtracts a path from the verdict key, and a path this fold" \
                "COMMITS is read back by the gate by construction — the consumer's generated" \
                "client is compiled inside it. A step declares in the fold's own grammar:" \
                "    # ${FOLD_WRITES_BEGIN}" \
                "    # path/to/the/file — why this step regenerates it" \
                "    # ${FOLD_WRITES_END}" \
                "Nothing was regenerated and nothing was committed."
        _fold_local_rc=0
        _fold_local_decl="$(fold_declared_paths "$_fold_local_rel" 2>"$FOLD_DECL_ERR")" ||
            _fold_local_rc=$?
        if [ "$_fold_local_rc" != "0" ]; then
            cat "$FOLD_DECL_ERR" >&2
            refuse "the declaration in ${_fold_local_rel} could not be read (notes above)." \
                "It is read by scripts/gate_ledger.sh's own reader, in that reader's entry" \
                "grammar, and a block it refuses is a block whose paths this fold cannot" \
                "partition against. Exit 2 from the reader means it could not be reached." \
                "Nothing was regenerated and nothing was committed."
        fi
        [ -n "$_fold_local_decl" ] ||
            refuse "${_fold_local_rel} declares no written paths." \
                "A step owes a sentinel block naming every path it writes — the em dash and" \
                "the reason are part of the entry form, because without them a paragraph" \
                "inside the block declares whatever its first word is:" \
                "    # ${FOLD_WRITES_BEGIN}" \
                "    # path/to/the/file — why this step regenerates it" \
                "    # ${FOLD_WRITES_END}" \
                "A block that is empty, one the reader could not read, and a path nothing" \
                "tracks are all this same refusal: the declaration is what clause 2" \
                "partitions against, and a step whose output nobody can partition is a step" \
                "that may commit anything." \
                "Nothing was regenerated and nothing was committed."
        # ONE PATH, ONE OWNER. Two steps declaring one path is two steps with a
        # claim on the same bytes and no order anybody wrote down: whichever
        # ran last wins, silently, and the census can attribute the write to
        # neither. The refusal names BOTH, because naming one is a bug report
        # the reader has to go and finish.
        while IFS= read -r _fold_local_p; do
            [ -n "$_fold_local_p" ] || continue
            _fold_local_owner=""
            while IFS="$(printf '\t')" read -r _o_path _o_step; do
                [ -n "$_o_path" ] || continue
                [ "$_o_path" = "$_fold_local_p" ] || continue
                _fold_local_owner="$_o_step"
            done <<EOF
$FOLD_LOCAL_OWNERS
EOF
            [ -z "$_fold_local_owner" ] ||
                refuse "two local fold steps declare '${_fold_local_p}'." \
                    "    scripts/local/fold.d/${_fold_local_owner}.sh" \
                    "    ${_fold_local_rel}" \
                    "Two steps with a claim on one path have no order anybody wrote down:" \
                    "whichever ran last would win, silently, and this run could attribute the" \
                    "write to neither of them." \
                    "Nothing was regenerated and nothing was committed."
            FOLD_LOCAL_OWNERS="${FOLD_LOCAL_OWNERS}${_fold_local_p}	${_fold_local_name}
"
        done <<EOF
$_fold_local_decl
EOF
        FOLD_LOCAL_PATHS="${FOLD_LOCAL_PATHS}${_fold_local_decl}
"
        FOLD_LOCAL_STEP_NAMES="${FOLD_LOCAL_STEP_NAMES}${FOLD_LOCAL_STEP_NAMES:+ }${_fold_local_name}"
        FOLD_LOCAL_STEPS="${FOLD_LOCAL_STEPS}${_fold_local_name}	${_fold_local}
"
    done
    unset _fold_local _fold_local_name _fold_local_rel _fold_local_decl _fold_local_p
    unset _fold_local_owner _fold_local_wrong _o_path _o_step
fi

# THE STEP LIST IS CLOSED, AND A NAME OUTSIDE IT IS EXIT 2. A typo that fell
# through to "select nothing" would be a fold that ran no step and said so in
# the voice of a clean tree. The closed list is the template's four PLUS
# whatever the drawer above declared — discovered, never typed, because the
# whole point of the drawer is that a product adds a step without editing this
# file; the refusal below names both halves so a typo is legible either way.
if [ -n "$FOLD_ONLY" ]; then
    IFS=',' read -r -a _fold_wanted <<<"$FOLD_ONLY"
    for _fold_step in "${_fold_wanted[@]}"; do
        case " ${FOLD_STEP_NAMES} ${FOLD_LOCAL_STEP_NAMES} " in
        *" ${_fold_step} "*) ;;
        *)
            refuse "--only names '${_fold_step}', which is not a step of this fold." \
                "The steps are a closed list, in the order they run: ${FOLD_STEP_NAMES}." \
                "This checkout's scripts/local/fold.d/ adds: ${FOLD_LOCAL_STEP_NAMES:-(nothing)}." \
                "Nothing was regenerated and nothing was committed."
            ;;
        esac
    done
    unset _fold_wanted _fold_step
fi

[ -z "$FOLD_NO_COMMIT" ] || [ -n "$FOLD_ONLY" ] ||
    refuse "--no-commit is legal only with --only." \
        "A WHOLE fold that commits nothing leaves every derived file regenerated in a" \
        "working tree nobody wrote down, and the next bank keys its verdict on that" \
        "tree. --only names the one subject a caller is tidying; --no-commit says the" \
        "rung's own commit will carry it." \
        "Nothing was regenerated and nothing was committed."

# --- THE DERIVED LIST, TYPED ---------------------------------------------------
#
# DERIVED AT RUNG TIME, THEN TYPED. Each entry below named a CONSUMER in this
# tree before it was written down, and an entry with no consumer was dropped:
#
#   frontend/openapi.json                    the committed document of record.
#                                            Read by frontend/scripts/pin_client.sh
#                                            (the byte-pin compares it against a
#                                            fresh export) and shipped by
#                                            docs/product/publication-manifest.md's
#                                            R11 row.
#   frontend/src/api/generated/schema.d.ts   the generated client. Imported by
#                                            frontend/src/api/client.ts; the
#                                            byte-pin's whole subject; named in
#                                            .gitignore as deliberately COMMITTED.
#   .secrets.baseline                        read by scripts/check.sh's full-tree
#                                            scan, by scripts/secrets_scan.sh's
#                                            per-rung walk, by scripts/publish.sh's
#                                            artifact scan, and by quality/checks.py.
#   quality/budgets.yaml                     read by quality/gate.py::check_budgets,
#                                            reached from live_scan on every
#                                            ordinary engine run, and by
#                                            quality/hotpath_probe.py.
#   scripts/gate_member_durations.ci.json    the CI walls table, written by step
#                                            (e) from a green CI run's own shard
#                                            lines. Read by scripts/check.sh's
#                                            selftest partition
#                                            (`selftest_walls_choose`) and by
#                                            `--list-legs --ci`'s shard count.
#   scripts/test_impact.json                 the acceptance map. Read by
#                                            scripts/loop_tier.sh
#                                            (LOOP_SCOPE_MAP_PATH) for the
#                                            loop's closure scope, and by
#                                            scripts/publish.sh's R12 row.
#
# THE MAP IS THE ONE ENTRY NO FOLD STEP REGENERATES, and that is not a gap —
# it is the whole reason it is here. `scripts/test_impact.py` inverts ONE
# acceptance run's coverage contexts, which is a two-pass run of the entire
# suite on a verifier box; nothing on this Mac can produce it. So the bank's
# acceptance box writes it into the working tree and LEAVES IT THERE
# (`bank_boxes_acceptance_report` in scripts/pm_push.sh: "a bank takes no
# commit"), and until this line existed the PM committed it by hand, with the
# ledger, on the docs-only road.
#
# WHY THAT WAS WORTH A LINE. `scripts/test_impact.json` IS on
# `GATE_DOCS_ONLY_PATHS`, so the road admitted it — and then derived its
# READERS from it, and `scripts/tests/test_pm_push.sh` declares it. One
# hand-committed map therefore added 116 s of drive to EVERY docs-only push
# (Row 12: 274 s, of which 244 s was readers). Committed HERE instead, the map
# rides the next bank's fold commit — a tree that is measured in full anyway —
# and a ledger push's delta never names it.
#
# IT IS THEREFORE ALSO THE ONE ENTRY CLAUSE 1 TOLERATES ALREADY DIRTY, and
# that exemption is its own typed list below rather than a widening of this
# one: the other four are regenerated by a step of this fold, so a human's
# uncommitted edit to one of them is WORK, and sweeping work into an
# unattended commit is precisely what clause 1 exists to prevent.
#
# DROPPED, with the reason, because a fold that commits a file nobody consumes
# is the failure this derivation exists to prevent:
#
#   clients/api.d.ts, clients/openapi.json   `clients/` is gitignored, and
#                                            scripts/gen_client.sh writes a
#                                            `.gitignore` holding `*` into
#                                            whatever directory it is pointed at.
#                                            Nothing commits them; nothing reads
#                                            them across commits.
#   .rung/introspect.json                    `/.rung/` is gitignored. Step (b)
#                                            regenerates it and it is invisible to
#                                            the census by construction.
#
# THESE SIX ARE A FIXED LITERAL, and the header's third blind spot is why: a
# computed list grows whenever a generator misbehaves, which is the one thing
# clause 2 exists to catch. They are the TEMPLATE's six, and a seventh one of
# the template's own is a human edit here.
#
# AND THEY STAY TYPED FOR THE SECOND REASON TOO, the map included: a
# `derived-tree-paths` declaration SUBTRACTS a path from the verdict key, and
# `scripts/loop_tier.sh` reads `scripts/test_impact.json` back on every
# `--loop` to decide the closure scope. A path a measurement reads is a path
# the key must carry.
#
# WHAT IS COMPUTED INSTEAD, so a PRODUCT never edits this file: the union
# below. A product's own generator declares beside its own write, and a
# product's own fold step declares what it regenerates, both in THE FOLD'S
# grammar — never the gate's, for the reason argued at `FOLD_WRITES_BEGIN`
# above: the gate's grammar subtracts a path from the verdict key, and every
# path in this union is read back by something that measures it.
DERIVED_PATHS='frontend/openapi.json
frontend/src/api/generated/schema.d.ts
.secrets.baseline
quality/budgets.yaml
scripts/test_impact.json
scripts/gate_member_durations.ci.json'

# --- THE ABSORBED LIST, TYPED, AND A STRICT SUBSET OF THE ONE ABOVE ----------
#
# A path this fold may find ALREADY DIRTY at clause 1 and commit anyway. The
# argument is at `scripts/test_impact.json`'s entry above and is not repeated;
# the shape is: a derived file WRITTEN FROM OUTSIDE THIS CHECKOUT, which no
# step here can regenerate and which therefore cannot arrive any other way.
#
# THE SUBSET IS CHECKED, NOT TRUSTED. An absorbed path that fell off
# `DERIVED_PATHS` would be tolerated at clause 1 and then convicted as a STRAY
# at clause 2 — a fold that refuses every bank, for a reason two lists apart.
# The self-check below is four lines and turns that into a refusal that names
# itself.
FOLD_ABSORBED_PATHS='scripts/test_impact.json'

# THE UNION: the typed list, PLUS what each local step declared about itself.
# The two halves are read separately and stay separately readable — the typed
# list is a human edit to this file and the local half is a product's
# declaration this file has never seen — but clause 2 partitions against both,
# because a path a step declared is a path somebody wrote down before it was
# written.
fold_is_derived() {
    fold_is_template_derived "$1" || fold_is_declared "$1"
}

# The two declared halves, read as one list: what the TREE declares (a product's
# own deriver, beside its own write) and what a LOCAL FOLD STEP declares. They
# are one grammar and one reader; they are two variables only because the second
# is discovered before `$FOLD_WORK` exists and the first is read after.
fold_is_declared() {
    local want="$1" p
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        [ "$p" != "$want" ] || return 0
    done <<EOF
${FOLD_TREE_PATHS}
${FOLD_LOCAL_PATHS}
EOF
    return 1
}

fold_is_template_derived() {
    local want="$1" p
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        [ "$p" != "$want" ] || return 0
    done <<EOF
$DERIVED_PATHS
EOF
    return 1
}

# fold_is_absorbed <path> — on the typed absorbed list. ONE READER, so "what
# may arrive already dirty" has one answer, exactly as `fold_is_derived` is the
# one answer to "what may this fold commit".
fold_is_absorbed() {
    local want="$1" p
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        [ "$p" != "$want" ] || return 0
    done <<EOF
$FOLD_ABSORBED_PATHS
EOF
    return 1
}


# `-uall` IS LOAD-BEARING. Without it git collapses a wholly-untracked
# directory to its name, so a generator's stray output inside one is hidden
# behind the directory — and a derived file BORN in a checkout that never had
# one is untracked too. The two must not be told apart by whether git felt like
# collapsing a directory. `${entry:3}` strips the two status characters and the
# space git prints before every path.
fold_dirty_paths() {
    git status --porcelain -uall | while IFS= read -r entry; do
        [ -n "$entry" ] || continue
        printf '%s\n' "${entry:3}"
    done
}

command -v git >/dev/null 2>&1 ||
    refuse "no git on PATH." "Nothing was regenerated and nothing was committed."
git rev-parse --show-toplevel >/dev/null 2>&1 ||
    refuse "${ROOT} is not inside a git checkout." \
        "Nothing was regenerated and nothing was committed."

# --- THE TREE'S OWN FOLD DECLARATIONS, READ ONCE ----------------------------
# Everything a generator in this checkout says THE FOLD regenerates, in the
# fold's own grammar, read out of the same source globs the gate's reader uses
# (`scripts/*.sh quality/*.py frontend/scripts/*.sh` — where a generator
# lives). This is the half that retires a product's edit to this file: their
# client generator writes `events.ts`, so their client generator declares
# `events.ts`, and `DERIVED_PATHS` below never grows a line. Zero is the
# template's own answer today and is a clean read. A refusal is this run's
# refusal too: a declaration nobody can parse is a path this fold can neither
# commit nor call a stray, and guessing between those two is exactly what
# clause 2 exists to stop.
FOLD_TREE_PATHS=""
FOLD_TREE_RC=0
FOLD_TREE_PATHS="$(fold_declared_paths 2>"$FOLD_DECL_ERR")" || FOLD_TREE_RC=$?
if [ "$FOLD_TREE_RC" != "0" ]; then
    cat "$FOLD_DECL_ERR" >&2
    refuse "this checkout's fold-writes declarations could not be read (notes above)." \
        "They are read through scripts/gate_ledger.sh's own reader, and a block it" \
        "refuses is a block whose paths this fold can neither commit nor call a stray." \
        "Exit 2 from the reader means it could not be reached at all." \
        "Nothing was regenerated and nothing was committed."
fi


# --- THE ABSORBED LIST IS A SUBSET, AND IT IS CHECKED HERE -------------------
# Before clause 1 reads it. See the list's own header for what a drift would
# cost: a path tolerated here and convicted as a stray at clause 2.
while IFS= read -r _abs; do
    [ -n "$_abs" ] || continue
    fold_is_template_derived "$_abs" ||
        refuse "the absorbed path ${_abs} is not on DERIVED_PATHS." \
            "An absorbed path is a DERIVED path this fold may find already dirty. Off the" \
            "derived list it would be tolerated by clause 1 and convicted as a stray by" \
            "clause 2, so every fold in this checkout would refuse for a reason two lists" \
            "apart. Put it on both lists or neither." \
            "Nothing was regenerated and nothing was committed."
done <<EOF
$FOLD_ABSORBED_PATHS
EOF
unset _abs

# --- CLAUSE 1: a dirty tree is refused ---------------------------------------
# Inline rather than through `refuse()`, because the refusal wants the status
# entries interleaved with its own sentences — and it PARTITIONS them first, so
# it prints what it kept rather than shelling out to `git status --short` a
# second time and printing the absorbed path as work.
#
# EXCEPT AN ABSORBED PATH, and the exception is as narrow as the list is. The
# clause's argument — "there is no way to say which of the changes the fold
# made" — is an argument about WORK, and an absorbed path is not work: nothing
# in this checkout can produce it, it is on the derived list, and the commit
# below carries it under its own subject whether it arrived before this run or
# during it. A DELETION is still work: a declared path that vanished is a human
# diff (the same sentence step (e) makes about a local step that deletes what
# it declares), so the status characters are read and only a modification or an
# addition is absorbed.
FOLD_ABSORBED_PRE=""
FOLD_UNSAVED=""
while IFS= read -r _entry; do
    [ -n "$_entry" ] || continue
    _p="${_entry:3}"
    if fold_is_absorbed "$_p"; then
        case "${_entry:0:2}" in
        *D* | *d*) ;;
        *)
            FOLD_ABSORBED_PRE="${FOLD_ABSORBED_PRE}${_p}
"
            continue
            ;;
        esac
    fi
    FOLD_UNSAVED="${FOLD_UNSAVED}${_entry}
"
done <<EOF
$(git status --porcelain -uall)
EOF
unset _entry _p

if [ -n "$FOLD_UNSAVED" ]; then
    FOLD_REFUSED=1
    echo "!! pm_fold: ${ROOT} has uncommitted changes." >&2
    printf '%s' "$FOLD_UNSAVED" >&2
    echo "   A fold folds a COMMITTED tree. With work already in the checkout there is" >&2
    echo "   no way to say which of the changes below the fold made, and the commit this" >&2
    echo "   script would write would carry whatever it swept up. Commit or stash first;" >&2
    echo "   this script will not decide that for you." >&2
    echo "   Nothing was regenerated and nothing was committed." >&2
    exit 2
fi

PRE_HEAD="$(git rev-parse --verify HEAD)" ||
    refuse "this checkout has no HEAD to fold." "Nothing was committed."
PRE_TREE="$(git rev-parse --verify "HEAD^{tree}")" ||
    refuse "could not read HEAD's tree." "Nothing was committed."

echo "pm_fold: folding ${ROOT}"
echo "  Pre-fold HEAD  $(git rev-parse --short "$PRE_HEAD")  $(git log -1 --format=%s "$PRE_HEAD")"
echo "  Pre-fold tree  ${PRE_TREE}"
if [ -n "$FOLD_ABSORBED_PRE" ]; then
    # SAID OUT LOUD, because it is the one thing in this run that was already
    # in the tree when the run started. A reader of the fold commit should not
    # have to infer which of its paths a generator here wrote.
    printf '%s' "$FOLD_ABSORBED_PRE" | while IFS= read -r _p; do
        [ -n "$_p" ] || continue
        echo "  absorbed       ${_p} — already in the working tree; written from outside this checkout"
    done
fi
echo ""

FOLD_WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-pm-fold.XXXXXX")" ||
    refuse "could not make a scratch directory." "Nothing was committed."

# Every step is one of three states, and the difference matters:
#   ARTIFACT ABSENT   -> skipped, printed, and it does NOT count as a step run.
#                        A product with no frontend/ has no client to fold.
#   ARTIFACT PRESENT,
#   TOOL ABSENT       -> REFUSED at exit 2. The file is committed and this run
#                        cannot say whether it is current: could-not-look.
#   BOTH PRESENT      -> run.
STEPS_RUN=0

step_skipped() {
    echo "  skipped — $1"
}

# The generators are overridable so a drive never has to be the real checkout —
# the same reason `scripts/fe_gate.sh` makes `FE_FRONTEND_DIR` and `FE_PNPM`
# overridable, and the same reason its tri-state is fixture-proven rather than
# tree-observed. A fold whose every live run takes one branch is a fold nothing
# has proven can take the others.
FOLD_PIN_CLIENT="${DJB_FOLD_PIN_CLIENT:-$ROOT/frontend/scripts/pin_client.sh}"
FOLD_UV="${DJB_FOLD_UV:-uv}"

# --- (a) the contract: the committed document and the generated client -------
echo "== (a) contract · ${FOLD_PIN_CLIENT} --write"
if ! fold_step_selected contract; then
    step_skipped "--only ${FOLD_ONLY} does not name this step"
elif [ ! -f "$ROOT/frontend/openapi.json" ] && [ ! -f "$ROOT/frontend/src/api/generated/schema.d.ts" ]; then
    step_skipped "neither frontend/openapi.json nor the generated client is in this checkout"
elif [ ! -x "$FOLD_PIN_CLIENT" ]; then
    refuse "the committed contract is here but ${FOLD_PIN_CLIENT} is not executable." \
        "A committed client this run cannot regenerate is a client nobody can say is" \
        "current — could-not-look, never a clean fold." \
        "Nothing was committed."
else
    STEPS_RUN=$((STEPS_RUN + 1))
    PIN_RC=0
    "$FOLD_PIN_CLIENT" --write || PIN_RC=$?
    [ "$PIN_RC" = "0" ] ||
        refuse "the client generator exited ${PIN_RC} (its output is above)." \
            "2 is its own could-not-look (no npx, no Node); 1 is a checkout that cannot" \
            "export a schema. Either way the contract was not regenerated and may now be" \
            "half-written." \
            "Nothing was committed."
fi
echo ""

# --- (b) the schema dump: regenerated, NEVER committed -----------------------
# `/.rung/` is in this repository's `.gitignore`, so this file cannot reach the
# census below and cannot reach a commit. It is folded anyway because a builder
# picking up this tree reads it instead of guessing the schema
# (`.claude/skills/rung-execution/SKILL.md` §0), and a stale one is a schema
# read rather than guessed and wrong all the same.
#
# THE IGNORE IS CHECKED, NOT ASSUMED, and this is a defect the step's own
# drive found rather than a precaution. Written into a checkout whose
# `.gitignore` does NOT cover `/.rung/`, this step MANUFACTURES ITS OWN STRAY:
# the census below then names `.rung/introspect.json`, refuses at exit 2, and
# the fold is stopped by the one file it wrote on purpose. Tooth 1 working
# correctly on a victim the fold created for itself is not tooth 1 working. So
# the step asks git whether the path is ignored and declines to write it when
# it is not — which is what makes the header's "invisible to clause 2 BY
# CONSTRUCTION" true by construction rather than by whatever the ambient
# `.gitignore` happens to say.
echo "== (b) schema · manage.py introspect -> .rung/introspect.json (git-ignored, never committed)"
FOLD_RUNG_IGNORED=0
git check-ignore -q .rung/introspect.json 2>/dev/null && FOLD_RUNG_IGNORED=1
if ! fold_step_selected schema; then
    step_skipped "--only ${FOLD_ONLY} does not name this step"
elif [ ! -f "$ROOT/manage.py" ]; then
    step_skipped "no manage.py in this checkout — there is no schema to dump"
elif [ "$FOLD_RUNG_IGNORED" != "1" ]; then
    step_skipped ".rung/introspect.json is NOT git-ignored in this checkout, so writing it
            would manufacture a stray for the footprint census to refuse on. The dump is
            a builder's convenience, never something a fold commits; add \`/.rung/\` to
            .gitignore and it comes back."
elif ! command -v "$FOLD_UV" >/dev/null 2>&1; then
    refuse "manage.py is here but there is no ${FOLD_UV} on PATH." \
        "Nothing was committed."
else
    STEPS_RUN=$((STEPS_RUN + 1))
    mkdir -p "$ROOT/.rung"
    INTROSPECT_RC=0
    "$FOLD_UV" run python manage.py introspect >"$FOLD_WORK/introspect.json" 2>"$FOLD_WORK/introspect.err" ||
        INTROSPECT_RC=$?
    if [ "$INTROSPECT_RC" != "0" ]; then
        cat "$FOLD_WORK/introspect.err" >&2
        refuse "introspect exited ${INTROSPECT_RC} (output above)." \
            "A fold that cannot read this checkout's schema cannot say the derived files" \
            "it is about to commit came from it." \
            "Nothing was committed."
    fi
    cp "$FOLD_WORK/introspect.json" "$ROOT/.rung/introspect.json"
    echo "  -> .rung/introspect.json ($(wc -c <"$ROOT/.rung/introspect.json" | tr -d ' ') bytes)"
fi
echo ""

# --- (c) the secret baseline, and THE generated_at STRIP ---------------------
#
# THE STAMP NEVER REACHES A COMMIT. `detect-secrets scan` rewrites
# `"generated_at"` on every run, unconditionally, whether or not anything about
# the tree moved — so a committed baseline carrying one is a file whose LAST
# LINE differs on every branch that ever re-scanned it. Two lanes both folding
# then conflict on that line and on nothing else: measured here (`ea56096 fold:
# baseline shifted`) and on the sibling product, where three merges were
# hand-resolved in one night and a clone was refused.
#
# So the stamp is STRIPPED, and the stripped file is what both the comparison
# and the commit see. Nothing reads the field — detect-secrets writes it at
# `core/baseline.py:78` and reads it nowhere, and `detect-secrets-hook
# --baseline` over a stampless file exits 0 on a clean set and 1 on a key-shaped
# one (measured on 1.5.0; `scripts/tests/test_secrets_baseline_guard.sh` prints
# the version each verdict belongs to).
#
# THREE OUTCOMES, each with its own sentence, because a message that cannot tell
# them apart is how churn gets committed as a finding:
#   * the results did not move and the committed file was already stampless
#     -> the PRE-SCAN FILE IS PUT BACK, byte for byte, and the census below sees
#        a clean path.
#   * the results did not move but the committed file carried a stamp (a revert,
#     a hand-resolved merge, a clone from before this) -> the stripped file is
#     written, so the fold heals it rather than restoring the stamp forever.
#   * the results moved -> the stripped file is written and the census commits
#     it.
#
# A STRIP THAT COULD NOT RUN IS A REFUSAL, never a "shift", and never a file
# written half-stripped.
echo "== (c) secrets · ${FOLD_UV} run detect-secrets scan --baseline .secrets.baseline"
if ! fold_step_selected secrets; then
    step_skipped "--only ${FOLD_ONLY} does not name this step"
elif [ ! -f "$ROOT/.secrets.baseline" ]; then
    step_skipped "no .secrets.baseline in this checkout — there is no baseline to shift"
elif ! command -v "$FOLD_UV" >/dev/null 2>&1; then
    refuse ".secrets.baseline is here but there is no ${FOLD_UV} on PATH." \
        "Nothing was committed."
elif ! command -v python3 >/dev/null 2>&1; then
    refuse ".secrets.baseline is here but there is no python3 on PATH." \
        "The stamp strip below is a JSON rewrite, not a line filter: deleting the" \
        "\"generated_at\" line textually leaves the trailing comma of the line above" \
        "it and the result is not JSON. Without python3 this step cannot produce a" \
        "committable file." \
        "Nothing was committed."
else
    STEPS_RUN=$((STEPS_RUN + 1))
    cp "$ROOT/.secrets.baseline" "$FOLD_WORK/baseline.before"
    SECRETS_RC=0
    "$FOLD_UV" run detect-secrets scan --baseline .secrets.baseline || SECRETS_RC=$?
    [ "$SECRETS_RC" = "0" ] ||
        refuse "detect-secrets exited ${SECRETS_RC}." \
            "The baseline was not re-scanned and may now be half-written." \
            "Nothing was committed."

    # THE FILTER'S OWN SHAPE IS CHECKED, not assumed. The scan writes EXACTLY
    # ONE `"generated_at"` line; zero (the format moved) or two (a second
    # always-moving field arrived) is a could-not-look, not a silent pass — the
    # header's second declared blind spot with a tooth on it. The BEFORE count
    # is not constrained: a stampless committed file is the point, and a stamped
    # one is the migration path above.
    STAMPS_BEFORE="$(grep -c '"generated_at"' "$FOLD_WORK/baseline.before" || true)"
    STAMPS_AFTER="$(grep -c '"generated_at"' "$ROOT/.secrets.baseline" || true)"
    if [ "$STAMPS_AFTER" != "1" ]; then
        refuse "the scan wrote ${STAMPS_AFTER} generated_at line(s); this strip is built on exactly one." \
            "detect-secrets' format has moved under this strip. Stripping on a shape this" \
            "script no longer recognises would either commit churn on every fold, hide a" \
            "real shift, or write a file that is no longer JSON." \
            "Nothing was committed."
    fi

    # THE STRIP, and it is a JSON rewrite rather than a line filter for one
    # measured reason: `"generated_at"` is the LAST key detect-secrets writes
    # (`core/baseline.py`, `format_for_output`), so the line above it ends in a
    # comma — delete the stamp line textually and what is left is
    # `"Illegal trailing comma before end of object"`. The rewrite is
    # `json.dumps(..., indent=2) + "\n"`, which is byte for byte what
    # detect-secrets' own `save_to_file` writes, so the stripped file is exactly
    # the file the scanner would have produced had it not stamped it.
    #
    # AND THE SECOND NORMALISATION: `line_number`, REMOVED FROM EVERY RESULT.
    # It is the same class as the stamp, one field over, and it is the half the
    # consumer pays: a secret's RECORDED LINE moves whenever anything is
    # inserted above it, so two lanes that each touch a file with a recorded
    # result rewrite the same `"line_number": N` lines to two different numbers
    # and conflict on them — measured on this fixture shape, two conflicted
    # regions in `.secrets.baseline` and no other file.
    #
    # NOTHING READS IT. detect-secrets 1.5.0 compares a result on
    # `['filename', 'secret_hash', 'type']` (`potential_secret.py`,
    # `fields_to_compare`) and says so in that file's own words — "line numbers
    # aren't included because they are subject to change" — and
    # `load_secret_from_dict` treats the key as OPTIONAL. So the key the tools
    # use is already content; only the writer was re-stamping lines.
    # `scripts/tests/test_secrets_baseline_guard.sh` drives the installed
    # scanner against a numberless baseline in both directions and prints the
    # version each verdict belongs to.
    #
    # ONE REWRITE, NOT TWO PASSES. Stripping in a second walk would mean a
    # second place for the JSON shape to be wrong; `data.pop` for the stamp and
    # `entry.pop` for the number are the same function's two lines.
    fold_strip_stamp() { # <src> <dst>
        python3 - "$1" "$2" <<'STRIP'
import json
import sys

with open(sys.argv[1]) as fh:
    data = json.load(fh)
data.pop("generated_at", None)
for entries in (data.get("results") or {}).values():
    for entry in entries:
        entry.pop("line_number", None)
with open(sys.argv[2], "w") as fh:
    fh.write(json.dumps(data, indent=2) + "\n")
STRIP
    }

    fold_strip_stamp "$ROOT/.secrets.baseline" "$FOLD_WORK/after.stripped" 2>"$FOLD_WORK/strip.err" ||
        refuse "could not strip the generated_at stamp from the re-scanned baseline." \
            "$(sed -n '$p' "$FOLD_WORK/strip.err" 2>/dev/null || echo 'python3 said nothing readable.')" \
            "Without the strip every fold would commit a line that differs on every branch." \
            "Nothing was committed."
    fold_strip_stamp "$FOLD_WORK/baseline.before" "$FOLD_WORK/before.stripped" 2>"$FOLD_WORK/strip.err" ||
        refuse "could not strip the committed baseline for comparison." \
            "$(sed -n '$p' "$FOLD_WORK/strip.err" 2>/dev/null || echo 'python3 said nothing readable.')" \
            "The committed .secrets.baseline is not readable as JSON — a half-resolved" \
            "merge is the usual cause, and it is a human's to fix." \
            "Nothing was committed."

    STAMPS_STRIPPED="$(grep -c '"generated_at"' "$FOLD_WORK/after.stripped" || true)"
    if [ "$STAMPS_STRIPPED" != "0" ]; then
        refuse "the strip left ${STAMPS_STRIPPED} generated_at line(s) behind." \
            "A strip that does not strip would commit the stamp and bring the merge" \
            "conflict class straight back." \
            "Nothing was committed."
    fi
    NUMBERS_STRIPPED="$(grep -c '"line_number"' "$FOLD_WORK/after.stripped" || true)"
    if [ "$NUMBERS_STRIPPED" != "0" ]; then
        refuse "the strip left ${NUMBERS_STRIPPED} line_number key(s) behind." \
            "The same sentence as the stamp one field over: a strip that does not strip" \
            "commits a number that moves whenever anything is inserted above a recorded" \
            "secret, and two lanes then conflict on it." \
            "Nothing was committed."
    fi

    # THE RESTORE BRANCH ASKS ABOUT BOTH FIELDS, and the second half is not
    # decoration: a committed baseline carrying line numbers strips to the same
    # bytes the fresh scan strips to, so a restore keyed on the stamp alone
    # would put the NUMBERED file back on every fold and the migration would
    # never happen. The condition is "the committed file is already in the
    # normal form", not "the committed file has no stamp".
    NUMBERS_BEFORE="$(grep -c '"line_number"' "$FOLD_WORK/baseline.before" || true)"
    if cmp -s "$FOLD_WORK/before.stripped" "$FOLD_WORK/after.stripped"; then
        if [ "$STAMPS_BEFORE" = "0" ] && [ "$NUMBERS_BEFORE" = "0" ]; then
            cp "$FOLD_WORK/baseline.before" "$ROOT/.secrets.baseline"
            echo "  no shift — only the generated_at stamp the scan writes on every run differed, so the baseline was restored"
        else
            cp "$FOLD_WORK/after.stripped" "$ROOT/.secrets.baseline"
            echo "  the always-moving fields were removed (${STAMPS_BEFORE} generated_at, ${NUMBERS_BEFORE} line_number) — the results did not shift, but the committed baseline carried fields that conflict between lanes"
        fi
    else
        cp "$FOLD_WORK/after.stripped" "$ROOT/.secrets.baseline"
        echo "  BASELINE SHIFTED — the scan found a different tree than the baseline recorded"
        # THE NEXT RUNG'S COMMAND, NAMED AT THE SITE OF THE SHIFT. A builder who
        # reads this line in a bank log is a builder whose own checkout's
        # baseline is now behind main's, and the answer used to be something to
        # go and look up. It is one command and it runs the line above rather
        # than a second copy of it.
        echo "  the next rung brings its own checkout level with: ./scripts/rung_tidy.sh --secrets"
    fi
fi
echo ""

# --- (d) the budgets: CLAUSE 3, and it never raises a ceiling ----------------
#
# WHAT IT READS. The house-rules engine's OWN budget check, called directly, so
# the sentences this parses are the sentences the gate prints — not a
# reimplementation that can drift from them. `quality/gate.py::check_budgets`
# returns the PROBLEMS (a ceiling passed, a subject with no ceiling) and appends
# the NOTES (a measured value below its ceiling) to the module-level `notes`
# list the engine prints at the end of every live scan.
#
# WHAT IT APPLIES. Only a note, and only the number the note itself printed.
# The two non-lowering shapes both end with a pasteable line and NEITHER carries
# the lowering sentence — the raise ends "The line to paste, verbatim:" and the
# new subject ends "in quality/budgets.yaml:". So a raise-shaped line is
# UNRECOGNISED by the parser below rather than merely unapplied, which is a
# stronger property: there is no branch in which a raise is read and then
# declined.
#
# WHY THE WHOLE OUTPUT IS SCANNED and never a region: a region would make
# clause 3 true by WHERE a line sits instead of by WHAT it says, and where a
# line sits is the engine's business and changes without this file changing.
#
# THE NOTE-COUNT CROSS-CHECK is the only thing that tells "there was nothing to
# lower" apart from "the engine's sentence moved and this parser reads a
# sentence nobody prints any more". Without it a reworded engine message
# degrades silently to a green no-op fold — which looks exactly like a clean
# tree. The worst reachable outcome here is could-not-look; it is never a
# silently raised ceiling.
echo "== (d) budgets · quality.gate.check_budgets(), lowerings only"
BUDGETS_LOWERED=0
if ! fold_step_selected budgets; then
    step_skipped "--only ${FOLD_ONLY} does not name this step"
elif [ ! -f "$ROOT/quality/budgets.yaml" ]; then
    step_skipped "no quality/budgets.yaml in this checkout — there are no floors to lower"
elif ! command -v "$FOLD_UV" >/dev/null 2>&1; then
    refuse "quality/budgets.yaml is here but there is no ${FOLD_UV} on PATH." \
        "Nothing was committed."
else
    STEPS_RUN=$((STEPS_RUN + 1))

    BUDGET_RC=0
    budget_notes_collect "$FOLD_UV" "$FOLD_WORK" || BUDGET_RC=$?
    if [ "$BUDGET_RC" != "0" ]; then
        cat "$FOLD_WORK/budget.out" >&2
        refuse "the budgets check exited ${BUDGET_RC} (output above)." \
            "A fold cannot lower a floor it could not measure." \
            "Nothing was committed."
    fi
    # >>> budgets: the engine's whole output >>>
    # Printed BEFORE anything is parsed, and unfiltered: a human reading a
    # refusal below needs the sentences this parser read, not this parser's
    # summary of them. Cited by this sentinel rather than by line number —
    # `docs/product/instruments.md`'s own citation of this print went stale by
    # 39 lines within days of being written, which is the same lesson the
    # registration sentinel in `scripts/check.sh` was already carrying.
    cat "$FOLD_WORK/budget.out"
    # <<< budgets: the engine's whole output <<<

    # THE SHAPE GUARD: exactly one summary line, and it must name a note count.
    SUMMARY="$(budget_notes_summary_lines "$FOLD_WORK/budget.out")"
    [ "$SUMMARY" = "1" ] ||
        refuse "the budgets check printed ${SUMMARY} summary line(s), not exactly one." \
            "This parser reads the engine's own sentences; a run whose shape it does not" \
            "recognise is a could-not-look, never an empty set of lowerings." \
            "Nothing was committed."
    NOTES_CLAIMED="$(budget_notes_claimed "$FOLD_WORK/budget.out" notes)"
    [ -n "$NOTES_CLAIMED" ] ||
        refuse "the budgets check's summary line did not name a note count." \
            "Nothing was committed."

    # THE PARSER LIVES IN `scripts/budget_notes.sh`, sourced above, because
    # `scripts/rung_tidy.sh` reads the SAME output for the two shapes this step
    # deliberately does not apply. Two copies of a parser over one interface is
    # a parser that drifts in one of them silently, which is the exact failure
    # the note-count cross-check below exists to make loud — and a cross-check
    # in one copy protects one copy.
    budget_notes_lowerings "$FOLD_WORK/budget.out" "$FOLD_WORK/lowerings.tsv"
    BUDGETS_LOWERED="$(budget_notes_count "$FOLD_WORK/lowerings.tsv")"

    [ "$BUDGETS_LOWERED" = "$NOTES_CLAIMED" ] ||
        refuse "the budgets check wrote ${NOTES_CLAIMED} note(s) and this parser recognised ${BUDGETS_LOWERED}." \
            "The engine's sentence has moved and this file has not. A parser that reads a" \
            "sentence that is no longer printed reports 'nothing to lower', which looks" \
            "exactly like a clean tree." \
            "Nothing was committed."

    if [ "$BUDGETS_LOWERED" = "0" ]; then
        if grep -q '^budget: ' "$FOLD_WORK/budget.out"; then
            echo "  nothing to lower — the check reported only RAISES or new subjects, and a"
            echo "  raise is a decision that stays a human diff. The fold changes nothing here."
        else
            echo "  nothing to lower — every recorded ceiling already equals what was measured"
        fi
    else
        # THE APPLY. Section-tracked, line-anchored, comment-preserving — a YAML
        # round-trip would throw away every provenance comment in that file, and
        # those comments are the whole reason a ceiling is readable. It writes a
        # SCRATCH file and only copies it over the real one after the miss check,
        # so a partial rewrite is never left behind. A key the file does not
        # contain is exit 3 out of awk and a refusal here: applying the rest and
        # staying quiet about one is how a floor stops being a floor.
        #
        # IT ALSO OWNS CLAUSE 3, HERE, rather than inheriting it. This is the one
        # place in the run that has BOTH numbers in its hands — the note's, and
        # the ceiling standing in the file it is rewriting — so this is where
        # "never raises a ceiling" is decided. `quality/gate.py` does compare
        # before it prints the lowering sentence, but a note is an INPUT and
        # inputs are not trusted: a crafted note carrying the sentence verbatim
        # and a HIGHER number was applied and committed as "1 budgets lowered",
        # exit 0 (the FOLD-1 verifier's plant B3). Not strictly lower is exit 4
        # out of awk and a refusal here, with all four values printed.
        #
        # AND IT REWRITES A NUMBER, NOT A LINE. The gap between the value and an
        # inline `#` is carried across byte for byte; re-spacing it would put
        # churn a reviewer must read past into the one diff whose whole purpose
        # is to be read.
        BUDGET_APPLY_RC=0
        awk -v REC="$FOLD_WORK/lowerings.tsv" '
            BEGIN {
                n = 0
                while ((getline rec < REC) > 0) {
                    if (rec == "") continue
                    split(rec, a, "\t")
                    n++; S[n] = a[1]; K[n] = a[2]; V[n] = a[3]; HIT[n] = 0
                }
            }
            /^[A-Za-z_][A-Za-z0-9_]*:[ \t]*$/ {
                sect = $0; sub(/:[ \t]*$/, "", sect); print; next
            }
            {
                for (i = 1; i <= n; i++) {
                    if (sect != S[i]) continue
                    pfx = "  " K[i] ": "
                    if (substr($0, 1, length(pfx)) != pfx) continue
                    tail = substr($0, length(pfx) + 1)
                    cm = ""
                    p = index(tail, "#")
                    if (p > 0) {
                        old = substr(tail, 1, p - 1)
                        # The gap is whatever sits between the value and the
                        # `#`, kept verbatim: drop the value off the front of
                        # that span and what is left IS the spacing.
                        gap = old
                        sub(/^[^ \t]*/, "", gap)
                        cm = gap substr(tail, p)
                    } else {
                        old = tail
                    }
                    sub(/[ \t]+$/, "", old)
                    if (old !~ /^[0-9]+$/) {
                        # `-> %s` IS THE NUMBER THE NOTE CARRIED. Without it
                        # this line names the subject and the text found and
                        # stops, so the one figure a reader needs to judge the
                        # note — what it wanted to write — is missing from the
                        # only line that names the subject. The RAISE line
                        # opposite has carried `old -> new` all along.
                        printf "UNREADABLE %s %s: the ceiling standing in the file is \"%s\", which is not a number -> %s\n", \
                            S[i], K[i], old, V[i] > "/dev/stderr"
                        bad = 1
                    } else if ((V[i] + 0) >= (old + 0)) {
                        printf "RAISE %s %s: %s -> %s\n", S[i], K[i], old, V[i] > "/dev/stderr"
                        bad = 1
                    }
                    print pfx V[i] cm
                    HIT[i] = 1
                    next
                }
                print
            }
            END {
                miss = 0
                for (i = 1; i <= n; i++) {
                    if (HIT[i]) continue
                    printf "MISS %s %s\n", S[i], K[i] > "/dev/stderr"
                    miss = 1
                }
                if (bad) exit 4
                if (miss) exit 3
            }
        ' "$ROOT/quality/budgets.yaml" >"$FOLD_WORK/budgets.new" 2>"$FOLD_WORK/budgets.miss" ||
            BUDGET_APPLY_RC=$?
        if [ "$BUDGET_APPLY_RC" = "4" ]; then
            cat "$FOLD_WORK/budgets.miss" >&2
            # EXIT 4 HAS TWO REASONS AND THEY ARE NOT THE SAME CLAIM. The awk
            # above emits `RAISE` when it READ the ceiling and the note's number
            # was not below it, and `UNREADABLE` when it could not read the
            # ceiling at all. One sentence covered both, so an unreadable
            # ceiling was reported as "a lowering note carried a number that is
            # not BELOW the ceiling" — a message naming a cause it had not
            # proven, and the one claim the fold is in no position to make about
            # a ceiling it never parsed. The status (2) and the byte-identity of
            # quality/budgets.yaml were right for both members throughout; only
            # the sentence was wrong, for one of them.
            #
            # Branched on the FIRST TOKEN of the first reason line. The awk
            # prints RAISE/UNREADABLE lines during its scan and any MISS lines
            # from END, so line 1 is always one of the two — read with `sed`
            # against the file rather than through a pipeline, because a quiet
            # reader at a pipeline tail under pipefail is the class
            # scripts/tests/test_sweep.sh's own sweep exists to refuse.
            BUDGET_APPLY_REASON="$(sed -n '1{s/ .*//;p;}' "$FOLD_WORK/budgets.miss")"
            if [ "$BUDGET_APPLY_REASON" = "UNREADABLE" ]; then
                refuse "a ceiling standing in quality/budgets.yaml is not a number (above: section, key, the text found, and the number the note carried), so the fold cannot tell lowering from raising and refuses to guess." \
                    "Clause 3 says the fold never raises a ceiling, and it owns that property HERE," \
                    "against the file it is rewriting. Owning it means READING the current ceiling;" \
                    "a line it cannot read is a line it cannot say is being lowered, and cannot-say" \
                    "is exit 2 here as everywhere. Fix the ceiling by hand, then fold." \
                    "quality/budgets.yaml was not modified and nothing was committed."
            fi
            refuse "a lowering note carried a number that is not BELOW the ceiling quality/budgets.yaml already records (above: section, key, old, new)." \
                "The fold never raises a ceiling — clause 3 — and it owns that property HERE," \
                "against the file it is rewriting, rather than inheriting it from whichever" \
                "engine printed the note. A note is an input, and inputs are not trusted." \
                "quality/budgets.yaml was not modified and nothing was committed."
        elif [ "$BUDGET_APPLY_RC" != "0" ]; then
            cat "$FOLD_WORK/budgets.miss" >&2
            refuse "the budgets check named a line quality/budgets.yaml does not contain (above)." \
                "The two files disagree about what a subject is called. Applying the rest and" \
                "staying quiet about this one is how a floor stops being a floor." \
                "quality/budgets.yaml was not modified and nothing was committed."
        fi
        cp "$FOLD_WORK/budgets.new" "$ROOT/quality/budgets.yaml"
        echo "  ${BUDGETS_LOWERED} ceiling(s) lowered to the number the gate printed:"
        while IFS="$(printf '\t')" read -r sect key val; do
            [ -n "$sect" ] || continue
            echo "    ${sect}  ${key}: ${val}"
        done <"$FOLD_WORK/lowerings.tsv"
    fi
fi
echo ""

# --- (e) walls: the CI walls table the selftest partition balances over ------
#
# WHAT IT HARVESTS. Every selftest shard of a CI run prints one line per member
# it drove — `drive <member>: exit <rc> (<s>s)` — and, when CI hands it
# `DJB_MEMBER_WALLS_OUT`, writes the same fact as a `member-walls/1` row. This
# step takes the LATEST GREEN, COMPLETE CI run on main, reads those rows (the
# run's `member-walls*` artifacts when it uploaded any, its log otherwise), and
# writes `scripts/gate_member_durations.ci.json`: one wall per member, the
# runner label as `machine`, the run id and the tree as `measured_at`. The
# selftest partition prefers that table to the Mac's (`selftest_walls_choose`
# in scripts/check.sh), and `--list-legs --ci` derives the shard count from it.
#
# A HINT, NEVER A PARTIAL TABLE, AND NEVER A REFUSAL. The table is a
# measurement of somebody else's run, so this step's worst outcome is "the
# committed table stands": every reason not to write it prints ONE line and
# leaves the fold's exit exactly as the other steps left it.
#
#   walls: NOT harvested — <why>          the run was read and is not a table:
#                                         a member in two shards, a member of
#                                         the population with no row, a row for
#                                         a member the population does not have,
#                                         any rc other than 0, a REUSED row (its
#                                         wall was never this run's), or a run
#                                         that does not say whose walls they are.
#   walls: could not look (<why>) — the committed table stands
#                                         no gh, gh failing, no green run.
#
# THE POPULATION IS THE GATE'S OWN: `./scripts/check.sh --list-legs`'s
# `selftest` row, whose composed-of is the leg and then every drive it walks —
# the leg's own self-test member is `house-rules-engine` wherever a member is
# named, so that is what the leg name maps to here. A closed population, never
# the harvest's own say-so: a run that lost a member is incomplete, not smaller.
#
# SEAMS, for the drive and for the one-time production of the table:
#   DJB_FOLD_WALLS_DIR         a directory already holding the harvest (`*.walls`
#                              files of `member-walls/1` rows, one per shard, and
#                              a `run.meta` of `run=` `machine=` `tree=` lines) —
#                              gh is not asked.
#   DJB_FOLD_WALLS_POPULATION  a file of member names, one per line, in place of
#                              the listing (a fixture repository has no gate).
#   DJB_FOLD_WALLS_RUN         the run id to read, in place of "the latest green".
#   DJB_FOLD_GH                the gh to run (a stub, or a path that is absent).
#
# WHAT IT DOES NOT COVER: whether the walls are representative (one run, one
# runner, whatever else that runner was doing); a run whose log lines were
# reworded (it reads nothing, and says NOT harvested — the population is
# missing); churn — a harvest writes only when bytes move, and if every train
# moves it the remedy is rounding, not skipping.
FOLD_GH="${DJB_FOLD_GH:-gh}"
FOLD_WALLS_PATH='scripts/gate_member_durations.ci.json'

# fold_walls_population — the member names, one per line; 1 when they cannot
# be had.
fold_walls_population() {
    if [ -n "${DJB_FOLD_WALLS_POPULATION:-}" ]; then
        [ -r "$DJB_FOLD_WALLS_POPULATION" ] || return 1
        grep -v '^$' "$DJB_FOLD_WALLS_POPULATION"
        return 0
    fi
    # TO A FILE, NEVER A `$( )`: the gate refuses a piped stdout (exit 2), and a
    # command substitution IS a pipe — the listing's own reader in
    # `scripts/pm_push.sh` redirects for the same reason.
    "$ROOT/scripts/check.sh" --list-legs >"$FOLD_WORK/walls-listing.tsv" 2>/dev/null || return 1
    awk -F'\t' '
        $1 == "selftest" {
            n = split($4, m, ",")
            for (i = 1; i <= n; i++) {
                if (m[i] == "selftest") { print "house-rules-engine" } else { print m[i] }
            }
            found = 1
        }
        END { exit(found ? 0 : 1) }
    ' "$FOLD_WORK/walls-listing.tsv"
}

# fold_walls_fetch <dir> — fill <dir> with the harvest from gh. On failure it
# prints the reason on stdout and returns 1 (could not look) or 3 (read, and not
# harvestable).
fold_walls_fetch() {
    local dir=$1 run="" view="" status="" conclusion="" sha="" tree="" labels=""
    if ! command -v "$FOLD_GH" >/dev/null 2>&1; then
        echo "no ${FOLD_GH} on PATH"
        return 1
    fi
    run=${DJB_FOLD_WALLS_RUN:-}
    if [ -z "$run" ]; then
        # `--branch=main` NAMES GITHUB'S BRANCH, NOT A LOCAL REF: the run list
        # is the remote's record, and this step reads nothing from this
        # checkout's refs but the commit the run names (and asks gh for its
        # tree when that commit is not here).
        run=$("$FOLD_GH" run list --workflow ci.yml --branch=main --event push --status success \
            --limit 1 --json databaseId --jq '.[0].databaseId // empty' 2>"$dir/gh.err") || {
            echo "gh run list failed: $(head -n 1 "$dir/gh.err")"
            return 1
        }
        if [ -z "$run" ]; then
            echo "no green CI run on main"
            return 1
        fi
    fi
    case "$run" in
    *[!0-9]*)
        echo "the run id '${run}' is not a number"
        return 1
        ;;
    esac
    view=$("$FOLD_GH" run view "$run" --json status,conclusion,headSha \
        --jq '"\(.status) \(.conclusion) \(.headSha)"' 2>"$dir/gh.err") || {
        echo "gh run view ${run} failed: $(head -n 1 "$dir/gh.err")"
        return 1
    }
    status=$(printf '%s\n' "$view" | awk '{print $1}')
    conclusion=$(printf '%s\n' "$view" | awk '{print $2}')
    sha=$(printf '%s\n' "$view" | awk '{print $3}')
    if [ "$status" != "completed" ] || [ "$conclusion" != "success" ]; then
        echo "run ${run} is ${status}/${conclusion}, not a green completed run"
        return 3
    fi
    tree=$(git rev-parse --verify --quiet "${sha}^{tree}" 2>/dev/null) ||
        tree=$("$FOLD_GH" api "repos/{owner}/{repo}/git/commits/${sha}" --jq '.tree.sha' 2>"$dir/gh.err") || {
        echo "the tree of ${sha} could not be read: $(head -n 1 "$dir/gh.err")"
        return 1
    }
    labels=$("$FOLD_GH" api "repos/{owner}/{repo}/actions/runs/${run}/jobs?per_page=100" \
        --jq '.jobs[] | select(.name | startswith("legs (selftest")) | .labels | join(",")' 2>"$dir/gh.err") || {
        echo "gh api could not list run ${run}'s jobs: $(head -n 1 "$dir/gh.err")"
        return 1
    }
    labels=$(printf '%s\n' "$labels" | grep -v '^$' | LC_ALL=C sort -u | tr '\n' '+' | sed 's/+$//')
    {
        echo "run=${run}"
        echo "machine=${labels}"
        echo "tree=${tree}"
    } >"$dir/run.meta"
    # THE ARTIFACTS FIRST — the rows the shards wrote themselves — and the log
    # when there are none (every run before CI uploaded them, the baseline
    # included). Both land as the same `member-walls/1` rows.
    mkdir -p "$dir/artifacts"
    if "$FOLD_GH" run download "$run" --pattern 'member-walls*' --dir "$dir/artifacts" >/dev/null 2>&1 &&
        [ -n "$(find "$dir/artifacts" -type f 2>/dev/null)" ]; then
        find "$dir/artifacts" -type f | LC_ALL=C sort | while IFS= read -r _wf; do cat "$_wf"; done |
            grep '^member-walls/1	' >"$dir/artifacts.walls" || true
        return 0
    fi
    "$FOLD_GH" run view "$run" --log >"$dir/run.log" 2>"$dir/gh.err" || {
        echo "gh run view ${run} --log failed: $(head -n 1 "$dir/gh.err")"
        return 1
    }
    # `<job>\t<step>\t<timestamp> <content>`, the job named by ci.yml's matrix
    # (`legs (selftest, k/N)`, or `legs (selftest)` unsharded). Only a line whose
    # CONTENT is exactly the leg's own member line counts: a drive's nested
    # output is indented further and is not a member of this run.
    awk -F'\t' '
        $1 ~ /^legs \(selftest(, [0-9]+\/[0-9]+)?\)$/ {
            part = "1/1"
            if (match($1, /[0-9]+\/[0-9]+/)) { part = substr($1, RSTART, RLENGTH) }
            c = $3
            sub(/^[0-9][0-9TZ:.+-]* /, "", c)
            if (c ~ /^  drive [A-Za-z0-9_:-]+: exit [0-9]+ \([0-9]+s\)$/) {
                split(c, w, " ")
                name = w[2]; sub(/:$/, "", name)
                secs = w[5]; gsub(/[()s]/, "", secs)
                printf "member-walls/1\t%s\t%s\t%s\t%s\n", name, w[4], secs, part
            } else if (c ~ /^  drive [A-Za-z0-9_:-]+: REUSED /) {
                split(c, w, " ")
                name = w[2]; sub(/:$/, "", name)
                printf "member-walls/1\t%s\treused\t-\t%s\n", name, part
            }
        }
    ' "$dir/run.log" >"$dir/log.walls"
    # AN HONOURED PUSH RAN NO SELFTEST SHARD, AND ITS LOG SAYS WHICH RUN DID.
    # A push whose tree a pull request's run already measured green is
    # honoured by derive (`honoured: tree <t> was measured green by run <id>`,
    # .github/workflows/ci.yml) and runs no `legs` job at all — so its log
    # carries no member line and uploads no walls, and a harvest of it could
    # only ever refuse. The run that measured the tree is the one the line
    # names; the step follows it ONCE (a followed run that is itself honoured is
    # a record nobody wrote, and is harvested as it stands).
    local honoured
    if [ ! -s "$dir/log.walls" ] && [ -z "${FOLD_WALLS_FOLLOWED:-}" ]; then
        honoured=$(sed -n 's/.*honoured: tree [0-9a-f]* was measured green by run \([0-9][0-9]*\).*/\1/p' "$dir/run.log" | sed -n 1p)
        if [ -n "$honoured" ]; then
            printf 'the push run %s ran no selftest shard — derive honoured its tree by run %s, which measured it; followed\n' \
                "$run" "$honoured" >"$dir/follow.note"
            rm -rf "$dir/artifacts" "$dir/artifacts.walls" "$dir/log.walls" "$dir/run.log"
            FOLD_WALLS_FOLLOWED=1 DJB_FOLD_WALLS_RUN="$honoured" fold_walls_fetch "$dir"
            return $?
        fi
    fi
    return 0
}

# fold_walls_rows <dir> — every `*.walls` file's rows, the files in name order
# (a glob, never `find`: the order a directory lists in is the filesystem's, and
# a refusal naming `sweep(2/3,1/3)` on one machine and `(1/3,2/3)` on another is
# a sentence nobody can grep for).
fold_walls_rows() {
    local f
    for f in "$1"/*.walls; do
        [ -f "$f" ] || continue
        cat "$f"
    done
}

# fold_walls_write <dir> <population-file> <out> — validate the harvest and
# write the table. Prints `walls: …` and returns 0 written, 3 not harvested.
fold_walls_write() {
    local dir=$1 pop=$2 out=$3 run="" machine="" tree="" why=""
    # EOF READERS OVER THE FILE, never a pipe into an early-exit reader — the
    # class `scripts/tests/test_pipefail_readers.sh` censuses.
    run=$(awk '/^run=/ { sub(/^run=/, ""); print; exit }' "$dir/run.meta" 2>/dev/null) || run=""
    machine=$(awk '/^machine=/ { sub(/^machine=/, ""); print; exit }' "$dir/run.meta" 2>/dev/null) || machine=""
    tree=$(awk '/^tree=/ { sub(/^tree=/, ""); print; exit }' "$dir/run.meta" 2>/dev/null) || tree=""
    [ -n "$run" ] && [ -n "$machine" ] && [ -n "$tree" ] ||
        why="the harvest does not say whose walls they are (run.meta needs run=, machine= and tree=)"
    if [ -z "$why" ]; then
        why=$(fold_walls_rows "$dir" | awk -F'\t' -v popf="$pop" '
            BEGIN { while ((getline p < popf) > 0) { if (p != "") { want[p] = 1 } } }
            NF == 0 { next }
            $1 != "member-walls/1" || NF != 5 { bad = bad " unparsable:" NR; next }
            {
                if ($3 == "reused") { reused = reused " " $2 }
                else if ($3 != "0") { red = red " " $2 "(exit " $3 ")" }
                else if ($4 !~ /^[0-9]+$/) { bad = bad " " $2 "(wall " $4 ")" }
                if ($2 in seen) { twice = twice " " $2 "(" seen[$2] "," $5 ")" }
                seen[$2] = $5
                if (!($2 in want)) { extra = extra " " $2 }
            }
            END {
                for (p in want) { if (!(p in seen)) { missing = missing " " p } }
                w = ""
                if (twice != "") { w = w "; in two shards:" twice }
                if (missing != "") { w = w "; missing against the population:" missing }
                if (extra != "") { w = w "; not a member of the population:" extra }
                if (red != "") { w = w "; not green:" red }
                if (reused != "") { w = w "; reused (never this run'"'"'s wall):" reused }
                if (bad != "") { w = w "; malformed:" bad }
                sub(/^; /, "", w)
                print w
            }
        ')
    fi
    if [ -n "$why" ]; then
        echo "  walls: NOT harvested — ${why}"
        echo "         ${FOLD_WALLS_PATH} unchanged (a hint, never a partial table)."
        return 3
    fi
    {
        printf '{\n'
        # `run:` AND `tree:` ARE PART OF THE VALUE, for the committed Mac table's
        # measured reason: a bare 40-hex value is what the secrets scanner reads
        # as a credential, and JSON has no comment to hang a pragma on.
        printf '  "measured_at": "run:%s tree:%s",\n' "$run" "$tree"
        printf '  "machine": "%s",\n' "$machine"
        printf '  "members": {\n'
        fold_walls_rows "$dir" | awk -F'\t' 'NF == 5 { print $2 "\t" $4 }' |
            LC_ALL=C sort | awk -F'\t' '
            { name[NR] = $1; secs[NR] = $2 }
            END { for (i = 1; i <= NR; i++) { printf "    \"%s\": %s%s\n", name[i], secs[i], (i < NR ? "," : "") } }
        '
        printf '  }\n'
        printf '}\n'
    } >"$dir/table.json"
    if [ -f "$out" ] && cmp -s "$dir/table.json" "$out"; then
        echo "  walls: harvested run ${run} ($(grep -c '^    "' "$dir/table.json") members, ${machine}, tree ${tree}) — the committed table already says exactly this"
        return 0
    fi
    cp "$dir/table.json" "$out"
    echo "  walls: harvested run ${run} ($(grep -c '^    "' "$dir/table.json") members, ${machine}, tree ${tree}) -> ${FOLD_WALLS_PATH}"
    return 0
}

echo "== (e) walls · the latest green CI run on main -> ${FOLD_WALLS_PATH}"
if ! fold_step_selected walls; then
    step_skipped "--only ${FOLD_ONLY} does not name this step"
elif [ ! -x "$ROOT/scripts/check.sh" ] && [ -z "${DJB_FOLD_WALLS_POPULATION:-}" ]; then
    step_skipped "no scripts/check.sh in this checkout — there is no selftest population to harvest walls for"
else
    STEPS_RUN=$((STEPS_RUN + 1))
    FOLD_WALLS_DIR="$FOLD_WORK/walls"
    mkdir -p "$FOLD_WALLS_DIR"
    FOLD_WALLS_WHY=""
    FOLD_WALLS_RC=0
    if [ -n "${DJB_FOLD_WALLS_DIR:-}" ]; then
        if [ -d "$DJB_FOLD_WALLS_DIR" ]; then
            cp "$DJB_FOLD_WALLS_DIR"/* "$FOLD_WALLS_DIR"/ 2>/dev/null || true
        else
            FOLD_WALLS_WHY="DJB_FOLD_WALLS_DIR=${DJB_FOLD_WALLS_DIR} is not a directory"
            FOLD_WALLS_RC=1
        fi
    else
        FOLD_WALLS_WHY=$(fold_walls_fetch "$FOLD_WALLS_DIR") || FOLD_WALLS_RC=$?
    fi
    if [ -s "$FOLD_WALLS_DIR/follow.note" ]; then
        echo "  walls: $(cat "$FOLD_WALLS_DIR/follow.note")"
    fi
    if [ "$FOLD_WALLS_RC" = "1" ]; then
        echo "  walls: could not look (${FOLD_WALLS_WHY}) — the committed table stands"
    elif [ "$FOLD_WALLS_RC" = "3" ]; then
        echo "  walls: NOT harvested — ${FOLD_WALLS_WHY}"
        echo "         ${FOLD_WALLS_PATH} unchanged (a hint, never a partial table)."
    elif ! fold_walls_population >"$FOLD_WALLS_DIR/population" || [ ! -s "$FOLD_WALLS_DIR/population" ]; then
        echo "  walls: could not look (the selftest population would not derive from ./scripts/check.sh --list-legs) — the committed table stands"
    else
        fold_walls_write "$FOLD_WALLS_DIR" "$FOLD_WALLS_DIR/population" "$ROOT/$FOLD_WALLS_PATH" || true
    fi
fi
echo ""

# --- (f) map: the latest nightly's test-impact map ---------------------------
#
# WHAT IT HARVESTS. `.github/workflows/nightly-proof.yml` runs the leak proof
# (`scripts/pm_push.sh --proof`) on main every night and publishes the
# `nightly-leak-proof` artifact: `leak_proof.txt` (the record, grammar owned by
# `scripts/gate_ledger.sh`) and, on a green pass 1, `test_impact.json` — the map
# the loop's closure scope reads (`scripts/loop_tier.sh`, LOOP_SCOPE_MAP_PATH).
# Since the leak proof went nightly a bank under `--leak-proof nightly` launches
# no acceptance box, so nothing else writes the map: this step takes the LATEST
# completed nightly and, when it is green, no older than 24 h and carries a map,
# writes `scripts/test_impact.json` from it and commits it with the fold.
#
# RED, STALE OR NONE → UNCHANGED, AND SAID. The map is a hint: a stale one
# costs the loop a narrower scope, never a verdict. So every reason not to
# write it prints ONE line naming the reason and the fold's exit is exactly
# what the other steps left it:
#
#   map: harvested nightly run <id> (<at>, tree <12>) -> scripts/test_impact.json
#   map: NOT harvested — the latest nightly (run <id>) is red (<form>) …
#   map: NOT harvested — the latest nightly (run <id>) is older than 24 h …
#   map: NOT harvested — nightly run <id> is green and published no map (map=<n>) …
#   map: none — <why> — scripts/test_impact.json unchanged
#   map: could not look (<why>) — scripts/test_impact.json unchanged
#
# THE LATEST, NEVER THE LATEST GREEN: a red night is the thing to say, and a
# walk back to an older green would print a harvest over the run that failed.
# One fetcher and one reader — `gate_nightly_fetch` and `gate_nightly_read` in
# `scripts/gate_ledger.sh`, the same two a bank's `--leak-proof nightly` calls.
#
# A MAP A BANK ALREADY WROTE WINS. `scripts/test_impact.json` is the one
# ABSORBED path: an acceptance box writes it into the working tree and the fold
# commits it. When it arrives here already dirty it is THIS tree's measurement
# and last night's is older — so the step says so and replaces nothing.
#
# SEAMS: DJB_FOLD_MAP_DIR — a directory already holding the artifact
# (`leak_proof.txt`, and `test_impact.json` when the night wrote one); gh is not
# asked. DJB_FOLD_GH — the gh the fetch runs (shared with step (e)).
#
# WHAT IT DOES NOT COVER: whether last night's map describes today's tree (the
# map names its own tree in its `generated` block, and the loop reads it as a
# hint); an artifact GitHub served wrong.
FOLD_MAP_PATH='scripts/test_impact.json'
FOLD_MAP_HARVESTED=0
FOLD_MAP_ABSORBED=0
FOLD_MAP_PRUNED=0

# fold_map_prune — drop every map entry this checkout no longer COLLECTS.
#
# WHY THE FOLD DOES IT. A test the map names and the collection does not hold
# (renamed, parametrized, deleted since the map was measured) is a stale entry;
# the loop's reader now names it and runs its module whole
# (`_impact_selection`, apps/conftest.py) instead of killing every worker, and
# this is the other half: the committed map stops naming it. Whatever the map
# step above decided — harvested, absorbed, unchanged — the map that is about
# to be committed is pruned against THIS tree's collection.
#
# THE COLLECTION IS pytest's OWN (`--collect-only -q`, read by the map writer's
# own `read_collected`, and the file is re-rendered by its own `render`, both
# imported from scripts/test_impact.py — one reader and one writer, never a
# second). `DJB_FOLD_MAP_COLLECTED` names a collection already taken, so a drive
# needs no suite. A collection that failed is `could not prune`, and the map
# stands as it was.
#
#   map: pruned <n> ids no longer collected — <ids> -> scripts/test_impact.json
#   map: every entry is collected (<n>) — nothing pruned
#   map: could not prune (<why>) — scripts/test_impact.json as it stands
fold_map_prune() {
    local collected="${DJB_FOLD_MAP_COLLECTED:-}" rc=0 said
    [ -f "$ROOT/$FOLD_MAP_PATH" ] || return 0
    if [ ! -f "$ROOT/scripts/test_impact.py" ]; then
        echo "  map: could not prune (no scripts/test_impact.py to read a collection with) — ${FOLD_MAP_PATH} as it stands"
        return 0
    fi
    if [ -z "$collected" ]; then
        collected="$FOLD_WORK/map-collected.txt"
        if ! command -v "$FOLD_UV" >/dev/null 2>&1; then
            echo "  map: could not prune (no ${FOLD_UV} on PATH to collect with) — ${FOLD_MAP_PATH} as it stands"
            return 0
        fi
        (cd "$ROOT" && "$FOLD_UV" run pytest --collect-only -q -p no:randomly) >"$collected" 2>&1 || rc=$?
        if [ "$rc" != "0" ]; then
            echo "  map: could not prune (the collection exited ${rc}: $(grep -m1 -E 'Error|error' "$collected" || echo 'no error line')) — ${FOLD_MAP_PATH} as it stands"
            return 0
        fi
    fi
    # NO BYTECODE: importing the writer must write nothing into the tree the
    # fold's own footprint census is about to judge (measured: a `__pycache__`
    # beside scripts/test_impact.py was the fold's own stray).
    said=$(cd "$ROOT" && PYTHONDONTWRITEBYTECODE=1 python3 - "$FOLD_MAP_PATH" "$collected" 2>&1 <<'PY'
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location("test_impact", "scripts/test_impact.py")
if spec is None or spec.loader is None:
    print("could not prune (scripts/test_impact.py would not load)")
    sys.exit(0)
ti = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ti)
path, collected_path = sys.argv[1], sys.argv[2]
try:
    collected = set(ti.read_collected(collected_path))
except ti.CannotLook as exc:
    print(f"could not prune ({str(exc).splitlines()[0]})")
    sys.exit(0)
doc = json.load(open(path, encoding="utf-8"))
stale = sorted(n for n in doc["tests"] if n not in collected)
if not stale:
    print(f"every entry is collected ({len(doc['tests'])}) — nothing pruned")
    sys.exit(0)
for nodeid in stale:
    del doc["tests"][nodeid]
with open(path, "w", encoding="utf-8") as fh:
    fh.write(ti.render(doc))
shown = ", ".join(stale[:5]) + (f" (+{len(stale) - 5} more)" if len(stale) > 5 else "")
print(f"pruned {len(stale)} ids no longer collected — {shown} -> {path}")
PY
) || said="could not prune (python3 exited $?)"
    case "$said" in
    "could not prune"*) echo "  map: ${said} — ${FOLD_MAP_PATH} as it stands" ;;
    pruned*)
        # AN EOF READER, NEVER A PIPE INTO AN EARLY-EXIT awk (the pipefail census).
        FOLD_MAP_PRUNED=$(awk '{ print $2; exit }' <<EOF
$said
EOF
)
        echo "  map: ${said}"
        ;;
    *) echo "  map: ${said}" ;;
    esac
    return 0
}

echo "== (f) map · the latest nightly's test-impact map -> ${FOLD_MAP_PATH}"
if ! fold_step_selected map; then
    step_skipped "--only ${FOLD_ONLY} does not name this step"
elif [ ! -f "$ROOT/$FOLD_MAP_PATH" ]; then
    step_skipped "no ${FOLD_MAP_PATH} in this checkout — there is no map to keep current"
else
    STEPS_RUN=$((STEPS_RUN + 1))
    FOLD_MAP_DIR=""
    FOLD_MAP_RUN="(given)"
    FOLD_MAP_WHY=""
    FOLD_MAP_RC=0
    if [ -n "$(git status --porcelain -- "$FOLD_MAP_PATH")" ]; then
        FOLD_MAP_RC=9
    elif [ -n "${DJB_FOLD_MAP_DIR:-}" ]; then
        if [ -d "$DJB_FOLD_MAP_DIR" ]; then
            FOLD_MAP_DIR="$DJB_FOLD_MAP_DIR"
        else
            FOLD_MAP_WHY="DJB_FOLD_MAP_DIR=${DJB_FOLD_MAP_DIR} is not a directory"
            FOLD_MAP_RC=2
        fi
    else
        FOLD_MAP_WHY=$(bash -c '
            set -uo pipefail
            . "$1" >/dev/null 2>&1 || { echo "scripts/gate_ledger.sh would not load"; exit 2; }
            GATE_NIGHTLY_GH="$2"
            gate_nightly_fetch "$3"
        ' _ "$FOLD_DECL_READER" "$FOLD_GH" "$FOLD_WORK/map") || FOLD_MAP_RC=$?
        if [ "$FOLD_MAP_RC" = "0" ]; then
            FOLD_MAP_RUN="${FOLD_MAP_WHY%% *}"
            FOLD_MAP_DIR="${FOLD_MAP_WHY#* * }"
            FOLD_MAP_WHY=""
        fi
    fi
    FOLD_MAP_FORM=""
    if [ "$FOLD_MAP_RC" = "0" ]; then
        FOLD_MAP_FORM=$(bash -c '
            set -uo pipefail
            . "$1" >/dev/null 2>&1 || { echo "scripts/gate_ledger.sh would not load" >&2; exit 2; }
            gate_nightly_read "$2"
        ' _ "$FOLD_DECL_READER" "$FOLD_MAP_DIR" 2>"$FOLD_WORK/map-read.err") || FOLD_MAP_RC=$?
        [ "$FOLD_MAP_RC" = "0" ] || FOLD_MAP_WHY="the record is unreadable: $(tr '\n' ' ' <"$FOLD_WORK/map-read.err")"
    fi
    case "$FOLD_MAP_RC" in
    9)
        FOLD_MAP_ABSORBED=1
        echo "  map: ${FOLD_MAP_PATH} is already modified in this working tree — a bank's"
        echo "       acceptance box wrote it, and this tree's own measurement outranks last"
        echo "       night's. Absorbed as it stands; nothing was fetched."
        ;;
    1) echo "  map: none — ${FOLD_MAP_WHY} — ${FOLD_MAP_PATH} unchanged" ;;
    0)
        FOLD_MAP_MAPRC=$(awk 'NF { for (i = 1; i <= NF; i++) if ($i ~ /^map=/) { sub(/^map=/, "", $i); print $i; exit } exit }' "$FOLD_MAP_DIR/leak_proof.txt")
        case "$FOLD_MAP_FORM" in
        nightly:stale:*)
            echo "  map: NOT harvested — the latest nightly (run ${FOLD_MAP_RUN}) is older than 24 h (${FOLD_MAP_FORM})"
            echo "       — ${FOLD_MAP_PATH} unchanged."
            ;;
        *" rc=0")
            if [ "$FOLD_MAP_MAPRC" != "0" ] || [ ! -s "$FOLD_MAP_DIR/test_impact.json" ]; then
                echo "  map: NOT harvested — nightly run ${FOLD_MAP_RUN} is green and published no map (map=${FOLD_MAP_MAPRC:-?})"
                echo "       — ${FOLD_MAP_PATH} unchanged."
            elif ! command -v python3 >/dev/null 2>&1 ||
                ! python3 -c 'import json, sys; d = json.load(open(sys.argv[1])); sys.exit(0 if isinstance(d, dict) and isinstance(d.get("tests"), dict) and "generated" in d else 1)' \
                    "$FOLD_MAP_DIR/test_impact.json" 2>/dev/null; then
                echo "  map: could not look (nightly run ${FOLD_MAP_RUN}'s test_impact.json is not a map python3 can read) — ${FOLD_MAP_PATH} unchanged"
            elif cmp -s "$FOLD_MAP_DIR/test_impact.json" "$ROOT/$FOLD_MAP_PATH"; then
                echo "  map: harvested nightly run ${FOLD_MAP_RUN} (${FOLD_MAP_FORM}) — the committed map already says exactly this"
            else
                cp "$FOLD_MAP_DIR/test_impact.json" "$ROOT/$FOLD_MAP_PATH"
                FOLD_MAP_HARVESTED=1
                echo "  map: harvested nightly run ${FOLD_MAP_RUN} (${FOLD_MAP_FORM}) -> ${FOLD_MAP_PATH}"
            fi
            ;;
        *)
            echo "  map: NOT harvested — the latest nightly (run ${FOLD_MAP_RUN}) is red (${FOLD_MAP_FORM})"
            echo "       — ${FOLD_MAP_PATH} unchanged; a red night's map is half a measurement."
            ;;
        esac
        ;;
    *) echo "  map: could not look (${FOLD_MAP_WHY}) — ${FOLD_MAP_PATH} unchanged" ;;
    esac
    fold_map_prune
fi
echo ""


# --- (local) the product's own steps, in name order --------------------------
#
# AFTER THE TEMPLATE'S FOUR, and the order is a contract rather than an
# accident: a product's step regenerates from THIS checkout, and the contract
# and the schema dump are part of this checkout by the time it runs. Within the
# drawer the order is the shell's glob order, which is byte order on the
# basename — hence the `<nn>-<name>.sh` convention, which is the product's to
# use and this file's only to honour.
#
# THE CENSUS IS PER STEP, AND THAT IS THE WHOLE REASON IT IS HERE RATHER THAN
# ONLY AT THE END. Clause 2's footprint census at the foot of this file names a
# stray PATH; it cannot name who wrote it, because by then four template steps
# and N local ones have run over one tree. A drawer makes "who wrote it" the
# question a reader actually has, so each local step is censused against the
# tree AS THE PREVIOUS STEP LEFT IT: a path that is new since then and is in
# nobody's declaration is that step's, by name, with nothing committed. A stray
# a TEMPLATE step wrote is not in the delta and is left to clause 2, which is
# the only reader that can honestly claim it.
if [ -n "$FOLD_LOCAL_STEPS" ]; then
    fold_dirty_paths >"$FOLD_WORK/local.before"
    while IFS="$(printf '\t')" read -r _lname _lpath; do
        [ -n "$_lname" ] || continue
        echo "== (local) ${_lname} · scripts/local/fold.d/${_lname}.sh"
        if ! fold_step_selected "$_lname"; then
            step_skipped "--only ${FOLD_ONLY} does not name this step"
            echo ""
            continue
        fi
        STEPS_RUN=$((STEPS_RUN + 1))
        # `</dev/null` IS LOAD-BEARING: this loop's stdin is the here-doc
        # carrying the remaining steps, and a step that read one line off it
        # would silently eat the next step out of the run.
        LOCAL_RC=0
        (cd "$ROOT" && "$_lpath") </dev/null || LOCAL_RC=$?
        [ "$LOCAL_RC" = "0" ] ||
            refuse "the local step '${_lname}' exited ${LOCAL_RC} (its output is above)." \
                "A step that failed did not regenerate what it declares, and this run cannot" \
                "say the declared paths came from this checkout — could-not-look, never a" \
                "clean fold." \
                "Nothing was committed."

        # A STEP THAT DELETED ITS OWN DECLARED PATH IS REFUSED, and it is not
        # the same finding as a stray. `fold_dirty_paths` strips the status
        # characters, so a deletion looks exactly like a rewrite to the census
        # below: the path is dirty, it is declared, it is committed, and the
        # subject says `1 declared path(s) regenerated` about a file that is
        # GONE. The next fold then reds on a generator whose input vanished,
        # one commit downstream of the run that did it. A fold regenerates; a
        # deletion is a human diff.
        git status --porcelain -uall >"$FOLD_WORK/local.porcelain"
        LOCAL_GONE=""
        while IFS= read -r _lentry; do
            [ -n "$_lentry" ] || continue
            case "${_lentry:0:2}" in
            *D* | *d*) ;;
            *) continue ;;
            esac
            _lp="${_lentry:3}"
            if fold_is_declared "$_lp"; then
                LOCAL_GONE="${LOCAL_GONE}${_lp}
"
            fi
        done <"$FOLD_WORK/local.porcelain"
        if [ -n "$LOCAL_GONE" ]; then
            FOLD_REFUSED=1
            echo "!! pm_fold: the local step '${_lname}' DELETED a path it declares." >&2
            printf '%s' "$LOCAL_GONE" | while IFS= read -r _lp; do
                [ -n "$_lp" ] || continue
                echo "     ${_lp}" >&2
            done
            echo "   A declaration says the step REGENERATES that path. Committing the" >&2
            echo "   deletion under \"declared path(s) regenerated\" would put a removal into" >&2
            echo "   the one history nobody reads by hand, and the next fold would red on a" >&2
            echo "   generator whose input had vanished a commit earlier." >&2
            echo "   NOTHING WAS COMMITTED. Removing a derived file is a human diff: take the" >&2
            echo "   path out of the step's declaration in the same change." >&2
            exit 2
        fi

        fold_dirty_paths >"$FOLD_WORK/local.after"
        LOCAL_STRAY=""
        while IFS= read -r _lp; do
            [ -n "$_lp" ] || continue
            # `if`, NEVER `<test> && continue`: a failing left-hand side makes
            # the whole `&&` list the loop body's last status, and under
            # `set -e` that kills the run — silently, in the one loop whose job
            # is to refuse loudly.
            if grep -qxF -- "$_lp" "$FOLD_WORK/local.before"; then continue; fi
            if fold_is_derived "$_lp"; then continue; fi
            LOCAL_STRAY="${LOCAL_STRAY}${_lp}
"
        done <"$FOLD_WORK/local.after"
        if [ -n "$LOCAL_STRAY" ]; then
            FOLD_REFUSED=1
            echo "!! pm_fold: the local step '${_lname}' wrote a path it did not declare." >&2
            printf '%s' "$LOCAL_STRAY" | while IFS= read -r _lp; do
                [ -n "$_lp" ] || continue
                echo "     ${_lp}" >&2
            done
            echo "   scripts/local/fold.d/${_lname}.sh declares:" >&2
            fold_declared_paths "scripts/local/fold.d/${_lname}.sh" 2>/dev/null | while IFS= read -r _lp; do
                [ -n "$_lp" ] || continue
                echo "     ${_lp}" >&2
            done
            echo "   A step's declaration is what this fold partitions its output against, and" >&2
            echo "   the declaration is the product's own — so a write outside it is not a" >&2
            echo "   smaller commit, it is a step that did something nobody wrote down." >&2
            echo "   NOTHING WAS COMMITTED. The tree is left exactly as the run left it, so the" >&2
            echo "   evidence is still there: read \`git status\`." >&2
            exit 2
        fi
        cp "$FOLD_WORK/local.after" "$FOLD_WORK/local.before"
        echo ""
    done <<EOF
$FOLD_LOCAL_STEPS
EOF
    unset _lname _lpath _lp _lentry
fi

if [ "$STEPS_RUN" -eq 0 ]; then
    if [ -n "$FOLD_ONLY" ]; then
        refuse "--only ${FOLD_ONLY} selected no step this checkout can run." \
            "The named step's artifact is not here, so this run regenerated nothing and" \
            "cannot say the file a caller asked about is current. A caller reading a 0" \
            "would read 'already current' off a run that never looked." \
            "Nothing was committed."
    fi
    refuse "this checkout has none of the four things a fold folds — no committed contract, no manage.py, no .secrets.baseline, no quality/budgets.yaml." \
        "That is a reader looking at the wrong tree, not a tree with nothing to fold." \
        "Nothing was committed."
fi

# --- CLAUSE 2: the fold's own footprint --------------------------------------
#
# THE WHOLE of `git status --porcelain -uall` is partitioned against the typed
# list. Not a diff of the list's own paths: a diff of the list can only ever
# find what the list already knows about, and the thing worth catching is a
# generator that wrote SOMEWHERE ELSE.
#
# The loop runs in THIS shell — a here-doc, never a pipe — because a pipe puts
# it in a subshell and both accumulators die with it, which reads as "no
# strays".
echo "== the fold's own footprint"
STRAY=""
CHANGED=""
while IFS= read -r p; do
    [ -n "$p" ] || continue
    if fold_is_derived "$p"; then
        CHANGED="${CHANGED}${p}
"
    else
        STRAY="${STRAY}${p}
"
    fi
done <<EOF
$(fold_dirty_paths)
EOF

if [ -n "$STRAY" ]; then
    FOLD_REFUSED=1
    echo "!! pm_fold: the fold modified a file OUTSIDE the derived list." >&2
    printf '%s' "$STRAY" | while IFS= read -r p; do
        [ -n "$p" ] || continue
        echo "     ${p}" >&2
    done
    echo "   A fold regenerates derived files and nothing else. A generator that wrote" >&2
    echo "   somewhere else did something nobody asked for, and this run cannot say what" >&2
    echo "   else it did — so it is a could-not-look and not a smaller commit." >&2
    echo "   NOTHING WAS COMMITTED. The tree is left exactly as the run left it, so the" >&2
    echo "   evidence is still there: read \`git status\`, then \`git checkout --\` what you" >&2
    echo "   did not want." >&2
    exit 2
fi

if [ -z "$CHANGED" ]; then
    echo "  nothing moved — every derived file already agrees with this checkout."
    echo "pm_fold: NOTHING TO FOLD. No commit was made; HEAD is still $(git rev-parse --short "$PRE_HEAD")."
    FOLD_REACHED_THE_END=1
    exit 0
fi

# --- --NO-COMMIT: the census ran, and the result is the RUNG'S to commit ------
# Clause 2 above is what makes this safe to stop here: a stray was still exit 2
# with nothing staged, so what is left in the working tree is derived files and
# derived files only. The one thing this branch must not do is stage them — the
# staged set is the caller's claim, and this run is not the caller.
if [ -n "$FOLD_NO_COMMIT" ]; then
    echo ""
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        echo "  changed  ${p}"
    done <<EOF
$CHANGED
EOF
    echo ""
    echo "pm_fold: --no-commit. The regenerated file(s) above are in the WORKING TREE,"
    echo "  unstaged and uncommitted; HEAD is still $(git rev-parse --short "$PRE_HEAD"). They"
    echo "  belong in the rung's own diff, where a reviewer reads them."
    FOLD_REACHED_THE_END=1
    exit 0
fi

# --- the commit: explicit paths, never `git add -A` ---------------------------
CONTRACT_CHANGED=0
BASELINE_CHANGED=0
BUDGETS_CHANGED=0
MAP_CHANGED=0
WALLS_CHANGED=0
DECLARED_CHANGED=0
while IFS= read -r p; do
    [ -n "$p" ] || continue
    echo "  changed  ${p}"
    case "$p" in
    frontend/openapi.json | frontend/src/api/generated/*) CONTRACT_CHANGED=1 ;;
    .secrets.baseline) BASELINE_CHANGED=1 ;;
    quality/budgets.yaml) BUDGETS_CHANGED=1 ;;
    # ITS OWN ARM AND ITS OWN WORD. Falling through to `*)` would subject the
    # map "1 declared path(s) regenerated" — and this fold regenerated nothing:
    # a verifier box did, and this run absorbed it. A commit subject that says
    # the wrong verb about the one path nobody can reproduce locally is worse
    # than a bare one.
    scripts/test_impact.json) MAP_CHANGED=1 ;;
    scripts/gate_member_durations.ci.json) WALLS_CHANGED=1 ;;
    *)
        # A DECLARED PATH, and the subject must say so. Without this arm a fold
        # whose only change came from a declaration commits under the bare
        # subject `fold:` — a commit that names nothing, in the one history
        # where the subject is how a reviewer knows what an unattended script
        # did.
        DECLARED_CHANGED=$((DECLARED_CHANGED + 1))
        ;;
    esac
    git add -- "$p" ||
        refuse "could not stage ${p}." "Nothing was committed."
done <<EOF
$CHANGED
EOF

SUBJECT="fold:"
SEP=" "
if [ "$CONTRACT_CHANGED" = "1" ]; then
    SUBJECT="${SUBJECT}${SEP}contract regenerated"
    SEP=" · "
fi
if [ "$BASELINE_CHANGED" = "1" ]; then
    SUBJECT="${SUBJECT}${SEP}baseline shifted"
    SEP=" · "
fi
if [ "$BUDGETS_CHANGED" = "1" ]; then
    SUBJECT="${SUBJECT}${SEP}${BUDGETS_LOWERED} budgets lowered"
    SEP=" · "
fi
if [ "$MAP_CHANGED" = "1" ]; then
    # TWO WRITERS, TWO VERBS: a bank's acceptance box wrote the map into the
    # working tree and this run ABSORBED it, or step (f) HARVESTED last night's.
    # A THIRD, WHEN IT IS THE ONLY ONE: step (f)'s prune dropped ids the
    # collection no longer holds from a map nobody else rewrote.
    if [ "$FOLD_MAP_HARVESTED" = "1" ]; then
        SUBJECT="${SUBJECT}${SEP}nightly map harvested"
    elif [ "$FOLD_MAP_ABSORBED" = "0" ] && [ "$FOLD_MAP_PRUNED" != "0" ]; then
        SUBJECT="${SUBJECT}${SEP}map pruned (${FOLD_MAP_PRUNED} ids no longer collected)"
    else
        SUBJECT="${SUBJECT}${SEP}acceptance map absorbed"
    fi
    SEP=" · "
fi
if [ "$WALLS_CHANGED" = "1" ]; then
    SUBJECT="${SUBJECT}${SEP}CI walls harvested"
    SEP=" · "
fi
if [ "$DECLARED_CHANGED" != "0" ]; then
    SUBJECT="${SUBJECT}${SEP}${DECLARED_CHANGED} declared path(s) regenerated"
    SEP=" · "
fi

# THE SUBJECT IS THE FIRST LINE OF THE MESSAGE FILE, and in the sibling
# product's first draft it was not — the body was written and nothing else, so
# every fold commit was subjected `Pre-fold tree: <hash>`. It was caught by
# that product's own drive on its first green run, in three cases at once. The
# drive here asserts the subject for the same reason.
{
    echo "$SUBJECT"
    echo ""
    echo "Pre-fold tree: ${PRE_TREE}"
    echo "Pre-fold HEAD: ${PRE_HEAD}"
    echo ""
    echo "Derived files only, regenerated by scripts/pm_fold.sh. Nothing in this"
    echo "commit was written by hand: the contract is the byte-pin's regeneration,"
    echo "the baseline is detect-secrets', and every budget number is a line the"
    echo "gate itself printed under \"a human may commit the lower number\". A"
    echo "ceiling is never raised here. The CI walls table is a green CI run's own"
    echo "shard lines, harvested whole or not at all."
} >"$FOLD_WORK/message"

echo ""
echo "pm_fold: committing — ${SUBJECT}"
COMMIT_RC=0
git commit -F "$FOLD_WORK/message" || COMMIT_RC=$?
if [ "$COMMIT_RC" != "0" ]; then
    FOLD_REFUSED=1
    echo "!! pm_fold: the commit failed (git exit ${COMMIT_RC})." >&2
    echo "   The derived files above are STAGED and the tree is dirty. A caller that" >&2
    echo "   banks or merges from here would measure a tree nobody committed — which is" >&2
    echo "   why this is a 2 and not a warning. Read git's output above (a pre-commit" >&2
    echo "   hook that went red is the usual cause), then commit or reset by hand." >&2
    exit 2
fi

POST_HEAD="$(git rev-parse --verify HEAD)"
if [ "$POST_HEAD" = "$PRE_HEAD" ]; then
    refuse "git exited 0 but HEAD did not move ($(git rev-parse --short "$PRE_HEAD"))." \
        "A zero status for a commit that produced nothing is the shape a caller reads as" \
        "a fold. Nothing here is vouched for."
fi

echo ""
git show --stat --oneline "$POST_HEAD"

if [ -n "$(git status --porcelain)" ]; then
    FOLD_REFUSED=1
    echo "!! pm_fold: the tree is still dirty after the fold commit." >&2
    git status --short >&2
    echo "   Everything the fold changed was supposed to be in it. A caller banking from" >&2
    echo "   here would key its verdict on a tree that is in nobody's history." >&2
    exit 2
fi

echo ""
echo "pm_fold: FOLDED. $(git rev-parse --short "$PRE_HEAD") -> $(git rev-parse --short "$POST_HEAD")"
FOLD_REACHED_THE_END=1
