#!/usr/bin/env bash
# drives: .github/workflows/ci.yml scripts/check.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/tests/ deploy/tests/ quality/roads.py quality/djb/legs/goalpost_census.py
# cites: scripts/local/env_keys scripts/local/ci .claude/agents .claude/skills CLAUDE.md
# The drive for THE REAL-REPOSITORY TRIPWIRE — `drive_repo_fingerprint` and
# `drive_tripwire_check` in `scripts/tests/drive_preamble.sh` §3.
#
#   ./scripts/tests/test_drive_preamble.sh                 run every case
#   ./scripts/tests/test_drive_preamble.sh --list          name them and stop
#   ./scripts/tests/test_drive_preamble.sh --case <name>   run exactly that case
#
# IT IS ALSO THE HARNESS'S WORKED EXAMPLE. This drive carries none of its own:
# its prologue is the preamble's one line, its assertions are the preamble's
# `ok` and `bad`, its cases run through `drive_run_case`, its scratch
# repositories are `drive_scratch_repo`'s, and its summary is the epilogue's.
# Section 10 below drives that harness, and the census beside it refuses a
# drive that writes its own copy.
#
# WHAT THE TRIPWIRE IS FOR, in one sentence, because every case below is a
# judgement about that sentence: a drive builds throwaway repositories and works
# in those, so if THE REAL repository moved while a drive ran, the drive did it
# by accident and nothing it asserted can be trusted. The preamble's own header
# records the incident — scenario branches, commits and `core.bare true` written
# into the real repository through an inherited `GIT_DIR`, every command exiting
# 0.
#
# WHY IT NEEDED A DRIVE OF ITS OWN, and it is the opposite failure. Refs are
# SHARED across every worktree of one repository, and this repository routinely
# carries dozens of agent worktrees. So a tripwire that reds on any ref delta
# reds on other people's ordinary work: a peer creating a worktree, a peer
# committing on its own branch, a merge into `main` from the primary checkout, a
# reap of a branch that has already merged. Each of those cost a whole gate
# re-run, and the remedy for a gate that cries wolf is people passing it with
# `--no-verify`. The excuse has to be as precise as the alarm, and the only way
# to know it is precise is to drive BOTH directions.
#
# THE RULE THE CASES BELOW ENCODE. A ref delta is excused when, and only when,
# somebody other than this checkout can be shown to own it AT CHECK TIME:
#
#   created or moved   a worktree OTHER than this one has that ref checked out
#                      (`git worktree list --porcelain` says so). A drive cannot
#                      plausibly commit onto a peer's checked-out branch without
#                      that peer's worktree, and if it did, the peer's own
#                      `git status` is the belt.
#   vanished           its last known target is an ancestor of `refs/heads/main`
#                      — a reap of a branch that has already merged.
#
# Everything else still reds: a new ref with no worktree, a moved ref with no
# worktree, a vanished ref whose work is NOT on main, and this checkout's own
# HEAD, HEAD-ref or `core.bare`. Every excuse is PRINTED with its reason; a
# tripwire that forgives silently is a tripwire nobody can audit.
#
# HOW THE CASES DRIVE IT. Each case builds its own throwaway repository under
# `mktemp -d`, then runs a CHILD bash process that stands in that repository and
# SOURCES the real preamble there — so `DRIVE_REPO_ROOT` is the scratch, the
# fingerprint is taken by the shipped function, the mutation happens between the
# fingerprint and the check, and `drive_tripwire_check` is the shipped function
# too. The child removes the preamble's EXIT trap immediately after sourcing:
# this harness calls the function directly and reports its status, and leaving
# the epilogue armed would run the same check a second time and overwrite the
# answer. Nothing here touches this checkout.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. THE EXCUSE IS A WORKTREE, NOT A PERSON. A ref that a peer worktree has
#      checked out is excused however it moved — including, in principle, by
#      this drive. That is the declared price of not reddening on every peer's
#      ordinary commit, and the preamble's header argues it.
#   2. `git worktree list` IS ASKED AT CHECK TIME. A peer that adds a worktree
#      and removes it again inside the drive's window leaves a ref delta with no
#      worktree to explain it, and reds. That is the correct answer for the
#      escape class and a false alarm for that one peer sequence; the case that
#      pins it is `case_a_peer_worktree_removed_mid_run_still_reds`.
#   3. THE VANISHED EXCUSE TRUSTS `refs/heads/main`. A repository with no local
#      `main` excuses no reap at all, and a repository whose `main` was itself
#      force-moved backwards could un-excuse a reap that was legitimate when it
#      happened. Both red rather than forgive, which is the direction this file
#      chooses everywhere.
#   4. IT DRIVES §3, §5, §9 AND §10 of the preamble. The git-location
#      neutralisation, the scratch-path belt, the CI strip and the signal
#      bridge have their own coverage in the drives that use them.
#   5. THE HARNESS CENSUS READS DEFINITIONS BY NAME. A drive's own `is`,
#      `same` or `differs` is `holds` under a name the census does not know,
#      and a helper renamed rather than removed is invisible to it.
set -euo pipefail

cd "$(dirname "$0")/../.."
. scripts/tests/drive_preamble.sh || exit 2

command -v git >/dev/null 2>&1 || drive_cannot_look "no git on PATH — the whole file is about git refs"

ROOT="$PWD"
PREAMBLE="${ROOT}/scripts/tests/drive_preamble.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-preamble-drive.XXXXXX")" || drive_cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

# The capture a red shows (the preamble's `bad` reads it unless handed another).
DRIVE_OUT=""

# A throwaway repository on `main` — the preamble's, so the path is proven
# before git is handed it — with one file committed on top of its base.
new_scratch_repo() {
    SCRATCH_REPO="$1"
    drive_scratch_repo SCRATCH_REPO
    printf 'one\n' >"${SCRATCH_REPO}/f.txt"
    git -C "$SCRATCH_REPO" add f.txt
    git -C "$SCRATCH_REPO" commit -q -m "one"
}

# Run the SHIPPED preamble inside `$1`, with `$2` as the mid-run mutation, and
# leave the tripwire's own output plus a `TRIPWIRE_RC=` line in `$DRIVE_OUT`.
#
# The child is written to a file rather than passed with `bash -c` so the
# mutation reads as the script it is, and so `$0` gives the preamble a sensible
# DRIVE_NAME.
CHILD_N=0
run_tripwire() {
    local stand_in="$1" mutation="$2" child
    CHILD_N=$((CHILD_N + 1))
    child="${WORK}/child-${CHILD_N}.sh"
    DRIVE_OUT="${WORK}/child-${CHILD_N}.log"
    {
        printf '#!/usr/bin/env bash\n'
        printf 'set -uo pipefail\n'
        printf 'cd %s\n' "$stand_in"
        printf '. %s\n' "$PREAMBLE"
        # This harness drives the function directly; the epilogue would run the
        # same check a second time and replace the answer with its own.
        printf 'trap - EXIT INT TERM HUP\n'
        printf '%s\n' "$mutation"
        printf 'tripwire_rc=0\n'
        printf 'drive_tripwire_check || tripwire_rc=$?\n'
        printf 'echo "TRIPWIRE_RC=${tripwire_rc}"\n'
        printf 'exit 0\n'
    } >"$child"
    chmod +x "$child"
    "$child" >"$DRIVE_OUT" 2>&1 || true
}

tripwire_rc() {
    local seen
    seen="$(grep '^TRIPWIRE_RC=' "$DRIVE_OUT" || true)"
    seen="${seen%%$'\n'*}"
    printf '%s' "${seen#TRIPWIRE_RC=}"
}

# seen <needle> — the predicate over the last capture (the preamble's `says` asserts; this asks).
seen() { grep -qF -- "$1" "$DRIVE_OUT"; }

# --- the fingerprint ----------------------------------------------------------

case_the_fingerprint_records_a_sha_for_every_ref() {
    local repo="${WORK}/fp" want got
    new_scratch_repo "$repo"
    git -C "$repo" branch zzz-other
    run_tripwire "$repo" 'drive_repo_fingerprint'
    want="$(git -C "$repo" rev-parse refs/heads/main)"
    got="$(awk '$1=="ref" && $2=="refs/heads/main" { print $3 }' "$DRIVE_OUT")"
    if [ "$got" != "$want" ]; then
        bad "the fingerprint's main line carries '${got}', wanted the sha '${want}' — a name-only fingerprint cannot tell a reap of merged work from a reap of lost work"
        return
    fi
    got="$(awk '$1=="ref" { n++ } END { print n+0 }' "$DRIVE_OUT")"
    if [ "$got" != "2" ]; then
        bad "wanted 2 ref lines, got ${got}"
        return
    fi
    ok "every ref line is 'ref <name> <sha>' — 2 refs, main's sha matches rev-parse"
}

# --- the four excuses ---------------------------------------------------------

case_a_peer_worktree_branch_created_mid_run_does_not_red_the_tripwire() {
    local repo="${WORK}/created" rc
    new_scratch_repo "$repo"
    run_tripwire "$repo" "git -C '${repo}' worktree add -q -b zzz-peer '${WORK}/created-peer' >/dev/null 2>&1"
    rc="$(tripwire_rc)"
    if [ "$rc" != "0" ]; then
        bad "a peer's worktree creation red the tripwire (rc=${rc}) — this is the flake that costs a whole gate"
        return
    fi
    if ! seen "excused: refs/heads/zzz-peer — created by a peer worktree"; then
        bad "the excuse was silent; an excuse nobody can read is an excuse nobody can audit"
        return
    fi
    ok "rc=0 with 'excused: refs/heads/zzz-peer — created by a peer worktree' printed"
}

case_a_peer_worktrees_commit_mid_run_does_not_red_the_tripwire() {
    local repo="${WORK}/moved" peer="${WORK}/moved-peer" rc
    new_scratch_repo "$repo"
    git -C "$repo" worktree add -q -b zzz-peer "$peer"
    run_tripwire "$repo" "printf 'two\n' > '${peer}/f.txt'
git -C '${peer}' add f.txt
git -C '${peer}' commit -q -m two"
    rc="$(tripwire_rc)"
    if [ "$rc" != "0" ]; then
        bad "a peer's ordinary boundary commit red the tripwire (rc=${rc})"
        return
    fi
    if ! seen "excused: refs/heads/zzz-peer — checked out by a peer worktree"; then
        bad "the moved ref was not excused by name and reason"
        return
    fi
    ok "rc=0 with 'excused: refs/heads/zzz-peer — checked out by a peer worktree' printed"
}

case_a_merge_into_main_by_the_primary_worktree_does_not_red_a_linked_drive() {
    local repo="${WORK}/merge" linked="${WORK}/merge-linked" rc
    new_scratch_repo "$repo"
    # The work the primary is about to merge, made before the drive is armed.
    git -C "$repo" branch zzz-work
    git -C "$repo" worktree add -q "${WORK}/merge-work" zzz-work
    printf 'work\n' >"${WORK}/merge-work/f.txt"
    git -C "${WORK}/merge-work" add f.txt
    git -C "${WORK}/merge-work" commit -q -m work
    # The drive stands in a LINKED worktree, the way every rung's drive does.
    git -C "$repo" worktree add -q -b zzz-linked "$linked"
    run_tripwire "$linked" "git -C '${repo}' merge -q --no-ff -m merge zzz-work"
    rc="$(tripwire_rc)"
    if [ "$rc" != "0" ]; then
        bad "a merge into main from the primary checkout red a linked worktree's drive (rc=${rc})"
        return
    fi
    if ! seen "excused: refs/heads/main — checked out by a peer worktree"; then
        bad "main moved and was not excused by the primary worktree that holds it"
        return
    fi
    ok "rc=0 with 'excused: refs/heads/main — checked out by a peer worktree' printed"
}

case_a_reap_of_a_merged_peer_branch_mid_run_does_not_red_the_tripwire() {
    local repo="${WORK}/reap" rc
    new_scratch_repo "$repo"
    git -C "$repo" worktree add -q -b zzz-done "${WORK}/reap-done"
    printf 'done\n' >"${WORK}/reap-done/f.txt"
    git -C "${WORK}/reap-done" add f.txt
    git -C "${WORK}/reap-done" commit -q -m done
    git -C "$repo" merge -q --no-ff -m merge zzz-done
    git -C "$repo" worktree remove "${WORK}/reap-done"
    run_tripwire "$repo" "git -C '${repo}' branch -q -d zzz-done"
    rc="$(tripwire_rc)"
    if [ "$rc" != "0" ]; then
        bad "the reap of a branch already merged into main red the tripwire (rc=${rc})"
        return
    fi
    if ! seen "excused: refs/heads/zzz-done — merged into main, reaped"; then
        bad "the vanished ref was not excused as a reap of merged work"
        return
    fi
    ok "rc=0 with 'excused: refs/heads/zzz-done — merged into main, reaped' printed"
}

# --- the controls: the alarm still fires ---------------------------------------

case_a_branch_with_no_worktree_still_reds_the_tripwire() {
    local repo="${WORK}/escape" rc
    new_scratch_repo "$repo"
    run_tripwire "$repo" "git -C '${repo}' branch zzz-escape"
    rc="$(tripwire_rc)"
    if [ "$rc" != "1" ]; then
        bad "a branch created with no worktree behind it did not red (rc=${rc}) — this is the escape class the tripwire exists for"
        return
    fi
    if ! seen "MUTATED THE REAL REPOSITORY"; then
        bad "no banner; a red with no sentence is a red nobody acts on"
        return
    fi
    ok "rc=1 and the banner named it — the excuse did not swallow the escape class"
}

case_a_moved_ref_with_no_worktree_still_reds_the_tripwire() {
    local repo="${WORK}/orphan" other rc
    new_scratch_repo "$repo"
    git -C "$repo" branch zzz-orphan
    printf 'two\n' >"${repo}/f.txt"
    git -C "$repo" add f.txt
    git -C "$repo" commit -q -m two
    other="$(git -C "$repo" rev-parse HEAD)"
    run_tripwire "$repo" "git -C '${repo}' update-ref refs/heads/zzz-orphan ${other}"
    rc="$(tripwire_rc)"
    if [ "$rc" != "1" ]; then
        bad "a ref moved with no worktree holding it did not red (rc=${rc})"
        return
    fi
    ok "rc=1 — a moved ref is excused only by a worktree, never by having existed before"
}

case_a_vanished_unmerged_ref_still_reds() {
    local repo="${WORK}/lost" lost rc
    new_scratch_repo "$repo"
    git -C "$repo" worktree add -q -b zzz-unmerged "${WORK}/lost-wt"
    printf 'unmerged\n' >"${WORK}/lost-wt/f.txt"
    git -C "${WORK}/lost-wt" add f.txt
    git -C "${WORK}/lost-wt" commit -q -m unmerged
    lost="$(git -C "$repo" rev-parse refs/heads/zzz-unmerged)"
    git -C "$repo" worktree remove --force "${WORK}/lost-wt"
    run_tripwire "$repo" "git -C '${repo}' branch -q -D zzz-unmerged"
    rc="$(tripwire_rc)"
    if [ "$rc" != "1" ]; then
        bad "work that was NOT on main vanished and the tripwire forgave it (rc=${rc})"
        return
    fi
    if ! seen "$lost"; then
        bad "the banner did not print the sha that was lost (${lost}) — the one thing a recovery needs"
        return
    fi
    ok "rc=1 and the lost sha ${lost} printed — the reap excuse is bounded by 'already on main'"
}

case_a_peer_worktree_removed_mid_run_still_reds() {
    local repo="${WORK}/removed" peer="${WORK}/removed-peer" rc
    new_scratch_repo "$repo"
    git -C "$repo" worktree add -q -b zzz-gone "$peer"
    run_tripwire "$repo" "printf 'two\n' > '${peer}/f.txt'
git -C '${peer}' add f.txt
git -C '${peer}' commit -q -m two
git -C '${repo}' worktree remove --force '${peer}'"
    rc="$(tripwire_rc)"
    if [ "$rc" != "1" ]; then
        bad "the excuse was taken at ADD time rather than at CHECK time (rc=${rc}) — a ref with no worktree standing behind it must red however it got there"
        return
    fi
    ok "rc=1 — the worktree list is asked when the check runs, not when the fingerprint was taken"
}

case_this_checkouts_head_moving_still_reds() {
    local repo="${WORK}/ownhead" rc
    new_scratch_repo "$repo"
    run_tripwire "$repo" "printf 'two\n' > '${repo}/f.txt'
git -C '${repo}' add f.txt
git -C '${repo}' commit -q -m two"
    rc="$(tripwire_rc)"
    if [ "$rc" != "1" ]; then
        bad "the drive's own checkout committed and the tripwire did not red (rc=${rc}) — this is exactly the escape the preamble was written for"
        return
    fi
    if ! seen "HEAD"; then
        bad "the banner did not name HEAD"
        return
    fi
    ok "rc=1 — this checkout's own HEAD is nobody else's to excuse"
}

# --- the base ref -------------------------------------------------------------

# A RUNNER-SHAPED CLONE, built rather than described: `actions/checkout` on a
# pull request leaves HEAD DETACHED and creates no local branch, so the shape a
# drive meets on CI is "a remote-tracking ref and nothing else". A clone,
# detached at `origin/main`, with the local branch `git clone` made deleted, is
# that shape exactly — and it is the shape none of these drives was written in.
runner_shaped_clone() {
    local src="$1" dst="$2" here
    git clone --quiet --shared --no-hardlinks "$src" "$dst" >/dev/null 2>&1 || return 1
    git -C "$dst" checkout --quiet --detach origin/main >/dev/null 2>&1 || return 1
    here="$(git -C "$dst" for-each-ref --format='%(refname:short)' refs/heads)"
    [ -z "$here" ] || git -C "$dst" branch -D $here >/dev/null 2>&1 || return 1
    return 0
}

case_the_base_ref_reader_resolves_main_then_origin_main_then_refuses() {
    # FOUR SHAPES AND FOUR ANSWERS, and the two that matter are the ones
    # no drive had ever been in: the runner's (no local `main`), and nothing at
    # all. The reader's whole job is that the second is a REFUSAL rather than an
    # empty string a caller then interpolates into `"${base}:path"`.
    local src="${WORK}/base-src" clone="${WORK}/base-clone" bare="${WORK}/base-bare"
    local err="${WORK}/base-err.txt" got rc
    DRIVE_OUT="$err"
    rm -rf "$src" "$clone" "$bare"
    new_scratch_repo "$src"

    # (1) a checkout WITH a local main — the laptop, the worktree, the primary.
    got="$(drive_base_ref "$src" 2>"$err")" && rc=0 || rc=$?
    if [ "$rc" = "0" ] && [ "$got" = "refs/heads/main" ]; then
        ok "a checkout with a local main resolves to refs/heads/main"
    else
        bad "a checkout with a local main answered '${got}' rc ${rc}"
    fi

    # (2) THE RUNNER'S SHAPE. Today's bare `main` is exit 1 here, and the
    # `|| true` spelling this reader replaces printed its own ARGUMENT instead.
    runner_shaped_clone "$src" "$clone" || {
        drive_cannot_look "could not build the runner-shaped clone in ${clone}"
    }
    if [ -n "$(git -C "$clone" for-each-ref --format='x' refs/heads)" ] ||
        [ -n "$(git -C "$clone" symbolic-ref -q HEAD || true)" ]; then
        bad "the scratch clone is not runner-shaped — it still has a local branch or an attached HEAD"
        return 0
    fi
    got="$(drive_base_ref "$clone" 2>"$err")" && rc=0 || rc=$?
    if [ "$rc" = "0" ] && [ "$got" = "refs/remotes/origin/main" ]; then
        ok "a detached clone with no local main resolves to refs/remotes/origin/main"
    else
        bad "the runner shape answered '${got}' rc ${rc}"
    fi

    # (3) A TYPED REF WINS, wherever it points — the operator knows a base this
    # checkout cannot derive.
    git -C "$src" branch -f release-1 main >/dev/null 2>&1
    got="$(DJB_BASE_REF=release-1 drive_base_ref "$src" 2>"$err")" && rc=0 || rc=$?
    if [ "$rc" = "0" ] && [ "$got" = "release-1" ]; then
        ok "a typed DJB_BASE_REF outranks a resolvable main"
    else
        bad "a typed ref answered '${got}' rc ${rc}"
    fi

    # (4) A TYPED REF THAT DOES NOT RESOLVE IS A REFUSAL, never a quiet fall
    # back to `main` — which is sitting right there in this repository, so a
    # fall-through would be green and would measure the wrong tree.
    got="$(DJB_BASE_REF=no/such/ref drive_base_ref "$src" 2>"$err")" && rc=0 || rc=$?
    if [ "$rc" = "1" ] && [ -z "$got" ] && grep -qF 'no/such/ref' "$err"; then
        ok "a typed ref that does not resolve is rc 1 and names what was typed, with main right there"
    else
        bad "a typed unresolvable ref answered '${got}' rc ${rc}"
    fi

    # (5) NOTHING AT ALL — rc 1, and the sentence names all three sources
    # because the reader of a refusal is deciding what to type next.
    runner_shaped_clone "$src" "$bare" || {
        drive_cannot_look "could not build the second runner-shaped clone in ${bare}"
    }
    git -C "$bare" remote remove origin >/dev/null 2>&1
    git -C "$bare" update-ref -d refs/remotes/origin/main >/dev/null 2>&1 || true
    got="$(drive_base_ref "$bare" 2>"$err")" && rc=0 || rc=$?
    local named=0 want
    for want in 'DJB_BASE_REF' 'refs/heads/main' 'refs/remotes/origin/main'; do
        grep -qF -- "$want" "$err" && named=$((named + 1))
    done
    if [ "$rc" = "1" ] && [ -z "$got" ] && [ "$named" = "3" ]; then
        ok "no base ref at all is rc 1 with an empty answer, naming all three sources"
    else
        bad "the empty shape answered '${got}' rc ${rc}, naming ${named}/3 sources"
    fi

    # (6) ITS OWN VICTIM, because every branch above is a green this case would
    # print anyway if the reader returned the first thing it found: a repository
    # whose `main` is GONE and whose origin/main is gone must not answer with a
    # ref that is merely NAMED in the refusal text.
    case "$got" in
    *main*) bad "the refusal path returned a ref name (${got}) — a caller would interpolate it" ;;
    *) ok "and the refusal returns no ref for a caller to interpolate" ;;
    esac

    rm -rf "$src" "$clone" "$bare"
    DRIVE_OUT=""
}


# --- section 5: a drive that did not finish is not a pass ---------------------
# Deleted: case_every_registered_drive_calls_drive_finished — subject dies with the shim (pin: test_harness.py::test_every_registered_drive_calls_drive_finished)

# THE CLASS, NOT THE BASH-3.2 SYMPTOM. A drive that `exit 0`s from inside a case
# never reaches its summary on any bash, so this arm is what bash 5 (the boxes,
# CI) can verify. The child sources the REAL preamble and sets nothing, so what
# it measures is the default.
run_unfinished_child() { # <arm: early|finished|opted-out>
    local arm="$1" child="${WORK}/unfinished-$1.sh"
    DRIVE_OUT="${WORK}/unfinished-$1.out"
    UNFINISHED_RC=0
    {
        printf '#!/usr/bin/env bash\n'
        printf 'set -uo pipefail\n'
        printf 'cd "%s" || exit 9\n' "$ROOT"
        printf '. scripts/tests/drive_preamble.sh\n'
        [ "$arm" != "opted-out" ] || printf 'DRIVE_OPTED_IN_TO_FINISH=0\n'
        printf 'case_that_leaves() {\n'
        [ "$arm" = "finished" ] || printf '    exit 0\n'
        printf '    :\n'
        printf '}\n'
        printf 'case_that_leaves\n'
        printf 'echo "unfinished-child: summary"\n'
        [ "$arm" = "opted-out" ] || printf 'drive_finished\n'
        printf 'exit 0\n'
    } >"$child"
    chmod +x "$child"
    "$child" >"$DRIVE_OUT" 2>&1 || UNFINISHED_RC=$?
}
UNFINISHED_RC=0

case_a_drive_that_exits_inside_a_case_is_exit_2_on_any_bash() {
    run_unfinished_child early
    if [ "$UNFINISHED_RC" != "2" ] || ! seen "DIED BEFORE REPORTING" || seen "unfinished-child: summary"; then
        bad "a drive that left from inside a case, by default, exited ${UNFINISHED_RC} (want 2 and the DIED BEFORE REPORTING banner)"
        return
    fi
    ok "by default, an exit 0 from inside a case is exit 2 with the banner ($(bash --version | sed -n '1p'))"
    run_unfinished_child finished
    if [ "$UNFINISHED_RC" != "0" ] || seen "DIED BEFORE REPORTING"; then
        bad "the control — the same drive reaching drive_finished — exited ${UNFINISHED_RC}, want 0 and no banner"
        return
    fi
    ok "the control reaches drive_finished and exits 0"
    run_unfinished_child opted-out
    if [ "$UNFINISHED_RC" != "0" ] || seen "DIED BEFORE REPORTING"; then
        bad "a drive that opted out with DRIVE_OPTED_IN_TO_FINISH=0 exited ${UNFINISHED_RC}, want 0 — the opt-out is not honoured"
        return
    fi
    ok "a drive that opts out (DRIVE_OPTED_IN_TO_FINISH=0) keeps the old behaviour"
}

# Deleted: case_a_registered_drive_that_cannot_look_is_exit_2_not_a_pass — subject dies with the shim (pin: test_selftest_compose.py::test_a_could_not_look_drive_outranks_a_red_one_and_both_are_named)

# Every name `.github/workflows/ci.yml` puts into the environment of the step
# that runs a unit, DERIVED FROM THE WORKFLOW rather than typed here. Three
# mechanisms, because the file uses three:
#
#   * the workflow-level `env:` block, which GitHub exports into every step;
#   * the gate step's own `env:` block, inside the `legs` job;
#   * a `NAME=` written to `$GITHUB_ENV` by an earlier step of the same job,
#     which is how the derived database name reaches the gate.
#
# The `images` and `verdict` jobs are deliberately OUT of scope: neither runs a
# drive, so a `TAG` or a `GH_TOKEN` there reaches nothing this file protects.
# An uppercase YAML key is the needle for the first two, because that is the
# convention the file keeps and the alternative — tracking `env:` block indent
# through a `run: |` literal — is a YAML parser written in awk.
workflow_sets() {
    awk '
        /^env:$/ { inenv = 1; next }
        inenv && /^[a-z]/ { inenv = 0 }
        /^  legs:$/ { inlegs = 1; next }
        inlegs && /^  [a-z]/ { inlegs = 0 }
        (inenv || inlegs) && match($0, /^[[:space:]]+[A-Z][A-Z0-9_]*:/) {
            k = substr($0, RSTART, RLENGTH); gsub(/[[:space:]:]/, "", k); print k; next
        }
        inlegs && /GITHUB_ENV/ && match($0, /"[A-Z][A-Z0-9_]*=/) {
            print substr($0, RSTART + 1, RLENGTH - 2)
        }
    ' "$1" | LC_ALL=C sort -u
}

case_every_variable_the_workflow_sets_is_accounted_for() {
    # THE TOOTH ON BOTH LISTS, and it is about the CLASS rather than one knob.
    # The workflow runs the selftest leg in the SAME step it runs every other
    # unit in, so every name that step carries is in every drive's environment —
    # and a case that asks for the DEFAULT branch of one then measures the
    # branch the runner typed. Measured on run 35241431444: three shards red,
    # five drives, and two of them were this exactly — `DJB_GATE_PYTEST_SEED`
    # made `test_list_legs`'s untyped-seed case see a typed one, and
    # `DATABASE_NAME` made `test_db_pin`'s present-database case read a
    # provenance label that belonged to the launcher.
    #
    # ACCOUNTED FOR, NOT STRIPPED, because most of this population is the
    # world's coordinates and a drive that unset them could not dial the stack
    # it measures. Every name is in `DRIVE_GATE_VARS` (unset for every drive) or
    # `DRIVE_INHERITED_VARS` (declared: somebody looked, and a case that turns on
    # it pins it at its own call site). What this case refuses is a name in
    # NEITHER — the knob nobody has thought about yet.
    #
    # Containment, not equality: `DRIVE_GATE_VARS` also names knobs an operator
    # types by hand and CI never sets, which is what the two sanction variables
    # are.
    local workflow names name unlisted="" stripped="" inherited=""
    DRIVE_OUT=""
    workflow="${ROOT}/.github/workflows/ci.yml"
    if [ ! -r "$workflow" ]; then
        bad "no readable ${workflow} — this case cannot look, and a silent pass would vouch for a list nothing compares"
        return
    fi
    names="$(workflow_sets "$workflow")"
    # THE CANARY. If the extraction ever comes back empty the case must not
    # report clean: an assertion over an empty population is could-not-look
    # wearing a pass, which is the shape this whole rung was sent to end.
    case " $(printf '%s' "$names" | tr '\n' ' ') " in
    *" DJB_GATE_PYTEST_SEED "*) ;;
    *)
        bad "the extraction found no DJB_GATE_PYTEST_SEED in ${workflow} — the reader is broken or the workflow moved, and either way this case is asserting over the wrong population"
        return
        ;;
    esac
    for name in $names; do
        case " ${DRIVE_GATE_VARS} " in
        *" ${name} "*)
            stripped="${stripped}${stripped:+ }${name}"
            continue
            ;;
        esac
        case " ${DRIVE_INHERITED_VARS} " in
        *" ${name} "*)
            inherited="${inherited}${inherited:+ }${name}"
            continue
            ;;
        esac
        unlisted="${unlisted}${unlisted:+ }${name}"
    done
    if [ -n "$unlisted" ]; then
        bad "ci.yml puts ${unlisted} into the step that runs the gate, and drive_preamble.sh neither strips it (DRIVE_GATE_VARS) nor declares it inherited (DRIVE_INHERITED_VARS) — every drive gets it, and a case that wants its default measures the runner's value instead"
        return
    fi
    ok "$(printf '%s\n' "$names" | grep -c .) name(s) the workflow sets, all accounted for — stripped: ${stripped:-none} · declared inherited: ${inherited:-none}"
}

# Deleted: case_every_registered_drive_declares_what_it_drives — subject dies with the shim (pin: test_harness.py::test_every_registered_drive_keys_cleanly_against_the_measured_tree)

case_a_body_spelling_three_undeclared_paths_is_named_whole_and_refused_at_the_hook() {
    # THE MEASURED SHAPE. A drive edit spelled `.claude/agents`, `.claude/skills`
    # and `CLAUDE.md` in its body and declared none of them; the hook and
    # `--loop` never asked, and the first reader was a ten-box bank that named
    # ONE of the three — so learning all three would have cost three banks. Two
    # teeth: the floor names every path in one sentence, and the tier the hook
    # runs decides the key of every drive the active rung touched.
    local clone drive list out rc
    # shellcheck source=scripts/gate_refuse.sh
    . "${ROOT}/scripts/gate_refuse.sh"
    # shellcheck source=scripts/gate_ledger.sh
    . "${ROOT}/scripts/gate_ledger.sh"
    if ! command -v drive_keys_of_touched >/dev/null 2>&1; then
        bad "scripts/gate_ledger.sh defines no drive_keys_of_touched — a drive's key is still decided only at the bank"
        return
    fi
    clone="${WORK}/three-paths-clone"
    git clone --quiet --shared --no-hardlinks "$ROOT" "$clone" >/dev/null 2>&1 ||
        drive_cannot_look "could not clone this checkout into ${clone}"
    drive="scripts/tests/test_three_undeclared.sh"
    # THE MARKER IS ASSEMBLED, never typed at column zero in this file's own
    # first forty lines — the same rule every planted declaration here keeps.
    {
        echo '#!/usr/bin/env bash'
        printf '# %s scripts/check.sh\n' 'drives:'
        echo '. "$(dirname "$0")/drive_preamble.sh"'
        echo 'ls .claude/agents >/dev/null'
        echo 'ls .claude/skills >/dev/null'
        echo 'grep -c gate CLAUDE.md'
    } >"${clone}/${drive}"
    chmod +x "${clone}/${drive}"
    list="${WORK}/three-paths-changed"
    printf '%s\0' "$drive" >"$list"
    rc=0
    out="$(cd "$clone" && drive_keys_of_touched "$list" 2>&1)" || rc=$?
    if [ "$rc" = "2" ]; then
        ok "the touched drive does not key — exit 2, the selftest leg's own status"
    else
        bad "a touched drive spelling three undeclared paths keyed, or answered ${rc} (not 2): ${out}"
    fi
    case "$out" in
    *"drive three_undeclared: could not key — its body spells .claude/agents, .claude/skills and CLAUDE.md and its"*)
        ok "ONE line names ALL THREE, in the leg's own sentence: ${out}"
        ;;
    *) bad "the refusal does not name all three paths in the leg's sentence: ${out}" ;;
    esac
    # THE CONTROL: the same drive, declaring what it reads, keys.
    {
        echo '#!/usr/bin/env bash'
        printf '# %s scripts/check.sh .claude/agents .claude/skills CLAUDE.md\n' 'drives:'
        echo '. "$(dirname "$0")/drive_preamble.sh"'
        echo 'ls .claude/agents >/dev/null'
        echo 'ls .claude/skills >/dev/null'
        echo 'grep -c gate CLAUDE.md'
    } >"${clone}/${drive}"
    rc=0
    out="$(cd "$clone" && drive_keys_of_touched "$list" 2>&1)" || rc=$?
    if [ "$rc" = "0" ]; then
        ok "declared, the same drive keys: ${out}"
    else
        bad "a drive declaring every path it spells still could not key (${rc}): ${out}"
    fi
    # AND NO DRIVE TOUCHED IS NOTHING TO DECIDE, said rather than silent.
    : >"$list"
    rc=0
    out="$(cd "$clone" && drive_keys_of_touched "$list" 2>&1)" || rc=$?
    case "${rc}:${out}" in
    "0:"*"touched no drive"*) ok "an empty touched set is exit 0 and says so" ;;
    *) bad "an empty touched set answered ${rc}: ${out}" ;;
    esac
    rm -rf "$clone"
    # WIRED INTO THE HOOK'S TIER: the goalpost-census leg (a --fast leg) calls it.
    if grep -qF 'drive_keys_of_touched "$changed"' "${ROOT}/quality/djb/legs/goalpost_census.py"; then
        ok "the goalpost-census leg (a --fast leg) calls drive_keys_of_touched"
    else
        bad "the --fast tier never decides a touched drive's key — the goalpost-census leg does not call drive_keys_of_touched"
    fi
}

# --- the product's own drawers: the env keys, and the workflow's one step -----
#
# WHY THESE TWO LIVE IN THIS DRIVE. Section 4a of the preamble is what strips
# the gate's own input variables, and section 4c is the PRODUCT's inverse of it
# — a `scripts/local/env_keys` drawer naming what to KEEP. The census above
# (`case_every_variable_the_workflow_sets_is_accounted_for`) is the tooth on
# both lists, so the drawer that widens one of them belongs beside it. The
# workflow's optional `local` job is the same decision one file over: a product
# declares its CI steps in `scripts/local/ci/` instead of editing this
# repository's `ci.yml`, and this drive is already the one that reads that file.

# The scratch `env_keys` file for one arm.
write_env_keys() {
    ENV_KEYS_FILE="${WORK}/env_keys-$1"
    shift
    printf '%s\n' "$@" >"$ENV_KEYS_FILE"
}
ENV_KEYS_FILE=""

# Source the REAL preamble in a child shell that stands in this checkout, with
# the drawer pointed where the arm wants it. A child, because the preamble
# unsets things and installs an EXIT trap: doing that in this drive's own shell
# would be a case rewriting the drive that runs it.
run_preamble_child() {
    PRE_OUT="${WORK}/preamble-child.out"
    PRE_RC=0
    (
        cd "$ROOT" || exit 2
        if [ -n "${1:-}" ]; then
            DJB_LOCAL_ENV_KEYS="$1"
            export DJB_LOCAL_ENV_KEYS
        fi
        shift || true
        # A TEMPLATE KNOB AND A PRODUCT KNOB, both set, so each arm can say
        # which of the two the strip did something about.
        DJB_GATE_SANCTION="drive: the strip arm"
        ACME_DRIVE_TOKEN="a value the product's drives read"
        export DJB_GATE_SANCTION ACME_DRIVE_TOKEN
        # shellcheck source=scripts/tests/drive_preamble.sh
        . scripts/tests/drive_preamble.sh
        echo "AFTER sanction=${DJB_GATE_SANCTION:-<unset>} acme=${ACME_DRIVE_TOKEN:-<unset>}"
        echo "AFTER inherited=${DRIVE_INHERITED_VARS}"
        drive_finished
    ) >"$PRE_OUT" 2>&1 || PRE_RC=$?
}
PRE_OUT=""
PRE_RC=0

case_the_product_env_keys_drawer_declares_product_keys_only() {
    DRIVE_OUT=""
    # (1) NO DRAWER: the template's own knob is stripped, as it always was, and
    # the product's is never mentioned. This is the negative, and it is first
    # so the arms below are differences from a measured baseline rather than
    # from a remembered one.
    run_preamble_child ""
    if [ "$PRE_RC" != "0" ]; then
        bad "sourcing the preamble with no drawer exited ${PRE_RC}: $(tr '\n' '|' <"$PRE_OUT")"
        return
    fi
    if ! grep -qF 'AFTER sanction=<unset>' "$PRE_OUT"; then
        bad "with no drawer the gate's own DJB_GATE_SANCTION was NOT stripped — section 4a is what the drawer inverts, and it has stopped working"
        return
    fi
    if grep -qF 'env keys kept' "$PRE_OUT"; then
        bad "a tree with no drawer printed a kept-keys line: $(grep -F 'env keys kept' "$PRE_OUT")"
        return
    fi
    ok "no drawer: the gate's own input variables are stripped and nothing mentions a drawer"

    # (2) A DRAWER OF THE PRODUCT'S OWN KEYS. The product's name survives (it
    # would have anyway — the template strips only its own), and the point of
    # the drawer is the DECLARATION: the census one screen up must read a
    # product's CI knob as accounted for rather than as the "nobody has thought
    # about this one" red it exists to print.
    write_env_keys kept 'ACME_DRIVE_TOKEN' '# a comment line, and a blank one below' '' 'ACME_OTHER'
    run_preamble_child "$ENV_KEYS_FILE"
    if [ "$PRE_RC" != "0" ]; then
        bad "a well-formed drawer exited ${PRE_RC}: $(tr '\n' '|' <"$PRE_OUT")"
        return
    fi
    if ! grep -qF "acme=a value the product's drives read" "$PRE_OUT"; then
        bad "the product's own variable did not survive the preamble at all"
        return
    fi
    if ! grep -qF 'product env keys declared' "$PRE_OUT"; then
        bad "the drawer is not PRINTED — a declaration nobody can see in the transcript is not one"
        return
    fi
    # AND THE TEMPLATE'S OWN KNOB IS STILL STRIPPED, drawer or no drawer. This
    # is the assertion the review turned around: the first draft let
    # the drawer KEEP a name from `DRIVE_GATE_VARS`, which on a runner hands a
    # product drive the full-gate sanction and the loop-here permission.
    if ! grep -qF 'AFTER sanction=<unset>' "$PRE_OUT"; then
        bad "a drawer was present and the gate's own DJB_GATE_SANCTION survived: $(grep -F 'AFTER sanction' "$PRE_OUT")"
        return
    fi
    if ! grep -qE 'AFTER inherited=.* ACME_DRIVE_TOKEN( |$)' "$PRE_OUT"; then
        bad "the drawer's names did not join DRIVE_INHERITED_VARS: $(grep -F 'AFTER inherited' "$PRE_OUT")"
        return
    fi
    ok "a product key is declared, printed and joins the declared-inherited list, and the template's own knob is still stripped"

    # (2b) THE REFUSAL, AND IT IS THE HIGH FINDING'S OWN CANARY. Every name the
    # template strips on purpose, plus the three reserved prefixes, one drawer
    # line at a time: each must be exit 2 naming the name.
    local reserved rc_seen
    for reserved in DJB_GATE_SANCTION DJB_LOOP_HERE DJB_LOCAL_ENV_KEYS CI GITHUB_ACTIONS DJB_GATE_ANYTHING_NEW; do
        write_env_keys "res-${reserved}" 'ACME_OK' "$reserved"
        run_preamble_child "$ENV_KEYS_FILE"
        rc_seen=$PRE_RC
        if [ "$rc_seen" != "2" ]; then
            bad "a drawer naming ${reserved} exited ${rc_seen}, want 2 — it re-admits a knob this template strips on purpose, and a product drive on a runner could then start a bare check.sh with the guard stood down"
            return
        fi
        if ! grep -qF "'${reserved}'" "$PRE_OUT"; then
            bad "the refusal for ${reserved} does not name it: $(grep -F '!!' "$PRE_OUT" | tr '\n' '|')"
            return
        fi
    done
    ok "six reserved names refused one at a time, each exit 2 naming itself (the two strip lists and the three DJB_ prefixes)"

    # (2c) THE NEGATIVE OF THE REFUSAL. A product name that merely LOOKS like
    # one of ours must still be admitted, or the guard has eaten the drawer.
    write_env_keys notreserved 'ACME_CI' 'CI_ACME' 'DJB_ACME_TOKEN'
    run_preamble_child "$ENV_KEYS_FILE"
    if [ "$PRE_RC" != "0" ]; then
        bad "a drawer of product names that merely resemble ours exited ${PRE_RC}: $(grep -F '!!' "$PRE_OUT" | tr '\n' '|')"
        return
    fi
    ok "ACME_CI, CI_ACME and DJB_ACME_TOKEN are the product's and are admitted — the refusal is the two lists and the three prefixes, not a substring"

    # (3) MALFORMED IS EXIT 2, NAMING THE FILE AND THE LINE. A drawer this
    # preamble half-understands is a strip it half-applies.
    write_env_keys bad 'ACME_OK' 'ACME=1'
    run_preamble_child "$ENV_KEYS_FILE"
    if [ "$PRE_RC" != "2" ]; then
        bad "a malformed drawer line exited ${PRE_RC}, want 2: $(tr '\n' '|' <"$PRE_OUT")"
        return
    fi
    if ! grep -qF ":2: 'ACME=1' is not a variable NAME" "$PRE_OUT"; then
        bad "the refusal does not name the line number and the text: $(grep -F '!!' "$PRE_OUT" | tr '\n' '|')"
        return
    fi
    ok "a malformed line is exit 2 naming the file, the line number and the text"
}

# Pull the workflow's optional `local` job out of `.github/workflows/ci.yml` by
# its sentinels and run its `run:` body in a scratch tree. The block CI ships is
# the block that runs.
run_local_ci_block() {
    local dir="$1" block="${WORK}/local-ci-block.sh"
    awk '
        /^[[:space:]]*# >>> local-ci >>>$/ { on = 1; next }
        /^[[:space:]]*# <<< local-ci <<<$/ { on = 0 }
        on && body                        { sub(/^          /, ""); print }
        on && /^[[:space:]]*run: \|$/     { body = 1 }
    ' "${ROOT}/.github/workflows/ci.yml" >"$block"
    if ! grep -qF 'scripts/local/ci' "$block"; then
        drive_cannot_look "the local-ci sentinels in .github/workflows/ci.yml enclose no run: body that mentions the drawer — the extraction is reading the wrong thing, and every arm below would judge an empty script"
    fi
    LOCAL_CI_OUT="${WORK}/local-ci.out"
    LOCAL_CI_RC=0
    (cd "$dir" && bash "$block") >"$LOCAL_CI_OUT" 2>&1 || LOCAL_CI_RC=$?
}
LOCAL_CI_OUT=""
LOCAL_CI_RC=0

case_the_workflows_optional_local_job_runs_the_products_ci_steps() {
    DRIVE_OUT=""
    local dir="${WORK}/local-ci-tree"
    rm -rf "$dir"
    mkdir -p "$dir"

    # (1) NO DRAWER — the shape this repository itself is in, and the one that
    # must cost nothing but a printed line.
    run_local_ci_block "$dir"
    if [ "$LOCAL_CI_RC" != "0" ] || ! grep -qF 'this product declares no CI steps of its own' "$LOCAL_CI_OUT"; then
        bad "an absent drawer gave exit ${LOCAL_CI_RC} without the printed skip line: $(tr '\n' '|' <"$LOCAL_CI_OUT")"
        return
    fi
    ok "no scripts/local/ci/ — the step prints why it did nothing and exits 0"

    # (2) TWO STEPS, IN NAME ORDER. Numbered the way a product orders them.
    mkdir -p "${dir}/scripts/local/ci"
    printf '#!/usr/bin/env bash\necho "STEP ONE"\n' >"${dir}/scripts/local/ci/10-one.sh"
    printf '#!/usr/bin/env bash\necho "STEP TWO"\n' >"${dir}/scripts/local/ci/20-two.sh"
    chmod +x "${dir}/scripts/local/ci/10-one.sh" "${dir}/scripts/local/ci/20-two.sh"
    run_local_ci_block "$dir"
    if [ "$LOCAL_CI_RC" != "0" ]; then
        bad "two green product steps gave exit ${LOCAL_CI_RC}: $(tr '\n' '|' <"$LOCAL_CI_OUT")"
        return
    fi
    local order
    order="$(grep -E '^STEP (ONE|TWO)$' "$LOCAL_CI_OUT" | tr '\n' ' ')"
    if [ "$order" != "STEP ONE STEP TWO " ]; then
        bad "the steps did not run in name order (got: '${order}')"
        return
    fi
    if ! grep -qF '2 product CI step(s) ran; exit 0' "$LOCAL_CI_OUT"; then
        bad "the step does not say how many product steps it ran: $(tr '\n' '|' <"$LOCAL_CI_OUT")"
        return
    fi
    ok "two product steps ran in name order and the job counted them"

    # (3) A RED STEP IS THE JOB'S EXIT, AND EVERY STEP STILL RUNS. One failure
    # per run is the cost this system refuses to keep paying.
    printf '#!/usr/bin/env bash\necho "STEP ONE"\nexit 1\n' >"${dir}/scripts/local/ci/10-one.sh"
    run_local_ci_block "$dir"
    if [ "$LOCAL_CI_RC" != "1" ]; then
        bad "a red product step gave exit ${LOCAL_CI_RC}, want 1: $(tr '\n' '|' <"$LOCAL_CI_OUT")"
        return
    fi
    if ! grep -qF 'STEP TWO' "$LOCAL_CI_OUT"; then
        bad "the job stopped at the first red — the step after it never ran"
        return
    fi
    ok "a red step is the job's exit 1 and the steps after it still run"

    # (4) NOT EXECUTABLE IS COULD-NOT-LOOK. A step this job cannot run is one it
    # would silently skip.
    printf '#!/usr/bin/env bash\necho "STEP ONE"\n' >"${dir}/scripts/local/ci/10-one.sh"
    chmod -x "${dir}/scripts/local/ci/20-two.sh"
    run_local_ci_block "$dir"
    if [ "$LOCAL_CI_RC" != "2" ] || ! grep -qF '20-two.sh is not executable' "$LOCAL_CI_OUT"; then
        bad "a non-executable product step gave exit ${LOCAL_CI_RC} without naming the file: $(tr '\n' '|' <"$LOCAL_CI_OUT")"
        return
    fi
    ok "a step with no +x is exit 2 naming the file"

    # (5) THE JOB IS WIRED BEHIND THE VERDICT, and that is a text-read of the
    # one line a `run:` body cannot show: whatever a product does here is
    # downstream of the gate's own verdict, exactly as `images` is.
    local job_needs
    job_needs="$(awk '
        /^  local:$/ { on = 1; next }
        on && /^  [a-z]/ { on = 0 }
        on && /^    needs: / { print $2; exit }
    ' "${ROOT}/.github/workflows/ci.yml")"
    if [ "$job_needs" != "verdict" ]; then
        bad "the workflow's local job declares needs: '${job_needs:-none}', want verdict — a product's CI step must not run beside the gate it depends on"
        return
    fi
    ok "the local job declares needs: verdict, so a product's own steps run behind the gate's verdict"
}

# --- section 9: a template-only case says so, and the skip is counted ---------
#
# A child drive that sources the REAL preamble from this checkout and carries
# two cases, one template-only. The answer to "has this tree folded" is handed
# to the child the way `_declared_namespace(doc=)` is handed a drawer on the
# Python side — `DRIVE__NAMESPACE_READ=1` and `DRIVE__NAMESPACE` set after the
# source — because reading this checkout's own declaration would make this
# case's expectation depend on which shape it happens to stand in. The live
# reader is proved by the fourth arm: an engine that cannot answer is exit 2.
TO_OUT=""
TO_RC=0
run_template_only_child() { # <arm> <namespace|-> [uv shim dir]
    local arm="$1" ns="$2" shim="${3:-}" child="${WORK}/to-child-$1.sh"
    TO_OUT="${WORK}/to-child-$1.out"
    TO_RC=0
    cat >"$child" <<CHILD
#!/usr/bin/env bash
set -euo pipefail
cd "${ROOT}"
. scripts/tests/drive_preamble.sh
if [ "${ns}" != "-" ]; then
    DRIVE__NAMESPACE_READ=1
    DRIVE__NAMESPACE="${ns}"
fi
RAN=""
case_the_templates_own_count() {
    template_only "it types the template's own rule count" || return 0
    RAN="\${RAN} template"
}
case_any_tree() {
    RAN="\${RAN} any"
}
case_the_templates_own_count
case_any_tree
echo "child: ran[\${RAN# }] · \${DRIVE_SKIPPED} skipped"
if [ "${arm}" = "no-reason" ]; then template_only ""; fi
drive_finished
exit 0
CHILD
    (
        if [ -n "$shim" ]; then
            PATH="${shim}:${PATH}"
            export PATH
        fi
        bash "$child"
    ) >"$TO_OUT" 2>&1 || TO_RC=$?
}

case_a_template_only_case_runs_on_the_template_and_is_counted_skipped_on_a_product() {
    DRIVE_OUT=""
    # (1) THE TEMPLATE: no namespace declared. Both cases run, nothing is
    #     counted, and nothing new is printed — not even a zero.
    run_template_only_child template ""
    DRIVE_OUT="$TO_OUT"
    if [ "$TO_RC" != "0" ] || ! grep -qxF 'child: ran[template any] · 0 skipped' "$TO_OUT"; then
        bad "on a tree with no namespace the template-only case did not run (exit ${TO_RC})"
        return
    fi
    if grep -q 'skipped  \|template-only' "$TO_OUT"; then
        bad "the template printed a skip line — its output is no longer byte-identical to a drive with no template-only case"
        return
    fi
    ok "the template runs the template-only case, counts nothing and prints nothing new"

    # (2) A PRODUCT: the case returns before it asserts, the skip is printed
    #     with the Python side's sentence and counted, the other case still
    #     runs, the epilogue repeats the reason above the summary, and the exit
    #     status does not move.
    run_template_only_child product acme
    DRIVE_OUT="$TO_OUT"
    local sentence="case_the_templates_own_count — template-only: this tree declares rule_id_namespace acme; it types the template's own rule count"
    if [ "$TO_RC" != "0" ]; then
        bad "a template-only skip moved the exit status to ${TO_RC} — a skip is not a status"
        return
    fi
    if ! grep -qxF 'child: ran[any] · 1 skipped' "$TO_OUT"; then
        bad "on a product the template-only case ran, or the other case did not, or the count is not 1"
        return
    fi
    if ! grep -qxF "  skipped  ${sentence}" "$TO_OUT"; then
        bad "the skip line does not name the case and the reason in the one sentence"
        return
    fi
    if ! grep -qxF "to-child-product: 1 skipped, by kind:" "$TO_OUT" ||
        ! grep -qxF "  template-only — the template's own properties, which this tree cannot pose:" "$TO_OUT" ||
        ! grep -qxF "    ${sentence}" "$TO_OUT"; then
        bad "the epilogue did not print the count and the reason under its kind's heading"
        return
    fi
    ok "a product skips the template-only case with the one sentence, counts it, runs the rest, and exits 0"

    # (3) A SKIP WITH NO REASON is exit 2: a skip nobody can audit.
    run_template_only_child no-reason acme
    DRIVE_OUT="$TO_OUT"
    if [ "$TO_RC" != "2" ] || ! grep -qF 'with no reason' "$TO_OUT"; then
        bad "template_only with no reason gave exit ${TO_RC}, want 2 naming the missing reason"
        return
    fi
    ok "template_only with no reason is exit 2"

    # (4) THE LIVE READER FAILS CLOSED. An engine that cannot answer is
    #     could-not-look — never "template" (which would red a product) and
    #     never "product" (which would skip the template's own cases).
    local shim="${WORK}/template-only-shim"
    mkdir -p "$shim"
    printf '#!/usr/bin/env bash\necho "uv: the engine would not start" >&2\nexit 1\n' >"${shim}/uv"
    chmod +x "${shim}/uv"
    run_template_only_child reader-broken - "$shim"
    DRIVE_OUT="$TO_OUT"
    if [ "$TO_RC" != "2" ] || ! grep -qF 'did not answer' "$TO_OUT"; then
        bad "a reader that could not ask the engine gave exit ${TO_RC}, want 2"
        return
    fi
    ok "an engine that cannot answer is exit 2, never a guess in either direction"
}

# Every skip carries a kind, and the report groups by it: an environment skip
# is never filed under the template-only heading. A kind outside the three is
# exit 2.
case_a_skip_carries_its_kind_and_the_report_groups_by_it() {
    local child="${WORK}/kinds_child.sh" out="${WORK}/kinds.out" rc=0
    DRIVE_OUT="$out"
    new_scratch_repo "${WORK}/kinds-repo"
    cat >"$child" <<CHILD
#!/usr/bin/env bash
cd "${WORK}/kinds-repo" || exit 9
. "${PREAMBLE}" || exit 2
DRIVE__NAMESPACE_READ=1
DRIVE__NAMESPACE=acme
case_mine() { template_only "it types the template's own count" || return 0; }
case_db() { drive_skip environment "no database on this machine" || return 0; }
case_world() { drive_skip could-not-pose "the fixture would not build" || return 0; }
case_held() { ok "held"; }
case_odd() { drive_skip whimsy "not a kind" || return 0; }
drive_run_case case_mine
drive_run_case case_db
drive_run_case case_world
drive_run_case case_held
[ "\${KINDS_ODD:-}" != "go" ] || drive_run_case case_odd
drive_finished
CHILD
    bash "$child" >"$out" 2>&1 || rc=$?
    local want
    want="kinds_child: 3 skipped, by kind:
  template-only — the template's own properties, which this tree cannot pose:
    case_mine — template-only: this tree declares rule_id_namespace acme; it types the template's own count
  environment — what this machine's environment cannot reach:
    case_db — environment: no database on this machine
  could-not-pose — a world the case could not build:
    case_world — could-not-pose: the fixture would not build
kinds_child: 1 passed · 0 failed · 3 skipped"
    if [ "$rc" != "0" ] || [ "$(tail -n 8 "$out")" != "$want" ]; then
        bad "three skips of three kinds exited ${rc}, and the report's tail is not the three groups above the summary"
        return
    fi
    ok "a skip of each kind is reported under its own heading, above the one summary, and moves no status"
    rc=0
    env KINDS_ODD=go bash "$child" >"$out" 2>&1 || rc=$?
    if [ "$rc" != "2" ] || ! grep -qF "drive_skip: 'whimsy' is not a kind" "$out"; then
        bad "a skip of an unknown kind exited ${rc}, want 2 naming it"
        return
    fi
    ok "a skip of a kind outside template-only, environment and could-not-pose is exit 2"
    DRIVE_OUT=""
}

# --- section 7: one header window, two readers ------------------------------
#
# A shell file's header is its first N lines, and two readers read it there:
# `scripts/gate_ledger.sh` reads a drive's `# drives:` / `# cites:` lines within
# `DRIVE_MARKER_LINES`, and `quality/roads.py` reads a whole script's road marker
# within `HEADER_WINDOW`. The Python census cannot import a shell constant, so
# the two are typed twice, and THIS is the pin its comment points at: a window
# widened on one side only would let a marker at line 41 be read by one reader
# and not the other. Each constant is read from its own source file, never
# retyped here.

# header_window_value <file> <name> — the integer `<name>=N` or `<name> = N`
# assigns at column zero, or nothing when the file holds no such line.
header_window_value() {
    awk -v name="$2" '
        $0 ~ ("^" name "[ \t]*=[ \t]*[0-9]+[ \t]*($|#)") {
            sub("^" name "[ \t]*=[ \t]*", "")
            sub("[^0-9].*$", "")
            print
            exit
        }
    ' "$1"
}

# header_window_pin <roads.py> <gate_ledger.sh> — exit 0 when the two windows
# are equal, 1 when they differ, 2 when either cannot be read; one line saying which.
header_window_pin() {
    local census ledger
    [ -r "$1" ] && [ -r "$2" ] || {
        echo "cannot read $1 or $2"
        return 2
    }
    census="$(header_window_value "$1" HEADER_WINDOW)"
    ledger="$(header_window_value "$2" DRIVE_MARKER_LINES)"
    if [ -z "$census" ] || [ -z "$ledger" ]; then
        echo "HEADER_WINDOW='${census}' in $1, DRIVE_MARKER_LINES='${ledger}' in $2 — one is not an integer assignment at column zero"
        return 2
    fi
    if [ "$census" != "$ledger" ]; then
        echo "HEADER_WINDOW=${census} but DRIVE_MARKER_LINES=${ledger}"
        return 1
    fi
    echo "both ${census}"
    return 0
}

case_the_road_census_and_the_drive_markers_read_one_header_window() {
    DRIVE_OUT=""
    local roads="${ROOT}/quality/roads.py" ledger="${ROOT}/scripts/gate_ledger.sh"
    local said rc=0
    said="$(header_window_pin "$roads" "$ledger")" || rc=$?
    case "$rc" in
    0) ok "quality/roads.py and scripts/gate_ledger.sh read one header window: ${said}" ;;
    1)
        bad "the two header windows differ: ${said} — a marker between them is read by one reader and not the other"
        return
        ;;
    *) drive_cannot_look "the header-window pin could not read its two constants: ${said}" ;;
    esac

    # THE PIN CAN FAIL: a scratch copy of the census with its window widened by
    # one, and a scratch copy with the constant gone, each through the same pin.
    local plant="${WORK}/roads-window-plant.py"
    sed 's/^HEADER_WINDOW = .*/HEADER_WINDOW = 41/' "$roads" >"$plant" ||
        drive_cannot_look "could not write the widened-window plant"
    grep -q '^HEADER_WINDOW = 41$' "$plant" ||
        drive_cannot_look "the widened-window plant did not take — there is no HEADER_WINDOW line to widen"
    rc=0
    said="$(header_window_pin "$plant" "$ledger")" || rc=$?
    if [ "$rc" != "1" ]; then
        bad "a census window of 41 against a ledger window of 40 gave exit ${rc} (${said}), want 1"
        return
    fi
    ok "a widened census window is refused: ${said}"

    sed '/^HEADER_WINDOW = /d' "$roads" >"$plant" ||
        drive_cannot_look "could not write the missing-window plant"
    rc=0
    said="$(header_window_pin "$plant" "$ledger")" || rc=$?
    if [ "$rc" != "2" ]; then
        bad "a census with no HEADER_WINDOW gave exit ${rc} (${said}), want 2 — an unread constant is could-not-look"
        return
    fi
    ok "a census with no window to read is could-not-look, never a pass"
}

# --- section 10: the harness a drive carries, once ----------------------------
#
# THE HARNESS IS DRIVEN THROUGH A DRIVE OF ITS OWN MAKING: a child that sources
# the real preamble, carries no harness of its own, and is asked the four
# things a verifier and the gate ask a drive — name your cases, run them, run
# just this one, and what is your verdict. Its scratch is this file's WORK; it
# stands in a scratch repository so the tripwire it is born with fingerprints
# that and nothing here.

# write_harness_child <path> — a drive on the preamble's harness: two cases, one
# ok and one bad over a 30-line capture, a heredoc that PLANTS a third case
# (which is not this child's), and nothing else.
write_harness_child() {
    cat >"$1" <<CHILD
#!/usr/bin/env bash
cd "${HARNESS_REPO}" || exit 9
. "${PREAMBLE}" || exit 2
set -euo pipefail
CAPTURE="\${TMPDIR:-/tmp}/harness-child-capture.\$\$"
drive_at_exit 'rm -f "\$CAPTURE"'
i=1
while [ "\$i" -le 30 ]; do echo "capture line \$i"; i=\$((i + 1)); done >"\$CAPTURE"
case_alpha() { ok "alpha held"; }
case_beta() { bad "beta did not hold" "\$CAPTURE"; }
cat >/dev/null <<'PLANT'
case_planted() {
PLANT
drive_run_case case_alpha
drive_run_case case_beta
drive_finished
CHILD
    chmod +x "$1"
}

# harness_run <out> <args…> — run the child, leaving its transcript in <out>
# and its status in HARNESS_RC.
harness_run() {
    local out="$1"
    shift
    HARNESS_RC=0
    bash "$HARNESS_CHILD" "$@" >"$out" 2>&1 || HARNESS_RC=$?
}

HARNESS_RC=0
HARNESS_REPO="${WORK}/harness-repo"
HARNESS_CHILD="${WORK}/harness_child.sh"

case_the_harness_lists_runs_and_summarises_a_drive_once() {
    local out="${WORK}/harness.out" first last summaries
    new_scratch_repo "$HARNESS_REPO"
    write_harness_child "$HARNESS_CHILD"
    DRIVE_OUT="$out"

    # (1) `--list`: each case once, by definition, the planted one not at all —
    # and readable through a pipe, which is what a list is for.
    harness_run "$out" --list
    if [ "$HARNESS_RC" != "0" ] || [ "$(cat "$out")" != "case_alpha
case_beta" ]; then
        bad "--list exited ${HARNESS_RC} and did not print exactly case_alpha and case_beta, once each"
        return
    fi
    first="$(bash "$HARNESS_CHILD" --list | sed -n '1p')"
    if [ "$first" != "case_alpha" ]; then
        bad "a piped --list did not read: its first line was '${first}'"
        return
    fi
    ok "--list names each case once, by definition, never the heredoc's planted case, and reads through a pipe"

    # (2) the whole run: one summary, in the one grammar, last; the counted red
    # is the status; the red shows the LAST 25 lines of its capture.
    harness_run "$out"
    summaries="$(grep -cE '^harness_child: [0-9]+ passed · [0-9]+ failed · [0-9]+ skipped$' "$out" || true)"
    last="$(sed -n '$p' "$out")"
    if [ "$HARNESS_RC" != "1" ] || [ "$summaries" != "1" ] ||
        [ "$last" != "harness_child: 1 passed · 1 failed · 0 skipped" ]; then
        bad "the run exited ${HARNESS_RC} with ${summaries} summary line(s), last line '${last}' — want 1, one, and the summary last"
        return
    fi
    if ! grep -qxF '             | capture line 30' "$out" || ! grep -qxF '             | capture line 6' "$out" ||
        grep -qxF '             | capture line 5' "$out"; then
        bad "the red did not show the last 25 lines of its capture (lines 6 to 30, and not 5)"
        return
    fi
    ok "the run ends with one summary in the one grammar, a counted red is exit 1, and the red shows the capture's last 25 lines"

    # (3) `--case`: exactly that case, and its summary says so.
    harness_run "$out" --case case_alpha
    if [ "$HARNESS_RC" != "0" ] || grep -q 'case_beta' "$out" ||
        [ "$(sed -n '$p' "$out")" != "harness_child: 1 passed · 0 failed · 0 skipped" ]; then
        bad "--case case_alpha exited ${HARNESS_RC} or ran case_beta too"
        return
    fi
    ok "--case runs exactly the case it names"

    # (3b) a repeated `--case` runs exactly that set, counted in the one summary.
    harness_run "$out" --case case_beta --case case_alpha
    if [ "$HARNESS_RC" != "1" ] || ! grep -qF 'alpha held' "$out" || ! grep -qF 'beta did not hold' "$out" ||
        [ "$(sed -n '$p' "$out")" != "harness_child: 1 passed · 1 failed · 0 skipped" ]; then
        bad "--case case_beta --case case_alpha exited ${HARNESS_RC} or did not run and count both"
        return
    fi
    ok "a repeated --case runs exactly the named set and the summary counts them"

    # (4) the two refusals: a case the drive does not define, and an argument
    # nobody declared. Both exit 2 before any case runs — never a silent run.
    harness_run "$out" --case case_planted
    if [ "$HARNESS_RC" != "2" ] || ! grep -qF -- "--case 'case_planted' names no case this drive defines" "$out" ||
        grep -q 'alpha held' "$out"; then
        bad "--case naming the heredoc's planted case exited ${HARNESS_RC}, want 2 naming it and no case run"
        return
    fi
    harness_run "$out" --lsit
    if [ "$HARNESS_RC" != "2" ] || ! grep -qF "unknown argument '--lsit'" "$out"; then
        bad "a mistyped flag exited ${HARNESS_RC}, want 2 naming it"
        return
    fi
    ok "a case the drive does not define and a mistyped flag are both exit 2, named, with nothing run"

    # (5) `--list` over a drive with no case is a refusal, never an empty pass.
    local caseless="${WORK}/caseless_child.sh"
    printf '#!/usr/bin/env bash\ncd "%s" || exit 9\n. "%s" || exit 2\nok "no case"\ndrive_finished\n' \
        "$HARNESS_REPO" "$PREAMBLE" >"$caseless"
    HARNESS_RC=0
    bash "$caseless" --list >"$out" 2>&1 || HARNESS_RC=$?
    if [ "$HARNESS_RC" != "2" ] || ! grep -qF 'defines no `case_` function — nothing to list' "$out"; then
        bad "--list over a drive with no case exited ${HARNESS_RC}, want 2 with the one sentence"
        return
    fi
    ok "--list over a drive that defines no case is exit 2 with one sentence"
    DRIVE_OUT=""
}

# A peer's branch created mid-run is an excused tripwire delta, printed; the
# summary still comes after it and stays the last line.
case_the_summary_stays_last_when_the_tripwire_excuses_a_delta() {
    local repo="${WORK}/excused-repo" child="${WORK}/excused_child.sh" out="${WORK}/excused.out" rc=0 last
    DRIVE_OUT="$out"
    new_scratch_repo "$repo"
    cat >"$child" <<CHILD
#!/usr/bin/env bash
cd "${repo}" || exit 9
. "${PREAMBLE}" || exit 2
case_peer() {
    git -C "${repo}" worktree add -q -b peer-mid-run "${WORK}/excused-peer" >/dev/null 2>&1 || exit 9
    ok "a peer worktree made its branch mid-run"
}
drive_run_case case_peer
drive_finished
CHILD
    bash "$child" >"$out" 2>&1 || rc=$?
    last="$(sed -n '$p' "$out")"
    if [ "$rc" != "0" ] || ! grep -qF 'excused: refs/heads/peer-mid-run — created by a peer worktree' "$out" ||
        [ "$last" != "excused_child: 1 passed · 0 failed · 0 skipped" ]; then
        bad "an excused delta exited ${rc} with last line '${last}' — want 0, the excused line printed, and the summary last"
        return
    fi
    ok "an excused tripwire delta prints before the one summary line, which stays last"
    DRIVE_OUT=""
}

# The four readers a run is asserted by: each counts through ok/bad in both
# directions, and a capture they cannot read is exit 2.
case_the_four_run_readers_count_both_ways_and_refuse_an_empty_capture() {
    local child="${WORK}/readers_child.sh" out="${WORK}/readers.out" rc=0
    DRIVE_OUT="$out"
    new_scratch_repo "${WORK}/readers-repo"
    cat >"$child" <<CHILD
#!/usr/bin/env bash
cd "${WORK}/readers-repo" || exit 9
. "${PREAMBLE}" || exit 2
DRIVE_OUT="${WORK}/readers-capture.txt"
printf 'the subject said its piece\\n' >"\$DRIVE_OUT"
RUN="the subject" RC=3
case_held() { holds "two equal" a a; exits 3; says "said its piece"; says_not "refused"; }
case_not() { holds "two unequal" a b; exits 0; says "refused"; says_not "said its piece"; }
case_empty() { : >"\$DRIVE_OUT"; says_not "anything"; }
drive_run_case case_held
drive_run_case case_not
[ "\${READERS_EMPTY:-}" != "go" ] || drive_run_case case_empty
drive_finished
CHILD
    bash "$child" >"$out" 2>&1 || rc=$?
    if [ "$rc" != "1" ] || [ "$(sed -n '$p' "$out")" != "readers_child: 4 passed · 4 failed · 0 skipped" ] ||
        ! grep -qxF "  ok       case_held — the subject: exit 3" "$out" ||
        ! grep -qxF "  FAILED   case_not — two unequal — wanted 'a', got 'b'" "$out" ||
        ! grep -qxF '  FAILED   case_not — the subject: says "said its piece" and must not' "$out"; then
        bad "the four readers over a held and an unheld run exited ${rc}, want 1 with 4 passed and 4 failed, each line labelled by \$RUN"
        return
    fi
    ok "holds, exits, says and says_not count a pass and a fail each, labelled by \$RUN"
    rc=0
    env READERS_EMPTY=go bash "$child" >"$out" 2>&1 || rc=$?
    if [ "$rc" != "2" ] || ! grep -qF 'which is EMPTY' "$out"; then
        bad "says_not over an empty capture exited ${rc}, want 2 naming the empty capture"
        return
    fi
    ok "says_not over an empty capture is exit 2, never a pass nobody looked at"
    DRIVE_OUT=""
}

case_the_preamble_refuses_a_shell_that_is_not_bash() {
    local out="${WORK}/not-bash.out" rc=0
    DRIVE_OUT="$out"
    new_scratch_repo "${WORK}/not-bash-repo"
    printf 'cd "%s" || exit 9\n. "%s"\necho "the sh reached its first case"\n' "${WORK}/not-bash-repo" "$PREAMBLE" >"${WORK}/not_bash.sh"
    sh "${WORK}/not_bash.sh" >"$out" 2>&1 || rc=$?
    if [ "$rc" != "2" ] || grep -qF 'the sh reached its first case' "$out" ||
        ! grep -qE 'must run under bash|bash is in POSIX mode' "$out"; then
        bad "a drive run by sh exited ${rc}; want 2 with the preamble's one sentence and nothing after it"
        return
    fi
    ok "sh on a drive is exit 2 with the preamble's sentence ($(sed -n '1p' "$out"))"
    DRIVE_OUT=""
}

case_the_scratch_repo_is_on_main_with_an_author_and_one_base_commit() {
    local repo="${WORK}/scratch-made" count branch who
    DRIVE_OUT=""
    SCRATCH_MADE="$repo"
    drive_scratch_repo SCRATCH_MADE builder
    branch="$(git -C "$repo" symbolic-ref --short HEAD)"
    count="$(git -C "$repo" rev-list --count HEAD)"
    who="$(git -C "$repo" log -1 --format='%an <%ae>')"
    if [ "$branch" != "main" ] || [ "$count" != "1" ] || [ "$who" != "builder <builder@example.invalid>" ]; then
        bad "drive_scratch_repo made branch '${branch}', ${count} commit(s), author '${who}' — want main, 1, builder <builder@example.invalid>"
        return
    fi
    ok "drive_scratch_repo: on main, one base commit, the author it was handed"
    local out="${WORK}/scratch-refused.out" rc=0
    (
        RELATIVE_REPO="relative/path"
        drive_scratch_repo RELATIVE_REPO
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" != "2" ] || ! grep -qF 'is relative' "$out" || [ -e relative/path ]; then
        bad "a relative scratch path exited ${rc}, want 2 from the belt, and nothing made" "$out"
        return
    fi
    ok "a relative scratch path is refused by the belt before git is handed it"
}

case_a_drive_with_its_own_list_arm_keeps_its_own_parse_and_summary() {
    # A DRIVE NOT YET MIGRATED IS UNTOUCHED: its own `--list)` arm answers, and
    # its own summary is the only one — this is what lets the migration go one
    # drive at a time.
    local child="${WORK}/legacy_child.sh" out="${WORK}/legacy.out" rc=0 n
    DRIVE_OUT="$out"
    new_scratch_repo "${WORK}/legacy-repo"
    cat >"$child" <<CHILD
#!/usr/bin/env bash
cd "${WORK}/legacy-repo" || exit 9
. "${PREAMBLE}" || exit 2
case "\${1:-}" in
"") ;;
--list) echo "LEGACY LIST"; exit 0 ;;
esac
PASSED=0
ok() { PASSED=\$((PASSED + 1)); }
case_one() { ok; }
case_one
echo "legacy_child: \${PASSED} passed, 0 failed"
drive_finished
CHILD
    bash "$child" --list >"$out" 2>&1 || rc=$?
    if [ "$rc" != "0" ] || [ "$(cat "$out")" != "LEGACY LIST" ]; then
        bad "a drive with its own --list arm was answered by the preamble (exit ${rc})"
        return
    fi
    rc=0
    bash "$child" >"$out" 2>&1 || rc=$?
    n="$(grep -c 'passed' "$out" || true)"
    if [ "$rc" != "0" ] || [ "$n" != "1" ] || ! grep -qxF 'legacy_child: 1 passed, 0 failed' "$out"; then
        bad "a drive with its own harness printed ${n} summary line(s) (exit ${rc}) — the preamble's must stand back"
        return
    fi
    ok "a drive that still carries its own --list arm and ok keeps its own parse and its own one summary"
    DRIVE_OUT=""
}

# --- section 10: the census — no drive writes the harness itself --------------
#
# THE POPULATION: every `scripts/tests/test_*.sh` and `deploy/tests/test_*.sh`
# the index carries. THE CLASS: a definition, in the drive's own code (a
# heredoc's body is a plant, not the drive), of a helper the preamble ships
# (`ok`, `bad`, `holds`, `exits`, `says`, `says_not`, `says_before` by name; `cannot_look`,
# `run_case`, `fresh*`, `clone_into` as its drive_ forms), or a `--list)` arm of
# its own. THE VALVE: `# harness: <reason>` on the line directly above a
# definition — honoured only for a name the preamble does not ship verbatim. THE RATCHET: the copies are FOUND, never typed, and their count
# may only fall — over HARNESS_COPIES_RECORDED is a red naming every copy; under
# it prints the lower number to record.
#
# does-not-cover: a helper under a name this census does not read (`is`,
# `same`, `differs` — the equality assertion under other names); a copy
# deleted while another is added (the count holds); a drive that does not
# source the preamble at all.
HARNESS_HELPERS_RE='^[[:space:]]*(function[[:space:]]+)?(ok|bad|holds|exits|says_not|says_before|says|cannot_look|run_case|fresh_repo|fresh_checkout|fresh|clone_into)[[:space:]]*\(\)'
# The names the preamble ships verbatim: a valve above one of these is no excuse.
HARNESS_SHIPPED=" ok bad holds exits says says_not says_before "
HARNESS_LIST_ARM_RE='^[[:space:]]*["'\'']?--list["'\'']?[[:space:]]*(\)|[|])'

# harness_copies_in <file> — `<helper>` per copy the file defines in its own
# code, or `valved <helper> <reason>` for one carrying the valve above it.
harness_copies_in() {
    local file="$1" text prev="" name
    while IFS= read -r text; do
        text="${text#*$'\t'}"
        if [[ "$text" =~ $HARNESS_HELPERS_RE ]]; then
            name="${BASH_REMATCH[2]}"
            if [[ "$HARNESS_SHIPPED" != *" ${name} "* ]] &&
                [[ "$prev" =~ ^[[:space:]]*#[[:space:]]*harness:[[:space:]]*([^[:space:]].*)$ ]]; then
                printf 'valved %s %s\n' "$name" "${BASH_REMATCH[1]}"
            else
                printf '%s\n' "$name"
            fi
        elif [[ "$text" =~ $HARNESS_LIST_ARM_RE ]]; then
            printf '%s\n' "--list"
        fi
        prev="$text"
    done < <(drive__code_lines "$file")
}

# harness_census <root> — sets HARNESS_COPIES, HARNESS_COUNT, HARNESS_DRIVES, HARNESS_VALVED, HARNESS_NONE and HARNESS_CLEAN.
# A drive whose only copies are the five run readers is still ON the harness (HARNESS_CLEAN).
harness_census() {
    local root="$1" drive helper pop copies core
    HARNESS_VALVED=0
    HARNESS_CLEAN=""
    HARNESS_NONE=0
    HARNESS_COPIES=""
    pop="$(cd "$root" && git ls-files 'scripts/tests/test_*.sh' 'deploy/tests/test_*.sh')" ||
        drive_cannot_look "git ls-files did not answer in ${root} — the drive population is unknown"
    HARNESS_DRIVES="$(printf '%s\n' "$pop" | grep -c . || true)"
    [ "$HARNESS_DRIVES" -gt 0 ] || drive_cannot_look "no drive under ${root} — a census over nothing asserts nothing"
    while IFS= read -r drive; do
        [ -n "$drive" ] || continue
        copies="$(harness_copies_in "${root}/${drive}" | LC_ALL=C sort -u)"
        core=0
        [ -n "$copies" ] || HARNESS_NONE=$((HARNESS_NONE + 1))
        while IFS= read -r helper; do
            case "$helper" in
            '') ;;
            valved\ *) HARNESS_VALVED=$((HARNESS_VALVED + 1)) ;;
            holds | exits | says | says_not | says_before) HARNESS_COPIES="${HARNESS_COPIES}${drive}|${helper}"$'\n' ;;
            *)
                HARNESS_COPIES="${HARNESS_COPIES}${drive}|${helper}"$'\n'
                core=1
                ;;
            esac
        done <<<"$copies"
        [ "$core" = 1 ] || HARNESS_CLEAN="${HARNESS_CLEAN}${drive}"$'\n'
    done <<<"$pop"
    HARNESS_COPIES="$(printf '%s' "$HARNESS_COPIES" | LC_ALL=C sort)"
    HARNESS_COUNT="$(printf '%s' "$HARNESS_COPIES" | grep -c . || true)"
}

# The recorded count, from the census's own printed line; only ever lowered.
HARNESS_COPIES_RECORDED=33

# harness_ratchet <recorded> — 0 at or under the recorded count (printing the
# lower number to record when under), 1 over it, after a `bad` naming every copy.
harness_ratchet() {
    local recorded="$1"
    if [ "$HARNESS_COUNT" -gt "$recorded" ]; then
        bad "harness copies grew to ${HARNESS_COUNT}, over the recorded ${recorded} — use the preamble's (\`drive_cannot_look\`, \`ok\`, \`bad\`, \`drive_run_case\`, \`drive_scratch_repo\`, its --list and --case) and delete the copy, or say why with \`# harness: <reason>\` above a helper the preamble does not ship. Every copy:
$(printf '%s\n' "$HARNESS_COPIES" | sed 's/^/             copy /')"
        return 1
    fi
    if [ "$HARNESS_COUNT" -lt "$recorded" ]; then
        echo "  note     harness copies fell to ${HARNESS_COUNT} from the recorded ${recorded} — record it: HARNESS_COPIES_RECORDED=${HARNESS_COUNT}"
    fi
    return 0
}

case_no_drive_defines_the_harness_itself() {
    local drives
    DRIVE_OUT=""
    harness_census "$ROOT"
    harness_ratchet "$HARNESS_COPIES_RECORDED" || return 0
    drives="$(printf '%s\n' "$HARNESS_COPIES" | cut -d'|' -f1 | LC_ALL=C sort -u | grep -c . || true)"
    ok "harness copies: ${HARNESS_COUNT} (recorded ${HARNESS_COPIES_RECORDED}) in ${drives} drives; ${HARNESS_VALVED} valved; ${HARNESS_NONE} of ${HARNESS_DRIVES} drives carry none, $(printf '%s' "$HARNESS_CLEAN" | grep -c . || true) are on the harness"

    # THE PLANT, in a scratch tree of its own and with no row anywhere: a drive
    # that defines `cannot_look()` is named and counted; the same definition
    # inside a heredoc, and one under the valve, are not.
    local plant="${WORK}/harness-plant"
    new_scratch_repo "$plant"
    mkdir -p "${plant}/scripts/tests"
    printf '#!/usr/bin/env bash\ncannot_look() {\n    exit 2\n}\n' >"${plant}/scripts/tests/test_planted.sh"
    printf '#!/usr/bin/env bash\ncat <<%s\nok() {\n%s\n# harness: a helper the preamble does not ship, said so\nfresh() {\n    :\n}\n' "'X'" "X" >"${plant}/scripts/tests/test_heredoc_and_valve.sh"
    git -C "$plant" add scripts >/dev/null 2>&1 && git -C "$plant" commit -q -m plant >/dev/null 2>&1 ||
        drive_cannot_look "the harness plant would not commit in ${plant}"
    harness_census "$plant"
    if [ "$HARNESS_COPIES" != "scripts/tests/test_planted.sh|cannot_look" ] || [ "$HARNESS_VALVED" != "1" ]; then
        bad "the planted cannot_look() was not the one copy found (got '${HARNESS_COPIES}', ${HARNESS_VALVED} valved)"
        return
    fi
    # A valve above a name the preamble ships verbatim excuses nothing.
    printf '#!/usr/bin/env bash\n# harness: an assertion over the capture\nsays() {\n    :\n}\n' >"${plant}/scripts/tests/test_valved_says.sh"
    git -C "$plant" add scripts >/dev/null 2>&1 && git -C "$plant" commit -q -m says >/dev/null 2>&1 ||
        drive_cannot_look "the valved-says plant would not commit in ${plant}"
    harness_census "$plant"
    if [ "$HARNESS_COPIES" != "scripts/tests/test_planted.sh|cannot_look
scripts/tests/test_valved_says.sh|says" ] || [ "$HARNESS_VALVED" != "1" ]; then
        bad "a valved says() was not counted as a copy (got '${HARNESS_COPIES}', ${HARNESS_VALVED} valved)"
        return
    fi
    git -C "$plant" rm -q scripts/tests/test_valved_says.sh >/dev/null 2>&1 && git -C "$plant" commit -q -m unsays >/dev/null 2>&1 ||
        drive_cannot_look "the valved-says plant would not come out of ${plant}"
    harness_census "$plant"
    local saved_failed="$FAILED" said
    said="$(harness_ratchet 0)" && {
        bad "one copy over a recorded 0 did not red"
        return
    }
    FAILED="$saved_failed"
    case "$said" in
    *"copy scripts/tests/test_planted.sh|cannot_look"*) ;;
    *)
        bad "the ratchet's red did not name the planted copy: ${said}"
        return
        ;;
    esac
    said="$(harness_ratchet 2)" || {
        bad "one copy under a recorded 2 was red: ${said}"
        return
    }
    case "$said" in
    *"HARNESS_COPIES_RECORDED=1"*) ;;
    *)
        bad "one copy under a recorded 2 did not print the lower number to record: ${said}"
        return
        ;;
    esac
    ok "a planted cannot_look() is found with no row typed and reds over the count, naming it; a heredoc's ok() and a valved helper are not copies; under the count prints the number to record"
}

# summary_census <root> <drives> — each drive lists once and ends with one summary; sets SUMMARY_ON, returns 1 after a `bad`.
# An exit 2 carrying `drive_cannot_reach`'s `environment:` sentence is an environment skip, never a red.
SUMMARY_ON=0
summary_census() {
    local root="$1" drives="$2" drive name out listing lines unique first last summary rc reach
    SUMMARY_ON=0
    while IFS= read -r drive; do
        [ -n "$drive" ] || continue
        name="$(basename "$drive" .sh)"
        out="${WORK}/on-harness-${name}.out"
        listing="${WORK}/on-harness-${name}.list"
        bash "${root}/${drive}" --list >"$listing" 2>&1 || {
            bad "${drive} --list did not exit 0" "$listing"
            return 1
        }
        lines="$(grep -c . "$listing" || true)"
        unique="$(LC_ALL=C sort -u "$listing" | grep -c . || true)"
        first="$(sed -n '1p' "$listing")"
        # Never this case asking for itself: a drive whose first case is this
        # one is asked for its second.
        [ "$first" != "case_every_drive_on_the_harness_lists_once_and_prints_one_summary" ] || first="$(sed -n '2p' "$listing")"
        if [ "$lines" = "0" ] || [ "$lines" != "$unique" ]; then
            bad "${drive} lists ${lines} line(s) for ${unique} case(s) — a case listed twice, or none" "$listing"
            return 1
        fi
        rc=0
        bash "${root}/${drive}" --case "$first" >"$out" 2>&1 || rc=$?
        if [ "$rc" = "2" ]; then
            reach="$(grep -F "!! ${name}: environment: " "$out" || true)"
            if [ -n "$reach" ]; then
                reach="${reach%%$'\n'*}"
                drive_skip environment "${drive} --case ${first} could not reach its world: ${reach#"!! ${name}: environment: "}" || true
                continue
            fi
        fi
        if [ "$rc" != "0" ]; then
            bad "${drive} --case ${first} exited ${rc}, not 0" "$out"
            return 1
        fi
        last="$(sed -n '$p' "$out")"
        summary="$(grep -E "^${name}: [0-9]+ passed · [0-9]+ failed · [0-9]+ skipped\$" "$out" || true)"
        if [ -z "$summary" ] || [ "$summary" != "$last" ]; then
            bad "${drive} --case ${first} does not end with the preamble's one summary line" "$out"
            return 1
        fi
        SUMMARY_ON=$((SUMMARY_ON + 1))
    done <<<"$drives"
    return 0
}

case_every_drive_on_the_harness_lists_once_and_prints_one_summary() {
    # THE SEAM USED: every drive the census finds carrying no copy is ON the
    # harness, so it lists each case once and, run for its first case alone,
    # ends with the preamble's one summary line. Asked of the drive itself, by
    # `--case`, so the property is the drive's and not a reading of its text.
    local pending
    DRIVE_OUT=""
    harness_census "$ROOT"
    summary_census "$ROOT" "$HARNESS_CLEAN" || return 0
    if [ "$SUMMARY_ON" = "0" ]; then
        bad "no drive is on the harness — the property below would hold of nothing"
        return
    fi
    pending="$(printf '%s\n' "$HARNESS_COPIES" | cut -d'|' -f1 | LC_ALL=C sort -u | grep -c . || true)"
    ok "summary grammar: ${SUMMARY_ON} drive(s) on the harness list each case once and end with the one summary; ${pending} carry copies pending their migration"
}

# The census's own plant: a drive that cannot reach its environment is a skip
# by kind; a drive that refuses for any other reason is still red.
case_an_environment_refusal_is_a_skip_in_the_summary_census_and_any_other_refusal_is_red() {
    local plant="${WORK}/reach-plant" before
    DRIVE_OUT=""
    new_scratch_repo "$plant"
    mkdir -p "${plant}/scripts/tests"
    printf '#!/usr/bin/env bash\ncd "$(dirname "$0")/../.." || exit 9\n. "%s" || exit 2\ndrive_cannot_reach "no database on this machine"\ncase_one() { ok "one"; }\ndrive_run_case case_one\ndrive_finished\n' \
        "$PREAMBLE" >"${plant}/scripts/tests/test_unreachable.sh"
    printf '#!/usr/bin/env bash\ncd "$(dirname "$0")/../.." || exit 9\n. "%s" || exit 2\ndrive_cannot_look "a broken fixture"\ncase_one() { ok "one"; }\ndrive_run_case case_one\ndrive_finished\n' \
        "$PREAMBLE" >"${plant}/scripts/tests/test_broken.sh"
    before="$DRIVE_SKIPPED"
    if ! summary_census "$plant" "scripts/tests/test_unreachable.sh" >"${WORK}/reach-plant.out" 2>&1; then
        bad "an environment refusal was red in the summary census" "${WORK}/reach-plant.out"
        return
    fi
    if [ "$DRIVE_SKIPPED" != "$((before + 1))" ] || ! grep -qF 'environment: scripts/tests/test_unreachable.sh --case case_one could not reach its world: no database on this machine' "${WORK}/reach-plant.out"; then
        bad "an environment refusal was not counted as one skip of kind environment naming the drive" "${WORK}/reach-plant.out"
        return
    fi
    DRIVE_SKIPPED="$before"
    DRIVE_SKIP_REASONS=""
    local saved_failed="$FAILED" saved_passed="$PASSED"
    if summary_census "$plant" "scripts/tests/test_broken.sh" >"${WORK}/reach-plant.out" 2>&1 ||
        ! grep -qF 'scripts/tests/test_broken.sh --case case_one exited 2, not 0' "${WORK}/reach-plant.out"; then
        FAILED="$saved_failed"
        PASSED="$saved_passed"
        bad "a refusal that is not the environment sentence was not red in the summary census" "${WORK}/reach-plant.out"
        return
    fi
    FAILED="$saved_failed"
    PASSED="$saved_passed"
    ok "an environment refusal (drive_cannot_reach) is one environment skip naming the drive; any other exit 2 is still red"
}

# A case that returns having recorded nothing is FAILED `nothing asserted`.
case_a_case_that_asserts_nothing_is_failed_nothing_asserted() {
    local child="${WORK}/hollow_child.sh" out="${WORK}/hollow.out" rc=0
    DRIVE_OUT="$out"
    new_scratch_repo "${WORK}/hollow-repo"
    cat >"$child" <<CHILD
#!/usr/bin/env bash
set -uo pipefail
cd "${WORK}/hollow-repo" || exit 9
. "${PREAMBLE}" || exit 2
case_hollow() { an_undefined_helper "the assertion it meant to make"; }
case_held() { ok "this one asserted"; }
case_skipped() { drive_skip environment "a skip is a record" || return 0; }
drive_run_case case_hollow
drive_run_case case_held
drive_run_case case_skipped
drive_finished
CHILD
    bash "$child" >"$out" 2>&1 || rc=$?
    if [ "$rc" != "1" ] || [ "$(sed -n '$p' "$out")" != "hollow_child: 1 passed · 1 failed · 1 skipped" ] ||
        ! grep -qF "  FAILED   case_hollow — nothing asserted" "$out" ||
        grep -qF "  FAILED   case_held" "$out" || grep -qF "  FAILED   case_skipped" "$out"; then
        bad "a case calling an undefined helper exited ${rc}, want 1 with case_hollow FAILED 'nothing asserted' and the asserting and skipping cases untouched"
        return
    fi
    ok "a case that called an undefined helper is FAILED 'nothing asserted', exit 1; a case that asserted or skipped is not"
    DRIVE_OUT=""
}

# A case whose only assertion ran in a subshell is FAILED `nothing asserted`, and the hint names the subshell.
case_a_subshell_only_assertion_is_named_in_the_hint() {
    local child="${WORK}/subshell_child.sh" out="${WORK}/subshell.out" rc=0
    DRIVE_OUT="$out"
    new_scratch_repo "${WORK}/subshell-repo"
    cat >"$child" <<CHILD
#!/usr/bin/env bash
set -uo pipefail
cd "${WORK}/subshell-repo" || exit 9
. "${PREAMBLE}" || exit 2
case_in_a_subshell() { ( ok "counted in a subshell that dies" ); }
drive_run_case case_in_a_subshell
drive_finished
CHILD
    bash "$child" >"$out" 2>&1 || rc=$?
    holds "a subshell-only case's run status" "1" "$rc"
    says "FAILED   case_in_a_subshell — nothing asserted"
    says "inside a subshell"
    DRIVE_OUT=""
}

# A whole run that recorded nothing is exit 2 for a tracked drive; a planted child (untracked) is exempt.
case_a_whole_run_that_asserted_nothing_is_refused_unless_planted() {
    local repo="${WORK}/wholerun-repo" out="${WORK}/wholerun.out" rc=0
    DRIVE_OUT="$out"
    new_scratch_repo "$repo"
    mkdir -p "${repo}/scripts/tests"
    cat >"${repo}/scripts/tests/test_empty.sh" <<CHILD
#!/usr/bin/env bash
set -uo pipefail
cd "\$(dirname "\$0")/../.." || exit 9
. "${PREAMBLE}" || exit 2
case_never_called() { ok "not run"; }
drive_finished
CHILD
    git -C "$repo" add scripts/tests/test_empty.sh
    git -C "$repo" commit -q -m "a registered drive that runs no case"
    bash "${repo}/scripts/tests/test_empty.sh" >"$out" 2>&1 || rc=$?
    holds "a tracked drive that ran no case" "2" "$rc"
    says "the run asserted nothing"
    cp "${repo}/scripts/tests/test_empty.sh" "${repo}/scripts/tests/test_planted.sh"
    rc=0
    bash "${repo}/scripts/tests/test_planted.sh" >"$out" 2>&1 || rc=$?
    holds "the same drive planted (untracked) — a parent's child, exempt" "0" "$rc"
    says "test_planted: 0 passed · 0 failed · 0 skipped"
    DRIVE_OUT=""
}

# says_before orders two needles; an absent needle is a bad under pipefail, never a dead drive.
case_says_before_orders_two_lines_and_an_absent_needle_is_a_bad() {
    local child="${WORK}/before_child.sh" out="${WORK}/before.out" rc=0
    DRIVE_OUT="$out"
    new_scratch_repo "${WORK}/before-repo"
    cat >"$child" <<CHILD
#!/usr/bin/env bash
set -euo pipefail
cd "${WORK}/before-repo" || exit 9
. "${PREAMBLE}" || exit 2
DRIVE_OUT="${WORK}/before-capture.txt"
printf 'the fold ran\\nthe gate ran\\n' >"\$DRIVE_OUT"
case_order() {
    says_before "the fold ran" "the gate ran"
    says_before "the gate ran" "the fold ran"
    says_before "never printed" "the gate ran"
    ok "the case ran on past the absent needle"
}
drive_run_case case_order
drive_finished
CHILD
    bash "$child" >"$out" 2>&1 || rc=$?
    if [ "$rc" != "1" ] || [ "$(sed -n '$p' "$out")" != "before_child: 2 passed · 2 failed · 0 skipped" ] ||
        ! grep -qxF '  ok       case_order — "the fold ran" (line 1) before "the gate ran" (line 2)' "$out" ||
        ! grep -qxF '  FAILED   case_order — "never printed" (line absent) is not before "the gate ran" (line 2)' "$out"; then
        bad "says_before over an ordered, a reversed and an absent pair exited ${rc}, want 1 with 2 passed and 2 failed and the case run to its end"
        return
    fi
    ok "says_before passes the ordered pair, fails the reversed one, and an absent needle is a bad under pipefail"
    DRIVE_OUT=""
}

# drive_checkout_mirror carries the working tree, the branch and main; a plant there leaves the source untouched.
case_the_checkout_mirror_carries_the_working_tree_and_a_plant_there_stays_there() {
    local src="${WORK}/mirror-src" mirror="${WORK}/mirror-dst" out="${WORK}/mirror.out" rc=0 before after
    DRIVE_OUT="$out"
    new_scratch_repo "$src"
    printf 'gone\n' >"${src}/deleted.txt"
    printf '.env\nignored.txt\n' >"${src}/.git/info/exclude"
    git -C "$src" add deleted.txt && git -C "$src" commit -q -m two
    git -C "$src" checkout -q -b rung-x
    printf 'committed on the rung\n' >"${src}/rung.txt"
    git -C "$src" add rung.txt && git -C "$src" commit -q -m three
    git -C "$src" update-ref refs/remotes/origin/main "$(git -C "$src" rev-parse main)"
    printf 'edited, uncommitted\n' >"${src}/f.txt"
    rm "${src}/deleted.txt"
    printf 'untracked\n' >"${src}/new.txt"
    printf 'IGNORED\n' >"${src}/ignored.txt"
    printf 'DATABASE_NAME=pinned\n' >"${src}/.env"
    before="$(cd "$src" && git status --porcelain=v1 --ignored | LC_ALL=C sort)"
    (
        cd "$src" || exit 9
        drive_checkout_mirror mirror "$src"
        cp "${mirror}/f.txt" "${WORK}/mirror-f.txt"
        printf 'planted\n' >"${mirror}/planted.txt"
        printf 'severed\n' >"${mirror}/f.txt"
    ) >"$out" 2>&1 || rc=$?
    after="$(cd "$src" && git status --porcelain=v1 --ignored | LC_ALL=C sort)"
    holds "the mirror built" 0 "$rc"
    holds "the mirror's branch" rung-x "$(git -C "$mirror" symbolic-ref --short HEAD 2>&1)"
    holds "the mirror's HEAD" "$(git -C "$src" rev-parse HEAD)" "$(git -C "$mirror" rev-parse HEAD 2>&1)"
    holds "the mirror's main" "$(git -C "$src" rev-parse main)" "$(git -C "$mirror" rev-parse main 2>&1)"
    holds "the mirror's origin/main" "$(git -C "$src" rev-parse origin/main)" "$(git -C "$mirror" rev-parse origin/main 2>&1)"
    holds "an uncommitted edit carried" "edited, uncommitted" "$(cat "${WORK}/mirror-f.txt" 2>&1)"
    holds "an untracked file carried" untracked "$(cat "${mirror}/new.txt" 2>&1)"
    holds "a deletion carried" absent "$([ -e "${mirror}/deleted.txt" ] && echo present || echo absent)"
    holds "an ignored file other than .env is not carried" absent "$([ -e "${mirror}/ignored.txt" ] && echo present || echo absent)"
    holds ".env is a copy" "DATABASE_NAME=pinned" "$([ -L "${mirror}/.env" ] && echo link || cat "${mirror}/.env")"
    holds "the source's working tree is unmoved by the plant" "$before" "$after"
    holds "the source's f.txt is its own" "edited, uncommitted" "$(cat "${src}/f.txt")"
    DRIVE_OUT=""
}

# --- run ----------------------------------------------------------------------

drive_run_case case_the_fingerprint_records_a_sha_for_every_ref
drive_run_case case_a_peer_worktree_branch_created_mid_run_does_not_red_the_tripwire
drive_run_case case_a_peer_worktrees_commit_mid_run_does_not_red_the_tripwire
drive_run_case case_a_merge_into_main_by_the_primary_worktree_does_not_red_a_linked_drive
drive_run_case case_a_reap_of_a_merged_peer_branch_mid_run_does_not_red_the_tripwire
drive_run_case case_a_branch_with_no_worktree_still_reds_the_tripwire
drive_run_case case_a_moved_ref_with_no_worktree_still_reds_the_tripwire
drive_run_case case_a_vanished_unmerged_ref_still_reds
drive_run_case case_a_peer_worktree_removed_mid_run_still_reds
drive_run_case case_this_checkouts_head_moving_still_reds
drive_run_case case_the_base_ref_reader_resolves_main_then_origin_main_then_refuses
drive_run_case case_a_drive_that_exits_inside_a_case_is_exit_2_on_any_bash
drive_run_case case_every_variable_the_workflow_sets_is_accounted_for
drive_run_case case_a_body_spelling_three_undeclared_paths_is_named_whole_and_refused_at_the_hook
drive_run_case case_the_product_env_keys_drawer_declares_product_keys_only
drive_run_case case_the_workflows_optional_local_job_runs_the_products_ci_steps
drive_run_case case_a_template_only_case_runs_on_the_template_and_is_counted_skipped_on_a_product
drive_run_case case_a_skip_carries_its_kind_and_the_report_groups_by_it
drive_run_case case_the_road_census_and_the_drive_markers_read_one_header_window
drive_run_case case_the_harness_lists_runs_and_summarises_a_drive_once
drive_run_case case_the_summary_stays_last_when_the_tripwire_excuses_a_delta
drive_run_case case_the_four_run_readers_count_both_ways_and_refuse_an_empty_capture
drive_run_case case_the_preamble_refuses_a_shell_that_is_not_bash
drive_run_case case_the_scratch_repo_is_on_main_with_an_author_and_one_base_commit
drive_run_case case_a_drive_with_its_own_list_arm_keeps_its_own_parse_and_summary
drive_run_case case_no_drive_defines_the_harness_itself
drive_run_case case_every_drive_on_the_harness_lists_once_and_prints_one_summary
drive_run_case case_an_environment_refusal_is_a_skip_in_the_summary_census_and_any_other_refusal_is_red
drive_run_case case_a_case_that_asserts_nothing_is_failed_nothing_asserted
drive_run_case case_a_subshell_only_assertion_is_named_in_the_hint
drive_run_case case_a_whole_run_that_asserted_nothing_is_refused_unless_planted
drive_run_case case_says_before_orders_two_lines_and_an_absent_needle_is_a_bad
drive_run_case case_the_checkout_mirror_carries_the_working_tree_and_a_plant_there_stays_there
drive_finished
