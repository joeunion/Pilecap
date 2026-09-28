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
# Pin the pm-push worktree to a commit and push it. The PM's one push path.
#
#   ./scripts/pm_push.sh              # pin pm-push to THIS checkout's HEAD, push
#   ./scripts/pm_push.sh <sha>        # pin it to that commit instead
#   ./scripts/pm_push.sh --dry-run    # everything except the push
#   ./scripts/pm_push.sh --bank       # bank a verdict for this tree FIRST, then push
#   ./scripts/pm_push.sh --bank --on-boxes 8
#                                     # the same verdict, measured on 8 verifier boxes
#                                     # instead of on this laptop: one unit of the gate
#                                     # per box, every shard's verdict fetched, ONE
#                                     # composed row banked for the post-fold tree.
#   ./scripts/pm_push.sh --pr         # push THIS pm/* train branch with NO local verdict:
#                                     # its pull request's CI run is the measurement
#   ./scripts/pm_push.sh --ci-verdict [<run id>]
#                                     # read that run's record and bank the ci: row;
#                                     # then a plain push fast-forwards main to it
#   ./scripts/pm_push.sh --bank --on-boxes 8 --leak-proof nightly
#                                     # the shards at one pass, the second whole pass
#                                     # read from the latest nightly (report-only);
#                                     # `acceptance` (the default) launches the box
#   ./scripts/pm_push.sh --proof [--out D] [--seed S] [--workers N]
#                                     # the leak proof itself, HERE: the suite twice
#                                     # under one seed, the map, leak_proof.txt
#
# WHY THIS EXISTS, and it is a scar rather than a convenience. On
# 2026-08-23 a `cd` into the pm-push worktree persisted as the PM session's
# working directory. The next three commits — including a merge — landed on
# pm-push's DETACHED HEAD instead of the branch; the following re-pin left them
# dangling; and the push then carried a tip nobody intended. Nothing failed.
# The only thing that caught it was a human reading the push's range line and
# noticing it said `7f2c4f6..328ff47` where a different merge was expected.
#
# So this script exists to make that sequence unavailable:
#
#   1. IT NEVER CHANGES ANYBODY'S WORKING DIRECTORY. Every git call is
#      `git -C <path>`. There is no `cd` in this file, so there is no cwd left
#      behind in another checkout for the next command to inherit. That is the
#      first half of the rule the incident produced, enforced instead of
#      remembered.
#   2. IT PRINTS THE RANGE AND THE INTENDED TIP TOGETHER, before the push, so
#      the comparison the PM had to do from memory is on the screen. The second
#      half of the rule, made cheap.
#   3. IT DOES NOTHING AFTER THE PUSH. The push is `exec`'d: this process is
#      REPLACED by git, so the exit status a caller sees is the push's own and
#      there is no line of code after it — nothing to swallow a failure, log
#      over it, or "clean up" on the way out. A push that is refused exits
#      nonzero through this script, unchanged.
#
# The pm-push worktree is found from `git worktree list`, never hard-coded: a
# path typed into a script is a path that goes stale, and a stale one here would
# pin the wrong checkout.
set -euo pipefail

TARGET_BRANCH="${DJB_PUSH_BRANCH:-main}"
REMOTE="${DJB_PUSH_REMOTE:-origin}"
WORKTREE_NAME="${DJB_PUSH_WORKTREE:-pm-push}"

die() {
    # Exit 2 everywhere in this repository is "could not look" — here, "could
    # not get as far as pushing". A push that was never attempted must never
    # share an exit code with a push that was refused.
    echo "!! pm_push: $*" >&2
    echo "   Nothing was pinned and nothing was pushed." >&2
    exit 2
}

BANK=0
#: The CI road's two modes (the `ci:` verdict). Each is its own arm below and
#: neither pins the pm-push worktree: `--pr` pushes the checkout's own train
#: branch, and `--ci-verdict` pushes nothing at all.
PR_MODE=0
CI_VERDICT_MODE=0
CI_VERDICT_RUN=""

# --- --no-fold, LIFTED OUT BEFORE THE MAIN PARSER, AND NEVER SILENTLY --------
#
# WHY IT IS LIFTED. `--bank` enforces `[ "$#" -eq 1 ]` below — a bank measures
# THIS checkout's tree, so it takes no commit argument — and `--no-fold` would
# land in that count and be rejected as a commit-ish. So it is taken out of the
# argument list here, before anything counts.
#
# AND WHY THE REFUSAL BELOW EXISTS. The sibling product lifts it out exactly
# like this and then consults it ONLY inside the `--bank` block, which makes
# `./scripts/pm_push.sh --no-fold` an ORDINARY PUSH OF HEAD with the flag
# accepted, inert, and nothing printed (a defect confirmed by reading their
# tree). The effect is benign — a plain push regenerates nothing, so there is
# nothing there for a fold to skip — but the LEGIBILITY is not: an operator
# typed a flag, this script took it, and it did nothing. That is the
# never-silent class, and this repository does not inherit it. Outside `--bank`
# the flag is a loud refusal, and `pm_merge.sh` carries the identical semantic
# at its own parser: `--no-fold` is legal only where a fold would otherwise run,
# which in both scripts is the bank.
#
# `--on-boxes N` IS LIFTED HERE FOR THE SAME REASON AND REFUSED THE SAME WAY.
# It takes a VALUE, which is the one difference: the loop below walks exactly
# the original argument count, and each argument is either taken out or rotated
# to the tail, so at iteration `i` the head of the list is original argument
# `i+1` — which is how `--on-boxes` can consume the next one. An `--on-boxes`
# with nothing after it is a refusal rather than an empty count.
NO_FOLD=0
ON_BOXES=""
#: WHERE THE SECOND WHOLE PASS COMES FROM on a `--bank --on-boxes` run: the
#: acceptance box this bank launches (the default, and the only source before
#: the nightly existed), or the latest nightly's record (ADR gate-1 as re-ruled:
#: the leak proof goes nightly and is never silent). Lifted like `--on-boxes`,
#: for the same reason: it takes a value, and `--bank` counts its arguments.
LEAK_PROOF=""
#: `--proof`'s own options, parsed in its arm below.
PROOF_MODE=0
PROOF_OUT=""
PROOF_SEED=""
PROOF_WORKERS=""
PROOF_WHERE="acceptance"
PROOF_RUN="0"
PROOF_ATTEMPT="0"
#: THE FLOOR, AND IT IS A RULE RATHER THAN A ROUND NUMBER. Below five boxes one
#: unit of the gate would have no box at all (the criteria's § 1: N = 3 + P + S
#: over today's five units). It is checked twice on purpose and neither check is
#: the other's copy: THIS one is syntactic and costs nothing, so a typo refuses
#: before the fold and before anything is launched; the DERIVED one below reads
#: `--list-legs` and refuses when N is short of the units that listing actually
#: has, which is the check that stays right when a unit is added.
ON_BOXES_FLOOR=5
#: HOW LONG THE ONE DETACH RETRY WAITS. `up` returns on the SSM agent's
#: `Online`, and the SSH tunnel is a few seconds behind it; a `leg` fired in
#: that window comes back with ssh's own 255 and an empty log. Fifteen seconds
#: is longer than that gap has been measured to be and short enough that a box
#: which is genuinely unreachable is still said so in one breath.
BANK_DETACH_RETRY_SECONDS="${DJB_BANK_DETACH_RETRY_SECONDS:-15}"
#: THE LIFETIME EVERY BANK BOX CARRIES, and it is the belt under a SIGKILL.
#: The teardown is a trap and no shell covers a SIGKILL: a measured killed bank
#: (`boxbank-17-killed.log`) shows the trap firing and dying with the Mac, and
#: what was left underneath it was the image's own 4 h ceiling and 30 m idle
#: reaper — enough for the bill, not for promptness. One hour is comfortably
#: above the longest leg measured (~21 min).
#:
#: AND THE IDLE MINUTES ARE THE IMAGE'S OWN THIRTY, NOT SOMETHING SHORTER. The
#: box's idle clock starts when its LEG EXITS — `idle_reaper.sh` watches for a
#: running gate and finds none — and a finished shard then sits there while the
#: bank waits on the slowest one. So the idle ceiling is not "above the longest
#: gap between processes"; it has to be above the WHOLE REMAINING WALL OF THE
#: BANK, because everything after a shard's leg (its fetch, the harvest, the
#: image, the `down`) happens on a box that has been idle since. Ten minutes
#: reaped a two-minute pytest shard out from under a twenty-minute selftest and
#: cost the bank a log it could not re-fetch.
BANK_BOX_TTL_HOURS="${DJB_BANK_BOX_TTL_HOURS:-1}"
BANK_BOX_IDLE_MINUTES="${DJB_BANK_BOX_IDLE_MINUTES:-30}"
#: THE WORKER COUNT THE ACCEPTANCE BOX'S TWO PASSES RUN UNDER, spelled once
#: because it is spelled twice in the remote command and a third time in the
#: replay line a red pass prints. A replay that named a different `-n` would
#: be a command that does not reproduce what was measured.
BANK_PROOF_WORKERS="${DJB_BANK_PROOF_WORKERS:-16}"
_pm_push_total=$#
_pm_push_i=0
while [ "$_pm_push_i" -lt "$_pm_push_total" ]; do
    _pm_push_arg="$1"
    shift
    case "$_pm_push_arg" in
    --no-fold) NO_FOLD=1 ;;
    --on-boxes)
        [ "$_pm_push_i" -lt "$((_pm_push_total - 1))" ] ||
            die "--on-boxes takes a box count: ./scripts/pm_push.sh --bank --on-boxes 8"
        ON_BOXES="$1"
        shift
        _pm_push_i=$((_pm_push_i + 1))
        ;;
    --leak-proof)
        [ "$_pm_push_i" -lt "$((_pm_push_total - 1))" ] ||
            die "--leak-proof takes a source, nightly or acceptance: ./scripts/pm_push.sh --bank --on-boxes 8 --leak-proof nightly"
        LEAK_PROOF="$1"
        shift
        _pm_push_i=$((_pm_push_i + 1))
        ;;
    *) set -- ${@+"$@"} "$_pm_push_arg" ;;
    esac
    _pm_push_i=$((_pm_push_i + 1))
done
unset _pm_push_arg _pm_push_total _pm_push_i

case "${1:-}" in
--dry-run)
    DRY_RUN=1
    SHA_ARG=""
    ;;
--bank)
    # THE RITUAL FULL GATE, RUN BEFORE THE PUSH RATHER THAN INSIDE IT. The
    # pre-push hook already runs the same gate when the tree has no verdict —
    # this flag moves that ~8 minutes in front of the operator who asked for
    # it, where it can be watched and where a red one is a decision rather
    # than a surprise. It was written up in this file's footer for a cycle
    # with no code behind it; a comment block is not a flag.
    #
    # IT TAKES NO COMMIT, and that is the whole of how it stays honest. A bank
    # is a claim about a TREE: `check.sh` keys its verdict on the working tree
    # it measures here, and the pre-push hook consults the ledger with the same
    # key. Measuring this checkout and then pushing some other commit would
    # vouch for a tree the push does not carry — so the combination is refused
    # at the argument rather than reasoned about later, and `--bank` means HEAD
    # by construction. (The first draft of this flag accepted the pair and
    # compared them below; that guard could never fire, because `$#` is capped
    # at one. An unreachable refusal is worse than no refusal — it reads like
    # cover.)
    [ "$#" -eq 1 ] ||
        die "--bank measures THIS checkout's tree, so it pushes THIS checkout's HEAD and takes no commit argument. Got: $*"
    DRY_RUN=0
    SHA_ARG=""
    BANK=1
    ;;
--pr)
    # THE TRAIN'S PUSH. It takes no commit for `--bank`'s reason: the intent
    # row it writes names THIS checkout's tree, and the push carries HEAD.
    [ "$#" -eq 1 ] ||
        die "--pr pushes THIS checkout's train branch, so it takes no commit argument. Got: $*"
    DRY_RUN=0
    SHA_ARG=""
    PR_MODE=1
    ;;
--ci-verdict)
    # THE READER. An optional run id; without one, the latest completed run of
    # the CI workflow on this checkout's branch is asked for.
    [ "$#" -le 2 ] ||
        die "--ci-verdict takes at most one run id. Got: $*"
    CI_VERDICT_RUN="${2:-}"
    if [ -n "$CI_VERDICT_RUN" ] && ! [[ $CI_VERDICT_RUN =~ ^[1-9][0-9]*$ ]]; then
        die "--ci-verdict takes a run id (a decimal, as gh prints it); got '${CI_VERDICT_RUN}'."
    fi
    set -- --ci-verdict
    DRY_RUN=0
    SHA_ARG=""
    CI_VERDICT_MODE=1
    ;;
--proof)
    # THE LEAK PROOF, RUN HERE. Its options are its own and parsed now, so the
    # one-commit rule below sees only the mode word.
    shift
    while [ "$#" -gt 0 ]; do
        case "$1" in
        --out | --seed | --workers | --where | --run | --attempt)
            [ "$#" -ge 2 ] || die "--proof ${1} takes a value."
            case "$1" in
            --out) PROOF_OUT="$2" ;;
            --seed) PROOF_SEED="$2" ;;
            --workers) PROOF_WORKERS="$2" ;;
            --where) PROOF_WHERE="$2" ;;
            --run) PROOF_RUN="$2" ;;
            --attempt) PROOF_ATTEMPT="$2" ;;
            esac
            shift 2
            ;;
        *) die "--proof takes --out, --seed, --workers, --where, --run and --attempt; got '${1}'." ;;
        esac
    done
    set -- --proof
    DRY_RUN=0
    SHA_ARG=""
    PROOF_MODE=1
    ;;
-h | --help)
    # THE USAGE BLOCK BY ITS OWN FIRST AND NEXT HEADINGS, never by line
    # number: the bash belt was prepended above it once, and a `2,8p` then
    # printed the belt's comment as this file's help for a cycle.
    awk '/^# Pin the pm-push worktree/ { p = 1 } /^# WHY THIS EXISTS/ { exit } p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
-*)
    die "unknown flag ${1}. Run $0 --help."
    ;;
*)
    DRY_RUN=0
    SHA_ARG="${1:-}"
    ;;
esac
[ "$#" -le 1 ] || die "one commit at most; got: $*"

# The never-silent half of the lift above. A flag that was accepted and did
# nothing is the defect; a flag that is refused with its reason is not.
if [ "$NO_FOLD" = "1" ] && [ "$BANK" != "1" ] && [ "$PR_MODE" != "1" ]; then
    die "--no-fold is only meaningful with --bank or --pr, and this is neither.
   The fold runs at the BANK: it regenerates the derived files and commits them
   BEFORE the gate measures the tree, so that the verdict vouches for the tree
   the push carries. A plain push pins and pushes a commit that already exists
   and regenerates nothing, so there is nothing here for --no-fold to skip.
   Accepting it silently would be a flag that did nothing with no line printed.
   scripts/pm_merge.sh refuses the same combination (it has no --pr)."
fi

# --on-boxes, THE SAME NEVER-SILENT CLAUSE, AND BEFORE ANYTHING LAUNCHES.
# `--on-boxes` says WHERE the bank measures. Outside a bank there is nothing
# measuring, so the flag would be a word the operator typed that changed
# nothing — the class `--no-fold` above refuses, in the same place and for the
# same reason.
if [ -n "$ON_BOXES" ] && [ "$BANK" != "1" ]; then
    die "--on-boxes is only meaningful with --bank, and this is not a --bank run.
   --on-boxes says WHERE the bank's full gate runs: one unit of it per verifier
   box instead of every unit on this laptop. A plain push measures nothing here
   — the pre-push hook consults the ledger and runs the gate itself when there
   is no verdict — so there is nothing for --on-boxes to place.
   Accepting it silently would be a flag that did nothing with no line printed.
   The form is: ./scripts/pm_push.sh --bank --on-boxes ${ON_BOXES}"
fi
# --leak-proof, THE SAME CLAUSE ONE LEVEL IN. It says where a SHARDED bank's
# second whole pass comes from, so outside `--bank --on-boxes` there is no
# second pass for it to source; and a source this file does not know is a
# word that would otherwise select the default silently.
if [ -n "$LEAK_PROOF" ]; then
    if [ "$BANK" != "1" ] || [ -z "$ON_BOXES" ]; then
        die "--leak-proof is only meaningful with --bank --on-boxes N, and this is not one.
   It says where the sharded bank's second whole pass comes from — the
   acceptance box it launches, or the latest nightly's record. Anywhere else
   there is no one-pass suite for a proof to stand behind.
   The form is: ./scripts/pm_push.sh --bank --on-boxes 8 --leak-proof ${LEAK_PROOF}"
    fi
    case "$LEAK_PROOF" in
    nightly | acceptance) ;;
    *)
        die "--leak-proof takes nightly or acceptance, got '${LEAK_PROOF}'.
   Nothing was folded, nothing was launched and nothing was pushed."
        ;;
    esac
fi
if [ -n "$ON_BOXES" ]; then
    case "$ON_BOXES" in
    '' | *[!0-9]*)
        die "--on-boxes takes a whole number of boxes, got '${ON_BOXES}'.
   Nothing was folded, nothing was launched and nothing was pushed."
        ;;
    esac
    [ "$ON_BOXES" -ge "$ON_BOXES_FLOOR" ] ||
        die "--on-boxes ${ON_BOXES} is below the floor of ${ON_BOXES_FLOOR}.
   THE RULE: one \`--leg\` per box, N = 3 + P + S over the gate's own units —
   the indivisible units one box each, pytest-x2 split P ways and selftest S
   ways. Below ${ON_BOXES_FLOOR} at least one unit would have NO box, and a bank
   that silently dropped a unit is a green that vouches for less than it says.
   ./scripts/check.sh --list-legs names the units; the floor this run would
   derive from that listing is checked again after the fold.
   Nothing was folded, nothing was launched and nothing was pushed."
fi

ROOT="$(git rev-parse --show-toplevel)" || die "not inside a git checkout"

# The commit to push, resolved to a full sha HERE, in the checkout the operator
# is standing in — not in pm-push, whose HEAD is exactly the thing that has been
# wrong before.
SHA="$(git -C "$ROOT" rev-parse --verify "${SHA_ARG:-HEAD}^{commit}" 2>/dev/null)" ||
    die "'${SHA_ARG:-HEAD}' is not a commit in $ROOT"

# =============================================================================
# THE CI ROAD — --pr AND --ci-verdict (the `ci:` verdict)
# =============================================================================
#
# THE MERGE ROAD, IN FOUR COMMANDS, and each one is somebody else's check:
#
#   ./scripts/pm_push.sh --pr                   push this pm/* train branch
#   gh pr create --base main --head pm/<train>  (once) — CI measures the PR
#   ./scripts/pm_push.sh --ci-verdict [<run>]   read the run's record, bank the row
#   ./scripts/pm_push.sh                        fast-forward main to the measured commit
#
# The PR's CI run is the ONE measurement: every unit of the gate, the suite at
# one pass, one record (`scripts/gate_ledger.sh`, the CI VERDICT section, owns
# its grammar, its fetch and its judge — this file only calls them). The last
# command is the ordinary push: the pre-push hook honours the `ci:` row by the
# tree key exactly as it honours a bank's, and a merge commit over a moved
# main is a new tree with no row, measured. `pm_merge.sh` is unchanged — it
# builds the train; the train's measurement is the PR run.
#
# NEITHER MODE PINS pm-push, and both sit here — after the commit is resolved
# and before the pm-push worktree is looked for — because neither needs it:
# `--pr` pushes the checkout's own branch, and `--ci-verdict` pushes nothing.

#: The branch prefix a train branch carries — the one namespace `--pr` pushes
#: and the one the pre-push hook honours an intent for.
PR_BRANCH_PREFIX="pm/"

# pr_main — `--pr`. Exit 2 on every refusal, before the intent row and before
# the push; otherwise git's own status (the push is `exec`'d).
pr_main() {
    local branch tree fold_rc remote_sha
    branch="$(git -C "$ROOT" symbolic-ref -q --short HEAD 2>/dev/null || true)"
    case "$branch" in
    "${PR_BRANCH_PREFIX}"?*) ;;
    *)
        die "--pr pushes a TRAIN branch, and this checkout is on '${branch:-a detached HEAD}'.
   Only a ${PR_BRANCH_PREFIX}* branch rides the CI road: its pull request's run is the
   measurement, and main is reached by a fast-forward after --ci-verdict,
   never by this push. Make the train branch first: git switch -c ${PR_BRANCH_PREFIX}<train>"
        ;;
    esac
    if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
        echo "!! pm_push --pr: ${ROOT} has uncommitted changes." >&2
        git -C "$ROOT" status --short >&2
        echo "   The intent row names the tree CI is about to measure, and a dirty tree is" >&2
        echo "   bytes no commit carries. Commit or stash first." >&2
        echo "   Nothing was folded, nothing was written and nothing was pushed." >&2
        exit 2
    fi
    if [ -z "${DJB_GATE_SANCTION:-}" ] || ! [[ ${DJB_GATE_SANCTION} =~ ^[^:]+:\ .+$ ]]; then
        die "--pr pushes WITHOUT a local verdict, so it takes a typed sanction.
   got:  DJB_GATE_SANCTION='${DJB_GATE_SANCTION:-}'
   want: export DJB_GATE_SANCTION=\"<who>: <why>\" (the shape the full gate reads)
   It is printed in this header and written into the intent row."
    fi
    [ -r "$ROOT/scripts/gate_ledger.sh" ] ||
        die "no ${ROOT}/scripts/gate_ledger.sh — the intent row has no writer without it"
    # THE FOLD, AS THE BANK FOLDS: before the tree is named, so the pull
    # request's run measures the derived files the push carries. `--no-fold`
    # is honoured and says so.
    if [ "$NO_FOLD" = "1" ]; then
        echo "pm_push --pr: ** --no-fold — THE DERIVED FILES WERE NOT REGENERATED. **"
    else
        [ -x "$ROOT/scripts/pm_fold.sh" ] ||
            die "no executable fold at ${ROOT}/scripts/pm_fold.sh — pass --no-fold to push without one"
        echo "pm_push --pr: folding ${ROOT} before the push — ${ROOT}/scripts/pm_fold.sh"
        fold_rc=0
        "$ROOT/scripts/pm_fold.sh" || fold_rc=$?
        if [ "$fold_rc" != "0" ]; then
            echo "!! pm_push --pr: the fold exited ${fold_rc}. Read its output above." >&2
            echo "   Nothing was written and nothing was pushed." >&2
            exit "$fold_rc"
        fi
        SHA="$(git -C "$ROOT" rev-parse --verify "HEAD^{commit}")" ||
            die "could not re-read HEAD after the fold"
        if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
            echo "!! pm_push --pr: the fold left ${ROOT} dirty." >&2
            git -C "$ROOT" status --short >&2
            echo "   Nothing was written and nothing was pushed." >&2
            exit 2
        fi
    fi
    tree="$(cd "$ROOT" && . scripts/gate_ledger.sh && gate_measured_tree)" ||
        die "the measured tree of ${ROOT} could not be read — the intent row would name nothing"
    # NOTHING NEW, NOTHING PUSHED — AND EXIT 0 BEFORE THE HOOK EVER RUNS. A
    # push of a ref the remote already has at this commit hands the pre-push
    # hook NO refs on stdin, and a hook that reads no refs has no train branch
    # to honour an intent for: it fell through to a FULL LOCAL GATE, the most
    # expensive thing on the machine, for a push that moved nothing. So the
    # remote's own answer is asked first. A remote that cannot be asked is not
    # "up to date": the push below goes ahead and says what git says.
    remote_sha="$(git -C "$ROOT" ls-remote "$REMOTE" "refs/heads/${branch}" 2>/dev/null | awk 'NR == 1 { print $1 }')" || remote_sha=""
    if [ -n "$remote_sha" ] && [ "$remote_sha" = "$SHA" ]; then
        echo "pm_push --pr: ${REMOTE}/${branch} is already at ${SHA} — nothing to push."
        echo "  No intent row was written and no push was made (so no hook and no gate ran)."
        echo "  The pull request's run for this commit is the measurement; read it with"
        echo "  ./scripts/pm_push.sh --ci-verdict [<run id>]"
        exit 0
    fi
    echo "pm_push --pr: pushing ${branch} to ${REMOTE} with NO local verdict — its pull request's CI run is the measurement"
    echo "  sanction      ${DJB_GATE_SANCTION}"
    echo "  branch        ${branch}"
    echo "  commit        ${SHA}  $(git -C "$ROOT" log -1 --format=%s "$SHA")"
    echo "  tree          ${tree} (measured)"
    if ! (cd "$ROOT" && . scripts/gate_ledger.sh &&
        gate_ledger_intent_record "$tree" "$SHA" "$branch" "$DJB_GATE_SANCTION"); then
        die "the intent row could not be written — a push nobody can account for is not a push this script makes"
    fi
    echo "  intent        intent=ci run=pending tree=${tree} (the verdict ledger)"
    echo "  next          gh pr create --base ${TARGET_BRANCH} --head ${branch}   (once; CI measures the pull request)"
    echo "                ./scripts/pm_push.sh --ci-verdict [<run id>]   (after the run completes; banks the ci: row)"
    echo "                ./scripts/pm_push.sh   (on ${branch}: fast-forwards ${TARGET_BRANCH} to the measured commit)"
    echo "pm_push: pushing ${SHA} -> ${REMOTE}/${branch}"
    # THE ONE PUSH THIS ROAD MAKES, AND THE ONE PLACE THE INTENT IS SAID. The
    # pre-push hook honours the intent row above only with this variable in
    # its environment AND every pushed ref under refs/heads/pm/ — and the
    # refspec below names the train branch and nothing else.
    export DJB_PUSH_INTENT=ci
    exec git -C "$ROOT" push "$REMOTE" "${SHA}:refs/heads/${branch}"
}

# ci_verdict_refuse <why> — the one refusal shape: exit 2, no row.
# The footer is TRUE in both of its forms: "No row was written" everywhere a
# row never reached the ledger or was taken back out, and the other sentence
# on the one path where a refused row could not be removed.
CI_VERDICT_ROW_STANDS=0
ci_verdict_refuse() {
    echo "!! pm_push --ci-verdict: THE CI RECORD CANNOT BE BANKED: $1" >&2
    if [ "$CI_VERDICT_ROW_STANDS" = "1" ]; then
        echo "   A REFUSED ROW STANDS in the ledger (named above) and nothing was pushed." >&2
    else
        echo "   No row was written and nothing was pushed. A reader that could not" >&2
    fi
    echo "   vouch for the record banks nothing (exit 2)." >&2
    exit 2
}

# ci_verdict_main — `--ci-verdict [<run id>]`. Exit 0 with the `ci:` row
# banked and honoured, or exit 2 (ci_verdict_refuse) with nothing written.
ci_verdict_main() {
    local sink runid listrc=0 branch attempt rc listing expanded line ledger before added
    command -v gh >/dev/null 2>&1 ||
        ci_verdict_refuse "no \`gh\` on PATH — the record is a workflow artifact and \`gh\` is its one reader."
    [ -r "$ROOT/scripts/gate_ledger.sh" ] ||
        ci_verdict_refuse "no ${ROOT}/scripts/gate_ledger.sh — the row has no writer without it."
    # shellcheck source=scripts/gate_ledger.sh
    . "$ROOT/scripts/gate_ledger.sh"
    sink="$(mktemp -d "${TMPDIR:-/tmp}/djb-ci-verdict.XXXXXX")" ||
        ci_verdict_refuse "could not make a directory to download the record into."
    echo "pm_push --ci-verdict: reading the CI run's ${GATE_CI_ARTIFACT} record (logs: ${sink})"
    runid="$CI_VERDICT_RUN"
    if [ -z "$runid" ]; then
        branch="$(git -C "$ROOT" symbolic-ref -q --short HEAD 2>/dev/null || true)"
        [ -n "$branch" ] ||
            ci_verdict_refuse "no run id was given and this checkout is on a detached HEAD — there is no branch to ask \`gh\` about."
        runid="$(cd "$ROOT" && gh run list --workflow "$GATE_CI_WORKFLOW" --branch "$branch" \
            --status completed --limit 1 --json databaseId --jq '.[0].databaseId' \
            2>"${sink}/gh-run-list.err" </dev/null)" || listrc=$?
        [ "$listrc" = "0" ] ||
            ci_verdict_refuse "\`gh run list\` did not answer (exit ${listrc}; ${sink}/gh-run-list.err) — a reader that could not look cannot say which run measured this branch."
        [[ $runid =~ ^[1-9][0-9]*$ ]] ||
            ci_verdict_refuse "no completed run of ${GATE_CI_WORKFLOW} on ${branch} (gh answered '${runid}') — nothing has measured this branch yet."
        echo "  run      ${runid} (the latest completed ${GATE_CI_WORKFLOW} run on ${branch})"
    else
        echo "  run      ${runid} (given)"
    fi
    rc=0
    attempt="$(cd "$ROOT" && gate_ci_fetch "$runid" "$sink")" || rc=$?
    [ "$rc" = "0" ] || ci_verdict_refuse "${attempt}."
    echo "  attempt  ${attempt} (the latest; its artifact is $(gate_ci_artifact_name "$attempt"))"
    line="$(awk 'NF { print; exit }' "${sink}/record-${runid}/${GATE_CI_RECORD}")"
    echo "  record   ${line:-<empty>}"
    # THE LEGS are read against this checkout's listing, REDIRECTED to a file
    # and never captured through a pipe (the gate refuses a piped stdout).
    listing="${sink}/listlegs.tsv"
    (cd "$ROOT" && gate_ci_listing "$listing") ||
        ci_verdict_refuse "./scripts/check.sh --list-legs would not answer — the record's units cannot be read without it."
    rc=0
    expanded="$(cd "$ROOT" && gate_ci_record_judge "$line" "$runid" "$attempt" "$listing")" || rc=$?
    [ "$rc" = "0" ] || ci_verdict_refuse "${expanded}."
    gate_ci_record_parse "$line" ||
        ci_verdict_refuse "the record parsed in the judge and not here (${GATE_CI_REC_WHY}) — the two readers disagree."
    DJB_GATE_CALLER=pm-bank
    GATE_RUN_SANCTION="ci-verdict run=${runid} attempt=${attempt} commit=${GATE_CI_REC_COMMIT:0:12} shards=${GATE_CI_REC_SHARDS}"
    GATE_RUN_LEAK_PROOF="ci:${runid} rc=0"
    export DJB_GATE_CALLER
    # THE LEDGER'S LENGTH BEFORE THE WRITE, so a row the lookup then refuses
    # can be taken back out — exactly that row and nothing else (below).
    ledger="$(cd "$ROOT" && gate_ledger_path)" ||
        ci_verdict_refuse "the verdict ledger's path would not resolve — there is nowhere to write the row."
    before=0
    [ ! -f "$ledger" ] || before="$(wc -c <"$ledger" | tr -d ' ')"
    if ! (cd "$ROOT" && gate_ledger_record "$GATE_CI_REC_TREE" "$expanded"); then
        ci_verdict_refuse "the verdict ledger could not be written — a green nobody can read is not a verdict."
    fi
    if ! (cd "$ROOT" && gate_ledger_lookup "$GATE_CI_REC_TREE" >/dev/null); then
        # A ROW THE LEDGER'S OWN READER REFUSES IS TAKEN BACK OUT, NOT LEFT.
        # The lookup reads the NEWEST row for a tree (`tail -1`), so a refused
        # row left standing would shadow an older verdict that still holds for
        # the same tree: the next consult would refuse a tree that has one.
        # Removing it puts the ledger back to the bytes it held before this
        # run. THE ROW IS IDENTIFIED BY POSITION AND CONTENT: the bytes past
        # the length read before the write must be exactly ONE line, starting
        # `<schema> <tree> full ` and ending `leak-proof=ci:<run> rc=0`, and
        # only then is the file cut back to that length. Anything else there
        # (another writer's line landed after ours) is left alone and said.
        added="$(tail -c +"$((before + 1))" "$ledger" 2>/dev/null || true)"
        case "$added" in
        *$'\n'*) added="<more than one line>" ;;
        esac
        case "$added" in
        "${GATE_LEDGER_SCHEMA} ${GATE_CI_REC_TREE} full "*" leak-proof=${GATE_RUN_LEAK_PROOF}")
            # WRITE-THEN-`mv`, BESIDE THE LEDGER. The ledger is one file every
            # worktree of the primary appends to; truncating it in place
            # (`cat >`) opens a window in which a concurrent append lands in a
            # file about to be overwritten, or a reader sees it half-written.
            # A rename in one directory is atomic: the ledger is the old bytes
            # or the new ones, never neither.
            if head -c "$before" "$ledger" >"${ledger}.rewrite.$$" &&
                mv -f "${ledger}.rewrite.$$" "$ledger"; then
                ci_verdict_refuse "the row was written and gate_ledger_lookup refuses it (its note is above) — the row was REMOVED, and the ledger holds exactly what it held before this run."
            fi
            rm -f "${ledger}.rewrite.$$"
            CI_VERDICT_ROW_STANDS=1
            ci_verdict_refuse "the row was written, gate_ledger_lookup refuses it, and it could not be removed from ${ledger} — it STANDS there as its tree's newest row; remove that last line by hand."
            ;;
        esac
        CI_VERDICT_ROW_STANDS=1
        ci_verdict_refuse "the row was written and gate_ledger_lookup refuses it, and the ledger's tail past this run's write is not exactly that one row (${added:0:120}) — nothing was removed; the refused row STANDS in ${ledger}."
    fi
    echo "pm_push --ci-verdict: verdict banked for tree ${GATE_CI_REC_TREE}"
    echo "  caller=pm-bank sanction=${GATE_RUN_SANCTION}"
    echo "  legs=${expanded}"
    echo "  leak-proof=${GATE_RUN_LEAK_PROOF} (the second whole pass is the nightly's)"
    echo "  next     ./scripts/pm_push.sh   (fast-forwards ${TARGET_BRANCH} to ${GATE_CI_REC_COMMIT:0:12}; the hook honours this row)"
    exit 0
}

# =============================================================================
# --proof — THE LEAK PROOF, ONE FUNCTION, TWO CALLERS
# =============================================================================
#
# WHAT IT IS. The whole suite twice under ONE seed — pass 1 with per-test
# coverage contexts, the test-impact map inverted out of it, pass 2 plain — and
# ONE record, `leak_proof.txt`, in the grammar `scripts/gate_ledger.sh` owns
# (`gate_nightly_line` writes it, `gate_nightly_read` reads it):
#
#   schema=leak-proof/1 at= commit= tree= seed= pass1= pass2= map= rc= run=
#     attempt= where=
#
# TWO CALLERS AND ONE BODY. `.github/workflows/nightly-proof.yml` runs
# `./scripts/pm_push.sh --proof --where nightly --run <id> --attempt <n>` on a
# runner, and a bank's acceptance box runs `./scripts/pm_push.sh --proof`
# through `bank_boxes_acceptance_remote` — so the box's command is a CALL of
# this function, never a second spelling of it, and the two write the same
# field set by construction. (Before this, the box's body was a one-line string
# of shell and nothing else could run it.)
#
# THE CLAIM AND THE MEASUREMENT SEPARATE HERE, as they always have on the box:
# `pass1=`/`pass2=` and `rc=` are the claim; `map=` is a measurement and
# decides nothing. The map is written only after a green pass 1 (a map
# inverted out of a coverage database a red pass abandoned is half a run), and
# it is written OUTSIDE THE CHECKOUT, into `--out`: a measurement may not dirty
# the tree it measured (`scripts/test_impact.json` is tracked, and a box whose
# tree moved under the image step refused to build — the header of
# `bank_boxes_acceptance_remote` has the whole story).
#
# EXIT: 0 the proof is green · 1 a pass is red · 2 could not look (the
# collection failed, or no record could be written). The record is written on
# 0 and 1 and on a collection that failed, so the nightly publishes a record
# whatever happened, and a bank reads a status rather than an absence.
#
# WHAT IT DOES NOT COVER: the environment — the stack the suite dials is the
# caller's (the workflow's compose step, the box's image); what the suite
# covers; a test whose leak needs more than two passes to show.

# leak_proof_verdict <pass1> <pass2> <seed> <workers> — ONE line naming what
# the two statuses mean and the command that replays them.
#
# A PASS-2-ONLY RED NAMES ITS CANDIDATES, NEVER ONE CAUSE. One seed fixes the
# collection order, and it is still not the whole of what differs between the
# two passes: pass 2 runs later (the wall clock — a date, an expiry, a
# timezone), and xdist's scheduling hands tests to workers in an order the seed
# does not pin (test order). State pass 1 left behind is the likeliest and the
# one the proof exists for; a line that said it was the ONLY one would name a
# cause nobody proved.
leak_proof_verdict() {
    local p1="$1" p2="$2" seed="$3" workers="$4"
    if [ "$p1" = "0" ] && [ "$p2" = "0" ]; then
        printf 'leak proof: GREEN - pass 1 and pass 2 both passed under seed %s\n' "$seed"
    elif [ "$p1" = "0" ]; then
        printf 'pass 2 red after a green pass 1 — candidate causes: state pass 1 left behind, the wall clock, test order; replay: ./scripts/pm_push.sh --proof --seed %s --workers %s\n' \
            "$seed" "$workers"
    elif [ "$p1" = "-" ]; then
        printf 'leak proof: COULD NOT LOOK - the collection failed and neither pass ran (seed %s)\n' "$seed"
    else
        printf 'pass 1 red (exit %s; pass 2 exit %s) — the suite is red before a second pass could say anything about a leak; replay: ./scripts/test.sh -n %s --randomly-seed=%s\n' \
            "$p1" "$p2" "$workers" "$seed"
    fi
}

proof_main() {
    local out seed workers where run attempt commit tree at line rc
    local t0 t1 t2 p1="-" p2="-" map="-" collect_rc=0
    [ -r "$ROOT/scripts/gate_ledger.sh" ] ||
        die "no ${ROOT}/scripts/gate_ledger.sh — the leak-proof record has no writer without it"
    # shellcheck source=scripts/gate_ledger.sh
    . "$ROOT/scripts/gate_ledger.sh"
    workers="${PROOF_WORKERS:-$BANK_PROOF_WORKERS}"
    [[ $workers =~ ^[1-9][0-9]*$ ]] || die "--proof --workers takes a whole number above zero, got '${workers}'."
    where="$PROOF_WHERE"
    case "$where" in nightly | acceptance) ;; *) die "--proof --where takes nightly or acceptance, got '${where}'." ;; esac
    run="$PROOF_RUN"
    attempt="$PROOF_ATTEMPT"
    [[ $run =~ ^(0|[1-9][0-9]*)$ ]] && [[ $attempt =~ ^(0|[1-9][0-9]*)$ ]] ||
        die "--proof --run and --attempt take decimals (the workflow's run id and attempt), got '${run}' '${attempt}'."
    if [ "$where" = "nightly" ] && { [ "$run" = "0" ] || [ "$attempt" = "0" ]; }; then
        die "--proof --where nightly names the workflow run that is writing it: --run \${{ github.run_id }} --attempt \${{ github.run_attempt }}."
    fi
    # ONE SEED FOR BOTH PASSES, minted here when none is given. That is what
    # makes this a leak proof rather than two runs of the suite, and a given
    # seed is what makes the replay line below a replay.
    seed="${PROOF_SEED:-$((RANDOM * 32768 + RANDOM))}"
    [[ $seed =~ ^[0-9]+$ ]] || die "--proof --seed takes a decimal, got '${seed}'."
    if [ -n "$PROOF_OUT" ]; then
        out="$PROOF_OUT"
        mkdir -p "$out" || die "could not make --out ${out}"
        out="$(cd "$out" && pwd -P)" || die "could not resolve --out ${PROOF_OUT}"
    else
        out="$(mktemp -d "${TMPDIR:-/tmp}/djb-leak-proof.XXXXXX")" || die "could not make a directory for the proof"
    fi
    case "$out/" in
    "$(cd "$ROOT" && pwd -P)/"*)
        die "--proof --out ${out} is inside ${ROOT}. A measurement may not dirty the tree it
   measured: the map and the record are written OUTSIDE the checkout, always."
        ;;
    esac
    commit="$(git -C "$ROOT" rev-parse --verify HEAD)" || die "could not read HEAD in ${ROOT}"
    tree="$(cd "$ROOT" && gate_measured_tree)" || die "could not read the measured tree of ${ROOT}"
    rm -f "${out}/impact.coverage" "${out}/impact.coverage."* "${out}/${GATE_NIGHTLY_RECORD}" \
        "${out}/test_impact.json" "${out}/map.log"
    echo "pm_push --proof: the whole suite twice under one seed, and the map (where=${where})"
    echo "  checkout      ${ROOT}"
    echo "  commit        ${commit}"
    echo "  tree          ${tree} (measured)"
    echo "  seed          ${seed}"
    echo "  workers       ${workers}"
    echo "  out           ${out}"
    t0=$(date +%s)
    (cd "$ROOT" && ./scripts/test.sh --collect-only -q -p no:randomly) >"${out}/collected.txt" 2>&1 || collect_rc=$?
    t1=$t0
    t2=$t0
    if [ "$collect_rc" != "0" ]; then
        rc=2
        echo "!! pm_push --proof: the collection exited ${collect_rc} (${out}/collected.txt); neither pass ran." >&2
    else
        p1=0
        (cd "$ROOT" && COVERAGE_FILE="${out}/impact.coverage" ./scripts/test.sh -n "$workers" \
            --randomly-seed="$seed" --cov=apps --cov=config --cov-context=test --cov-report=) \
            >"${out}/pass1.log" 2>&1 || p1=$?
        t1=$(date +%s)
        map=2
        if [ "$p1" = "0" ]; then
            map=0
            (cd "$ROOT" && .venv/bin/python scripts/test_impact.py write --coverage "${out}/impact.coverage" \
                --collected "${out}/collected.txt" --root . --out "${out}/test_impact.json") \
                >"${out}/map.log" 2>&1 || map=$?
        fi
        p2=0
        (cd "$ROOT" && ./scripts/test.sh -n "$workers" --randomly-seed="$seed") \
            >"${out}/pass2.log" 2>&1 || p2=$?
        t2=$(date +%s)
        rc=1
        [ "$p1" != "0" ] || [ "$p2" != "0" ] || rc=0
    fi
    at="$(date -u +%Y%m%dT%H%M%SZ)"
    line="$(gate_nightly_line "$at" "$commit" "$tree" "$seed" "$p1" "$p2" "$map" "$rc" "$run" "$attempt" "$where")" ||
        die "the leak-proof record would not parse (above) — none was written, and a proof with no record proves nothing."
    printf '%s\n' "$line" >"${out}/${GATE_NIGHTLY_RECORD}"
    # THE SUMMARY LINE A BANK READS OUT OF THE BOX'S OWN OUTPUT (`^acceptance:
    # pass1`), prefixed with where the proof ran.
    echo "${where}: pass1 (contexts) $((t1 - t0))s · pass2 (plain) $((t2 - t1))s rc1=${p1} rc2=${p2} map=${map}"
    cat "${out}/${GATE_NIGHTLY_RECORD}"
    [ ! -s "${out}/map.log" ] || cat "${out}/map.log"
    leak_proof_verdict "$p1" "$p2" "$seed" "$workers"
    echo "  record        ${out}/${GATE_NIGHTLY_RECORD}"
    [ ! -s "${out}/test_impact.json" ] || echo "  map           ${out}/test_impact.json"
    exit "$rc"
}

if [ "$PROOF_MODE" = "1" ]; then
    proof_main
fi

if [ "$PR_MODE" = "1" ]; then
    pr_main
fi
if [ "$CI_VERDICT_MODE" = "1" ]; then
    ci_verdict_main
fi

# Where pm-push is, asked rather than assumed.
PM_PUSH=""
while IFS= read -r line; do
    case "$line" in
    "worktree "*)
        candidate="${line#worktree }"
        case "$(basename "$candidate")" in
        "$WORKTREE_NAME") PM_PUSH="$candidate" ;;
        esac
        ;;
    esac
done < <(git -C "$ROOT" worktree list --porcelain)
[ -n "$PM_PUSH" ] ||
    die "no worktree named '${WORKTREE_NAME}' in git worktree list. Create one (git worktree add --detach .claude/worktrees/${WORKTREE_NAME}) or name another with DJB_PUSH_WORKTREE."
[ -d "$PM_PUSH" ] || die "git worktree list names ${PM_PUSH}, which is not a directory"

# A dirty pm-push is somebody's unsaved work, and pinning would destroy it.
# This is the one thing the incident did NOT do and could have.
if [ -n "$(git -C "$PM_PUSH" status --porcelain)" ]; then
    echo "!! pm_push: ${PM_PUSH} has uncommitted changes." >&2
    git -C "$PM_PUSH" status --short >&2
    echo "   Pinning it would throw them away. Deal with them first; this script" >&2
    echo "   will not decide that for you." >&2
    exit 2
fi

# =============================================================================
# --on-boxes N — ONE UNIT OF THE GATE PER VERIFIER BOX
# =============================================================================
#
# WHAT IT MOVES, AND WHY THAT IS THE WHOLE POINT. A `--bank` on this laptop
# takes the machine-wide lease and EVERY pytest slot for its whole run, so the
# builders' `--loop`s queue behind it — the bank is the one thing on this box
# that stops everybody else. `--on-boxes N` runs the SAME units on N throwaway
# verifier boxes instead: the Mac folds, reads `--list-legs`, launches, waits,
# fetches every shard's log and COMPOSES one verdict row for the post-fold tree.
# It measures nothing itself, so it takes no lease and no slot, and the wall
# the PM waits is the slowest shard rather than the sum of all of them.
#
# THE PLAN IS DERIVED, NEVER TYPED. `./scripts/check.sh --list-legs` is the
# authority on what a unit is and which units take a `k/N` (column 3), exactly
# as `.github/workflows/ci.yml` derives its matrix from the same listing. The
# split rule is one sentence with its arithmetic: the indivisible units take one
# box each; of the N-capable ones, every unit but the last takes two shards once
# there are seven boxes or more and one below that, and the LAST takes every box
# that is left. A bin-packer over measured leg durations was rejected: a second
# durations concept for four small units buys about ninety seconds, and the
# measurement row is what tells the PM which N to type.
#
# THE ROW HAS ONE WRITER, AND IT IS `gate_ledger_record`. There is no second
# grammar for a verdict line and no second place a full row is written — the
# composition is the Mac's arithmetic over N logs, and the line it produces is
# the ordinary full row with the sanction naming how it was earned
# (`sanction=push-wall boxes=N shards=<labels>`), so the hook honours it through
# exactly the lookup it already does and every existing reader still parses it.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * THE TUNNEL, THE SPOT MARKET AND THE BOX ITSELF. Everything past
#     `scripts/verifier_box.sh`'s argv is that wrapper's and its drive's. This
#     file asserts the seam — the arguments, the order, the ids — and reads what
#     comes back; a shard whose gate LIED is invisible here exactly as it is to
#     CI, whose per-runner `--leg` is the same authority.
#   * A BOX LAUNCHED BY AN `up` THAT WAS STILL IN FLIGHT WHEN THE BANK WAS
#     KILLED. `up` returns after the launch, so the id reaches `boxes.tsv` only
#     once it has; a signal in that window leaves a box the teardown cannot
#     name. What is underneath it is the box's own `djb:expires` tag, its idle
#     reaper and `verifier_box.sh census` — the same three things that are
#     underneath a SIGKILL, and for the same reason.
#   * THE CROSS-SHARD IDEMPOTENCY NARROWING `docs/product/build-contract.md`
#     ALREADY DECLARES FOR CI. An on-box bank shards `pytest-x2` the same way,
#     so it inherits that blind spot, and the row's `shards=` field is what says
#     so to a reader afterwards.
#   * THE `terminate_or_by_hand` SENTENCE IS A COPY. `scripts/verifier_box.sh`
#     is an executable wrapper rather than a sourceable library, so the sentence
#     a failed `down` prints below is the same words rather than the same code;
#     nothing pins the two equal, and a reworded original would leave this one
#     reading as the wrapper's when it is not.

#: The wrapper, the exit sink and the ids the teardown has to take down. They
#: are globals because a TRAP reads them, and a trap has no arguments.
BANK_BOXES_VB=""
BANK_BOXES_SINK=""
BANK_BOXES_TSV=""
BANK_BOXES_WORKERS=""
# THE ACCEPTANCE BOX — the ninth machine, and the one that is NOT a shard.
# It measures the test-impact map and its answer is a FILE; it is in
# `boxes.tsv` so the teardown reaps it, and in nothing else.
BANK_BOXES_ACCEPT_ID=""
BANK_BOXES_ACCEPT_NOTE=""
# THE ZONE RING, READ ONCE FROM THE WRAPPER AND NEVER TYPED. Spot capacity is
# a per-availability-zone fact, so a bank whose boxes all land in one zone
# loses all of them to one capacity event — the measured shape of a reclaimed
# wave. It is a global because the retry below reaches for it from outside the
# function that read it, and because two reads are two answers.
BANK_BOXES_ZONES=""
# THE PLAN FILE AND THE ACCEPTANCE RUN'S COORDINATES, for the same reason: the
# reclaim sweep re-launches, re-detaches and re-fetches, and it needs the same
# arguments the first attempt was given rather than a second composition of
# them.
BANK_BOXES_PLAN=""
BANK_BOXES_TREE8=""
BANK_BOXES_ARUNG=""
BANK_BOXES_ACMD=""
BANK_BOXES_ACCEPT_AZ=""

# bank_boxes_kill_workers — the bank's OWN children, by pid and nothing else.
# An `up` still in flight after the teardown has read `boxes.tsv` would land a
# box nobody is going to name, so the children go first and the census second.
bank_boxes_kill_workers() {
    local p
    for p in $BANK_BOXES_WORKERS; do
        kill -TERM "$p" 2>/dev/null || true
    done
    BANK_BOXES_WORKERS=""
}

# bank_boxes_down_all — `down` every id recorded, once. Exit 0 iff every one of
# them went down.
#
# THE LIST IS EMPTIED AS IT IS WALKED, which is what makes a second call a
# no-op: the green path takes the boxes down itself (this script `exec`s git at
# the end, and an `exec` never runs an EXIT trap), and the trap must not then
# terminate the same ids again.
bank_boxes_down_all() {
    local label id frc=0
    [ -n "$BANK_BOXES_TSV" ] && [ -f "$BANK_BOXES_TSV" ] || return 0
    while IFS='	' read -r label id; do
        [ -n "$id" ] || continue
        if "$BANK_BOXES_VB" down "$id" </dev/null; then
            continue
        fi
        frc=1
        # `terminate_or_by_hand`'s sentence (scripts/verifier_box.sh), copied
        # rather than sourced — see the header's last blind spot. What it owes
        # is the id, the command that takes the box down, and the command that
        # reads the FLEET back, because a call that failed may also have half
        # worked and this box is not necessarily the only one on the clock.
        echo "!! pm_push --bank --on-boxes: could not terminate ${id} (${label}) — IT IS STILL UP" >&2
        echo "   AND IT IS STILL BILLING, and nothing else is going to notice except its" >&2
        echo "   expiry tag. TAKE IT DOWN BY HAND:" >&2
        echo "     scripts/verifier_box.sh down ${id}" >&2
        echo "   then read the fleet back:" >&2
        echo "     scripts/verifier_box.sh census" >&2
    done <"$BANK_BOXES_TSV"
    : >"$BANK_BOXES_TSV"
    return "$frc"
}

# bank_boxes_teardown — EVERY way out of the bank after the first `up` takes the
# boxes with it: a green, a red, an exit 2, a Ctrl-C, a TERM.
#
# IT IS A TRAP AND NOT N CALL SITES, for `cmd_bake`'s reason one file over: N
# call sites are the N failures somebody thought of and the trap covers the
# N+1th. INT and TERM route through it by exiting. No shell covers a SIGKILL,
# and the box's own expiry tag and idle reaper are what sit under that.
#
# AND IT SPEAKS THROUGH ITS OWN DESCRIPTORS, fds 8 and 9, duplicated from the
# real stdout and stderr before anything is armed: a trap runs inside whatever
# redirection was in force where it FIRED, and this bank's phases redirect their
# children's output into the sink. The cost is two inherited duplicates of the
# operator's own terminal for the length of one bank, which is `cmd_bake`'s
# accepted cost and its argument.
bank_boxes_teardown() {
    local rc=$?
    set +e
    trap - EXIT
    {
        bank_boxes_kill_workers
        if [ -n "$BANK_BOXES_TSV" ] && [ -s "$BANK_BOXES_TSV" ]; then
            echo "!! pm_push --bank --on-boxes: the bank stopped (exit ${rc}) with boxes still up;" >&2
            echo "   taking them down so they cannot become a stale bill." >&2
            if ! bank_boxes_down_all; then
                # THE STATUS STAYS THE ORIGINAL FAILURE'S — `bake_teardown`'s
                # rule and its argument: the teardown is the cleanup and not the
                # verdict. The one substitution is the belt underneath it: a
                # teardown firing on a CLEAN exit with a box still up must not
                # report success over an orphan.
                [ "$rc" != "0" ] || rc=2
            fi
        fi
        if [ -n "$BANK_BOXES_SINK" ]; then
            echo "   the bank's logs are under ${BANK_BOXES_SINK}" >&2
        fi
    } >&8 2>&9
    exit "$rc"
}

# =============================================================================
# THE ZONE RING — read from the wrapper, spread over, and stepped on a reclaim
# =============================================================================
#
# WHY THE BANK CARES ABOUT ZONES AT ALL. A Spot reclaim is AWS taking capacity
# back in ONE availability zone, so N boxes in one zone is N boxes with one
# shared failure and a whole bank's work lost to it (the consumer lost five
# shards of nine to a single event). Spreading costs nothing — the boxes are
# in one VPC either way — and it turns a wave into at most a shard.
#
# AND THE RING IS THE WRAPPER'S, NEVER A LIST HERE. `verifier_box.sh zones`
# owns the question (it reads the security group's VPC and the subnets in it);
# a list typed in this file would be a second answer that goes stale the first
# time the account gains or loses a zone.

# bank_boxes_zones_read <wrapper> — the ring on stdout, one zone per line, or
# exit 2 having said why. An EMPTY answer is the same answer as a refusal: a
# ring of nothing is not a ring, and a bank that carried on would launch every
# box into whatever the subnet default happens to be — the single-zone shape
# this exists to end, silently.
bank_boxes_zones_read() {
    local vb="$1" out="$2" zrc=0
    # STDOUT ONLY. The ring is what is on stdout and the refusal is on stderr;
    # `2>&1` here would fold a wrapper's explanation into the zone list and
    # this bank would round-robin its boxes over an error message.
    "$vb" zones >"$out" 2>"${out}.err" </dev/null || zrc=$?
    if [ "$zrc" != "0" ]; then
        return 2
    fi
    grep -q . "$out" || return 2
    return 0
}

# bank_boxes_zone_at <zones> <index> — the index'th zone, wrapping. The whole
# of the round-robin, in one place, so the plan and every reader agree.
bank_boxes_zone_at() {
    local zones="$1" idx="$2" n=0 i=0 z
    for z in $zones; do n=$((n + 1)); done
    [ "$n" != "0" ] || return 0
    idx=$((idx % n))
    for z in $zones; do
        if [ "$i" = "$idx" ]; then
            printf '%s\n' "$z"
            return 0
        fi
        i=$((i + 1))
    done
    return 0
}

# bank_boxes_zone_after <az> — the NEXT zone in the ring, wrapping. It is what
# a reclaimed shard is retried into: the zone that just took a box back is the
# one place a second box should not go.
bank_boxes_zone_after() {
    local want="$1" first="" take=0 z
    for z in $BANK_BOXES_ZONES; do
        [ -n "$first" ] || first="$z"
        if [ "$take" = "1" ]; then
            printf '%s\n' "$z"
            return 0
        fi
        if [ "$z" = "$want" ]; then take=1; fi
    done
    printf '%s\n' "$first"
    return 0
}

#: THE ONE LEG NAME THIS FILE SPELLS, and it is spelled because ADR gate-1's
#: amendment bends the two-pass rule for THAT leg and for nothing else. The
#: same name is spelled for the same reason in `scripts/gate_ledger.sh`'s
#: reader (`onepass_unit`) and in `scripts/check.sh`'s refusal; a second
#: two-pass leg means editing three names rather than three files inheriting
#: an exemption by accident. WHICH SHARD carries it is still derived — out of
#: the listing's own legs column, never out of a unit name.
BANK_SUITE_LEG="pytest-x2"

# bank_boxes_plan <listing file> <N> <passes> <zones> — one line per shard:
#   <label>\t<unit>\t<az>\t<k/P or empty>\t<passes, on suite shards only>
#
# THE ZONE SITS AHEAD OF THE TWO COLUMNS THAT CAN BE EMPTY, and that is not
# taste: TAB is an IFS WHITESPACE character, so `IFS=<tab> read` COLLAPSES a
# run of them and a column behind two empty ones is read into the first of
# them. Every optional column therefore trails, where an empty one costs
# nothing. (`awk -F'\t'` does not collapse, which is why the pass-count reader
# below can still address a trailing column by number.)
#
# THE ZONE IS ROUND-ROBIN OVER THE RING, in the
# plan's own row order: shard i goes to `zones[i mod n]`, and the acceptance
# box — which is not in the plan — takes the next place after the last shard.
# One composer, so the argv a shard is launched with and the zone the table
# prints are the same fact read twice rather than two arithmetics.
#
# THE PASS COUNT IS DECIDED HERE, BEFORE ANY BOX IS LAUNCHED, and it is one
# decision for the whole bank rather than one per shard: `<passes>` is 1 on
# every shard of every N-capable unit whose legs include the suite leg when the
# caller could read an acceptance checkout, and 2 on every one of them when it
# could not. A bank that mixed the two would compose a row whose legs field
# could not say which half of the suite ran twice.
#
# THE COLUMN IS EMPTY ON EVERY OTHER ROW, and that is not a default — it is
# "this unit runs no suite, so it has no passes to have one of". An
# indivisible unit gets no count either: `check.sh` refuses `--passes 1`
# without a `--shard`, because the whole-suite belt is a whole unit's own.
#
# Exit 2 having said why when N cannot cover the units the listing declares.
bank_boxes_plan() {
    local listing=$1 n=$2 passes=$3 zones=$4
    local unit needs shards legs
    local zcount=0 zslot=0 az
    local indiv="" capable="" ci=0 ii=0 suite="" rowpasses
    for az in $zones; do zcount=$((zcount + 1)); done
    if [ "$zcount" = "0" ]; then
        echo "!! pm_push --bank --on-boxes: the zone ring is empty — there is nowhere to spread to." >&2
        return 2
    fi
    while IFS='	' read -r unit needs shards legs; do
        [ -n "$unit" ] || continue
        case ",${legs}," in
        *",${BANK_SUITE_LEG},"*) suite="${suite}${suite:+ }${unit}" ;;
        esac
        case "$shards" in
        N-capable)
            capable="${capable}${capable:+ }${unit}"
            ci=$((ci + 1))
            ;;
        *)
            indiv="${indiv}${indiv:+ }${unit}"
            ii=$((ii + 1))
            ;;
        esac
    done <"$listing"
    if [ "$ii" = "0" ] && [ "$ci" = "0" ]; then
        echo "!! pm_push --bank --on-boxes: the unit listing declared no units at all." >&2
        return 2
    fi
    local need=$((ii + ci))
    if [ "$n" -lt "$need" ]; then
        echo "!! pm_push --bank --on-boxes ${n}: this gate declares ${need} units (${ii} indivisible," >&2
        echo "   ${ci} shardable) and ${n} boxes cannot give every one of them a box." >&2
        echo "   The floor is DERIVED from ./scripts/check.sh --list-legs, never typed: a bank" >&2
        echo "   that silently dropped a unit is a green that vouches for less than it says." >&2
        echo "   Nothing was launched." >&2
        return 2
    fi
    local rest=$((n - ii)) per=1 remaining idx=0 take k
    # TWO SHARDS FOR EVERY N-CAPABLE UNIT BUT THE LAST, once there are seven
    # boxes or more; one below that. The LAST takes whatever is left, which is
    # what makes the arithmetic add up for any N at or above the floor.
    if [ "$n" -ge 7 ]; then
        per=2
    fi
    remaining=$((rest - ci))
    for unit in $indiv; do
        printf '%s\t%s\t%s\t\t\n' "$unit" "$unit" "$(bank_boxes_zone_at "$zones" "$zslot")"
        zslot=$((zslot + 1))
    done
    for unit in $capable; do
        rowpasses=""
        case " ${suite} " in
        *" ${unit} "*) rowpasses="$passes" ;;
        esac
        idx=$((idx + 1))
        if [ "$idx" -lt "$ci" ]; then
            take=$((per - 1))
            [ "$take" -le "$remaining" ] || take=$remaining
            take=$((take + 1))
            remaining=$((remaining - (take - 1)))
        else
            take=$((1 + remaining))
            remaining=0
        fi
        k=0
        while [ "$k" -lt "$take" ]; do
            k=$((k + 1))
            printf '%s-%sof%s\t%s\t%s\t%s/%s\t%s\n' "$unit" "$k" "$take" "$unit" \
                "$(bank_boxes_zone_at "$zones" "$zslot")" "$k" "$take" "$rowpasses"
            zslot=$((zslot + 1))
        done
    done
    return 0
}

# =============================================================================
# the acceptance box — ONE box carrying TWO answers of different kinds
# =============================================================================
#
# WHAT IT IS. One extra box, outside `bank_boxes_plan` and outside the shard
# table, that runs the WHOLE suite twice under ONE seed: pass 1 with per-test
# coverage contexts (`--cov-context=test`, so every measured line carries the
# nodeid that executed it) and pass 2 plain. `scripts/test_impact.py` then
# inverts pass 1's database into `scripts/test_impact.json` — for every
# collected test, the source files it executed — which is what lets the inner
# loop run the tests a change can REACH instead of the whole dependency closure.
#
# AND IT CARRIES TWO ANSWERS THAT ARE NOT THE SAME KIND OF THING. This is the
# whole design and the reason one box has two paragraphs:
#
#   * THE MAP IS A MEASUREMENT. A measurement that could refuse a claim would
#     mean a coverage run that died — a box that would not come up, a
#     `pytest-cov` that changed its flags, a disk that filled — reddening a
#     tree every shard passed. So its status enters `lost`, `red`, `foreign`
#     and `kbad` nowhere: it is PRINTED and the bank carries on. The cost of a
#     missing map is one wave of the loop keeping the closure scope it has
#     today, which is the designed degradation and not an outage.
#   * THE LEAK PROOF IS A CLAIM. Two whole passes under one seed are the
#     idempotency belt: a test that passes alone and fails behind its own
#     leftovers reds in pass 2 and nowhere else. Since ADR gate-1's 2026-09-18
#     amendment the pytest SHARDS run ONE pass (`--passes 1`) and THIS box's
#     two passes are what the row rests on — so the proof's own statuses are
#     composed exactly like a shard's: unreadable is `lost` (exit 2, no row),
#     a red pass is `red` (exit 1, no row), and only a green one reaches
#     `gate_ledger_record` as `leak-proof=acceptance:<box> rc=0`.
#
# THE TWO ROLES SEPARATE AT THE `rc`, and they separate in the box's own
# `leak_proof.txt`: `pass1=` and `pass2=` are the claim, `map=` is the measurement.
# A bank whose passes are green and whose map writer died writes the row and
# prints that the map was not written; there is no state in which a map
# refuses a tree every pass passed.
#
# WHEN THE PLAN IS TWO PASSES there is no acceptance box at all — the plan is
# one pass exactly when this box's checkout path could be read — so nothing
# fetches a proof, nothing reads one, and the bank is byte-for-byte the one it
# was before the amendment.
#
# AND IT IS HANDED `run`, NEVER `--leg`. A unit is a part of the composed
# verdict by definition — `bank_boxes_plan` derives the plan from
# `./scripts/check.sh --list-legs` and the composition adds the shards' leg sets
# up against it — so a `--leg` for this box would be a unit whose legs have to
# add up. `run` is the wrapper's own verb for "a command on that box", its exit
# status is the remote command's passed through untouched, and it is the seam
# this measurement belongs at.

# bank_boxes_box_checkout — the path the box's checkout lives at, or exit 1.
#
# READ, NEVER GUESSED, and read from the ONE place it is written down:
# `deploy/verifier/bake.sh`'s two knob defaults. `scripts/verifier_box.sh`'s
# `verifier_checkout_path` reads the same two lines with the same two `sed`
# programs and is the OWNER of the question; this is a second READER and not a
# second answer, and it exists because this file does not source that wrapper —
# it invokes it as an executable. A bake.sh this cannot read costs the map and
# never the bank, so it RETURNS rather than dying.
bank_boxes_box_checkout() {
    local bake="$ROOT/deploy/verifier/bake.sh" user path
    [ -r "$bake" ] || return 1
    user="$(sed -n 's|^BAKE_USER="\${DJB_VERIFIER_BAKE_USER:-\(.*\)}"$|\1|p' "$bake")"
    user="${user%%$'\n'*}"
    path="$(sed -n 's|^BAKE_CHECKOUT="\${DJB_VERIFIER_CHECKOUT:-\(.*\)}"$|\1|p' "$bake")"
    path="${path%%$'\n'*}"
    { [ -n "$user" ] && [ -n "$path" ]; } || return 1
    printf '%s\n' "${path//\$\{BAKE_USER\}/$user}"
}

# bank_boxes_acceptance_remote <checkout> <rung> — the ONE command string the
# box's shell runs. ONE LINE, and every `$` that belongs to the BOX is escaped:
# the wrapper joins its arguments with spaces and the box's shell re-parses
# them, so a `$VAR` of ours would be expanded here and a newline would split the
# command in two.
#
# THE REDIRECTS ARE ON THE BOX, for `cmd_leg`'s reason: nothing is piped, each
# phase writes its own log, and the status that comes home is the command's own.
#
# ONE SEED, MINTED ON THE BOX, ON BOTH PASSES. That is what makes this a LEAK
# PROOF rather than two runs of the suite: with the collection order and the
# worker assignment identical across the pair, a red pass 2 can only be state
# pass 1 left behind — ADR gate-1's own argument, and `scripts/check.sh`'s
# `pytest_x2_passes` reasons the same way about the same pair. Unseeded, a red
# pass 2 means "order or state, cannot tell", which proves nothing and would be
# banked as if it had.
#
# BOTH PASSES RUN WHATEVER EITHER ANSWERS, EACH WRITING ITS OWN rc, and a red
# proof still comes home as `exit 0`. The wrapper's status stays "the command
# ran", and the three statuses that matter travel home as DATA in one file
# rather than as one collapsed exit code that cannot say which of them failed.
# A collection that failed is the box and not the suite: that is `--proof`'s
# exit 2, and it comes home as the command's own status.
#
# THE MAP WRITER RUNS ONLY AFTER A GREEN PASS 1 — today's `set -e` ordering,
# made explicit now that pass 1 no longer kills the command. A map inverted out
# of a coverage database a red pass abandoned would be a projection of half a
# run; `map=2` in the proof is "could not look", which is what a writer that
# never ran honestly is.
#
# AND THE MAP IS WRITTEN OUTSIDE THE CHECKOUT — `~/verify/<rung>/`, beside the
# proof and the two pass logs, and NEVER into `scripts/test_impact.json` on the
# box. A MEASUREMENT MAY NOT DIRTY THE TREE IT MEASURED, and this one did:
# `scripts/test_impact.json` is TRACKED, so writing it left `git diff HEAD`
# non-empty on that box for ever after — and the image step runs on that same
# box, a few seconds later, and asks `deploy/provision.sh image-tag` what tree
# this is. A bank came home green, banked and pushed, with
# `!! image: refusing to build under 'tree-ee9be431c7b9-dirty'`: the refusal was
# right (a tag that says the tree was uncommitted names an image nobody can
# reproduce) and the cause was here.
#
# NOTHING ON THE MAC MOVED WITH IT. The fetch already reads
# `~/verify/<rung>/test_impact.json` — the box used to `cp` the file there
# after writing it into the tree — so this deletes the copy and the write that
# needed it, and the map lands in this checkout exactly as before.
bank_boxes_acceptance_remote() {
    local checkout="$1" rung="$2" v
    v="\$HOME/verify/${rung}"
    # THE BODY IS `--proof`, CALLED — `proof_main` above, the one function the
    # nightly runner calls too, so the box and the runner write one field set.
    # `--out` is under $HOME, outside the checkout (the paragraph above). A
    # proof that ran and was RED is still exit 0 here (`r=1` → 0): the
    # statuses travel home as DATA in `leak_proof.txt`, and the wrapper's status
    # stays "the command ran". Only 2 — the collection failed, or no record
    # could be written — comes home as the command's status, which is what it
    # always was when the setup, not the suite, failed.
    printf '%s' "mkdir -p ${v}; cd ${checkout}; \
./scripts/pm_push.sh --proof --where acceptance --workers ${BANK_PROOF_WORKERS} --out ${v}; \
r=\$?; [ \"\${r}\" != 1 ] || r=0; exit \${r}"
}

# bank_boxes_acceptance_report <the acceptance box's rc> — what the ninth box
# measured, said in full, on every exit path.
#
# IT NEVER RETURNS NON-ZERO. Every branch here ends in a printed line and a 0:
# this function's entire contract is that nothing it can discover changes what
# the bank decides about the tree.
#
# THE FILE LANDS IN THE WORKING TREE AND IS NOT COMMITTED — the
# `scripts/pytest_durations.json` practice, and a bank takes no commit
# (`pm_push.sh` refuses a dirty checkout BEFORE it starts, which is a different
# rule from this one). It is safe against the verdict for a reason worth
# writing down: the row was keyed on the tree read at the top of the bank and
# `gate_ledger_record` is handed that value, and the pre-push hook consults the
# PUSHED COMMIT's tree — so a map modified in the working tree afterwards moves
# neither.
bank_boxes_acceptance_report() {
    local arc="${1:-}" fetched="${BANK_BOXES_SINK}/test_impact.json" line mrc
    echo ""
    if [ -n "$BANK_BOXES_ACCEPT_NOTE" ]; then
        echo "${BANK_BOXES_ACCEPT_NOTE}"
        echo ""
        return 0
    fi
    if [ -z "$BANK_BOXES_ACCEPT_ID" ]; then
        echo "acceptance: no box — none was asked for."
        echo ""
        return 0
    fi
    # THE BOX'S OWN TWO WALLS, out of its own output. The Mac's elapsed is the
    # command PLUS a transport; the numbers a person compares against the
    # shards are the ones the box timed.
    line="$(awk '/^acceptance: pass1/ { print; exit }' "${BANK_BOXES_SINK}/acceptance.log" 2>/dev/null || true)"
    [ -z "$line" ] || echo "  ${line}"
    echo "  acceptance box ${BANK_BOXES_ACCEPT_ID} · $(cat "${BANK_BOXES_SINK}/acceptance.wall" 2>/dev/null || echo '?')s from this Mac"
    if [ "${arc:-1}" != "0" ]; then
        echo "acceptance: map NOT written (exit ${arc:-<no status>}) — the loop keeps the closure scope"
        echo "   Its whole log is ${BANK_BOXES_SINK}/acceptance.log. NOTHING about the verdict"
        echo "   above depends on it: a measurement may not refuse a claim every shard passed."
        echo ""
        return 0
    fi
    if [ ! -s "$fetched" ]; then
        # WHY NO FILE CAME BACK, WHEN THE BOX ITSELF SAYS SO. The command
        # always exits 0 (its three statuses travel home in `leak_proof.txt`
        # instead), so "the box said 0" is true of a dead map writer and of a
        # fetch that could not reach the file, and those are two different
        # things to go and look at. `map=` is read here — the same field the
        # composition reads and deliberately does NOT act on — so the line
        # names the cause the box already proved rather than the one the
        # absence of a file merely suggests.
        mrc="$(bank_boxes_proof_field "${BANK_BOXES_SINK}/acceptance.proof" map)"
        case "${mrc:-}" in
        '' | 0)
            echo "acceptance: map NOT written (the box said 0 and no file came back) — the loop keeps the closure scope"
            echo "   The fetch log is ${BANK_BOXES_SINK}/fetch-acceptance.log."
            ;;
        *)
            echo "acceptance: map NOT written (the box's map writer exited ${mrc}) — the loop keeps the closure scope"
            echo "   Its log is ${BANK_BOXES_SINK}/acceptance.log and the fetch log is"
            echo "   ${BANK_BOXES_SINK}/fetch-acceptance.log. NOTHING about the verdict above"
            echo "   depends on it: a measurement may not refuse a claim every pass passed."
            ;;
        esac
        echo ""
        return 0
    fi
    if ! cp "$fetched" "$ROOT/scripts/test_impact.json"; then
        echo "acceptance: map NOT written (it came back and could not be copied into ${ROOT}) —"
        echo "   the loop keeps the closure scope. It is at ${fetched}."
        echo ""
        return 0
    fi
    echo "acceptance: scripts/test_impact.json rewritten from ${BANK_BOXES_ACCEPT_ID}"
    # The map's own census line and its generated block, read out of the file
    # rather than restated: one grep, and a file that is not the shape this
    # bank expects prints as the shape it is.
    awk '
        /"tree"/ { t = $0 }
        /"at"/   { a = $0 }
        /"pytest"/ { p = $0 }
        END {
            gsub(/^[ \t]+|[ \t]+$/, "", t); gsub(/^[ \t]+|[ \t]+$/, "", a); gsub(/^[ \t]+|[ \t]+$/, "", p)
            printf "  generated  %s %s %s\n", t, a, p
        }
    ' "$ROOT/scripts/test_impact.json"
    echo "  It is MODIFIED IN THE WORKING TREE AND NOT COMMITTED — a bank takes no commit."
    echo "  Commit it the way scripts/pytest_durations.json is committed:"
    echo "     git add scripts/test_impact.json"
    echo ""
    return 0
}

# bank_boxes_field <file> <awk program> — read the file WHOLE and slice it.
# Never `grep | head`: the exit status of a reader is not the exit status of the
# thing being read, and nothing here branches on a reader's status.
bank_boxes_first_match() {
    awk "$2" "$1" 2>/dev/null || true
}

# bank_boxes_proof_field <file> <key> — the value of `<key>=` in the box's
# `leak_proof.txt`, or NOTHING. Never a default: the caller distinguishes "the box
# said 0" from "the box said nothing", and a reader that answered 0 for an
# absent key would turn an unreadable proof into a green one.
#
# THE WHOLE FILE IS READ AND SLICED, `bank_boxes_first_match`'s rule: no pipe
# whose exit status anything branches on, and no `head` in front of a `grep`.
bank_boxes_proof_field() {
    awk -v k="$2" '
        {
            for (i = 1; i <= NF; i++) {
                n = index($i, "=")
                if (n && substr($i, 1, n - 1) == k) { print substr($i, n + 1); exit }
            }
        }
    ' "$1" 2>/dev/null || true
}

# =============================================================================
# ONE LAUNCH BLOCK, ONE DETACH, ONE FETCH OF THE NINTH BOX
# =============================================================================
#
# WHY THEY ARE FUNCTIONS AND NOT THREE COPIES. A reclaimed shard is brought up
# again, detached again and fetched again, and a second spelling of any of the
# three is a second thing to keep in step with the first — the `legargv` array
# in phase 2 exists for exactly that reason one retry earlier. House rule 13's
# shape: one launch block and one row writer.

# bank_boxes_up_one <label> <rung> <az> <log> <is-shard> — bring ONE box up and
# record everything the rest of this file reads about it.
#
# THE LAUNCHED ID REACHES THE TEARDOWN LIST BEFORE THE STATUS IS READ, and that
# ordering is the whole of the defect. `up` launches the instance, waits for the SSM
# agent, and THEN probes the tunnel — and the probe's `die` fires BEFORE the
# `instance` line is printed. A bank that read the id out of that line alone
# therefore lost the id of every box whose probe failed: launched, billing, and
# nameable by nothing this script keeps. So the `launched <id> az <az>` line —
# printed the moment the instance exists — is read FIRST and appended to
# `boxes.tsv` FIRST, and only then is the status consulted.
#
# AND THE SECOND APPEND IS GUARDED. An `up` that went all the way prints both
# lines about the same box; two rows would be two `down`s of one instance, and
# the teardown's "each box exactly once" would stop being true.
bank_boxes_up_one() {
    local label="$1" rung="$2" az="$3" log="$4" isshard="$5"
    local urc=0 lid uid
    if [ "$isshard" = "1" ]; then
        # DJB_VERIFIER_BANK_SHARD IS WHAT MAKES THIS A SHARD'S `up` AND NOT AN
        # OPERATOR'S. The wrapper's Spot→on-demand fallback is right for one box
        # somebody is standing in front of and wrong for a bank: N shards each
        # answering a Spot refusal with an on-demand box is N on-demand boxes
        # against a quota an order of magnitude smaller than the Spot one,
        # bought without anybody deciding to. With this set the shard is `could
        # not launch` instead. `DJB_VERIFIER_ON_DEMAND_OK` is the valve, and it
        # is inherited from the operator's own environment so that one typed
        # sentence covers the whole bank.
        DJB_VERIFIER_BANK_SHARD=1 "$BANK_BOXES_VB" up --for "$rung" --az "$az" \
            --ttl "$BANK_BOX_TTL_HOURS" --idle "$BANK_BOX_IDLE_MINUTES" \
            >"$log" 2>&1 </dev/null || urc=$?
    else
        "$BANK_BOXES_VB" up --for "$rung" --az "$az" \
            --ttl "$BANK_BOX_TTL_HOURS" --idle "$BANK_BOX_IDLE_MINUTES" \
            >"$log" 2>&1 </dev/null || urc=$?
    fi
    lid="$(awk '$1 == "launched" { print $2; exit }' "$log" 2>/dev/null || true)"
    [ -z "$lid" ] || printf '%s\t%s\n' "$label" "$lid" >>"$BANK_BOXES_TSV"
    printf '%s\n' "$urc" >"${BANK_BOXES_SINK}/${label}.up.rc"
    [ "$urc" = "0" ] || return 0
    uid="$(awk '$1 == "instance" { print $2; exit }' "$log" 2>/dev/null || true)"
    if [ -z "$uid" ]; then
        printf '2\n' >"${BANK_BOXES_SINK}/${label}.up.rc"
        return 0
    fi
    printf '%s\n' "$uid" >"${BANK_BOXES_SINK}/${label}.id"
    awk '$1 == "market" { print $2; exit }' "$log" >"${BANK_BOXES_SINK}/${label}.market" 2>/dev/null || true
    [ "$uid" = "$lid" ] || printf '%s\t%s\n' "$label" "$uid" >>"$BANK_BOXES_TSV"
    return 0
}

# bank_boxes_detach <label> <id> <unit> <shard> <passes> <log> — one unit of
# the gate on one box, with the ONE retry that 255 gets.
#
# 255 IS SSH'S OWN STATUS AND IT GETS ONE MORE GO. `up` returns when SSM
# reports the agent Online, and the agent answers before the SSH tunnel does —
# so a detach fired in that window comes back 255 with an EMPTY log: no gate
# ran, nothing was measured, and a whole bank refused with every box up and
# paid for while the socket was answering seconds later. ONE retry, after a
# short printed wait, and ONLY for 255: any other status is the wrapper or the
# box saying something real, and retrying it would risk a second copy of a leg
# that is already running.
#
# THE SEAM'S ARGV IS COMPOSED ONCE AND HANDED TO BOTH TRIES — an array rather
# than three nested `if`s, because two spellings of one command are two
# commands to keep in step. `--passes 1` is appended only where the plan said
# one: `--passes 2` is the default `check.sh` normalises away, so a two-pass
# bank's argv is byte-for-byte the one it was before the amendment.
bank_boxes_detach() {
    local label="$1" lid="$2" unit="$3" shard="$4" passes="$5" log="$6"
    local legargv drc try
    legargv=(leg "$lid" --unit "$unit")
    [ -z "$shard" ] || legargv+=(--shard "$shard")
    [ "$passes" != "1" ] || legargv+=(--passes 1)
    legargv+=(--log leg)
    drc=0
    for try in 1 2; do
        drc=0
        "$BANK_BOXES_VB" "${legargv[@]}" >"$log" 2>&1 </dev/null || drc=$?
        if [ "$drc" = "255" ] && [ "$try" = "1" ]; then
            echo "pm_push --bank --on-boxes: ${label}: the detach exited 255 — that is ssh, not the gate, and the tunnel is usually a few seconds behind the agent. Waiting ${BANK_DETACH_RETRY_SECONDS}s and retrying the detach, once."
            sleep "$BANK_DETACH_RETRY_SECONDS"
            continue
        fi
        break
    done
    printf '%s\n' "$drc" >"${BANK_BOXES_SINK}/${label}.leg.rc"
    return 0
}

# bank_boxes_fetch_shard <label> <id> — one shard's log and its exit status,
# fetched BY THE WORKER THAT JUST WAITED ON IT and never in a later phase.
#
# WHY THE FETCH CANNOT WAIT FOR THE OTHER SHARDS. A box's idle reaper starts
# counting when its LEG EXITS, and the bank's phases join: a pytest shard that
# finished in two and a half minutes used to sit untouched until the slowest
# unit (selftest, ~20 min on a tree where `quality/rules.yaml` moved) came
# home, and the box was shut down under it — `box gone (terminated)`, no log,
# and a leak proof this bank composes as LOST with no retry, because a reclaim
# is not what happened. Fetching here puts the work on the Mac while the box
# is unambiguously alive, and no idle ceiling can be short enough to matter.
bank_boxes_fetch_shard() {
    local label="$1" fid="$2"
    [ -n "$fid" ] || return 0
    "$BANK_BOXES_VB" fetch "$fid" "~/verify/bank-${BANK_BOXES_TREE8}-${label}/leg.log" \
        "${BANK_BOXES_SINK}/${label}.log" \
        >"${BANK_BOXES_SINK}/fetch-${label}.log" 2>&1 </dev/null || true
    "$BANK_BOXES_VB" fetch "$fid" "~/verify/bank-${BANK_BOXES_TREE8}-${label}/leg.rc" \
        "${BANK_BOXES_SINK}/${label}.rc" \
        >>"${BANK_BOXES_SINK}/fetch-${label}.log" 2>&1 </dev/null || true
    return 0
}

# bank_boxes_fetch_acceptance_files <acceptance rc> — the ninth box's four
# files, asked for in ONE place so phase 4 and the reclaim retry cannot drift.
#
# THE MAP IS CONDITIONAL AND THE OTHER THREE ARE NOT, and the difference is the
# two roles. A map fetched from a box that wrote nothing would bring home the
# PREVIOUS wave's file or nothing at all, and either would be a projection
# claiming to be this tree's. The PROOF is the thing the row rests on and its
# absence has to be READ rather than assumed. The two PASS LOGS are the last of
# them, and they are the newest reason this function exists: the
# one moment they exist anywhere this Mac can reach is before the teardown, and
# a red bank that did not bring them home is a refusal nobody can act on
# without re-running the whole bank — so they come home on a green too.
bank_boxes_fetch_acceptance_files() {
    local arc="$1" id="$BANK_BOXES_ACCEPT_ID" v p rc
    [ -n "$id" ] || return 0
    v="~/verify/${BANK_BOXES_ARUNG}"
    if [ "${arc:-1}" = "0" ]; then
        rc=0
        "$BANK_BOXES_VB" fetch "$id" "${v}/test_impact.json" \
            "${BANK_BOXES_SINK}/test_impact.json" \
            >"${BANK_BOXES_SINK}/fetch-acceptance.log" 2>&1 </dev/null || rc=$?
        printf '%s\n' "$rc" >"${BANK_BOXES_SINK}/acceptance.fetch.rc"
    fi
    rc=0
    "$BANK_BOXES_VB" fetch "$id" "${v}/leak_proof.txt" \
        "${BANK_BOXES_SINK}/acceptance.proof" \
        >"${BANK_BOXES_SINK}/fetch-proof.log" 2>&1 </dev/null || rc=$?
    printf '%s\n' "$rc" >"${BANK_BOXES_SINK}/acceptance.proof.fetch.rc"
    for p in pass1 pass2; do
        "$BANK_BOXES_VB" fetch "$id" "${v}/${p}.log" \
            "${BANK_BOXES_SINK}/${p}.log" \
            >"${BANK_BOXES_SINK}/fetch-${p}.log" 2>&1 </dev/null || true
    done
    return 0
}

# =============================================================================
# A RECLAIM IS ONE MORE BOX, IN THE NEXT ZONE, ONCE
# =============================================================================
#
# WHY A RETRY AT ALL. A Spot reclaim is AWS taking the machine back, and before
# this the whole bank was exit 2 over it: one box of nine vanishing cost the
# other eight's work and a full re-run. ONE more box, in the NEXT zone, is the
# cheapest thing that can be true — capacity is a per-zone fact, so the zone
# that just took a box back is the one place not to go again.
#
# AND ONLY ONCE. Two reclaims of one shard is capacity that is gone, and the
# honest answer is the one this bank always gave: LOST, never red. The marker
# is a file in the sink and it is written BEFORE the retry, so no path can
# reach a third box.

# bank_boxes_saw_reclaim <file>... — 0 iff one of them carries the wrapper's
# own `box reclaimed` line. Every subcommand goes through `refuse_if_reclaimed`,
# so the news arrives at whichever of the wait, the run or the fetch came first.
bank_boxes_saw_reclaim() {
    local f
    for f in "$@"; do
        [ -f "$f" ] || continue
        if grep -qF 'box reclaimed' "$f"; then return 0; fi
    done
    return 1
}

# bank_boxes_reclaim_status <file>... — the spot status code the wrapper named
# on that line, or `status unread`. It is the one thing a reclaim leaves behind
# that says WHY, and it is what the table prints beside the retried shard.
bank_boxes_reclaim_status() {
    local f s=""
    for f in "$@"; do
        [ -f "$f" ] || continue
        s="$(bank_boxes_first_match "$f" '
            /box reclaimed/ {
                for (i = 1; i <= NF; i++) {
                    if ($i == "status") {
                        out = $(i + 1)
                        for (j = i + 2; j <= NF; j++) { out = out " " $j }
                        print out
                        exit
                    }
                }
            }')"
        [ -z "$s" ] || break
    done
    printf '%s\n' "${s:-status unread}"
}

# bank_boxes_retry_reclaimed — the sweep, run ONCE after every log is home and
# before anything is composed. A shard whose box was reclaimed gets one more
# box in the next zone, its leg detached again, its wait and its two fetches
# redone; the old id STAYS on the teardown list (a reclaimed instance is
# `already gone` to the wrapper's `down`, which is exit 0 and not a refusal —
# trusting AWS to have finished what it started is not a saving) and the new
# one joins it.
#
# EVERYTHING IT REWRITES IS WHAT THE COMPOSITION READS: the wait log, the
# fetched leg log and the fetched status. So a second reclaim leaves the words
# `box reclaimed` in the wait log exactly where the composition has always
# looked for them, and the shard is LOST by the branch that was already there.
bank_boxes_retry_reclaimed() {
    local label unit shard passes az oldid status nextaz
    local retried=0

    # THE DETECTION IS SERIAL AND CHEAP — it reads files this Mac already has
    # — AND THE RETRIES ARE PARALLEL, one worker per reclaimed box, exactly
    # the shape phases 1 to 3 have. Serially, two reclaimed selftest shards
    # would cost two whole legs end to end (+46 min on a measured tree) for
    # work that runs on two different machines.
    BANK_BOXES_WORKERS=""
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        [ ! -f "${BANK_BOXES_SINK}/${label}.retried" ] || continue
        bank_boxes_saw_reclaim "${BANK_BOXES_SINK}/wait-${label}.log" \
            "${BANK_BOXES_SINK}/fetch-${label}.log" || continue
        oldid="$(cat "${BANK_BOXES_SINK}/${label}.id" 2>/dev/null || echo '<unnamed>')"
        status="$(bank_boxes_reclaim_status "${BANK_BOXES_SINK}/wait-${label}.log" \
            "${BANK_BOXES_SINK}/fetch-${label}.log")"
        nextaz="$(bank_boxes_zone_after "$az")"
        printf '%s\t%s\n' "$oldid" "$status" >"${BANK_BOXES_SINK}/${label}.retried"
        retried=$((retried + 1))
        echo "pm_push --bank --on-boxes: ${label}: the box was RECLAIMED (${status})."
        echo "    One more box, in ${nextaz} — capacity is a per-zone fact and ${az} has just"
        echo "    said no. ${oldid} stays on the teardown list; a reclaimed instance is"
        echo "    'already gone' to a down, never a refusal."
        (
            set +e
            bank_boxes_up_one "$label" "bank-${BANK_BOXES_TREE8}-${label}" "$nextaz" \
                "${BANK_BOXES_SINK}/up-${label}-retry.log" 1
            if [ "$(cat "${BANK_BOXES_SINK}/${label}.up.rc" 2>/dev/null || echo 2)" != "0" ]; then
                echo "pm_push --bank --on-boxes: ${label}: the second box did not come up either (${BANK_BOXES_SINK}/up-${label}-retry.log); the shard stays LOST and this bank will refuse."
                exit 0
            fi
            newid="$(cat "${BANK_BOXES_SINK}/${label}.id")"
            bank_boxes_detach "$label" "$newid" "$unit" "$shard" "$passes" \
                "${BANK_BOXES_SINK}/leg-${label}-retry.log"
            if [ "$(cat "${BANK_BOXES_SINK}/${label}.leg.rc" 2>/dev/null || echo 2)" != "0" ]; then
                echo "pm_push --bank --on-boxes: ${label}: the unit could not be detached on ${newid}; the shard stays LOST."
                exit 0
            fi
            printf '%s\n' "$(date +%s)" >"${BANK_BOXES_SINK}/${label}.began"
            "$BANK_BOXES_VB" wait "$newid" leg \
                >"${BANK_BOXES_SINK}/wait-${label}.log" 2>&1 </dev/null
            printf '%s\n' "$(($(date +%s) - $(cat "${BANK_BOXES_SINK}/${label}.began")))" \
                >"${BANK_BOXES_SINK}/${label}.wall"
            # THE SAME WORKER FETCHES, for the same reason phase 3's does:
            # the second box's idle clock starts the moment its leg exits too.
            bank_boxes_fetch_shard "$label" "$newid"
        ) &
        BANK_BOXES_WORKERS="${BANK_BOXES_WORKERS}${BANK_BOXES_WORKERS:+ }$!"
    done <"$BANK_BOXES_PLAN"

    # THE NINTH BOX GETS THE SAME ONE MORE BOX, in the same shape and beside
    # the shards' retries rather than after them. It needs it more than any
    # shard does: since ADR gate-1's amendment every pytest shard runs ONE
    # pass, so a reclaimed acceptance box is a bank with no leak proof at all
    # — exit 2 over eight green shards. Its reclaim shows up wherever the
    # first subcommand met it: the run, or either of the fetches.
    if [ -n "$BANK_BOXES_ACCEPT_ID" ] && [ ! -f "${BANK_BOXES_SINK}/acceptance.retried" ] &&
        bank_boxes_saw_reclaim "${BANK_BOXES_SINK}/acceptance.log" \
            "${BANK_BOXES_SINK}/fetch-proof.log" \
            "${BANK_BOXES_SINK}/fetch-acceptance.log"; then
        oldid="$BANK_BOXES_ACCEPT_ID"
        status="$(bank_boxes_reclaim_status "${BANK_BOXES_SINK}/acceptance.log" \
            "${BANK_BOXES_SINK}/fetch-proof.log" "${BANK_BOXES_SINK}/fetch-acceptance.log")"
        nextaz="$(bank_boxes_zone_after "$BANK_BOXES_ACCEPT_AZ")"
        printf '%s\t%s\n' "$oldid" "$status" >"${BANK_BOXES_SINK}/acceptance.retried"
        retried=$((retried + 1))
        echo "pm_push --bank --on-boxes: acceptance: the box was RECLAIMED (${status})."
        echo "    One more box, in ${nextaz}. Every pytest shard ran ONE pass, so this box"
        echo "    IS the leak proof and a bank without it refuses over eight green shards."
        (
            set +e
            bank_boxes_up_one acceptance "$BANK_BOXES_ARUNG" "$nextaz" \
                "${BANK_BOXES_SINK}/up-acceptance-retry.log" 0
            if [ "$(cat "${BANK_BOXES_SINK}/acceptance.up.rc" 2>/dev/null || echo 2)" != "0" ]; then
                echo "pm_push --bank --on-boxes: acceptance: the second box did not come up either; the leak proof stays unread."
                exit 0
            fi
            # THE WORKER READS THE NEW ID OUT OF THE FILE `bank_boxes_up_one`
            # wrote, and the PARENT re-reads the same file after the join: a
            # subshell cannot hand a variable back, and the id is what every
            # later step (the proof's box, the image, the teardown) names.
            aid="$(cat "${BANK_BOXES_SINK}/acceptance.id")"
            arrc=0
            "$BANK_BOXES_VB" run "$aid" -- "$BANK_BOXES_ACMD" \
                >"${BANK_BOXES_SINK}/acceptance.log" 2>&1 </dev/null || arrc=$?
            printf '%s\n' "$arrc" >"${BANK_BOXES_SINK}/acceptance.rc"
            BANK_BOXES_ACCEPT_ID="$aid"
            bank_boxes_fetch_acceptance_files "$arrc"
        ) &
        BANK_BOXES_WORKERS="${BANK_BOXES_WORKERS}${BANK_BOXES_WORKERS:+ }$!"
    fi

    if [ "$retried" != "0" ]; then
        # `set +e` AROUND THE JOIN, every other phase's rule: `wait` carries
        # the last worker's status and a retry worker that ended non-zero
        # would take errexit — and the bank — with it, instead of leaving the
        # shard LOST for the composition to refuse over.
        set +e
        wait
        set -e
        BANK_BOXES_WORKERS=""
        # THE NINTH BOX'S ID, RE-READ. Its retry ran in a subshell, so the
        # variable it set died with it; the file did not.
        if [ -f "${BANK_BOXES_SINK}/acceptance.retried" ]; then
            BANK_BOXES_ACCEPT_ID="$(cat "${BANK_BOXES_SINK}/acceptance.id" 2>/dev/null || true)"
            [ -z "$BANK_BOXES_ACCEPT_ID" ] || BANK_BOXES_ACCEPT_NOTE=""
        fi
        echo ""
    fi
    BANK_BOXES_WORKERS=""
    return 0
}

# =============================================================================
# WHICH TEST FAILED, AND THE COMMAND THAT REPLAYS IT
# =============================================================================
#
# WHY IT IS COMPOSED AND NOT LINKED. A red bank's boxes are terminated four
# lines later, so `pass2.log` is readable exactly once — before the teardown —
# and a refusal that pointed at a path on a machine that no longer exists cost
# the reader a whole second bank to learn one nodeid. The line is PRINTED
# beside the table and composed into NO row: a red bank writes no row at all,
# and `gate_ledger_record`'s grammar gains nothing.

# bank_boxes_first_failing <log> <what> <seed> — one line naming the first
# failing test and the command that reproduces it, or `none named`.
#
# `FAILED <nodeid>` IS PYTEST'S OWN SHORT SUMMARY (its default `-r fE`), and
# the FIRST such line is the first failure in the order that ran — which is
# the one worth replaying, because the ones after it may be its consequences.
# A log with no such line is a pass that died without a summary (a collection
# error, an OOM, a box that went away): the status is red and there is no
# nodeid in it, and a composer that invented one would be worse than one that
# says so.
bank_boxes_first_failing() {
    local log="$1" what="$2" seed="$3" node n
    node="$(bank_boxes_first_match "$log" '/^FAILED / { print $2; exit }')"
    if [ -z "$node" ]; then
        printf 'first failing: none named - no FAILED line in %s\n' "$log"
        return 0
    fi
    n="$(bank_boxes_first_match "$log" '/^FAILED / { n++ } END { print n + 0 }')"
    printf 'first failing: %s (%s; %s FAILED) - replay: ./scripts/test.sh -n %s --randomly-seed=%s %s\n' \
        "$node" "$what" "${n:-?}" "$BANK_PROOF_WORKERS" "${seed:-<seed unread>}" "$node"
}

# bank_boxes_log_seed <log> — the seed pytest-randomly printed at the top of
# that run, so a shard's replay names the order it reddened in. The acceptance
# box's seed comes from its `leak_proof.txt` instead, which is the authority there.
bank_boxes_log_seed() {
    bank_boxes_first_match "$1" '
        /--randomly-seed=/ {
            i = index($0, "--randomly-seed=")
            s = substr($0, i + 16)
            sub(/[^0-9].*$/, "", s)
            if (s != "") { print s; exit }
        }'
}

# bank_boxes_table — the per-shard table, printed on EVERY exit path, green or
# not. A composition that refused and said only "a shard was red" is a
# composition nobody can act on.
bank_boxes_table() {
    local label unit shard passes az id rc wall tree market retried
    echo ""
    printf '  %-26s %-21s %-9s %-14s %-6s %-3s %-7s %s\n' \
        "shard" "box" "market" "az" "passes" "rc" "wall" "tree"
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        id="$(cat "${BANK_BOXES_SINK}/${label}.id" 2>/dev/null || echo '-')"
        rc="$(cat "${BANK_BOXES_SINK}/${label}.rc" 2>/dev/null || echo '?')"
        wall="$(cat "${BANK_BOXES_SINK}/${label}.legwall" 2>/dev/null ||
            cat "${BANK_BOXES_SINK}/${label}.wall" 2>/dev/null || echo '?')"
        tree="$(cat "${BANK_BOXES_SINK}/${label}.tree" 2>/dev/null || echo '-')"
        # THE MARKET THE WRAPPER READ BACK OFF THE INSTANCE, not the one the
        # launch asked for: `up` prints it from EC2's `InstanceLifecycle` and
        # this is where it is kept, because afterwards the boxes are gone and
        # this table is all there is to cost the bank from.
        market="$(cat "${BANK_BOXES_SINK}/${label}.market" 2>/dev/null || true)"
        case "$market" in '') market="-" ;; esac
        # THE PASS COUNT THE PLAN DECIDED, out of the plan itself. A dash is
        # "this unit runs no suite", never "two" — a column that guessed a
        # default would read as a claim about a shard that made none.
        case "$passes" in '') passes="-" ;; esac
        # THE ZONE THE PLAN SENT IT TO. After a reclaim retry the box in the
        # `box` column is the SECOND one, so its zone is the one it was
        # retried into and the `retried-from` line below says which box and
        # which capacity code it replaced.
        case "$az" in '') az="-" ;; esac
        printf '  %-26s %-21s %-9s %-14s %-6s %-3s %-7s %s\n' \
            "$label" "$id" "$market" "$az" "$passes" "$rc" "${wall}s" "$tree"
        if [ -f "${BANK_BOXES_SINK}/${label}.retried" ]; then
            retried="$(bank_boxes_first_match "${BANK_BOXES_SINK}/${label}.retried" \
                '{ printf "retried-from %s (%s)", $1, substr($0, index($0, "\t") + 1); exit }')"
            printf '    %s\n' "$retried"
        fi
    done <"${BANK_BOXES_SINK}/plan.tsv"
    # AND THE NINTH BOX, WHEN IT WAS RETRIED TOO. It is not in the plan and
    # never has been (it takes no unit), so it has no row above — but a reader
    # costing this bank needs to know a tenth box existed.
    if [ -f "${BANK_BOXES_SINK}/acceptance.retried" ]; then
        retried="$(bank_boxes_first_match "${BANK_BOXES_SINK}/acceptance.retried" \
            '{ printf "retried-from %s (%s)", $1, substr($0, index($0, "\t") + 1); exit }')"
        printf '  %-26s %-21s %s\n' "acceptance" "${BANK_BOXES_ACCEPT_ID:--}" ""
        printf '    %s\n' "$retried"
    fi
    # THE VALVE, PRINTED WHEREVER THE TABLE IS. An on-demand row in the column
    # above is only readable beside the reason somebody typed for it, and a
    # bank with no valve set is the ordinary case that should say so once.
    if [ -n "${DJB_VERIFIER_ON_DEMAND_OK:-}" ]; then
        echo "  on-demand valve: ${DJB_VERIFIER_ON_DEMAND_OK}"
    else
        echo "  on-demand valve: unset — a shard whose Spot request is refused could not"
        echo "    launch, and this bank refuses rather than buying on-demand for it."
    fi
    echo ""
}

# =============================================================================
# THE IMAGE, BUILT ONCE, BY THE BANK, FROM THE BANKED TREE (ADR deploy-4a)
# =============================================================================
#
# WHY IT IS HERE AND NOT IN CI. CI's `images` job sits behind `needs: verdict`
# — a second full gate on GitHub runners — and its OIDC push role has failed on
# every run since the role was last touched, so the registry's newest image was
# a month old while every green tree went by. The bank already has what an
# image build needs and nothing else in the system does: a tree that a composed
# verdict has just passed, N boxes of the right architecture still up, and a
# moment after the row is written where nothing is waiting on a measurement.
#
# THE IMAGE IS NEVER PART OF THE VERDICT, and every branch below is written to
# that rule: no registry coordinate, a tag that does not match, a build that
# failed, a push the role was refused — each is PRINTED and each returns 0 with
# the row standing. The verdict is a claim about bytes a gate measured; an
# image is an artefact derived from those bytes afterwards, and a registry that
# was down may not retract a green. The fallback when this step does nothing is
# the one CI has always had: its `images` job builds the tag that is missing.
#
# bank_boxes_image_remote <checkout> <tag> <registry> <region> <web ref> <worker ref>
# — the ONE command string the box's shell runs, `bank_boxes_acceptance_remote`'s
# grammar exactly: one line, and every `$` that belongs to the BOX escaped,
# because the wrapper joins its arguments with spaces and the box re-parses them.
#
# THE TOKEN IS THE BOX'S OWN. `aws ecr get-login-password` runs THERE, under the
# instance profile, and never on this Mac: a token piped from here would make
# every bank depend on the operator's credentials and would put a registry
# password in a local process's argv. `deploy/iam/verifier_bootstrap.sh` grants
# the box role exactly the two repositories.
#
# AND IT LOGS OUT AT THE END, `|| true`. `docker login` writes the token into
# `~/.docker/config.json` and leaves it there: the box is terminated a few
# lines later, so this buys minutes rather than days — but a registry
# credential resting on disk for no reason is the kind of thing that is only
# ever cheap to remove before somebody reuses the box for something else. It
# comes AFTER the digest reads, which go to the registry and need the token,
# and it may never fail the step: an image that was built and pushed must not
# read as `NOT built` because a logout was unhappy.
#
# AND IT IS A VARIABLE, NOT A PIPE. `set -o pipefail` is bash's and the box's
# login shell is not promised to be one, so a piped `get-login-password` whose
# `aws` half failed would hand `docker login` an empty password and the pipeline
# would carry docker's status. An assignment fails under plain `set -e`.
bank_boxes_image_remote() {
    local checkout="$1" tag="$2" registry="$3" region="$4" web="$5" worker="$6"
    printf '%s' "set -e; cd ${checkout}; export DJB_IMAGE_REGISTRY=${registry}; \
t=\$(./deploy/provision.sh image-tag); \
if [ \"\$t\" != \"${tag}\" ]; then \
echo \"!! image: refusing to build under '\$t' — this bank keys on ${tag}\"; \
echo '   what moved under it (git status --short, first 10):'; \
git status --short | sed -n '1,10p'; exit 3; fi; \
p=\$(aws ecr get-login-password --region ${region}); \
printf '%s' \"\$p\" | docker login --username AWS --password-stdin ${registry%%/*}; \
T0=\$(date +%s); \
docker build --target web --tag ${web} .; docker push ${web}; \
T1=\$(date +%s); \
docker build --target worker --tag ${worker} .; docker push ${worker}; \
T2=\$(date +%s); \
echo \"image: seconds web \$((T1-T0)) worker \$((T2-T1))\"; \
echo \"image: digest web \$(./deploy/provision.sh image-digest web ${tag})\"; \
echo \"image: digest worker \$(./deploy/provision.sh image-digest worker ${tag})\"; \
echo \"image: platform \$(docker image inspect --format '{{.Os}}/{{.Architecture}}' ${web})\"; \
docker logout ${registry%%/*} || true"
}

# bank_boxes_image <checkout> <tag> — the whole step. ALWAYS 0.
#
# THE TAG IS THIS BANK'S OWN TREE and it is composed here, not asked for: the
# row was just keyed on `$tree` and the image has to carry the same name or the
# registry and the ledger are talking about different bytes. The BOX asserts the
# equality from its own side (`provision.sh image-tag` in its own checkout) —
# which is the half this Mac cannot do, and the half that catches a box parked
# off the pushed tree.
#
# THE REFS COME FROM `deploy/provision.sh image-ref`, the one function that
# composes a registry name in this tree. Asking it is also how the registry
# coordinate is CHECKED: it refuses with `require_image_registry`'s own text
# when there is none, and the refusal is this step's "not built" branch.
bank_boxes_image() {
    local checkout="$1" tag="$2"
    local ref_web ref_worker registry host region id label why log rc cmd
    local secs_web secs_worker dg_web dg_worker platform
    echo ""
    if [ -z "$checkout" ]; then
        echo "image: not built — deploy/verifier/bake.sh does not say where a box's checkout"
        echo "   lives, so there is nothing to build FROM. The row above stands."
        return 0
    fi
    if ! ref_web="$(cd "$ROOT" && ./deploy/provision.sh image-ref web "$tag" 2>/dev/null)" ||
        ! ref_worker="$(cd "$ROOT" && ./deploy/provision.sh image-ref worker "$tag" 2>/dev/null)"; then
        echo "image: not built — no registry coordinate"
        echo "   DJB_IMAGE_REGISTRY is unset here and deploy/.env carries none, so there is"
        echo "   no name to push under. The verdict row above STANDS: the image is not the"
        echo "   verdict. Set it and the next bank builds one; CI builds it meanwhile."
        return 0
    fi
    # THE REGISTRY, RECOVERED FROM THE ONE COMPOSITION rather than parsed a
    # second time out of the environment or the env file: `image_ref` is
    # `<registry>/djb-<service>:<tag>`, so the registry is what is left when the
    # rest is taken off. A second reader of `deploy/.env` here would be a second
    # answer to "which registry", which is the C1 disease this file argues about
    # everywhere else.
    registry="${ref_web%"/djb-web:${tag}"}"
    if [ "$registry" = "$ref_web" ] || [ -z "$registry" ]; then
        echo "image: not built — deploy/provision.sh image-ref answered '${ref_web}', which is"
        echo "   not <registry>/djb-web:${tag}. Nothing here will guess a registry. The row stands."
        return 0
    fi
    host="${registry%%/*}"
    # THE REGION IS DERIVED FROM THE HOST, never typed and never taken from this
    # Mac's own environment: an ECR registry name IS its account and its region
    # (`<account>.dkr.ecr.<region>.amazonaws.com`), and the token has to be
    # minted in the region the repositories are in. A coordinate that is not an
    # ECR host is a registry whose login this step does not know how to do.
    case "$host" in
    *.dkr.ecr.*.amazonaws.com) region="$(printf '%s' "$host" | awk -F. '{ print $4 }')" ;;
    *)
        echo "image: not built — ${host} is not an ECR registry, and this step only knows"
        echo "   how to mint an ECR token from a box's own role. The row above stands."
        return 0
        ;;
    esac
    # WHICH BOX. The acceptance box, whenever there is one: it is the one box in
    # the bank that is NOT part of the composed verdict (`run`, never `--leg`),
    # so nothing a build does to it can ever be confused with a measured leg,
    # and its own work finished in phase 3. Failing that, the first shard — by
    # then every shard's log and status are home and its box is idle too. Never
    # all of them: N boxes building one tree is N images of it (rejected in the
    # criteria by name).
    id="$BANK_BOXES_ACCEPT_ID"
    why="the acceptance box — the one box outside the composed verdict"
    if [ -z "$id" ]; then
        label="$(awk -F'\t' 'NF { print $1; exit }' "${BANK_BOXES_SINK}/plan.tsv" 2>/dev/null || true)"
        [ -z "$label" ] || id="$(cat "${BANK_BOXES_SINK}/${label}.id" 2>/dev/null || true)"
        why="shard ${label} — this bank has no acceptance box"
    fi
    if [ -z "$id" ]; then
        echo "image: not built — no box is still up to build on. The row above stands."
        return 0
    fi
    log="${BANK_BOXES_SINK}/image.log"
    cmd="$(bank_boxes_image_remote "$checkout" "$tag" "$registry" "$region" "$ref_web" "$ref_worker")"
    echo "pm_push --bank --on-boxes: building the image on ${id} (${why})."
    echo "  tag           ${tag}"
    echo "  refs          ${ref_web}"
    echo "                ${ref_worker}"
    rc=0
    "$BANK_BOXES_VB" run "$id" -- "$cmd" >"$log" 2>&1 </dev/null || rc=$?
    if [ "$rc" != "0" ]; then
        echo "image: NOT built (exit ${rc}) — and the verdict row above STANDS."
        echo "   An image is downstream of a verdict and never part of one: the gate measured"
        echo "   the tree, this step only names it in a registry. CI's images job builds a tag"
        echo "   the registry does not have, which is the fallback ADR deploy-4a argues from."
        sed 's/^/     | /' "$log" | tail -15
        return 0
    fi
    secs_web="$(bank_boxes_first_match "$log" '/^image: seconds / { print $4; exit }')"
    secs_worker="$(bank_boxes_first_match "$log" '/^image: seconds / { print $6; exit }')"
    dg_web="$(bank_boxes_first_match "$log" '/^image: digest web / { print $4; exit }')"
    dg_worker="$(bank_boxes_first_match "$log" '/^image: digest worker / { print $4; exit }')"
    platform="$(bank_boxes_first_match "$log" '/^image: platform / { print $3; exit }')"
    echo "image: ${tag} pushed (web ${secs_web:-?}s, worker ${secs_worker:-?}s)"
    # THE DIGEST THE REGISTRY HOLDS, read back through `provision.sh
    # image-digest` on the box AFTER the push — out of the registry and not out
    # of the build log, because the registry is what a deploy will pull. A
    # verifier replays the same command from its own clone and compares.
    echo "image: web ${dg_web:-<no digest read back>} worker ${dg_worker:-<no digest read back>}"
    echo "  platform      ${platform:-<unread>} — the box's own architecture, built natively"
    echo "  box log       ${log}"
    return 0
}

# bank_on_boxes <N> — the whole of it. Exit 0 with ONE row banked, 1 with a red
# shard named and NO row, 2 with the reason named and NO row. Boxes down on all
# three.
bank_on_boxes() {
    local n=$1
    local vb="$ROOT/scripts/verifier_box.sh"
    local tree tree8 declared listing lrc plan prc planned
    local label unit shard log rc treev composed wallv legwall
    local lost red foreign union pytest_wall failed
    local kbad needsv shardsv legsv lunit lshard lpasses laz kk pp seen kmax
    local az zonesfile ffwhat fflog
    local shard_legs listing_legs declared_legs missing extra uncovered labels drc
    local acheckout arung acmd arc hid passes planpasses onepass
    local proof_file pseed pworkers ppass1 ppass2 pmap member sawpasses
    local nsource nform nline
    [ -x "$vb" ] ||
        die "no executable verifier wrapper at ${vb} — there is nothing to bank on"
    BANK_BOXES_VB="$vb"

    # SOURCED HERE AND NOT AT FILE SCOPE, so an ordinary push is byte-for-byte
    # the script it was: the row writer is only needed where a row is written.
    # The precedent is `scripts/githooks/pre-push`, which sources the same file
    # to ask the same library the same question.
    [ -r "$ROOT/scripts/gate_ledger.sh" ] ||
        die "no ${ROOT}/scripts/gate_ledger.sh — a composed verdict has no writer without it"
    # shellcheck source=scripts/gate_ledger.sh
    . "$ROOT/scripts/gate_ledger.sh"

    # THE SINK IS OUTSIDE THE CHECKOUT, and it is checked rather than assumed:
    # a log written beside the tree is a file that moves the very hash this
    # bank is about to key a verdict on.
    BANK_BOXES_SINK="$(mktemp -d "${TMPDIR:-/tmp}/djb-bank-boxes.XXXXXX")" ||
        die "could not make an exit sink for the bank"
    case "$BANK_BOXES_SINK" in
    "$ROOT" | "$ROOT"/*)
        die "the exit sink (${BANK_BOXES_SINK}) landed inside ${ROOT}. Every byte in the
   checkout is part of the tree this bank keys a verdict on; point TMPDIR
   somewhere outside it."
        ;;
    esac
    BANK_BOXES_TSV="${BANK_BOXES_SINK}/boxes.tsv"
    : >"$BANK_BOXES_TSV"

    # THE KEY, READ ONCE, BEFORE ANYTHING IS LAUNCHED. It is the post-fold tree
    # of this clean checkout — the same function the gate and the pre-push hook
    # call, so there is one opinion about it and no second arithmetic.
    #
    # THE SUBSHELL IS THE `cd`, AND IT IS THE ONLY KIND THIS FILE HAS. The
    # header's first property is that no cwd is left behind in another checkout
    # for the next command to inherit; a subshell cannot leave one, and
    # `gate_measured_tree` reads the repository it is STANDING in.
    tree="$(cd "$ROOT" && gate_measured_tree)" ||
        die "could not read the measured tree of ${ROOT} — there is nothing to key a verdict on"
    [ -n "$tree" ] ||
        die "the measured tree of ${ROOT} read empty — there is nothing to key a verdict on"
    tree8="${tree:0:8}"
    declared="$(cd "$ROOT" && gate_full_legs)"
    [ -n "$declared" ] ||
        die "scripts/check.sh declares no FULL_LEGS — a composed row could name no leg set"

    # THE PASS COUNT IS DECIDED HERE, BEFORE THE LISTING IS EVEN READ, because
    # the plan below is what hands it to every shard and a plan that decided it
    # halfway through would be a bank with two kinds of shard in it. There is
    # exactly one input: whether this bank can have an acceptance box at all —
    # one pass per shard is only legal while a whole-suite two-pass proof is
    # running somewhere, and that somewhere is the acceptance box.
    arung="bank-${tree8}-acceptance"
    acheckout="$(bank_boxes_box_checkout || true)"
    planpasses=2
    [ -z "$acheckout" ] || planpasses=1
    # `--leak-proof nightly`: THE SECOND WHOLE PASS IS LAST NIGHT'S, READ, and
    # there is no acceptance box to launch. The shards run one pass exactly as
    # they do beside a box, and the row carries the nightly's form instead of
    # the box's id. READ HERE, BEFORE ANYTHING IS LAUNCHED, so the one source
    # line is at the top of the transcript where the operator is looking —
    # and a read that cannot look costs this bank nothing but the warning:
    # every form is honoured (report-only) and the teeth are at prod.
    nform=""
    nline=""
    if [ "$LEAK_PROOF" = "nightly" ]; then
        acheckout=""
        planpasses=1
        nsource="$(gate_nightly_source "${BANK_BOXES_SINK}/nightly" "$tree")"
        nform="${nsource%%$'\n'*}"
        nline="${nsource#*$'\n'}"
        nline="${nline%%$'\n'*}"
    fi

    BANK_BOXES_TREE8="$tree8"
    BANK_BOXES_ARUNG="$arung"

    echo "pm_push --bank --on-boxes ${n}: the full gate, one unit per verifier box."
    echo "  tree          ${tree}"
    echo "  sink          ${BANK_BOXES_SINK}"
    echo "  wrapper       ${vb}"
    # THE RIDER, SAID WHERE THE OPERATOR READS IT. The teardown is a trap and
    # no shell covers a SIGKILL, so every box this bank launches carries its
    # own ceiling and its own idle reaper — and the header is where somebody
    # who has just killed a bank looks to find out what is still running.
    echo "  box lifetime: ${BANK_BOX_TTL_HOURS}h hard, ${BANK_BOX_IDLE_MINUTES}m idle - the box reaps itself if the Mac dies"
    echo "  This Mac MEASURES NOTHING: it takes no machine lease and no pytest slot,"
    echo "  so every builder's --loop on this box keeps its own slot throughout."
    # THE ONE SOURCE LINE, and it is printed once: `leak-proof: nightly …` for
    # a green night no older than 24 h, `WARNING: leak-proof: …` naming red,
    # older than 24 h, or none (`gate_nightly_source` owns the four forms).
    [ -z "$nline" ] || echo "$nline"
    echo ""

    # --- the listing, and the plan derived from it --------------------------
    listing="${BANK_BOXES_SINK}/list-legs.tsv"
    lrc=0
    echo "pm_push --bank --on-boxes: reading the units — ${GATE} --list-legs"
    set +e
    "$GATE" --list-legs >"$listing" 2>"${BANK_BOXES_SINK}/list-legs.err"
    lrc=$?
    set -e
    if [ "$lrc" != "0" ]; then
        cat "${BANK_BOXES_SINK}/list-legs.err" >&2 || true
        die "./scripts/check.sh --list-legs exited ${lrc}. A gate that cannot say what its
   units are cannot be split across boxes, and a plan guessed from anything else
   is the hand list this repository refuses everywhere.
   Nothing was launched, nothing was banked and nothing was pushed."
    fi

    # --- the zone ring, read ONCE, before a box exists ----------------------
    #
    # BEFORE THE PLAN, because the plan is what spreads over it, and before
    # anything is launched, because a bank that could not read the ring would
    # otherwise launch every box into the subnet default — the single-zone
    # shape this exists to end, silently.
    zonesfile="${BANK_BOXES_SINK}/zones.txt"
    if ! bank_boxes_zones_read "$vb" "$zonesfile"; then
        cat "${zonesfile}.err" >&2 2>/dev/null || true
        die "could not read the zones — ${vb} zones answered nothing this bank can spread
   over. Spot capacity is a per-availability-zone fact and a bank in one zone is a
   bank that loses every box to one capacity event; rather than launch blind, this
   one refuses. Nothing was launched, nothing was banked and nothing was pushed."
    fi
    BANK_BOXES_ZONES="$(tr '\n' ' ' <"$zonesfile")"
    BANK_BOXES_ZONES="${BANK_BOXES_ZONES% }"
    echo "pm_push --bank --on-boxes: zones ${BANK_BOXES_ZONES}"
    echo "    read from the wrapper, never typed here: one box per zone in turn, so a"
    echo "    capacity event in one zone costs a shard and not a wave."
    echo ""

    plan="${BANK_BOXES_SINK}/plan.tsv"
    BANK_BOXES_PLAN="$plan"
    prc=0
    set +e
    bank_boxes_plan "$listing" "$n" "$planpasses" "$BANK_BOXES_ZONES" \
        >"$plan" 2>"${BANK_BOXES_SINK}/plan.err"
    prc=$?
    set -e
    if [ "$prc" != "0" ]; then
        cat "${BANK_BOXES_SINK}/plan.err" >&2 || true
        die "the bank could not draw a plan for ${n} boxes. Nothing was launched."
    fi
    planned="$(grep -c . "$plan" || true)"
    if [ "$planned" != "$n" ]; then
        die "the plan came to ${planned} shards for ${n} boxes. One shard is one box and
   one box is one shard; a plan that does not add up is never a smaller bank."
    fi
    # A PLAN ROW'S PASS COUNT IS PRINTED ONLY WHERE IT IS NOT THE DEFAULT.
    # `--passes 2` is what every shard has always run and what `check.sh`
    # normalises to nothing, so a two-pass bank's echo, argv and transcript are
    # the ones they were before the amendment; `--passes 1` is the departure
    # and it says so, beside the `--shard` it is only legal next to.
    echo "pm_push --bank --on-boxes: the plan, derived from that listing —"
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        if [ "$passes" = "1" ]; then
            echo "    ${label}	--leg ${unit}${shard:+ --shard ${shard}} --passes 1"
        else
            echo "    ${label}	--leg ${unit}${shard:+ --shard ${shard}}"
        fi
    done <"$plan"
    if [ "$planpasses" = "1" ] && [ "$LEAK_PROOF" != "nightly" ]; then
        echo "    ONE pass per suite shard (ADR gate-1's amendment): the whole-suite"
        echo "    two-pass leak proof runs on the acceptance box below, and the row is"
        echo "    not written until it comes home green."
    fi
    echo ""

    # --- the acceptance box, named before anything is launched --------------
    #
    # OUTSIDE THE PLAN, and the plan's own arithmetic above has already been
    # checked against `n`: this box is the (n+1)th machine and it takes no unit.
    # Its checkout path was read BEFORE the plan, because the plan's pass count
    # is decided by whether this box can exist.
    if [ "$LEAK_PROOF" = "nightly" ]; then
        BANK_BOXES_ACCEPT_NOTE="acceptance: no box — --leak-proof nightly: the second whole pass is the
   nightly's (${nform}), and so is the map: the fold harvests the latest green
   nightly's scripts/test_impact.json. This bank writes neither."
        echo "pm_push --bank --on-boxes: NO acceptance box — --leak-proof nightly."
        echo "    ONE pass per suite shard; the row names the nightly as its leak proof."
        echo ""
    elif [ -z "$acheckout" ]; then
        BANK_BOXES_ACCEPT_NOTE="acceptance: no box — deploy/verifier/bake.sh could not be read, so
   the box's checkout path is unknown. The map is NOT written and the loop keeps
   the closure scope; the bank is unaffected."
        echo "pm_push --bank --on-boxes: NO acceptance box — ${ROOT}/deploy/verifier/bake.sh"
        echo "    could not be read for the box's checkout path. The test-impact map will"
        echo "    not be rewritten by this bank; nothing else changes."
        echo ""
    else
        # THE NINTH BOX TAKES THE NEXT PLACE IN THE RING, after the last
        # shard: it is not in the plan (it carries no unit) but it is a box on
        # the same Spot market, and leaving it in zone one would put the box
        # the row now rests on in the most crowded place in the bank.
        BANK_BOXES_ACCEPT_AZ="$(bank_boxes_zone_at "$BANK_BOXES_ZONES" "$n")"
        echo "pm_push --bank --on-boxes: and ONE more box, outside the verdict —"
        echo "    ${arung}	the whole suite twice (contexts, then plain) -> scripts/test_impact.json"
        echo "    in ${BANK_BOXES_ACCEPT_AZ}"
        echo "    Its status is PRINTED and composed nowhere: a measurement may not refuse"
        echo "    a claim every shard passed."
        echo ""
    fi

    # --- the trap, armed BEFORE the first up --------------------------------
    exec 8>&1 9>&2
    trap 'bank_boxes_teardown' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    # --- phase 1: N boxes, each carrying the fold commit's tree -------------
    echo "pm_push --bank --on-boxes: bringing ${n} boxes up, concurrently."
    BANK_BOXES_WORKERS=""
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        (
            set +e
            # ONE LAUNCH BLOCK — `bank_boxes_up_one`, which is also what the
            # reclaim retry calls. It records the LAUNCHED id on the teardown
            # list before it reads the status, which is the only thing
            # standing between a probe that died and a box nobody can name.
            bank_boxes_up_one "$label" "bank-${tree8}-${label}" "$az" \
                "${BANK_BOXES_SINK}/up-${label}.log" 1
        ) &
        BANK_BOXES_WORKERS="${BANK_BOXES_WORKERS}${BANK_BOXES_WORKERS:+ }$!"
    done <"$plan"
    if [ -n "$acheckout" ]; then
        (
            set +e
            # THE SAME LAUNCH BLOCK, and NOT as a shard: this box is outside
            # the composed verdict, so the Spot→on-demand refusal that protects
            # the shards' quota is not its rule.
            bank_boxes_up_one acceptance "$arung" "$BANK_BOXES_ACCEPT_AZ" \
                "${BANK_BOXES_SINK}/up-acceptance.log" 0
        ) &
        BANK_BOXES_WORKERS="${BANK_BOXES_WORKERS}${BANK_BOXES_WORKERS:+ }$!"
    fi
    set +e
    wait
    set -e
    BANK_BOXES_WORKERS=""

    # THE ACCEPTANCE BOX'S OWN UP, READ FIRST AND SEPARATELY. A shard that would
    # not launch is exit 2 with nothing measured; this one is a printed line,
    # because there is no unit of the gate behind it to leave uncovered.
    if [ -n "$acheckout" ]; then
        BANK_BOXES_ACCEPT_ID="$(cat "${BANK_BOXES_SINK}/acceptance.id" 2>/dev/null || true)"
        if [ -z "$BANK_BOXES_ACCEPT_ID" ]; then
            # THE LAST CLAUSE IS THE PLAN'S, and it stopped being a constant
            # at ADR gate-1's amendment. Under a two-pass plan this box was
            # only ever the map's, so "every shard is unaffected" is true. Under
            # a ONE-pass plan every shard has already been handed `--passes 1`
            # on the strength of a proof that was going to run here — so the
            # bank is about to refuse, and a note that said the shards were
            # unaffected would be printed moments before the refusal that says
            # they were not. A message may not name a cause it has not proven,
            # and it may not deny one that is already certain.
            if [ "$planpasses" = "1" ]; then
                BANK_BOXES_ACCEPT_NOTE="acceptance: no box — it did not come up (see
   ${BANK_BOXES_SINK}/up-acceptance.log). The map is NOT written, and this bank will be
   REFUSED — one pass was measured and nothing can prove it left nothing behind."
            else
                BANK_BOXES_ACCEPT_NOTE="acceptance: no box — it did not come up (see
   ${BANK_BOXES_SINK}/up-acceptance.log). The map is NOT written and the loop keeps
   the closure scope; every shard is unaffected."
            fi
        fi
    fi

    failed=""
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        if [ "$(cat "${BANK_BOXES_SINK}/${label}.up.rc" 2>/dev/null || echo 2)" != "0" ]; then
            failed="${failed}${failed:+ }${label}"
        fi
    done <"$plan"
    if [ -n "$failed" ]; then
        bank_boxes_table
        echo "!! pm_push --bank --on-boxes: a box did not come up: ${failed}" >&2
        echo "   Their up logs are under ${BANK_BOXES_SINK}. Nothing was measured and no" >&2
        echo "   verdict was composed; every box that DID come up is being taken down." >&2
        if [ -z "${DJB_VERIFIER_ON_DEMAND_OK:-}" ]; then
            echo "   If a log above says Spot was refused: a shard NEVER falls back to on-demand" >&2
            echo "   on its own — N shards doing that is N on-demand boxes nobody asked for. To" >&2
            echo "   buy them deliberately, type the reason and run the bank again:" >&2
            echo "     DJB_VERIFIER_ON_DEMAND_OK=\"<why this wave is worth on-demand money>\" \\" >&2
            echo "       ./scripts/pm_push.sh --bank --on-boxes <N>" >&2
        fi
        exit 2
    fi

    # --- phase 2: one leg per box, the seam's exact argv --------------------
    echo "pm_push --bank --on-boxes: detaching one unit of the gate on each box."
    BANK_BOXES_WORKERS=""
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        (
            set +e
            lid="$(cat "${BANK_BOXES_SINK}/${label}.id")"
            printf '%s\n' "$(date +%s)" >"${BANK_BOXES_SINK}/${label}.began"
            # ONE DETACH, AND THE 255 RETRY LIVES INSIDE IT —
            # `bank_boxes_detach`, which the reclaim retry calls too, so the
            # seam's argv and the transport rule have one spelling.
            bank_boxes_detach "$label" "$lid" "$unit" "$shard" "$passes" \
                "${BANK_BOXES_SINK}/leg-${label}.log"
        ) &
        BANK_BOXES_WORKERS="${BANK_BOXES_WORKERS}${BANK_BOXES_WORKERS:+ }$!"
    done <"$plan"
    set +e
    wait
    set -e
    BANK_BOXES_WORKERS=""

    failed=""
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        if [ "$(cat "${BANK_BOXES_SINK}/${label}.leg.rc" 2>/dev/null || echo 2)" != "0" ]; then
            failed="${failed}${failed:+ }${label}"
        fi
    done <"$plan"
    if [ -n "$failed" ]; then
        bank_boxes_table
        echo "!! pm_push --bank --on-boxes: a unit could not be detached: ${failed}" >&2
        echo "   That is the transport or the wrapper, never a red tree: nothing was" >&2
        echo "   measured and no verdict was composed." >&2
        exit 2
    fi

    # --- phase 3: wait on every box -----------------------------------------
    #
    # A NON-ZERO `wait` IS NOT A REFUSAL HERE, and that is deliberate: `wait`
    # passes the shard's own gate status through, so a RED shard exits 1 and the
    # bank still has to fetch its log and name it. The authority on what each
    # shard decided is the `.rc` the box itself wrote, fetched below.
    echo "pm_push --bank --on-boxes: waiting on every shard (the wall is the slowest one)."
    BANK_BOXES_WORKERS=""
    # THE ACCEPTANCE RUN STARTS HERE AND NOT IN PHASE 2, so that it is
    # CONCURRENT with the shards' legs rather than in front of them: phase 2's
    # `wait` is a bare one and would block on it. `run` is synchronous — its
    # status is the remote command's, passed through — so the worker below is
    # the detach, the wait and the status all at once, and the bank's wall grows
    # only if this box outlasts the slowest shard.
    if [ -n "$BANK_BOXES_ACCEPT_ID" ]; then
        acmd="$(bank_boxes_acceptance_remote "$acheckout" "$arung")"
        BANK_BOXES_ACMD="$acmd"
        (
            set +e
            began="$(date +%s)"
            "$vb" run "$BANK_BOXES_ACCEPT_ID" -- "$acmd" \
                >"${BANK_BOXES_SINK}/acceptance.log" 2>&1 </dev/null
            printf '%s\n' "$?" >"${BANK_BOXES_SINK}/acceptance.rc"
            printf '%s\n' "$(($(date +%s) - began))" >"${BANK_BOXES_SINK}/acceptance.wall"
            # AND ITS FOUR FILES, HERE, while this box is unambiguously alive.
            # It finishes around six minutes and the slowest shard can be
            # twenty: a fetch joined to the others is a fetch from a box its
            # own idle reaper has already shut down.
            bank_boxes_fetch_acceptance_files \
                "$(tr -d ' \r\n' <"${BANK_BOXES_SINK}/acceptance.rc" 2>/dev/null || true)"
        ) &
        BANK_BOXES_WORKERS="${BANK_BOXES_WORKERS}${BANK_BOXES_WORKERS:+ }$!"
    fi
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        (
            set +e
            wid="$(cat "${BANK_BOXES_SINK}/${label}.id")"
            "$vb" wait "$wid" leg >"${BANK_BOXES_SINK}/wait-${label}.log" 2>&1 </dev/null
            printf '%s\n' "$?" >"${BANK_BOXES_SINK}/${label}.wait.rc"
            began="$(cat "${BANK_BOXES_SINK}/${label}.began" 2>/dev/null || echo 0)"
            printf '%s\n' "$(($(date +%s) - began))" >"${BANK_BOXES_SINK}/${label}.wall"
            bank_boxes_fetch_shard "$label" "$wid"
        ) &
        BANK_BOXES_WORKERS="${BANK_BOXES_WORKERS}${BANK_BOXES_WORKERS:+ }$!"
    done <"$plan"
    set +e
    wait
    set -e
    BANK_BOXES_WORKERS=""

    # --- everything is already home ----------------------------------------
    #
    # THERE IS NO FETCH PHASE, AND THAT IS THE POINT. Each phase-3 worker
    # fetched its own box's log the moment its own `wait` returned, and the
    # acceptance worker fetched its four files the moment its `run` did. A
    # phase that joined every shard first and fetched afterwards asked a box
    # that had been idle since minute two for a file, and the box's own idle
    # reaper had shut it down: `box gone (terminated)`, no log, and a leak
    # proof composed as LOST over a tree every shard passed.
    arc="$(tr -d ' \r\n' <"${BANK_BOXES_SINK}/acceptance.rc" 2>/dev/null || true)"

    # --- a reclaimed box is one more box, in the next zone, once ------------
    #
    # HERE, AFTER EVERY LOG IS HOME AND BEFORE ANYTHING IS COMPOSED. A reclaim
    # reaches this Mac at whichever subcommand met it first — the wait, the
    # acceptance run, or a fetch — so the sweep can only be honest once all
    # three have happened, and it must be over before the composition reads
    # the files it rewrites.
    bank_boxes_retry_reclaimed
    # THE NINTH BOX'S STATUS IS RE-READ, because a retry ran the whole
    # acceptance command again and `arc` is what decides whether its map is
    # reported as written.
    arc="$(tr -d ' \r\n' <"${BANK_BOXES_SINK}/acceptance.rc" 2>/dev/null || true)"

    # --- the map, reported BEFORE the composition ---------------------------
    #
    # BEFORE, so that it is printed on EVERY exit path: a bank that refuses is
    # exactly the bank whose operator most wants to know whether the
    # measurement beside it survived, and a line printed only on the green path
    # is a line nobody reads on the day it matters.
    bank_boxes_acceptance_report "$arc"

    # --- the composition ----------------------------------------------------
    #
    # ORDER MATTERS AND IT IS THE GATE'S OWN: 2 outranks a red. Every
    # could-not-look is gathered FIRST across all shards — a missing log, an
    # unreadable status, a 2, a reclaimed box, a foreign tree, a leg set that
    # does not add up — because a bank that reported "one shard red" over a
    # shard whose log it never read would be judging bytes nobody measured.
    lost=""
    red=""
    foreign=""
    union=""
    kbad=""
    pytest_wall=0
    # ONE PASS WAS PLANNED IFF THE PLAN SAYS SO, read back out of the plan file
    # rather than carried in a variable the launch set: the plan is what the
    # boxes were actually handed, and it is the only thing entitled to decide
    # whether this row may name a one-pass leg. Column FIVE, and `awk -F'\t'`
    # rather than `read`, because awk does not collapse a run of tabs and a
    # trailing empty column here is an ordinary empty field.
    onepass=0
    if awk -F'\t' '$5 == "1" { found = 1 } END { exit !found }' "$plan"; then
        onepass=1
    fi
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        log="${BANK_BOXES_SINK}/${label}.log"
        if [ ! -s "$log" ]; then
            lost="${lost}
     ${label}: no log came back from the box (fetch log: ${BANK_BOXES_SINK}/fetch-${label}.log)"
            continue
        fi
        rc="$(tr -d ' \r\n' <"${BANK_BOXES_SINK}/${label}.rc" 2>/dev/null || true)"
        treev="$(bank_boxes_first_match "$log" '/The tree it ran on was/ { t = $NF; sub(/\.$/, "", t); print t; exit }')"
        composed="$(bank_boxes_first_match "$log" '/^  composed-of: / { sub(/^  composed-of: /, ""); print; exit }')"
        # THE LEG'S OWN WALL, out of the leg's own banner. The Mac measures the
        # detach-to-return elapsed, which is the leg PLUS a transport; the
        # number `took=` means everywhere else in this ledger is the leg's, so
        # that is the one recorded when the log carries it.
        legwall="$(bank_boxes_first_match "$log" '/^ok: all checks passed \(/ { t = $NF; sub(/^\(/, "", t); sub(/s\)$/, "", t); print t; exit }')"
        case "${legwall:-}" in
        '' | *[!0-9]*) legwall="$(cat "${BANK_BOXES_SINK}/${label}.wall" 2>/dev/null || echo 0)" ;;
        esac
        case "${legwall:-}" in '' | *[!0-9]*) legwall=0 ;; esac
        printf '%s\n' "$legwall" >"${BANK_BOXES_SINK}/${label}.legwall"
        printf '%s\n' "${treev:-}" >"${BANK_BOXES_SINK}/${label}.tree"
        if grep -qF 'box reclaimed' "${BANK_BOXES_SINK}/wait-${label}.log" 2>/dev/null; then
            lost="${lost}
     ${label}: the box was RECLAIMED mid-flight — the verdict is LOST, never red"
            continue
        fi
        case "$rc" in
        0 | 1) ;;
        2)
            lost="${lost}
     ${label}: the shard exited 2 — enforcement broken on that box, which outranks a pass"
            continue
            ;;
        *)
            lost="${lost}
     ${label}: no exit status came back from the box (read '${rc:-<empty>}')"
            continue
            ;;
        esac
        if [ -z "$treev" ]; then
            lost="${lost}
     ${label}: the log names no tree — nothing says WHICH bytes that shard measured"
            continue
        fi
        if [ "$treev" != "$tree" ]; then
            foreign="${foreign}
     ${label}: the box ran ${treev}
              this bank keys on ${tree}"
            continue
        fi
        if [ -z "$composed" ]; then
            lost="${lost}
     ${label}: the log carries no composed-of: line — nothing says WHICH legs that shard ran"
            continue
        fi
        union="${union}${union:+,}${composed}"
        # WHAT THE SHARD SAYS IT RAN, AGAINST WHAT THE PLAN TOLD IT TO RUN.
        # The seam grammar is `<leg>[/<passes>]` and an absent suffix means 2,
        # so a shard planned at one pass whose banner names a bare
        # `pytest-x2` either ignored the flag or is a gate that predates it —
        # and a row composed over it would say one pass ran twice, or two ran
        # once. Neither is a claim anybody can act on, so it is exit 2 and no
        # row, beside the other ways the plan and the shards can disagree.
        if [ -n "$passes" ]; then
            sawpasses=""
            member=""
            for member in $(printf '%s' "$composed" | tr ',' ' '); do
                case "$member" in
                "$BANK_SUITE_LEG")
                    sawpasses=2
                    break
                    ;;
                "${BANK_SUITE_LEG}"/*)
                    sawpasses="${member#*/}"
                    break
                    ;;
                *) member="" ;;
                esac
            done
            if [ -z "$sawpasses" ]; then
                kbad="${kbad}
     ${unit}: planned --passes ${passes} and the shard's composed-of: names no ${BANK_SUITE_LEG} member at all (${label})"
            elif [ "$sawpasses" != "$passes" ]; then
                kbad="${kbad}
     ${unit}: planned --passes ${passes} and the shard reports ${member} (${label})"
            fi
        fi
        if [ "$rc" = "1" ]; then
            red="${red}
     ${label}: --leg ${unit}${shard:+ --shard ${shard}} on $(cat "${BANK_BOXES_SINK}/${label}.id" 2>/dev/null) exited 1"
            # AND WHICH TEST, WHEN THE LEG WAS ONE THAT HAS TESTS. The
            # condition is the LOG and not the unit's name: a `static` leg
            # that reddened has no failing test to name, and a line saying
            # `none named` under it would be noise claiming to be evidence.
            # A pytest leg's log carries pytest's own short summary, so the
            # question "is there a nodeid here" answers itself.
            if grep -q '^FAILED ' "$log"; then
                red="${red}
              $(bank_boxes_first_failing "$log" "$label" "$(bank_boxes_log_seed "$log")")"
            fi
        fi
        case ",${unit}," in
        *,pytest-x2,*)
            wallv="$legwall"
            [ "$wallv" -le "$pytest_wall" ] || pytest_wall="$wallv"
            ;;
        esac
    done <"$plan"

    # THE SHARD'S OWN `k` IS CHECKED AGAINST THE LISTING, not against the plan
    # that produced it: an N-capable unit with no shard, or a k outside 1..P, is
    # a unit somebody would have run a part of with no parts. `kbad` is
    # initialised with the rest of the composition's accumulators above,
    # because the pass-count disagreement is the same kind of finding and
    # reaches the same refusal.
    while IFS='	' read -r unit needsv shardsv legsv; do
        [ -n "$unit" ] || continue
        seen=0
        kmax=0
        while IFS='	' read -r label lunit laz lshard lpasses; do
            [ "$lunit" = "$unit" ] || continue
            seen=$((seen + 1))
            case "$shardsv" in
            N-capable)
                case "$lshard" in
                '')
                    kbad="${kbad}
     ${unit}: shardable and its shard ${label} carries no k/N"
                    continue
                    ;;
                esac
                kk="${lshard%%/*}"
                pp="${lshard##*/}"
                kmax="$pp"
                if [ "$kk" -lt 1 ] || [ "$kk" -gt "$pp" ]; then
                    kbad="${kbad}
     ${unit}: shard ${lshard} is outside 1..${pp}"
                fi
                ;;
            *)
                [ -z "$lshard" ] || kbad="${kbad}
     ${unit}: indivisible, and ${label} was handed --shard ${lshard}"
                ;;
            esac
        done <"$plan"
        if [ "$seen" = "0" ]; then
            kbad="${kbad}
     ${unit}: the listing declares it and the plan gave it no box"
        fi
        case "$shardsv" in
        N-capable)
            if [ "$kmax" != "0" ] && [ "$seen" != "$kmax" ]; then
                kbad="${kbad}
     ${unit}: split ${kmax} ways and only ${seen} of those shards is in the plan"
            fi
            ;;
        esac
    done <"$listing"

    # THE LEG SETS, ADDED UP. Three sets have to agree before a row is written:
    # what the shards say they ran, what the listing says the units are made of,
    # and what this gate declares a full run to be. The first two are compared
    # for EQUALITY and the third for COVER — `gate_ledger_lookup`'s own
    # semantic, and the honest one, because a unit's composed-of names the
    # drives a shard walks as well as its legs, so the listing's union is a
    # superset of FULL_LEGS by construction.
    #
    # AND THE MEMBER GRAMMAR IS `<leg>[/<passes>]`, so the pass count comes OFF
    # before the three sets are compared. It is not part of the identity of a
    # leg — it is a property of the RUN, checked against the plan one loop up,
    # and the whole of its meaning downstream is the row's `leak-proof=` field.
    # Left on, a one-pass shard's `pytest-x2/1` would read as a leg the listing
    # has never heard of AND as a declared leg no shard covered: two refusals,
    # both saying "the legs do not add up" about a bank whose legs add up
    # exactly. `gate_ledger_lookup` is where the suffix means something, and it
    # reads the same grammar there.
    shard_legs="$(printf '%s' "$union" | tr ',' '\n' | sed 's|/[0-9][0-9]*$||' |
        LC_ALL=C sort -u | grep -v '^$' || true)"
    listing_legs="$(awk -F'\t' 'NF { print $4 }' "$listing" | tr ',' '\n' | LC_ALL=C sort -u | grep -v '^$' || true)"
    declared_legs="$(printf '%s' "$declared" | tr ',' '\n' | LC_ALL=C sort -u | grep -v '^$' || true)"
    missing="$(comm -13 <(printf '%s\n' "$shard_legs") <(printf '%s\n' "$listing_legs") | grep -v '^$' || true)"
    extra="$(comm -23 <(printf '%s\n' "$shard_legs") <(printf '%s\n' "$listing_legs") | grep -v '^$' || true)"
    uncovered="$(comm -13 <(printf '%s\n' "$shard_legs") <(printf '%s\n' "$declared_legs") | grep -v '^$' || true)"

    # --- the LEAK PROOF, gathered like a shard's ----------------------------
    #
    # BEFORE `lost` IS DECIDED AND ONLY UNDER A ONE-PASS PLAN. Every shard
    # above ran half the belt this bank claims; the other half ran on the
    # acceptance box, and a row written without reading it would be a green
    # vouching for one pass while naming two. So the proof enters the SAME two
    # accumulators every shard enters: unreadable is `lost` (exit 2, no row —
    # could-not-look outranks a pass), a red pass is `red` (exit 1, no row).
    #
    # AND `map=` ENTERS NEITHER. It is the measurement half of the same file
    # (see the acceptance box's header): a coverage writer that died costs the
    # loop one wave of its map and may not refuse a tree whose every pass was
    # green. The two roles separate exactly here, at the `rc` each one wrote.
    proof_file="${BANK_BOXES_SINK}/acceptance.proof"
    # UNDER `--leak-proof nightly` THERE IS NO BOX TO READ: the nightly's form
    # was read before the launch and is the row's field as it stands.
    if [ "$onepass" = "1" ] && [ "$LEAK_PROOF" != "nightly" ]; then
        pseed=""
        ppass1=""
        ppass2=""
        pmap=""
        pworkers=""
        if [ -n "$BANK_BOXES_ACCEPT_ID" ] && [ -s "$proof_file" ]; then
            pseed="$(bank_boxes_proof_field "$proof_file" seed)"
            pworkers="$(bank_boxes_proof_field "$proof_file" workers)"
            ppass1="$(bank_boxes_proof_field "$proof_file" pass1)"
            ppass2="$(bank_boxes_proof_field "$proof_file" pass2)"
            pmap="$(bank_boxes_proof_field "$proof_file" map)"
        fi
        # UNPARSABLE IS THE SAME ANSWER AS ABSENT, and it is reduced to one
        # state here: an empty seed. A proof missing its seed proves nothing
        # (two passes in different orders are not a pair), and an `rc` that is
        # not a decimal is a status nobody can read as green or red.
        if [ -z "$ppass1" ] || [ -z "$ppass2" ]; then
            pseed=""
        fi
        case "$ppass1" in *[!0-9]*) pseed="" ;; esac
        case "$ppass2" in *[!0-9]*) pseed="" ;; esac
        if [ -z "$pseed" ]; then
            lost="${lost}
     acceptance: the leak proof could not be read — one pass was measured and nothing proved it left nothing behind.
              Every pytest shard was planned --passes 1 under ADR gate-1's amendment, so
              the whole-suite two-pass run on the acceptance box IS the belt, and this
              bank cannot say whether it ran. Box: ${BANK_BOXES_ACCEPT_ID:-<none came up>}; the
              fetch log is ${BANK_BOXES_SINK}/fetch-proof.log and the box's own log
              is ${BANK_BOXES_SINK}/acceptance.log."
        else
            echo "acceptance: the leak proof — seed=${pseed} workers=${pworkers:-$BANK_PROOF_WORKERS} pass1=${ppass1} pass2=${ppass2} map=${pmap:-?}"
            echo "  from ${BANK_BOXES_ACCEPT_ID}, the whole suite twice under one seed. pass1= and"
            echo "  pass2= are the CLAIM this row rests on; map= is a measurement and decides nothing."
            if [ "$ppass1" != "0" ] || [ "$ppass2" != "0" ]; then
                # WHICH PASS, AND THEREFORE WHICH LOG. A red pass 2 beside a
                # green pass 1 is the leak the belt exists to catch, so that
                # is the log to name; a red pass 1 is an ordinary failure and
                # its own log is the one that holds it.
                if [ "$ppass2" != "0" ]; then
                    ffwhat="pass 2"
                    fflog="${BANK_BOXES_SINK}/pass2.log"
                else
                    ffwhat="pass 1"
                    fflog="${BANK_BOXES_SINK}/pass1.log"
                fi
                # THE PROSE NAMES CANDIDATES, NEVER ONE CAUSE — the one
                # sentence `leak_proof_verdict` owns, and `--proof` prints the
                # same line on the nightly runner.
                red="${red}
     acceptance: the leak proof is RED on ${BANK_BOXES_ACCEPT_ID} — pass1=${ppass1} pass2=${ppass2}
              under seed ${pseed}. Its whole log is ${BANK_BOXES_SINK}/acceptance.log.
              $(leak_proof_verdict "$ppass1" "$ppass2" "$pseed" "${pworkers:-$BANK_PROOF_WORKERS}")
              $(bank_boxes_first_failing "$fflog" "$ffwhat" "$pseed")"
            fi
        fi
    fi

    bank_boxes_table

    if [ -n "$lost" ]; then
        echo "!! pm_push --bank --on-boxes: a shard's verdict could not be read. NO ROW WAS" >&2
        echo "   WRITTEN and nothing was pushed — a bank is a claim about every unit, and 2" >&2
        echo "   (could not look) outranks any pass:${lost}" >&2
        exit 2
    fi
    if [ -n "$foreign" ]; then
        echo "!! pm_push --bank --on-boxes: a box measured a DIFFERENT tree. NO ROW WAS" >&2
        echo "   WRITTEN and nothing was pushed:${foreign}" >&2
        echo "   A verdict composed from those shards would vouch for bytes no box ran." >&2
        exit 2
    fi
    if [ -n "$kbad" ]; then
        echo "!! pm_push --bank --on-boxes: the plan and the unit listing disagree. NO ROW" >&2
        echo "   WAS WRITTEN and nothing was pushed:${kbad}" >&2
        exit 2
    fi
    if [ -n "$missing" ] || [ -n "$extra" ] || [ -n "$uncovered" ]; then
        echo "!! pm_push --bank --on-boxes: the shards' legs do not add up to a full gate." >&2
        echo "   NO ROW WAS WRITTEN and nothing was pushed." >&2
        [ -z "$missing" ] || {
            echo "   in the listing's units and in NO shard's composed-of:" >&2
            printf '     %s\n' $missing >&2
        }
        [ -z "$extra" ] || {
            echo "   in a shard's composed-of and in NO unit of the listing:" >&2
            printf '     %s\n' $extra >&2
        }
        [ -z "$uncovered" ] || {
            echo "   declared by FULL_LEGS and covered by no shard:" >&2
            printf '     %s\n' $uncovered >&2
        }
        exit 2
    fi
    if [ -n "$red" ]; then
        echo "!! pm_push --bank --on-boxes: the gate is RED. NO ROW WAS WRITTEN and nothing" >&2
        echo "   was pushed:${red}" >&2
        echo "   Each shard's whole log is under ${BANK_BOXES_SINK}." >&2
        exit 1
    fi

    # --- ONE row, written by the one writer ---------------------------------
    labels=""
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        labels="${labels}${labels:+,}${label}"
    done <"$plan"
    # `waited=` is left to its own default of 0, which is the honest answer: this
    # bank took neither the lease nor a slot, so it queued for nothing.
    DJB_GATE_CALLER=pm-bank
    GATE_RUN_SANCTION="push-wall boxes=${n} shards=${labels}"
    GATE_PYTEST_TOOK="$pytest_wall"
    # THE ROW SAYS WHAT RAN, AND UNDER A ONE-PASS PLAN THAT IS TWO EDITS, MADE
    # HERE AND NOWHERE ELSE. The legs field's suite member gains its pass count
    # in the seam grammar `<leg>[/<passes>]`, and the row gains the box that
    # ran the belt instead. A row that said `pytest-x2` over one pass would be
    # a green vouching for more than ran — the one failure this ledger exists
    # to prevent — and `gate_ledger_lookup` refuses `pytest-x2/1` unless the
    # proof beside it is green, so the two fields are written together or the
    # row is not honoured.
    #
    # ONE SITE, AND THE REST OF `FULL_LEGS` IS UNTOUCHED: the substitution is
    # anchored on the commas around the member, so a leg whose name merely
    # CONTAINS the suite leg's is not rewritten.
    if [ "$onepass" = "1" ]; then
        declared=",${declared},"
        declared="${declared/,${BANK_SUITE_LEG},/,${BANK_SUITE_LEG}/1,}"
        declared="${declared#,}"
        declared="${declared%,}"
        if [ "$LEAK_PROOF" = "nightly" ]; then
            GATE_RUN_LEAK_PROOF="$nform"
        else
            GATE_RUN_LEAK_PROOF="acceptance:${BANK_BOXES_ACCEPT_ID} rc=0"
        fi
    fi
    # AND A RECORDER THAT REFUSED IS EXIT 2, NEVER A PUSH. `gate_ledger_record`
    # returns 1 when the proof field will not parse, and it writes nothing in
    # that case by design — so a caller that carried on would push a tree with
    # no row at all behind it.
    if ! (cd "$ROOT" && gate_ledger_record "$tree" "$declared"); then
        die "the verdict ledger could not be written. Every shard was green and nothing
   was pushed: a green nobody can read is not a verdict."
    fi
    echo "pm_push --bank --on-boxes: verdict banked for tree ${tree}"
    echo "  caller=pm-bank sanction=push-wall boxes=${n} shards=${labels}"
    if [ "$onepass" = "1" ]; then
        echo "  legs=${declared}"
        echo "  leak-proof=${GATE_RUN_LEAK_PROOF}"
    fi
    echo "  The pre-push hook will honour it and cost seconds."

    # --- the drive rows come home, before the boxes go ----------------------
    #
    # A DRIVE ROW IS A CACHE THAT IS WORTH CARRYING BETWEEN MACHINES OF ONE
    # IMAGE, and a bank's shards are exactly that: N boxes cut from one image,
    # each of which has just driven some of the same drives the next bank will
    # drive again. The rows live in the box's `.git/djb-gate-verdicts` and the
    # box is about to be terminated, so this is the only moment they exist
    # anywhere the Mac can reach — and `push` (which sends this checkout's
    # drive rows OUT to the next box) has nothing image-keyed to send if none
    # ever came back. A measured bank re-drove every drive with the selftest
    # unit at over twenty minutes.
    #
    # AFTER THE ROW AND BEFORE THE DOWN, and only on a green: a red bank's
    # shards are not a cache anybody should reuse, and a harvest before the
    # composition would be work done for a bank that is about to refuse.
    #
    # THROUGH THE WRAPPER'S OWN DOOR. `harvest-drives <id> <tree>` reaches
    # `harvest_drive_rows`, which owns the tree filter, the already-here rule
    # and the ledger path; fetching the file here and appending it would be a
    # second opinion about all three. It never refuses — a carrier that could
    # not read costs a re-drive, never a verdict — so its status is not
    # consulted and the bank's own green stands whatever it says.
    #
    # AND A HOMING THAT FAILED IS SAID, PER BOX, WITH A COUNT. The harvest
    # never refuses — its status decides nothing about the verdict — but a
    # Spot reclaim between the leg and this call takes the box's rows with it,
    # and before this line that loss was exit 0 and silence: the next bank
    # re-drove every drive on that box and nobody could say why. So each box's
    # own status is read (its output is kept in the sink and echoed), a box
    # that did not answer is `LOST` with the reclaim status the wrapper named
    # (or `exit <n>` when it named none), and the count says how many of the
    # plan's boxes brought their rows home.
    echo "pm_push --bank --on-boxes: bringing the shards' drive rows home."
    local hrc hboxes=0 hhomed=0 hwhy
    while IFS='	' read -r label unit az shard passes; do
        [ -n "$label" ] || continue
        hboxes=$((hboxes + 1))
        hid="$(cat "${BANK_BOXES_SINK}/${label}.id" 2>/dev/null || true)"
        if [ -z "$hid" ]; then
            echo "  drive rows from ${label}: LOST (no box id in the sink) — the next bank re-drives them"
            continue
        fi
        hrc=0
        "$BANK_BOXES_VB" harvest-drives "$hid" "$tree" </dev/null \
            >"${BANK_BOXES_SINK}/harvest-${label}.log" 2>&1 || hrc=$?
        cat "${BANK_BOXES_SINK}/harvest-${label}.log" 2>/dev/null || true
        if [ "$hrc" = "0" ]; then
            hhomed=$((hhomed + 1))
            continue
        fi
        if bank_boxes_saw_reclaim "${BANK_BOXES_SINK}/harvest-${label}.log"; then
            hwhy="$(bank_boxes_reclaim_status "${BANK_BOXES_SINK}/harvest-${label}.log")"
        else
            hwhy="exit ${hrc}"
        fi
        echo "  drive rows from ${label}: LOST (${hwhy}) — the next bank re-drives them"
    done <"$plan"
    echo "  drive rows homed: ${hhomed}/${hboxes} boxes"

    # --- the image, built once, from the banked tree ------------------------
    #
    # AFTER THE HARVEST AND BEFORE THE DOWN. After, because the rows are a
    # cache every later bank wants and a build that hung would otherwise cost
    # them; before, because the boxes are the only machines in this system that
    # hold the banked tree and the right architecture, and in four lines' time
    # they do not exist. AFTER THE ROW, always: `gate_ledger_record` returned 0
    # above, so nothing is ever pushed to a registry for a tree the gate has not
    # passed — which is ADR deploy-4 (b)'s invariant, moved from `needs:
    # verdict` onto the row itself.
    bank_boxes_image "$acheckout" "tree-${tree:0:12}"

    # --- the boxes, down, before the push -----------------------------------
    #
    # HERE AND NOT IN THE TRAP, because this script ends in `exec git push` and
    # an `exec` never runs an EXIT trap. The list is emptied as it is walked, so
    # the trap below has nothing left to do either way.
    echo "pm_push --bank --on-boxes: taking every box down."
    drc=0
    bank_boxes_down_all || drc=$?
    trap - EXIT INT TERM
    exec 8>&- 9>&-
    if [ "$drc" != "0" ]; then
        echo "!! pm_push --bank --on-boxes: the verdict IS banked for ${tree} and a box did" >&2
        echo "   NOT go down. Nothing was pinned and nothing was pushed: deal with the box" >&2
        echo "   first, then ./scripts/pm_push.sh (no --bank) honours the row above." >&2
        exit 2
    fi
    return 0
}

# --- --bank: the verdict, earned in front of the operator --------------------
#
# WHERE IT SITS. After every refusal that costs nothing — a bad commit-ish, no
# pm-push worktree, a dirty pm-push — and before anything is pinned or pushed.
# An eight-minute gate that runs and THEN discovers there is no worktree to pin
# is an expensive way to learn about a typo.
#
# WHAT IT REFUSES: A BANK IS A CLAIM ABOUT A TREE, so the tree it measures must
# be the tree that is about to be pushed. `check.sh` keys its verdict on the
# WORKING TREE it measures here, and the pre-push hook consults the ledger with
# the same key. A DIRTY checkout is therefore refused — the verdict would be
# keyed on a tree that exists in nobody's history while the push carried a
# different one. The other half of that rule is enforced up at the argument:
# `--bank` takes no commit, so what is measured is always this checkout's HEAD.
#
# Exit 2 (could not get as far as pushing) rather than a red gate: nothing was
# measured and nothing was judged.
if [ "$BANK" = "1" ]; then
    GATE="$ROOT/scripts/check.sh"
    [ -x "$GATE" ] || die "no executable gate at ${GATE} — there is nothing to bank with"

    # --- THE FOLD, FIRST, AND THE BANK IS OF THE POST-FOLD HEAD --------------
    #
    # WHERE IT SITS, AND WHY IT CANNOT SIT ANYWHERE ELSE. The fold regenerates
    # this checkout's derived files and COMMITS them. The gate below keys its
    # verdict on the working tree it measures. So the fold must run BEFORE the
    # gate: folding after it would be worse than not folding at all, because the
    # verdict would vouch for a tree the fold then changed — a banked green over
    # content nobody measured, which is the one failure the ledger exists to
    # prevent.
    #
    # It also sits before the cleanliness check below, which is what lets the
    # fold's own commit land and the bank still see a clean tree. A fold that
    # ran after that check would leave the tree dirty at exactly the moment the
    # bank refuses a dirty tree.
    #
    # AND THE SHA IS RE-READ AFTERWARDS. `SHA` was resolved above, before any of
    # this, and `--bank` takes no commit argument — so it is pre-fold HEAD. The
    # fold may add a commit. Re-reading it here is what makes "bank the
    # post-fold HEAD" true rather than intended: the INTENDED TIP line, the
    # RANGE, the pin and the push all read the re-resolved value.
    #
    # It also closes the byte-pin's missing tooth by construction: nothing in
    # `check.sh` or `fe_gate.sh` compares the committed generated client to a
    # fresh regeneration, so a stale contract banks green today. The fold
    # regenerates it and either commits the shift under its own subject or
    # refuses — never a silent green bank over a stale contract.
    if [ "$NO_FOLD" = "1" ]; then
        echo "pm_push --bank: ** --no-fold — THE DERIVED FILES WERE NOT REGENERATED. **"
        echo "  The contract, the secret baseline and the budget floors are whatever is"
        echo "  committed. If the gate below reddens on a stale client or on a budget,"
        echo "  that is THIS FLAG and not the tree."
        echo ""
    else
        FOLD="$ROOT/scripts/pm_fold.sh"
        [ -x "$FOLD" ] ||
            die "no executable fold at ${FOLD} — pass --no-fold to bank without one"
        echo "pm_push --bank: folding ${ROOT} before the gate — ${FOLD}"
        echo "  It regenerates the derived files and commits AT MOST the paths on its own"
        echo "  typed list; anything it modifies outside that list is its own exit 2 naming"
        echo "  the file, with nothing committed."
        FOLD_RC=0
        "$FOLD" || FOLD_RC=$?
        if [ "$FOLD_RC" != "0" ]; then
            echo "!! pm_push --bank: the fold exited ${FOLD_RC}." >&2
            echo "   2 is 'could not fold' — a dirty tree, a generator that failed, or a" >&2
            echo "   file modified outside the derived list. Read its output above." >&2
            echo "   Nothing was banked, nothing was pinned and nothing was pushed." >&2
            exit "$FOLD_RC"
        fi
        SHA="$(git -C "$ROOT" rev-parse --verify "HEAD^{commit}")" ||
            die "could not re-read HEAD after the fold"
        echo "pm_push --bank: banking the POST-FOLD HEAD $(git -C "$ROOT" rev-parse --short "$SHA")."
        echo ""
    fi

    if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
        echo "!! pm_push --bank: ${ROOT} has uncommitted changes." >&2
        git -C "$ROOT" status --short >&2
        echo "   A banked verdict is keyed on the tree the gate measured, and that tree" >&2
        echo "   would not be the one this push carries. Commit or stash first." >&2
        echo "   Nothing was banked, nothing was pinned and nothing was pushed." >&2
        exit 2
    fi
    # --- THE DOCS-ONLY ROAD, BEFORE EITHER ARM ------------------------------
    #
    # WHERE IT SITS, AND WHY IT CANNOT SIT ANYWHERE ELSE. After the fold (so the
    # delta is the one the push carries) and after the clean-tree refusal (so
    # "the tree" is a thing that exists in history); BEFORE the arms split, and
    # therefore before a lease, a pytest slot or a single `verifier_box.sh up`.
    # That ordering IS the saving: a docs-only push that decided this after
    # launching five boxes would have spent the money it exists to save.
    #
    # WHAT IT IS. When every path changed since the nearest MEASURED ancestor
    # tree is on the declared list (`GATE_DOCS_ONLY_PATHS`, argued in
    # `scripts/gate_ledger.sh`), the readers those bytes really have are run
    # HERE, on this Mac, and an ORDINARY full row is written for the tree about
    # to be pushed. Seconds, not the ~25 minutes a bank costs, for a tree whose
    # measured surface did not move.
    #
    # EVERY OTHER OUTCOME IS THE FULL BANK, AND EVERY ONE OF THEM SAYS SO. A
    # path off the list, a docs path a module under `apps/` or `config/` really
    # opens, a source row that is not honoured, a reader that could not look:
    # each prints its cause and ends in "full bank", and the arm below runs
    # exactly as it did. A reader that went RED is the one outcome that is not a
    # full bank — it is a red tree, exit 1, no row and no push.
    DOCS_ONLY_BANKED=0
    if [ -n "${DJB_BANK_MEASURE:-}" ] && [ "${DJB_BANK_MEASURE}" != "0" ]; then
        # THE MEASURING VALVE. The reuse's whole claim is that the readers it
        # runs are the ones that could have said anything about these bytes, and
        # the only way to check that claim is to measure the tree in full and
        # compare. One typed variable turns the road off for one run, and it
        # says so in the transcript rather than in somebody's memory.
        echo "pm_push --bank: docs-only reuse SKIPPED by DJB_BANK_MEASURE — measuring."
        echo ""
    else
        [ -r "$ROOT/scripts/gate_ledger.sh" ] ||
            die "no ${ROOT}/scripts/gate_ledger.sh — the docs-only road has no reader without it"
        # shellcheck source=scripts/gate_ledger.sh
        . "$ROOT/scripts/gate_ledger.sh"
        DOCS_T0="$(date +%s)"
        DOCS_READERS_TOOK=0
        DOCS_PLAN_RC=0
        # THE PLAN READS THIS CHECKOUT, so it is run STANDING IN IT. Every
        # line after this block addresses git with `-C`, so moving the working
        # directory here changes nothing downstream.
        cd "$ROOT" || die "could not stand in ${ROOT}"
        # CALLED PLAINLY, NEVER IN `$(...)`: its whole answer is six globals,
        # and a substitution's copy of a global dies with the subshell.
        gate_docs_only_plan "$SHA" || DOCS_PLAN_RC=$?
        if [ "$DOCS_PLAN_RC" != "0" ]; then
            echo "pm_push --bank: ${GATE_DOCS_ONLY_WHY}"
            echo ""
        else
            echo "pm_push --bank: docs-only? yes — ${GATE_DOCS_ONLY_N} path(s) changed since the"
            echo "  measured tree ${GATE_DOCS_ONLY_SOURCE}, every one of them on the declared list."
            echo "  readers, DERIVED from what those paths are read by:"
            printf '    %s\n' ${GATE_DOCS_ONLY_READERS//,/ }
            DOCS_RED=""
            DOCS_CANNOT=""
            for DOCS_READER in ${GATE_DOCS_ONLY_READERS//,/ }; do
                DOCS_R0="$(date +%s)"
                DOCS_RC=0
                case "$DOCS_READER" in
                */*)
                    # A DRIVE IS RUN THE WAY THE SELFTEST LEG RUNS IT — from the
                    # checkout root, by its own path, under its own shebang.
                    "./${DOCS_READER}" || DOCS_RC=$?
                    ;;
                *)
                    "$GATE" --leg "$DOCS_READER" || DOCS_RC=$?
                    ;;
                esac
                DOCS_R1="$(date +%s)"
                DOCS_READERS_TOOK=$((DOCS_READERS_TOOK + DOCS_R1 - DOCS_R0))
                echo "  reader ${DOCS_READER}: $((DOCS_R1 - DOCS_R0))s (exit ${DOCS_RC})"
                if [ "$DOCS_RC" = "1" ]; then
                    DOCS_RED="$DOCS_READER"
                    break
                fi
                if [ "$DOCS_RC" != "0" ]; then
                    DOCS_CANNOT="$DOCS_READER exited ${DOCS_RC}"
                    break
                fi
            done
            if [ -n "$DOCS_RED" ]; then
                echo "!! pm_push --bank: docs-only readers RED: ${DOCS_RED}." >&2
                echo "   That is a red tree and not a cheaper road: NO ROW was written, nothing" >&2
                echo "   was pinned and nothing was pushed. Fix it and run the bank again." >&2
                exit 1
            fi
            if [ -n "$DOCS_CANNOT" ]; then
                echo "pm_push --bank: could not look — ${DOCS_CANNOT} — full bank."
                echo "  2 is enforcement broken, and a reuse resting on a reader that could not"
                echo "  look would be a green nobody measured."
                echo ""
            else
                # --- ONE row, written by the one writer -------------------------
                #
                # AN ORDINARY FULL ROW. The legs field and `leak-proof=` are
                # COPIED FROM THE SOURCE ROW rather than re-derived: this run
                # measured no leg, so the claim it carries forward is the source
                # row's claim and nothing stronger. `gate_ledger_lookup` then
                # covers it exactly as it covers the row it came from, and the
                # pre-push hook honours it unedited.
                DOCS_TREE="$(cd "$ROOT" && gate_measured_tree)" ||
                    die "could not read the measured tree for the docs-only row"
                DJB_GATE_CALLER=pm-bank
                GATE_RUN_SANCTION="docs-only from=${GATE_DOCS_ONLY_SOURCE} paths=${GATE_DOCS_ONLY_N} readers=${GATE_DOCS_ONLY_READERS}"
                GATE_RUN_LEAK_PROOF="$GATE_DOCS_ONLY_PROOF"
                if ! (cd "$ROOT" && gate_ledger_record "$DOCS_TREE" "$GATE_DOCS_ONLY_LEGS"); then
                    die "the verdict ledger could not be written. Every reader was green and
   nothing was pushed: a green nobody can read is not a verdict."
                fi
                DOCS_T1="$(date +%s)"
                echo "pm_push --bank: docs-only reuse of ${GATE_DOCS_ONLY_SOURCE} — readers ${DOCS_READERS_TOOK} s, total $((DOCS_T1 - DOCS_T0)) s"
                echo "  source + delta + row: $((DOCS_T1 - DOCS_T0 - DOCS_READERS_TOOK)) s"
                echo "  verdict banked for tree ${DOCS_TREE}"
                echo "  caller=pm-bank sanction=${GATE_RUN_SANCTION}"
                echo "  legs=${GATE_DOCS_ONLY_LEGS}"
                [ -z "$GATE_DOCS_ONLY_PROOF" ] || echo "  leak-proof=${GATE_DOCS_ONLY_PROOF}"
                echo "  The pre-push hook will honour it and cost seconds."
                echo ""
                DOCS_ONLY_BANKED=1
            fi
        fi
    fi

    # WHERE THE BANK RUNS, AND IT IS ONE BRANCH RATHER THAN TWO RITUALS. Both
    # arms earn the SAME verdict for the SAME post-fold tree through the SAME
    # writer; what differs is the machine the legs run on. Everything above this
    # line — the fold, the re-read SHA, the clean-tree refusal — is shared by
    # construction, which is the reason `--on-boxes` is a flag on this script
    # rather than a second one beside it.
    if [ "$DOCS_ONLY_BANKED" = "1" ]; then
        # NEITHER ARM RUNS. The row above is the verdict for this tree and it
        # was written by the one writer; there is nothing left for a bank to
        # earn, and launching one would measure bytes a measured row already
        # covers.
        :
    elif [ -n "$ON_BOXES" ]; then
        BANK_RC=0
        bank_on_boxes "$ON_BOXES" || BANK_RC=$?
        if [ "$BANK_RC" != "0" ]; then
            echo "!! pm_push --bank --on-boxes: the composed gate exited ${BANK_RC}." >&2
            echo "   2 is enforcement broken or a shard nobody could read, 1 is a red tree;" >&2
            echo "   neither is a tree to push, and no row was written for either." >&2
            echo "   Nothing was pinned and nothing was pushed." >&2
            exit "$BANK_RC"
        fi
        echo ""
    else
        echo "pm_push: banking a verdict for ${ROOT} before the push — ${GATE} --bank"
        echo "  This is the full gate: two whole-suite passes, the supply chain, the canary"
        echo "  self-test and every shell refusal drive. It takes the machine-wide lease and"
        echo "  EVERY pytest slot on this box, so every other full gate waits behind it AND"
        echo "  every builder's --loop waits for this run's pytest passes, naming this bank."
        echo "  DJB_BANK_SHARES_SLOTS=1 takes one slot instead and shares the box."
        echo "  --on-boxes N runs the same units on N verifier boxes and takes neither."
        echo "  A red one stops here: nothing is pinned and nothing is pushed."
        # NOT `exec`, and not piped. The push is still this script's job and the
        # header's third property is about the PUSH, not about every command in the
        # file — so the gate's status is captured and answered, and only a 0 goes
        # on. check.sh's own exit 2 (enforcement broken) outranks a pass on the way
        # through here exactly as it does everywhere else.
        BANK_RC=0
        "$GATE" --bank || BANK_RC=$?
        if [ "$BANK_RC" != "0" ]; then
            echo "!! pm_push --bank: the full gate exited ${BANK_RC}." >&2
            echo "   2 is enforcement broken, 1 is a red tree; neither is a tree to push." >&2
            echo "   Nothing was pinned and nothing was pushed." >&2
            exit "$BANK_RC"
        fi
        echo "pm_push: verdict banked. The pre-push hook will honour it and cost seconds."
        echo ""
    fi
fi

echo "pm_push: pinning ${WORKTREE_NAME} and pushing to ${REMOTE}/${TARGET_BRANCH}"
echo "  checkout      ${ROOT}"
echo "  pm-push       ${PM_PUSH}"
echo "  was at        $(git -C "$PM_PUSH" rev-parse --short HEAD 2>/dev/null || echo '(unknown)')"
echo "  INTENDED TIP  $(git -C "$ROOT" rev-parse --short "$SHA")  $(git -C "$ROOT" log -1 --format=%s "$SHA")"

# THE RANGE LINE, printed BEFORE the push rather than read out of its output
# afterwards. `git push` prints `<old>..<new>` only on success and only after
# the fact; the whole value of the range is in comparing it with what you meant
# while you can still stop.
git -C "$ROOT" fetch -q "$REMOTE" "$TARGET_BRANCH" 2>/dev/null || true
REMOTE_TIP="$(git -C "$ROOT" rev-parse --verify --quiet "${REMOTE}/${TARGET_BRANCH}" || true)"
if [ -n "$REMOTE_TIP" ]; then
    COUNT="$(git -C "$ROOT" rev-list --count "${REMOTE_TIP}..${SHA}" 2>/dev/null || echo '?')"
    echo "  RANGE         $(git -C "$ROOT" rev-parse --short "$REMOTE_TIP")..$(git -C "$ROOT" rev-parse --short "$SHA")  (${COUNT} commit(s))"
    if [ "$COUNT" = "0" ]; then
        echo "  note: nothing to push — ${REMOTE}/${TARGET_BRANCH} already has this commit."
    fi
    # Named, not refused: a deliberate force is the operator's call, and this
    # script's job is to make sure it is never an accident.
    if ! git -C "$ROOT" merge-base --is-ancestor "$REMOTE_TIP" "$SHA" 2>/dev/null; then
        echo "  !! NOT A FAST-FORWARD: ${REMOTE}/${TARGET_BRANCH} is not an ancestor of this commit." >&2
        echo "     The push below will be REFUSED unless somebody forces it. That refusal" >&2
        echo "     is the correct outcome of pushing a tip you did not mean." >&2
    fi
else
    echo "  RANGE         ${REMOTE}/${TARGET_BRANCH} not known locally — pushing a new branch"
fi

git -C "$PM_PUSH" checkout -q --detach "$SHA" ||
    die "could not pin ${PM_PUSH} to ${SHA}"
echo "  pinned        $(git -C "$PM_PUSH" rev-parse --short HEAD)"

if [ "$DRY_RUN" = "1" ]; then
    echo "pm_push: --dry-run, so the push did not happen. Everything above did."
    exit 0
fi

# --- THE PUSH, AND NOTHING AFTER IT ------------------------------------------
# `exec`: this shell is REPLACED by git. There is no line after this one — not
# a cleanup, not a log line, not an `echo done` — so nothing can run between the
# push failing and the caller reading the status. The exit code a caller sees is
# git's own, always.
#
# THE FULL GATE IS BEHIND THIS PUSH, not in this script. `scripts/githooks/pre-push`
# consults the verdict ledger and runs `./scripts/check.sh` itself when the tree
# has none, exporting `DJB_GATE_CALLER=push-wall` — which is one of the three
# things that SANCTIONS a full run (`scripts/check.sh`, THE FULL GATE IS
# SANCTIONED). So the wall needs nothing typed here and never has. To bank the
# verdict AHEAD of the push instead — an ~8-minute gate the operator can watch
# rather than one that fires inside a hook — pass `--bank` to THIS script,
# which runs it above and refuses to pin or push on anything but a 0. Running
# it by hand from this checkout or from pm-push is still legal and identical:
#     ./scripts/check.sh --bank > "$PWD/bank.log" 2>&1
# The push then honours that verdict and costs seconds.
echo "pm_push: pushing ${SHA} -> ${REMOTE}/${TARGET_BRANCH}"
exec git -C "$PM_PUSH" push "$REMOTE" "${SHA}:refs/heads/${TARGET_BRANCH}"
