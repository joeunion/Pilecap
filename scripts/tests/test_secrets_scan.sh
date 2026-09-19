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
# drives: .secrets.baseline docs/product/queue.md scripts/check.sh scripts/db.sh scripts/kill_mine.sh scripts/queue_cited.sh scripts/secrets_scan.sh scripts/serve.sh scripts/sweep.sh scripts/tests/test_pm_merge.sh scripts/tests/test_verify_start.sh
# The drive for `scripts/secrets_scan.sh` — the `--loop` secret scan's
# changed-file derivation, its edge cases and the sentence it prints.
#
#   ./scripts/tests/test_secrets_scan.sh          run every case
#   ./scripts/tests/test_secrets_scan.sh --list   name them and stop
#
# WHY IT EXISTS. This narrowed the per-rung secret scan from the whole tree to
# the files a rung changed, which took ~40s off every `--loop` run. The entire
# risk of that trade is a DERIVATION THAT QUIETLY NARROWS TOO FAR: a set that
# comes back empty because the merge-base was wrong reads, on a terminal,
# exactly like a set that came back empty because nothing changed — green, fast,
# and vouching for nothing. Nothing else in the gate can see that. So every
# rule of the derivation is driven here, in both directions: what MUST be in the
# set, and what must NOT be, said out loud so the blind spots are declared
# rather than discovered.
#
# IT BUILDS ITS OWN REPOSITORIES, `test_pm_merge.sh`'s trick and for its reason:
# the derivation's whole subject is branches, merge-bases, deletions, renames
# and linked worktrees, and none of those can be arranged in this checkout
# without moving somebody's rung. Every derivation case runs against a throwaway
# git repository under `mktemp -d`.
#
# ONE CASE PLANTS IN THIS TREE, and it is the case that matters most: a real
# secret, in a real file, meeting the real `detect-secrets` through the real
# leg. That is the house-rules self-test's own method (plant through the live
# scope, assert it fires, restore) and it is here for the same reason — a
# derivation that is provably correct and a leg that no longer runs the scanner
# look identical from outside. The plant is restored in a trap, and the case
# asserts the tree is green BEFORE it plants, so a red left behind by anything
# else is reported as this driver's failure rather than absorbed by it.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER `detect-secrets` FINDS SECRETS, with ONE declared exception. That
#     is detect-secrets' business and its baseline's; this drives which FILES it
#     is handed and what the leg SAYS about them, and the one planted case proves
#     the scanner is still wired to the derivation at all rather than that its
#     detectors are any good. THE EXCEPTION is the baseline's own
#     `should_exclude_secret` opinion about Zitadel's `PASSWORDLESS_TYPE_*` enum
#     (see the two cases at the bottom of this file). That opinion is a
#     suppression this repository wrote, so this repository owes both halves of
#     it: the four shapes it must silence, and the plant on a `PASSWORDLESS_`
#     line that must still fire. It is asserted against the REAL baseline, which
#     is where the filter lives and therefore the one place all three scan sites
#     — `--loop`, the push-side full-tree leg, and `publish.sh`'s artifact scan —
#     inherit the same opinion.
#
# WHAT THE `PASSWORDLESS_` FILTER ITSELF DOES NOT COVER, declared here because a
# suppression's blind spots belong beside the suppression:
#
#   * A LINE WHERE THE ENUM IS FOLLOWED BY MORE TEXT. The filter matches the
#     extracted secret VALUE, anchored at both ends. In prose — a markdown
#     sentence, a `#` comment — the keyword detector can swallow the rest of the
#     line into the value, which then is not the enum and is not filtered. The
#     remedy is the inline `pragma: allowlist secret` on that line, and it is
#     already the precedent this tree uses for prose ABOUT detectors
#     (`docs/product/queue.md`, where a row carries an HTML-comment pragma for
#     exactly this reason). Widening the
#     anchor to cover it would suppress every value that merely STARTS with the
#     enum name, which is a hole rather than a filter.
#   * A `printf 'KEY=…\nOTHER=\n'` LITERAL READ AS BASE64 HIGH ENTROPY. Priced
#     and declined: the flagged string is an artifact of the `\n` escapes inside
#     a shell literal, it carries no `PASSWORDLESS_` identifier to tie a filter
#     to, and any pattern broad enough to catch it would also blind a real
#     credential written into a fixture `.env` — which is exactly the place a
#     real one would appear. `scripts/tests/test_verify_start.sh` carries the
#     inline pragma for the one instance in this tree.
#   * THE PUSH-SIDE FULL-TREE SCAN. It is one unchanged line in check.sh's
#     supply-chain leg and it reads `git ls-files`. Nothing here touches it, and
#     nothing here would notice if it were deleted — that is the census's and
#     the full gate's business.
#   * A SECRET IN A FILE THE RUNG DID NOT TOUCH. Not a gap in this driver: it is
#     the narrowing itself, and `case_a_file_the_rung_did_not_touch_is_absent`
#     asserts the blind spot exists rather than pretending it does not.
#   * FILENAMES CONTAINING NEWLINES. The derivation is NUL-separated end to end
#     and handles them; these assertions compare line by line and cannot express
#     one, so no case plants one.
set -euo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before the first git command -----------
#
# A drive run from the pre-push hook inherits an absolute `GIT_DIR` from
# `git -C <linked worktree> push`, and an inherited `GIT_DIR` OVERRIDES `-C`.
# `scripts/tests/test_pm_merge.sh` — this file's twin, the same
# `git -C "$REPO"` shape — built its whole scenario in the REAL repository
# three pushes running because of it. Every `git -C "$REPO"` below is that same
# construction. The preamble unsets the inherited environment, guards the
# scratch paths, and fingerprints this checkout so a drive that moves it says
# so. Read its header for the measured mechanism.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_secrets_scan: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_secrets_scan: $*" >&2
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
    # A mistyped flag is never a silently different run.
    echo "!! unknown argument '$1': test_secrets_scan.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -f scripts/secrets_scan.sh ] || cannot_look "scripts/secrets_scan.sh is not in this tree — there is nothing to drive"

# THE FILE ITSELF IS WHAT RUNS, not a copy: the derivation reads the repository
# containing the current working directory, so a `cd` into a scratch repo is all
# it takes to aim it. No stub, no copy, no drift.
# shellcheck source=scripts/secrets_scan.sh
. scripts/secrets_scan.sh

ROOT="$PWD"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-secrets-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"

# The plant, and its restore. Declared next to the trap so a case that dies
# mid-plant still puts the tree back.
PROBE="scripts/serve.sh"
PROBE_SAVE="${WORK}/probe.orig"
restore_probe() {
    if [ -f "$PROBE_SAVE" ]; then
        cp "$PROBE_SAVE" "$ROOT/$PROBE"
        rm -f "$PROBE_SAVE"
    fi
}
drive_at_exit 'restore_probe; rm -rf "$WORK"'

# --- the assertions ----------------------------------------------------------
CURRENT=""
LIST=""
DERIVE_RC=0
BASIS=""
OUT=""
N=0

# Aim the derivation at a directory and keep everything it said. Not a subshell:
# SECRETS_SCAN_BASIS is half of what is being asserted and a subshell would
# throw it away.
derive_in() {
    local dir="$1" label="$2" here
    CURRENT="$label"
    N=$((N + 1))
    LIST="${WORK}/list${N}"
    OUT="${WORK}/out${N}.log"
    here="$PWD"
    cd "$dir"
    SECRETS_SCAN_BASIS=""
    DERIVE_RC=0
    secrets_scan_changed_files "$LIST" >"$OUT" 2>&1 || DERIVE_RC=$?
    BASIS="$SECRETS_SCAN_BASIS"
    cd "$here"
}

# The whole leg body, for the cases about what it PRINTS. Safe in a scratch repo
# only while the change set is empty — a non-empty set reaches for `uv`, which
# has no project to resolve outside this checkout.
run_leg_in() {
    local dir="$1" label="$2" here
    CURRENT="$label"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    here="$PWD"
    cd "$dir"
    DERIVE_RC=0
    secrets_scan_loop >"$OUT" 2>&1 || DERIVE_RC=$?
    cd "$here"
}

# Aim the REAL baseline at ONE scratch file and keep its verdict. The subject is
# the baseline's opinion, not the derivation's, so this deliberately bypasses the
# change-set machinery above: a filter in `.secrets.baseline` is what all three
# scan sites read, and asserting it here asserts it for all three.
hook_on() {
    local label="$1" name="$2" path
    CURRENT="$label"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    path="${WORK}/${name}"
    cat >"$path"
    DERIVE_RC=0
    (cd "$ROOT" && uv run detect-secrets-hook --baseline .secrets.baseline "$path") \
        >"$OUT" 2>&1 || DERIVE_RC=$?
}

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    [ -n "$OUT" ] && [ -f "$OUT" ] && sed 's/^/             | /' "$OUT" | tail -20
    FAILED=$((FAILED + 1))
}

exits() {
    if [ "$DERIVE_RC" -eq "$1" ]; then
        ok "exit ${DERIVE_RC}"
    else
        bad "wanted exit $1, got ${DERIVE_RC}"
    fi
}

listed() {
    if tr '\0' '\n' <"$LIST" | grep -xF -- "$1" >/dev/null; then
        ok "the set contains ${1}"
    else
        bad "the set does NOT contain ${1} — it is $(tr '\0' '\n' <"$LIST" | tr '\n' ' ')"
    fi
}

not_listed() {
    if tr '\0' '\n' <"$LIST" | grep -xF -- "$1" >/dev/null; then
        bad "the set contains ${1} and must not — it is $(tr '\0' '\n' <"$LIST" | tr '\n' ' ')"
    else
        ok "the set does not contain ${1}"
    fi
}

set_is_empty() {
    if [ -s "$LIST" ]; then
        bad "the set is not empty — it is $(tr '\0' '\n' <"$LIST" | tr '\n' ' ')"
    else
        ok "the set is empty"
    fi
}

# A derivation with the right membership and the wrong sentence is a leg nobody
# can read, so both are asserted about the same run.
basis_says() {
    case "$BASIS" in
    *"$1"*) ok "the basis says \"$1\"" ;;
    *) bad "the basis does not say \"$1\" — it says \"${BASIS}\"" ;;
    esac
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
#   main:   base -> on-main        (untouched.txt lands in `base` and is never
#                                   touched again — the blind spot's subject)
#   rung:   forked from `base`, empty until a case commits into it
REPO=""
R=0
fresh_repo() {
    R=$((R + 1))
    REPO="${WORK}/repo${R}"
    # THE BELT, and it comes before the `mkdir` as well as before the
    # first git command. `git -C "" ...` is a no-op chdir, not a refusal: every
    # command after it lands on whatever repository this process is standing in.
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "secrets scan drive"

    echo "nobody touches this" >"$REPO/untouched.txt"
    echo "one" >"$REPO/shared.txt"
    echo "doomed" >"$REPO/doomed.txt"
    echo "before" >"$REPO/renamed_from.txt"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "base"

    echo "two" >"$REPO/shared.txt"
    git -C "$REPO" add shared.txt
    git -C "$REPO" commit -q -m "on main"
}

on_a_rung() {
    git -C "$REPO" checkout -q -b rung "$(git -C "$REPO" rev-parse HEAD~1)"
}

commit_in() {
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "$1"
}

# --- the cases ----------------------------------------------------------------

case_a_committed_change_on_a_branch_is_in_the_set() {
    fresh_repo
    on_a_rung
    echo "the rung's own work" >"$REPO/rung.txt"
    commit_in "rung work"
    derive_in "$REPO" "a file committed on the rung"
    exits 0
    listed "rung.txt"
    basis_says "1 file(s) committed on 'rung' since the merge-base with main"
}

case_a_file_the_rung_did_not_touch_is_absent() {
    # THE NARROWING ITSELF, asserted as a property rather than left implicit.
    # This is the whole cost of the narrowing and it is declared in the leg's own output
    # every run: a secret in a file nobody touched is the PUSH scan's finding.
    fresh_repo
    on_a_rung
    echo "the rung's own work" >"$REPO/rung.txt"
    commit_in "rung work"
    derive_in "$REPO" "an untouched file"
    not_listed "untouched.txt"
}

case_a_change_only_on_main_is_absent() {
    # The merge-base and not `main` itself: `shared.txt` moved on main AFTER the
    # rung forked. Diffing against the branch tip would drag it in and the leg
    # would redden a rung for somebody else's commit.
    fresh_repo
    on_a_rung
    echo "the rung's own work" >"$REPO/rung.txt"
    commit_in "rung work"
    derive_in "$REPO" "a change made on main after the fork"
    not_listed "shared.txt"
}

case_an_unstaged_edit_is_in_the_set() {
    fresh_repo
    on_a_rung
    echo "edited, not staged" >>"$REPO/untouched.txt"
    derive_in "$REPO" "an unstaged edit"
    exits 0
    listed "untouched.txt"
}

case_a_staged_new_file_is_in_the_set() {
    fresh_repo
    on_a_rung
    echo "new and staged" >"$REPO/staged.txt"
    git -C "$REPO" add staged.txt
    derive_in "$REPO" "a staged new file"
    exits 0
    listed "staged.txt"
}

case_an_untracked_file_is_absent() {
    # Parity with the push-side scan, which reads `git ls-files`. A `--loop` leg
    # reddening on a scratch file the push scan would never look at is a
    # false-positive machine, which is the cost this change exists to remove.
    fresh_repo
    on_a_rung
    echo "scratch" >"$REPO/untracked.txt"
    derive_in "$REPO" "an untracked, never-staged file"
    not_listed "untracked.txt"
}

case_on_main_only_the_working_tree_is_read() {
    fresh_repo
    echo "edited on main" >>"$REPO/untouched.txt"
    derive_in "$REPO" "standing on main"
    exits 0
    basis_says "on main itself"
    basis_says "ONLY this checkout's uncommitted changes were scanned"
    listed "untouched.txt"
    not_listed "shared.txt"
}

case_a_branch_with_no_commits_yet_reads_the_working_tree() {
    fresh_repo
    git -C "$REPO" checkout -q -b rung
    echo "not committed yet" >>"$REPO/untouched.txt"
    derive_in "$REPO" "a branch that has committed nothing"
    exits 0
    basis_says "branch 'rung' has committed nothing yet"
    listed "untouched.txt"
}

case_a_committed_deletion_is_excluded_without_erroring() {
    fresh_repo
    on_a_rung
    git -C "$REPO" rm -q doomed.txt
    commit_in "delete it"
    derive_in "$REPO" "a file the rung deleted and committed"
    exits 0
    not_listed "doomed.txt"
}

case_a_working_tree_deletion_is_excluded_without_erroring() {
    fresh_repo
    on_a_rung
    rm -f "$REPO/doomed.txt"
    derive_in "$REPO" "a file deleted but not committed"
    exits 0
    not_listed "doomed.txt"
}

case_a_rename_names_the_destination_that_exists() {
    fresh_repo
    on_a_rung
    git -C "$REPO" mv renamed_from.txt renamed_to.txt
    commit_in "rename"
    derive_in "$REPO" "a renamed file"
    exits 0
    listed "renamed_to.txt"
    not_listed "renamed_from.txt"
}

case_no_local_main_falls_back_and_says_so() {
    fresh_repo
    git -C "$REPO" checkout -q -b rung
    git -C "$REPO" branch -q -m main trunk
    echo "changed" >>"$REPO/untouched.txt"
    derive_in "$REPO" "no local refs/heads/main"
    exits 0
    basis_says "no local refs/heads/main to fork from"
    listed "untouched.txt"
}

case_a_linked_worktree_derives_against_the_shared_main() {
    # THE CASE THE BRIEF NAMED, and the one every rung actually runs in: refs
    # live in the COMMON git dir, so `refs/heads/main` must resolve from a
    # linked worktree exactly as it does from the main checkout.
    fresh_repo
    local wt="${WORK}/wt${R}"
    git -C "$REPO" worktree add -q -b rung "$wt" "$(git -C "$REPO" rev-parse HEAD~1)" 2>/dev/null ||
        cannot_look "git worktree add failed — the worktree case cannot be driven"
    echo "the rung's own work" >"$wt/rung.txt"
    git -C "$wt" add rung.txt
    git -C "$wt" commit -q -m "rung work"
    derive_in "$wt" "a linked worktree"
    exits 0
    listed "rung.txt"
    basis_says "since the merge-base with main"
    not_listed "shared.txt"
}

# --- the fork point a machine could not derive, handed to it ------------------
#
# WHAT A VERIFIER BOX ACTUALLY HOLDS. The wrapper pushes `HEAD:refs/heads/main`
# into a shallow checkout, so over there HEAD, `refs/heads/main` and the
# merge-base of the two are ONE commit: every branch in this function reads it
# as "on main itself", the uncommitted half is empty because nobody edited
# anything, and the answer is an empty change set for a rung that touched six
# files on the laptop. Five readers inherit that one answer — the `--loop`
# scope, this scan, the three changed-file censuses and the fe leg — so all five
# ask about nothing while printing a sentence that sounds like a measurement.
#
# `collapsed_box_checkout` is that machine, built rather than described: a clone
# whose `main` is the rung's tip and whose history is one commit deep.
collapsed_box_checkout() {
    local src="$1" dst="$2"
    git clone -q --depth 1 --branch rung "file://${src}" "$dst" 2>/dev/null || return 1
    git -C "$dst" branch -q -f main HEAD
    git -C "$dst" checkout -q main
    return 0
}

case_a_collapsed_checkout_derives_nothing_without_a_carried_base() {
    # THE RED THIS EXISTS FOR, kept as a case rather than as a memory: without
    # the carried base the box's answer is EMPTY and says "on main itself".
    fresh_repo
    on_a_rung
    echo "the rung's own work" >"$REPO/rung.txt"
    commit_in "rung work"
    local box="${WORK}/box${R}"
    collapsed_box_checkout "$REPO" "$box" ||
        cannot_look "could not build a depth-1 clone — the box's shape cannot be driven"
    derive_in "$box" "a depth-1 box checkout with no base handed to it"
    exits 0
    set_is_empty
    basis_says "on main itself"
}

case_a_carried_base_gives_the_collapsed_checkout_the_rungs_own_files() {
    fresh_repo
    on_a_rung
    echo "the rung's own work" >"$REPO/rung.txt"
    commit_in "rung work"
    local box="${WORK}/box${R}" base
    base="$(git -C "$REPO" merge-base rung main)"
    collapsed_box_checkout "$REPO" "$box" ||
        cannot_look "could not build a depth-1 clone — the box's shape cannot be driven"
    # THE REF THE WRAPPER SENDS, planted the way the wrapper sends it: the base
    # COMMIT has to be ON the box, because a sha it does not have is a name it
    # cannot diff against. Advertised as a ref on the source and fetched at
    # depth 1 — the same one-commit-deep shape the wrapper's mirror pushes.
    git -C "$REPO" update-ref refs/djb/base "$base"
    git -C "$box" fetch -q --depth 1 "file://${REPO}" "+refs/djb/base:refs/djb/base" 2>/dev/null ||
        cannot_look "could not plant refs/djb/base in the box clone"
    DJB_LOOP_SCOPE_BASE=refs/djb/base derive_in "$box" "a depth-1 box checkout with the fork point carried"
    exits 0
    listed "rung.txt"
    not_listed "shared.txt"
    basis_says "CARRIED fork point"
    basis_says "DJB_LOOP_SCOPE_BASE"
}

case_a_carried_base_never_overrides_a_real_fork_point() {
    # IT CAN ONLY WIDEN A THIN BASIS. On a laptop the derivation answers for
    # itself, and a knob left in the environment — exported once, forgotten,
    # inherited by every later run — must not be able to move the question.
    fresh_repo
    on_a_rung
    echo "the rung's own work" >"$REPO/rung.txt"
    commit_in "rung work"
    local first
    first="$(git -C "$REPO" rev-list --max-parents=0 HEAD)"
    git -C "$REPO" update-ref refs/djb/base "$first"
    DJB_LOOP_SCOPE_BASE=refs/djb/base derive_in "$REPO" "a real fork point with a knob set beside it"
    exits 0
    listed "rung.txt"
    not_listed "untouched.txt"
    basis_says "since the merge-base with main"
}

case_a_carried_base_that_resolves_to_nothing_is_ignored() {
    # A NAME THAT IS NOT THERE IS NOT A BASIS. An old image, a push that
    # declined to carry the ref, a typo: the run behaves exactly as it did
    # before the knob existed rather than refusing or inventing a scope.
    fresh_repo
    on_a_rung
    echo "the rung's own work" >"$REPO/rung.txt"
    commit_in "rung work"
    local box="${WORK}/box${R}"
    collapsed_box_checkout "$REPO" "$box" ||
        cannot_look "could not build a depth-1 clone — the box's shape cannot be driven"
    DJB_LOOP_SCOPE_BASE=refs/djb/base derive_in "$box" "a carried base that is not in this repository"
    exits 0
    set_is_empty
    basis_says "on main itself"
}

case_an_empty_change_set_says_nothing_was_scanned() {
    # The honesty case. A leg that looked at nothing and a leg that looked at
    # everything and found nothing print the same word — "ok" — unless one of
    # them says which it was.
    fresh_repo
    run_leg_in "$REPO" "a clean tree on main"
    exits 0
    says "NOTHING WAS SCANNED"
    says "FULL-TREE scan over \`git ls-files\` runs at push"
    says_not "scanning"
}

case_a_directory_that_is_no_repository_cannot_look() {
    local bare="${WORK}/not-a-repo"
    mkdir -p "$bare"
    # `git rev-parse --git-dir` walks upward, so this only means anything if the
    # scratch root is itself outside any repository. mktemp puts it under the
    # system temp directory, which is.
    if git -C "$bare" rev-parse --git-dir >/dev/null 2>&1; then
        cannot_look "the scratch directory is inside a git repository — the could-not-look case cannot be driven here"
    fi
    derive_in "$bare" "a directory that is not a repository"
    exits 2
    # B4.2. `derive_in` runs the derivation in THIS shell, so the global
    # `gate_refuse` sets survives the call — which is what makes this assertable at
    # all, and what the `secret scan COULD NOT DERIVE … — see above.` banner in
    # scripts/check.sh depends on. Without it that banner prints
    # `(the callee set none …)` and the reader is back to scrolling.
    CURRENT="the refusal RECORDED its cause for the leg banner to print"
    case "${GATE_LAST_REFUSAL:-}" in
    "")
        bad "GATE_LAST_REFUSAL is empty — check.sh's secret-scan banner would have to say the callee set none"
        ;;
    *"could not read a git directory here"*) ok "cause: ${GATE_LAST_REFUSAL}" ;;
    *) bad "the recorded cause is not this refusal's first line: '${GATE_LAST_REFUSAL}'" ;;
    esac
}

case_a_planted_secret_in_a_changed_file_fails_the_leg() {
    # THE END-TO-END CASE. Everything above proves a list; this proves the list
    # still reaches detect-secrets and that detect-secrets still reddens the leg.
    # It runs in THIS checkout, through the real leg, against the real baseline.
    [ -f "$ROOT/$PROBE" ] || cannot_look "$PROBE is not in this tree — the plant has nowhere to go"
    [ -f "$ROOT/.secrets.baseline" ] || cannot_look ".secrets.baseline is not in this tree"
    command -v uv >/dev/null 2>&1 || cannot_look "no uv on PATH — the real leg cannot be run"
    cp "$ROOT/$PROBE" "$PROBE_SAVE"

    run_leg_in "$ROOT" "this tree, before the plant"
    exits 0
    says "basis:"

    # A private-key header: one line, one detector, no entropy luck — and TWO
    # scanners in this repository would flag it if it were written down here,
    # detect-secrets and house rule 23, which reads all of `scripts/` and knows
    # no pragma. So the marker is ASSEMBLED rather than spelled: no line of this
    # file contains the block. That is not a dodge past rule 23, it is exactly
    # what rule 23 asserts — this tree holds no private key. The probe file
    # holds one for about a second, which is the property being driven.
    local head='-----BEGIN RSA' tail='PRIVATE KEY-----'
    printf '# %s %s\n' "$head" "$tail" >>"$ROOT/$PROBE"
    run_leg_in "$ROOT" "this tree, with a secret planted in a CHANGED file"
    if [ "$DERIVE_RC" -eq 0 ]; then
        bad "the leg passed with a planted secret in a changed file — the narrowed scan is no longer scanning"
    else
        ok "exit ${DERIVE_RC} — the planted secret reddened the leg"
    fi
    says "$PROBE"

    restore_probe
    run_leg_in "$ROOT" "this tree, after the plant was restored"
    exits 0
}

case_the_zitadel_passwordless_enum_is_not_a_secret() {
    # THE FALSE POSITIVE, in the four shapes it was reproduced in. Zitadel's
    # login policy answers `passwordlessType` with a `PASSWORDLESS_TYPE_*`
    # constant; the keyword detector sees `password` in the key and reports the
    # enum name as the secret. It is an enum in a public API, it is the same four
    # letters in every deployment, and it is not a credential in any of them.
    command -v uv >/dev/null 2>&1 || cannot_look "no uv on PATH — detect-secrets cannot be run"
    [ -f "$ROOT/.secrets.baseline" ] || cannot_look ".secrets.baseline is not in this tree"

    hook_on "the enum in a python dict literal" "policy.py" <<'EOF'
ORG_OWN_POLICY = {
    "passwordlessType": "PASSWORDLESS_TYPE_ALLOWED",
}
EOF
    exits 0

    hook_on "the enum as a python constant" "constant.py" <<'EOF'
PASSWORDLESS_TYPE_ALLOWED = "PASSWORDLESS_TYPE_ALLOWED"
EOF
    exits 0

    hook_on "the enum in a json fixture" "policy.json" <<'EOF'
{"policy": {"passwordlessType": "PASSWORDLESS_TYPE_NOT_ALLOWED"}}
EOF
    exits 0

    hook_on "the enum in a yaml document" "policy.yaml" <<'EOF'
passwordlessType: PASSWORDLESS_TYPE_ALLOWED
EOF
    exits 0
}

case_a_real_secret_on_a_passwordless_line_still_fires() {
    # THE CANARY, and the reason the filter above is a filter and not a hole. A
    # suppression is only defensible while something proves it did not suppress
    # the thing it was aimed near. The key is ASSEMBLED from two halves for the
    # same reason the private-key marker above is: no line of this file may
    # contain a credential, and two scanners in this repository would say so.
    local akia='AKIA' rest='IOSFODNN7EXAMPLE'
    hook_on "a real key on a PASSWORDLESS_ line" "canary.py" <<EOF
PASSWORDLESS_TYPE_SIGNING_KEY = "${akia}${rest}"
EOF
    if [ "$DERIVE_RC" -eq 0 ]; then
        bad "a planted key on a PASSWORDLESS_ line did NOT fire — the filter is a hole"
    else
        ok "exit ${DERIVE_RC} — the planted key still fired"
    fi
    says "AWS Access Key"
}

case_a_committed_change_on_a_branch_is_in_the_set
case_a_file_the_rung_did_not_touch_is_absent
case_a_change_only_on_main_is_absent
case_an_unstaged_edit_is_in_the_set
case_a_staged_new_file_is_in_the_set
case_an_untracked_file_is_absent
case_on_main_only_the_working_tree_is_read
case_a_branch_with_no_commits_yet_reads_the_working_tree
case_a_committed_deletion_is_excluded_without_erroring
case_a_working_tree_deletion_is_excluded_without_erroring
case_a_rename_names_the_destination_that_exists
case_no_local_main_falls_back_and_says_so
case_a_linked_worktree_derives_against_the_shared_main
case_an_empty_change_set_says_nothing_was_scanned
case_a_collapsed_checkout_derives_nothing_without_a_carried_base
case_a_carried_base_gives_the_collapsed_checkout_the_rungs_own_files
case_a_carried_base_never_overrides_a_real_fork_point
case_a_carried_base_that_resolves_to_nothing_is_ignored
case_a_directory_that_is_no_repository_cannot_look
case_a_planted_secret_in_a_changed_file_fails_the_leg
case_the_zitadel_passwordless_enum_is_not_a_secret
case_a_real_secret_on_a_passwordless_line_still_fires

echo "test_secrets_scan: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property of the narrowed secret scan did not hold. The narrowing is only" >&2
    echo "   defensible while the derivation is right AND says what it looked at: an" >&2
    echo "   empty set from a wrong merge-base reads exactly like a clean rung." >&2
    exit 1
fi
exit 0
