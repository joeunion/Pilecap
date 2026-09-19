#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made.
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
# drives: .github/workflows/ci.yml scripts/check.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/tests/
# The drive for THE REAL-REPOSITORY TRIPWIRE — `drive_repo_fingerprint` and
# `drive_tripwire_check` in `scripts/tests/drive_preamble.sh` §3.
#
#   ./scripts/tests/test_drive_preamble.sh          run every case
#   ./scripts/tests/test_drive_preamble.sh --list   name them and stop
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
#   4. IT DRIVES §3 AND NOTHING ELSE of the preamble. The other five sections —
#      the git-location neutralisation, the scratch-path belt, the CI strip, the
#      finished-sentinel and the signal bridge — have their own coverage in the
#      drives that use them, and this file adds none.
#   5. THE REGISTRATION CASES READ `scripts/check.sh`, they do not run it. A
#      drive cannot run a nested gate inside a gate, so the three blocks are
#      EXTRACTED by their sentinels and run against planted drives. That proves
#      the block's exit map and that the invocation sits inside the selftest
#      leg; it does not prove the leg itself is reached, which is the gate's own
#      `leg`/`leg_done` machinery and has its own coverage.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_drive_preamble: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It is the file under drive. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_drive_preamble: $*" >&2
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
    echo "!! unknown argument '$1': test_drive_preamble.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH — the whole file is about git refs"

ROOT="$PWD"
PREAMBLE="${ROOT}/scripts/tests/drive_preamble.sh"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-preamble-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

CURRENT=""
OUT=""
ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ] && [ -s "$OUT" ]; then
        sed 's/^/             | /' "$OUT"
    fi
    FAILED=$((FAILED + 1))
}

# A throwaway repository with one commit on `main`. `git init` then
# `symbolic-ref`, rather than `init -b`, because the flag is newer than the git
# a fresh machine may carry and the default branch name is a config a laptop
# may have set to anything.
new_scratch_repo() {
    local d="$1"
    mkdir -p "$d"
    git -C "$d" init -q
    git -C "$d" symbolic-ref HEAD refs/heads/main
    git -C "$d" config user.email "drive@example.invalid"
    git -C "$d" config user.name "drive"
    git -C "$d" config commit.gpgsign false
    printf 'one\n' >"${d}/f.txt"
    git -C "$d" add f.txt
    git -C "$d" commit -q -m "one"
}

# Run the SHIPPED preamble inside `$1`, with `$2` as the mid-run mutation, and
# leave the tripwire's own output plus a `TRIPWIRE_RC=` line in `$OUT`.
#
# The child is written to a file rather than passed with `bash -c` so the
# mutation reads as the script it is, and so `$0` gives the preamble a sensible
# DRIVE_NAME.
CHILD_N=0
run_tripwire() {
    local stand_in="$1" mutation="$2" child
    CHILD_N=$((CHILD_N + 1))
    child="${WORK}/child-${CHILD_N}.sh"
    OUT="${WORK}/child-${CHILD_N}.log"
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
    "$child" >"$OUT" 2>&1 || true
}

tripwire_rc() {
    local seen
    seen="$(grep '^TRIPWIRE_RC=' "$OUT" || true)"
    seen="${seen%%$'\n'*}"
    printf '%s' "${seen#TRIPWIRE_RC=}"
}

says() { grep -qF -- "$1" "$OUT"; }

# --- the fingerprint ----------------------------------------------------------

case_the_fingerprint_records_a_sha_for_every_ref() {
    CURRENT=case_the_fingerprint_records_a_sha_for_every_ref
    local repo="${WORK}/fp" want got
    new_scratch_repo "$repo"
    git -C "$repo" branch zzz-other
    run_tripwire "$repo" 'drive_repo_fingerprint'
    want="$(git -C "$repo" rev-parse refs/heads/main)"
    got="$(awk '$1=="ref" && $2=="refs/heads/main" { print $3 }' "$OUT")"
    if [ "$got" != "$want" ]; then
        bad "the fingerprint's main line carries '${got}', wanted the sha '${want}' — a name-only fingerprint cannot tell a reap of merged work from a reap of lost work"
        return
    fi
    got="$(awk '$1=="ref" { n++ } END { print n+0 }' "$OUT")"
    if [ "$got" != "2" ]; then
        bad "wanted 2 ref lines, got ${got}"
        return
    fi
    ok "every ref line is 'ref <name> <sha>' — 2 refs, main's sha matches rev-parse"
}

# --- the four excuses ---------------------------------------------------------

case_a_peer_worktree_branch_created_mid_run_does_not_red_the_tripwire() {
    CURRENT=case_a_peer_worktree_branch_created_mid_run_does_not_red_the_tripwire
    local repo="${WORK}/created" rc
    new_scratch_repo "$repo"
    run_tripwire "$repo" "git -C '${repo}' worktree add -q -b zzz-peer '${WORK}/created-peer' >/dev/null 2>&1"
    rc="$(tripwire_rc)"
    if [ "$rc" != "0" ]; then
        bad "a peer's worktree creation red the tripwire (rc=${rc}) — this is the flake that costs a whole gate"
        return
    fi
    if ! says "excused: refs/heads/zzz-peer — created by a peer worktree"; then
        bad "the excuse was silent; an excuse nobody can read is an excuse nobody can audit"
        return
    fi
    ok "rc=0 with 'excused: refs/heads/zzz-peer — created by a peer worktree' printed"
}

case_a_peer_worktrees_commit_mid_run_does_not_red_the_tripwire() {
    CURRENT=case_a_peer_worktrees_commit_mid_run_does_not_red_the_tripwire
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
    if ! says "excused: refs/heads/zzz-peer — checked out by a peer worktree"; then
        bad "the moved ref was not excused by name and reason"
        return
    fi
    ok "rc=0 with 'excused: refs/heads/zzz-peer — checked out by a peer worktree' printed"
}

case_a_merge_into_main_by_the_primary_worktree_does_not_red_a_linked_drive() {
    CURRENT=case_a_merge_into_main_by_the_primary_worktree_does_not_red_a_linked_drive
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
    if ! says "excused: refs/heads/main — checked out by a peer worktree"; then
        bad "main moved and was not excused by the primary worktree that holds it"
        return
    fi
    ok "rc=0 with 'excused: refs/heads/main — checked out by a peer worktree' printed"
}

case_a_reap_of_a_merged_peer_branch_mid_run_does_not_red_the_tripwire() {
    CURRENT=case_a_reap_of_a_merged_peer_branch_mid_run_does_not_red_the_tripwire
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
    if ! says "excused: refs/heads/zzz-done — merged into main, reaped"; then
        bad "the vanished ref was not excused as a reap of merged work"
        return
    fi
    ok "rc=0 with 'excused: refs/heads/zzz-done — merged into main, reaped' printed"
}

# --- the controls: the alarm still fires ---------------------------------------

case_a_branch_with_no_worktree_still_reds_the_tripwire() {
    CURRENT=case_a_branch_with_no_worktree_still_reds_the_tripwire
    local repo="${WORK}/escape" rc
    new_scratch_repo "$repo"
    run_tripwire "$repo" "git -C '${repo}' branch zzz-escape"
    rc="$(tripwire_rc)"
    if [ "$rc" != "1" ]; then
        bad "a branch created with no worktree behind it did not red (rc=${rc}) — this is the escape class the tripwire exists for"
        return
    fi
    if ! says "MUTATED THE REAL REPOSITORY"; then
        bad "no banner; a red with no sentence is a red nobody acts on"
        return
    fi
    ok "rc=1 and the banner named it — the excuse did not swallow the escape class"
}

case_a_moved_ref_with_no_worktree_still_reds_the_tripwire() {
    CURRENT=case_a_moved_ref_with_no_worktree_still_reds_the_tripwire
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
    CURRENT=case_a_vanished_unmerged_ref_still_reds
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
    if ! says "$lost"; then
        bad "the banner did not print the sha that was lost (${lost}) — the one thing a recovery needs"
        return
    fi
    ok "rc=1 and the lost sha ${lost} printed — the reap excuse is bounded by 'already on main'"
}

case_a_peer_worktree_removed_mid_run_still_reds() {
    CURRENT=case_a_peer_worktree_removed_mid_run_still_reds
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
    CURRENT=case_this_checkouts_head_moving_still_reds
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
    if ! says "HEAD"; then
        bad "the banner did not name HEAD"
        return
    fi
    ok "rc=1 — this checkout's own HEAD is nobody else's to excuse"
}

# --- the gate's registration of the drive family -------------------------------
#
# THE SECOND SUBJECT OF THIS FILE, and it belongs here for the same reason the
# tripwire does: it is a property of the family, not of any one drive. A drive
# that nothing invokes is a promise — green every time somebody remembers — and
# `scripts/check.sh` already carries the derivation that would catch one, as a
# comment nobody runs. These cases run it, and drive the exit map the gate wraps
# every drive in: 2 is could-not-look and outranks a pass, 1 is the drive's own
# red, 0 carries on.

SELFTEST_BLOCK="${WORK}/selftest-block.txt"

case_every_drive_under_tests_is_invoked_by_the_gate() {
    CURRENT=case_every_drive_under_tests_is_invoked_by_the_gate
    local present invoked missing
    OUT=""
    present="$(ls "${ROOT}"/scripts/tests/test_*.sh | xargs -n1 basename | LC_ALL=C sort)"
    invoked="$(grep -oE '\./scripts/tests/test_[a-z_]+\.sh' "${ROOT}/scripts/check.sh" |
        xargs -n1 basename | LC_ALL=C sort -u)"
    missing="$(comm -23 <(printf '%s\n' "$present") <(printf '%s\n' "$invoked"))"
    if [ -n "$missing" ]; then
        bad "invoked by no moment: $(printf '%s' "$missing" | tr '\n' ' ') — by hand is a promise, not a leg"
        return
    fi
    ok "$(printf '%s\n' "$present" | grep -c . ) drive(s) under scripts/tests/, every one invoked by scripts/check.sh"
}

case_the_drive_is_registered_in_the_gate() {
    CURRENT=case_the_drive_is_registered_in_the_gate
    local leg_at drive_at
    OUT=""
    # Inside the selftest leg, not merely somewhere in the file: a drive invoked
    # above the leg's own banner is a drive in a different leg.
    leg_at="$(grep -n '^leg selftest ' "${ROOT}/scripts/check.sh" | sed -n '1p' | cut -d: -f1)"
    drive_at="$(grep -n '^\./scripts/tests/test_gate_explain\.sh$' "${ROOT}/scripts/check.sh" | sed -n '1p' | cut -d: -f1)"
    if [ -z "$leg_at" ] || [ -z "$drive_at" ]; then
        bad "the selftest leg (${leg_at:-none}) or the gate-explain invocation (${drive_at:-none}) is not in scripts/check.sh"
        return
    fi
    if [ "$drive_at" -le "$leg_at" ]; then
        bad "the gate-explain drive is invoked at line ${drive_at}, above the selftest leg at ${leg_at}"
        return
    fi
    ok "./scripts/tests/test_gate_explain.sh is invoked at line ${drive_at}, inside the selftest leg that starts at ${leg_at}"
}

# Pull one registration block out of `scripts/check.sh` by its sentinels and run
# it against a PLANTED drive of the given exit status, in a scratch tree. The
# block the gate ships is the block that runs — a copy of its logic here would
# be a case that passes while the gate drifts.
run_registration() {
    local name="$1" planted_rc="$2" dir="${WORK}/reg-${name}-${2}"
    mkdir -p "${dir}/scripts/tests"
    sed -n "/^# >>> drive: ${name} >>>\$/,/^# <<< drive: ${name} <<<\$/p" \
        "${ROOT}/scripts/check.sh" >"$SELFTEST_BLOCK"
    {
        printf '#!/usr/bin/env bash\n'
        printf 'set -euo pipefail\n'
        cat "$SELFTEST_BLOCK"
        printf 'echo "THE LEG CARRIED ON"\n'
    } >"${dir}/block.sh"
    {
        printf '#!/usr/bin/env bash\n'
        printf 'echo "the planted drive said its piece"\n'
        printf 'exit %s\n' "$planted_rc"
    } >"${dir}/scripts/tests/test_${name}.sh"
    chmod +x "${dir}/block.sh" "${dir}/scripts/tests/test_${name}.sh"
    OUT="${WORK}/reg-${name}-${2}.log"
    REG_RC=0
    (cd "$dir" && ./block.sh) >"$OUT" 2>&1 || REG_RC=$?
}

REG_RC=0

case_a_registered_drive_that_cannot_look_is_exit_2_not_a_pass() {
    CURRENT=case_a_registered_drive_that_cannot_look_is_exit_2_not_a_pass
    local name
    for name in gate_explain drive_preamble pipefail_readers; do
        run_registration "$name" 2
        if [ "$REG_RC" != "2" ]; then
            bad "${name}: a drive that exited 2 mapped to ${REG_RC}; could-not-look outranks a pass and must not become one"
            return
        fi
        if ! grep -qF 'COULD NOT LOOK — see above.' "$OUT"; then
            bad "${name}: exit 2 with no COULD NOT LOOK sentence — the status is right and the reader is told nothing"
            return
        fi
        if grep -qF 'THE LEG CARRIED ON' "$OUT"; then
            bad "${name}: the leg continued past a could-not-look"
            return
        fi
        run_registration "$name" 1
        if [ "$REG_RC" != "1" ]; then
            bad "${name}: a drive that exited 1 mapped to ${REG_RC}"
            return
        fi
        if grep -qF 'THE LEG CARRIED ON' "$OUT"; then
            bad "${name}: the leg continued past a failed drive"
            return
        fi
        run_registration "$name" 0
        if [ "$REG_RC" != "0" ] || ! grep -qF 'THE LEG CARRIED ON' "$OUT"; then
            bad "${name}: a green drive did not let the leg carry on (rc=${REG_RC})"
            return
        fi
    done
    OUT=""
    ok "three registrations × three statuses: 2 is COULD NOT LOOK and exit 2, 1 is the drive's red, 0 carries on"
}

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
    CURRENT=case_every_variable_the_workflow_sets_is_accounted_for
    local workflow names name unlisted="" stripped="" inherited=""
    OUT=""
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

case_every_registered_drive_declares_what_it_drives() {
    CURRENT=case_every_registered_drive_declares_what_it_drives
    # THE NEGATIVE OF THE LEG'S OWN REFUSALS, and the fourth thing this census
    # out of a registration. `test_selftest_leg.sh` plants the three ways a key
    # cannot be decided and requires exit 2 for each; this case requires that no
    # drive this repository SHIPS is in any of those states — a marker in its
    # first forty lines, every declared path expanding to something in the
    # measured tree, and every checkout path its body spells covered by one of
    # them.
    #
    # THE POPULATION IS `selftest_registered_drives`, read out of
    # `scripts/check.sh` (:901-910) and never typed here: a list in this file
    # would be right on the day it was written and silent ever after.
    local names name file keyout tree listing bad_ones=""
    OUT=""
    # shellcheck source=scripts/gate_refuse.sh
    . "${ROOT}/scripts/gate_refuse.sh"
    # shellcheck source=scripts/gate_ledger.sh
    . "${ROOT}/scripts/gate_ledger.sh"
    if ! command -v drive_key >/dev/null 2>&1; then
        bad "scripts/gate_ledger.sh defines no drive_key — the declaration nothing derives is FULL_LEGS before R3-F3x"
        return
    fi
    names="$(cd "$ROOT" && awk '
        /^\.\/scripts\/tests\/test_[a-z_]+\.sh$/ {
            name = $0
            sub(/^\.\/scripts\/tests\/test_/, "", name)
            sub(/\.sh$/, "", name)
            print name
        }
    ' scripts/check.sh)"
    if [ -z "$names" ]; then
        bad "no registered drives read out of scripts/check.sh — this census has lost its subject"
        return
    fi
    tree="$(cd "$ROOT" && gate_measured_tree)" || tree=""
    if [ -z "$tree" ]; then
        cannot_look "the measured tree could not be read — every key below would be undecidable for the wrong reason"
    fi
    listing="${WORK}/tree-listing.txt"
    (cd "$ROOT" && git ls-tree -r "$tree") >"$listing" 2>/dev/null || true
    if [ ! -s "$listing" ]; then
        cannot_look "git ls-tree -r ${tree} produced nothing"
    fi
    for name in $names; do
        file="${ROOT}/scripts/tests/test_${name}.sh"
        if [ ! -f "$file" ]; then
            bad_ones="${bad_ones}
  ${name}: registered and not in scripts/tests/"
            continue
        fi
        keyout="$(cd "$ROOT" && drive_key "scripts/tests/test_${name}.sh" "$tree" "$listing")" || true
        case "$keyout" in
        ok\ drive-v1:*) ;;
        *) bad_ones="${bad_ones}
  ${name}: ${keyout#err }" ;;
        esac
    done
    if [ -n "$bad_ones" ]; then
        bad "drive(s) whose key the leg could not decide — each is exit 2 on every full gate:${bad_ones}"
        return
    fi
    ok "$(printf '%s\n' "$names" | grep -c .) registered drive(s), each with a \`# drives:\` line that keys cleanly against tree ${tree:0:12}…"
}

# --- run ----------------------------------------------------------------------

case_the_fingerprint_records_a_sha_for_every_ref
case_a_peer_worktree_branch_created_mid_run_does_not_red_the_tripwire
case_a_peer_worktrees_commit_mid_run_does_not_red_the_tripwire
case_a_merge_into_main_by_the_primary_worktree_does_not_red_a_linked_drive
case_a_reap_of_a_merged_peer_branch_mid_run_does_not_red_the_tripwire
case_a_branch_with_no_worktree_still_reds_the_tripwire
case_a_moved_ref_with_no_worktree_still_reds_the_tripwire
case_a_vanished_unmerged_ref_still_reds
case_a_peer_worktree_removed_mid_run_still_reds
case_this_checkouts_head_moving_still_reds
case_every_drive_under_tests_is_invoked_by_the_gate
case_the_drive_is_registered_in_the_gate
case_a_registered_drive_that_cannot_look_is_exit_2_not_a_pass
case_every_variable_the_workflow_sets_is_accounted_for
case_every_registered_drive_declares_what_it_drives

echo "test_drive_preamble: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! the real-repository tripwire no longer tells a drive's escape from a" >&2
    echo "   peer's ordinary work. Too loud and a gate that cries wolf is a gate" >&2
    echo "   people pass with --no-verify; too quiet and a drive can write into the" >&2
    echo "   repository it is measuring and still read green." >&2
    exit 1
fi
exit 0
