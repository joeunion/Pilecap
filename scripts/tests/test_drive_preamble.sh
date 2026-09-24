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
# cites: scripts/local/env_keys scripts/local/ci .claude/agents .claude/skills CLAUDE.md
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

# >>> one case, by name >>>
# `--case <name>` runs exactly that case and nothing else. The seam exists so
# rule 60's drawer census can prove ONE PLANT PER DRAWER through the drive that
# already owns the property, rather than re-implementing the drawer's reader —
# a second implementation of a reader is a second opinion about it. A name this
# file does not define is exit 2, never a silent run of nothing.
ONLY_CASE=""
run_case() {
    [ -z "$ONLY_CASE" ] || [ "$1" = "$ONLY_CASE" ] || return 0
    "$@"
}
# <<< one case, by name <<<
case "${1:-}" in
"") ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
--case)
    [ -n "${2:-}" ] || {
        echo "!! --case needs a case name; --list names them" >&2
        exit 2
    }
    grep -q "^${2}() {" "$0" || {
        echo "!! --case: test_drive_preamble.sh defines no case named '${2}'; --list names them" >&2
        exit 2
    }
    ONLY_CASE="$2"
    ;;
*)
    echo "!! unknown argument '$1': test_drive_preamble.sh takes nothing, --list or --case <name>" >&2
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
    CURRENT=case_the_base_ref_reader_resolves_main_then_origin_main_then_refuses
    # FOUR SHAPES AND FOUR ANSWERS, and the two that matter are the ones
    # no drive had ever been in: the runner's (no local `main`), and nothing at
    # all. The reader's whole job is that the second is a REFUSAL rather than an
    # empty string a caller then interpolates into `"${base}:path"`.
    local src="${WORK}/base-src" clone="${WORK}/base-clone" bare="${WORK}/base-bare"
    local err="${WORK}/base-err.txt" got rc
    OUT="$err"
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
        cannot_look "could not build the runner-shaped clone in ${clone}"
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
        cannot_look "could not build the second runner-shaped clone in ${bare}"
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
    OUT=""
}

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

case_a_body_spelling_three_undeclared_paths_is_named_whole_and_refused_at_the_hook() {
    CURRENT=case_a_body_spelling_three_undeclared_paths_is_named_whole_and_refused_at_the_hook
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
        cannot_look "could not clone this checkout into ${clone}"
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
    # WIRED INTO THE HOOK'S TIER: the call sits inside the goalpost-census leg's
    # body, which `--fast` runs — so no new leg, and `--list-legs` does not move.
    if awk '
        /^gate_leg_goalpost_census\(\) \{/ { inside = 1 }
        inside && /drive_keys_of_touched / { found = 1 }
        inside && /^gate_run_body goalpost-census / { exit }
        END { exit !found }
    ' "${ROOT}/scripts/check.sh"; then
        ok "check.sh's goalpost-census leg (a --fast leg) calls drive_keys_of_touched"
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
    ) >"$PRE_OUT" 2>&1 || PRE_RC=$?
}
PRE_OUT=""
PRE_RC=0

case_the_product_env_keys_drawer_declares_product_keys_only() {
    CURRENT=case_the_product_env_keys_drawer_declares_product_keys_only
    OUT=""
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
        cannot_look "the local-ci sentinels in .github/workflows/ci.yml enclose no run: body that mentions the drawer — the extraction is reading the wrong thing, and every arm below would judge an empty script"
    fi
    LOCAL_CI_OUT="${WORK}/local-ci.out"
    LOCAL_CI_RC=0
    (cd "$dir" && bash "$block") >"$LOCAL_CI_OUT" 2>&1 || LOCAL_CI_RC=$?
}
LOCAL_CI_OUT=""
LOCAL_CI_RC=0

case_the_workflows_optional_local_job_runs_the_products_ci_steps() {
    CURRENT=case_the_workflows_optional_local_job_runs_the_products_ci_steps
    OUT=""
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
    CURRENT=case_a_template_only_case_runs_on_the_template_and_is_counted_skipped_on_a_product
    OUT=""
    # (1) THE TEMPLATE: no namespace declared. Both cases run, nothing is
    #     counted, and nothing new is printed — not even a zero.
    run_template_only_child template ""
    OUT="$TO_OUT"
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
    #     runs, the epilogue repeats the reason under the summary, and the exit
    #     status does not move.
    run_template_only_child product acme
    OUT="$TO_OUT"
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
    if ! grep -qxF "to-child-product: 1 skipped — template-only cases this tree cannot pose:" "$TO_OUT" ||
        ! grep -qxF "    ${sentence}" "$TO_OUT"; then
        bad "the epilogue did not print the count and the reason under the summary"
        return
    fi
    ok "a product skips the template-only case with the one sentence, counts it, runs the rest, and exits 0"

    # (3) A SKIP WITH NO REASON is exit 2: a skip nobody can audit.
    run_template_only_child no-reason acme
    OUT="$TO_OUT"
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
    OUT="$TO_OUT"
    if [ "$TO_RC" != "2" ] || ! grep -qF 'did not answer' "$TO_OUT"; then
        bad "a reader that could not ask the engine gave exit ${TO_RC}, want 2"
        return
    fi
    ok "an engine that cannot answer is exit 2, never a guess in either direction"
}

# --- run ----------------------------------------------------------------------

run_case case_the_fingerprint_records_a_sha_for_every_ref
run_case case_a_peer_worktree_branch_created_mid_run_does_not_red_the_tripwire
run_case case_a_peer_worktrees_commit_mid_run_does_not_red_the_tripwire
run_case case_a_merge_into_main_by_the_primary_worktree_does_not_red_a_linked_drive
run_case case_a_reap_of_a_merged_peer_branch_mid_run_does_not_red_the_tripwire
run_case case_a_branch_with_no_worktree_still_reds_the_tripwire
run_case case_a_moved_ref_with_no_worktree_still_reds_the_tripwire
run_case case_a_vanished_unmerged_ref_still_reds
run_case case_a_peer_worktree_removed_mid_run_still_reds
run_case case_this_checkouts_head_moving_still_reds
run_case case_the_base_ref_reader_resolves_main_then_origin_main_then_refuses
run_case case_every_drive_under_tests_is_invoked_by_the_gate
run_case case_the_drive_is_registered_in_the_gate
run_case case_a_registered_drive_that_cannot_look_is_exit_2_not_a_pass
run_case case_every_variable_the_workflow_sets_is_accounted_for
run_case case_every_registered_drive_declares_what_it_drives
run_case case_a_body_spelling_three_undeclared_paths_is_named_whole_and_refused_at_the_hook
run_case case_the_product_env_keys_drawer_declares_product_keys_only
run_case case_the_workflows_optional_local_job_runs_the_products_ci_steps
run_case case_a_template_only_case_runs_on_the_template_and_is_counted_skipped_on_a_product

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
