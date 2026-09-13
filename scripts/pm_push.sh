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
NO_FOLD=0
_pm_push_total=$#
_pm_push_i=0
while [ "$_pm_push_i" -lt "$_pm_push_total" ]; do
    _pm_push_arg="$1"
    shift
    case "$_pm_push_arg" in
    --no-fold) NO_FOLD=1 ;;
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
-h | --help)
    sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
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
if [ "$NO_FOLD" = "1" ] && [ "$BANK" != "1" ]; then
    die "--no-fold is only meaningful with --bank, and this is not a --bank run.
   The fold runs at the BANK: it regenerates the derived files and commits them
   BEFORE the gate measures the tree, so that the verdict vouches for the tree
   the push carries. A plain push pins and pushes a commit that already exists
   and regenerates nothing, so there is nothing here for --no-fold to skip.
   Accepting it silently would be a flag that did nothing with no line printed.
   scripts/pm_merge.sh refuses the same combination in the same words."
fi

ROOT="$(git rev-parse --show-toplevel)" || die "not inside a git checkout"

# The commit to push, resolved to a full sha HERE, in the checkout the operator
# is standing in — not in pm-push, whose HEAD is exactly the thing that has been
# wrong before.
SHA="$(git -C "$ROOT" rev-parse --verify "${SHA_ARG:-HEAD}^{commit}" 2>/dev/null)" ||
    die "'${SHA_ARG:-HEAD}' is not a commit in $ROOT"

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
    echo "pm_push: banking a verdict for ${ROOT} before the push — ${GATE} --bank"
    echo "  This is the full gate: two whole-suite passes, the supply chain, the canary"
    echo "  self-test and every shell refusal drive. It takes the machine-wide lease and"
    echo "  one pytest slot, so every other full gate on this box waits behind it."
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
