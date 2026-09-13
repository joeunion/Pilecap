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
# THE VERIFY START. One command that takes a rung branch from "merged in
# somebody else's worktree" to a checkout a field test can measure.
#
#   ./scripts/verify_start.sh <rung-branch> [<destination>]
#   ./scripts/verify_start.sh --check [<checkout>]
#
# Five steps, unconditionally and in this order, each printing what it did and
# how long it took, with the total at the end:
#
#   1. CLONE       this checkout, at the rung branch, into a directory of its
#                  own. A verifier never measures in the builder's worktree and
#                  never measures in the primary.
#   2. UNION MERGE local `main` (carried in as `origin/main`) merged into the
#                  rung branch inside the clone — the tree the rung would LAND
#                  as, which is the tree the criteria are about.
#   3. ENVIRONMENT `.env` from `.env.example`, with this clone's own DERIVED
#                  `DATABASE_NAME` written into it and the primary's `ZITADEL_*`
#                  lines carried across BY NAME. Every value it derives is
#                  PRINTED. Nothing is sourced — see THE .ENV IS PRINTED below.
#   4. LOOP SEED   the source's banked `--loop` verdict rows, copied into the
#                  clone's own ledger inside `.git/`, schema-checked line by
#                  line with the skipped ones COUNTED. A verifier's first
#                  `--loop` can then reuse a verdict the builder already earned
#                  on the same bytes, instead of re-measuring it.
#   5. VERDICT KEY `git status --porcelain` in the clone must show nothing but
#                  untracked `*.log` files. Anything else is exit 2, naming it.
#                  It runs AFTER the seed on purpose: the seeded file lives in
#                  `.git/`, so a seed that ever landed in the working tree would
#                  be caught here rather than shipped.
#
# Exit: 0 the clone is ready · 1 a step ran and FAILED (a merge that conflicts
# is the whole population today) · 2 refused, or a step could not be verified.
# 2 outranks a pass, here as everywhere in this repository.
#
# `--check` runs STEP 5 ALONE against a checkout that already exists (default:
# the one you are standing in). Same code, same exit grammar, no clone. It is
# the leg a verifier runs by hand before a full gate, because the file that
# ruins a verdict is usually one the verifier created themselves an hour ago.
#
# ---------------------------------------------------------------------------
# WHY IT EXISTS. Verifier setup was a hand-recipe, re-derived from memory by
# every batched field test: clone somewhere, merge main in, make an `.env`,
# find a database name. `rung_start.sh` is the same argument one lane over and
# it is the precedent this file follows — hand steps done from memory are also
# hand steps SKIPPED from memory, and the skipped one here is the merge: a rung
# verified against its branch ALONE is verified against a tree that will never
# exist.
#
# THE .ENV IS PRINTED, AND THIS SCRIPT NEVER SOURCES IT. This is the one rule
# here that was bought rather than reasoned, and a sibling product paid for it:
# their verifier recipe ran `source .env`, which exported `PUBLIC_BASE_URL=""`
# into the shell, and their `??` default treats an empty string as PRESENT — so
# the empty export won, the configuration read as set, and THREE GATE RUNS were
# spent before anybody looked at the export rather than the file. An `.env` is
# a file a framework reads at settings import, with its own rules about empty
# and absent (`django-environ` here); a shell that sources it inherits a
# DIFFERENT set of rules and hands them to every process it starts. So this
# script writes that file, prints every value it put in it, and reads it back
# with `grep` where it needs to. It never lets those lines into its own
# environment, and neither should the recipe that replaced it.
#
# WHAT IT REFUSES, AND WHY THE REFUSALS ARE THE DESIGN.
#
#   A DIRTY SOURCE CHECKOUT (exit 2, cloning nothing). `git clone` copies
#   COMMITTED state. A source checkout with uncommitted work would hand the
#   verifier a tree that silently differs from the one the operator is looking
#   at, and the difference is invisible from inside the clone — which is the
#   worst shape a verification error can have. The allowance is the same one
#   step 5 makes and for the same reason: an untracked `*.log` is the output of
#   a run, never source.
#
#   ONE NARROWING, AND IT IS NOT A LOOSENING OF THE ABOVE: when EVERY dirty path
#   in the SOURCE is under `docs/product/`, the clone proceeds from HEAD and
#   each ignored path is printed by name. The refusal exists because the
#   verifier would measure different CODE; a dirty ledger row is not code and
#   moves no verdict key. What is disclosed instead is the thing that really can
#   bite — a verifier reads its criteria from the cycle file IN THE CLONE, so an
#   uncommitted plan is not in the clone either. Scoped to step 1's call site;
#   `strays_in`, which step 5 and `--check` share, is untouched.
#
#   A STRAY UNTRACKED FILE IN THE CLONE (exit 2, naming it). THE TOOTH. The
#   gate's verdict is keyed on the working tree measured through `git add -A`
#   (`scripts/gate_ledger.sh`), so an untracked file that is not ignored SHIFTS
#   THE KEY: a green eight-minute full run banks a verdict against a tree
#   nothing will ever present again, and the next run measures the whole thing
#   over. Two products found this independently in one week — a sibling's
#   verifier scratch files, and this repository's own untracked
#   `.claude/settings.json`, which is why `pm_push.sh` could not reuse main's
#   banked verdict and a push went round the ritual by hand
#   (`docs/product/misses.md`, the push-ritual entry). One mechanism, two bills.
#   `*.log` is the ONLY allowance, because that is the one artefact this
#   repository tells every agent to write into their worktree and the one it
#   already ignores for exactly this reason (`.gitignore`, the run-logs block).
#
#   A DESTINATION THAT IS ALREADY OCCUPIED (exit 2, naming it). Cloning over
#   somebody's half-finished verification is the same data loss `rung_start.sh`
#   refuses one organ over.
#
#   A PIPED STDOUT (exit 2). check.sh's detection and its CI exemption,
#   deliberately identical (`scripts/check.sh:63-66`) and for the same reason:
#   a pipe replaces this script's exit status with the filter's, and the exit
#   status is the verdict. Redirect to a file instead.
#
# WHAT IT CANNOT SEE, declared here rather than discovered:
#
#   1. WHETHER THE MERGE IS THE RIGHT MERGE. It merges `main` as this checkout
#      has it AT CLONE TIME. If the PM merges another rung a minute later, this
#      clone is measuring a union that has already moved. The clone prints both
#      shas so the report can name them; nothing here watches for drift.
#   2. THE VENV, THE DATABASE AND THE SCHEMA. It DERIVES the database name and
#      writes it down; it does not run `uv sync`, create the database or
#      migrate. That is deliberate and it is the line between this script and
#      `scripts/setup.sh`: those steps need a compose stack this script must not
#      start on other agents' behalf (`rung_start.sh`'s argument, unchanged),
#      and a step that cannot be driven end to end in a scratch repository is a
#      step nothing proves. The footer prints the exact commands.
#   3. A CONFLICTED MERGE'S MEANING. It names the paths and exits 1. Whether
#      the conflict is the rung's fault, main's, or a PM ordering failure is a
#      judgement no script makes.
#   4. A REPOSITORY THAT DOES NOT IGNORE `.env`. Step 3 writes `.env`; step 5
#      allows only `*.log`. In this template and in every product cloned from
#      it `.env` is ignored (`.gitignore`, the Env block), so the two never
#      meet. Somewhere that line was deleted, step 5 refuses and names `.env` —
#      correctly, because there the file really does shift the verdict key. The
#      fix is the `.gitignore` line, not an allowance here.
#   5. THE ZITADEL CARRY IS A COPY, AND IT IS ANNOUNCED RATHER THAN AUDITED.
#      It moves `ZITADEL_*` lines and nothing else (the closed population), by
#      NAME in the output and never by value. House rule 27's spirit is that
#      the copy is RECORDED; it is not a claim that the credential is valid,
#      current, or yours to use.
#   6. WHETHER A SEEDED `--loop` ROW WILL ACTUALLY HIT. Step 3b copies the
#      source's banked `--loop` verdicts into the clone, and the sentence that
#      used to stand here — that a verify clone begins with an empty ledger — is
#      false from the commit that added that step. What replaced it is narrower
#      than "the clone reuses the builder's verdict": a seeded row hits only
#      when the union IS the branch tip (step 2's *already up to date* case, so
#      main has not moved since the builder's last fold) AND the environment
#      fingerprint matches, which is a MEASURED question rather than an
#      assumption — this clone's `.env` is `.env.example` plus a derived
#      database name plus the identity carry, and the builder's is whatever its
#      own `setup.sh` wrote. A moved main is a `miss(tree)` and belongs to the
#      per-leg-key work that is deferred, not to this step. Every miss says
#      which of the three key lines moved (`scripts/check.sh`'s miss banner).
# ---------------------------------------------------------------------------

set -euo pipefail

# --- it refuses to be piped --------------------------------------------------
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! verify_start refuses pipes — run it bare or redirect to a file." >&2
    echo "   The exit status is the verdict, and a filter replaces it." >&2
    exit 2
fi

usage() {
    cat <<'USAGE'
usage: verify_start.sh <rung-branch> [<destination>]
       verify_start.sh --check [<checkout>]
       verify_start.sh -h

  <rung-branch>   the branch the rung was built on, as this checkout has it.
  <destination>   where the clone goes. Default: $TMPDIR/djb-verify/<branch>.
                  It must not already exist with anything in it.

  --check         run STEP 5 alone — the verdict-key guard — against an
                  existing checkout (default: the one you are standing in).
                  Nothing is cloned, merged or written.

exit: 0 ready · 1 a step ran and failed · 2 refused, or a step could not be
      verified (2 outranks a pass).
USAGE
}

MODE="clone"
BRANCH=""
DEST=""
CHECK_DIR=""

while [ $# -gt 0 ]; do
    case "$1" in
    -h | --help)
        usage
        exit 0
        ;;
    --check)
        MODE="check"
        shift
        if [ $# -gt 0 ]; then
            CHECK_DIR="$1"
            shift
        fi
        [ $# -eq 0 ] || {
            echo "!! --check takes at most one path; got '$1' as well." >&2
            usage >&2
            exit 2
        }
        ;;
    -*)
        # Not a usage nit: a mistyped flag falling through to a silently
        # different run is enforcement misfiring, and that is an exit 2
        # (scripts/check.sh:71-76).
        echo "!! verify_start: unknown option '$1'." >&2
        usage >&2
        exit 2
        ;;
    *)
        if [ -z "$BRANCH" ]; then
            BRANCH="$1"
        elif [ -z "$DEST" ]; then
            DEST="$1"
        else
            echo "!! verify_start takes a branch and at most one destination; got '$1' as well." >&2
            usage >&2
            exit 2
        fi
        shift
        ;;
    esac
done

ROOT=$(cd "$(dirname "$0")/.." && pwd)

STEP_TOTAL=5

# --- the three ways this can end ---------------------------------------------
#
# REFUSED and COULD-NOT-VERIFY are both exit 2 and are printed differently on
# purpose: the first promises nothing was created, and that promise stops being
# true once step 1 has run.

refuse() {
    printf '\n!! %s\n' "$1" >&2
    shift
    while [ $# -gt 0 ]; do
        printf '   %s\n' "$1" >&2
        shift
    done
    printf '   Nothing was cloned, merged or written.\n' >&2
    exit 2
}

cannot_verify() {
    printf '\n!! step %d could not be VERIFIED: %s\n' "$STEP_N" "$1" >&2
    shift
    while [ $# -gt 0 ]; do
        printf '   %s\n' "$1" >&2
        shift
    done
    printf '   The step may have done its work; this script could not prove it,\n' >&2
    printf '   and a step it cannot prove is never reported as done.\n' >&2
    exit 2
}

act_failed() {
    # The act RAN and came back non-zero. That is a different fact from "could
    # not look", and it gets the different code (deploy/release.sh:27-34).
    printf '\n!! step %d FAILED: %s exited %s\n' "$STEP_N" "$1" "$2" >&2
    printf '   Its output is above, unfiltered.\n' >&2
    exit 1
}

# --- the clock ---------------------------------------------------------------
#
# `rung_start.sh`'s, deliberately identical: the number a report re-measures
# must mean the same thing in both instruments.

CLOCK=""
_probe=$(date +%s%3N 2>/dev/null || echo x)
if [ -n "${EPOCHREALTIME:-}" ]; then
    CLOCK=bash5
elif case "$_probe" in '' | *[!0-9]*) false ;; *) true ;; esac; then
    CLOCK=gnudate
elif command -v perl >/dev/null 2>&1; then
    CLOCK=perl
elif command -v python3 >/dev/null 2>&1; then
    CLOCK=python3
else
    CLOCK=seconds
fi

now_ms() {
    case "$CLOCK" in
    bash5)
        local us=${EPOCHREALTIME/./}
        printf '%s' "${us%???}"
        ;;
    gnudate) date +%s%3N ;;
    perl) perl -MTime::HiRes=time -e 'printf "%.0f", time()*1000' ;;
    python3) python3 -c 'import time; print(int(time.time()*1000))' ;;
    *) printf '%s000' "$(date +%s)" ;;
    esac
}

fmt_ms() {
    awk -v ms="$1" 'BEGIN { printf "%.2fs", ms / 1000 }'
}

STEP_N=0
STEP_START=0
RUN_START=$(now_ms)

step_begin() {
    STEP_N=$((STEP_N + 1))
    STEP_START=$(now_ms)
    printf '\n== step %d/%d · %s\n' "$STEP_N" "$STEP_TOTAL" "$1"
}

step_end() {
    local now
    now=$(now_ms)
    printf '   [%s] step %d done\n' "$(fmt_ms $((now - STEP_START)))" "$STEP_N"
}

say() { printf '   %s\n' "$*"; }

# =============================================================================
# THE VERDICT-KEY GUARD — step 5's body, and `--check`'s whole job.
# =============================================================================
#
# ONE FUNCTION, TWO ENTRY POINTS, because a guard a verifier can only get at by
# cloning is a guard nobody runs on the checkout that actually has the stray
# file in it.
#
# What counts as a stray: EVERY `git status --porcelain` entry except an
# untracked file whose name ends `.log`. A modified tracked file counts — it
# moves the key exactly as an untracked one does, and in a freshly made clone
# it also means something wrote to the tree that had no business writing to it.

strays_in() {
    # Prints one porcelain line per stray. Silent when the tree is clean.
    local dir="$1" line path
    git -C "$dir" status --porcelain | while IFS= read -r line; do
        [ -n "$line" ] || continue
        case "$line" in
        '?? '*)
            path="${line#?? }"
            case "$path" in
            *.log) continue ;;
            esac
            ;;
        esac
        printf '%s\n' "$line"
    done
}

verdict_key_guard() {
    # $1 = the checkout to look at, $2 = what to call it in the output.
    local dir="$1" label="$2" strays
    git -C "$dir" rev-parse --git-dir >/dev/null 2>&1 ||
        cannot_verify "$label is not a git checkout: $dir" \
            "There is no working tree to read a verdict key off."

    strays="$(strays_in "$dir")"
    if [ -z "$strays" ]; then
        say "clean        \`git status --porcelain\` in $label is empty but for ignored files"
        say "             (untracked \`*.log\` is the one allowance, and it is ignored here anyway)"
        return 0
    fi

    printf '\n!! STRAY FILES in %s — REFUSING to call this checkout ready.\n' "$dir" >&2
    printf '   The gate keys its verdict on the working tree measured through\n' >&2
    printf '   `git add -A`, so every one of these SHIFTS THE KEY. A green full\n' >&2
    printf '   gate over this tree banks a verdict against a tree nothing will\n' >&2
    printf '   present again, and the next run measures the whole thing over.\n' >&2
    printf '   Only an untracked `*.log` is allowed. These are not:\n\n' >&2
    printf '%s\n' "$strays" | sed 's/^/     /' >&2
    printf '\n   Remove them, ignore them, or commit them — deliberately.\n' >&2
    exit 2
}

# =============================================================================
# --check · the guard alone
# =============================================================================
if [ "$MODE" = "check" ]; then
    if [ -z "$CHECK_DIR" ]; then
        CHECK_DIR="$(git rev-parse --show-toplevel 2>/dev/null || true)"
        [ -n "$CHECK_DIR" ] ||
            refuse "no checkout to look at." \
                "You are not standing in a git checkout, and --check was given no path."
    fi
    [ -d "$CHECK_DIR" ] ||
        refuse "no such directory: $CHECK_DIR"
    CHECK_DIR="$(cd "$CHECK_DIR" && pwd)"
    printf '== verify_start --check · %s\n' "$CHECK_DIR"
    # The guard is the LAST step, derived rather than typed: a hand-written 4
    # here goes quietly wrong the day a step is inserted in front of it, which
    # is the same staleness a `step 1/4` assertion has already had once in the
    # sibling drive.
    STEP_N="$STEP_TOTAL"
    verdict_key_guard "$CHECK_DIR" "this checkout"
    printf '\n== CLEAN · no stray file shifts this tree'\''s verdict key.\n'
    exit 0
fi

# =============================================================================
[ -n "$BRANCH" ] || {
    echo "!! verify_start needs the rung branch to verify." >&2
    usage >&2
    exit 2
}

cd "$ROOT"

git rev-parse --git-dir >/dev/null 2>&1 ||
    refuse "this is not a git checkout: $ROOT"

git rev-parse --verify --quiet "refs/heads/${BRANCH}" >/dev/null ||
    refuse "no local branch '${BRANCH}' in this repository." \
        "A rung branch is verified from the checkout the PM merges in, and this" \
        "one does not have it. Fetch it, or name the branch as this checkout has it."

MAIN_SHA=$(git rev-parse --verify --quiet main || true)
[ -n "$MAIN_SHA" ] ||
    refuse "no local branch 'main' in this repository." \
        "The union this script builds is the rung branch merged with local main," \
        "and main does not resolve."

# The default destination, derived: the branch name, sanitised the way `db.sh`
# sanitises it for a database name, under the machine's scratch directory. It is
# printed either way, because a verifier who does not know where their clone
# went has a clone they will not tear down.
if [ -z "$DEST" ]; then
    SAFE_BRANCH="$(printf '%s' "$BRANCH" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '-')"
    TMPROOT="${TMPDIR:-/tmp}"
    TMPROOT="${TMPROOT%/}"
    DEST="${TMPROOT}/djb-verify/${SAFE_BRANCH}"
fi
case "$DEST" in
/*) ;;
*) DEST="$(pwd)/${DEST}" ;;
esac

if [ -e "$DEST" ]; then
    [ -d "$DEST" ] ||
        refuse "the destination exists and is not a directory: $DEST"
    if [ -n "$(ls -A "$DEST" 2>/dev/null || true)" ]; then
        refuse "the destination is not empty: $DEST" \
            "Cloning over it would destroy whatever verification is already there." \
            "Remove it deliberately, or name another destination."
    fi
fi

printf '== verify_start · %s\n' "$ROOT"
say "branch       $BRANCH  $(git log -1 --format='%h  %s' "$BRANCH")"
say "main         $(git log -1 --format='%h  %s' "$MAIN_SHA")"
say "destination  $DEST"

# =============================================================================
# STEP 1 · CLONE
# =============================================================================
step_begin "clone — this checkout, at the rung branch, into its own directory"

# THE DIRTY-SOURCE REFUSAL, before anything is created. `git clone` copies
# committed state; uncommitted work here would be invisible from inside the
# clone, which is the worst shape a verification error can take.
SOURCE_STRAYS="$(strays_in "$ROOT")"

# DOCS DIRT IN THE SOURCE IS ANNOUNCED, NOT REFUSED, and the scope of
# that sentence is this call site and nowhere else.
#
# THE MEASURED PROBLEM. The PM's own working copy of `docs/product/` is dirty
# for most of a cycle — a staged in-flight row, an unsaved ledger edit — and
# every verifier dispatched in that window was refused here and cloned by hand
# instead. Three of them in one day. The refusal was doing its job on a class it
# was never aimed at: `git clone` copies committed state, and the reason that
# matters is that the verifier would measure DIFFERENT CODE. A dirty
# `docs/product/` file changes no code and moves no verdict key in the clone.
#
# WHAT IS DISCLOSED INSTEAD, because the honest risk is not zero: a verifier
# reads its criteria from the cycle file IN THE CLONE, i.e. from HEAD. If the
# criteria it is about to work from are uncommitted here, they are not in the
# clone either — so every ignored path is printed BY NAME.
#
# NOT `strays_in`, WHICH IS SHARED. That function is also step 5's verdict-key
# guard and `--check`'s whole body, where a stray `docs/product/` file in a
# CLONE is a real finding — something wrote into a tree that had no business
# being written to. Loosening it there would take the teeth out of the guard
# this script exists to run. The narrowing lives here, at the one call site
# whose subject is the SOURCE.
SOURCE_DIRT_ALL_DOCS=""
if [ -n "$SOURCE_STRAYS" ]; then
    SOURCE_DIRT_ALL_DOCS=1
    while IFS= read -r stray_line; do
        [ -n "$stray_line" ] || continue
        # Porcelain is `XY <path>`; a rename is `R  old -> new` and the
        # destination is what would be in the clone. Both halves are tested, so
        # a rename that moves a code file OUT of docs/ still refuses.
        stray_path="${stray_line#???}"
        case "$stray_path" in
        *" -> "*) stray_path="${stray_path##* -> }" ;;
        esac
        case "$stray_path" in
        docs/product/*) ;;
        *)
            SOURCE_DIRT_ALL_DOCS=""
            break
            ;;
        esac
    done <<EOF
$SOURCE_STRAYS
EOF
fi

if [ -n "$SOURCE_STRAYS" ] && [ -n "$SOURCE_DIRT_ALL_DOCS" ]; then
    STRAY_COUNT=$(printf '%s\n' "$SOURCE_STRAYS" | grep -c . || true)
    say "docs dirt    ${STRAY_COUNT} path(s) under docs/product/ are dirty here and are NOT in"
    say "             the clone — a criterion read from an uncommitted plan is not in"
    say "             this clone either. Cloning from HEAD anyway:"
    printf '%s\n' "$SOURCE_STRAYS" | while IFS= read -r stray_line; do
        [ -n "$stray_line" ] || continue
        say "               ${stray_line}"
    done
    SOURCE_STRAYS=""
fi

if [ -n "$SOURCE_STRAYS" ]; then
    printf '\n!! this checkout has uncommitted work — REFUSING to clone it.\n' >&2
    printf '   `git clone` copies COMMITTED state only, so the verifier would\n' >&2
    printf '   measure a tree that differs from the one you are looking at, and\n' >&2
    printf '   nothing inside the clone could tell them. Untracked `*.log` files\n' >&2
    printf '   are allowed and none of these are:\n\n' >&2
    printf '%s\n' "$SOURCE_STRAYS" | sed 's/^/     /' >&2
    printf '\n   Commit them, stash them, or discard them by hand — deliberately.\n' >&2
    printf '   Nothing was cloned, merged or written.\n' >&2
    exit 2
fi

# A BYTE COPY OF THE SOURCE LEDGER, TAKEN BEFORE ANYTHING IS CREATED. Step 3b
# copies rows OUT of this file and must never write into it, and `cmp` after the
# copy is what turns that from a claim into a check.
#
# `cmp`, NOT A DIGEST, and that is this file's rule rather than a preference:
# `verify_start.sh` computes no hashes at all — the path-hash arithmetic belongs
# to `scripts/db.sh` and a second copy of it here is the thing the seam exists
# to prevent, which this drive's own case pins by looking for `shasum` in the
# executable text. A byte comparison is also the stronger assertion.
SRC_LEDGER_COPY=""
SRC_COMMON_EARLY=$(git -C "$ROOT" rev-parse --git-common-dir 2>/dev/null || true)
case "$SRC_COMMON_EARLY" in
"") ;;
/*) ;;
*) SRC_COMMON_EARLY="${ROOT}/${SRC_COMMON_EARLY}" ;;
esac
if [ -n "$SRC_COMMON_EARLY" ] && [ -f "${SRC_COMMON_EARLY}/djb-loop-verdicts" ]; then
    SRC_LEDGER_COPY=$(mktemp "${TMPDIR:-/tmp}/djb-verify-src-ledger.XXXXXX") || SRC_LEDGER_COPY=""
    [ -n "$SRC_LEDGER_COPY" ] && cp "${SRC_COMMON_EARLY}/djb-loop-verdicts" "$SRC_LEDGER_COPY"
fi

set +e
git clone --quiet --branch "$BRANCH" "$ROOT" "$DEST"
rc=$?
set -e
[ $rc -eq 0 ] || act_failed "git clone" "$rc"

[ -d "${DEST}/.git" ] ||
    cannot_verify "git clone exited 0 and ${DEST}/.git is not there." \
        "There is no clone for the next three steps to work in."

CLONE_HEAD="$(git -C "$DEST" rev-parse HEAD)"
[ "$CLONE_HEAD" = "$(git rev-parse "refs/heads/${BRANCH}")" ] ||
    cannot_verify "the clone's HEAD is ${CLONE_HEAD}, and ${BRANCH} here is $(git rev-parse "refs/heads/${BRANCH}")." \
        "The clone did not land on the branch it was aimed at."

say "cloned       $DEST"
say "HEAD         $(git -C "$DEST" log -1 --format='%h  %s' HEAD)"
step_end

# =============================================================================
# STEP 2 · UNION MERGE
# =============================================================================
#
# THE STEP THAT GETS SKIPPED, and the reason this script exists at all. A rung
# verified against its own branch is verified against a tree that will never
# exist: what lands is the branch UNION main, and a criterion that passes on one
# and fails on the other is exactly the finding a field test is for.
step_begin "union merge — local main, merged into the rung branch"

ORIGIN_MAIN="$(git -C "$DEST" rev-parse --verify --quiet refs/remotes/origin/main || true)"
[ -n "$ORIGIN_MAIN" ] ||
    cannot_verify "the clone carries no origin/main." \
        "There is nothing to merge the rung branch with."
[ "$ORIGIN_MAIN" = "$MAIN_SHA" ] ||
    cannot_verify "the clone's origin/main is ${ORIGIN_MAIN}; this checkout's main is ${MAIN_SHA}." \
        "The clone did not carry the main this run announced."

say "origin/main  $(git -C "$DEST" log -1 --format='%h  %s' "$ORIGIN_MAIN")"

# THE LOCAL `refs/heads/main`, CREATED HERE, and it is a pairing rather than a
# convenience. `git clone --branch <rung branch>` leaves the clone with exactly
# one local head — the rung's — and main only as a REMOTE ref. Every derivation
# in this repository that asks "what did the active rung change" forks from the
# LOCAL `refs/heads/main`, spelled in full, for the reasons
# `scripts/secrets_scan.sh` argues there. In a clone with no such ref those
# derivations fall back to a thin basis, and `scripts/loop_tier.sh` now REFUSES
# that basis outright rather than grading a rung against a scope its committed
# work never reached. Without this line the house's own verification tool would
# be the first thing to trip its own refusal.
#
# SET TO THE IDENTITY THIS SCRIPT ALREADY VERIFIED, three lines up: the clone's
# origin/main was compared against the source checkout's main and refused if
# they differed, so `$ORIGIN_MAIN` is `$MAIN_SHA` by the time this runs. Created
# with `git branch`, which refuses to clobber an existing head — if a future
# clone ever arrives carrying one, this is loud rather than silently rewriting
# somebody else's idea of main.
if git -C "$DEST" rev-parse -q --verify refs/heads/main >/dev/null 2>&1; then
    say "main ref     the clone already carries refs/heads/main — left alone"
else
    git -C "$DEST" branch main "$ORIGIN_MAIN" ||
        cannot_verify "could not create refs/heads/main in the clone at ${ORIGIN_MAIN}." \
            "Every changed-file derivation in this tree forks from that ref."
    say "main ref     refs/heads/main created at $(git -C "$DEST" rev-parse --short "$ORIGIN_MAIN") (the verified MAIN_SHA)"
fi

if git -C "$DEST" merge-base --is-ancestor "$ORIGIN_MAIN" HEAD; then
    say "already up to date — the rung branch already contains main's tip"
    say "union        $(git -C "$DEST" rev-parse HEAD)  (= the branch tip; no merge commit)"
else
    set +e
    git -C "$DEST" \
        -c user.name="${GIT_AUTHOR_NAME:-verify_start}" \
        -c user.email="${GIT_AUTHOR_EMAIL:-verify-start@localhost}" \
        merge --no-edit --no-ff "$ORIGIN_MAIN" \
        -m "verify_start: ${BRANCH} union main for verification"
    rc=$?
    set -e
    if [ $rc -ne 0 ]; then
        printf '\n!! the rung branch and main CONFLICT.\n' >&2
        printf '   The union this verification is about cannot be built without a\n' >&2
        printf '   human deciding what it means. The unmerged paths:\n\n' >&2
        git -C "$DEST" diff --name-only --diff-filter=U | sed 's/^/     /' >&2
        printf '\n   The clone is left AT THE CONFLICT, on purpose, so it can be read:\n' >&2
        printf '     %s\n' "$DEST" >&2
        printf '   Whether this is the rung'\''s doing, main'\''s, or a PM ordering\n' >&2
        printf '   failure is a judgement this script does not make.\n' >&2
        exit 1
    fi
    say "union        $(git -C "$DEST" rev-parse HEAD)  (merge commit)"
fi

# Both halves really are in the tree now, whichever branch above ran.
git -C "$DEST" merge-base --is-ancestor "$ORIGIN_MAIN" HEAD ||
    cannot_verify "main is still not an ancestor of the clone's HEAD after the merge." \
        "The merge reported success over a tree that is not the union."
git -C "$DEST" merge-base --is-ancestor "$CLONE_HEAD" HEAD ||
    cannot_verify "the rung branch tip ${CLONE_HEAD} is not an ancestor of the clone's HEAD." \
        "The merge reported success over a tree that is not the union."

say "verified     both parents are ancestors of the union"
step_end

# =============================================================================
# STEP 3 · ENVIRONMENT
# =============================================================================
#
# EVERY VALUE HERE IS PRINTED AND NONE OF IT IS SOURCED. The header says what
# that cost somebody; this is the step it is about.
step_begin "environment — .env, this clone's own derived database name, the identity carry"

[ -f "${DEST}/.env.example" ] ||
    cannot_verify "the clone has no .env.example." \
        "There is nothing to derive this clone's environment from."
cp "${DEST}/.env.example" "${DEST}/.env"
say ".env         created from .env.example"

# THE DERIVATION IS ASKED FOR, NEVER RE-IMPLEMENTED. `scripts/db.sh` is sourced
# INSIDE THE CLONE, in a subshell, so the name it derives is the CLONE's — the
# arithmetic is `db.sh`'s and the path hash follows the checkout
# (`scripts/db.sh`, the header's rule 2). A second copy of that arithmetic in
# this file is the drift class this repository names everywhere else.
[ -r "${DEST}/scripts/db.sh" ] ||
    cannot_verify "the clone has no readable scripts/db.sh." \
        "It is the one seam this script derives a database name through."

# `DATABASE_NAME=''` in front of the subshell is load-bearing. db.sh's rule 1 is
# that a name already in the ENVIRONMENT wins — correct for a checkout acting on
# its own behalf, and wrong here, because a verifier's shell very often carries
# the name of the checkout they came FROM. Empty is treated as unset by db.sh's
# `:-`, so this asks for the derivation and gets it.
if [ -n "${DATABASE_NAME:-}" ]; then
    say "note: DATABASE_NAME=${DATABASE_NAME} is set in this shell and is IGNORED here —"
    say "      the clone derives its own, or two checkouts share one database."
fi
DERIVED="$(cd "$DEST" && DATABASE_NAME='' bash -c '. ./scripts/db.sh 2>/dev/null; printf "%s" "${DATABASE_NAME:-}"')"
[ -n "$DERIVED" ] ||
    cannot_verify "the clone's scripts/db.sh derived no DATABASE_NAME." \
        "The one seam this script consumes did not answer."

if grep -qE '^DATABASE_NAME=' "${DEST}/.env"; then
    tmp=$(mktemp "${DEST}/.env.verify_start.XXXXXX")
    DBN="$DERIVED" awk '
        /^DATABASE_NAME=/ { print "DATABASE_NAME=" ENVIRON["DBN"]; next }
        { print }
    ' "${DEST}/.env" >"$tmp"
    mv "$tmp" "${DEST}/.env"
else
    printf 'DATABASE_NAME=%s\n' "$DERIVED" >>"${DEST}/.env"
fi
say "database     $DERIVED"
say "             derived by the clone's own scripts/db.sh, not by this script"

# --- THE ZITADEL CARRY -------------------------------------------------------
#
# THE CLOSED POPULATION IS `ZITADEL_*` AND NOTHING ELSE. A fresh checkout's
# `.env` comes from `.env.example`, where the identity credential is blank, so a
# verifier probing the real instance used to hand-copy it out of another
# checkout — an unrecorded copy of a credential, which is the one thing house
# rule 27 is about. Carrying it is fine; carrying it SILENTLY is not, so every
# key that moves is announced BY NAME. No value is ever printed, and no value is
# ever read into this shell.
CARRIED=0
CARRIED_NAMES=""
SKIPPED_EMPTY=""
if [ -f "${ROOT}/.env" ]; then
    while IFS= read -r zline; do
        [ -n "$zline" ] || continue
        zkey="${zline%%=*}"
        zval="${zline#*=}"
        if [ -z "$zval" ]; then
            SKIPPED_EMPTY="${SKIPPED_EMPTY}${SKIPPED_EMPTY:+ }${zkey}"
            continue
        fi
        if grep -qE "^${zkey}=" "${DEST}/.env"; then
            tmp=$(mktemp "${DEST}/.env.verify_start.XXXXXX")
            ZK="$zkey" ZL="$zline" awk '
                $0 ~ "^" ENVIRON["ZK"] "=" { print ENVIRON["ZL"]; next }
                { print }
            ' "${DEST}/.env" >"$tmp"
            mv "$tmp" "${DEST}/.env"
        else
            printf '%s\n' "$zline" >>"${DEST}/.env"
        fi
        CARRIED=$((CARRIED + 1))
        CARRIED_NAMES="${CARRIED_NAMES}${CARRIED_NAMES:+ }${zkey}"
    done <<EOF
$(grep -E '^ZITADEL_[A-Z0-9_]+=' "${ROOT}/.env" || true)
EOF
fi

if [ "$CARRIED" -gt 0 ]; then
    say "zitadel      carried ${CARRIED} key(s) from ${ROOT}/.env, BY NAME ONLY:"
    for zkey in $CARRIED_NAMES; do
        say "               $zkey"
    done
    say "             (values are never printed and never enter this shell; house rule 27)"
elif [ -n "$SKIPPED_EMPTY" ]; then
    say "zitadel      nothing carried — every ZITADEL_* line in ${ROOT}/.env is empty."
    say "             the clone keeps .env.example's defaults."
elif [ -f "${ROOT}/.env" ]; then
    say "zitadel      nothing carried — no ZITADEL_* line in ${ROOT}/.env."
else
    say "zitadel      nothing carried — this checkout has no .env to carry from."
fi
# An empty line in the primary is not a carry and is not a silence either: a
# verifier whose probe fails because the credential was blank at the SOURCE
# should read that here rather than discover it against the live instance.
if [ -n "$SKIPPED_EMPTY" ] && [ "$CARRIED" -gt 0 ]; then
    say "             not carried, empty in ${ROOT}/.env:"
    for zkey in $SKIPPED_EMPTY; do
        say "               $zkey"
    done
fi

# The whole point of the step, said out loud where the values are.
printf '\n'
say "NOT SOURCED  every value above was PRINTED. This script never reads that"
say "             file into its own shell — the header records what that cost a"
say "             sibling product, and it was three gate runs."
step_end

# =============================================================================
# STEP 4 · THE LOOP-VERDICT SEED
# =============================================================================
#
# WHY A CLONE STARTS BLIND, AND WHY THAT IS WORTH FIXING. `--loop` banks a
# verdict keyed on tree + environment + scope (`scripts/gate_ledger.sh`, the
# loop-ledger section). The ledger lives beside the repository, in the common
# git dir — so `git clone` never brings it, and a verifier's first `--loop` in a
# fresh clone re-measures a suite the builder measured minutes earlier on the
# very same bytes. Measured: a fresh clone has no `djb-` file in `.git` at all.
#
# WHEN A SEEDED ROW ACTUALLY HITS, stated here so nobody reads more into this
# than it does: the key's tree and HEAD lines equal the builder's only when the
# union IS the branch tip — the *already up to date* case in step 2, i.e. main
# has not moved since the builder's last fold. A moved main is an honest miss
# and a full re-measure. The `.env` line is the other half and it is NOT equal
# by construction: this clone's `.env` is `.env.example` plus a derived database
# name (excluded from the fingerprint) plus the identity carry, while the
# builder's is whatever its own `setup.sh` wrote. That is a measured question,
# not an assumption — which is why the miss banner prints the five components.
#
# BEFORE STEP 5, DELIBERATELY. The file lands inside `.git/`, which the verdict
# key guard does not look at, and the assertion below says so rather than
# trusting it: a seed that made the clone dirty would defeat the guard this
# script exists to run.
# >>> seed: the source's banked --loop rows >>>
step_begin "loop-verdict seed — the source's banked --loop rows, copied into the clone"

SRC_COMMON=$(git -C "$ROOT" rev-parse --git-common-dir 2>/dev/null || true)
case "$SRC_COMMON" in
"") SRC_COMMON="" ;;
/*) ;;
*) SRC_COMMON="${ROOT}/${SRC_COMMON}" ;;
esac
SRC_LEDGER=""
[ -n "$SRC_COMMON" ] && SRC_LEDGER="${SRC_COMMON}/djb-loop-verdicts"
DEST_LEDGER="${DEST}/.git/djb-loop-verdicts"

if [ -z "$SRC_LEDGER" ] || [ ! -f "$SRC_LEDGER" ]; then
    say "ledger not seeded: ${SRC_LEDGER:-<no common git dir>} has no loop ledger"
    say "             A NAMED ABSENCE, never silence — the clone's first --loop will"
    say "             re-measure, which is correct and is not an error."
else
    SEEDED=0
    SKIPPED=0
    : >"$DEST_LEDGER"
    # SCHEMA-CHECKED LINE BY LINE, and a line that does not match is SKIPPED AND
    # COUNTED. Copying a malformed line would put a row the lookup can never
    # match into a file whose whole purpose is to be matched; dropping it in
    # silence would hide a source ledger that had started to rot.
    while IFS= read -r ledger_line || [ -n "$ledger_line" ]; do
        [ -n "$ledger_line" ] || continue
        if printf '%s' "$ledger_line" |
            grep -E '^loop-v1 loop-v1:[0-9a-f]{64} loop ' >/dev/null; then
            printf '%s\n' "$ledger_line" >>"$DEST_LEDGER"
            SEEDED=$((SEEDED + 1))
        else
            SKIPPED=$((SKIPPED + 1))
        fi
    done <"$SRC_LEDGER"
    printf 'seeded=%s from=%s\n' "$SEEDED" "$SRC_LEDGER" >"${DEST_LEDGER}-seed"
    say "ledger seeded: ${SEEDED} loop rows from ${SRC_LEDGER} (${SKIPPED} skipped: not loop-v1)"
fi

# READ-ONLY TOWARD THE SOURCE, asserted rather than asserted-in-a-comment. The
# only writes above are into `$DEST`; this re-reads the source's digest and
# refuses if it moved, because "I only read it" is exactly the claim every
# accidental writer has made.
if [ -n "$SRC_LEDGER" ] && [ -f "$SRC_LEDGER" ] && [ -n "$SRC_LEDGER_COPY" ]; then
    if cmp -s "$SRC_LEDGER" "$SRC_LEDGER_COPY"; then
        say "read-only    the source's loop ledger is byte-identical to before the clone"
    else
        rm -f "$SRC_LEDGER_COPY"
        cannot_verify "the SOURCE's loop ledger changed while it was being copied." \
            "This step reads the source and writes only into the clone."
    fi
fi
rm -f "$SRC_LEDGER_COPY"

# The file must be inside `.git/`, or step 5 is about to refuse a tree this
# script dirtied itself.
case "$DEST_LEDGER" in
"${DEST}/.git/"*) say "inside .git  ${DEST_LEDGER} — invisible to the verdict-key guard below" ;;
*) cannot_verify "the seeded ledger path ${DEST_LEDGER} is not inside ${DEST}/.git." \
    "It would be a stray file, and step 5 would refuse the clone this script just made." ;;
esac
step_end
# <<< seed: the source's banked --loop rows <<<

# =============================================================================
# STEP 5 · VERDICT KEY
# =============================================================================
step_begin "verdict key — nothing untracked but *.log, or this clone is not ready"
verdict_key_guard "$DEST" "the clone"
step_end

# =============================================================================
TOTAL=$(($(now_ms) - RUN_START))
printf '\n== READY · total %s · %s\n' "$(fmt_ms $TOTAL)" "$(git -C "$DEST" log -1 --format='%h  %s' HEAD)"
printf '   The clone is the union of %s and main, and nothing in it shifts a\n' "$BRANCH"
printf '   verdict key. It has no venv and no database yet — deliberately (header,\n'
printf '   WHAT IT CANNOT SEE 2). From here:\n'
printf '\n'
printf '     cd %s\n' "$DEST"
printf '     ./scripts/setup.sh                       # venv, database, migrate\n'
printf '     ./scripts/check.sh --loop > "$PWD/gate-<your-verification>.log" 2>&1\n'
printf '\n'
printf '   Re-run the guard alone whenever you have written into the tree:\n'
printf '     %s/scripts/verify_start.sh --check %s\n' "$ROOT" "$DEST"
if [ "$CLOCK" = "seconds" ]; then
    printf '   (clock resolution: whole seconds — no sub-second clock on this host)\n'
fi
