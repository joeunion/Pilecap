#!/usr/bin/env bash
# THE RUNG START. One command that takes a freshly spawned
# worktree from whatever the pool handed you to a tree you can build in.
#
#   ./scripts/rung_start.sh
#
# Five steps, unconditionally and in this order, each printing what it did and
# how long it took, with the total at the end:
#
#   1. BASELINE   reset this worktree to local `main`, printing the sha before
#                 and the sha after — and SAYING SO when they differ.
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
#   5. THE .ENV PIN POLICY IS A SECOND COPY. The `# pinned` marker semantics
#      below are setup.sh's (`scripts/setup.sh:325-337`), re-implemented rather
#      than shared, because setup.sh is a script that runs top to bottom and
#      cannot be sourced for one function. Two copies that agree today is the
#      drift class this repository names everywhere else; it is declared here
#      rather than discovered, and `scripts/tests/test_rung_start.sh` drives
#      this copy so a divergence is at least loud on THIS side.
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

# --- it refuses to be piped --------------------------------------------------
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! rung_start refuses pipes — run it bare or redirect to a file." >&2
    echo "   The exit status is the verdict, and a filter replaces it." >&2
    exit 2
fi

usage() {
    cat <<'USAGE'
usage: rung_start.sh [-h]

  Takes THIS worktree to a ready state: baseline reset to main, venv, database,
  object-storage bucket, introspect dump. It takes no options and no arguments
  — every step is unconditional, which is the whole point of it.

exit: 0 ready, every step verified · 1 a step ran and failed · 2 refused, or a
      step could not be verified (2 outranks a pass). A bucket that could not be
      made is the one named exception: exit 0 with `object storage ABSENT` in
      the footer.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
    -h | --help)
        usage
        exit 0
        ;;
    *)
        # Not a usage nit: a mistyped flag falling through to a silently
        # different run is enforcement misfiring, and that is an exit 2
        # (scripts/check.sh:71-76).
        echo "!! rung_start takes no arguments; got '$1'." >&2
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
step_begin "baseline — reset this worktree to main"

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
DIRTY=$(git status --porcelain)
if [ -n "$DIRTY" ]; then
    printf '\n!! this worktree has uncommitted work — REFUSING to reset it.\n' >&2
    printf '   The reset in step 1 is unconditional over a CLEAN tree only. These\n' >&2
    printf '   files would have been destroyed:\n\n' >&2
    printf '%s\n' "$DIRTY" | sed 's/^/     /' >&2
    printf '\n   Commit them, stash them, or discard them by hand — deliberately.\n' >&2
    printf '   Nothing was reset, installed, created or written.\n' >&2
    exit 2
fi

# THE COMMITS-AHEAD REFUSAL. Clean is not the same as safe.
AHEAD=$(git rev-list --count main..HEAD)
if [ "$AHEAD" != "0" ]; then
    printf '\n!! this branch has %s commit(s) main does not have — REFUSING to reset it.\n' "$AHEAD" >&2
    printf '   A clean tree is not an empty one: rung-execution §5 tells builders to\n' >&2
    printf '   commit at every leg boundary, so mid-rung work lives in commits exactly\n' >&2
    printf '   like these. `reset --hard main` would discard them:\n\n' >&2
    git log --oneline main..HEAD | sed 's/^/     /' >&2
    printf '\n   If the active rung is finished with, the PM merges it. If it is not, keep\n' >&2
    printf '   building — your baseline was already established.\n' >&2
    printf '   Nothing was reset, installed, created or written.\n' >&2
    exit 2
fi

BEFORE=$(git rev-parse HEAD)
BEHIND=$(git rev-list --count HEAD..main)

say "branch     $BRANCH"
say "before     $(git log -1 --format='%h  %s' "$BEFORE")"
say "main       $(git log -1 --format='%h  %s' "$MAIN_SHA")"

if [ "$BEHIND" != "0" ]; then
    # SAY IT. A stale baseline that is silently repaired teaches nobody that the
    # pool hands out stale checkouts, and this class has been rediscovered by
    # hand in nine separate rungs.
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
else
    say ".env         already present"
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
# setup.sh:325-337's semantics, second copy, declared in the header.
if grep -qE '^DATABASE_NAME=.*#[[:space:]]*pinned' "$ROOT/.env"; then
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
