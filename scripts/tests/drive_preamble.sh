#!/usr/bin/env bash
# road: drive_harness — the one harness every drive sources: scratch, strip, exit path, and `ok` `bad` `holds` `exits` `says` `says_not` `says_before` `drive_skip` `drive_summary` `drive_list_cases` `drive_run_case` `drive_scratch_repo` `drive_checkout_mirror` `drive_cannot_look` `drive_cannot_reach` `drive_finished` · example: scripts/tests/test_drive_preamble.sh::case_the_harness_lists_runs_and_summarises_a_drive_once
# THE DRIVE PREAMBLE — sourced first by every drive under `scripts/tests/`,
# immediately after its `cd` to the checkout root and BEFORE its first git
# command. It is not a drive, it is not executable, and it asserts nothing of
# its own. It carries three jobs, and they are different stories:
#
#   * THE THREE LAYERS that keep a drive's scratch work inside its scratch
#     directory — sections 1 to 3 below.
#   * THE ONE ENVIRONMENT STRIP that keeps a drive's EXPECTATIONS out of the
#     harness's hands — section 4 below, which is its own incident and reads
#     independently.
#   * THE EXIT PATH ITSELF — sections 5 and 6 below: a drive that died of its
#     own shell does not read as a pass, and a drive somebody KILLED says so and
#     runs the cleanups it registered. Both are their own stories, and section 6
#     is the one that carries a measurement rather than an incident.
#
# THE INCIDENT IT IS MADE OF. The merge drive (since swept) built throwaway
# git repositories under `mktemp -d` and did everything to them with
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
#     touches. `quality/tests/test_secrets.py` deliberately plants a file
#     in this checkout and restores it, and must go on being able to.
#   * A PEER MOVING ANY REF, `main` INCLUDED. Refs are shared across every
#     worktree of one repository and this one carries eighty-odd of them, so the
#     fingerprint holds ref NAMES rather than ref shas — the note above
#     `drive_repo_fingerprint` is where that trade is argued, and `main` joined
#     it after a PM merge demoted a blameless drive to exit 2. A
#     peer committing on its own branch, or the PM merging into main, is
#     invisible here, deliberately; a peer CREATING or DELETING a branch is not,
#     and the printed delta is what tells the two apart at a glance.
#   * A MUTATION MADE AND UNDONE inside one drive's run. This is two samples,
#     not a watch.
#   * ANYTHING OUTSIDE GIT. Databases, Temporal namespaces and docker are the
#     sweep drive's own refusals, not this file's.
#   * A DRIVE THAT DOES NOT SOURCE IT, or that clobbers the EXIT trap with a
#     bare `trap ... EXIT` of its own afterwards. Use `drive_at_exit`.
#
# AND A FOURTH JOB, THE HARNESS — section 10 at the foot: the assertions, the
# summary, the case list, the one-case seam and the scratch repository, so a
# drive's prologue is one line and its body is its cases.

# --- the shell, refused here once ---------------------------------------------
#
# Written in POSIX `sh` on purpose, and FIRST: a drive run as `sh drive` or
# `zsh drive` reads this file with that shell, and these lines must be the ones
# it can parse before anything bash-only below is reached. A sourced file is
# read command by command, so a shell that is not bash stops here with one
# sentence instead of failing somewhere nobody would read as the cause. Every
# drive used to carry its own copy of this block.
if [ -z "${BASH_VERSION:-}" ]; then
    echo "${0##*/}: must run under bash — not sh, not zsh. Try \`bash ${0}\`." >&2
    exit 2
fi
case ":${SHELLOPTS:-}:" in
*:posix:*)
    echo "${0##*/}: bash is in POSIX mode — which is what \`sh ${0}\` does on a" >&2
    echo "  machine whose /bin/sh is bash. Try \`bash ${0}\`." >&2
    exit 2
    ;;
esac

# --- 0 · who is speaking ------------------------------------------------------
# Derived, never typed: a drive that is renamed goes on naming itself correctly.
DRIVE_NAME="$(basename "${BASH_SOURCE[1]:-$0}" .sh)"

drive_cannot_look() {
    echo "!! ${DRIVE_NAME}: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

# drive_cannot_reach <why> — could-not-look because this machine lacks the world
# the drive needs (a database, a service); a census reads its `environment:` sentence as a skip.
drive_cannot_reach() {
    drive_cannot_look "environment: $*"
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

# WHAT IS IN THE FINGERPRINT, and why every ref carries its sha:
#
#   HEAD, HEAD-ref  this worktree's own checkout. No peer can move it. The
#                   escape did, twice over: it pointed HEAD at refs/heads/main
#                   and then committed onto it — so this pair is what actually
#                   catches the escape.
#   core.bare       `git init` under an inherited GIT_DIR with no GIT_WORK_TREE
#                   sets it. Nothing legitimate in this repository ever does.
#   ref <name> <sha>  every local branch, `main` included, WITH its target.
#
# WHY THE SHA CAME BACK, having once been dropped. It was dropped because refs
# are SHARED across every worktree of one repository — this one routinely has
# dozens of agent worktrees — so a peer's ordinary commit moved a ref and
# reddened whoever's drive happened to be running. Dropping the sha bought quiet
# at the price of a blind spot in BOTH directions: a `git branch -f main`, a
# `git update-ref`, a push into a ref, any force-move without a HEAD move,
# became invisible; and the name-only list STILL reddened on a created ref (a
# peer's `worktree add`) and on a VANISHED one (the PM reaping a merged branch),
# which are the two deltas that actually happen here. Both were paid for in
# whole re-run gates.
#
# So the fingerprint is exact again and the JUDGEMENT moved into the check,
# where it can name who owns a delta instead of guessing from its shape.
#
# THE RULE, and `scripts/tests/test_drive_preamble.sh` drives both directions of
# every clause of it. A delta is excused when, and only when, somebody other
# than this checkout can be shown to own it AT CHECK TIME:
#
#   created or moved   a worktree OTHER than this one has that ref checked out,
#                      as `git worktree list --porcelain` reports it. A drive
#                      cannot plausibly commit onto a peer's checked-out branch
#                      without that peer's worktree, and if it did, the peer's
#                      own `git status` is the belt.
#   vanished           its last known target — the sha this fingerprint recorded
#                      — is an ancestor of `refs/heads/main`. That is a reap of a
#                      branch that had already merged, which is the PM's ordinary
#                      housekeeping and destroys nothing.
#
# STILL RED, AND THIS IS THE HALF THAT MATTERS: a new ref with no worktree, a
# moved ref with no worktree (the escape class), a vanished ref whose target is
# NOT on `main` — work destroyed, and the lost sha is printed so it can be
# recovered — and this checkout's own HEAD, HEAD-ref or `core.bare`, which
# nobody else can touch and which no excuse reaches.
#
# EVERY EXCUSE IS PRINTED WITH ITS REASON, on the green path too. A tripwire that
# forgives silently is a tripwire nobody can audit, and the first question after
# a surprising green is which deltas it decided not to mind.
#
# DECLARED RESIDUALS, named rather than implied:
#
#   * THE EXCUSE IS A WORKTREE, NOT A PERSON. A ref some peer worktree has
#     checked out is excused however it moved — including by this drive. That is
#     the price of not reddening on every peer's ordinary commit.
#   * THE WORKTREE LIST IS ASKED AT CHECK TIME. A peer that adds a worktree and
#     removes it again inside the window leaves a delta with nothing to explain
#     it, and reds. Correct for the escape class, a false alarm for that one
#     sequence, and pinned by a case that says so.
#   * THE VANISHED EXCUSE TRUSTS `refs/heads/main`. No local `main` excuses no
#     reap at all; a `main` force-moved backwards could un-excuse a legitimate
#     one. Both red rather than forgive.
drive_repo_fingerprint() {
    [ -n "${DRIVE_REPO_ROOT:-}" ] || return 0
    printf 'HEAD      %s\n' "$(git -C "$DRIVE_REPO_ROOT" rev-parse HEAD 2>/dev/null || echo '(none)')"
    printf 'HEAD-ref  %s\n' "$(git -C "$DRIVE_REPO_ROOT" symbolic-ref -q HEAD 2>/dev/null || echo '(detached)')"
    printf 'core.bare %s\n' "$(git -C "$DRIVE_REPO_ROOT" config --get core.bare 2>/dev/null || echo '(unset)')"
    git -C "$DRIVE_REPO_ROOT" for-each-ref --format='ref       %(refname) %(objectname)' refs/heads 2>/dev/null |
        LC_ALL=C sort
}

if [ -n "$DRIVE_REPO_ROOT" ]; then
    DRIVE_FINGERPRINT_BEFORE="$(drive_repo_fingerprint)"
else
    echo "${DRIVE_NAME}: not inside a git checkout — the real-repository tripwire is not armed." >&2
fi

# The physical path, because `git rev-parse --show-toplevel` and
# `git worktree list` can spell the same directory differently on a machine
# whose temp directory is a symlink (`/tmp` -> `/private/tmp` on macOS), and the
# whole excuse below turns on comparing two paths.
drive__physical_path() {
    (cd "$1" 2>/dev/null && pwd -P) || printf '%s' "$1"
}

# Every ref that a worktree OTHER than this one has checked out, one per line,
# asked fresh at the moment of the call.
drive_peer_checked_out_refs() {
    local wt="" line
    git -C "$DRIVE_REPO_ROOT" worktree list --porcelain 2>/dev/null |
        while IFS= read -r line; do
            case "$line" in
            "worktree "*) wt="${line#worktree }" ;;
            "branch "*)
                [ "$wt" = "$DRIVE_REPO_ROOT" ] && continue
                [ "$(drive__physical_path "$wt")" = "$(drive__physical_path "$DRIVE_REPO_ROOT")" ] && continue
                printf '%s\n' "${line#branch }"
                ;;
            esac
        done
}

# awk rather than a shell loop: the fingerprint's ref lines are
# `ref <name> <sha>` under padding, and a field is a field.
drive__ref_lines() { printf '%s\n' "$1" | awk '$1 == "ref" { print }'; }
drive__head_lines() { printf '%s\n' "$1" | awk '$1 != "ref" { print }'; }
drive__ref_names() { printf '%s\n' "$1" | awk '$1 == "ref" { print $2 }'; }
drive__ref_sha() { printf '%s\n' "$1" | awk -v want="$2" '$1 == "ref" && $2 == want { print $3 }'; }

# Returns 0 if the real repository is as this drive found it, or differs only in
# ways somebody else demonstrably owns — each of those printed with its reason.
drive_tripwire_check() {
    [ -n "${DRIVE_REPO_ROOT:-}" ] || return 0
    local after
    after="$(drive_repo_fingerprint)"
    [ "$after" != "$DRIVE_FINGERPRINT_BEFORE" ] || return 0

    local before_refs after_refs peers peers_nl names name before_sha after_sha
    local excused="" unexcused=0
    before_refs="$(drive__ref_lines "$DRIVE_FINGERPRINT_BEFORE")"
    after_refs="$(drive__ref_lines "$after")"
    peers="$(drive_peer_checked_out_refs)"
    # Newline-delimited on both ends so membership is one substring test. NOT
    # `printf … | grep -qx`: a reader that answers on its first match closes the
    # pipe and orphans its producer under `set -o pipefail`, which is the shape
    # `test_sweep.sh::case_a_presence_probe_survives_a_long_scan` censuses — and
    # it found this line.
    peers_nl=$'\n'"${peers}"$'\n'

    # This checkout's own three lines are nobody else's to move.
    if [ "$(drive__head_lines "$DRIVE_FINGERPRINT_BEFORE")" != "$(drive__head_lines "$after")" ]; then
        unexcused=$((unexcused + 1))
    fi

    names="$(printf '%s\n%s\n' "$(drive__ref_names "$before_refs")" "$(drive__ref_names "$after_refs")" |
        LC_ALL=C sort -u)"
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        before_sha="$(drive__ref_sha "$before_refs" "$name")"
        after_sha="$(drive__ref_sha "$after_refs" "$name")"
        [ "$before_sha" != "$after_sha" ] || continue
        if [ -z "$after_sha" ]; then
            if git -C "$DRIVE_REPO_ROOT" merge-base --is-ancestor "$before_sha" refs/heads/main 2>/dev/null; then
                excused="${excused}  excused: ${name} — merged into main, reaped"$'\n'
                continue
            fi
        elif [ "${peers_nl#*$'\n'"${name}"$'\n'}" != "$peers_nl" ]; then
            if [ -z "$before_sha" ]; then
                excused="${excused}  excused: ${name} — created by a peer worktree"$'\n'
            else
                excused="${excused}  excused: ${name} — checked out by a peer worktree"$'\n'
            fi
            continue
        fi
        unexcused=$((unexcused + 1))
    done <<<"$names"

    if [ "$unexcused" -eq 0 ]; then
        # PRINTED, never silent: the first question after a surprising green is
        # which deltas the tripwire decided not to mind.
        echo "${DRIVE_NAME}: the repository moved while this ran, and every delta belongs to somebody else:" >&2
        printf '%s' "$excused" >&2
        return 0
    fi

    echo "!! ${DRIVE_NAME} MUTATED THE REAL REPOSITORY." >&2
    echo "   checkout: ${DRIVE_REPO_ROOT}" >&2
    echo "   A drive builds throwaway repositories and works in those. Anything it" >&2
    echo "   changed here it changed by accident, and nothing it asserted this run can" >&2
    echo "   be trusted. The delta, '-' as this drive found it and '+' as it left it:" >&2
    diff <(printf '%s\n' "$DRIVE_FINGERPRINT_BEFORE") <(printf '%s\n' "$after") |
        sed 's/^/     /' >&2 || true
    if [ -n "$excused" ]; then
        echo "   Some of it was somebody else's and is not the finding:" >&2
        printf '%s' "$excused" >&2
    fi
    echo "   What is left is NOT: a ref no worktree has checked out moved or appeared," >&2
    echo "   a branch vanished whose work was never on main — the sha above is the only" >&2
    echo "   copy of it — or this checkout's own HEAD, HEAD-ref or core.bare moved," >&2
    echo "   which nobody but this process could have done. That last one is the escape" >&2
    echo "   this file was written for, and the header is where the mechanism is." >&2
    echo "   Nothing this run asserted is trustworthy." >&2
    return 1
}

# --- 4 · THE CI EXEMPTION: a case's expectation is not the runner's ----------
#
# A DIFFERENT INCIDENT FROM THE THREE ABOVE, and it belongs here for the same
# reason they do: the alternative is six copies that drift.
#
# WHAT HAPPENED. A CI run once died at 14m34s, the deepest a run had reached.
# `scripts/gate_refuse.sh::refuse_if_piped` (the gate's), `quality/djb/rituals/merge.py::refuse_if_piped`
# and `deploy/release.sh:110` each refuse a piped stdout, and each EXEMPTS CI —
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
#   * `quality/tests/deploy/test_release.py` — the sixth drive, carrying the identical
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

# --- 4a · THE GATE'S OWN INPUT VARIABLES, stripped for section 4's reason -----
#
# THE SAME INCIDENT AGAIN, ONE GUARD OVER, and it was found by the run that was
# supposed to prove this cycle's work rather than by reasoning. `check.sh`'s
# full-gate sanction valve reads `DJB_GATE_SANCTION` and `DJB_GATE_CALLER`, and
# both are EXEMPTIONS in exactly the sense `CI` is: set, and a refusal does not
# fire. `rung-execution` §3 tells every builder to type a sanction on the
# command line for a by-hand full gate — so the variable is in the gate's
# environment, the gate's selftest leg spawns the drives, and every drive
# inherits it.
#
# WHAT THAT DID, measured on a real 20-minute run of this repository's own full
# gate with a typed sanction:
#
#     test_gate_lease: 193 passed, 12 FAILED
#     FAILED  a bare full gate with no sanction — does not say "REFUSING an unsanctioned FULL gate"
#            | !! REFUSING: a FULL gate is already running in THIS checkout.
#
# The case asked for the UNSANCTIONED refusal; the nested `check.sh` inherited
# the operator's sanction, sailed past the valve, and was stopped further down
# by the per-checkout lock — a different refusal, in different words, for a
# different reason. The same leak carried the two `--bank` cases past the valve
# into legs that then failed on the scratch work tree. Twelve red assertions,
# one leaked variable, and every one of them green when the same drive is run
# by hand from a shell that has no sanction in it. THAT GAP IS THE DEFECT: a
# case whose verdict depends on who started it is not a case.
#
# The three cases also clear these at their own call sites, which is this
# file's declared doctrine (section 4: a case that wants an exemption sets it
# where it wants it). This strip is the belt that makes the doctrine hold for
# every drive that has not thought about it yet — including the ones nobody has
# written.
#
# A THIRD TIME, AND THE THIRD ONE IS NOT AN EXEMPTION — it is an INPUT, which is
# why the section's title is now the wider word. `DJB_GATE_PYTEST_SEED` types
# the random seed both pytest passes carry, and `.github/workflows/ci.yml` sets
# it on the step that runs the gate so that every shard of one run splits the
# same collection order. That step is also the step that runs the selftest leg,
# so on a runner every drive inherits a TYPED seed — and
# `test_list_legs.sh::case_a_typed_seed_reaches_both_passes` has a third
# assertion that runs the seam with no assignment of its own and expects the
# gate to MINT one:
#
#     FAILED  and an untyped seed is minted, and says THAT
#            | an untyped run did not print a minted seed with its provenance
#
# One red on three CI shards, green on every laptop, over identical bytes:
# the case asked for the minted path and the runner's environment handed it the
# typed one. Same shape as the sanction leak above, one variable over — a case
# whose verdict depends on who started it is not a case — so the belt widens
# rather than that one case learning to clear it.
#
# THE LIST HAS A TOOTH TOO, and it is about the CLASS rather than this one
# variable: `test_drive_preamble.sh::case_every_variable_the_workflow_sets_is_accounted_for`
# lifts EVERY name `.github/workflows/ci.yml` puts into the step that runs a
# unit — the workflow-level `env:` block, the gate step's own `env:`, and what
# the derivation step writes into `$GITHUB_ENV` — and asserts each one is either
# stripped here or DECLARED inherited in section 4b below. A knob CI grows and
# nobody thinks about is then a red case, not a green drive measuring somebody
# else's branch.
# A FOURTH, AND IT IS AN EXEMPTION IN EXACTLY `CI`'s SENSE. `DJB_LOOP_HERE`
# is what lets a `--loop` run off a verifier box, and an operator who exports
# one in the shell that starts a gate hands it to the selftest leg, to every
# drive, and to every child `check.sh --loop` a drive spawns — so a case about
# the refusal would meet the permission instead, and pass. The drives that
# legitimately need it type it AT THEIR OWN CALL SITE (`test_list_legs.sh`'s
# `DRY_LOOP_HERE` on the dry runs, which announce legs and run no body), which
# is this file's doctrine for the whole class.
#
# A FIFTH, SIXTH AND SEVENTH, AND THEY ARE THE DRAWERS' OWN SEAMS.
# `DJB_LOCAL_DRIVES_DIR` moves the product's DRIVE drawer and
# `DJB_LOCAL_ENV_KEYS` moves the keys file section 4c reads, exactly as
# `DJB_LOCAL_LEGS_DIR` moves the leg drawer — each exists so a drive can point
# the reader at a planted set under its own scratch directory instead of
# writing into the checkout the gate is measuring. Inherited by a CHILD drive
# they would point that child's reader at somebody else's plant, which is
# section 4's whole argument one drawer over. Section 4c reads its own name
# BEFORE this loop runs, so being on this list costs the reader nothing.
# AN EIGHTH, AND IT IS THE WALLS FILE. `DJB_MEMBER_WALLS_OUT` is set on every CI
# row so the selftest leg appends one `member-walls/1` row per member it runs;
# inherited by a drive that runs a planted selftest body, it would append the
# PLANTED members' walls to the row's real file, and the fold's harvest refuses
# a row for a member the population does not have. A case that drives the
# append names its own file at its own call site.
# `STACK_REGISTRY`, `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`: the registry step's inputs; no drive reads them, and a drive never holds a credential it did not ask for.
# `DJB_GATE_LEGS_DRY` (every leg announced, no body run), `DJB_GATE_BOX_MARKER(S)` (a child that believes it is a verifier box), `DJB_LOOP_NO_IMPACT` and `DJB_GATE_MEMBER_DURATIONS` (a selection and a pricing the child never chose): each changes what a child gate concludes; a case that wants one types it at its own call site.
# THE LIST IS `quality/djb/env.py::STEERS` SPELLED IN SHELL, held equal by `test_fixtures.py::test_the_preambles_hand_list_is_env_steers`.
# `DJB_LAYER_HOOK_JUDGED`: the pre-commit hook's word to its own `--fast` that rule 95 judged the staged set; a child gate that inherited it would skip rule 95 on a set nobody judged.
DRIVE_GATE_VARS="SELFTEST_PLAN DJB_SELFTEST_PLAN DJB_GATE_SANCTION DJB_GATE_CALLER DJB_GATE_PYTEST_SEED DJB_LOOP_HERE DJB_LAYER_HOOK_JUDGED DJB_GATE_LEGS_DRY DJB_GATE_BOX_MARKER DJB_GATE_BOX_MARKERS DJB_GATE_MEMBER_DURATIONS DJB_LOOP_NO_IMPACT DJB_LOCAL_LEGS_DIR DJB_LOCAL_LEGS_KNOWN_NAMES DJB_LOCAL_LEGS_TEMPLATE_UNITS DJB_LOCAL_LEGS_CHANGED_FILES DJB_LOCAL_DRIVES_DIR DJB_LOCAL_ENV_KEYS DJB_MEMBER_WALLS_OUT STACK_REGISTRY DOCKERHUB_USERNAME DOCKERHUB_TOKEN"

# --- 4b · WHAT CI SETS THAT A DRIVE IS MEANT TO INHERIT -----------------------
#
# THE OTHER HALF OF THE CENSUS, and it exists because "strip everything CI sets"
# is the wrong answer. Most of what `ci.yml` exports is THE WORLD'S COORDINATES
# — where Postgres is, what it is called, where the object store is and with
# what credential — and a drive that unset those would be a drive that cannot
# reach the stack it is measuring. Section 4's rule is about a variable that
# changes what a case CONCLUDES; these change what the case can DIAL.
#
# So they are named rather than ignored. A name here is a claim that somebody
# looked at it and decided a drive should stand on it — which is what makes the
# census above able to say "this one is new" instead of "this one is unlisted".
#
# AND A NAME HERE IS NOT A PROMISE THAT NO CASE CARES. `DATABASE_NAME` is the
# worked example of exactly that, and it cost three red assertions on the same
# CI run: `scripts/db.sh:216` exports it WITH a provenance label, and
# `test_db_pin.sh`'s `run_leg_in` set the name for its scratch checkout and left
# the launcher's label in place — so on a runner, where the name arrives
# exported, the label said `exported` and the leg looked up a database nothing
# had created. The fix was at the case, which is section 4's declared doctrine
# for exactly this population ("a drive whose expectation turns on
# `DATABASE_NAME` pins that itself, at the case"). This list is where a reader
# finds out that such a case is possible.
# Read by the census in `test_drive_preamble.sh`, never by this file: unlike
# `DRIVE_GATE_VARS` this list is a DECLARATION rather than an instruction, so
# there is nothing here to act on it.
# shellcheck disable=SC2034
# `PASSES` and `LANE` join `UNIT`, `SHARD` and `PR_BASE`: the row's own
# coordinates, read by the workflow's gate step and by no script under test.
# `DJB_STACK_REGISTRY` is the compose registry prefix: a drive's compose call resolves the same refs as the stack.
DRIVE_INHERITED_VARS="UNITS DJB_STACK_REGISTRY DATABASE_NAME DATABASE_HOST DATABASE_PORT DATABASE_USER DATABASE_PASSWORD REDIS_URL CACHE_URL AWS_S3_ENDPOINT_URL AWS_S3_REGION_NAME AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN PYTHON_VERSION PYTEST_SHARDS UNIT SHARD PR_BASE PASSES LANE ZITADEL_ISSUER ZITADEL_PAT BRAND_ACCENT EMAIL_HOST EMAIL_PORT SERVER_EMAIL"

# --- 4c · WHAT THE PRODUCT DECLARES ITS OWN DRIVES NEED -----------------------
#
# THE SAME MECHANISM AS 4a, INVERTED, AND THAT IS THE WHOLE IDEA. The two lists
# above are the TEMPLATE's: it strips what IT sets, and it declares what CI sets
# that a drive should stand on. Neither of them can name a knob a PRODUCT
# invented, because the template has never heard of it — and the only place to
# put one was inside `DRIVE_GATE_VARS` and `DRIVE_INHERITED_VARS`, which is an
# edit to a template-owned file. The first consumer's v2.1.0 CHANGELOG
# INSTRUCTED that edit, in as many words; the fold then priced it, along with
# the twenty other edits like it.
#
# SO THE PRODUCT DECLARES BESIDE US: `scripts/local/env_keys`, one variable NAME
# per line — the drawer sibling of `scripts/local/legs/` and
# `scripts/local/drives/`, under the same platform-extension-1 rule, and the
# template never ships the path so a release can never conflict with one.
#
#   * IT MAY NAME THE PRODUCT'S OWN KEYS AND NOTHING ELSE, and that is a
#     REFUSAL rather than a convention. The first draft of this section let the
#     drawer re-admit a name the lists above strip, on the theory that a
#     product overriding a template knob had at least said so in a file a
#     reviewer can open. It had not thought about what those particular names
#     ARE: `DJB_GATE_SANCTION` is the valve that lets an unsanctioned FULL gate
#     run, `DJB_LOOP_HERE` the one that lets a `--loop` run off a verifier box,
#     and `CI` the one that stands down the piped-stdout refusal — so a drawer
#     naming those five turns any product drive on a runner into a shell that
#     can start a bare `check.sh` with every guard already stood down. There is
#     no product whose own knob is spelled `CI`. A name in
#     `DRIVE_GATE_VARS`, in `DRIVE_CI_VARS`, or beginning `DJB_GATE_`,
#     `DJB_LOOP_` or `DJB_LOCAL_` is EXIT 2 naming it and the list it belongs
#     to. (Found in review; the first draft of this section shipped the hole.)
#   * WHICH IS ALSO WHY "KEPT" NEEDS NO CODE. Nothing below strips a name that
#     is not on one of the template's two lists, and the refusal above means a
#     drawer name is never on one — so a declared key survives both scrubs by
#     construction, and an override branch would be a line that can only ever
#     be reached by the shape this section refuses.
#   * A name here joins `DRIVE_INHERITED_VARS`, so
#     `test_drive_preamble.sh::case_every_variable_the_workflow_sets_is_accounted_for`
#     reads the product's own CI knobs as accounted for instead of as the
#     "nobody has thought about this one" red it exists to print. That is the
#     drawer's whole job.
#   * The values are NEVER here. This file reads NAMES; a value in the drawer
#     would be a secret in a tracked file, and the line is refused on its shape
#     before anything else looks at it.
#
# MALFORMED IS EXIT 2, NAMING THE FILE AND THE LINE. A blank line and a
# whole-line `#` comment are the only things skipped; anything that is not a
# shell identifier — an `=`, a space, a quote, a lower-case habit — is a drive
# that cannot look, because a drawer this file half-understands is a strip it
# half-applies. Absent, every line below is byte-identical to a tree that has
# never heard of a drawer.
DRIVE_LOCAL_ENV_KEYS=""
DRIVE_LOCAL_ENV_KEYS_FILE="${DJB_LOCAL_ENV_KEYS:-scripts/local/env_keys}"
if [ -f "$DRIVE_LOCAL_ENV_KEYS_FILE" ]; then
    _drive_env_key_lineno=0
    while IFS= read -r _drive_env_key_line || [ -n "$_drive_env_key_line" ]; do
        _drive_env_key_lineno=$((_drive_env_key_lineno + 1))
        # Trailing carriage returns and surrounding blanks are the two ways a
        # correct name arrives unreadable; both are the product's typo and
        # neither is worth an exit 2, so they are trimmed and the SHAPE is what
        # is judged.
        _drive_env_key_line="${_drive_env_key_line%$'\r'}"
        _drive_env_key_line="${_drive_env_key_line#"${_drive_env_key_line%%[![:space:]]*}"}"
        _drive_env_key_line="${_drive_env_key_line%"${_drive_env_key_line##*[![:space:]]}"}"
        case "$_drive_env_key_line" in
        '' | '#'*) continue ;;
        esac
        case "$_drive_env_key_line" in
        *[!A-Za-z0-9_]* | [0-9]*)
            drive_cannot_look "${DRIVE_LOCAL_ENV_KEYS_FILE}:${_drive_env_key_lineno}: '${_drive_env_key_line}' is not a variable NAME — one identifier per line ([A-Za-z_][A-Za-z0-9_]*), no '=', no value, no quotes. A drawer this preamble half-understands is a strip it half-applies."
            ;;
        esac
        # THE RESERVED NAMES. A drawer may declare the PRODUCT's keys; the
        # template's own are not a product's to re-admit, and the prefixes are
        # in the refusal so a knob this template grows TOMORROW is refused the
        # day a product's drawer collides with it rather than silently winning.
        case " ${DRIVE_GATE_VARS} ${DRIVE_CI_VARS} " in
        *" ${_drive_env_key_line} "*)
            drive_cannot_look "${DRIVE_LOCAL_ENV_KEYS_FILE}:${_drive_env_key_lineno}: '${_drive_env_key_line}' is a name THIS TEMPLATE strips from every drive on purpose (DRIVE_GATE_VARS / DRIVE_CI_VARS). Re-admitting it hands a product drive the gate's own valves — the full-gate sanction, the loop-here permission, the CI exemption — so a drive on a runner could start a bare check.sh with every guard stood down. The drawer names the PRODUCT's keys only."
            ;;
        esac
        case "$_drive_env_key_line" in
        DJB_GATE_* | DJB_LOOP_* | DJB_LOCAL_*)
            drive_cannot_look "${DRIVE_LOCAL_ENV_KEYS_FILE}:${_drive_env_key_lineno}: '${_drive_env_key_line}' is in this template's own DJB_GATE_/DJB_LOOP_/DJB_LOCAL_ namespace. Those are the gate's valves and the drawers' own seams; a product's key carries the product's own prefix."
            ;;
        esac
        DRIVE_LOCAL_ENV_KEYS="${DRIVE_LOCAL_ENV_KEYS}${DRIVE_LOCAL_ENV_KEYS:+ }${_drive_env_key_line}"
    done <"$DRIVE_LOCAL_ENV_KEYS_FILE"
    unset _drive_env_key_line _drive_env_key_lineno
fi

if [ -n "$DRIVE_LOCAL_ENV_KEYS" ]; then
    # DECLARED INHERITED, for the census one screen up. Appended rather than
    # merged into the literal: the template's own list stays readable as the
    # template's.
    DRIVE_INHERITED_VARS="${DRIVE_INHERITED_VARS} ${DRIVE_LOCAL_ENV_KEYS}"
    echo "${DRIVE_NAME}: product env keys declared (${DRIVE_LOCAL_ENV_KEYS_FILE}): ${DRIVE_LOCAL_ENV_KEYS}"
fi

DRIVE_GATE_STRIPPED=""
for _drive_gate_var in $DRIVE_GATE_VARS; do
    if [ -n "${!_drive_gate_var+set}" ]; then
        DRIVE_GATE_STRIPPED="${DRIVE_GATE_STRIPPED}${DRIVE_GATE_STRIPPED:+ }${_drive_gate_var}"
        unset "$_drive_gate_var"
    fi
done
unset _drive_gate_var

if [ -n "$DRIVE_GATE_STRIPPED" ]; then
    echo "${DRIVE_NAME}: gate input variables unset for this drive: ${DRIVE_GATE_STRIPPED}"
fi
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
# MEASURED, and it depends on the bash. On GNU bash 3.2.57 (macOS — the laptop,
# where the pre-commit hook runs) a `set -u` death on an unbound variable hands
# THE EXIT TRAP `$? = 0`: `drive_epilogue`'s `exit "$rc"` exits **0**,
# `check.sh` reads the drive as green, and a driver that never reached its own
# summary line reports success. On GNU bash 5.2.15 (the verifier boxes, CI) the
# same death hands the trap `$? = 1`, so there it is already red. Minimal repro,
# and it is three lines:
#
#     set -euo pipefail
#     trap 'rc=$?; echo "trap saw rc=$rc"; exit "$rc"' EXIT
#     echo "$NOPE"          # -> "unbound variable", "trap saw rc=0" on 3.2 (1 on 5.2)
#
# `set -E` with `trap ... ERR` does NOT catch it either — tested on 3.2. And the
# class is wider than one bash's symptom: a drive that `exit 0`s from inside a
# case never reaches its summary on ANY bash. There is no way for this file to
# notice either on its own, so a drive has to say it finished.
#
# IT IS ON BY DEFAULT. It began opt-in, so the first commit would not hand every
# drive a new way to fail at once; every drive then took the one line, and a
# drive that says nothing is now one whose silence cannot be read as a pass.
# `test_drive_preamble.sh` censuses every registered drive for the call, and
# proves the default with a planted drive that leaves from inside a case.
DRIVE_FINISHED=0

# ON unless a drive opts OUT by setting this to 0 after sourcing this file, with
# a comment saying why (none does). Two variables rather than one so that
# "never armed" and "armed and died" are different states rather than one
# ambiguous zero.
DRIVE_OPTED_IN_TO_FINISH=1

# --- 5a · LIST MODE IS NOT A RUN ---------------------------------------------
#
# THE DEFECT, and it is section 5's own sentence pointed at the wrong run.
# Every drive here offers `--list`: name the cases and stop, run nothing. A
# drive in list mode therefore never reaches `drive_finished` — correctly,
# because there is nothing to finish — and section 5 read that as the state it
# was built to catch. Measured on the tree this fixes, over every drive that
# offers the flag:
#
#     test_db_template.sh   --list -> exit 2, "DIED BEFORE REPORTING"
#     test_gate_lease.sh    --list -> exit 2, "DIED BEFORE REPORTING"
#     test_loop_tier.sh     --list -> exit 2, "DIED BEFORE REPORTING"
#     test_rung_start.sh    --list -> exit 2, "DIED BEFORE REPORTING"
#     test_serve_port.sh    --list -> exit 2, "DIED BEFORE REPORTING"
#     test_verify_start.sh  --list -> exit 2, "DIED BEFORE REPORTING"
#
# Six of the six drives that BOTH offer `--list` and opt into the sentinel —
# the population is exact, not a sample. The seven that read exit 0 are the
# ones that never opted in, so they were never armed rather than ever safe.
#
# WHY IT MATTERS MORE THAN A WRONG STATUS. The banner says "nothing this run
# printed can be trusted" over a list that is perfectly correct, and it says it
# in the voice of the one guard here whose whole job is to be believed. A
# reader who learns to ignore this sentence on `--list` is a reader who ignores
# it on the run it was written for; and `--list` is what a verifier asks a
# drive before deciding which case to reach for, so the first thing an unknown
# drive says about itself was that it had died.
#
# THE FIX IS HERE AND NOT IN THIRTEEN DRIVES, for section 4's reason: the
# alternative is thirteen copies that drift. A sourced file's positional
# parameters are its CALLER'S, so the preamble can see the flag the drive is
# about to parse — the same argument the drive will answer a few lines later,
# read once, before any case could have run.
#
# IT DISARMS ONE CHECK AND NOTHING ELSE. The tripwire still runs, the cleanups
# still run, the signal handlers are unchanged: a list-mode run that somehow
# moved the real repository is still exit 2, because that claim has nothing to
# do with whether cases ran. What list mode buys is exemption from a sentence
# about a run that was never started.
#
# DECLARED RESIDUAL: a drive whose `--list` is spelled some other way is not
# recognised, and gets the old banner. This reads exactly the token the whole
# family already uses (`--list`, in all thirteen), so the residual is a drive
# that has already broken the family's convention.
DRIVE_LIST_MODE=0
case "${1:-}" in
--list) DRIVE_LIST_MODE=1 ;;
esac

# Called by a drive immediately before its own final `exit`. Everything after it
# is the epilogue's.
drive_finished() {
    DRIVE_FINISHED=1
}

drive_epilogue() {
    local rc=$?
    local cleanup tripwire=0 summarise=0
    # Cleanups, then the tripwire, then the report: every line the tripwire
    # prints (an excuse included) lands above the summary, which stays last.
    while IFS= read -r cleanup; do
        [ -n "$cleanup" ] || continue
        eval "$cleanup" || true
    done <<<"$DRIVE_CLEANUPS"
    drive_tripwire_check || tripwire=1
    # Section 10: a drive on the harness prints no summary of its own, and a
    # red it counted is its status — only for a drive that FINISHED.
    # Guarded: a drive that died inside this file before section 10 was read has no such function.
    if [ "$DRIVE_FINISHED" = "1" ] && [ "${DRIVE_LIST_MODE:-0}" != "1" ] &&
        declare -F drive__on_the_harness >/dev/null && drive__on_the_harness; then
        summarise=1
    fi
    # Section 9: every skip, grouped by kind, above the summary.
    if declare -F drive__skip_report >/dev/null; then drive__skip_report || true; fi
    if [ "$summarise" = "1" ]; then
        drive_summary
        if [ "$rc" = "0" ] && [ "${FAILED:-0}" != "0" ]; then
            rc=1
        fi
        # The whole-run floor: a tracked drive that recorded nothing cleared nothing; a parent's planted child is untracked.
        if [ "$rc" = "0" ] && [ -z "${DRIVE_ONLY_CASE:-}" ] && [ "${DRIVE__NESTED:-0}" = 0 ] &&
            [ $((${PASSED:-0} + ${FAILED:-0} + ${DRIVE_SKIPPED:-0})) = 0 ] &&
            git -C "${DRIVE__ROOT:-.}" ls-files --error-unmatch -- "$DRIVE__SOURCE" >/dev/null 2>&1; then
            echo "!! ${DRIVE_NAME}: the run asserted nothing — no case recorded an ok, bad or skip, so nothing was cleared." >&2
            rc=2
        fi
    fi
    if [ "$tripwire" = "1" ]; then
        # 2 outranks everything, including a pass and including a case that
        # failed for its own reasons: this run measured nothing it can vouch for.
        exit 2
    fi
    # Section 10: a run asked for cases it never reached cleared nothing.
    local unrun=""
    if [ "$rc" = "0" ] && [ -n "${DRIVE_ONLY_CASE:-}" ] && [ "$DRIVE_FINISHED" = "1" ]; then
        unrun="$(drive__cases_unrun | tr '\n' ' ')"
    fi
    if [ -n "$unrun" ]; then
        echo "!! ${DRIVE_NAME}: --case ${unrun% } was asked for and the drive never ran it" >&2
        echo "   through drive_run_case. Nothing was asserted for it, so nothing was cleared." >&2
        rc=2
    fi
    # Section 5. A drive that opted in and did NOT reach its own end, while the
    # masked status says 0, is could-not-look — never a pass. Section 5a: list
    # mode ran no cases on purpose, so there was no end to reach.
    if [ "${DRIVE_OPTED_IN_TO_FINISH:-0}" = "1" ] && [ "${DRIVE_LIST_MODE:-0}" != "1" ] &&
        [ "$DRIVE_FINISHED" != "1" ] && [ "$rc" = "0" ]; then
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

# --- 6 · A DRIVE THAT WAS KILLED STILL OWES ITS CLEANUPS ---------------------
#
# A BELT, AND THE MEASUREMENT THAT DEMOTED IT FROM A FIX. This section was
# written to close what looked like a hole — a drive somebody KILLED skipping
# every `drive_at_exit` cleanup, because an untrapped fatal signal was assumed
# not to run a bash EXIT trap. THAT ASSUMPTION IS WRONG ON THE BASH THIS
# REPOSITORY RUNS, and it was wrong before this section existed. Measured on GNU
# bash 3.2.57 (arm64-apple-darwin24), a script whose only trap is on EXIT:
#
#     TERM -> rc=143  EXIT trap RAN
#     INT  -> rc=130  EXIT trap RAN
#     HUP  -> rc=129  EXIT trap RAN
#
# So bash runs the EXIT trap for all three on its own, and the cleanups, the
# tripwire and section 5 were already reached on a killed drive. This section
# therefore fixes nothing. It is kept for two things it does buy, and it is
# labelled a belt so nobody later reads it as the mechanism:
#
#   1. IT SAYS SO OUT LOUD. A gate transcript that ends mid-drive is otherwise
#      indistinguishable from a drive that hung; the announcement line names the
#      signal. `test_runbook_recipes.sh` asserts that line, so this is watched.
#   2. IT MAKES THE PATH EXPLICIT RATHER THAN INHERITED. The behaviour above is
#      real but undocumented-feeling, and the next reader who deletes a cleanup
#      "because a killed drive skips it anyway" is reading the same wrong thing
#      this section's first draft did. The measurement lives here now.
#
# HOW IT WORKS: three signals bridged to the ordinary exit path. The handler
# cleans nothing itself — it exits, which runs `drive_epilogue`, which runs the
# same cleanups in the same order for a killed drive as for a finished one. One
# cleanup list, one tripwire, one code path.
#
# THE EXIT CODE IS THE SHELL CONVENTION, `128 + signal`, which is also what bash
# reports without the trap, so a caller reading the status sees exactly what it
# saw before (143 for TERM, 130 for INT) and never a pass.
#
# AND A CONSUMER READS THAT STATUS OUT OF `drive_epilogue`'S OWN `local rc`.
# Bash scopes locals dynamically, so a cleanup this epilogue `eval`s runs inside
# this frame and can see `rc` — which is the ONLY place a signal status is
# visible at cleanup time, since the epilogue is the frame that captured `$?`.
# The swept gate_explain drive's `census_status_floor` did exactly that
# (reading it defensively: unset or non-numeric and it is not consulted) so a
# TERM-killed drive's 143 is never lowered to its census's 1. The name `rc` is
# therefore part of this section's contract and not an internal detail: renaming
# it would silently drop that floor with every case still green, which is the
# reason the fourth cell of that drive's floor case now pins it.
#
# WHY THESE THREE. `INT` is Ctrl-C and is what an operator does. `TERM` is what
# every harness, `kill` and supervisor sends. `HUP` is a closed terminal. `KILL`
# cannot be trapped by anything, ever, and is therefore this section's first
# declared blind spot rather than an omission.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * `SIGKILL`. Untrappable. A `kill -9`'d drive leaves everything, and no
#     shell-level guard can change that.
#   * THE ONE BEHAVIOUR IT DOES CHANGE: a killed drive now EXITS with 128+N
#     instead of dying FROM the signal, so a parent that asks `WIFSIGNALED`
#     rather than reading the status sees a normal exit. Nothing in this tree
#     asks — `scripts/check.sh` reads `$?` — and it is written down here because
#     a difference nobody declared is the kind somebody discovers.
#   * A SIGNAL DELIVERED TO THE DRIVE'S SHELL ALONE WHILE IT WAITS ON A LONG
#     CHILD. Bash runs a trap for a signal received during a foreground command
#     only after that command returns, so a TERM aimed at the shell's pid while
#     it is thirty seconds into a `uv run` is honoured thirty seconds later. The
#     covered case — and the one that actually happens — is a signal to the
#     process GROUP (Ctrl-C, a harness reaping its children,
#     `scripts/kill_mine.sh`), where the child dies too and the wait returns at
#     once.
#   * A DRIVE THAT INSTALLS ITS OWN `trap ... TERM` afterwards, which removes
#     this one exactly as a bare `trap ... EXIT` removes the epilogue. The
#     header above says so for EXIT; it is the same sentence for these three.
DRIVE_KILLED_BY=""

drive_on_signal() {
    DRIVE_KILLED_BY="$1"
    echo "${DRIVE_NAME}: killed by SIG${1} — running the registered cleanups before dying." >&2
    exit "$((128 + $2))"
}

trap 'drive_on_signal INT 2' INT
trap 'drive_on_signal TERM 15' TERM
trap 'drive_on_signal HUP 1' HUP

# --- 7 · A CAPTURE A CASE CANNOT READ IS COULD-NOT-LOOK, NEVER A PASS ---------
#
# THE SHAPE THIS CLOSES, and it is the one shape a green drive can be made of
# nothing. Every drive in this directory runs a subject, redirects its combined
# output into a file, and then asserts over that file — `says`, `says_not`,
# `grep -q`, a count. Three of those readers answer the same way about a capture
# that is EMPTY as about one that is there and does not carry the needle:
#
#   * a NEGATIVE assertion (`says_not`, "the run printed no clamp line") is
#     TRUE of a file with nothing in it, and prints `ok`;
#   * a count over an empty file is `0`, which is what several floors want;
#   * a `grep` handed a path that does not exist exits 2 and a reader that only
#     branches on "did it match" reads that as "it did not".
#
# So a subject that never started — a `uv` that is not on PATH, a clone that was
# not made, a variable a refactor emptied — produces a drive that passes without
# looking at anything. That is the failure mode `rung-execution` §2 names as the
# one an instrument cannot find in itself, and it is why this floor lives here
# rather than in one drive: four drives assert over captures, and four copies of
# a floor is three that drift.
#
# WHAT IT IS NOT. It is not an assertion about the SUBJECT's exit status — a
# refusal that exits 2 and prints its sentence is a perfectly good capture, and
# several cases here want exactly that. It is an assertion about the CAPTURE:
# there is a path, there is a file at it, and it has bytes. The exit code is
# carried into the refusal's sentence so a reader is never told "empty" without
# being told what the run that produced it returned.
#
# drive_capture_refusal <label> <path> <exit code> — the sentence to refuse
# with, on stdout, and exit 0 when the capture cannot be read; exit 1 (printing
# nothing) when it can. The caller turns a returned sentence into its own
# `cannot_look`, because each drive's refusal names itself and this file does
# not know which drive is speaking.
drive_capture_refusal() {
    local label=$1 path=$2 rc=${3:-<none>}
    if [ -z "$path" ]; then
        printf '%s asserts over a capture with no path at all (the run it names exited %s). A reader handed an empty path answers "no match" to every question, so every negative assertion below it would have printed ok without looking.\n' \
            "${label:-an unnamed case}" "$rc"
        return 0
    fi
    if [ ! -f "$path" ]; then
        printf '%s asserts over %s, which is not a file (the run it names exited %s). Nothing was captured, so nothing below it was measured.\n' \
            "${label:-an unnamed case}" "$path" "$rc"
        return 0
    fi
    if [ ! -s "$path" ]; then
        printf '%s asserts over %s, which is EMPTY (the run it names exited %s). An empty capture answers "no" to every needle, so a negative assertion over it is a pass nobody looked at.\n' \
            "${label:-an unnamed case}" "$path" "$rc"
        return 0
    fi
    return 1
}

# --- 8 · THE BASE REF A DRIVE COMPARES AGAINST, DERIVED AND NEVER TYPED ------
#
# THE DEFECT, measured rather than reasoned. Three drives asked git for
# `main` by that bare name — `git rev-parse main:scripts/setup.sh`,
# `git rev-parse --verify -q main` — and every one of them was written in a
# checkout that has a local `main`. A GitHub runner on a pull request does not:
# `actions/checkout` leaves HEAD DETACHED at the merge commit and creates no
# local branch at all. What that does to the two spellings is different, and
# the silent one is the one that cost a green run:
#
#   * `git rev-parse --verify -q main` exits 1 and prints nothing, so the case
#     that guards it says `bad "this checkout has no local main"` — loud, and
#     wrong only in that a perfectly good base ref (`refs/remotes/origin/main`)
#     was sitting there unasked.
#   * `git rev-parse main:scripts/setup.sh 2>/dev/null || true` exits 1 too —
#     and the `|| true` swallows it, so the substitution captures git's
#     ERROR-PATH stdout, which is THE ARGUMENT ITSELF. Measured on a detached
#     no-main clone of this repository:
#
#         scripts/gate_lease.sh  main main:scr vs HEAD 66f86a3f
#         scripts/setup.sh       main main:scr vs HEAD 5ca24c45
#         .env.example           main main:.en vs HEAD b54efef2
#
#     Three blob comparisons, none of them between two blobs, and the failure
#     reads as three files that moved. A string that is not a sha, truncated to
#     eight characters and printed in a column of shas, is the shape a reader
#     cannot see.
#
# SO THE RESOLUTION IS ONE FUNCTION AND IT IS HERE, for section 4's reason: the
# alternative is a copy per drive and the copies drift. The order, and every
# step of it is a deliberate answer to "which tree is this change measured
# against":
#
#   1. `DJB_BASE_REF`, TYPED. The operator or the harness knows something the
#      checkout does not — a PR base that is not `main`, a release branch, a
#      tag. A TYPED ref that does not resolve is a REFUSAL and never a silent
#      fall-through to `main`: somebody said which tree they meant, and
#      measuring a different one is worse than measuring none.
#   2. `refs/heads/main` — a laptop, a worktree, the primary checkout, and the
#      shape every one of these drives was written in.
#   3. `refs/remotes/origin/main` — the runner. `actions/checkout` fetches it
#      whenever it is given any depth beyond the default, and this workflow
#      takes `fetch-depth: 0`, so on CI it is there when a local `main` is not.
#   4. NOTHING. rc 1, with the three sources named on stderr.
#
# WHY rc 1 AND NOT exit 2, when a drive that cannot find its base ref plainly
# CANNOT LOOK. Because `drive_cannot_look` exits, and every caller here reads
# this through a command substitution — a SUBSHELL — where an exit kills the
# substitution and the drive sails on with an empty string. So the refusal is
# returned rather than taken, exactly as `drive_capture_refusal` (section 7)
# returns its sentence, and the caller spends its own `cannot_look` on it:
#
#     base="$(drive_base_ref "$ROOT")" || cannot_look "no base ref in $ROOT"
#
# That form — the substitution OUTSIDE the `||` — is the one that exits the
# drive with 2. `base="$(drive_base_ref || cannot_look …)"` does not, and is
# the mistake this paragraph exists to stop.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE BASE IS THE RIGHT ONE. This answers "which ref names the tree
#     this change is measured against", never "is that tree current". A stale
#     `origin/main` is a correct answer to this question and a wrong tree to
#     compare against, and nothing here can tell them apart.
#   * A DETACHED RUNNER WITH NO REMOTE REF EITHER — a depth-1 checkout, an
#     archive export, `git init` over an unpacked tarball. That is step 4, and
#     it is a refusal rather than a guess.
#   * THE REF'S SHA. Callers that want one ask git themselves; returning the
#     NAME is what lets `"${base}:path"` and `merge-base "$base" HEAD` both be
#     spelled from one answer.
#   * A `DJB_BASE_REF` LEFT EXPORTED IN SOMEBODY'S SHELL. It is a DIAL, not an
#     exemption — section 4b's population rather than section 4a's — so it is
#     deliberately NOT stripped: stripping it would make a typed base
#     unreachable, which is the whole feature. The residual is real and it is
#     the dial's own shape: an operator who exports one and forgets changes
#     what every drive in this tree compares against, silently, and the only
#     trace is that the answers moved. A drive whose case must compare against
#     `main` SPECIFICALLY pins that at the case, exactly as `test_sweep.sh`
#     pins `DATABASE_NAME`.
drive_base_ref() {
    local repo="${1:-.}" candidate

    if [ -n "${DJB_BASE_REF:-}" ]; then
        if git -C "$repo" rev-parse --verify -q "${DJB_BASE_REF}^{commit}" >/dev/null 2>&1; then
            printf '%s\n' "$DJB_BASE_REF"
            return 0
        fi
        drive__base_ref_refused "$repo" \
            "DJB_BASE_REF is typed as '${DJB_BASE_REF}' and does not resolve there"
        return 1
    fi

    for candidate in refs/heads/main refs/remotes/origin/main; do
        if git -C "$repo" rev-parse --verify -q "${candidate}^{commit}" >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    drive__base_ref_refused "$repo" "none of the three sources below resolves there"
    return 1
}

# The sentence, in one place, naming all three sources whichever one failed —
# because the reader of a refusal is deciding what to type next, and the answer
# is always one of these three.
drive__base_ref_refused() {
    local repo="$1" why="$2"
    echo "!! ${DRIVE_NAME}: no base ref for ${repo} — ${why}." >&2
    echo "   A drive compares this tree against a base, and the base is derived in" >&2
    echo "   this order, never typed into a case:" >&2
    echo "     1. \$DJB_BASE_REF          (typed; unresolvable is a refusal, not a fallback)" >&2
    echo "     2. refs/heads/main        (a laptop, a worktree, the primary checkout)" >&2
    echo "     3. refs/remotes/origin/main  (a runner: actions/checkout detaches HEAD)" >&2
    echo "   Nothing this drive would have compared can be trusted without one." >&2
}

# --- 9 · A TEMPLATE-ONLY CASE SAYS SO, AND THE SKIP IS COUNTED -----------------
#
# THE DEFECT, and it is the consumer's. A handful of cases here assert a
# property only the TEMPLATE'S OWN TREE has — a typed count of its own rules,
# a listing with no product drawer in it, a transcript compared against a tree
# with no drawer at all. On the template they are exactly right. On a product
# that folded a release they are red BY CONSTRUCTION, and the product's only
# move was to skip them by name and carry the edit as a divergence: the first
# consumer carried thirty-three such named skips across six drives, each one a
# hand edit to a template-owned file that the next fold fast-forwards away.
#
# THE REMEDY IS THE PYTHON SUITE'S OWN (`@pytest.mark.template_only`, honoured
# in `apps/conftest.py`), made available to a shell drive. ONE form:
#
#     case_x() {
#         template_only "<why this property is the template's own>" || return 0
#         ...
#     }
#
# On the template it returns 0 and prints nothing — the case runs exactly as
# before. On a tree that declares `rule_id_namespace:` it prints one `skipped`
# line naming the case and the reason, counts it, and returns 1, so the case
# returns before it asserts anything. The reason string is the Python side's,
# prefix for prefix — `template-only: this tree declares rule_id_namespace
# <ns>; <why>` — so a product reading either suite reads one sentence.
#
# THE KEY IS THE ENGINE'S READING, NEVER A SECOND ONE. "Has this tree folded"
# is answered by `quality.gate`'s own parse of the drawer (`LOCAL_DOC`), the
# RAW declaration, for the reason `_declared_namespace` gives: a product with a
# typo in its namespace is still a product. It is asked ONCE per drive, lazily
# (a drive whose template-only cases never run never pays an interpreter
# start), from the checkout root this preamble was sourced in, whatever the
# case has `cd`'d to since. An engine that cannot answer is could-not-look,
# never a guess in either direction: guessing "template" reds the product,
# guessing "product" skips the template's own cases silently.
#
# THE COUNT, AND WHERE IT IS PRINTED. `DRIVE_SKIPPED` is the number; a drive
# that carries a template-only case prints it on its own summary line
# (`N passed · M failed · K skipped`), and the epilogue prints every skipped
# case and its reason ABOVE that line, grouped by kind (`drive_skip`'s three:
# template-only, environment, could-not-pose), on every exit path. A drive with no
# template-only case prints nothing new at all: on the template, every other
# driver's output is byte-identical to what it was.
#
# WHAT IT IS NOT, declared rather than discovered:
#
#   * NOT A VALVE FOR A CASE THAT COULD DERIVE. A skip is not a pass: a case
#     this prints is a property that went undriven on this tree, and the line
#     says which. A case that can DERIVE its expectation from the tree it is
#     standing in (a count read off the listing rather than typed, a scratch
#     drawer rather than the tree's own) derives it instead — that case is not
#     template-only, it was only ever written on one shape.
#   * NOT AN ENVIRONMENT SWITCH. The state below is assigned at source time, so
#     nothing inherited can pre-answer the question; the drive of THIS
#     mechanism (`test_drive_preamble.sh`) sets `DRIVE__NAMESPACE_READ` and
#     `DRIVE__NAMESPACE` after sourcing — the device `_declared_namespace(doc=)`
#     uses on the Python side, for the same reason.
#   * NOT A STATUS. A template-only skip does not move the exit code: the
#     property is the template's, and the template's own run still drives it.
DRIVE_SKIPPED=0
DRIVE_SKIP_REASONS=""
DRIVE__NAMESPACE=""
DRIVE__NAMESPACE_READ=0
DRIVE__ROOT="$(pwd -P)"

# Sets DRIVE__NAMESPACE in THIS shell — never through a command substitution
# of this function, which would ask the engine on every call and cache nothing.
drive__read_namespace() {
    [ "$DRIVE__NAMESPACE_READ" = 1 ] && return 0
    local out="" rc=0
    out="$(cd "$DRIVE__ROOT" && uv run python -c '
import sys
sys.argv = ["gate"]
from quality import gate
print("namespace=" + str(gate.LOCAL_DOC.get("rule_id_namespace") or "").strip())
' 2>&1)" || rc=$?
    if [ "$rc" != 0 ] || ! grep -q '^namespace=' <<<"$out"; then
        printf '%s\n' "$out" | sed 's/^/   /' >&2
        drive_cannot_look "template_only: the engine's reading of rule_id_namespace (quality.gate LOCAL_DOC) did not answer in ${DRIVE__ROOT} (exit ${rc}) — whether this tree is the template's cannot be guessed in either direction"
    fi
    DRIVE__NAMESPACE="$(sed -n 's/^namespace=//p' <<<"$out" | tail -1)"
    DRIVE__NAMESPACE_READ=1
}

# template_only "<why>" — 0 on the template (run the case); on a tree that
# declares a namespace, print and count the skip and return 1.
template_only() {
    local why="${1:-}" case_name="${FUNCNAME[1]:-$DRIVE_NAME}" line
    [ -n "$why" ] || drive_cannot_look "template_only called from ${case_name} with no reason — a skip that cannot say why is a skip nobody can audit"
    drive__read_namespace
    [ -n "$DRIVE__NAMESPACE" ] || return 0
    # The sentence is apps/conftest.py's, byte for byte (apps/test_template_only.py reads this line).
    line="${case_name} — template-only: this tree declares rule_id_namespace ${DRIVE__NAMESPACE}; ${why}"
    drive__skip_line "$line"
    return 1
}

# The three kinds a skip may carry, each with the heading the report files it under.
DRIVE_SKIP_KINDS="template-only environment could-not-pose"
drive__skip_heading() {
    case "$1" in
    template-only) echo "the template's own properties, which this tree cannot pose" ;;
    environment) echo "what this machine's environment cannot reach" ;;
    could-not-pose) echo "a world the case could not build" ;;
    *) echo "counted by the drive without a kind the preamble knows" ;;
    esac
}

# drive_skip <kind> <why> — print and count a skip of one of DRIVE_SKIP_KINDS
# for the calling case, and return 1 so `drive_skip … || return 0` leaves it.
# A skip is not a status: it moves no exit code. template_only is its template-only form.
drive_skip() {
    local kind="${1:-}" why="${2:-}" case_name
    drive__label
    case_name="$DRIVE__LABEL"
    case " ${DRIVE_SKIP_KINDS} " in
    *" ${kind} "*) ;;
    *) drive_cannot_look "drive_skip: '${kind}' is not a kind — a skip is one of: ${DRIVE_SKIP_KINDS}" ;;
    esac
    [ -n "$why" ] || drive_cannot_look "drive_skip ${kind} called from ${case_name} with no reason — a skip that cannot say why is a skip nobody can audit"
    drive__skip_line "${case_name} — ${kind}: ${why}"
    return 1
}

drive__skip_line() {
    local line="$1"
    echo "  skipped  ${line}"
    DRIVE_SKIPPED=$((DRIVE_SKIPPED + 1))
    DRIVE_SKIP_REASONS="${DRIVE_SKIP_REASONS}    ${line}
"
}

# Printed by the epilogue above the summary, grouped by kind; nothing at all
# when nothing was skipped. A reason line is `    <case> — <kind>: <why>`.
drive__skip_report() {
    [ "${DRIVE_SKIPPED:-0}" != 0 ] || return 0
    echo "${DRIVE_NAME}: ${DRIVE_SKIPPED} skipped, by kind:"
    printf '%s' "$DRIVE_SKIP_REASONS" | awk -v kinds="$DRIVE_SKIP_KINDS" '
        BEGIN { n = split(kinds, order, " "); for (i = 1; i <= n; i++) known[order[i]] = 1 }
        NF {
            k = $0
            if (index(k, " — ") == 0) { k = "" } else { k = substr(k, index(k, " — ") + length(" — ")); sub(/:.*/, "", k) }
            if (!(k in known)) k = "unkinded"
            body[k] = body[k] $0 "\n"
        }
        END {
            order[n + 1] = "unkinded"
            for (i = 1; i <= n + 1; i++) if (order[i] in body) printf "%s\t%s", order[i], body[order[i]]
        }
    ' | while IFS= read -r line; do
        case "$line" in
        *$'\t'*)
            echo "  ${line%%$'\t'*} — $(drive__skip_heading "${line%%$'\t'*}"):"
            echo "${line#*$'\t'}"
            ;;
        *) echo "$line" ;;
        esac
    done
}

# --- 10 · THE HARNESS A DRIVE CARRIES, ONCE ------------------------------------
#
# THE DEFECT, and it is this file's own argument one level up. Sections 1-9
# exist because "the guard has to be here rather than in six copies that
# drift". The harness every drive then wrote around them — a refusal, an `ok`,
# a `bad`, a summary line, a `--list`, a `--case`, a scratch repository — was
# written once per drive, in as many shapes as there were authors: summary
# lines in half a dozen grammars, `--list` printing every case twice in a
# score of drives, a `--case` arm re-typed per drive for one reader, the
# scratch repository's four git lines re-explained in each. The derived count
# of the copies still standing is `test_drive_preamble.sh`'s harness census.
#
# SO A DRIVE'S PROLOGUE IS ONE LINE AND ITS BODY IS ITS CASES:
#
#     . scripts/tests/drive_preamble.sh || exit 2
#     case_x() { ...; ok "what held"; ...; bad "what did not" "$OUT"; }
#     drive_run_case case_x
#     drive_finished
#
# AND A RUN IS READ BY FIVE, each counting through `ok`/`bad`:
#
#     holds <what> <want> <got>   the two are equal
#     exits <rc>                  the last run's status, `$RC`, is <rc>
#     says <needle>               the last capture, `$DRIVE_OUT`, carries the fixed string
#     says_not <needle>           … and does not
#     says_before <first> <then>  … carries <first> on an earlier line than <then>
#
# A drive that sets `$RUN` has it on every line `exits`/`says`/`says_not` print.
# A capture `says`/`says_not` cannot read is could-not-look (section 7), never a pass.
#
# and the rest is here: `--list` and `--case <name>` are answered before the
# drive's first line runs (so before any pipe guard a drive carries), `ok` and
# `bad` count, the summary is printed by the epilogue in the one grammar
# `<drive>: N passed · M failed · K skipped`, and a counted red is the exit
# status. The worked example is `test_drive_preamble.sh` itself, and
# `test_pipefail_readers.sh` beside it.
#
# A DRIVE NOT YET ON IT IS UNTOUCHED. A drive that still defines its own `ok`
# keeps its own (its definition is read after this one and wins), and prints
# its own summary — the epilogue's is printed only while `ok` is still the one
# defined here. A drive that still carries its own `--list)` arm still parses
# its own arguments: this section reads the arm and stands back, so nothing a
# drive does today changes until the drive is migrated, one file at a time.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * A HELPER UNDER ANOTHER NAME. The harness census in `test_drive_preamble.sh`
#     reads definitions by the names this section ships; a drive's `is`, `same`
#     or `differs` is `holds` under a name it does not know.
#   * A HEREDOC THE READER CANNOT SEE OPEN. The case list skips heredoc bodies
#     so a planted drive's cases are not this drive's; a `<<WORD` written
#     inside a quoted string reads as an opening it is not, and hides the lines
#     after it until a line equal to WORD.
#   * AN ARGUMENT A MIGRATED DRIVE TAKES OF ITS OWN. Anything but `--list` and
#     `--case <name>` (repeatable: the set runs) is refused unless the drive's text carries a `case` arm
#     for that exact token — the drive's parser is then the reader of it.

PASSED=0
# A second sourcing inside a running drive's own shell or subshell (never a new process): the whole-run floor is the outer drive's.
DRIVE__NESTED=0
[ -z "${DRIVE__LOADED:-}" ] || DRIVE__NESTED=1
DRIVE__LOADED=1
FAILED=0
DRIVE_ONLY_CASE=""
DRIVE_ONLY_CASE_RAN=0
DRIVE__SUMMARY_PRINTED=0
DRIVE__LABEL=""
# The drive's own file: the caller of this one, the same derivation as
# DRIVE_NAME at the top. A drive `cd`s to the checkout root before it sources
# this file, so a RELATIVE path it was started by is relative to where it was
# started — which the `cd` left in OLDPWD.
DRIVE__SOURCE="${BASH_SOURCE[1]:-$0}"
case "$DRIVE__SOURCE" in
/*) ;;
*) [ -r "$DRIVE__SOURCE" ] || [ -z "${OLDPWD:-}" ] || DRIVE__SOURCE="${OLDPWD}/${DRIVE__SOURCE}" ;;
esac

# drive__code_lines <file> — every line of the file that is CODE, as
# `<line>\t<text>`: a heredoc's body is the planted file's text, not this
# drive's, so it is dropped (the opening line itself is code and stays).
drive__code_lines() {
    awk '
        doc != "" {
            line = $0
            if (dash) sub(/^\t+/, "", line)
            if (line == doc) doc = ""
            next
        }
        {
            print FNR "\t" $0
            if ($0 ~ /^[[:space:]]*#/) next
            rest = $0
            while (match(rest, /<<-?[[:space:]]*["\047]?[A-Za-z_][A-Za-z0-9_]*["\047]?/)) {
                lead = (RSTART > 1) ? substr(rest, RSTART - 1, 1) : ""
                tok = substr(rest, RSTART, RLENGTH)
                rest = substr(rest, RSTART + RLENGTH)
                if (lead == "<") continue
                dash = (tok ~ /^<<-/)
                sub(/^<<-?[[:space:]]*/, "", tok)
                gsub(/["\047]/, "", tok)
                doc = tok
                break
            }
        }
    ' "$1"
}

# drive_list_cases [<file>] — the drive's cases, one name per line, in the
# order they are defined: a `case_<name>() {` definition at column zero
# outside any heredoc. The definition, never the call, so each case is named
# once; never a heredoc's, so a drive that plants a drive is not its plant.
drive_list_cases() {
    local src="${1:-$DRIVE__SOURCE}"
    [ -r "$src" ] || drive_cannot_look "drive_list_cases: '${src}' is not a readable file — the cases are read from the drive's own text"
    drive__code_lines "$src" | awk -F'\t' '$2 ~ /^case_[A-Za-z0-9_]*\(\) \{/ { sub(/\(\).*/, "", $2); print $2 }'
}

# drive_run_case <name> [args…] — run one case, unless `--case` named a set without it.
# The one seam `--case <name>` needs: a drive calls every case through it, and
# the epilogue refuses a `--case` run that never reached every case it named.
# A case on the harness that returns having recorded no ok, bad or skip is FAILED `nothing asserted`.
# does-not-cover: an assertion made only inside a subshell counts nowhere — the case reds `nothing asserted` (a false red the hint names), never a false green.
# does-not-cover: a case called without drive_run_case, and a drive off the harness (its own `--list` arm or `ok`), are not floored.
DRIVE__CASES_RAN=""
drive_run_case() {
    local name="${1:-}" before rc
    declare -F "$name" >/dev/null ||
        drive_cannot_look "drive_run_case: '${name}' is not a function this drive defines — a case that cannot be called asserts nothing"
    if [ -n "$DRIVE_ONLY_CASE" ]; then
        case $'\n'"${DRIVE_ONLY_CASE}"$'\n' in
        *$'\n'"${name}"$'\n'*) ;;
        *) return 0 ;;
        esac
        DRIVE_ONLY_CASE_RAN=1
        DRIVE__CASES_RAN="${DRIVE__CASES_RAN}${name}"$'\n'
    fi
    before=$((${PASSED:-0} + ${FAILED:-0} + ${DRIVE_SKIPPED:-0}))
    "$@"
    rc=$?
    if [ $((${PASSED:-0} + ${FAILED:-0} + ${DRIVE_SKIPPED:-0})) = "$before" ] && drive__on_the_harness; then
        drive__nothing_asserted "$name"
    fi
    return "$rc"
}

# drive__nothing_asserted <label> — count the FAILED line a run that asserted nothing owes.
drive__nothing_asserted() {
    local CURRENT="$1"
    bad "nothing asserted — it recorded no ok, bad or skip in this shell (an undefined helper — a 'command not found' above — or an assertion made only inside a subshell, whose count dies with it)" ""
}

# The named cases a `--case` run never reached, one per line.
drive__cases_unrun() {
    local name
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        case $'\n'"${DRIVE__CASES_RAN}" in
        *$'\n'"${name}"$'\n'*) ;;
        *) printf '%s\n' "$name" ;;
        esac
    done <<<"$DRIVE_ONLY_CASE"
}

# The case an assertion belongs to, DERIVED: the innermost `case_*` on the
# call stack, so a helper a case calls reports the case; `$CURRENT` only when
# no case is on the stack, then the drive. Set in THIS shell, never through a
# command substitution, so `ok` costs no fork.
drive__label() {
    local i=1
    DRIVE__LABEL=""
    while [ "$i" -lt "${#FUNCNAME[@]}" ]; do
        case "${FUNCNAME[$i]}" in
        case_*)
            DRIVE__LABEL="${FUNCNAME[$i]}"
            return 0
            ;;
        esac
        i=$((i + 1))
    done
    DRIVE__LABEL="${CURRENT:-$DRIVE_NAME}"
}

# ok <what held> — count a pass and say what held.
ok() {
    drive__label
    echo "  ok       ${DRIVE__LABEL} — $1"
    PASSED=$((PASSED + 1))
}

# bad <what did not hold> [<capture>] [<lines>] — count a fail, say what did
# not hold, and show the last <lines> (25 unless given) of the capture that
# shows why. The capture is `$DRIVE_OUT` unless one is given (an explicit ""
# shows none). A capture that is empty or absent is said to be, never
# skipped: a red with nothing under it is the shape a reader cannot act on.
bad() {
    local what="${1:-}" capture="${2-${DRIVE_OUT:-}}" lines="${3:-25}"
    case "$lines" in
    '' | *[!0-9]*) drive_cannot_look "bad: the capture tail '${lines}' is not a count of lines" ;;
    esac
    drive__label
    echo "  FAILED   ${DRIVE__LABEL} — ${what}"
    if [ -n "$capture" ]; then
        if [ -s "$capture" ]; then
            echo "             | (the last ${lines} lines of ${capture})"
            tail -n "$lines" "$capture" | sed 's/^/             | /'
        else
            echo "             | (the capture ${capture} is empty or absent — nothing shows why)"
        fi
    fi
    FAILED=$((FAILED + 1))
}

# holds <what> <want> <got> — ok when <got> equals <want>; bad naming both when not.
holds() {
    if [ "${2-}" = "${3-}" ]; then
        ok "${1:-} — ${3-}"
    else
        bad "${1:-} — wanted '${2-}', got '${3-}'"
    fi
}

# exits <rc> — the last run's status, `$RC`, is <rc>.
exits() {
    [ -n "${RC:-}" ] || drive_cannot_look "exits ${1:-}: no run status in \$RC — a status nobody recorded cannot be asserted"
    if [ "$RC" = "${1:-}" ]; then
        ok "${RUN:+${RUN}: }exit ${RC}"
    else
        bad "${RUN:+${RUN}: }wanted exit ${1:-}, got ${RC}"
    fi
}

# The capture `says`/`says_not` read, proven readable first.
drive__readable_capture() {
    local refusal
    if refusal="$(drive_capture_refusal "${RUN:-$1}" "${DRIVE_OUT:-}" "${RC:-<none>}")"; then
        drive_cannot_look "$refusal"
    fi
}

# says <needle> — the last capture, `$DRIVE_OUT`, carries the fixed string.
says() {
    drive__readable_capture says
    if grep -qF -- "${1:-}" "$DRIVE_OUT"; then
        ok "${RUN:+${RUN}: }says \"${1:-}\""
    else
        bad "${RUN:+${RUN}: }does not say \"${1:-}\""
    fi
}

# says_not <needle> — the last capture, `$DRIVE_OUT`, does not carry the fixed string.
says_not() {
    drive__readable_capture says_not
    if grep -qF -- "${1:-}" "$DRIVE_OUT"; then
        bad "${RUN:+${RUN}: }says \"${1:-}\" and must not"
    else
        ok "${RUN:+${RUN}: }does not say \"${1:-}\""
    fi
}

# says_before <first> <then> — the last capture, `$DRIVE_OUT`, carries <first> on an earlier line than <then>.
# Read by awk over the file, never `grep | …`: an absent needle under pipefail is a bad, not a dead drive.
says_before() {
    local a b
    drive__readable_capture says_before
    a="$(awk -v n="${1:-}" 'index($0, n) { print NR; exit }' "$DRIVE_OUT")"
    b="$(awk -v n="${2:-}" 'index($0, n) { print NR; exit }' "$DRIVE_OUT")"
    if [ -n "$a" ] && [ -n "$b" ] && [ "$a" -lt "$b" ]; then
        ok "${RUN:+${RUN}: }\"${1:-}\" (line ${a}) before \"${2:-}\" (line ${b})"
    else
        bad "${RUN:+${RUN}: }\"${1:-}\" (line ${a:-absent}) is not before \"${2:-}\" (line ${b:-absent})"
    fi
}

# drive_summary — the one summary line, once. The epilogue prints it for a
# drive on this harness; a drive never prints its own.
drive_summary() {
    [ "$DRIVE__SUMMARY_PRINTED" = "1" ] && return 0
    DRIVE__SUMMARY_PRINTED=1
    echo "${DRIVE_NAME}: ${PASSED:-0} passed · ${FAILED:-0} failed · ${DRIVE_SKIPPED:-0} skipped"
}

# Whether the drive asserts through THIS file's `ok` and lets this file parse
# its arguments — the one condition under which the epilogue owns its summary
# and its status. Read off the function itself, so a drive that defines its own
# `ok` keeps its own summary.
drive__on_the_harness() {
    [ "${DRIVE__OWNS_ITS_PARSE:-1}" = "0" ] || return 1
    case "$(declare -f ok 2>/dev/null)" in
    *drive__label*) return 0 ;;
    esac
    return 1
}

# drive_scratch_repo <var> [<author>] — a throwaway repository on `main`, at
# the path the NAMED variable holds, with an author and one empty base commit.
# It wraps section 2's belt, so the path is proven before git is handed it;
# what the repository then carries is the case's business.
drive_scratch_repo() {
    local var="${1:-}" author="${2:-drive}" path
    case "$var" in
    '' | [0-9]* | *[!A-Za-z0-9_]*)
        drive_cannot_look "drive_scratch_repo: '${var}' is not a variable NAME — it takes the name of the variable that holds the path, the way drive_require_scratch does"
        ;;
    esac
    path="${!var-}"
    drive_require_scratch "$var" "$path"
    mkdir -p "$path" || drive_cannot_look "drive_scratch_repo: could not make ${path}"
    {
        git -C "$path" init -q &&
            git -C "$path" symbolic-ref HEAD refs/heads/main &&
            git -C "$path" config user.email "${author}@example.invalid" &&
            git -C "$path" config user.name "$author" &&
            git -C "$path" config commit.gpgsign false &&
            git -C "$path" commit -q --allow-empty -m "base"
    } || drive_cannot_look "drive_scratch_repo: git could not build the scratch repository at ${path}"
}

# drive_checkout_mirror <var> [<checkout>] — a repository at the path the NAMED variable holds that
# borrows <checkout>'s objects (this one by default) and carries its refs, its HEAD, its working tree,
# a copy of its `.env` and a link to its `.venv`; a plant there never reaches the real `apps/`.
# does-not-cover: an ignored file other than `.env`/`.venv` (a drawer's local state) is not carried.
drive_checkout_mirror() {
    local var="${1:-}" src="${2:-$DRIVE__ROOT}" path head branch objects
    case "$var" in
    '' | [0-9]* | *[!A-Za-z0-9_]*)
        drive_cannot_look "drive_checkout_mirror: '${var}' is not a variable NAME — it takes the name of the variable that holds the path"
        ;;
    esac
    path="${!var-}"
    drive_require_scratch "$var" "$path"
    [ ! -e "$path" ] || drive_cannot_look "drive_checkout_mirror: ${path} already exists — a mirror is built fresh, never over something"
    head="$(git -C "$src" rev-parse --verify -q HEAD)" ||
        drive_cannot_look "drive_checkout_mirror: ${src} has no HEAD to mirror"
    branch="$(git -C "$src" symbolic-ref -q --short HEAD || true)"
    objects="$(cd "$src" && cd "$(git rev-parse --git-common-dir)" && pwd -P)/objects" ||
        drive_cannot_look "drive_checkout_mirror: ${src} has no object store to borrow"
    git init -q "$path" >/dev/null 2>&1 && printf '%s\n' "$objects" >"${path}/.git/objects/info/alternates" ||
        drive_cannot_look "drive_checkout_mirror: could not make a repository at ${path}"
    git -C "$path" fetch -q --update-head-ok --no-tags "$src" '+refs/heads/*:refs/heads/*' \
        '+refs/remotes/*:refs/remotes/*' '+refs/tags/*:refs/tags/*' '+refs/djb/*:refs/djb/*' >/dev/null 2>&1 ||
        drive_cannot_look "drive_checkout_mirror: could not carry ${src}'s refs into ${path}"
    if [ -n "$branch" ]; then
        git -C "$path" checkout -q -f -B "$branch" "$head" >/dev/null 2>&1
    else
        git -C "$path" checkout -q -f --detach "$head" >/dev/null 2>&1
    fi || drive_cannot_look "drive_checkout_mirror: could not check out ${head} in ${path}"
    git -C "$path" config user.email drive@example.invalid
    git -C "$path" config user.name "$DRIVE_NAME"
    git -C "$path" config commit.gpgsign false
    (cd "$src" && git diff -z --name-only --diff-filter=D HEAD) | (cd "$path" && xargs -0 rm -f --) ||
        drive_cannot_look "drive_checkout_mirror: could not carry ${src}'s deletions into ${path}"
    { (cd "$src" && git diff -z --name-only --diff-filter=d HEAD && git ls-files -z --others --exclude-standard) |
        (cd "$src" && tar -cf - --null -T -) | (cd "$path" && tar -xf -); } ||
        drive_cannot_look "drive_checkout_mirror: could not carry ${src}'s working tree into ${path}"
    [ ! -f "${src}/.env" ] || cp "${src}/.env" "${path}/.env" ||
        drive_cannot_look "drive_checkout_mirror: could not copy ${src}/.env"
    [ ! -e "${src}/.venv" ] || ln -s "${src}/.venv" "${path}/.venv" ||
        drive_cannot_look "drive_checkout_mirror: could not link ${src}/.venv"
}

# Whether the drive's own text carries a `case` arm for exactly this token —
# a drive that still parses its own arguments (`--list`), or a migrated drive
# that takes a flag of its own.
drive__has_arm() {
    local token="$1" src="$DRIVE__SOURCE" line
    [ -r "$src" ] || return 1
    while IFS= read -r line; do
        line="${line#*$'\t'}"
        line="${line#"${line%%[![:space:]]*}"}"
        case "$line" in
        "${token})"* | "${token} |"* | "${token}|"* | "\"${token}\")"* | "'${token}')"*) return 0 ;;
        esac
    done < <(drive__code_lines "$src")
    return 1
}

# THE ARGUMENTS, read before the drive's first line. A drive with its own
# `--list)` arm parses for itself (section 5a's read above is all this file
# does for it); every other drive is answered here, and the two answers are
# consumed so the drive's `$@` holds only what is left.
#
# THE SAME READ SAYS WHETHER THE DRIVE IS ON THIS HARNESS. Dropping its own
# `--list)` arm is the step that migrates a drive, so a drive that still
# carries one keeps its own summary and its own status even when it defines no
# `ok` of its own (it asserts through `holds` or `says`, and counts itself).
DRIVE__OWNS_ITS_PARSE=0
drive__has_arm --list && DRIVE__OWNS_ITS_PARSE=1
if [ "$DRIVE__OWNS_ITS_PARSE" = "0" ]; then
    case "${1:-}" in
    "") ;;
    --list)
        drive__cases="$(drive_list_cases)"
        [ -n "$drive__cases" ] ||
            drive_cannot_look "this drive defines no \`case_\` function — nothing to list"
        printf '%s\n' "$drive__cases"
        exit 0
        ;;
    --case)
        # Repeatable: each `--case <name>` adds one case to the set this run runs.
        drive__cases="$(drive_list_cases)"
        while [ "${1:-}" = "--case" ]; do
            drive__only="${2:-}"
            case $'\n'"${drive__cases}"$'\n' in
            *$'\n'"${drive__only:-"(none)"}"$'\n'*) ;;
            *) drive_cannot_look "--case '${drive__only}' names no case this drive defines — \`bash ${DRIVE__SOURCE} --list\` names them" ;;
            esac
            case $'\n'"${DRIVE_ONLY_CASE}"$'\n' in
            *$'\n'"${drive__only}"$'\n'*) ;;
            *) DRIVE_ONLY_CASE="${DRIVE_ONLY_CASE}${DRIVE_ONLY_CASE:+$'\n'}${drive__only}" ;;
            esac
            shift 2
        done
        unset drive__only drive__cases
        ;;
    *)
        drive__has_arm "$1" ||
            drive_cannot_look "unknown argument '$1': ${DRIVE_NAME} takes nothing, --list or --case <name> — a mistyped flag is never a silently different run"
        ;;
    esac
fi
