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
# The drive for `scripts/rung_start.sh` — the rung-start instrument, which is
# made almost entirely of REFUSALS and one reset.
#
#   ./scripts/tests/test_rung_start.sh          run every case
#   ./scripts/tests/test_rung_start.sh --list   name them and stop
#
# WHY IT EXISTS. `rung_start.sh` begins by running `git reset --hard main` in
# the worktree it is invoked from. That is the most destructive single line in
# `scripts/`, and the only things standing between it and a builder's work are
# two guards nobody sees when they are working: the dirty-tree refusal and the
# commits-ahead refusal. A guard that is invisible when it is right is a guard
# that can be deleted by accident and stay deleted — the state `backup.sh` and
# `sweep.sh` were each in before their own drives existed. Every refusal here is driven, and
# every destructive case asserts that THE WORK IS STILL THERE afterwards rather
# than merely that the exit status was 2.
#
# IT BUILDS ITS OWN REPOSITORIES, and it plants nothing in this tree. A scratch
# repository under `mktemp -d` with a `main`, a branch and a commit or two is a
# checkout as far as step 1 is concerned, and step 1 is what these cases are
# about.
#
# THE POOL CASE IS THE FINDING, REPRODUCED. `case_the_pool_mechanism` builds the
# exact shape once diagnosed — a `refs/remotes/origin/main` left behind local
# `main`, and a branch created from it — and requires the instrument to name it.
# That case failing means the diagnosis in `rung_start.sh`'s header no longer
# matches what the script detects.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. STEPS 2 THROUGH 5. A scratch repository has no `pyproject.toml`, no venv,
#      no `db.sh` and no Postgres, so every case that gets PAST step 1 dies in
#      step 2. Those cases assert step 1's printed lines and the resulting HEAD,
#      and DELIBERATELY DO NOT ASSERT THE RUN'S EXIT STATUS, because that status
#      belongs to a later step. `case_a_dirty_tree_*` and the other refusals do
#      assert the status, because they exit before step 2 exists. Where a case
#      asserts a status, it says so; where it cannot, it says that too.
#   2. THE HAPPY PATH END TO END. Nothing here proves `uv sync`, `db_create`,
#      `migrate` or the introspect dump. That is a real worktree with a real
#      compose stack behind it, and the rung report records the measured run.
#   3. A COPY IS WHAT RUNS, in every case but the first two. `rung_start.sh`
#      derives its root from its own location (`dirname "$0"/..`), so driving it
#      against a scratch repository means copying it in. The copy is made with
#      `cp` from this tree's file at the start of every case, so it cannot drift
#      within a run — but it is a copy, and a reader should know it. The two
#      cases that need no root (the pipe refusal and the unknown-argument
#      refusal) run THIS TREE'S OWN FILE.
#   4. WHETHER THE RESET IS THE RIGHT THING TO DO. The instrument makes the
#      baseline current; whether main's tip is the tree a brief was written
#      against is a builder's flag-and-hold and nothing here has an opinion.
#   5. STEP 4'S BUCKET, EXCEPT AS WIRING. `case_the_storage_step_is_wired_and_
#      is_not_fatal` reads the script as TEXT — the step exists, it calls
#      `manage.py ensure_bucket` rather than deriving a name itself, it writes
#      the name back, its failure reaches the FOOTER rather than the exit
#      status, and the three step banners are in dependency order. It does not
#      make a bucket, because a scratch repository has no venv, no database and
#      no MinIO (blind spot 1). That is a weaker proof than running it and it is
#      named as one; the live half is a real worktree's `storage_audit` and the
#      integrations census, recorded in the rung report.
#   6. THE IDENTITY CARRY'S PLACE IN THE RUN. The carry lives in step 3, which
#      blind spot 1 says nothing here can reach, so the `case_the_identity_
#      carry_*` cases SOURCE `rung_start.sh` and call `zitadel_carry` against
#      fixture `.env` files instead. That is the seam the script's own header
#      documents (THE SOURCED SEAM), and what it does NOT prove is that step 3
#      still calls the function — `case_the_identity_carry_is_wired_into_step_
#      three` reads that as text, the same weaker proof step 4 gets, for the
#      same reason. The live half is the builder's report: a real worktree, a
#      real primary checkout, and the announced key names in its output.
#   7. WHETHER A CARRIED CREDENTIAL WORKS. Every value in these fixtures is a
#      canary string invented here. Nothing reaches a Zitadel, and nothing here
#      has an opinion about an expired PAT — `manage.py zitadel_audit` is the
#      instrument for that (house rule 27), and it is a rung's to run.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_rung_start: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble, opted into. On bash 3.2 a `set -u` death
# hands the EXIT trap a status of 0, so a drive that dies halfway reads as a
# PASS to check.sh — which is exactly how a drive that ran none of its cases
# reports success. Every case below is worthless without this.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_rung_start: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_rung_start.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -x scripts/rung_start.sh ] ||
    cannot_look "scripts/rung_start.sh is not an executable file in this tree — there is nothing to drive"

ROOT="$PWD"
REAL="${ROOT}/scripts/rung_start.sh"

# The step count, ASKED rather than typed. Step banners are `step N/TOTAL`, and
# a case that spells the total by hand goes vacuous the day a step is added
# (which is exactly what happened once to `says_not "step 1/4"`).
STEP_TOTAL_IN_SCRIPT="$(sed -n 's/^STEP_TOTAL=\([0-9][0-9]*\).*/\1/p' "$REAL" | head -1)"
[ -n "$STEP_TOTAL_IN_SCRIPT" ] ||
    cannot_look "scripts/rung_start.sh declares no STEP_TOTAL — the step banners cannot be read"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-rung-start-drive.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

CURRENT=""
RC=0
OUT=""
N=0
REPO=""

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then
        sed 's/^/             | /' "$OUT" | tail -30
    fi
    FAILED=$((FAILED + 1))
}

exits() {
    if [ "$RC" -eq "$1" ]; then
        ok "exit ${RC}"
    else
        bad "wanted exit $1, got ${RC}"
    fi
}

says() {
    if grep -qF -- "$1" "$OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}

says_not() {
    if grep -qF -- "$1" "$OUT"; then
        bad "says \"$1\" and must not"
    else
        ok "does not say \"$1\""
    fi
}

# --- the scratch repository ---------------------------------------------------
#
# A `main` with two commits, and a copy of the real script under `scripts/`.
# `git -C` is never trusted on its own here; the preamble has already unset the
# inherited location variables and `drive_require_scratch` guards the
# path before anything is written to it.
fresh_repo() {
    N=$((N + 1))
    REPO="${WORK}/repo${N}"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "${REPO}/scripts"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "rung start drive"
    # The real file, copied in — see blind spot 3.
    cp "$REAL" "${REPO}/scripts/rung_start.sh"
    chmod +x "${REPO}/scripts/rung_start.sh"
    echo "one" >"${REPO}/tracked.txt"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "base"
    echo "two" >>"${REPO}/tracked.txt"
    git -C "$REPO" add tracked.txt
    git -C "$REPO" commit -q -m "second commit on main"
}

# Run the copy, from inside the scratch repository, capturing both streams.
run_in_repo() {
    CURRENT="$1"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$REPO" && ./scripts/rung_start.sh) >"$OUT" 2>&1 || RC=$?
}

# The same, with flags. Separate rather than variadic-everywhere so that every
# existing case above stays a call with no arguments at all — a flag arriving by
# accident in a case about the no-flag run is the class this whole drive is for.
run_in_repo_with() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$REPO" && ./scripts/rung_start.sh "$@") >"$OUT" 2>&1 || RC=$?
}

head_of() { git -C "$REPO" rev-parse HEAD; }
main_of() { git -C "$REPO" rev-parse main; }

# --- the identity carry, driven through the sourced seam ----------------------
#
# `zitadel_carry` is in step 3 and blind spot 1 says nothing here reaches step
# 3, so the function is called directly: `rung_start.sh` returns early when it
# is SOURCED rather than executed (THE SOURCED SEAM in its header), so sourcing
# it defines the function and runs no step. `set --` first, because a sourced
# file with no arguments of its own inherits the CALLER'S positional parameters
# in bash — and this script's own `$1` would then walk into rung_start's
# argument parser and be refused.
carry_in_fixture() {
    CURRENT="$1"
    local primary="$2" target="$3"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        set --
        # shellcheck source=scripts/rung_start.sh
        . "$REAL"
        zitadel_carry "$primary" "$target"
    ) >"$OUT" 2>&1 || RC=$?
}

file_has() {
    if grep -qF -- "$2" "$1"; then
        ok "$(basename "$1") carries \"$2\""
    else
        bad "$(basename "$1") does not carry \"$2\""
        sed 's/^/             > /' "$1" >&2
    fi
}

file_lacks() {
    if grep -qF -- "$2" "$1"; then
        bad "$(basename "$1") carries \"$2\" and must not"
        sed 's/^/             > /' "$1" >&2
    else
        ok "$(basename "$1") does not carry \"$2\""
    fi
}

# The canary values. Invented here, never a real credential, and distinctive
# enough that finding one in the instrument's output is unambiguous — which is
# the whole point: criterion 3 is announce the KEY NAME, and a value in this
# script's output is a value in every rung log that ever pastes one.
CANARY_PAT="CARRY-CANARY-A-VALUE-THAT-MUST-NEVER-BE-PRINTED"          # pragma: allowlist secret
CANARY_AUD="CARRY-CANARY-A-SECOND-VALUE-THAT-MUST-NEVER-BE-PRINTED"   # pragma: allowlist secret
CANARY_OTHER="CARRY-CANARY-NOT-ZITADEL-AND-MUST-NOT-TRAVEL"           # pragma: allowlist secret

# A primary checkout's `.env`, as one looks after `zitadel_seed`: some ZITADEL_*
# keys populated, one blank, and two decoys that are NOT in the population — a
# plain non-identity key, and one whose name CONTAINS the prefix without
# starting with it.
write_primary_env() {
    cat >"$1" <<PRIMARY
# A comment line that happens to spell ZITADEL_PAT= and carries no value.
DATABASE_NAME=djb_primary_checkout
ZITADEL_ISSUER=http://localhost:8081
ZITADEL_PAT=${CANARY_PAT}
ZITADEL_MCP_AUDIENCE=${CANARY_AUD}
ZITADEL_ORG_NAME=
SECRET_KEY=${CANARY_OTHER}
NOT_ZITADEL_PAT=${CANARY_OTHER}
PRIMARY
}

# A fresh worktree's `.env`, as `cp .env.example` leaves it: the identity keys
# present and BLANK, which is the gap this carry closes.
write_fresh_env() {
    cat >"$1" <<FRESH
DATABASE_NAME=djb_fresh_worktree
ZITADEL_ISSUER=http://localhost:8081
ZITADEL_PAT=
ZITADEL_MCP_AUDIENCE=
SECRET_KEY=
FRESH
}

# =============================================================================

# Runs THIS TREE'S OWN FILE: the pipe refusal fires before the script derives a
# root, so it needs no scratch repository at all.
case_a_piped_stdout_is_refused() {
    CURRENT="a piped stdout is refused"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    # The pipe is the point. `cat` is the filter whose exit status would
    # otherwise become the verdict, and PIPESTATUS is how this driver
    # reads the status the pipe would have swallowed.
    set +e
    "$REAL" 2>&1 | cat >"$OUT"
    RC=${PIPESTATUS[0]}
    set -e
    exits 2
    says "refuses pipes"
    says "The exit status is the verdict"
}

case_an_unknown_argument_is_refused() {
    CURRENT="an unknown argument is refused"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    set +e
    "$REAL" --force >"$OUT" 2>&1
    RC=$?
    set -e
    exits 2
    says "takes no arguments"
    # The step banner, spelled with the CURRENT total. `says_not "step 1/4"`
    # went quietly vacuous the moment a step was added and the total became 5
    # — an absence
    # assertion whose subject cannot exist is an assertion that passes for the
    # wrong reason, so the total is read out of the script rather than typed.
    says_not "step 1/${STEP_TOTAL_IN_SCRIPT}"
}

case_a_dirty_tree_is_refused_and_nothing_is_lost() {
    fresh_repo
    git -C "$REPO" checkout -q -b work main~1
    # THE VICTIM IS THIS CASE'S OWN: a modification and an untracked
    # file it made itself, never found state.
    echo "work in progress a builder has not committed" >>"${REPO}/tracked.txt"
    echo "a new file nobody has added yet" >"${REPO}/untracked.txt"
    local before_tracked before_head
    before_tracked="$(cat "${REPO}/tracked.txt")"
    before_head="$(head_of)"

    run_in_repo "a dirty tree is refused, and nothing is lost"
    exits 2
    says "uncommitted work"
    says "REFUSING to reset"
    says "Nothing was reset, installed, created or written."
    says "tracked.txt"
    says "untracked.txt"

    if [ "$(cat "${REPO}/tracked.txt")" = "$before_tracked" ]; then
        ok "the uncommitted modification is still there, byte for byte"
    else
        bad "the uncommitted modification was destroyed — the whole guard"
    fi
    if [ -f "${REPO}/untracked.txt" ]; then
        ok "the untracked file is still there"
    else
        bad "the untracked file was destroyed"
    fi
    if [ "$(head_of)" = "$before_head" ]; then
        ok "HEAD did not move"
    else
        bad "HEAD moved despite the refusal"
    fi
}

case_a_branch_ahead_of_main_is_refused_and_the_commits_survive() {
    fresh_repo
    git -C "$REPO" checkout -q -b work main~1
    echo "a finished leg, committed the way rung-execution §5 says to" >"${REPO}/leg.txt"
    git -C "$REPO" add leg.txt
    git -C "$REPO" commit -q -m "rung work main does not have"
    local before_head
    before_head="$(head_of)"

    # Clean tree, ahead of main. A dirty-tree guard alone would wave this
    # through and reset --hard would discard the commit.
    run_in_repo "a branch ahead of main is refused, and the commits survive"
    exits 2
    says "commit(s) main does not have"
    says "REFUSING to reset"
    says "rung work main does not have"
    says "Nothing was reset, installed, created or written."

    if [ "$(head_of)" = "$before_head" ]; then
        ok "HEAD did not move — the commit is still reachable"
    else
        bad "HEAD moved: committed rung work was discarded"
    fi
    if [ -f "${REPO}/leg.txt" ]; then
        ok "the committed file is still in the tree"
    else
        bad "the committed file is gone"
    fi
    # The refusal names the door. Before `--resume` existed this message ended
    # at "keep building", which is true about the BASELINE and silent about the
    # environment — and the environment is what a builder in this state has
    # usually lost.
    says "./scripts/rung_start.sh --resume"
}

# =============================================================================
# --RESUME. The refusal above is correct and re-establishes nothing; this is the
# door next to it. Every case here asserts that HEAD DID NOT MOVE, because a
# flag whose entire contract is "no reset" is worth exactly that assertion.
# =============================================================================

# Gets past step 1 — which is the point — and dies in step 2, so the exit status
# is NOT asserted (blind spot 1). That it REACHED step 2 is asserted instead,
# and that is the difference between this and the refusal above.
case_resume_keeps_a_branch_ahead_of_main_and_says_what_it_skipped() {
    fresh_repo
    git -C "$REPO" checkout -q -b work main~1
    echo "a finished leg, committed the way rung-execution §5 says to" >"${REPO}/leg.txt"
    git -C "$REPO" add leg.txt
    git -C "$REPO" commit -q -m "rung work main does not have"
    local before_head
    before_head="$(head_of)"

    run_in_repo_with "--resume keeps a branch ahead of main, and says what it skipped" --resume
    says "** RESUME **"
    says "the reset in step 1 was SKIPPED"
    says "skipped    git reset --hard main"
    says "kept       1 commit(s) main does not have"
    says "rung work main does not have"
    # Not a refusal. This is the whole difference.
    says_not "REFUSING to reset"
    # It went ON, into the environment steps this flag exists to re-run.
    says "step 2/${STEP_TOTAL_IN_SCRIPT}"

    # This branch is ahead by one AND behind by one, so the un-repaired stale
    # baseline is announced — LOUDER than the normal path's banner, not
    # quieter, because here it is a thing that was NOT fixed.
    says "** STALE BASELINE NOT REPAIRED **"
    says_not "** STALE BASELINE **"

    if [ "$(head_of)" = "$before_head" ]; then
        ok "HEAD did not move — the flag's entire contract"
    else
        bad "HEAD moved from ${before_head} to $(head_of): --resume reset something"
    fi
    if [ -f "${REPO}/leg.txt" ]; then
        ok "the committed file is still in the tree"
    else
        bad "the committed file is gone"
    fi
}

case_resume_on_a_current_baseline_says_there_was_nothing_to_skip() {
    fresh_repo
    git -C "$REPO" checkout -q -b work main
    local before_head
    before_head="$(head_of)"

    run_in_repo_with "--resume on a current baseline says there was nothing to skip" --resume
    says "** RESUME **"
    says "kept       0 commits main does not have"
    says "baseline   already current — nothing to skip past"
    says_not "STALE BASELINE"
    says_not "REFUSING to reset"

    if [ "$(head_of)" = "$before_head" ]; then
        ok "HEAD did not move"
    else
        bad "HEAD moved despite --resume"
    fi
}

# CRITERION 2's second half, and the counter-intuitive one: with no reset there
# is nothing for step 1 to destroy, and the refusal stands anyway — steps 3-5
# rewrite `.env` and overwrite `.rung/introspect.json`, and a hand-edited `.env`
# is the commonest uncommitted file a builder reaching for a resume has.
case_resume_on_a_dirty_tree_still_refuses() {
    fresh_repo
    git -C "$REPO" checkout -q -b work main
    echo "work in progress a builder has not committed" >>"${REPO}/tracked.txt"
    echo "a new file nobody has added yet" >"${REPO}/untracked.txt"
    local before_tracked before_head
    before_tracked="$(cat "${REPO}/tracked.txt")"
    before_head="$(head_of)"

    run_in_repo_with "--resume on a dirty tree still refuses" --resume
    exits 2
    says "uncommitted work"
    says "REFUSING to reset"
    says "--resume DOES NOT LIFT THIS"
    says "Nothing was reset, installed, created or written."
    # And it stopped BEFORE the steps that write. An exit 2 that had already
    # rewritten .env would be the refusal telling a lie in its last line.
    says_not "step 2/${STEP_TOTAL_IN_SCRIPT}"

    if [ "$(cat "${REPO}/tracked.txt")" = "$before_tracked" ]; then
        ok "the uncommitted modification is still there, byte for byte"
    else
        bad "the uncommitted modification was destroyed"
    fi
    if [ -f "${REPO}/untracked.txt" ]; then
        ok "the untracked file is still there"
    else
        bad "the untracked file was destroyed"
    fi
    if [ "$(head_of)" = "$before_head" ]; then
        ok "HEAD did not move"
    else
        bad "HEAD moved despite the refusal"
    fi
}

# `--resume` turns off the RESET, not the reporting. Both of these refusals are
# about being able to say what this checkout's baseline IS.
case_resume_does_not_lift_the_reporting_refusals() {
    fresh_repo
    git -C "$REPO" checkout -q --detach main
    run_in_repo_with "--resume does not lift the detached-HEAD refusal" --resume
    exits 2
    says "detached HEAD"
    says "Nothing was reset, installed, created or written."

    fresh_repo
    git -C "$REPO" checkout -q -b work main
    git -C "$REPO" branch -q -D main
    run_in_repo_with "--resume does not lift the missing-main refusal" --resume
    exits 2
    says "no local branch 'main'"
    says "Nothing was reset, installed, created or written."
}

# Runs THIS TREE'S OWN FILE: --help needs no root.
case_the_help_documents_resume() {
    CURRENT="--help documents --resume"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    set +e
    "$REAL" --help >"$OUT" 2>&1
    RC=$?
    set -e
    exits 0
    says "--resume"
    says "RESET REMOVED"
    says "It lifts NO refusal"
}

# Gets past step 1 and dies in step 2 (no venv in a scratch repository), so the
# exit status is NOT asserted — blind spot 1.
case_a_stale_baseline_is_reset_and_said() {
    fresh_repo
    git -C "$REPO" checkout -q -b work main~1
    local before_head
    before_head="$(head_of)"

    run_in_repo "a stale baseline is reset, and SAID"
    says "** STALE BASELINE **"
    says "1 commits behind main"
    says "RESET 1 commits"

    if [ "$(head_of)" = "$(main_of)" ]; then
        ok "HEAD is main's tip after the run"
    else
        bad "HEAD is $(head_of), main is $(main_of) — the reset did not happen"
    fi
    if [ "$(head_of)" != "$before_head" ]; then
        ok "HEAD actually moved (${before_head} -> $(head_of))"
    else
        bad "HEAD did not move"
    fi
}

case_a_current_baseline_says_the_reset_was_a_no_op() {
    fresh_repo
    git -C "$REPO" checkout -q -b work main

    run_in_repo "a current baseline is a no-op, and says so"
    says "already current"
    # The stale banner is a claim about this worktree. Printing it on a current
    # tree would make the one signal that matters unreadable.
    says_not "** STALE BASELINE **"
}

# THE POOL, REPRODUCED. This is the original finding as an assertion: a
# remote-tracking ref left behind local main, a branch created from it, and an
# instrument that names both.
case_the_pool_mechanism_is_diagnosed_by_name() {
    fresh_repo
    # `origin/main` frozen one commit back — a remote-tracking ref moves only on
    # a push or a fetch, and this loop merges into LOCAL main continuously.
    git -C "$REPO" update-ref refs/remotes/origin/main "$(git -C "$REPO" rev-parse main~1)"
    # The harness's own move, in git's own words: creating the branch this way
    # is what writes "branch: Created from origin/main" into its reflog.
    git -C "$REPO" checkout -q -b work origin/main

    run_in_repo "the pool mechanism is diagnosed by name"
    says "THE POOL (why this keeps happening)"
    says "origin/main is 1 commits behind local main"
    says "This branch was created from: origin/main"
    says "scripts/pm_push.sh"
    # And the belt still ran.
    says "** STALE BASELINE **"
    if [ "$(head_of)" = "$(main_of)" ]; then
        ok "the worktree was repaired as well as diagnosed"
    else
        bad "diagnosed and not repaired"
    fi
}

case_a_current_origin_main_prints_no_pool_block() {
    fresh_repo
    git -C "$REPO" update-ref refs/remotes/origin/main "$(git -C "$REPO" rev-parse main)"
    git -C "$REPO" checkout -q -b work main

    run_in_repo "a current origin/main prints no pool block"
    # An alarm that is normally true is one people learn to skip
    # (scripts/sweep.sh's roll-up made the same choice).
    says_not "THE POOL (why this keeps happening)"
}

case_a_detached_head_is_refused() {
    fresh_repo
    git -C "$REPO" checkout -q --detach main

    run_in_repo "a detached HEAD is refused"
    exits 2
    says "detached HEAD"
    says "Nothing was reset, installed, created or written."
}

case_no_local_main_is_refused() {
    fresh_repo
    git -C "$REPO" checkout -q -b work main
    git -C "$REPO" branch -q -D main

    run_in_repo "no local main is refused"
    exits 2
    says "no local branch 'main'"
    says "Nothing was reset, installed, created or written."
}

# =============================================================================

case_the_storage_step_is_wired_and_is_not_fatal() {
    # READ AS TEXT, and named as the weaker proof it is (blind spot 5). Step 4
    # needs a venv, a database and a MinIO, none of which a scratch repository
    # has — so what is asserted here is the WIRING: that the step exists, that
    # it sits between the database and the introspect dump, that it writes the
    # name back, and that its failure is a named absence in the footer rather
    # than a refusal. The live half is a real worktree's `storage_audit`, which
    # the rung report records.
    CURRENT="the storage step is wired, and is not fatal"
    OUT=""
    local db_line bucket_line introspect_line
    if [ "$STEP_TOTAL_IN_SCRIPT" = "5" ]; then
        ok "STEP_TOTAL is 5"
    else
        bad "STEP_TOTAL is ${STEP_TOTAL_IN_SCRIPT}, and the storage step makes it 5"
    fi
    if grep -q 'manage.py ensure_bucket' "$REAL"; then
        ok "it runs manage.py ensure_bucket — setup.sh's own door, not a second derivation"
    else
        bad "no manage.py ensure_bucket — the bucket is not made"
    fi
    # CODE ONLY, comments stripped first. This guard's first run went red on
    # the script's own BLIND-SPOT NOTE, which cites the seam by name while
    # explaining why the seam is not copied here — a guard a comment can trip
    # is a guard that teaches people to stop writing comments, and it is a
    # known class (prose spelling a censused marker counts as a registration).
    # What is being detected is a second DERIVATION, and a derivation is code.
    if sed 's/#.*//' "$REAL" | grep -qE 'shasum|sha256sum|derived_bucket_name'; then
        bad "it has grown its own bucket-name arithmetic — that is the second copy setup.sh:446 exists to avoid"
    else
        ok "it names no bucket itself; ensure_bucket's stdout is the name"
    fi
    if grep -q 'AWS_STORAGE_BUCKET_NAME=' "$REAL"; then
        ok "it writes AWS_STORAGE_BUCKET_NAME back into .env"
    else
        bad "the derived name is never written back — a bare manage.py would still have no bucket"
    fi
    if grep -q 'object storage ABSENT' "$REAL"; then
        ok "a bucket that could not be made reaches the FOOTER, not the exit status"
    else
        bad "nothing says 'object storage ABSENT' — a failed bucket would be invisible in the verdict line"
    fi
    # ORDER. The bucket needs the venv and the .env the database step writes,
    # and the introspect dump is the last thing a builder reads.
    db_line="$(grep -n '^# STEP 3 · DATABASE' "$REAL" | cut -d: -f1)"
    bucket_line="$(grep -n '^# STEP 4 · STORAGE' "$REAL" | cut -d: -f1)"
    introspect_line="$(grep -n '^# STEP 5 · INTROSPECT' "$REAL" | cut -d: -f1)"
    if [ -n "$db_line" ] && [ -n "$bucket_line" ] && [ -n "$introspect_line" ] &&
        [ "$db_line" -lt "$bucket_line" ] && [ "$bucket_line" -lt "$introspect_line" ]; then
        ok "the steps run database (${db_line}) -> storage (${bucket_line}) -> introspect (${introspect_line})"
    else
        bad "the three step banners are not in the order the steps depend on: db='${db_line}' storage='${bucket_line}' introspect='${introspect_line}'"
    fi
}

# =============================================================================
# THE IDENTITY CARRY. Driven through the sourced seam (blind spot 6) because it
# lives in step 3 and nothing here reaches step 3.
# =============================================================================

case_the_identity_carry_copies_zitadel_keys_and_prints_no_value() {
    N=$((N + 1))
    local dir="${WORK}/carry${N}"
    mkdir -p "$dir"
    write_primary_env "${dir}/primary.env"
    write_fresh_env "${dir}/fresh.env"

    carry_in_fixture "the identity carry copies ZITADEL_* and prints NO value" \
        "${dir}/primary.env" "${dir}/fresh.env"
    exits 0

    # ANNOUNCED, one line per KEY NAME.
    says "ZITADEL_* carried from the primary checkout"
    says "KEY NAMES only"
    says "ZITADEL_PAT"
    says "ZITADEL_MCP_AUDIENCE"
    says "ZITADEL_ISSUER"

    # THE TOOTH. Not "it printed the names" — "it printed NO value". A
    # credential in this instrument's output is a credential in every rung log,
    # which is worse than the unrecorded hand copy the carry replaces.
    says_not "$CANARY_PAT"
    says_not "$CANARY_AUD"

    # And the value actually arrived, in the file, where it belongs.
    file_has "${dir}/fresh.env" "ZITADEL_PAT=${CANARY_PAT}"
    file_has "${dir}/fresh.env" "ZITADEL_MCP_AUDIENCE=${CANARY_AUD}"
    # Substitution, not accumulation: a second `ZITADEL_PAT=` line would leave
    # the blank one below the real one and whichever reader wins decides.
    if [ "$(grep -c '^ZITADEL_PAT=' "${dir}/fresh.env")" = "1" ]; then
        ok "exactly one ZITADEL_PAT line — the blank was replaced, not joined"
    else
        bad "there are $(grep -c '^ZITADEL_PAT=' "${dir}/fresh.env") ZITADEL_PAT lines"
    fi
    # Everything it was not asked to touch.
    file_has "${dir}/fresh.env" "DATABASE_NAME=djb_fresh_worktree"
}

# CRITERION 4: the population is the prefix, matched on the KEY, and nothing
# else travels. A carry that grows a second category grows it into every
# worktree on the machine at once and nobody sees it happen.
case_the_identity_carry_population_is_the_zitadel_prefix_only() {
    N=$((N + 1))
    local dir="${WORK}/carry${N}"
    mkdir -p "$dir"
    write_primary_env "${dir}/primary.env"
    write_fresh_env "${dir}/fresh.env"

    carry_in_fixture "the identity carry population is the ZITADEL_ prefix only" \
        "${dir}/primary.env" "${dir}/fresh.env"
    exits 0

    # A plain non-identity secret in the same primary .env.
    file_lacks "${dir}/fresh.env" "$CANARY_OTHER"
    says_not "SECRET_KEY"
    # A key whose name CONTAINS the prefix without starting with it.
    file_lacks "${dir}/fresh.env" "NOT_ZITADEL_PAT"
    says_not "NOT_ZITADEL_PAT"
    # A ZITADEL_* key the primary has but leaves BLANK is not a credential, so
    # it is neither carried nor appended — the fresh .env does not have the key
    # at all and must not grow one.
    file_lacks "${dir}/fresh.env" "ZITADEL_ORG_NAME"
    says_not "ZITADEL_ORG_NAME"
    # The blank the fresh .env DID have and the primary did not populate.
    file_has "${dir}/fresh.env" "SECRET_KEY="
}

# THE EMPTY-PRIMARY NEGATIVE CASE (criterion 4). An unseeded machine is the
# ordinary case, not a failure — and the announcement is still the deliverable.
case_the_identity_carry_on_an_empty_primary_carries_nothing() {
    N=$((N + 1))
    local dir="${WORK}/carry${N}"
    mkdir -p "$dir"
    cat >"${dir}/primary.env" <<'EMPTY'
DATABASE_NAME=djb_primary_checkout
ZITADEL_PAT=
ZITADEL_MCP_AUDIENCE=
ZITADEL_ORG_NAME=
EMPTY
    write_fresh_env "${dir}/fresh.env"
    cp "${dir}/fresh.env" "${dir}/fresh.env.before"

    carry_in_fixture "the identity carry on an empty primary carries nothing, and says so" \
        "${dir}/primary.env" "${dir}/fresh.env"
    exits 0
    says "carries no populated ZITADEL_* value"
    says "zitadel_seed"
    says_not "ZITADEL_* carried from the primary checkout"

    # BYTE-IDENTICAL. "Carried nothing" has to mean the file was not rewritten,
    # not merely that the values happened to match.
    if cmp -s "${dir}/fresh.env" "${dir}/fresh.env.before"; then
        ok "the fresh .env is byte-identical — nothing was rewritten"
    else
        bad "the fresh .env changed on a primary with nothing to carry"
    fi
}

case_the_identity_carry_says_so_when_there_is_no_primary_env() {
    N=$((N + 1))
    local dir="${WORK}/carry${N}"
    mkdir -p "$dir"
    write_fresh_env "${dir}/fresh.env"
    cp "${dir}/fresh.env" "${dir}/fresh.env.before"

    # A machine where nobody has ever run setup.sh in the primary checkout.
    carry_in_fixture "the identity carry says so when the primary has no .env" \
        "${dir}/no-such.env" "${dir}/fresh.env"
    exits 0
    says "no readable .env"
    if cmp -s "${dir}/fresh.env" "${dir}/fresh.env.before"; then
        ok "the fresh .env is byte-identical"
    else
        bad "the fresh .env was rewritten from a primary that does not exist"
    fi
}

# READ AS TEXT, and named as the weaker proof it is (blind spot 6) — the same
# shape and the same reason as the storage case. What the cases above cannot
# see is whether step 3 still CALLS the function they drive.
case_the_identity_carry_is_wired_into_step_three() {
    CURRENT="the identity carry is wired into step 3"
    OUT=""
    local carry_def carry_call db_line
    if grep -q '^zitadel_carry() {' "$REAL"; then
        ok "zitadel_carry is defined"
    else
        bad "no zitadel_carry function — the cases above are driving nothing"
    fi
    if grep -q 'BASH_SOURCE\[0\]' "$REAL"; then
        ok "the sourced seam is there — the cases above can reach the function"
    else
        bad "no sourced seam: sourcing rung_start.sh would run all five steps"
    fi
    # `|| true` on every one of these, and it is not decoration: under
    # `set -euo pipefail` a grep that finds NOTHING takes the whole drive down
    # mid-case, so the run that most needs a verdict — the one where the thing
    # being looked for is absent — is the run that prints no tally at all.
    # (Measured on the baseline tree while proving these cases red.)
    carry_def="$(grep -n '^zitadel_carry() {' "$REAL" | cut -d: -f1 || true)"
    carry_call="$(grep -n '^ *zitadel_carry "' "$REAL" | cut -d: -f1 || true)"
    db_line="$(grep -n '^# STEP 3 · DATABASE' "$REAL" | cut -d: -f1 || true)"
    if [ -n "$carry_call" ] && [ -n "$db_line" ] && [ "$carry_call" -gt "$db_line" ]; then
        ok "step 3 (${db_line}) calls zitadel_carry (${carry_call}), defined at ${carry_def}"
    else
        bad "zitadel_carry is defined and never called from step 3: call='${carry_call}' step3='${db_line}'"
    fi
    # The carry is on the CREATE branch only: a `.env` this script did not make
    # is the builder's, and reaching into one to rewrite credential lines on
    # every re-run is a side effect nobody asked for (script header, blind
    # spot 7). `--resume` is therefore never a carry.
    if [ -n "$db_line" ] && sed -n "${db_line},\$p" "$REAL" | grep -q 'ZITADEL_\* left alone'; then
        ok "an existing .env is left alone, and says so"
    else
        bad "nothing says an existing .env keeps its own ZITADEL_* lines"
    fi
}

case_the_pin_marker_is_read_from_db_sh_and_not_recopied() {
    # THE COPY THAT WAS NEVER DRIVEN. rung_start.sh's header has declared its
    # `.env` pin policy "a second copy of setup.sh's" and named THIS file as
    # what keeps the copy honest — while this file had no case about the pin at
    # all. The claim was true about the write half and empty about the read
    # half, which is the half that broke: the marker's grammar moved (its own
    # comment line above a bare value — scripts/db.sh, "THE MARKER'S GRAMMAR")
    # and a hand-copied regex here would have gone on clobbering a name a human
    # pinned on purpose, silently, in every new worktree.
    #
    # A TEXT PROOF, and named as the weaker one rather than dressed up: the pin
    # block is top-level code inside a five-step script, so posing it
    # behaviourally means a real database. What is asserted is the seam — that
    # there is ONE marker implementation and this script calls it.
    CURRENT="the pin marker comes from db.sh"
    OUT=""
    local marker_call db_source own_grep
    # `|| true` throughout, for the reason case_the_identity_carry_is_wired...
    # spells out: a grep that finds nothing must not take the drive down.
    own_grep="$(grep -n "pinned' *\"\$ROOT/.env\"" "$REAL" | cut -d: -f1 || true)"
    if [ -z "$own_grep" ]; then
        ok "no hand-copied marker regex in this script"
    else
        bad "line ${own_grep} greps for the marker itself — a second implementation to leave behind; call db_pin_marked"
    fi
    marker_call="$(grep -n '^if db_pin_marked; then' "$REAL" | cut -d: -f1 || true)"
    db_source="$(grep -n '^\. "\$ROOT/scripts/db.sh"' "$REAL" | cut -d: -f1 || true)"
    if [ -z "$marker_call" ]; then
        bad "this script never calls db_pin_marked — the pin block reads the marker some other way"
        return 0
    fi
    ok "the pin block asks db_pin_marked (line ${marker_call})"
    if [ -n "$db_source" ] && [ "$marker_call" -gt "$db_source" ]; then
        ok "db.sh is sourced first (line ${db_source}), so the function exists when it is called"
    else
        bad "db_pin_marked is called at ${marker_call} with db.sh sourced at '${db_source}' — the call would be a command-not-found"
    fi
    # The announcement itself: a checkout that keeps its pin has to be TOLD, or
    # the scripts and a bare manage.py silently disagree for the rest of the rung.
    if grep -q 'marker — DATABASE_NAME left alone' "$REAL"; then
        ok "a pinned checkout is told its DATABASE_NAME was left alone"
    else
        bad "nothing announces the leave-alone branch — the pin would be honoured in silence"
    fi
}

echo "== test_rung_start — driving scripts/rung_start.sh's refusals"
echo "   scratch: ${WORK}"

case_a_piped_stdout_is_refused
case_an_unknown_argument_is_refused
case_a_dirty_tree_is_refused_and_nothing_is_lost
case_a_branch_ahead_of_main_is_refused_and_the_commits_survive
case_a_stale_baseline_is_reset_and_said
case_a_current_baseline_says_the_reset_was_a_no_op
case_the_pool_mechanism_is_diagnosed_by_name
case_a_current_origin_main_prints_no_pool_block
case_a_detached_head_is_refused
case_no_local_main_is_refused
case_the_storage_step_is_wired_and_is_not_fatal

case_resume_keeps_a_branch_ahead_of_main_and_says_what_it_skipped
case_resume_on_a_current_baseline_says_there_was_nothing_to_skip
case_resume_on_a_dirty_tree_still_refuses
case_resume_does_not_lift_the_reporting_refusals
case_the_help_documents_resume

case_the_identity_carry_copies_zitadel_keys_and_prints_no_value
case_the_identity_carry_population_is_the_zitadel_prefix_only
case_the_identity_carry_on_an_empty_primary_carries_nothing
case_the_identity_carry_says_so_when_there_is_no_primary_env
case_the_identity_carry_is_wired_into_step_three

case_the_pin_marker_is_read_from_db_sh_and_not_recopied

echo
echo "== ${PASSED} passed, ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another
# case — see section 5 of the preamble for why saying so is load-bearing.
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
