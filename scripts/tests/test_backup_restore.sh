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
# The refusal drive for scripts/backup.sh and scripts/restore_drill.sh.
#
#   ./scripts/tests/test_backup_restore.sh          run every case
#   ./scripts/tests/test_backup_restore.sh --list   name them and stop
#
# WHY IT EXISTS. Both scripts are made of refusals, and every one of them was
# proven exactly once, by hand, on the day it was written. A refusal
# nothing drives is a refusal that can be deleted by accident and stay deleted:
# the code goes on running, the happy path goes on passing, and the first
# person to find out is whoever aimed a restore at the stack it came from. So
# the refusals get a driver, and the driver runs in the gate.
#
# THE SHAPE, and it is `db_sweep.sh`'s: drive the real script, as a caller would,
# and assert TWO things about each case — the EXIT CODE and a phrase from the
# message. Neither alone is enough. An exit code with no message is a refusal
# nobody can act on; a message with the wrong code is exactly the class
# `docs/product/instruments.md` exists to refuse (an absence reported as a
# violation). Asserting both is what makes a case fail when somebody "fixes"
# one half.
#
# EXIT (the house semantics, and this file is held to them too):
#   0  every case drove its refusal and got it
#   1  a case FAILED — a refusal did not fire, or fired with the wrong code
#   2  COULD NOT LOOK — no docker, no database, no scripts. 2 outranks a pass:
#      a driver that could not run its cases has not cleared them.
#
# `set -e` IS DELIBERATELY OFF. Every case here runs a command whose whole
# purpose is to fail; under `set -e` the first refusal would end the driver and
# it would report a pass on the cases it never reached. `pipefail` and `-u`
# stay on.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * `--to-s3`. There is no S3 on a laptop and no account in the gate. The
#     `--to-s3` ABSENCE refusal (no `aws` on PATH → exit 2) is driven; the
#     upload is not, and cannot be from here. `backup.sh`'s own header is why
#     that is tolerable: `--to-dir` and `--to-s3` are one mechanism with two
#     targets and everything above the last line is identical, so the covered
#     path is the shared one.
#   * A REAL `--stack` DUMP, and therefore a real `.origin` sidecar. `--stack`
#     points `docker compose` at `deploy/compose.yaml`, which is a deployment
#     stack this driver has no business bringing up on a shared machine. What
#     is driven is `--stack`'s refusals, and a sidecar this driver WRITES to
#     the shape `backup.sh` documents — so the restore drill's origin reasoning
#     is proven against a faithful file, and the file's own production is not.
#     A change to the sidecar's format is invisible here, which is why the
#     shape is quoted from `scripts/backup.sh`'s header rather than invented.
#   * A COMPLETED RESTORE — still not driven, and now for a narrower reason.
#     Most `restore_drill.sh` cases here stop at a refusal, which is declared
#     to fire "before anything is created or dropped"
#     (`scripts/restore_drill.sh`). The two DEATH-GUARD cases deliberately go
#     past that line, into the scratch-mode region where the drill creates and
#     restores — one dies on `set -e` against a broken dump, one is killed
#     mid-drill — because a guard about dying cannot be driven from outside the
#     region where dying is possible. Both assert the scratch database is gone
#     afterwards, so the property the refusal cases relied on is now proven
#     rather than assumed. What is STILL not driven is a drill that reaches
#     `RESTORE DRILL PASSED`: neither death case may, and one that did would be
#     reported as a failure to drive its own path. The happy path remains
#     `restore_drill.sh` run by a human against a dump they made.
#   * `--into-project`'s death. Both death cases run in SCRATCH mode. The live-
#     stack branch of `cleanup` (which deliberately drops nothing) is reasoned
#     about and not exercised — driving it would need a second deployment stack
#     up on a shared machine, which is the same line this driver already
#     declines to cross for `--stack`.
#   * WHETHER A REFUSAL IS THE RIGHT REFUSAL. This asserts that the script
#     refuses and says a particular thing. That the thing is TRUE is the
#     reader's judgement, exactly as it is for every row in the census.

set -uo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before anything asks git a question ----
#
# A drive run from the pre-push hook inherits an absolute `GIT_DIR` from
# `git -C <linked worktree> push`. This drive runs no `git -C` of its own, so
# it cannot escape the way `scripts/tests/test_pm_merge.sh` did — but it
# sources `scripts/db.sh`, and THIS CHECKOUT'S DATABASE NAME IS DERIVED FROM
# `git rev-parse --show-toplevel`. Under an inherited `GIT_DIR` that answers
# with the pushing worktree, so a driver that takes a real `pg_dump` would be
# dumping a database it never named. Same environment, same class, so the same
# preamble — and `set -e` is off in this file, which makes the scratch belt
# below worth more here than anywhere else.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_backup_restore: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the neutralisation that keeps this drive reading its own" >&2
    echo "   checkout's derivation. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

PASSED=0
FAILED=0

# Exit 2 is "I could not look" — the same word this repository uses everywhere
# else (docs/product/instruments.md). Nothing has been asserted when this fires.
cannot_look() {
    echo "!! test_backup_restore: $*" >&2
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
    echo "!! unknown argument '$1': test_backup_restore.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v docker >/dev/null 2>&1 || cannot_look "no docker on PATH; backup.sh dumps inside the compose container"
[ -x scripts/backup.sh ] || cannot_look "scripts/backup.sh is not executable from $(pwd)"
[ -x scripts/restore_drill.sh ] || cannot_look "scripts/restore_drill.sh is not executable from $(pwd)"

# shellcheck source=scripts/db.sh
source scripts/db.sh
db_exists "$DATABASE_NAME" ||
    cannot_look "this checkout's database ${DATABASE_NAME} does not exist; run ./scripts/setup.sh first (the --to-dir case dumps it)"

# --- THE PRECONDITION THIS DRIVER HAS, STATED AND THEN ENSURED --------
#
# `case_backup_to_dir_produces_an_object` asserts the dump is at least 1024
# bytes, because `backup.sh` refuses anything smaller as "not a backup". An
# EMPTY database dumps to about 900 bytes of header — so a checkout whose
# database was created bare by `db_create` and never migrated fails this case,
# and the failure names a byte count instead of the reason. That is every fresh
# worktree that has only ever run pytest: pytest populates `test_`-prefixed
# databases and never the base one, so the base one exists and is empty — the
# same class as an unstated precondition anywhere else.
#
# WHY THE FIX IS HERE AND NOT IN `db_create`. `db_create` lives in `scripts/db.sh`,
# which is SOURCED by everything — the gate, `db_sweep.sh`, `backup.sh`,
# `perf.sh` — including callers that must not need Django importable at all
# (`db_sweep.sh` reasons about names and never opens the ORM). Making a
# creation primitive shell out to `manage.py migrate` would put a slow, Django-
# dependent side effect inside a `source`, which is the class of surprise
# already refused for `db.sh` on exactly these grounds; it would also double the
# work in `perf.sh`, which calls `db_create` and then migrates on purpose. The
# precondition belongs to the instrument that HAS it.
#
# ENSURE, not merely state. Refusing with exit 2 would be honest and would
# still leave a fresh worktree's first full gate red for a reason the operator
# did nothing to cause. So this migrates once, says so, and moves on — and the
# `cannot_look` above still covers the case it cannot fix (no database at all).
if [ "$(db_query "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" -d "$DATABASE_NAME" -tA 2>/dev/null || echo 0)" = "0" ]; then
    echo "  precondition: ${DATABASE_NAME} has no tables (created bare, never migrated)."
    echo "                Migrating it once — an empty database dumps to ~900 bytes and"
    echo "                backup.sh rightly refuses that as not-a-backup."
    DATABASE_NAME="$DATABASE_NAME" uv run python manage.py migrate --no-input >/dev/null ||
        cannot_look "could not migrate ${DATABASE_NAME}; the --to-dir case needs a database with tables in it"
fi

WORK="$(mktemp -d)"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'
# The death-guard cases put the drill's own scratch database on the machine.
# The drill drops it itself on every path — that is half of what those cases
# assert — but this driver is the one that started it, so it owns the belt for
# the run that dies before the drill can.
drive_at_exit 'db_exists "${DATABASE_NAME}_drill" && db_drop "${DATABASE_NAME}_drill" >/dev/null'
trap 'exit 130' INT
trap 'exit 143' TERM

# --- the two assertions every case makes -------------------------------------
#
# Usage: drive <label> <want-exit> -- <command...>
# Leaves the transcript in $DRIVE_OUT and the status in $DRIVE_EXIT, so the
# caller can add a `says` assertion about the same run rather than running it
# twice (two runs is two answers, and the second one is the one nobody read).
DRIVE_OUT=""
DRIVE_EXIT=0
CURRENT=""
drive() {
    local label="$1" want="$2"
    shift 3   # label, want, --
    CURRENT="$label"
    DRIVE_OUT="${WORK}/$(printf '%s' "$label" | tr -c 'a-zA-Z0-9' '_').log"
    "$@" >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    if [ "$DRIVE_EXIT" -eq "$want" ]; then
        echo "  ok       ${label} — exit ${DRIVE_EXIT}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted exit ${want}, got ${DRIVE_EXIT}"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -12
        FAILED=$((FAILED + 1))
    fi
}

# The second half. A refusal with the right code and the wrong sentence is a
# refusal nobody can act on, so both are asserted about the SAME run.
says() {
    local needle="$1"
    if grep -qF -- "$needle" "$DRIVE_OUT"; then
        echo "  ok       ${CURRENT} — says \"${needle}\""
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — does not say \"${needle}\""
        sed 's/^/             | /' "$DRIVE_OUT" | tail -12
        FAILED=$((FAILED + 1))
    fi
}

# A database assertion, for the death-guard cases: the scratch database the
# drill created must be gone, however the drill ended.
db_absent() {
    local name="$1"
    if db_exists "$name"; then
        echo "  FAILED   ${CURRENT} — ${name} was left behind"
        FAILED=$((FAILED + 1))
    else
        echo "  ok       ${CURRENT} — ${name} was dropped"
        PASSED=$((PASSED + 1))
    fi
}

# A file assertion, for the one case that is not a refusal.
file_at_least() {
    local path="$1" bytes="$2" size
    if [ ! -f "$path" ]; then
        echo "  FAILED   ${CURRENT} — no object at ${path}"
        FAILED=$((FAILED + 1))
        return
    fi
    size="$(wc -c <"$path" | tr -d ' ')"
    if [ "$size" -ge "$bytes" ]; then
        echo "  ok       ${CURRENT} — object at ${path} (${size} bytes)"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — ${path} is ${size} bytes, wanted at least ${bytes}"
        FAILED=$((FAILED + 1))
    fi
}

# --- the cases ---------------------------------------------------------------

case_backup_unknown_flag() {
    # An unknown flag is enforcement broken, not a usage nit: a flag that fell
    # through to a silent default would be a backup taken somewhere nobody meant.
    drive "backup: unknown flag" 2 -- ./scripts/backup.sh --no-such-flag
    says "unknown flag --no-such-flag"
}

case_backup_flag_without_value() {
    drive "backup: --to-dir with no value" 2 -- ./scripts/backup.sh --to-dir
    says "needs a value"
}

case_backup_two_outputs() {
    drive "backup: two output paths" 2 -- ./scripts/backup.sh "${WORK}/a.dump" "${WORK}/b.dump"
    says "two output paths given"
}

case_backup_absent_database() {
    # "There is no such database" is COULD-NOT-LOOK, and the code has to
    # say so: a nightly that lost its database name must not read like a nightly
    # that produced a bad dump.
    drive "backup: the database does not exist" 2 -- \
        env DATABASE_NAME=djb_test_no_such_world_deadbeef ./scripts/backup.sh --to-dir "${WORK}/off"
    says "does not exist, so there is nothing to back up"
}

case_backup_stack_without_env_file() {
    drive "backup: --stack with no environment file" 2 -- \
        ./scripts/backup.sh --stack djb-nosuch --env-file "${WORK}/absent.env"
    says "--stack needs the deployment's own env"
}

case_backup_to_dir_produces_an_object() {
    # The one case that is not a refusal, and the reason the driver needs a real
    # database: `--to-dir` is `--to-s3`'s code path with the last line changed,
    # so proving the copy here proves the shared mechanism.
    local out="${WORK}/laptop.dump" off="${WORK}/off"
    drive "backup: --to-dir copies the object" 0 -- ./scripts/backup.sh --to-dir "$off" "$out"
    file_at_least "$out" 1024
    file_at_least "${off}/$(basename "$out")" 1024
}

case_restore_unknown_flag() {
    drive "restore: unknown flag" 2 -- ./scripts/restore_drill.sh --no-such-flag
    says "unknown flag --no-such-flag"
}

case_restore_no_origin_at_a_live_stack() {
    # Refusal 2 of 3. `--into-project` aims at a LIVE stack, and a dump with no
    # sidecar cannot prove the target is not the source. Exit 2, not 1: the
    # script could not look, because the fact it needed was never written down.
    local dump="${WORK}/orphan.dump"
    printf 'not really a dump, and this case never gets far enough to read it\n' >"$dump"
    drive "restore: no .origin beside the dump" 2 -- \
        ./scripts/restore_drill.sh --into-project djb-nosuch "$dump"
    says "refusing to restore into a LIVE stack from a dump with no origin"
}

case_restore_origin_without_a_project_line() {
    local dump="${WORK}/blank-origin.dump"
    printf 'not really a dump\n' >"$dump"
    printf '# a sidecar that forgot the one line that matters\ndatabase=djb_x\n' >"${dump}.origin"
    drive "restore: .origin with no project= line" 2 -- \
        ./scripts/restore_drill.sh --into-project djb-nosuch "$dump"
    says "the origin is unreadable"
}

case_restore_target_is_the_source() {
    # Refusal 1 of 3, and the one with teeth: a drill that can overwrite the
    # thing it is protecting is a worse risk than not drilling. Exit 1, not 2 —
    # this one LOOKED, and what it found is wrong.
    local dump="${WORK}/same.dump"
    printf 'not really a dump\n' >"$dump"
    # The sidecar's shape is backup.sh's, quoted rather than invented.
    {
        printf 'project=%s\n' "djb-same"
        printf 'database=%s\n' "djb_same"
        printf 'env_file=%s\n' "${WORK}/same.env"
        printf 'taken_at=%s\n' "19700101T000000Z"
    } >"${dump}.origin"
    drive "restore: the target is the source" 1 -- \
        ./scripts/restore_drill.sh --into-project djb-same "$dump"
    says "the restore target is the source"
}

case_restore_target_differs_and_the_check_moves_on() {
    # The other side of the same refusal, and it is the case that keeps the one
    # above honest: a driver that only proved "it refuses" would still pass if
    # somebody made it refuse EVERYTHING. Here the projects differ, the
    # target-is-the-source check passes, and the run stops at the NEXT guard —
    # a missing env file for the target stack. Different message, different
    # cause, same exit class.
    local dump="${WORK}/other.dump"
    printf 'not really a dump\n' >"$dump"
    {
        printf 'project=%s\n' "djb-source"
        printf 'database=%s\n' "djb_source"
    } >"${dump}.origin"
    drive "restore: a different target reaches the next guard" 2 -- \
        ./scripts/restore_drill.sh --into-project djb-target --env-file "${WORK}/absent.env" "$dump"
    says "--into-project needs the target stack's own env"
}

case_restore_a_broken_dump_dies_and_says_so() {
    # THE DEATH GUARD, deterministically. A garbage dump gets past every refusal
    # (all three are about `--into-project`), reaches `pg_restore` in scratch
    # mode and trips `set -e`. On the baseline the transcript ended at
    # pg_restore's own complaint — which is exactly what a killed drill and a
    # drill still running both look like. Two halves, on the same run: the
    # sentinel naming the code, and the scratch database gone anyway.
    local dump="${WORK}/broken.dump"
    printf 'not a dump at all\n' >"$dump"
    drive "restore: a broken dump dies and says so" 1 -- ./scripts/restore_drill.sh "$dump"
    says "RESTORE DRILL DID NOT FINISH (exit 1)"
    db_absent "${DATABASE_NAME}_drill"
}

case_restore_killed_mid_drill_says_so_and_drops_the_scratch() {
    # THE SIGNAL PATH, which the case above cannot reach: a trap on EXIT alone
    # never runs for a drill somebody kills, so INT/TERM/HUP each become an exit
    # first. Driven against the REAL dump `--to-dir` produced, because a signal
    # has to land while the drill is genuinely working.
    #
    # NOT A KNIFE-EDGE RACE. The signal is sent the moment the scratch database
    # appears — the earliest instant the drill has started — which leaves the
    # whole of pg_restore, the table assertions and `migrate --check` (seconds
    # of Django start-up alone) as the window for it to land. If the drill
    # nevertheless got all the way to PASSED, this case FAILS saying so rather
    # than skipping: a case that quietly did not drive its path is worse than
    # no case.
    local dump="${WORK}/laptop.dump" log="${WORK}/killed.log" pid polls=0
    CURRENT="restore: killed mid-drill"
    if [ ! -f "$dump" ]; then
        echo "  FAILED   ${CURRENT} — no real dump at ${dump}; the --to-dir case owes it"
        FAILED=$((FAILED + 1))
        return
    fi
    ./scripts/restore_drill.sh "$dump" >"$log" 2>&1 &
    pid=$!
    while [ "$polls" -lt 120 ]; do
        db_exists "${DATABASE_NAME}_drill" && break
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.25
        polls=$((polls + 1))
    done
    kill -TERM "$pid" 2>/dev/null
    wait "$pid"
    DRIVE_EXIT=$?
    DRIVE_OUT="$log"
    if grep -qF "RESTORE DRILL PASSED" "$log"; then
        echo "  FAILED   ${CURRENT} — the drill reached PASSED before the signal landed;"
        echo "             this run did not drive the signal path at all"
        FAILED=$((FAILED + 1))
    elif [ "$DRIVE_EXIT" -eq 143 ]; then
        echo "  ok       ${CURRENT} — exit ${DRIVE_EXIT} (128 + SIGTERM)"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — wanted exit 143, got ${DRIVE_EXIT}"
        sed 's/^/             | /' "$log" | tail -12
        FAILED=$((FAILED + 1))
    fi
    says "RESTORE DRILL DID NOT FINISH (exit 143)"
    db_absent "${DATABASE_NAME}_drill"
}

echo "test_backup_restore: driving scripts/backup.sh and scripts/restore_drill.sh"
echo "  database: ${DATABASE_NAME} (this checkout's, scripts/db.sh)"

case_backup_unknown_flag
case_backup_flag_without_value
case_backup_two_outputs
case_backup_absent_database
case_backup_stack_without_env_file
case_backup_to_dir_produces_an_object
case_restore_unknown_flag
case_restore_no_origin_at_a_live_stack
case_restore_origin_without_a_project_line
case_restore_target_is_the_source
case_restore_target_differs_and_the_check_moves_on
case_restore_a_broken_dump_dies_and_says_so
case_restore_killed_mid_drill_says_so_and_drops_the_scratch

echo "test_backup_restore: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a refusal did not fire, or fired with the wrong code. Both halves of a" >&2
    echo "   refusal are load-bearing: the status a caller branches on and the" >&2
    echo "   sentence a human acts on." >&2
    exit 1
fi
exit 0
