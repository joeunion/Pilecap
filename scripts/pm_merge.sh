#!/usr/bin/env bash
# Merge a returned builder's branch into this checkout, and own the exit status.
# The PM's one merge path.
#
#   ./scripts/pm_merge.sh <branch>              # merge --no-ff, git's default message
#   ./scripts/pm_merge.sh <branch> -m FILE      # ...with the message in FILE
#   ./scripts/pm_merge.sh <branch> -m -         # ...with the message on stdin
#
# WHY THIS EXISTS, and like scripts/pm_push.sh it is a scar rather than a
# convenience. A merge was once run as
# `git merge ... | grep -E "CONFLICT|Merge|files|failed"`. The branch name was
# wrong — a session-history name, not the branch actually being built on — so git
# refused with `merge: <branch> - not something we can merge`. That line matches
# none of those four patterns (git's is a LOWERCASE "merge"), so the failure
# printed NOTHING, the grep exited 1 into a shell nobody was reading, the ledger
# said "merging", and the gate then ran on the UNMERGED tree and went green. The
# only thing that caught it was a human driving the product and finding the bug
# the merge was supposed to have fixed still live.
#
# So this script makes that sequence unavailable, in the same four ways
# pm_push.sh makes its own scar unavailable:
#
#   1. IT REFUSES A PIPED STDOUT (exit 2), exactly as the gate does. The
#      incident was not "a grep with the wrong pattern" — it was a merge whose
#      output was filtered at all. You cannot grep this script; you can redirect
#      it to a file and read the file, which loses nothing.
#   2. IT ASSERTS THE BRANCH EXISTS BEFORE IT MERGES, and a name that resolves
#      to nothing is a LOUD refusal at exit 2 that names the near misses — never
#      a one-line "not something we can merge" a filter can swallow. Same for a
#      branch already merged: a merge that does nothing must never print a
#      proof line that looks like a merge.
#   3. IT OWNS `$?`. The merge is not piped, not filtered and not `set -e`'d
#      away: its status is captured on the line after it and answered. On a
#      conflict it says what state the WORKING TREE is now in (mid-merge, or
#      untouched) — the thing the PM otherwise has to go and ask for — and
#      exits with git's own status.
#   4. IT PRINTS `git log -1 --oneline` AS THE PROOF OF MERGE, and it verifies
#      before printing it that HEAD actually moved and that the new tip has two
#      parents. The standing doctrine is "check `$?` or `git log -1`
#      after every merge"; this does both, so neither depends on remembering.
#
# THEN IT GATES THE MERGED TREE, and `exec`s the gate so that — pm_push's third
# property — there is no line of code after the thing whose status you care
# about. The exit code a caller sees is the gate's own.
#
# WHAT TIER, AND WHY NOT MORE (ADR gate-3, and this comment is the required
# answer to "the cheap per-rule floor check, if one exists as a separable
# leg"):
#
#   * `./scripts/check.sh --fast` is what runs here. It is the tier the
#     post-merge hook already runs, and its `house-rules` leg is
#     `python -m quality.gate --diff HEAD` — the ENGINE'S ORDINARY SCAN, which
#     already includes the per-rule FLOORS and the consistency pass
#     (`quality/gate.py::run_rule` takes `floors=True` by default, and
#     `quality/gate.py::consistency` refuses a rule with no floors at all). So
#     the "cheap per-rule floor check" is not a separable leg that had to be
#     added — it is inside `--fast`, and `--fast` runs it here.
#   * THE CANARY SELF-TEST DOES NOT RUN HERE, and no cheap separable form of it
#     exists to run. `quality/gate.py::main` accepts exactly two flags,
#     `--selftest` and `--diff <ref>`; `--selftest` is all-or-nothing, measures
#     ~45s, and PLANTS canary files into the working tree — into a tree that
#     has just been merged and may be dirty, which is the half ADR gate-3 calls
#     deciding. A sampled "selftest-lite" was considered and rejected in that
#     same ADR (a sampled corpus is a corpus with a hole somebody has to
#     remember). Nothing was invented here to fill the gap: ADR gate-3 stands,
#     and the merge window's own defect class is covered by
#     `apps/core/tests/test_plant_sites.py` (a pytest test, so it binds in
#     `--loop` and at push) plus the per-rule selftest floors at push.
#
# WHAT THIS DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE BRANCH SHOULD BE MERGED. It checks that the name resolves and
#     that the merge is not a no-op. Whether this is the branch actually
#     reported as built, whether its criteria were met, and whether a peer verified it
#     are the PM's judgement and no script's.
#   * A CONFLICT'S RESOLUTION. It refuses and reports the state; it never
#     resolves, never aborts and never `--strategy`s its way out. An automatic
#     abort would destroy a half-done resolution somebody may want.
#   * THE FULL GATE. `--fast` is not `--loop` and is not the push tier. A green
#     here says the merged tree passes the static legs; the suite, the supply
#     chain, the two-pass idempotency and the canary self-test all still bind
#     at push, where the verdict is recorded.
#   * ANY REMOTE. It merges a local branch into the current checkout. Pushing
#     is `scripts/pm_push.sh`'s job and stays there.
set -euo pipefail

# --- it refuses to be piped, for the reason in the header --------------------
# Detection and the CI exemption are check.sh's, deliberately identical
# (scripts/check.sh:38-64): a pipe replaces this script's exit status with the
# filter's, which is exactly the failure this script exists to close. A TTY or
# a file redirect keeps it.
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! pm_merge refuses pipes — this script exists BECAUSE a merge was piped" >&2
    echo "   through a grep that could not match git's refusal. Run it bare" >&2
    echo "   or redirect to a file; the exit status is the verdict." >&2
    exit 2
fi

die() {
    # Exit 2 everywhere in this repository is "could not look" — here, "could
    # not get as far as merging". A merge that was never attempted must never
    # share an exit code with a merge that was refused by git.
    echo "!! pm_merge: $*" >&2
    echo "   Nothing was merged and the working tree was not touched." >&2
    exit 2
}

BRANCH=""
MSG_ARG=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    -h | --help)
        sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    -m)
        [ "$#" -ge 2 ] || die "-m needs a message file, or - for stdin."
        [ -z "$MSG_ARG" ] || die "-m given twice."
        MSG_ARG="$2"
        shift 2
        ;;
    -*)
        # Not a usage nit: a mistyped flag falling through to a silently
        # different merge is the same class as the swallowed refusal.
        die "unknown flag '$1'. Usage: $0 <branch> [-m <msg-file|->]"
        ;;
    *)
        [ -z "$BRANCH" ] || die "one branch at most; got '$BRANCH' and '$1'."
        BRANCH="$1"
        shift
        ;;
    esac
done
[ -n "$BRANCH" ] || die "no branch named. Usage: $0 <branch> [-m <msg-file|->]"

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git checkout"

# THE CHECKOUT YOU ARE STANDING IN MUST BE THE ONE THIS SCRIPT LIVES IN. The
# worktrees on this machine share a directory prefix and are one path component
# apart, and this script both merges into `git rev-parse
# --show-toplevel` and runs `$ROOT/scripts/check.sh`. If those two are different
# checkouts, the merge lands in one tree and nothing here is what the caller
# meant. `-ef` compares device+inode, so a symlinked path is still the same file.
[ -e "$ROOT/scripts/pm_merge.sh" ] && [ "$ROOT/scripts/pm_merge.sh" -ef "$0" ] ||
    die "you are standing in ${ROOT}, which is not the checkout this script lives in ($0). Run the pm_merge.sh that belongs to the tree you mean to merge into."

GATE="$ROOT/scripts/check.sh"
[ -x "$GATE" ] || die "no executable gate at ${GATE} — a merge this script cannot gate is a merge it will not make"

# --- the branch must EXIST, refused loudly if it does not --------------
if ! TIP="$(git -C "$ROOT" rev-parse --verify --quiet "${BRANCH}^{commit}")"; then
    echo "!! pm_merge: '${BRANCH}' names no commit in ${ROOT}." >&2
    echo "   git would have said 'not something we can" >&2
    echo "   merge' on one line, and a filtered merge would have swallowed it." >&2
    # A mistyped branch is often a session-history name close to the real one,
    # so the near misses are worth the two lines they cost.
    NEAR="$(git -C "$ROOT" for-each-ref --format='     %(refname:short)' refs/heads/ |
        grep -F -- "${BRANCH: -8}" | head -5 || true)"
    if [ -n "$NEAR" ]; then
        echo "   Local branches whose names end similarly:" >&2
        echo "$NEAR" >&2
    else
        echo "   Local branches: $(git -C "$ROOT" for-each-ref --count=8 --format='%(refname:short)' refs/heads/ | tr '\n' ' ')" >&2
    fi
    echo "   Nothing was merged and the working tree was not touched." >&2
    exit 2
fi

# A dirty tree, refused rather than merged into. git merge refuses to clobber
# files it needs, but it will happily merge AROUND unrelated local edits and
# leave a tree where nobody can say which change came from where — and the
# gate that runs below would then be measuring that mixture.
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
    echo "!! pm_merge: ${ROOT} has uncommitted changes." >&2
    git -C "$ROOT" status --short >&2
    echo "   Merging on top of them would produce a tree whose contents nobody can" >&2
    echo "   attribute, and the gate below would measure the mixture. Commit or" >&2
    echo "   stash them first; this script will not decide that for you." >&2
    exit 2
fi

HEAD_BEFORE="$(git -C "$ROOT" rev-parse --verify HEAD)" || die "this checkout has no HEAD commit"
ONTO="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"

# A merge that does nothing must not print a proof line that looks like one.
# `git merge --no-ff` of an ancestor exits 0 and says "Already up to date." —
# a zero exit status for a merge that never happened is the same silent-failure
# shape with a different mechanism.
if git -C "$ROOT" merge-base --is-ancestor "$TIP" "$HEAD_BEFORE"; then
    echo "!! pm_merge: ${BRANCH} ($(git -C "$ROOT" rev-parse --short "$TIP")) is ALREADY an ancestor of ${ONTO}." >&2
    echo "   git would exit 0 saying 'Already up to date' — a success status for a" >&2
    echo "   merge that did not happen. If you meant a different branch, name it;" >&2
    echo "   if this work is already in, the ledger row is what needs the edit." >&2
    echo "   Nothing was merged and the working tree was not touched." >&2
    exit 2
fi

echo "pm_merge: merging into ${ONTO} in ${ROOT}"
echo "  onto          $(git -C "$ROOT" rev-parse --short "$HEAD_BEFORE")  $(git -C "$ROOT" log -1 --format=%s "$HEAD_BEFORE")"
echo "  MERGING       $(git -C "$ROOT" rev-parse --short "$TIP")  $(git -C "$ROOT" log -1 --format=%s "$TIP")"
echo "  branch        ${BRANCH}"
echo "  RANGE         $(git -C "$ROOT" rev-parse --short "$HEAD_BEFORE")..$(git -C "$ROOT" rev-parse --short "$TIP")  ($(git -C "$ROOT" rev-list --count "${HEAD_BEFORE}..${TIP}") commit(s) not yet in ${ONTO})"

MERGE_ARGS=(merge --no-ff --no-edit)
MSG_FILE=""
if [ -n "$MSG_ARG" ]; then
    if [ "$MSG_ARG" = "-" ]; then
        MSG_FILE="$(mktemp "${TMPDIR:-/tmp}/djb-pm-merge-msg.XXXXXX")"
        cat >"$MSG_FILE"
        [ -s "$MSG_FILE" ] || {
            rm -f "$MSG_FILE"
            die "-m - was given but stdin was empty; a merge message nobody wrote is worse than git's default"
        }
    else
        [ -r "$MSG_ARG" ] || die "-m ${MSG_ARG}: no such readable file (use - to read the message from stdin)"
        MSG_FILE="$MSG_ARG"
    fi
    MERGE_ARGS+=(-F "$MSG_FILE")
fi
MERGE_ARGS+=("$BRANCH")

# --- THE MERGE, AND ITS STATUS READ ON THE VERY NEXT LINE --------------------
# Not piped, not filtered, not `set -e`'d past — the whole point of this script.
echo "pm_merge: git ${MERGE_ARGS[*]}"
set +e
git -C "$ROOT" "${MERGE_ARGS[@]}"
MERGE_RC=$?
set -e
if [ "$MSG_ARG" = "-" ] && [ -n "$MSG_FILE" ]; then
    # The temp file made for stdin, removed HERE — before the `exec` below,
    # which replaces this process and takes any trap with it.
    rm -f "$MSG_FILE"
fi

if [ "$MERGE_RC" != "0" ]; then
    echo "" >&2
    echo "!! pm_merge: THE MERGE FAILED (git exit ${MERGE_RC}). Nothing below ran." >&2
    # The state of the working tree, stated rather than left to be asked for:
    # a conflicted merge and a refused-before-it-started merge look nothing
    # alike and need opposite next moves.
    if [ -f "$ROOT/.git/MERGE_HEAD" ] || git -C "$ROOT" rev-parse --verify --quiet MERGE_HEAD >/dev/null; then
        echo "   WORKING TREE: MID-MERGE. ${ROOT} now holds a merge in progress." >&2
        echo "   Unmerged paths:" >&2
        git -C "$ROOT" diff --name-only --diff-filter=U >&2 || true
        echo "   Resolve them and commit, or 'git -C ${ROOT} merge --abort' to put the" >&2
        echo "   tree back. This script does neither for you: an automatic abort" >&2
        echo "   would destroy a resolution somebody may already have started." >&2
    else
        echo "   WORKING TREE: unchanged — the merge was refused before it began." >&2
        git -C "$ROOT" status --short >&2
    fi
    exit "$MERGE_RC"
fi

# --- the proof of merge, verified before it is printed -----------------------
HEAD_AFTER="$(git -C "$ROOT" rev-parse --verify HEAD)"
if [ "$HEAD_AFTER" = "$HEAD_BEFORE" ]; then
    echo "!! pm_merge: git exited 0 but HEAD did not move ($(git -C "$ROOT" rev-parse --short "$HEAD_BEFORE"))." >&2
    echo "   A zero status for a merge that produced no commit is exactly the shape" >&2
    echo "   a filtered pipe would hide. Nothing is vouched for here; the gate did not run." >&2
    exit 2
fi
if ! git -C "$ROOT" rev-parse --verify --quiet "${HEAD_AFTER}^2" >/dev/null; then
    echo "!! pm_merge: the new tip $(git -C "$ROOT" rev-parse --short "$HEAD_AFTER") has ONE parent — it is not a merge commit," >&2
    echo "   though --no-ff was given. Something is not what this script assumes." >&2
    exit 2
fi
echo ""
echo "pm_merge: MERGED. Proof of merge — git log -1 --oneline:"
git -C "$ROOT" log -1 --oneline
echo "  parents       $(git -C "$ROOT" log -1 --format='%p' "$HEAD_AFTER")"

# --- the template database, warmed for the wave about to be dispatched -------
#
# THE MERGE IS WHERE THE MIGRATION SET CHANGES, so it is where the template that
# every worktree clones its database from is republished. Warming
# it here rather than at rung start is the whole point: a builder mid-rung holds
# a migration set that exists only in their worktree, and building a
# machine-global template for one of those would leave one behind per in-flight
# rung. A merged state is the one the next nine worktrees are all about to want.
#
# ADVISORY, and `db_template_refresh_advisory` is the shape of that: it cannot
# fail this script, and it says nothing when there is no Postgres or no
# migration set to digest — which is every case in
# `scripts/tests/test_pm_merge.sh`, whose scratch repositories have neither.
# The merge above is already made and vouched for; a cache warmer does not get
# to have an opinion about it. Costs one existence check when the migration set
# has not moved.
if [ -r "$ROOT/scripts/db.sh" ]; then
    (
        cd "$ROOT" || exit 0
        set +u
        # shellcheck source=scripts/db.sh
        . "$ROOT/scripts/db.sh" >/dev/null 2>&1 || exit 0
        db_template_refresh_advisory
    ) || true
fi

# --- THE GATE, AND NOTHING AFTER IT ------------------------------------------
# `exec`: this shell is REPLACED by the gate. There is no line after this one —
# not a cleanup, not a log line, not an `echo done` — so nothing can run between
# a red gate and the caller reading the status. The exit code a caller sees is
# check.sh's own, and check.sh's exit 2 (enforcement broken) still outranks a
# pass on the way through.
#
# The merge commit is ALREADY MADE at this point and a red gate does not undo it
# — same property `scripts/githooks/post-merge` declares about itself, for the
# same reason: git makes the commit before anything can object. A red here is a
# report on a tree that exists, and the next move is a fix commit or
# `git -C <root> reset --hard <the sha printed above as 'onto'>`.
echo ""
echo "pm_merge: gating the merged tree — ${GATE} --fast"
echo "  NOT run here: pytest, the supply chain, the canary self-test, the shell"
echo "                refusal drives, the verdict. Those bind at push. See this"
echo "                script's header for why the self-test is not here (ADR gate-3)."
exec "$GATE" --fast
