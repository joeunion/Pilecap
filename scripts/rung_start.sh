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
# THE RUNG START. One command that takes a freshly spawned
# worktree from whatever the pool handed you to a tree you can build in.
#
#   ./scripts/rung_start.sh              the whole thing, reset included
#   ./scripts/rung_start.sh --resume     the environment only, NO reset
#
# Five steps, unconditionally and in this order, each printing what it did and
# how long it took, with the total at the end:
#
#   1. BASELINE   reset this worktree to local `main`, printing the sha before
#                 and the sha after — and SAYING SO when they differ. This is
#                 the one step `--resume` removes, printing what it skipped.
#   2. VENV       `uv sync`, then prove the interpreter it made can import
#                 Django.
#   3. DATABASE   this checkout's own database, created through `scripts/db.sh`
#                 and migrated, then proved by `migrate --check`.
#   4. STORAGE    this checkout's own object-storage bucket, created through
#                 `manage.py ensure_bucket` and its name written back into
#                 `.env` — setup.sh's step, mirrored.
#   5. INTROSPECT `manage.py introspect` dumped to .rung/introspect.json, then
#                 proved to be JSON.
#
# Exit: 0 the worktree is ready and every step was VERIFIED · 1 a step ran and
# FAILED · 2 could not get far enough to judge (refused, or could not verify).
# 2 outranks a pass, here as everywhere in this repository. The ONE exception is
# named in the footer rather than in the status: step 4's bucket is not fatal,
# and a run that could not make one ends `READY · object storage ABSENT` at
# exit 0 (see 3b below).
#
# ---------------------------------------------------------------------------
# WHY IT EXISTS. Setup choreography once measured 30-50% of a short rung across
# six agents in a row: notice-the-stale-baseline then reset, rebuild the venv,
# create and migrate the database, dump introspect — the same four hand steps,
# every agent, every rung.
# Hand steps done from memory are also hand steps SKIPPED from memory, which
# is the more expensive half: step one skipped is a rung built against a tree
# the criteria never saw.
#
# WHAT IT REFUSES, AND WHY THE REFUSALS ARE THE DESIGN.
#
#   A DIRTY TREE (exit 2, resetting NOTHING). The reset is unconditional only
#   over a CLEAN tree. An unconditional `reset --hard` over uncommitted work is
#   data loss wearing a convenience, and a builder who re-runs this mid-rung —
#   which is exactly what a convenient command invites — must lose nothing.
#   (The engineering lead's amendment, recorded in the platform repository,
#   the archive of record.)
#
#   A BRANCH WITH COMMITS MAIN DOES NOT HAVE (exit 2, resetting NOTHING). The
#   same argument one level up, and the more dangerous half: rung-execution §5
#   tells every builder to COMMIT at each leg boundary, so a mid-rung worktree
#   is routinely clean AND ahead. A dirty-tree guard alone would wave that
#   through and `reset --hard main` would discard finished, committed rung work
#   with no reflog anybody thinks to read. The skill's own step zero already
#   conditions its reset on "and you have not committed yet"
#   (`.claude/skills/rung-execution/SKILL.md:33`); this is that clause, kept.
#
# ---------------------------------------------------------------------------
# --RESUME, AND WHY A REFUSAL NEEDED A DOOR NEXT TO IT.
#
# The commits-ahead refusal above is correct and it re-establishes NOTHING. Its
# closing words are "keep building — your baseline was already established",
# which is true about the BASELINE and false about everything else this script
# does: a builder whose session was killed, whose venv was blown away, whose
# database was swept, or who moved a checkout on disk is clean, ahead, and has
# no environment. Before `--resume` the only answers were to run the four hand
# steps this instrument exists to delete, or to run `./scripts/setup.sh`, which
# is the complete provisioner and does far more.
#
# `--resume` is the same five steps with STEP 1'S RESET REMOVED and nothing
# else changed. It never moves HEAD, never touches a commit, and PRINTS WHAT IT
# SKIPPED — including, loudly, a baseline it did NOT repair, because a stale
# baseline silently tolerated is the one class step 1 was built for.
#
# WHAT --RESUME DOES NOT LIFT, and the answer is every refusal:
#
#   A DIRTY TREE STILL REFUSES. This looks wrong at first — with no reset there
#   is nothing to destroy — and it is not. Steps 3, 4 and 5 WRITE: `.env` is
#   rewritten (DATABASE_NAME, the bucket name, the identity carry below) and
#   `.rung/introspect.json` is overwritten. A builder's uncommitted work
#   routinely includes a hand-edited `.env`, and clobbering that silently while
#   claiming to be the safe flag is worse than the reset it replaced, because
#   the name on the tin says nothing was going to be touched. The guard is the
#   same guard, kept, for the second reason as well as the first.
#
#   A DETACHED HEAD AND A MISSING LOCAL `main` STILL REFUSE. `--resume` turns
#   off the reset, not the reporting. Both refusals are about being able to say
#   what this checkout's baseline IS, and a flag whose contract is "do less"
#   does not get to make the instrument say less truthfully.
#
#   THE PIPE AND THE POSTGRES REFUSALS ARE UNTOUCHED. Neither has anything to
#   do with the reset.
#
# The refusal itself now names the door: a builder who meets the commits-ahead
# refusal is told, in the same breath, the one flag that does what they came
# for.
# ---------------------------------------------------------------------------
#
# THE IDENTITY CARRY (`ZITADEL_*`, and that prefix is the whole population).
#
# A fresh worktree's `.env` is `cp .env.example`, and `.env.example` ships the
# identity credentials BLANK — they are not derivable, they are seeded once per
# machine into the checkout somebody ran `zitadel_seed` in. So a rung that
# probes the real instance began with an UNRECORDED HAND COPY out of another
# checkout, done from memory, by every builder who needed one. That is rule
# 27's subject exactly (`docs/product/architecture.md`: the row is the intent,
# the console is a window) with the recording missing, and it was paid by hand
# once more in the rung immediately before this one.
#
# So when — and ONLY when — this script CREATES `.env` from `.env.example`, it
# copies every `ZITADEL_*` line the PRIMARY checkout's `.env` carries a value
# for, and ANNOUNCES ONE LINE PER KEY NAME.
#
#   THE VALUE IS NEVER PRINTED, by anything, ever. A credential in this
#   script's output is a credential in every rung log, every report that pastes
#   one, and every gate transcript — the leak this carry exists to make
#   unnecessary would become a leak this carry causes. The drive asserts the
#   absence, not just the presence (`scripts/tests/test_rung_start.sh`).
#
#   THE POPULATION IS CLOSED AND IT IS THE PREFIX. `ZITADEL_*` and nothing
#   else: not `SECRET_KEY`, not an API token, not a database URL. A carry that
#   grows a second category grows it silently, into every worktree on the
#   machine, so the population is one prefix, matched on the KEY, and the drive
#   plants a non-`ZITADEL_` secret in the primary and requires it to stay put.
#
#   THE PRIMARY IS `git rev-parse --git-common-dir`'s parent — the checkout the
#   linked worktrees hang off, which is where `zitadel_seed` was run. When this
#   IS that checkout there is nothing to carry from, and it says so.
#
#   AN EXISTING `.env` IS LEFT ALONE, carry included. A `.env` this script did
#   not make is the builder's, and reaching into one to rewrite credential
#   lines on every re-run is a side effect nobody asked for. (`--resume` is
#   therefore never a carry: it runs against a `.env` that already exists.)
#
#   A PIPED STDOUT (exit 2). check.sh's detection and its CI exemption,
#   deliberately identical (`scripts/check.sh:63-66`) and for the same reason:
#   a pipe replaces this script's exit status with the filter's, and
#   the exit status is the verdict. Redirect to a file instead.
#
#   A POSTGRES IT CANNOT REACH (exit 2). It does NOT bring the stack up. The
#   compose stack is shared by every checkout on this machine (`compose.yaml`,
#   `name: djangobootstrap`), and a convenience command that silently starts a
#   stack somebody deliberately stopped is a side effect on other agents' work.
#   The refusal names the one command to run.
#
# WHAT IT CANNOT SEE (declared here, and again in the instrument census):
#
#   1. WHETHER THE CRITERIA MATCH THE TREE. It makes the baseline CURRENT; it
#      has no opinion about whether main's tip is the tree your brief was
#      written against. A brief naming an older sha is still something to flag
#      and hold rather than guess past (`.claude/skills/rung-execution/SKILL.md:35-36`).
#   2. THE POOL ITSELF. It REPORTS why worktrees spawn stale and repairs this
#      one; the lever that stops them spawning stale is not in this repository
#      (see THE POOL below). A green run means this checkout is current, never
#      that the next one will be.
#   3. ANYTHING SETUP.SH DOES BEYOND THESE FIVE STEPS. No Zitadel seed, no
#      `docker compose up`, no Meili index. A rung needing one of those runs
#      `./scripts/setup.sh`, which is the complete provisioner and always was;
#      this is the fast path through the part every rung needs. **The bucket
#      joined that part later**: a worktree provisioned by this script
#      used to start with object storage OFF — `storage_audit` exit 2, the
#      integrations census reading NOT CONFIGURED — so a files or exports
#      builder spent their first discovery on a slot that was never going to be
#      filled, and a second builder then spent a second one confirming it. One
#      step, mirroring `scripts/setup.sh:446`, closes it for every rung at once.
#   3b. AND THE BUCKET STEP IS NOT FATAL, deliberately, where the database is.
#      Steps 3, 4 and 5 all need Postgres, so an unreachable one is a refusal;
#      almost no rung needs MinIO, so an unreachable one is a NAMED ABSENCE and
#      the run still ends ready. It is loud (setup.sh's shape, argued the other way) and the
#      final line says `READY · object storage ABSENT` rather than a bare
#      `READY`, because a footer that reads the same either way is the silence
#      this step exists to end.
#   3c. AND IT CANNOT SEE A STALE BUCKET PIN. An `AWS_STORAGE_BUCKET_NAME`
#      already in `.env` WINS and is NOT compared against what this checkout
#      would derive — so a `.env` copied from another worktree, or a checkout
#      moved on disk, silently points this tree's uploads, downloads and
#      exports at ANOTHER CHECKOUT'S BUCKET. That is the same hazard
#      `DATABASE_NAME` has one organ over, and `DATABASE_NAME` has an exit status for it
#      (`scripts/db.sh::db_pin_leg`, a `--fast` gate leg) where storage has
#      nothing at all. It is NOT closed here on purpose: the comparison needs
#      the derivation, and re-implementing that in shell is the second copy
#      this step's whole shape exists to avoid (see STEP 4 below). What it
#      needs is a read-only door on `apps/files/storage.py::
#      derived_bucket_name` — a `manage.py ensure_bucket --check`, or a
#      `storage_audit` verdict for it — and then this script comparing the two
#      the way `db.sh` does. That is `apps/files`' to add, and declared here
#      so the gap is stated rather than
#      discovered by whoever meets it.
#   4. WHETHER THE MIGRATED SCHEMA IS THE RIGHT ONE. `migrate --check` proves
#      nothing is UNAPPLIED. A migration that applied and is wrong is the
#      gate's subject, not this script's.
#   5. THE .ENV PIN POLICY IS A SECOND COPY — the WRITE half of it, and no
#      longer the read. The reconcile-or-leave-alone behaviour below is
#      setup.sh's, re-implemented rather than shared, because setup.sh is a
#      script that runs top to bottom and cannot be sourced for one function.
#      The MARKER TEST itself is no longer copied: both scripts call
#      `db_pin_marked` out of the `db.sh` they already source. That copy was
#      the one that mattered — when the marker's grammar changed (its own
#      comment line above a bare value; `scripts/db.sh`, "THE MARKER'S
#      GRAMMAR") a hand copy left behind here would have gone on rewriting a
#      line a human pinned on purpose. What remains copied is behaviour a test
#      can see: `scripts/tests/test_rung_start.sh` drives this side so a
#      divergence in the write half is at least loud here.
#   6. WHETHER A CARRIED CREDENTIAL STILL WORKS. The carry copies what the
#      primary checkout HAS. An expired PAT, or one seeded against a Zitadel
#      instance that has since been rebuilt, is copied faithfully and this
#      script has no idea. `manage.py zitadel_audit` is the instrument that
#      does (house rule 27), and it is a rung's to run, not a provisioner's.
#   7. A `.env` THIS SCRIPT DID NOT CREATE GETS NO CARRY AT ALL — deliberately
#      (see THE IDENTITY CARRY above), which means a worktree provisioned
#      before this change, or one whose `.env` was made by `setup.sh`, still
#      has the blank credentials it always had. The fix for one of those is to
#      copy the line by hand, exactly as before; this closes the class only
#      going forward.
#
# --- THE SOURCED SEAM (why `return` appears below the functions) -------------
#
# The identity carry is a FUNCTION and this file returns early when it is
# SOURCED rather than executed, so that `scripts/tests/test_rung_start.sh` can
# drive that one function against fixture `.env` files — a real primary, an
# empty one, a planted non-`ZITADEL_` secret — without a venv, a Postgres or a
# MinIO behind it. Every other case in that drive dies in step 2 for exactly
# that reason (its blind spot 1), and a carry proved only by reading the source
# would be a credential mechanism nothing exercises.
#
# It is `[ "${BASH_SOURCE[0]}" != "$0" ]` and not an environment variable ON
# PURPOSE: an env-var switch is a switch somebody can export and then get a
# silent, successful no-op out of an instrument whose whole value is that it
# ran. Executed, the two are equal and nothing is skipped; there is no way to
# ask for the early return from the command line.
#
# THE POOL — why a fresh worktree arrives 78-96 commits behind main.
#
# Every worktree branch in this repository is created from `origin/main`, not
# from local `main`. Git records it in the branch's own reflog, in these words:
#
#     $ git reflog show worktree-agent-a2dcd8b8dd52a2dbb
#     f5ebf9f ...: branch: Created from origin/main
#
# and every sampled peer branch says the same thing. `origin/main` is a
# remote-tracking ref: it moves only when somebody pushes or fetches. This
# loop's PM merges rungs into LOCAL main continuously and pushes rarely, so
# `origin/main` is a snapshot of the last push and every worktree spawned after
# it inherits that snapshot. On 2026-08-24 the last push was 09:20 and the pool
# was still handing out its commit at 19:21 — 96 commits and ten hours of
# merged work later. Nine sightings that wave; the cause is one line of git.
#
# THE LEVER IS NOT IN THIS REPOSITORY. The branch is created by the agent
# harness, outside the tree, before any file here is read; nothing in `scripts/`
# runs early enough to choose a different base. Two things WOULD close it, and
# both are somebody else's to do: the harness basing new worktrees on the
# checked-out branch instead of `origin/main`, or the PM pushing main after each
# merge so that `origin/main` and `main` do not drift apart in the first place
# (`scripts/pm_push.sh` is that push, already built). Until one of them happens,
# step 1 is the belt: it repairs the checkout it is run in and PRINTS THE GAP so
# the class cannot be mistaken for this worktree's bad luck.
# ---------------------------------------------------------------------------

set -euo pipefail

# --- the identity carry -------------------------------------------------------
#
# See THE IDENTITY CARRY in the header for why this exists and what it refuses
# to grow into. KEY NAMES are printed; NO LINE IN THIS FUNCTION PRINTS A VALUE,
# and that absence is what the drive asserts rather than merely the presence of
# the names.
#
#   zitadel_carry <the primary checkout's .env> <this checkout's .env>
#
# It always returns 0. A primary with nothing to carry is an ordinary machine
# nobody has seeded yet, not a failure, and the announcement is the deliverable
# either way: the copy is RECORDED, which is the whole point (house rule 27).
zitadel_carry() {
    local primary="$1" target="$2"
    local line key tmp
    local carried=0

    if [ ! -r "$primary" ]; then
        printf '   identity     the primary checkout has no readable .env — nothing carried\n'
        printf '                (%s)\n' "$primary"
        return 0
    fi

    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in
        ZITADEL_*=*) ;;
        *) continue ;;
        esac
        key=${line%%=*}
        # THE POPULATION, asserted on the KEY rather than on the line: one
        # prefix, then letters, digits and underscores, and nothing else gets
        # in. A carry that grows a second category grows it into every worktree
        # on the machine at once.
        printf '%s' "$key" | grep -qE '^ZITADEL_[A-Za-z0-9_]+$' || continue
        # A blank in the primary is not a credential. Copying it would rewrite
        # a line for nothing and announce a carry that carried nothing.
        [ -n "${line#*=}" ] || continue

        if [ "$carried" -eq 0 ]; then
            printf '   identity     ZITADEL_* carried from the primary checkout — KEY NAMES only,\n'
            printf '                never a value (a credential printed here would land in every\n'
            printf '                rung log, every report that pastes one, every gate transcript):\n'
        fi
        carried=$((carried + 1))

        tmp=$(mktemp "${target}.rung_start.XXXXXX")
        ZC_LINE="$line" ZC_KEY="$key" awk '
            index($0, ENVIRON["ZC_KEY"] "=") == 1 {
                if (!done) { print ENVIRON["ZC_LINE"]; done = 1 }
                next
            }
            { print }
            END { if (!done) print ENVIRON["ZC_LINE"] }
        ' "$target" >"$tmp"
        mv "$tmp" "$target"
        printf '                  %s\n' "$key"
    done <"$primary"

    if [ "$carried" -eq 0 ]; then
        printf '   identity     the primary checkout carries no populated ZITADEL_* value —\n'
        printf '                nothing carried. A rung that probes the real instance needs one\n'
        printf '                seeded first (manage.py zitadel_seed).\n'
        return 0
    fi
    printf '                %s key(s), from %s\n' "$carried" "$primary"
    return 0
}

# --- the sourced seam ---------------------------------------------------------
# See THE SOURCED SEAM in the header. SOURCED: the function above is defined and
# nothing below this line runs, which is how the drive exercises the carry
# without a venv, a Postgres or a MinIO behind it. EXECUTED: the two are equal,
# this is a no-op, and there is no command-line way to ask for it.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
    return 0
fi

# --- it refuses to be piped --------------------------------------------------
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! rung_start refuses pipes — run it bare or redirect to a file." >&2
    echo "   The exit status is the verdict, and a filter replaces it." >&2
    exit 2
fi

usage() {
    cat <<'USAGE'
usage: rung_start.sh [--resume] [-h]

  Takes THIS worktree to a ready state: baseline reset to main, venv, database,
  object-storage bucket, introspect dump. With no flag every step is
  unconditional, which is the whole point of it.

  --resume  The same five steps with STEP 1'S RESET REMOVED. For a worktree
            that is ALREADY on the right baseline and has lost its environment
            — a killed session, a swept database, a blown-away venv, a rung
            mid-flight with commits main does not have. It never moves HEAD and
            never touches a commit; it prints what it skipped, and says so
            loudly if it left a stale baseline standing. It lifts NO refusal: a
            dirty tree, a detached HEAD and a missing local `main` still refuse,
            because steps 3-5 write to `.env` and `.rung/` (see --RESUME in
            this script's header).

exit: 0 ready, every step verified · 1 a step ran and failed · 2 refused, or a
      step could not be verified (2 outranks a pass). A bucket that could not be
      made is the one named exception: exit 0 with `object storage ABSENT` in
      the footer.
USAGE
}

RESUME=""

while [ $# -gt 0 ]; do
    case "$1" in
    -h | --help)
        usage
        exit 0
        ;;
    --resume)
        RESUME=1
        shift
        ;;
    *)
        # Not a usage nit: a mistyped flag falling through to a silently
        # different run is enforcement misfiring, and that is an exit 2
        # (scripts/check.sh:71-76).
        echo "!! rung_start takes no arguments other than --resume; got '$1'." >&2
        usage >&2
        exit 2
        ;;
    esac
done

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

INTROSPECT_DIR="$ROOT/.rung"
INTROSPECT_OUT="$INTROSPECT_DIR/introspect.json"
STEP_TOTAL=5

# Step 4's verdict, carried to the footer. Empty means the bucket is there.
STORAGE_ABSENT=""

# --- the three ways this can end ---------------------------------------------
#
# REFUSED and COULD-NOT-VERIFY are both exit 2 and are printed differently on
# purpose: the first promises the worktree is untouched, and that promise is
# only true before step 1 has run.

refuse() {
    printf '\n!! %s\n' "$1" >&2
    shift
    while [ $# -gt 0 ]; do
        printf '   %s\n' "$1" >&2
        shift
    done
    printf '   Nothing was reset, installed, created or written.\n' >&2
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
# Resolution is declared rather than assumed, because the number this prints is
# what verification re-measures and a builder must know what it is reading. Only
# the last fallback is coarse, and it says so in the footer when it is used.

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

printf '== rung_start · %s\n' "$ROOT"

# =============================================================================
# STEP 1 · BASELINE
# =============================================================================
if [ -n "$RESUME" ]; then
    step_begin "baseline — RESUME: reporting it, resetting NOTHING"
else
    step_begin "baseline — reset this worktree to main"
fi

git rev-parse --git-dir >/dev/null 2>&1 ||
    refuse "this is not a git checkout: $ROOT"

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
[ -n "$BRANCH" ] && [ "$BRANCH" != "HEAD" ] ||
    refuse "this worktree is on a detached HEAD." \
        "Check out a branch first; resetting a detached HEAD would leave the" \
        "commits reachable from nothing but the reflog."

MAIN_SHA=$(git rev-parse --verify main 2>/dev/null || echo "")
[ -n "$MAIN_SHA" ] ||
    refuse "no local branch 'main' in this repository." \
        "The baseline every rung is cut from is local main, and it does not resolve."

# THE DIRTY-TREE REFUSAL, before anything at all is touched.
#
# `--resume` DOES NOT LIFT THIS, and the header says why at length: with no
# reset there is nothing to destroy in step 1, but steps 3-5 rewrite `.env` and
# overwrite `.rung/introspect.json`, and a hand-edited `.env` is exactly the
# kind of uncommitted work a builder has when they reach for a resume.
DIRTY=$(git status --porcelain)
if [ -n "$DIRTY" ]; then
    printf '\n!! this worktree has uncommitted work — REFUSING to reset it.\n' >&2
    printf '   The reset in step 1 is unconditional over a CLEAN tree only. These\n' >&2
    printf '   files would have been destroyed:\n\n' >&2
    printf '%s\n' "$DIRTY" | sed 's/^/     /' >&2
    printf '\n   Commit them, stash them, or discard them by hand — deliberately.\n' >&2
    if [ -n "$RESUME" ]; then
        printf '\n   --resume DOES NOT LIFT THIS. It removes the reset, not the writes:\n' >&2
        printf '   steps 3-5 rewrite .env (DATABASE_NAME, the bucket name, the identity\n' >&2
        printf '   carry) and overwrite .rung/introspect.json. A hand-edited .env is the\n' >&2
        printf '   commonest uncommitted file there is, and clobbering it under the flag\n' >&2
        printf '   whose name promises safety is worse than the reset it replaced.\n' >&2
    fi
    printf '   Nothing was reset, installed, created or written.\n' >&2
    exit 2
fi

# THE COMMITS-AHEAD REFUSAL. Clean is not the same as safe.
AHEAD=$(git rev-list --count main..HEAD)
if [ "$AHEAD" != "0" ] && [ -z "$RESUME" ]; then
    printf '\n!! this branch has %s commit(s) main does not have — REFUSING to reset it.\n' "$AHEAD" >&2
    printf '   A clean tree is not an empty one: rung-execution §5 tells builders to\n' >&2
    printf '   commit at every leg boundary, so mid-rung work lives in commits exactly\n' >&2
    printf '   like these. `reset --hard main` would discard them:\n\n' >&2
    git log --oneline main..HEAD | sed 's/^/     /' >&2
    printf '\n   If the active rung is finished with, the PM merges it. If it is not, keep\n' >&2
    printf '   building — your baseline was already established.\n' >&2
    printf '\n   IF WHAT YOU LOST IS THE ENVIRONMENT rather than the baseline — a killed\n' >&2
    printf '   session, a swept database, a blown-away venv — that is what --resume is:\n\n' >&2
    printf '       ./scripts/rung_start.sh --resume\n\n' >&2
    printf '   the same five steps with this reset removed. It moves no commit.\n' >&2
    printf '   Nothing was reset, installed, created or written.\n' >&2
    exit 2
fi

BEFORE=$(git rev-parse HEAD)
BEHIND=$(git rev-list --count HEAD..main)

say "branch     $BRANCH"
say "before     $(git log -1 --format='%h  %s' "$BEFORE")"
say "main       $(git log -1 --format='%h  %s' "$MAIN_SHA")"

if [ -n "$RESUME" ]; then
    # WHAT IT SKIPPED, printed. A flag that quietly does less is a flag whose
    # user cannot tell which of the two instruments they ran.
    printf '\n   ** RESUME ** the reset in step 1 was SKIPPED, deliberately.\n'
    printf '      skipped    git reset --hard main\n'
    printf '      HEAD stays at %s\n' "$BEFORE"
    if [ "$AHEAD" != "0" ]; then
        printf '      kept       %s commit(s) main does not have:\n' "$AHEAD"
        git log --oneline main..HEAD | sed 's/^/        /'
    else
        printf '      kept       0 commits main does not have\n'
    fi
    if [ "$BEHIND" != "0" ]; then
        # LOUDER THAN THE NORMAL PATH, not quieter. In the normal path a stale
        # baseline is a thing that WAS repaired; here it is a thing that was
        # not, and the builder is the only one who can decide about it.
        printf '\n      ** STALE BASELINE NOT REPAIRED ** this worktree is %s commits\n' "$BEHIND"
        printf '         behind main and --resume left it there, which is the flag doing\n'
        printf '         what it says. Your baseline is NOT main'\''s tip. If that is not\n'
        printf '         what you meant, this is the moment to notice it.\n'
    else
        printf '      baseline   already current — nothing to skip past\n'
    fi
    printf '\n'
    say "after      $(git log -1 --format='%h  %s' HEAD)  (unmoved)"
    AFTER="$BEFORE"
else
    if [ "$BEHIND" != "0" ]; then
        # SAY IT. A stale baseline that is silently repaired teaches nobody that
        # the pool hands out stale checkouts, and this class has been
        # rediscovered by hand in nine separate rungs.
        printf '\n   ** STALE BASELINE ** this worktree was %s commits behind main.\n' "$BEHIND"
        printf '      It was NOT cut from main'\''s tip. Resetting it now.\n\n'
    fi

    set +e
    git reset --hard main >/dev/null
    rc=$?
    set -e
    [ $rc -eq 0 ] || act_failed "git reset --hard main" "$rc"

    AFTER=$(git rev-parse HEAD)
    say "after      $(git log -1 --format='%h  %s' "$AFTER")"

    if [ "$AFTER" != "$MAIN_SHA" ]; then
        cannot_verify "HEAD is $AFTER after the reset, but main is $MAIN_SHA." \
            "The reset reported success and did not land where it was aimed."
    fi

    if [ "$BEHIND" = "0" ]; then
        say "baseline was already current — reset was a no-op ($BEFORE)"
    else
        say "RESET $BEHIND commits: ${BEFORE} -> ${AFTER}"
    fi
fi

# --- the pool diagnosis ------------------------------------------------------
#
# Printed whenever origin/main lags main, INDEPENDENTLY of whether this
# particular worktree was stale — because the condition is a statement about the
# NEXT spawn, not about this one. See THE POOL in the header.
ORIGIN_SHA=$(git rev-parse --verify origin/main 2>/dev/null || echo "")
if [ -n "$ORIGIN_SHA" ] && [ "$ORIGIN_SHA" != "$MAIN_SHA" ]; then
    POOL_GAP=$(git rev-list --count origin/main..main 2>/dev/null || echo "?")
    CREATED_FROM=$(git reflog show "$BRANCH" 2>/dev/null | tail -1 | sed -n 's/.*branch: Created from //p')
    printf '\n   -- THE POOL (why this keeps happening) ------------------------------\n'
    printf '   origin/main is %s commits behind local main.\n' "$POOL_GAP"
    printf '     origin/main  %s\n' "$(git log -1 --format='%h  %ad  %s' --date=short origin/main)"
    printf '     main         %s\n' "$(git log -1 --format='%h  %ad  %s' --date=short main)"
    if [ -n "$CREATED_FROM" ]; then
        printf '   This branch was created from: %s  (its own reflog says so)\n' "$CREATED_FROM"
    fi
    printf '   Worktree branches are cut from origin/main, which moves only on a push;\n'
    printf '   this loop merges into LOCAL main continuously. Every worktree spawned\n'
    printf '   until the next push starts %s commits behind, and step 1 above is the\n' "$POOL_GAP"
    printf '   belt, not the fix. The lever is the harness, or a push after each merge\n'
    printf '   (scripts/pm_push.sh). See THE POOL in this script'\''s header.\n'
    printf '   ---------------------------------------------------------------------\n'
fi

step_end

# =============================================================================
# STEP 2 · VENV
# =============================================================================
step_begin "venv — uv sync"

command -v uv >/dev/null 2>&1 ||
    refuse "no \`uv\` on PATH." \
        "This repository's interpreter and dependencies are uv's (CLAUDE.md, the stack)."

set +e
uv sync
rc=$?
set -e
[ $rc -eq 0 ] || act_failed "uv sync" "$rc"

PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] ||
    cannot_verify "uv sync exited 0 but $PY is not an executable file." \
        "There is no interpreter to hand the next two steps."

"$PY" -c 'import django; print("   django " + django.get_version() + " importable")' ||
    cannot_verify "the venv's own interpreter cannot import Django." \
        "uv sync reported success over a venv that cannot run this project."

say "interpreter $PY"
step_end

# =============================================================================
# STEP 3 · DATABASE
# =============================================================================
step_begin "database — this checkout's own, created and migrated"

# `.env` first: a BARE `manage.py` — one that never sourced db.sh — reads the
# database name out of .env, and a fresh worktree has no .env at all. Without
# this a builder's first `uv run python manage.py shell` lands in whatever
# database .env.example ships (scripts/setup.sh:146,308-312).
if [ ! -f "$ROOT/.env" ]; then
    [ -f "$ROOT/.env.example" ] ||
        refuse "no .env and no .env.example in $ROOT." \
            "There is nothing to derive this checkout's environment from."
    cp "$ROOT/.env.example" "$ROOT/.env"
    say ".env         created from .env.example"

    # THE IDENTITY CARRY, and only here — on a `.env` this script just made.
    # See THE IDENTITY CARRY in the header: `.env.example` ships the identity
    # credentials blank because they are seeded once per machine, so a fresh
    # worktree used to begin with an unrecorded hand copy out of another
    # checkout. KEY NAMES are announced; a value is never printed.
    # Asked in two steps, and the emptiness check between them is the point:
    # `git rev-parse --git-common-dir` answers a RELATIVE `.git` in the primary
    # checkout itself, so the `cd` is how it becomes absolute — and `cd ""`
    # SUCCEEDS in bash, staying put, which would silently make the parent of
    # THIS worktree the "primary" and read a `.env` that has nothing to do with
    # this repository. Step 1 has already proved this is a git checkout, so the
    # empty branch should be unreachable; an unreachable branch that would be
    # silently wrong if reached is exactly the kind that gets written.
    PRIMARY_COMMON=$(git rev-parse --git-common-dir 2>/dev/null || echo "")
    PRIMARY_ROOT=""
    if [ -n "$PRIMARY_COMMON" ] && [ -d "$PRIMARY_COMMON" ]; then
        PRIMARY_GIT=$(cd "$PRIMARY_COMMON" && pwd)
        PRIMARY_ROOT=$(dirname "$PRIMARY_GIT")
    fi
    if [ -z "$PRIMARY_ROOT" ]; then
        say "identity     could not locate the primary checkout — nothing carried"
    elif [ "$PRIMARY_ROOT" = "$ROOT" ]; then
        # Not a failure and not silent: this IS where zitadel_seed was run, so
        # there is no other checkout for the credentials to come from.
        say "identity     this IS the primary checkout — nothing to carry from"
    else
        zitadel_carry "$PRIMARY_ROOT/.env" "$ROOT/.env"
    fi
else
    say ".env         already present"
    say "identity     .env was not created by this run — ZITADEL_* left alone (header 7)"
fi

# db.sh sets no shell options of its own and may read unset variables; seam_check
# sources it the same way and for the same reason (scripts/seam_check.sh:182-187).
[ -r "$ROOT/scripts/db.sh" ] ||
    refuse "$ROOT/scripts/db.sh is missing or unreadable." \
        "It is the one seam this script derives a database name through."
set +u
set +e
# shellcheck source=scripts/db.sh
. "$ROOT/scripts/db.sh"
set -e
set -u

[ -n "${DATABASE_NAME:-}" ] ||
    cannot_verify "db.sh was sourced but exported no DATABASE_NAME." \
        "The one seam this script consumes did not answer."

say "database     $DATABASE_NAME"

# Postgres reachability, BEFORE anything is created. An unreachable server is
# could-not-look, and this script does not start a stack it shares with every
# other checkout on the machine.
if ! db_query 'SELECT 1' -tA >/dev/null 2>&1; then
    refuse "cannot reach Postgres in the compose stack." \
        "Bring it up yourself — it is shared by every checkout on this machine," \
        "and this script will not start something you may have stopped on purpose:" \
        "" \
        "    docker compose up -d db" \
        ""
fi

# db.sh's PUBLIC CLI and nothing below it: db_create / db_exists, exactly as its
# own header advertises them (scripts/db.sh:4-5). What db_create does inside
# can change; this line is the seam that must not notice.
set +e
db_create_out=$(db_create 2>&1)
rc=$?
set -e
printf '%s\n' "$db_create_out" | sed 's/^/   /'
[ $rc -eq 0 ] || act_failed "db_create" "$rc"

db_exists ||
    cannot_verify "db_create returned, and db_exists says $DATABASE_NAME is not there." \
        "The database was not created and the failure was silent."

# The pin, so a bare manage.py resolves the same name every script here does.
# setup.sh's pin-reconcile semantics, second copy, declared in the header —
# except for the MARKER TEST, which is `db_pin_marked` from the db.sh sourced
# above and is no longer copied here. The marker's grammar moved (its own
# comment line above a bare value; scripts/db.sh, "THE MARKER'S GRAMMAR") and
# a hand copy is a reader that gets left behind at exactly that moment.
if db_pin_marked; then
    say ".env carries the \`# pinned\` marker — DATABASE_NAME left alone"
    say "  .env:       $(grep -E '^DATABASE_NAME=' "$ROOT/.env" | tail -1)"
    say "  derivation: ${DATABASE_NAME}"
elif grep -qE '^DATABASE_NAME=' "$ROOT/.env"; then
    tmp=$(mktemp "$ROOT/.env.rung_start.XXXXXX")
    DBN="$DATABASE_NAME" awk '
        /^DATABASE_NAME=/ { print "DATABASE_NAME=" ENVIRON["DBN"]; next }
        { print }
    ' "$ROOT/.env" >"$tmp"
    mv "$tmp" "$ROOT/.env"
    say ".env         DATABASE_NAME=${DATABASE_NAME}"
else
    printf 'DATABASE_NAME=%s\n' "$DATABASE_NAME" >>"$ROOT/.env"
    say ".env         DATABASE_NAME=${DATABASE_NAME} (appended)"
fi

set +e
DATABASE_NAME="$DATABASE_NAME" "$PY" manage.py migrate
rc=$?
set -e
[ $rc -eq 0 ] || act_failed "manage.py migrate" "$rc"

# `--check` exits non-zero when a migration is unapplied. That is the
# verification: migrate exiting 0 is what it SAID, this is what is TRUE.
set +e
DATABASE_NAME="$DATABASE_NAME" "$PY" manage.py migrate --check >/dev/null 2>&1
rc=$?
set -e
[ $rc -eq 0 ] ||
    cannot_verify "migrate exited 0 and \`migrate --check\` exits $rc." \
        "Migrations are still unapplied against $DATABASE_NAME."

say "migrations   applied and verified (migrate --check clean)"
step_end

# =============================================================================
# STEP 4 · STORAGE
# =============================================================================
#
# THE SAME PROBLEM AS THE DATABASE, THE SAME ANSWER, AND setup.sh ALREADY HAD
# IT (`scripts/setup.sh:446`). Agents build in parallel worktrees against ONE
# compose MinIO, so the bucket follows the CHECKOUT exactly as `DATABASE_NAME`
# does, and a name already in `.env` wins exactly as `DATABASE_NAME`'s does.
#
# THE ARITHMETIC IS NOT MIRRORED HERE, and that is the shape of this step, as it
# is of setup.sh's. `manage.py ensure_bucket` prints the derived name on stdout
# and nothing else, for exactly this line to capture; it also CREATES the bucket,
# which is the other half — a name in `.env` pointing at no bucket makes /readyz
# report `storage: false`, a worse lie than reporting nothing.
#
# WHY IT IS IN THE FAST PATH AT ALL. Naming a bucket is the whole switch to S3
# (`config/settings/base.py`), so after this step `/readyz` grows a `storage`
# member and `apps/files` can store, sign and stream for real. Before it, every
# worktree this script provisioned began with object storage OFF and nothing
# announcing it: `storage_audit` exit 2, the integrations census NOT CONFIGURED
# (found and confirmed by an earlier files-lane rung).
#
# NOT FATAL, AND NOT SILENT — the header's 3b. It joins the footer instead of
# replacing the verdict.
step_begin "storage — this checkout's own bucket, created and named"

if grep -qE '^AWS_STORAGE_BUCKET_NAME=.+' "$ROOT/.env"; then
    # A CONFIGURED NAME WINS — `ensure_bucket`'s own contract, and setup.sh's.
    # It is also, declared here rather than discovered, this step's blind spot:
    # a name that came from somewhere else (a copied `.env`, a checkout moved on
    # disk) points at ANOTHER checkout's bucket, and nothing below compares it
    # against what this checkout would derive. That is the same hazard
    # `DATABASE_NAME` has exactly — and `DATABASE_NAME` has a disagreement check with an exit
    # status (`scripts/db.sh::db_pin_leg`) where storage has none. Building the
    # comparison here would mean a SECOND copy of the bucket arithmetic in
    # shell, which is the one thing this step's header refuses; the answer is a
    # read-only door on the seam that owns it (`apps/files/storage.py::
    # derived_bucket_name`), and that is `apps/files`' to add, not this
    # script's. Until it exists, this line prints the pin so a reader can see
    # it, and the header's 3c says what it cannot check.
    say "bucket       already named in .env — left alone (NOT compared against this checkout's derivation; header 3c)"
    say "  .env:      $(grep -E '^AWS_STORAGE_BUCKET_NAME=' "$ROOT/.env" | tail -1)"
else
    set +e
    BUCKET_NAME=$(DATABASE_NAME="$DATABASE_NAME" "$PY" manage.py ensure_bucket 2>"$ROOT/.rung_start_bucket.err")
    rc=$?
    set -e
    if [ $rc -eq 0 ] && [ -n "${BUCKET_NAME:-}" ]; then
        if grep -qE '^AWS_STORAGE_BUCKET_NAME=' "$ROOT/.env"; then
            tmp=$(mktemp "$ROOT/.env.rung_start.XXXXXX")
            BKT="$BUCKET_NAME" awk '
                /^AWS_STORAGE_BUCKET_NAME=/ { print "AWS_STORAGE_BUCKET_NAME=" ENVIRON["BKT"]; next }
                { print }
            ' "$ROOT/.env" >"$tmp"
            mv "$tmp" "$ROOT/.env"
        else
            printf 'AWS_STORAGE_BUCKET_NAME=%s\n' "$BUCKET_NAME" >>"$ROOT/.env"
        fi
        say "bucket       $BUCKET_NAME"
        say ".env         AWS_STORAGE_BUCKET_NAME=${BUCKET_NAME}"
    else
        # LOUD, and it names the one command — the same words setup.sh uses,
        # because a builder meeting this in either script is meeting one fact.
        STORAGE_ABSENT="the object storage bucket was not made"
        printf '\n   !! no object storage: the bucket could not be made, so\n' >&2
        printf '      AWS_STORAGE_BUCKET_NAME was left alone. /readyz will carry no\n' >&2
        printf '      `storage` member, `manage.py storage_audit` exits 2 and the\n' >&2
        printf '      integrations census reads NOT CONFIGURED. apps/files and\n' >&2
        printf '      apps/exports will refuse at the seam.\n' >&2
        printf '      ensure_bucket said:\n' >&2
        sed 's/^/        /' "$ROOT/.rung_start_bucket.err" >&2
        printf '      Bring MinIO up and run it again:\n' >&2
        printf '        docker compose up -d minio\n' >&2
        printf '        uv run python manage.py ensure_bucket\n' >&2
        printf '      THIS IS NOT FATAL: a rung that touches neither files nor exports\n' >&2
        printf '      needs nothing here, and the footer says so rather than this\n' >&2
        printf '      script deciding for you.\n\n' >&2
    fi
    rm -f "$ROOT/.rung_start_bucket.err"
fi
step_end

# =============================================================================
# STEP 5 · INTROSPECT
# =============================================================================
step_begin "introspect — the schema, read rather than guessed"

mkdir -p "$INTROSPECT_DIR"

set +e
DATABASE_NAME="$DATABASE_NAME" "$PY" manage.py introspect >"$INTROSPECT_OUT"
rc=$?
set -e
[ $rc -eq 0 ] || act_failed "manage.py introspect" "$rc"

[ -s "$INTROSPECT_OUT" ] ||
    cannot_verify "introspect exited 0 and wrote an empty file to $INTROSPECT_OUT."

# It is documented as JSON on stdout and nothing else
# (apps/core/management/commands/introspect.py:8-9). Proving that here is what
# separates "the dump ran" from "the dump is readable".
"$PY" -c 'import json,sys; json.load(open(sys.argv[1]))' "$INTROSPECT_OUT" ||
    cannot_verify "$INTROSPECT_OUT is not valid JSON." \
        "introspect exited 0 over output nothing can read."

say "wrote        $INTROSPECT_OUT ($(wc -c <"$INTROSPECT_OUT" | tr -d ' ') bytes)"
say "             read it instead of guessing the schema (CLAUDE.md, standing rules)"
step_end

# =============================================================================
TOTAL=$(($(now_ms) - RUN_START))
if [ -n "$STORAGE_ABSENT" ]; then
    # The footer reads differently, because a footer that reads the same either
    # way is the silence step 4 exists to end (header, 3b).
    printf '\n== READY · object storage ABSENT · total %s · %s\n' \
        "$(fmt_ms $TOTAL)" "$(git log -1 --format='%h  %s' HEAD)"
    printf '   %s — step 4 said what to do about it. Every other step is verified.\n' "$STORAGE_ABSENT"
else
    printf '\n== READY · total %s · %s\n' "$(fmt_ms $TOTAL)" "$(git log -1 --format='%h  %s' HEAD)"
fi
if [ "$CLOCK" = "seconds" ]; then
    printf '   (clock resolution: whole seconds — no sub-second clock on this host)\n'
fi
printf '   Next: load django-conventions before writing Python; gate with\n'
printf '   ./scripts/check.sh --loop > "$PWD/gate-<your rung>.log" 2>&1 (rung-execution §3;\n'
printf '   the rung id is not decoration — five lanes writing `gate.log` write one file).\n'
