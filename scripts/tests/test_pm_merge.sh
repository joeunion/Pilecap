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
# drives: .gitattributes CHANGELOG.md scripts/check.sh scripts/db.sh scripts/docs_legs.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/kill_mine.sh scripts/pm_fold.sh scripts/pm_merge.sh scripts/queue_cited.sh scripts/sweep.sh scripts/tests/test_pm_fold.sh scripts/tests/test_sweep.sh
# The drive for `scripts/pm_merge.sh` — the refusals, the exit propagation and
# the proof of merge.
#
#   ./scripts/tests/test_pm_merge.sh          run every case
#   ./scripts/tests/test_pm_merge.sh --list   name them and stop
#
# WHY IT EXISTS, and it is `scripts/tests/test_sweep.sh`'s reason exactly: a
# wrapper is made of refusals, and a refusal nothing drives can be deleted by
# accident and stay deleted — the happy path goes on merging, the proof line
# goes on printing, and the first person to find out is whoever types a branch
# name that does not exist and gets a green gate on an unmerged tree. That is
# not a hypothetical: it is the incident pm_merge.sh was built from.
#
# IT BUILDS ITS OWN REPOSITORIES AND MERGES IN THOSE. Every case here runs
# against a throwaway git repository this file creates under `mktemp -d`, with
# its own commits, its own branches and — the piece that makes the last third of
# the cases possible — ITS OWN STUB `scripts/check.sh`. Nothing here merges
# anything in this checkout, and nothing here runs the real gate.
#
# THAT SENTENCE WAS FALSE FOR AS LONG AS THIS FILE HAS EXISTED, and `git -C` is
# why it read as true. Under the pre-push hook this drive
# inherits an absolute `GIT_DIR` — `git -C <linked worktree> push` exports one,
# and it OVERRIDES `-C` — so every `git -C "$REPO" ...` below built the scenario
# in the real repository instead: `stale`, `safe` and `clash` in real refs,
# "base" and "only on main" committed onto real main, and `core.bare true` set
# on the real config, three pushes running, every command exiting 0. The
# sentence is true now because `scripts/tests/drive_preamble.sh` makes it true
# rather than because `-C` was ever the guard anybody read it as.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * THE REAL GATE. The scratch repositories carry a stub `scripts/check.sh`
#     that records the arguments it was handed and exits with whatever status
#     the case asked for. So these cases prove the WIRING — that pm_merge runs
#     the tree's own gate, with `--fast`, only after a merge that actually
#     happened, and that the gate's exit status becomes pm_merge's own. They
#     prove nothing whatever about `scripts/check.sh` itself, which is the full
#     gate's business and is measured everywhere else in this repository.
#   * THE REAL FOLD, for the same reason and with the same shape. `--bank` runs
#     `scripts/pm_fold.sh` before the gate, and the scratch repositories carry a
#     STUB one that announces itself and exits 0. So the `--bank` cases prove
#     the WIRING — that the fold is run, that it is run BEFORE the gate, that a
#     merge without `--bank` does not run one at all, and that a missing fold is
#     a refusal rather than a skip. They prove nothing about what the fold
#     regenerates or commits; that is `scripts/tests/test_pm_fold.sh`'s
#     business, and it is the drive that copies the REAL fold into its
#     fixtures.
#   * A COPY, NOT THE FILE ITSELF, IS WHAT RUNS. `scripts/pm_merge.sh` refuses
#     to act when the checkout you are standing in is not the one it lives in
#     (a property worth having on its own), which means the
#     cases must run a copy inside each scratch repository. The copy is made
#     with `cp` from this tree in every case, so it is the same bytes; if that
#     ever stops being true, `case_the_real_script_refuses_a_foreign_checkout`
#     is the one case that runs THIS tree's file, and it asserts the refusal.
#   * WHETHER A MERGE SHOULD HAPPEN. Criteria, reviews and whether the branch
#     is the one a builder reported are the PM's judgement; see pm_merge.sh's
#     own "what this does not cover".
#   * CONFLICT RESOLUTION. The conflicting case asserts the refusal and the
#     stated working-tree state, then aborts the merge itself. pm_merge never
#     resolves and never aborts, deliberately.
#   * THE ENVIRONMENT, EXCEPT FOR ONE NAME. The pipe guard exempts CI, so this
#     drive's expectations used to change with the harness — green on a laptop,
#     three red assertions on a runner, with the wrapper working perfectly both
#     times. `drive_preamble.sh` section 4 now unsets the exemption
#     variables for the whole drive and the two pipe cases below drive BOTH
#     directions. Nothing else here is pinned against the environment, and
#     nothing else here was found to need it.
set -euo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before the first git command -----------
#
# This drive is the one that escaped. Run under the pre-push hook it
# inherited an absolute `GIT_DIR` from `git -C <linked worktree> push`, which
# overrides `-C` — so `git -C "$REPO" init/commit/branch` built its scenario in
# the REAL repository three times: `stale`, `safe` and `clash` in real refs,
# "base" and "only on main" on real main, `core.bare true` on the real config.
# The preamble unsets that environment, guards the scratch paths, and
# fingerprints this checkout so a drive that moves it says so. Read its header
# for the measured mechanism.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_pm_merge: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_pm_merge: $*" >&2
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
    echo "!! unknown argument '$1': test_pm_merge.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -f scripts/pm_merge.sh ] || cannot_look "scripts/pm_merge.sh is not in this tree — there is nothing to drive"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-pm-merge-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

SOURCE="$PWD/scripts/pm_merge.sh"
# check.sh is read as TEXT by one case only — the pipe guard pm_merge's header
# claims it copied. It is never run from here; `--fast` would refuse anyway
# while the full gate holds this checkout's lock.
GATE="$PWD/scripts/check.sh"

# --- the two assertions every case makes (test_sweep.sh's helpers) -----------
DRIVE_OUT=""
DRIVE_EXIT=0
CURRENT=""
drive() {
    local label="$1" want="$2"
    shift 3
    CURRENT="$label"
    DRIVE_OUT="${WORK}/$(printf '%s' "$label" | tr -c 'a-zA-Z0-9' '_').log"
    set +e
    "$@" >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    set -e
    if [ "$DRIVE_EXIT" -eq "$want" ]; then
        echo "  ok       ${label} — exit ${DRIVE_EXIT}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted exit ${want}, got ${DRIVE_EXIT}"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -20
        FAILED=$((FAILED + 1))
    fi
}

# A refusal with the right code and the wrong sentence is a refusal nobody can
# act on, so both are asserted about the same run.
says() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        echo "  ok       ${CURRENT} — says \"$1\""
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — does not say \"$1\""
        sed 's/^/             | /' "$DRIVE_OUT" | tail -20
        FAILED=$((FAILED + 1))
    fi
}

says_not() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        echo "  FAILED   ${CURRENT} — says \"$1\" and must not"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -20
        FAILED=$((FAILED + 1))
    else
        echo "  ok       ${CURRENT} — does not say \"$1\""
        PASSED=$((PASSED + 1))
    fi
}

# ORDER, and it is a property rather than a decoration. `pm_merge` prints the
# fold's output and the gate's into ONE stdout, so the line numbers in
# `$DRIVE_OUT` are the sequence the operator saw. The sequence is the whole
# argument of `pm_merge.sh`'s fold block: a fold that ran AFTER the gate would
# have changed the tree the verdict just vouched for, and the verdict would key
# on a tree that no longer exists. Two `says` calls cannot see that — both are
# green whichever way round they happened.
says_before() {
    local first="$1" second="$2" fl sl
    fl="$(grep -nF -- "$first" "$DRIVE_OUT" | head -1 | cut -d: -f1)"
    sl="$(grep -nF -- "$second" "$DRIVE_OUT" | head -1 | cut -d: -f1)"
    if [ -n "$fl" ] && [ -n "$sl" ] && [ "$fl" -lt "$sl" ]; then
        echo "  ok       ${CURRENT} — \"${first}\" (line ${fl}) came before \"${second}\" (line ${sl})"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — \"${first}\" (line ${fl:-absent}) did not come before \"${second}\" (line ${sl:-absent})"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -20
        FAILED=$((FAILED + 1))
    fi
}

holds() {
    local label="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then
        echo "  ok       ${label} — ${got}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted '${want}', got '${got}'"
        FAILED=$((FAILED + 1))
    fi
}

# --- the scratch repository ---------------------------------------------------
#
# main:  base -> only-on-main   (so no branch is ever a fast-forward)
# safe:  base -> safe-change    (merges cleanly into main)
# clash: base -> clash-change   (touches the same line as only-on-main)
# stale: base                   (already an ancestor of main)
REPO=""
GATE_LOG=""
FOLD_LOG=""
N=0
fresh_repo() {
    N=$((N + 1))
    REPO="${WORK}/repo${N}"
    GATE_LOG="${WORK}/gate${N}.log"
    FOLD_LOG="${WORK}/fold${N}.log"
    # Created empty, so "the gate never ran" is an empty file rather than a
    # missing one — an absent file and a gate that ran zero times read the same
    # to `wc`, and only one of them is the property being asserted.
    : >"$GATE_LOG"
    : >"$FOLD_LOG"
    # THE BELT, and it comes before the `mkdir` as well as before the
    # first git command. `git -C "" ...` is a no-op chdir, not a refusal: every
    # command after it lands on whatever repository this process is standing in.
    # An empty $REPO makes the line below `mkdir -p /scripts`, which is the same
    # incident one step earlier.
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO/scripts"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "pm_merge drive"

    cp "$SOURCE" "$REPO/scripts/pm_merge.sh"
    chmod +x "$REPO/scripts/pm_merge.sh"

    # The stub gate: it records what it was handed and exits with the status the
    # case asked for. This is the whole of what these cases know about the gate.
    {
        echo '#!/usr/bin/env bash'
        echo "echo \"STUB GATE ran with: \$*\""
        echo "printf '%s\\n' \"\$*\" >>\"$GATE_LOG\""
        echo "exit \"\${DJB_DRIVE_GATE_RC:-0}\""
    } >"$REPO/scripts/check.sh"
    chmod +x "$REPO/scripts/check.sh"

    # The stub fold, the stub gate's idiom exactly, and it exists because the
    # ritual grew a step this fixture did not have. The fold landed in
    # `pm_merge.sh --bank` on 2026-09-02: `--bank` now runs
    # `${ROOT}/scripts/pm_fold.sh` BEFORE the gate, and refuses at exit 2 when
    # there is no executable one. The fixture carried a stub gate and no fold,
    # so every `--bank` case here was measuring the refusal instead of the tier
    # — four red assertions at the push bank of 2026-09-07, with the ritual
    # entirely right and the fixture five days stale.
    #
    # THE PATH IS DERIVED, NOT CHOSEN. `pm_merge.sh` resolves the fold as
    # `$ROOT/scripts/pm_fold.sh` where `ROOT` is `git rev-parse --show-toplevel`
    # — the scratch repository, because `in_repo` stands in it — so this is that
    # path and not a guess at it.
    #
    # It exits 0 the way the real `pm_fold.sh` does on a tree with nothing to
    # fold, which is the honest answer here: these repositories have no derived
    # files to regenerate. That is also the whole of what these cases know about
    # the fold — see THE REAL FOLD in the blind spots above.
    {
        echo '#!/usr/bin/env bash'
        echo 'echo "STUB FOLD ran"'
        echo "printf '%s\\n' \"ran\" >>\"$FOLD_LOG\""
        echo 'echo "pm_fold: NOTHING TO FOLD. No commit was made."'
        echo 'exit 0'
    } >"$REPO/scripts/pm_fold.sh"
    chmod +x "$REPO/scripts/pm_fold.sh"

    echo "one" >"$REPO/shared.txt"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "base"
    git -C "$REPO" branch stale

    git -C "$REPO" checkout -q -b safe
    echo "safe" >"$REPO/safe.txt"
    git -C "$REPO" add safe.txt
    git -C "$REPO" commit -q -m "safe change"

    git -C "$REPO" checkout -q -b clash main
    echo "clash" >"$REPO/shared.txt"
    git -C "$REPO" add shared.txt
    git -C "$REPO" commit -q -m "clash change"

    git -C "$REPO" checkout -q main
    echo "main" >"$REPO/shared.txt"
    git -C "$REPO" add shared.txt
    git -C "$REPO" commit -q -m "only on main"
}

# Run a command with the scratch repository as the working directory — the
# checkout pm_merge reads from `git rev-parse --show-toplevel`.
in_repo() { (cd "$REPO" && "$@"); }

head_of() { git -C "$REPO" rev-parse HEAD; }

# --- the refusals ------------------------------------------------------------

case_no_branch_named_is_refused() {
    fresh_repo
    local before
    before="$(head_of)"
    drive "no branch named" 2 -- in_repo ./scripts/pm_merge.sh
    says "no branch named"
    holds "no branch named: HEAD did not move" "$before" "$(head_of)"
}

case_an_unknown_flag_is_refused() {
    fresh_repo
    drive "unknown flag" 2 -- in_repo ./scripts/pm_merge.sh --merge-it safe
    says "unknown flag"
}

case_two_branches_are_refused() {
    fresh_repo
    drive "two branches" 2 -- in_repo ./scripts/pm_merge.sh safe clash
    says "one branch at most"
}

# A branch name that does not exist must be a loud refusal that names itself,
# not git's one-line "not something we can merge".
case_a_nonexistent_branch_is_a_loud_refusal() {
    fresh_repo
    local before
    before="$(head_of)"
    drive "nonexistent branch" 2 -- in_repo ./scripts/pm_merge.sh worktree-agent-typo-safe
    says "names no commit"
    says "Nothing was merged"
    holds "nonexistent branch: HEAD did not move" "$before" "$(head_of)"
    holds "nonexistent branch: the gate never ran" "0" "$(wc -l <"$GATE_LOG" | tr -d ' ')"
}

# The other half of the same class: a name that DOES resolve but is already in.
# git exits 0 on that, which is a success status for a merge that did not happen.
case_an_already_merged_branch_is_refused() {
    fresh_repo
    local before
    before="$(head_of)"
    drive "already an ancestor" 2 -- in_repo ./scripts/pm_merge.sh stale
    says "ALREADY an ancestor"
    says "Already up to date"
    holds "already an ancestor: HEAD did not move" "$before" "$(head_of)"
    says_not "Proof of merge"
}

case_a_dirty_tree_is_refused() {
    fresh_repo
    local before
    before="$(head_of)"
    echo "an unsaved edit" >>"$REPO/shared.txt"
    drive "dirty tree" 2 -- in_repo ./scripts/pm_merge.sh safe
    says "uncommitted changes"
    holds "dirty tree: HEAD did not move" "$before" "$(head_of)"
}

# The refusal is actually about: you cannot filter this script's output.
#
# THIS CASE DEPENDS ON AN ENVIRONMENT IT DOES NOT SET, and for eight days it did
# not say so. The guard exempts CI (`scripts/pm_merge.sh:91`, check.sh's line
# copied), so on a GitHub runner — where CI is exported and every step's stdout
# IS a pipe — the exemption fires, the pipe is allowed, the scratch merge really
# happens, and all three assertions here go red against a wrapper that is
# working exactly as designed. The refusal path is
# exercised on every platform now because `drive_preamble.sh` section 4 unsets
# the exemption variables for the whole drive; the exemption's own half is the
# case below, which sets them back at its own call site.
case_a_piped_stdout_is_refused() {
    fresh_repo
    local before
    before="$(head_of)"
    drive "piped stdout" 2 -- in_repo bash -c 'set -o pipefail; ./scripts/pm_merge.sh safe | cat'
    says "refuses pipes"
    holds "piped stdout: HEAD did not move" "$before" "$(head_of)"
}

# THE OTHER HALF, and the reason the strip above is a fix rather than a dodge: a
# refusal exercised everywhere and an exemption exercised nowhere is the same
# blindness pointed the other way. If the exemption is ever lost, CI stops being
# able to run the gate at all — and this is the case that says so first, on a
# laptop, in fifteen seconds, instead of fourteen minutes into a runner.
#
# There is no exemption SENTENCE to assert: the guard falls through silently, so
# what it honestly says is the merge itself — the proof line, the gate the
# wrapper went on to run, and a HEAD that really moved.
case_the_ci_exemption_lets_a_piped_run_through() {
    fresh_repo
    local before
    before="$(head_of)"
    drive "piped stdout under CI" 0 -- in_repo env CI=true GITHUB_ACTIONS=true \
        bash -c 'set -o pipefail; ./scripts/pm_merge.sh safe | cat'
    says_not "refuses pipes"
    says "MERGED. Proof of merge"
    says "STUB GATE ran with: --fast"
    if [ "$before" = "$(head_of)" ]; then
        echo "  FAILED   piped stdout under CI — HEAD did not move, so the pipe was refused after all"
        FAILED=$((FAILED + 1))
    else
        echo "  ok       piped stdout under CI — HEAD moved to $(git -C "$REPO" rev-parse --short HEAD)"
        PASSED=$((PASSED + 1))
    fi
}

# THE TOOTH ON THE TWO CASES ABOVE. Both of them are only as honest as the list
# of variables `drive_preamble.sh` strips, and that list is typed. So it is
# checked against the guard itself rather than promised: the guard's condition
# is lifted out of pm_merge.sh by the one test it is made of (`-p` on the stdout
# fd — a marker, never a line number), asserted to be check.sh's same line
# (pm_merge's header claims it is), and every environment variable it reads is
# asserted to be one the preamble unsets. An exemption that grows a variable the
# drives do not strip is a red case here, not a refusal that quietly stopped
# being exercised anywhere.
case_the_pipe_guard_reads_only_what_the_preamble_strips() {
    local marker='[ -p /dev/fd/1 ]'
    local mine theirs vars v unstripped=""
    CURRENT="the pipe guard's variables"
    [ -r "$GATE" ] ||
        cannot_look "scripts/check.sh is not readable — the guard the two pipe cases turn on cannot be compared against the file it was copied from"
    mine="$(grep -m1 -F -- "$marker" "$SOURCE" || true)"
    theirs="$(grep -m1 -F -- "$marker" "$GATE" || true)"
    [ -n "$mine" ] ||
        cannot_look "no pipe guard found in scripts/pm_merge.sh (looked for '${marker}') — the pipe cases assert a refusal that may no longer exist"
    [ -n "$theirs" ] ||
        cannot_look "no pipe guard found in scripts/check.sh (looked for '${marker}') — pm_merge's header claims its guard IS check.sh's and there is nothing left to compare it to"

    holds "the pipe guard is check.sh's line, byte for byte" "$theirs" "$mine"

    # `|| true` is load-bearing and was found by the plant, not reasoned to: a
    # guard that reads NO variable makes grep exit 1, and under this file's
    # `pipefail` that kills the drive mid-case — exit 1 with the case unscored
    # and no summary line at all. The empty set is a RESULT here (it is the
    # assertion below), never a reason to stop reporting.
    vars="$(printf '%s\n' "$mine" | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*' | sed 's/^..//' |
        LC_ALL=C sort -u | tr '\n' ' ' || true)"
    vars="${vars% }"
    holds "the guard reads an environment variable at all (the exemption exists)" \
        "yes" "$([ -n "$vars" ] && echo yes || echo no)"

    for v in $vars; do
        case " ${DRIVE_CI_VARS} " in
        *" $v "*) ;;
        *) unstripped="${unstripped}${unstripped:+ }${v}" ;;
        esac
    done
    holds "every variable the guard reads is one drive_preamble.sh unsets (${DRIVE_CI_VARS})" \
        "(none)" "${unstripped:-(none)}"
}

# --- the tripwire may not convict a drive of a PEER'S merge ------------------
#
# THE DEFECT. `drive_repo_fingerprint` carried `main` BY SHA, on the sentence
# "the PM merges into main from the main checkout, never during a push". That
# was true of ONE caller and the fingerprint is read by every drive: the PM
# merges into LOCAL main continuously, refs are shared across every worktree of
# this repository, and a builder's drive is not a push. So a merge landing
# while any drive ran demoted that drive to exit 2 through no act of its own,
# and it cost one rung a full re-run before anybody found the mechanism.
#
# DRIVEN LIVE, IN BOTH DIRECTIONS, because a text assertion here would only say
# the line is gone and not that the tripwire still works. Each half builds a
# scratch repository with a `main` and a rung branch checked out — this
# repository's shape — and runs a throwaway drive inside it that sources THIS
# tree's real preamble.
#
# The act each half performs is written into the fake drive as shell, and it
# runs with the drive's own working directory inside the scratch repository —
# so a plain `git` there is the scratch repository's, which is the whole point
# of the preamble's section 1.
N454_RC=0
run_fake_drive() {
    # Three statements, not one: on bash 3.2 a single `local a=$1 b=${a}` reads
    # `a` before the assignment lands and dies under `set -u`. Found here, by
    # this file, on its first run.
    local label="$1"
    local act="$2"
    # `hold-main` gives the scratch repository a SECOND worktree standing on
    # `main`, which is this repository's real shape: the primary checkout holds
    # `main` and every rung is a linked worktree on its own branch. The tripwire
    # excuses a moved ref only when a worktree other than the drive's has it
    # checked out, so a fixture that fakes the PM's merge without the PM's
    # checkout is asking to be convicted — correctly. Only the peer-merge half
    # wants it: the escape half CHECKS OUT main inside the fake drive, which git
    # refuses while another worktree holds it.
    local shape="${3:-}"
    local repo="${WORK}/n454-${label}"
    drive_require_scratch repo "${repo:-}"
    mkdir -p "$repo"
    git -C "$repo" init -q
    git -C "$repo" symbolic-ref HEAD refs/heads/main
    git -C "$repo" config user.email drive@example.invalid
    git -C "$repo" config user.name "n454 drive"
    echo one >"$repo/a.txt"
    git -C "$repo" add a.txt
    git -C "$repo" commit -qm one
    # The rung worktree's own branch is what is checked out, so `main` is not
    # this checkout's HEAD — a builder's worktree, exactly.
    git -C "$repo" checkout -q -b worktree-agent-n454
    if [ "$shape" = "hold-main" ]; then
        git -C "$repo" worktree add -q "${WORK}/n454-${label}-primary" main
    fi

    {
        echo '#!/usr/bin/env bash'
        echo 'set -uo pipefail'
        echo "cd \"$repo\" || exit 9"
        echo ". \"${PWD}/scripts/tests/drive_preamble.sh\""
        echo 'DRIVE_OPTED_IN_TO_FINISH=1'
        printf '%s\n' "$act"
        echo 'drive_finished'
        echo 'exit 0'
    } >"${WORK}/n454-${label}.sh"
    chmod +x "${WORK}/n454-${label}.sh"
    DRIVE_OUT="${WORK}/n454-${label}.log"
    # `|| N454_RC=$?` and not a bare call: this file runs under `set -e`, and
    # HALF THESE CASES EXPECT A NONZERO STATUS. A bare invocation killed this
    # drive mid-case on its first run — exit 2, no summary line, no failing
    # assertion, nothing printed at all.
    N454_RC=0
    "${WORK}/n454-${label}.sh" >"$DRIVE_OUT" 2>&1 || N454_RC=$?
}

n454_exits() {
    if [ "$N454_RC" = "$1" ]; then
        echo "  ok       ${CURRENT} — exit ${N454_RC}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — wanted exit $1, got ${N454_RC}"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -20
        FAILED=$((FAILED + 1))
    fi
}

case_a_peers_merge_into_main_does_not_convict_a_drive() {
    CURRENT="a peer's merge into main"
    # THE PEER'S ACT, NOT THE DRIVE'S. `commit-tree` + `update-ref` moves
    # `main` and nothing else — no HEAD, no index, no working tree — which is
    # what a PM merge looks like from inside a worktree that is not the one
    # merging. The drive itself touches nothing at all. `hold-main` puts the
    # PM's own checkout into the fixture, because that checkout is what makes
    # the move somebody else's: a `main` no worktree anywhere holds, moved while
    # a drive ran, is the escape class and is meant to convict.
    run_fake_drive "peer-merge" '
NEW=$(git commit-tree "HEAD^{tree}" -p HEAD -m "the PM merge that landed mid-drive")
git update-ref refs/heads/main "$NEW"
echo "a peer moved main to $NEW while this drive ran"' hold-main
    n454_exits 0
    says_not "MUTATED THE REAL REPOSITORY"
}

case_the_escape_itself_is_still_caught() {
    # THE OTHER DIRECTION, and it is the one that matters: the incident this
    # whole preamble is made of pointed HEAD at refs/heads/main and committed
    # onto it. Both halves move HEAD and HEAD-ref, which are this checkout's
    # own and which no peer can touch — so removing main's SHA takes nothing
    # away from the escape. Asserted rather than argued.
    CURRENT="the escape is still caught"
    run_fake_drive "escape" '
git checkout -q main
echo escaped >>a.txt
git commit -qam "only on main"'
    n454_exits 2
    says "MUTATED THE REAL REPOSITORY"

    # And the scenario branches, which is how the escape was actually FOUND —
    # `stale`, `safe` and `clash` appearing in the real repository's refs.
    CURRENT="a drive that creates branches is still caught"
    run_fake_drive "branches" '
git branch stale
git branch safe
git branch clash'
    n454_exits 2
    says "refs/heads/clash"

    # And `core.bare`, which `git init` under an inherited GIT_DIR sets and
    # which nothing legitimate in this repository ever does.
    CURRENT="a drive that sets core.bare is still caught"
    run_fake_drive "core-bare" 'git config core.bare true'
    n454_exits 2
    says "core.bare"
}

case_the_real_script_refuses_a_foreign_checkout() {
    fresh_repo
    local before
    before="$(head_of)"
    # THIS tree's pm_merge.sh, run while standing in the scratch repository.
    drive "foreign checkout" 2 -- in_repo "$SOURCE" safe
    says "not the checkout this script lives in"
    holds "foreign checkout: HEAD did not move" "$before" "$(head_of)"
}

# --- the conflict -------------------------------------------------------------

case_a_conflicting_merge_surfaces_the_conflict() {
    fresh_repo
    drive "conflicting merge" 1 -- in_repo ./scripts/pm_merge.sh clash
    says "THE MERGE FAILED"
    says "WORKING TREE: MID-MERGE"
    says "shared.txt"
    says "merge --abort"
    # The state it claims is the state that is actually there.
    local mid="no"
    git -C "$REPO" rev-parse --verify --quiet MERGE_HEAD >/dev/null && mid="yes"
    holds "conflicting merge: the tree really is mid-merge" "yes" "$mid"
    holds "conflicting merge: the gate never ran" "0" "$(wc -l <"$GATE_LOG" | tr -d ' ')"
    says_not "Proof of merge"
    git -C "$REPO" merge --abort
}

# --- the clean merge ----------------------------------------------------------

case_a_clean_merge_prints_the_proof_line() {
    fresh_repo
    local before
    before="$(head_of)"
    drive "clean merge" 0 -- in_repo ./scripts/pm_merge.sh safe
    says "MERGED. Proof of merge"
    # The proof line is the real one: the sha it printed is this tree's new HEAD.
    says "$(git -C "$REPO" rev-parse --short HEAD)"
    if [ "$before" = "$(head_of)" ]; then
        echo "  FAILED   clean merge — HEAD did not move"
        FAILED=$((FAILED + 1))
    else
        echo "  ok       clean merge — HEAD moved to $(git -C "$REPO" rev-parse --short HEAD)"
        PASSED=$((PASSED + 1))
    fi
    holds "clean merge: the new tip has two parents" "2" \
        "$(git -C "$REPO" log -1 --format=%P | wc -w | tr -d ' ')"
    holds "clean merge: the gate ran once, with --fast" "--fast" "$(cat "$GATE_LOG")"
}

# --- the merge's two consults: the loop row, and the drives that declare it ----
#
# WHAT THE MERGE CAN SAY WITHOUT MEASURING. A rung's last boundary is one box
# `--loop`, and its row comes home with the box's `wait`; the merge prints
# whether the branch head's tree has one (HIT/MISS, the key, the box). And a
# merge's files are declared by shell drives the `--loop` does not run: the
# merge prints which declaring drives ran since that loop row and which did
# not, so a drive the wave meets only at the bank is named at the merge. The
# ledgers are this scratch repository's own (the common git dir), planted with
# rows in the writers' own grammar; the library is THIS tree's, copied in.
consult_repo() {
    fresh_repo
    cp "$PWD/scripts/gate_ledger.sh" "$REPO/scripts/gate_ledger.sh"
    cp "$GATE_REFUSE_SRC" "$REPO/scripts/gate_refuse.sh"
    mkdir -p "$REPO/scripts/tests"
    {
        echo '#!/usr/bin/env bash'
        echo '# drives: safe.txt'
        echo 'exit 0'
    } >"$REPO/scripts/tests/test_zzz_merged.sh"
    git -C "$REPO" add scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/tests/test_zzz_merged.sh
    git -C "$REPO" commit -q -m "the ledger library and a drive that declares safe.txt"
}

case_the_merge_names_the_loop_row_and_the_drives_that_have_not_run() {
    local tree other="0000000000000000000000000000000000000000" key="loop-v1:$(printf 'a%.0s' $(seq 1 64))"
    # THE QUIET DIRECTION: after the loop row, the drive ran RED on this tree and
    # GREEN on another. Neither measured the merged bytes green — NOT on it.
    consult_repo
    tree="$(git -C "$REPO" rev-parse 'safe^{tree}')"
    printf 'loop-v1 %s loop 2026-09-27T10:00:00Z caller=unstated scope=mode=fast passes=1 tree=%s env=x box=i-zzzbox\n' \
        "$key" "$tree" >>"$REPO/.git/djb-loop-verdicts"
    {
        printf 'v1 drive-v1:zzz1 drive 2026-09-27T11:00:00Z zzz_merged exit=1 took=1 tree=%s parts=-\n' "$tree"
        printf 'v1 drive-v1:zzz2 drive 2026-09-27T11:05:00Z zzz_merged exit=0 took=1 tree=%s parts=-\n' "$other"
    } >>"$REPO/.git/djb-gate-verdicts"
    drive "the merge's consults (a box row; the drive red here, green elsewhere, both after it)" 0 -- in_repo ./scripts/pm_merge.sh safe
    says "loop consult: HIT — tree ${tree} (safe's head) key ${key} box=i-zzzbox banked 2026-09-27T10:00:00Z"
    # A ROW ON THESE BYTES THAT IS NOT GREEN IS RED, whoever wrote it, and it
    # reads as the warning it is — never folded in with the structural misses.
    says "drives: 1 declare this merge's files — ran green on the branch head's tree (${tree}): none; red or absent on it: zzz_merged; not recorded by any loop: none"
    says "!! drives red or absent on these bytes that a loop records: zzz_merged — a finding"
    holds "the consults change nothing: the gate still ran once, with --fast" "--fast" "$(cat "$GATE_LOG")"

    # THE LOUD DIRECTION: the drive ran GREEN on exactly this tree, banked
    # BEFORE the loop row by the clock (the loop's own always-on drives are
    # this shape) — it ran on these bytes.
    consult_repo
    tree="$(git -C "$REPO" rev-parse 'safe^{tree}')"
    printf 'loop-v1 %s loop 2026-09-27T10:00:00Z caller=unstated scope=mode=fast passes=1 tree=%s env=x box=i-zzzbox\n' \
        "$key" "$tree" >>"$REPO/.git/djb-loop-verdicts"
    printf 'v1 drive-v1:zzz drive 2026-09-27T09:59:00Z zzz_merged exit=0 took=1 tree=%s parts=-\n' \
        "$tree" >>"$REPO/.git/djb-gate-verdicts"
    drive "the merge's consults (the drive green on this tree, before the loop row)" 0 -- in_repo ./scripts/pm_merge.sh safe
    says "drives: 1 declare this merge's files — ran green on the branch head's tree (${tree}): zzz_merged; red or absent on it: none; not recorded by any loop: none"
    says_not "!! drives red or absent"

    # AND NO LOOP ROW AT ALL is a MISS, said.
    consult_repo
    tree="$(git -C "$REPO" rev-parse 'safe^{tree}')"
    drive "the merge's consults (no loop row at all)" 0 -- in_repo ./scripts/pm_merge.sh safe
    says "loop consult: MISS — no loop row names tree ${tree} (safe's head); the verifier's consult re-measures"
    # NO ROW ANYWHERE: nothing shows a loop records it, so it is information.
    says "drives: 1 declare this merge's files — ran green on the branch head's tree (${tree}): none; red or absent on it: none; not recorded by any loop: zzz_merged"
    says "not recorded by any loop (1): no --loop runs them, so they meet these files first at the bank — information, not a finding"
    says_not "!! drives red or absent"
}

# THE SPLIT, BY THE LEDGERS' OWN WRITERS. Drive rows are written by the loop's
# always-on leg (on the loop's tree) and by a bank's selftest leg (on the bank's
# tree). A drive green on a tree a LOOP row names is one a loop records — its
# absence on these bytes is the warning. A drive green only on a tree no loop
# row names is full-only — its absence is structural, and says so.
case_the_merge_splits_unrecorded_drives_from_red_or_absent_ones() {
    local tree loopt="1111111111111111111111111111111111111111" bankt="2222222222222222222222222222222222222222"
    local key="loop-v1:$(printf 'b%.0s' $(seq 1 64))"
    # A LOOP RECORDS IT: green on another tree a loop measured, nothing here.
    consult_repo
    tree="$(git -C "$REPO" rev-parse 'safe^{tree}')"
    printf 'loop-v1 %s loop 2026-09-27T08:00:00Z caller=unstated scope=mode=fast passes=1 tree=%s env=x\n' \
        "$key" "$loopt" >>"$REPO/.git/djb-loop-verdicts"
    printf 'v1 drive-v1:zzz drive 2026-09-27T08:00:00Z zzz_merged exit=0 took=1 tree=%s parts=-\n' \
        "$loopt" >>"$REPO/.git/djb-gate-verdicts"
    drive "the merge's drives line (a drive a loop records, absent on these bytes)" 0 -- in_repo ./scripts/pm_merge.sh safe
    says "drives: 1 declare this merge's files — ran green on the branch head's tree (${tree}): none; red or absent on it: zzz_merged; not recorded by any loop: none"
    says "!! drives red or absent on these bytes that a loop records: zzz_merged — a finding; run them on a box before the bank"
    says_not "information, not a finding"

    # FULL-ONLY: green at a bank's tree no loop row names, nothing here.
    consult_repo
    tree="$(git -C "$REPO" rev-parse 'safe^{tree}')"
    printf 'loop-v1 %s loop 2026-09-27T08:00:00Z caller=unstated scope=mode=fast passes=1 tree=%s env=x\n' \
        "$key" "$loopt" >>"$REPO/.git/djb-loop-verdicts"
    printf 'v1 drive-v1:zzz drive 2026-09-27T08:00:00Z zzz_merged exit=0 took=1 tree=%s parts=-\n' \
        "$bankt" >>"$REPO/.git/djb-gate-verdicts"
    drive "the merge's drives line (a full-only drive, green only at a bank)" 0 -- in_repo ./scripts/pm_merge.sh safe
    says "drives: 1 declare this merge's files — ran green on the branch head's tree (${tree}): none; red or absent on it: none; not recorded by any loop: zzz_merged"
    says "not recorded by any loop (1): no --loop runs them, so they meet these files first at the bank — information, not a finding"
    says_not "!! drives red or absent"
}

# --- the CHANGELOG's merge driver ---------------------------------------------
#
# WHAT IS UNDER TEST HERE IS `.gitattributes`, NOT `pm_merge.sh`. The wrapper is
# unchanged by this; the one line `CHANGELOG.md merge=union` changes what
# `git merge` does underneath it, and these cases drive THIS TREE'S FILE into a
# scratch repository rather than re-typing the line, for `$SOURCE`'s reason: a
# case that re-types its subject stops being a case about the tree.
#
# WHY IT IS HERE AND NOT SOMEWHERE ELSE. `CHANGELOG.md` is append-only under
# `## [Unreleased]`, every rung appends to it, and the merge of two such
# branches is what this drive already exists to measure. Seven hand
# resolutions in cycle P21 were the cost, and the class' expensive half was a
# hand resolution of a CODE file that dropped 902 lines.
#
# THREE CASES, AND THE THIRD IS THE ONE THAT KEEPS THE OTHER TWO HONEST:
# the union merges two appends clean; WITHOUT the attribute the same two
# appends conflict (the sever direction — a guard nobody can turn off is a
# guard nobody has measured); and the union is a MERGE DRIVER AND NOT A JUDGE,
# so the release leg still refuses the interleave it can produce.
ATTRIBUTES_SRC="$PWD/.gitattributes"
DOCS_LEGS_SRC="$PWD/scripts/docs_legs.sh"
GATE_REFUSE_SRC="$PWD/scripts/gate_refuse.sh"

# changelog_repo <yes|no> <lane-a body> <main body> — `fresh_repo` plus a
# CHANGELOG.md and two lanes that both change it. The first argument decides
# whether THIS TREE'S `.gitattributes` is in the checkout, which is the whole
# variable between the first two cases.
#
# THE BODIES ARE WRITTEN WHOLE, never patched in place: `sed -i` is two
# different commands on the two machines this drive runs on (BSD wants an
# argument, GNU does not), and a fixture that builds itself differently on the
# box and on the Mac is a fixture whose green means two different things.
changelog_repo() {
    local attrs="$1" base="$2" lane_a="$3" lane_b="$4"
    fresh_repo
    if [ "$attrs" = "yes" ]; then
        [ -r "$ATTRIBUTES_SRC" ] || cannot_look "no readable ${ATTRIBUTES_SRC} — there is no merge contract to drive"
        cp "$ATTRIBUTES_SRC" "$REPO/.gitattributes"
        git -C "$REPO" add .gitattributes
    fi
    printf '%s' "$base" >"$REPO/CHANGELOG.md"
    git -C "$REPO" add CHANGELOG.md
    git -C "$REPO" commit -q -m "the changelog, and whatever merges it"

    git -C "$REPO" checkout -q -b lane-a
    printf '%s' "$lane_a" >"$REPO/CHANGELOG.md"
    git -C "$REPO" commit -q -a -m "lane A: a bullet under [Unreleased]"

    git -C "$REPO" checkout -q main
    printf '%s' "$lane_b" >"$REPO/CHANGELOG.md"
    git -C "$REPO" commit -q -a -m "lane B: a bullet under [Unreleased]"
}

# The appending scenario, whole files: what the base commit shipped and what
# each lane made of it.
CL_APPEND_BASE='# Changelog

## [Unreleased]

- the bullet the base commit shipped

## [9.9.8]

- a shipped section, and it is history
'
CL_APPEND_A='# Changelog

## [Unreleased]

- the bullet the base commit shipped
- lane A appended this bullet

## [9.9.8]

- a shipped section, and it is history
'
CL_APPEND_B='# Changelog

## [Unreleased]

- the bullet the base commit shipped
- lane B appended this bullet

## [9.9.8]

- a shipped section, and it is history
'

# The two INTERLEAVING lanes: both rewrite the OPENING line of one bullet whose
# code span closes on the NEXT line. Union writes ours' version of that line and
# then theirs', and the closing half — untouched context — follows ONCE. The
# section then carries an odd number of backticks: a bullet split across the two
# sides. This is the union's real failure mode, reproduced rather than described.
CL_SPLIT_BASE='# Changelog

## [Unreleased]

- the bullet, naming `./scripts/gate.sh
  --fast` and then prose

## [9.9.8]

- a shipped section, and it is history
'
CL_SPLIT_A='# Changelog

## [Unreleased]

- lane A rewrote this line, naming `./scripts/gate.sh
  --fast` and then prose

## [9.9.8]

- a shipped section, and it is history
'
CL_SPLIT_B='# Changelog

## [Unreleased]

- lane B rewrote this line, naming `./scripts/gate.sh
  --fast` and then prose

## [9.9.8]

- a shipped section, and it is history
'

# cl_backticks — how many backticks the fixture's CHANGELOG.md carries. The
# leg's own balance test in one number, so a case can say WHY the leg refused.
cl_backticks() { tr -cd '`' <"$REPO/CHANGELOG.md" | wc -c | tr -d ' '; }

# cl_flags <version> — the release leg's BODY, run in a subshell against the
# fixture. DRIVEN AT THE BODY AND NOT THROUGH publish.sh, for the reason every
# drive here states: the body is `docs_changelog_flags` in
# `scripts/docs_legs.sh` and a case that can read its status is a case that can
# say what it refused. The subshell is not tidiness — the library sets `set -e`
# expectations and globals of its own, and this drive's accumulators are not
# its to touch.
cl_flags() {
    CLOUT="$WORK/clflags${N}.out"
    [ -r "$DOCS_LEGS_SRC" ] || cannot_look "no readable ${DOCS_LEGS_SRC} — there is no release leg to ask"
    set +e
    (
        . "$GATE_REFUSE_SRC"
        . "$DOCS_LEGS_SRC"
        docs_changelog_flags "$REPO" "$1"
    ) >"$CLOUT" 2>&1
    CLRC=$?
    set -e
}

case_two_appends_to_the_changelog_merge_clean() {
    changelog_repo yes "$CL_APPEND_BASE" "$CL_APPEND_A" "$CL_APPEND_B"
    # THE ATTRIBUTE IS ASKED OF GIT, not assumed from the file's presence. On
    # main this line answered `unspecified` and the merge below was the seven
    # hand resolutions.
    holds "changelog union: git resolves the attribute" "CHANGELOG.md: merge: union" \
        "$(git -C "$REPO" check-attr merge CHANGELOG.md)"
    drive "two appends merge clean" 0 -- in_repo ./scripts/pm_merge.sh lane-a
    says "MERGED. Proof of merge"
    says_not "WORKING TREE: MID-MERGE"
    local mid="no"
    git -C "$REPO" rev-parse --verify --quiet MERGE_HEAD >/dev/null && mid="yes"
    holds "two appends: the tree is NOT mid-merge" "no" "$mid"
    holds "two appends: no conflict marker survived" "0" \
        "$(grep -c '^<<<<<<<\|^>>>>>>>\|^=======' "$REPO/CHANGELOG.md" || true)"
    # BOTH BULLETS, AND IN THE ORDER THE DRIVER PROMISES: ours, then theirs.
    # "Both are present" alone is satisfied by a resolution that shuffled the
    # section, and the order is the half a reader of the released section sees.
    holds "two appends: lane B's bullet is present" "1" \
        "$(grep -c 'lane B appended this bullet' "$REPO/CHANGELOG.md" || true)"
    holds "two appends: lane A's bullet is present" "1" \
        "$(grep -c 'lane A appended this bullet' "$REPO/CHANGELOG.md" || true)"
    holds "two appends: ours before theirs" "1" \
        "$([ "$(grep -n 'lane B appended' "$REPO/CHANGELOG.md" | cut -d: -f1)" \
            -lt "$(grep -n 'lane A appended' "$REPO/CHANGELOG.md" | cut -d: -f1)" ] && echo 1 || echo 0)"
    # The heading was not duplicated and the base bullet was not eaten — the two
    # ways a keep-both driver can keep the wrong both.
    holds "two appends: one [Unreleased] heading" "1" \
        "$(grep -c '^## \[Unreleased\]' "$REPO/CHANGELOG.md" || true)"
    holds "two appends: the base bullet survived once" "1" \
        "$(grep -c 'the bullet the base commit shipped' "$REPO/CHANGELOG.md" || true)"
}

case_without_the_attribute_the_same_two_appends_conflict() {
    # THE SEVER DIRECTION. Byte-identical fixture, byte-identical lanes, one
    # file removed — and this is the state main was in when the PM resolved
    # seven of these by hand. Without it the case above could pass on a merge
    # that was never going to conflict, and nobody would know.
    changelog_repo no "$CL_APPEND_BASE" "$CL_APPEND_A" "$CL_APPEND_B"
    holds "no attribute: git resolves nothing" "CHANGELOG.md: merge: unspecified" \
        "$(git -C "$REPO" check-attr merge CHANGELOG.md)"
    drive "the same two appends without the attribute" 1 -- in_repo ./scripts/pm_merge.sh lane-a
    says "THE MERGE FAILED"
    says "WORKING TREE: MID-MERGE"
    says "CHANGELOG.md"
    holds "no attribute: CHANGELOG.md is unmerged" "UU CHANGELOG.md" \
        "$(git -C "$REPO" status --porcelain -- CHANGELOG.md)"
    holds "no attribute: the gate never ran" "0" "$(wc -l <"$GATE_LOG" | tr -d ' ')"
    git -C "$REPO" merge --abort
}

case_the_union_is_a_merge_driver_and_not_a_judge() {
    # THE DECLARED COST OF THE LINE, DRIVEN. Union keeps both sides of a region
    # both sides changed, and it has no idea what a bullet is: two lanes that
    # rewrite the opening line of one wrapped bullet get that line twice and its
    # closing half once. The merge is CLEAN — nothing in git objects — and the
    # section is broken. What objects is the release leg, at exit 2, before a
    # tag.
    changelog_repo yes "$CL_SPLIT_BASE" "$CL_SPLIT_A" "$CL_SPLIT_B"
    drive "the interleave merges clean" 0 -- in_repo ./scripts/pm_merge.sh lane-a
    says "MERGED. Proof of merge"
    holds "interleave: the opening line landed twice" "2" \
        "$(grep -c 'rewrote this line, naming' "$REPO/CHANGELOG.md" || true)"
    holds "interleave: the closing half landed once" "1" \
        "$(grep -c -- '--fast` and then prose' "$REPO/CHANGELOG.md" || true)"
    holds "interleave: an ODD number of backticks" "1" \
        "$(( $(cl_backticks) % 2 ))"
    # AND THE JUDGE STILL REFUSES IT.
    cl_flags Unreleased
    holds "interleave: the changelog-flags leg is could-not-look" "2" "$CLRC"
    if grep -qF "ODD number of" "$CLOUT"; then
        echo "  ok       ${CURRENT} — the leg names the odd backtick count"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — the leg did not name the odd backtick count"
        sed 's/^/             | /' "$CLOUT" | tail -20
        FAILED=$((FAILED + 1))
    fi
}

case_bank_runs_the_full_gate_instead_of_fast() {
    # THE FLAG THAT WAS ONLY PROSE. This script printed a paragraph telling the
    # reader to bank a verdict for the merged tree, and then ran `--fast`
    # unconditionally — the tier was a sentence, not a choice. Both halves are
    # asserted here: what the gate was HANDED (the stub records its own argv,
    # so this is the argument itself and not a message about it) and what the
    # operator was TOLD before it ran.
    fresh_repo
    drive "merge with --bank" 0 -- in_repo ./scripts/pm_merge.sh safe --bank
    says "MERGED. Proof of merge"
    says "STUB GATE ran with: --bank"
    says "THE FULL GATE, asked for with --bank"
    says_not "NOT run here: pytest"
    holds "--bank: the gate ran once, with --bank" "--bank" "$(cat "$GATE_LOG")"
    holds "--bank: the merge still happened and has two parents" "2" \
        "$(git -C "$REPO" log -1 --format=%P | wc -w | tr -d ' ')"
    # AND THE FOLD, which `--bank` grew on 2026-09-02. Three separate claims:
    # that it ran at all, that it ran exactly once, and — the one only an
    # ordering assertion can see — that it ran BEFORE the gate, because a fold
    # after the gate changes the tree the verdict just vouched for.
    says "STUB FOLD ran"
    says_before "STUB FOLD ran" "STUB GATE ran with: --bank"
    holds "--bank: the fold ran once" "1" \
        "$(wc -l <"$FOLD_LOG" | tr -d ' ')"
}

case_the_default_tier_is_still_fast() {
    # The other direction, and it is the one that protects every ordinary
    # merge: a flag that changed the DEFAULT would put an eight-minute gate in
    # front of every returned branch.
    fresh_repo
    drive "merge without --bank" 0 -- in_repo ./scripts/pm_merge.sh safe
    says "STUB GATE ran with: --fast"
    says_not "STUB GATE ran with: --bank"
    holds "no flag: the gate ran once, with --fast" "--fast" "$(cat "$GATE_LOG")"
    # The fold is the bank's, not every merge's — `pm_merge.sh` says so in its
    # own fold block: one fold commit per push train beats one per merge, and a
    # `--fast` merge banks no verdict for a fold to keep honest. So the other
    # direction is asserted here too, where it protects every ordinary merge.
    says_not "STUB FOLD ran"
    holds "no flag: the fold did not run" "0" \
        "$(wc -l <"$FOLD_LOG" | tr -d ' ')"
}

case_bank_with_no_fold_is_refused() {
    # BOTH HALVES OF A REFUSAL ARE LOAD-BEARING — this file's own reason for
    # existing, applied to the ritual's newest step. The case above proves
    # `--bank` folds; this one proves it REFUSES, loudly and at exit 2, rather
    # than banking a verdict over derived files nobody regenerated.
    #
    # It is also the exact shape the push bank of 2026-09-07 hit, and keeping it
    # as a case is what stops the fixture's repair from turning the refusal into
    # something nothing drives: the fixture now installs a fold, so without this
    # case the "no executable fold" path would be unreachable from here.
    fresh_repo
    # COMMITTED, not just deleted. The fold is a tracked file in this fixture
    # (the `git add -A` at "base" takes it, exactly as it takes the stub gate),
    # so a bare `rm` leaves an uncommitted deletion and `pm_merge`'s dirty-tree
    # refusal fires FIRST — a green exit 2 for the wrong reason, which is the
    # shape this whole rung exists to stop. The gate's twin case
    # (`case_a_missing_gate_is_refused_before_the_merge`) needs no such commit
    # because its check runs before the dirty-tree one; the fold's runs after
    # the merge.
    git -C "$REPO" rm -q -f scripts/pm_fold.sh
    git -C "$REPO" commit -q -m "no fold in this checkout"
    local before
    before="$(head_of)"
    drive "merge with --bank and no fold" 2 -- in_repo ./scripts/pm_merge.sh safe --bank
    says "no executable fold"
    says "THE MERGE ABOVE IS ALREADY MADE"
    says_not "STUB GATE ran with: --bank"
    holds "no fold: the gate never ran" "" "$(cat "$GATE_LOG")"
    # The merge is not undone by the refusal, and pm_merge says so itself. That
    # is the property the operator has to act on: HEAD moved, the gate did not.
    holds "no fold: the merge still happened and has two parents" "2" \
        "$(git -C "$REPO" log -1 --format=%P | wc -w | tr -d ' ')"
    if [ "$before" = "$(head_of)" ]; then
        echo "  FAILED   no fold: HEAD did not move — the merge should still have happened"
        FAILED=$((FAILED + 1))
    else
        echo "  ok       no fold: HEAD moved to $(git -C "$REPO" rev-parse --short HEAD)"
        PASSED=$((PASSED + 1))
    fi
}

case_a_merge_message_file_is_used() {
    fresh_repo
    printf 'Merge: the message from a file\n' >"${WORK}/msg${N}.txt"
    drive "merge message from a file" 0 -- in_repo ./scripts/pm_merge.sh safe -m "${WORK}/msg${N}.txt"
    holds "the merge commit carries the file's subject" \
        "Merge: the message from a file" "$(git -C "$REPO" log -1 --format=%s)"
}

case_a_merge_message_on_stdin_is_used() {
    fresh_repo
    drive "merge message on stdin" 0 -- in_repo bash -c \
        'printf "Merge: the message from stdin\n" | ./scripts/pm_merge.sh safe -m -'
    holds "the merge commit carries stdin's subject" \
        "Merge: the message from stdin" "$(git -C "$REPO" log -1 --format=%s)"
}

case_an_unreadable_message_file_is_refused() {
    fresh_repo
    local before
    before="$(head_of)"
    drive "message file that is not there" 2 -- in_repo ./scripts/pm_merge.sh safe -m "${WORK}/nope.txt"
    says "no such readable file"
    holds "unreadable message file: HEAD did not move" "$before" "$(head_of)"
}

# --- the exit propagation -----------------------------------------------------
#
# The whole point of the wrapper: the caller's exit status is the gate's, and a
# red gate does not un-print the proof of a merge that really happened.
case_a_red_gate_propagates() {
    fresh_repo
    drive "red gate propagates" 1 -- in_repo env DJB_DRIVE_GATE_RC=1 ./scripts/pm_merge.sh safe
    says "MERGED. Proof of merge"
    says "STUB GATE ran with: --fast"
    holds "red gate: the merge commit is still there" "2" \
        "$(git -C "$REPO" log -1 --format=%P | wc -w | tr -d ' ')"
}

case_an_enforcement_broken_gate_propagates() {
    fresh_repo
    drive "gate exit 2 propagates" 2 -- in_repo env DJB_DRIVE_GATE_RC=2 ./scripts/pm_merge.sh safe
    says "MERGED. Proof of merge"
}

case_a_missing_gate_is_refused_before_the_merge() {
    fresh_repo
    local before
    before="$(head_of)"
    rm -f "$REPO/scripts/check.sh"
    drive "no gate to run" 2 -- in_repo ./scripts/pm_merge.sh safe
    says "no executable gate"
    holds "no gate: HEAD did not move" "$before" "$(head_of)"
}

case_no_branch_named_is_refused
case_an_unknown_flag_is_refused
case_two_branches_are_refused
case_a_nonexistent_branch_is_a_loud_refusal
case_an_already_merged_branch_is_refused
case_a_dirty_tree_is_refused
case_a_piped_stdout_is_refused
case_the_ci_exemption_lets_a_piped_run_through
case_the_pipe_guard_reads_only_what_the_preamble_strips
case_a_peers_merge_into_main_does_not_convict_a_drive
case_the_escape_itself_is_still_caught
case_the_real_script_refuses_a_foreign_checkout
case_a_conflicting_merge_surfaces_the_conflict
case_a_clean_merge_prints_the_proof_line
case_the_merge_names_the_loop_row_and_the_drives_that_have_not_run
case_the_merge_splits_unrecorded_drives_from_red_or_absent_ones
case_two_appends_to_the_changelog_merge_clean
case_without_the_attribute_the_same_two_appends_conflict
case_the_union_is_a_merge_driver_and_not_a_judge
case_bank_runs_the_full_gate_instead_of_fast
case_bank_with_no_fold_is_refused
case_the_default_tier_is_still_fast
case_a_merge_message_file_is_used
case_a_merge_message_on_stdin_is_used
case_an_unreadable_message_file_is_refused
case_a_red_gate_propagates
case_an_enforcement_broken_gate_propagates
case_a_missing_gate_is_refused_before_the_merge

echo "test_pm_merge: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property did not hold. Both halves of a refusal are load-bearing: the" >&2
    echo "   status a caller branches on and the sentence a human acts on." >&2
    exit 1
fi
exit 0
