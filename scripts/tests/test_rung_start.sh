#!/usr/bin/env bash
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

head_of() { git -C "$REPO" rev-parse HEAD; }
main_of() { git -C "$REPO" rev-parse main; }

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

echo
echo "== ${PASSED} passed, ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another
# case — see section 5 of the preamble for why saying so is load-bearing.
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
