#!/usr/bin/env bash
# Pin the pm-push worktree to a commit and push it. The PM's one push path.
#
#   ./scripts/pm_push.sh              # pin pm-push to THIS checkout's HEAD, push
#   ./scripts/pm_push.sh <sha>        # pin it to that commit instead
#   ./scripts/pm_push.sh --dry-run    # everything except the push
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

case "${1:-}" in
--dry-run)
    DRY_RUN=1
    SHA_ARG=""
    ;;
-h | --help)
    sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
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
echo "pm_push: pushing ${SHA} -> ${REMOTE}/${TARGET_BRANCH}"
exec git -C "$PM_PUSH" push "$REMOTE" "${SHA}:refs/heads/${TARGET_BRANCH}"
