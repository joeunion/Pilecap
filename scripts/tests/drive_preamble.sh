#!/usr/bin/env bash
# THE DRIVE PREAMBLE — sourced first by every drive under `scripts/tests/`,
# immediately after its `cd` to the checkout root and BEFORE its first git
# command. It is not a drive, it is not executable, and it asserts nothing of
# its own. It carries two jobs, and they are different stories:
#
#   * THE THREE LAYERS that keep a drive's scratch work inside its scratch
#     directory — sections 1 to 3 below.
#   * THE ONE ENVIRONMENT STRIP that keeps a drive's EXPECTATIONS out of the
#     harness's hands — section 4 below, which is its own incident and reads
#     independently.
#
# THE INCIDENT IT IS MADE OF. `scripts/tests/test_pm_merge.sh` builds throwaway
# git repositories under `mktemp -d` and does everything to them with
# `git -C "$REPO" ...`. Run from a terminal that is exactly what it looks like.
# Run from the pre-push hook it escaped DETERMINISTICALLY: three separate push
# attempts on 2026-08-24 created `stale`, `safe` and `clash` in the REAL
# repository's refs, committed the scenario commits "base" and "only on main"
# onto REAL main, and set `core.bare true` on the real repository's shared
# config. Every one of those commands exited 0. The scratch directory was left
# holding `shared.txt` and no `.git` at all.
#
# THE MECHANISM, measured rather than guessed. `scripts/pm_push.sh` ends with
#
#     exec git -C "$PM_PUSH" push "$REMOTE" "${SHA}:refs/heads/${TARGET_BRANCH}"
#
# and `$PM_PUSH` is a LINKED WORKTREE. When git is pointed at a linked worktree
# with `-C`, it cannot leave the hook to rediscover the repository from `.git`
# (in a linked worktree `.git` is a file, and the real gitdir is
# `<common>/worktrees/<name>`), so it EXPORTS an absolute `GIT_DIR` into the
# hook's environment:
#
#     $ git -C <plain checkout> push ...   # hook sees: GIT_EDITOR GIT_EXEC_PATH GIT_PREFIX
#     $ git -C <linked worktree> push ...  # hook sees: ... and GIT_DIR=<common>/.git/worktrees/pm-push
#
# `pre-push` inherits it, `scripts/check.sh` inherits it, and every drive the
# selftest leg spawns inherits it. An inherited `GIT_DIR` is ABSOLUTE and it
# WINS: `-C` changes the process's working directory and nothing else, so
# `git -C "$REPO" init`, `... commit`, `... branch` and `... checkout` all
# operate on the real repository's object store and its SHARED ref store no
# matter what `$REPO` says. `git init` under an inherited `GIT_DIR` with no
# `GIT_WORK_TREE` beside it is also what wrote `core.bare true`.
#
# So `-C` was never the guard anybody read it as. The guard has to be the
# environment, and it has to be here rather than in six copies that drift.
#
# THE THREE LAYERS, in the order they run:
#
#   1. ROOT CAUSE — the inherited location variables are unset at source time,
#      before the drive's first git command. This is the fix; the other two
#      exist because a fix nothing watches is a fix that can be deleted.
#   2. BELT — `drive_require_scratch` refuses an empty, unset, relative or
#      absurd scratch path at exit 2 (could-not-look) naming this incident
#      class. A drive calls it on every scratch variable it is about to hand to
#      git, before handing it over. `mktemp` failing silently and `set -u`
#      being off in two of these drives are the same hole from two directions.
#   3. TRIPWIRE — the real repository's branch list, HEAD and `core.bare` are
#      fingerprinted at source time and compared byte for byte at exit. A drive
#      that moved any of them fails loudly, names itself, and prints the delta.
#      Exit 2, because a run that mutated the repository it was measuring has
#      not cleared its cases whatever else it printed.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * THE WORKING TREE. The fingerprint is refs, HEAD and `core.bare` — the
#     three things the incident actually moved and the three no honest drive
#     touches. `scripts/tests/test_secrets_scan.sh` deliberately plants a file
#     in this checkout and restores it, and must go on being able to.
#   * A PEER MOVING A REF THAT IS NOT `main`. Refs are shared across every
#     worktree of one repository and this one carries eighty-odd of them, so the
#     fingerprint holds ref NAMES rather than ref shas — the note above
#     `drive_repo_fingerprint` is where that trade is argued. A peer committing
#     on its own branch is invisible here, deliberately; a peer CREATING one is
#     not, and the printed delta is what tells the two apart at a glance.
#   * A MUTATION MADE AND UNDONE inside one drive's run. This is two samples,
#     not a watch.
#   * ANYTHING OUTSIDE GIT. Databases, Temporal namespaces and docker are the
#     sweep drive's own refusals, not this file's.
#   * A DRIVE THAT DOES NOT SOURCE IT, or that clobbers the EXIT trap with a
#     bare `trap ... EXIT` of its own afterwards. Use `drive_at_exit`.

# --- 0 · who is speaking ------------------------------------------------------
# Derived, never typed: a drive that is renamed goes on naming itself correctly.
DRIVE_NAME="$(basename "${BASH_SOURCE[1]:-$0}" .sh)"

drive_cannot_look() {
    echo "!! ${DRIVE_NAME}: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

# --- 1 · ROOT CAUSE: neutralise the inherited location environment ------------
#
# Every one of these overrides `-C`, `--git-dir` discovery, or both. They are
# unset rather than emptied: git treats an empty `GIT_DIR` as "not set" on some
# paths and as "the current directory" on others, and a drive should not have to
# know which.
DRIVE_NEUTRALISED=""
for _drive_var in \
    GIT_DIR \
    GIT_WORK_TREE \
    GIT_INDEX_FILE \
    GIT_COMMON_DIR \
    GIT_OBJECT_DIRECTORY \
    GIT_ALTERNATE_OBJECT_DIRECTORIES \
    GIT_NAMESPACE \
    GIT_PREFIX \
    GIT_QUARANTINE_PATH; do
    if [ -n "${!_drive_var+set}" ]; then
        DRIVE_NEUTRALISED="${DRIVE_NEUTRALISED}${DRIVE_NEUTRALISED:+ }${_drive_var}"
        unset "$_drive_var"
    fi
done
unset _drive_var

if [ -n "$DRIVE_NEUTRALISED" ]; then
    # Printed, not silent. This is the only evidence that the drive was called
    # from inside a hook, and the day it stops printing under `pm_push` is the
    # day somebody should ask why.
    echo "${DRIVE_NAME}: inherited git location environment neutralised: ${DRIVE_NEUTRALISED}"
fi

command -v git >/dev/null 2>&1 || drive_cannot_look "no git on PATH"

# --- 2 · BELT: a scratch path is proven before git is handed it ---------------
#
# `git -C "" ...` does not fail — it is a no-op chdir, and every command after
# it runs against whatever repository the process is standing in. So does
# `git -C "/" ...`. An unset variable under a drive with `set -u` off is the
# same thing spelled differently. This is the check that has to come BEFORE the
# first git command, not after the first surprising one.
drive_require_scratch() {
    local label="$1" value="${2-}"

    [ -n "$value" ] ||
        drive_cannot_look "the scratch path \$${label} is empty or unset, and the next
   command would have been a git command. An empty path is not a refusal: 'git -C
   \"\"' is a no-op chdir and everything after it lands wherever this process is
   standing. That is the exact class that committed a drive's scenario onto
   real main three times."
    case "$value" in
    /*) ;;
    *)
        drive_cannot_look "the scratch path \$${label} is relative ('${value}'). A drive's
   scratch must be an absolute path it made itself; a relative one resolves
   against whatever directory a caller left behind."
        ;;
    esac
    [ "$value" != "/" ] ||
        drive_cannot_look "the scratch path \$${label} is '/'. Refusing."

    # Existence is checked only if the path is already there, because this must
    # be callable BEFORE the `mkdir -p "$REPO/..."` as well as after it. An
    # empty \$REPO makes that mkdir `mkdir -p /scripts`, which is the same
    # incident one step earlier — a guard that fires after the directory is made
    # is a guard that was too late to matter.
    if [ -e "$value" ] && [ ! -d "$value" ]; then
        drive_cannot_look "the scratch path \$${label} ('${value}') exists and is not a
   directory. Whatever made it did not make it."
    fi

    # The scratch must not be the checkout, and must not be inside it. Both have
    # happened to somebody: the first is the class above, the second is a related one.
    if [ -n "${DRIVE_REPO_ROOT:-}" ]; then
        case "$value" in
        "$DRIVE_REPO_ROOT" | "$DRIVE_REPO_ROOT"/*)
            drive_cannot_look "the scratch path \$${label} ('${value}') is inside this
   checkout (${DRIVE_REPO_ROOT}). A drive builds its scratch under mktemp, outside
   any repository, so that a mistake is confined to it."
            ;;
        esac
    fi
}

# --- 3 · TRIPWIRE: the real repository is fingerprinted, and checked at exit --
#
# Three lines and the branch list — the exact three things the incident moved,
# and three no drive has any business moving.
DRIVE_REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
DRIVE_FINGERPRINT_BEFORE=""

# WHAT IS IN THE FINGERPRINT, and why it is not simply everything. Refs are
# SHARED across every worktree of one repository, and this repository routinely
# has eighty-odd agent worktrees on it. If the fingerprint carried every ref's
# sha, a peer committing on its own branch during the couple of minutes the
# drives take would redden the push — and a gate that cries wolf is a gate people learn
# to pass with --no-verify. So it carries the four things the escape moved and a
# peer's ordinary commit does not:
#
#   HEAD, HEAD-ref  this worktree's own checkout. No peer can move it. The
#                   escape did, twice over: it pointed HEAD at refs/heads/main
#                   and then committed onto it.
#   core.bare       `git init` under an inherited GIT_DIR with no GIT_WORK_TREE
#                   sets it. Nothing legitimate in this repository ever does.
#   main            the branch every escape aimed at, by sha. The PM merges into
#                   main from the main checkout, never during a push.
#   ref names       the NAME list, without shas. The escape ADDS names (stale,
#                   safe, clash); a peer committing MOVES a name it already had.
#                   So a new branch is seen and a peer's ordinary commit is not.
drive_repo_fingerprint() {
    [ -n "${DRIVE_REPO_ROOT:-}" ] || return 0
    printf 'HEAD      %s\n' "$(git -C "$DRIVE_REPO_ROOT" rev-parse HEAD 2>/dev/null || echo '(none)')"
    printf 'HEAD-ref  %s\n' "$(git -C "$DRIVE_REPO_ROOT" symbolic-ref -q HEAD 2>/dev/null || echo '(detached)')"
    printf 'core.bare %s\n' "$(git -C "$DRIVE_REPO_ROOT" config --get core.bare 2>/dev/null || echo '(unset)')"
    printf 'main      %s\n' "$(git -C "$DRIVE_REPO_ROOT" rev-parse --verify -q refs/heads/main 2>/dev/null || echo '(none)')"
    git -C "$DRIVE_REPO_ROOT" for-each-ref --format='ref       %(refname)' refs/heads 2>/dev/null |
        LC_ALL=C sort
}

if [ -n "$DRIVE_REPO_ROOT" ]; then
    DRIVE_FINGERPRINT_BEFORE="$(drive_repo_fingerprint)"
else
    echo "${DRIVE_NAME}: not inside a git checkout — the real-repository tripwire is not armed." >&2
fi

# Returns 0 if the real repository is byte-identical to how this drive found it.
drive_tripwire_check() {
    [ -n "${DRIVE_REPO_ROOT:-}" ] || return 0
    local after
    after="$(drive_repo_fingerprint)"
    [ "$after" != "$DRIVE_FINGERPRINT_BEFORE" ] || return 0

    echo "!! ${DRIVE_NAME} MUTATED THE REAL REPOSITORY." >&2
    echo "   checkout: ${DRIVE_REPO_ROOT}" >&2
    echo "   A drive builds throwaway repositories and works in those. Anything it" >&2
    echo "   changed here it changed by accident, and nothing it asserted this run can" >&2
    echo "   be trusted. The delta, '-' as this drive found it and '+' as it left it:" >&2
    diff <(printf '%s\n' "$DRIVE_FINGERPRINT_BEFORE") <(printf '%s\n' "$after") |
        sed 's/^/     /' >&2 || true
    echo "   If those are a drive's own scenario names — stale, safe, clash, main," >&2
    echo "   core.bare, this worktree's HEAD — the escape is back and the preamble's" >&2
    echo "   header is where the mechanism is written down." >&2
    echo "   If it is one new branch with a peer's name on it, an agent created a" >&2
    echo "   worktree while this ran: refs are shared across every worktree of one" >&2
    echo "   repository. Re-run. Nothing this run asserted is trustworthy either way." >&2
    return 1
}

# --- 4 · THE CI EXEMPTION: a case's expectation is not the runner's ----------
#
# A DIFFERENT INCIDENT FROM THE THREE ABOVE, and it belongs here for the same
# reason they do: the alternative is six copies that drift.
#
# WHAT HAPPENED. A CI run once died at 14m34s, the deepest a run had reached.
# `scripts/check.sh:63`, `scripts/pm_merge.sh:91`
# and `deploy/release.sh:85` each refuse a piped stdout, and each EXEMPTS CI —
# GitHub Actions captures every step's stdout through a pipe, so without the
# exemption the guard would refuse every CI run. The exemption is correct and
# check.sh argues for it in full at its own guard.
#
# `test_pm_merge.sh::case_a_piped_stdout_is_refused` asserted the refusal
# UNCONDITIONALLY. On a laptop the refusal fires and the case is green. On the
# runner the exemption fires, the pipe is allowed, the scratch merge really
# happens and HEAD really moves — so three assertions went red:
#
#     FAILED   piped stdout — wanted exit 2, got 0
#     FAILED   piped stdout — does not say "refuses pipes"
#     FAILED   piped stdout: HEAD did not move — wanted '94bec39…', got '81e7dc5…'
#
# The exemption WORKING was scored as the refusal FAILING. That is the same
# class one layer up: there the CODE read an environment variable where it
# needed the derivation; here the TEST expects behaviour the environment
# legitimately changes.
#
# THE FIX. The drive process runs with the exemption variables UNSET, so every
# refusal case in every drive exercises the refusal path on every platform, CI
# included. A case that wants the exemption sets it at its own call site
# (`env CI=true …`) — which is what makes the exemption's OWN case possible, so
# the exemption cannot be silently lost either.
#
# WHAT IS STRIPPED, AND WHY THIS SET. `CI` is the whole population the three
# guards actually read; `grep -rn 'CI:-' scripts/ deploy/` is how that was
# established rather than remembered. `GITHUB_ACTIONS` is stripped beside it
# because it is the other name a GitHub runner exports that an exemption would
# plausibly grow to read, and unsetting a variable nothing reads costs nothing.
#
# THE LIST IS NOT SELF-MAINTAINING, so it has a tooth rather than a promise:
# `test_pm_merge.sh::case_the_pipe_guard_reads_only_what_the_preamble_strips`
# lifts the guard condition out of `scripts/pm_merge.sh` AND `scripts/check.sh`,
# asserts they are the same line (which is what pm_merge's own header claims),
# and asserts every variable that line reads is named here. An exemption that
# grows a variable the drives do not strip is a red case, not a refusal that
# quietly stopped being exercised.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * `deploy/tests/test_release.sh` — the sixth drive, carrying the identical
#     defect at its own `case_a_piped_stdout_is_refused` against the third copy
#     of the guard (`deploy/release.sh:85`). It does not source this file and is
#     not yet wired into the gate's selftest leg, so CI does not run it
#     today; the day it is wired, it is red exactly as this one was.
#   * EVERY OTHER ENVIRONMENT A CASE COULD TURN ON. This strips two names and
#     claims nothing wider. A drive whose expectation turns on `DATABASE_NAME`,
#     `TMPDIR`, `DJB_SWEEP_ROOT_DEPTH` or a global git config pins that itself,
#     at the case: `test_sweep.sh`'s two `DATABASE_NAME` pin cases are
#     the worked example of doing it there rather than here.
#   * A DRIVE'S PRECONDITIONS. Nothing here reads CI to decide what it can
#     reach; if a drive ever needs to know it is on a runner, this strip is the
#     thing it has to be told about first.
DRIVE_CI_VARS="CI GITHUB_ACTIONS"

DRIVE_CI_STRIPPED=""
for _drive_ci_var in $DRIVE_CI_VARS; do
    if [ -n "${!_drive_ci_var+set}" ]; then
        DRIVE_CI_STRIPPED="${DRIVE_CI_STRIPPED}${DRIVE_CI_STRIPPED:+ }${_drive_ci_var}"
        unset "$_drive_ci_var"
    fi
done
unset _drive_ci_var

if [ -n "$DRIVE_CI_STRIPPED" ]; then
    # Printed, not silent, for section 1's reason: on a CI log this line is the
    # only evidence that the refusal cases below tested the refusal rather than
    # the exemption.
    echo "${DRIVE_NAME}: CI exemption variables unset for this drive: ${DRIVE_CI_STRIPPED}"
fi

# --- the EXIT path ------------------------------------------------------------
#
# The tripwire has to run last, after the drive's own cleanup, on every exit
# path. So the preamble owns the EXIT trap and a drive registers its cleanup
# instead of installing a trap of its own — a bare `trap ... EXIT` after this
# point silently removes the tripwire.
# One cleanup per line rather than an array: the drives run under macOS's
# bash 3.2, where `arr+=(x)` does not exist and `${#arr[@]}` on an empty array
# is an unbound-variable error under `set -u`.
DRIVE_CLEANUPS=""

drive_at_exit() {
    DRIVE_CLEANUPS="${DRIVE_CLEANUPS}$1
"
}

# --- 5 · A DRIVE THAT DIED IS NOT A DRIVE THAT PASSED ------------------------
#
# MEASURED, on the bash this repository actually runs (GNU bash 3.2.57, macOS):
# when `set -u` kills the shell on an unbound variable, THE EXIT TRAP SEES
# `$? = 0`. So `drive_epilogue`'s `exit "$rc"` exits **0**, `check.sh` reads the
# drive as green, and a driver that never reached its own summary line reports
# success. Minimal repro, and it is three lines:
#
#     set -euo pipefail
#     trap 'rc=$?; echo "trap saw rc=$rc"; exit "$rc"' EXIT
#     echo "$NOPE"          # -> "unbound variable", "trap saw rc=0", exit 0
#
# `set -E` with `trap ... ERR` does NOT catch it either — tested on the same
# bash. There is no way for this file to notice on its own, so a drive has to
# say it finished.
#
# IT IS OPT-IN, DELIBERATELY. A drive that never calls `drive_finished` behaves
# exactly as it did before this was written — no drive is silently given a new
# way to fail, and this file stays a preamble rather than becoming a contract
# every drive must be edited to satisfy in the same commit. `test_loop_tier.sh`
# opts in; the other five owe the same one line and that is booked, not
# smuggled in here.
DRIVE_FINISHED=0

# A drive opts in by setting this to 1 near the top, which is what arms the
# check below. Two variables rather than one so that "never opted in" and
# "opted in and died" are different states rather than one ambiguous zero.
DRIVE_OPTED_IN_TO_FINISH=0

# Called by a drive immediately before its own final `exit`. Everything after it
# is the epilogue's.
drive_finished() {
    DRIVE_FINISHED=1
}

drive_epilogue() {
    local rc=$?
    local cleanup
    while IFS= read -r cleanup; do
        [ -n "$cleanup" ] || continue
        eval "$cleanup" || true
    done <<<"$DRIVE_CLEANUPS"
    if ! drive_tripwire_check; then
        # 2 outranks everything, including a pass and including a case that
        # failed for its own reasons: this run measured nothing it can vouch for.
        exit 2
    fi
    # Section 5. A drive that opted in and did NOT reach its own end, while the
    # masked status says 0, is could-not-look — never a pass.
    if [ "${DRIVE_OPTED_IN_TO_FINISH:-0}" = "1" ] && [ "$DRIVE_FINISHED" != "1" ] && [ "$rc" = "0" ]; then
        echo "!! ${DRIVE_NAME} DIED BEFORE REPORTING, and bash handed this trap a" >&2
        echo "   status of 0 (section 5 of drive_preamble.sh has the repro). Nothing" >&2
        echo "   this run printed can be trusted: the cases after the failure never" >&2
        echo "   ran, and without this branch the gate would have read the run as a" >&2
        echo "   pass. Scroll up for the shell's own error line." >&2
        exit 2
    fi
    exit "$rc"
}

trap drive_epilogue EXIT
