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
#   --only <steps>   a comma-joined subset of the four step names, which are a
#                    CLOSED list: contract|schema|secrets|budgets (steps a-d).
#                    An unknown name is exit 2, never a silently smaller fold.
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
#   1. A DIRTY TREE IS REFUSED. A fold folds a COMMITTED tree. With work
#      already in the checkout there is no way to say which of the changes the
#      fold made, and the commit this script writes would carry whatever it
#      swept up.
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
#   * A FIFTH DERIVED FILE. `DERIVED_PATHS` below is TYPED, never computed, and
#     that is deliberate: a computed list is a list that grows whenever a
#     generator misbehaves, which is the one thing clause 2 exists to catch. A
#     new derived file is a human edit to this file — until then a new
#     generator's output is a STRAY and stops the fold, which is clause 2
#     working rather than failing.
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

fold_cleanup() {
    [ -z "${FOLD_WORK:-}" ] || rm -rf "$FOLD_WORK"
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
# Four names for the four steps, in the order they run. TYPED here for the same
# reason `DERIVED_PATHS` is typed: a computed list is a list that grows whenever
# something misbehaves, and the whole value of `--only` is that a name it does
# not recognise is exit 2 rather than a silently smaller fold.
FOLD_STEP_NAMES='contract schema secrets budgets'
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

<steps> is a comma-joined subset of a CLOSED list, the four steps in order:
contract, schema, secrets, budgets. An unknown name is exit 2.

`--no-commit` is legal only WITH `--only`: a whole fold that commits nothing is
a bank that vouches for a tree nobody wrote down. `scripts/rung_tidy.sh
--secrets` is the caller these two exist for — step (c)'s scan line, the tree's
one legal baseline writer, stays in this file rather than being copied into a
second writer. (The command itself is deliberately not spelled here: a censused
string counts wherever it appears, prose included.)

`--bank` and `--no-fold` are the CALLERS' flags (scripts/pm_push.sh,
scripts/pm_merge.sh), never this script's.

Exit: 0 folded, or nothing to fold · 1 never · 2 refused, or could not look.

The four clauses: a dirty tree is refused; only the typed derived list may be
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

# THE STEP LIST IS CLOSED, AND A NAME OUTSIDE IT IS EXIT 2. A typo that fell
# through to "select nothing" would be a fold that ran no step and said so in
# the voice of a clean tree.
if [ -n "$FOLD_ONLY" ]; then
    IFS=',' read -r -a _fold_wanted <<<"$FOLD_ONLY"
    for _fold_step in "${_fold_wanted[@]}"; do
        case " ${FOLD_STEP_NAMES} " in
        *" ${_fold_step} "*) ;;
        *)
            refuse "--only names '${_fold_step}', which is not a step of this fold." \
                "The steps are a closed list, in the order they run: ${FOLD_STEP_NAMES}." \
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
# IT IS A FIXED LITERAL AND NOT A COMPUTED SET. See the header's third blind
# spot: a computed list grows whenever a generator misbehaves, which is the one
# thing clause 2 exists to catch.
DERIVED_PATHS='frontend/openapi.json
frontend/src/api/generated/schema.d.ts
.secrets.baseline
quality/budgets.yaml'

fold_is_derived() {
    local want="$1" p
    while IFS= read -r p; do
        [ -n "$p" ] || continue
        [ "$p" != "$want" ] || return 0
    done <<EOF
$DERIVED_PATHS
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

# --- CLAUSE 1: a dirty tree is refused ---------------------------------------
# Inline rather than through `refuse()`, because the refusal wants
# `git status --short` interleaved with its own sentences.
if [ -n "$(git status --porcelain)" ]; then
    FOLD_REFUSED=1
    echo "!! pm_fold: ${ROOT} has uncommitted changes." >&2
    git status --short >&2
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
while IFS= read -r p; do
    [ -n "$p" ] || continue
    echo "  changed  ${p}"
    case "$p" in
    frontend/openapi.json | frontend/src/api/generated/*) CONTRACT_CHANGED=1 ;;
    .secrets.baseline) BASELINE_CHANGED=1 ;;
    quality/budgets.yaml) BUDGETS_CHANGED=1 ;;
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
    echo "ceiling is never raised here."
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
