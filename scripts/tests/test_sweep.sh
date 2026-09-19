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
# drives: .github/workflows/ci.yml frontend/scripts scripts/check.sh scripts/db.sh scripts/db_sweep.sh scripts/gate_ledger.sh scripts/kill_mine.sh scripts/lifecycle.sh scripts/lifecycle_temporal.py scripts/queue_cited.sh scripts/setup.sh scripts/sweep.sh scripts/temporal_sweep.sh scripts/tests/test_backup_restore.sh scripts/tests/test_loop_ledger.sh scripts/tests/test_loop_scope.sh scripts/tests/test_pm_merge.sh scripts/tests/test_secrets_baseline_guard.sh
# The drive for `scripts/sweep.sh` and `scripts/lifecycle.sh` — the registry, the
# four verdicts, the two new Temporal classes, and the unrecognized-shape refusal.
#
#   ./scripts/tests/test_sweep.sh          run every case
#   ./scripts/tests/test_sweep.sh --list   name them and stop
#
# WHY IT EXISTS, and it is `scripts/tests/test_backup_restore.sh`'s reason: a
# broom is made of refusals, and a refusal nothing drives can be deleted by
# accident and stay deleted — the census goes on printing, the happy path goes on
# passing, and the first person to find out is whoever ran `--force-foreign` on a
# machine full of live sibling clones.
#
# IT CREATES ITS OWN MACHINERY AND SWEEPS THAT. Every destructive case here acts
# on a SCRATCH IDENTITY this file invents, owns and tears down —
# `djb_lc2scratch_<this checkout's 8 hex>`, derivation-shaped so the frame judges it exactly as
# it judges a real one, and derived by no checkout that has ever existed, so it
# reads FOREIGN. Every destructive call carries `--only "$SCRATCH_BASE"`, so a
# `--force-foreign` in this file can reach nothing but what this file made. That
# narrowing is not a convenience: it is the reason a destroy path can be proven
# at all on a shared machine, and the driver REFUSES TO START (exit 2) if a
# checkout it can see derives the scratch identity.
#
# ONE DESTRUCTIVE CALL IS NOT AIMED AT THE SCRATCH IDENTITY, and it is named
# rather than left to be discovered: `case_this_checkouts_running_work_survives_
# force_foreign` has to aim at an identity that is `live` AND `mine` at once,
# which no invented name can ever be. It is scoped to `--only "$OUR_BASE"` —
# THIS CHECKOUT'S DERIVED base, computed here and never read off `$DATABASE_NAME`,
# so an exported name cannot widen it — and it acts on a probe
# execution this file starts and terminates. Its whole assertion is that nothing
# was destroyed.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * A REAL MACHINE-WIDE SWEEP. Never, from here. `--force-foreign` without
#     `--only` is the owner's explicit step after reading a census, and a test
#     that took it would be deciding for them.
#   * A LIVE `DescribeTaskQueue` POLLER. Still never, from here: it needs a
#     worker process on the SHARED Temporal server, which this driver has no
#     business starting. The verdict FUNCTION is driven directly instead
#     (`case_verdict_grammar_answers_all_four`), which is where the ordering
#     between the four actually lives.
#
#     THE SESSION HALF IS NOW COVERED, and the split is deliberate rather than
#     inconsistent. `--assert-none`'s working-set exemption (its queue row)
#     turns on POSITIVE live-use evidence, and an exemption nothing exercises is
#     a branch that can be deleted by accident and stay deleted. A live
#     `pg_stat_activity` session on THIS CHECKOUT'S OWN database costs one
#     short-lived child of this driver, creates no server-side durable object,
#     touches nothing another agent can see, and reaches the identical branch of
#     `scripts/sweep.sh`. A poller costs a worker on a server every checkout on
#     the machine shares. The two are not the same risk and are not treated the
#     same way; the poller half is DECLARED by the case that cannot reach it.
#
#   * WHICH WORLD A CONSUMER IS IN, except where a case ASKS. Three cases in this
#     repository's drives carried the premise "nothing polls this checkout's
#     queue" — true on this workerless template, false on a product running its
#     local build, and found by a consumer rather than by us (its queue row).
#     The two here now fork on `our_pollers` and print the world they proved and
#     the one they skipped. That is a model of a product's machine, not a
#     product's machine: what this file can see is a poller count on one queue.
#   * `test-server-process`. Planting one means starting a real
#     `temporal-test-server` and orphaning it, which is the exact leak the
#     census exists to stop. Its census read is exercised by every unfiltered run;
#     `scripts/temporal_sweep.sh` owns its sweep and the gate already runs it.
#   * WHETHER A REFUSAL IS THE RIGHT REFUSAL. This asserts that the frame refuses
#     and says a particular thing. That the thing is TRUE is the reader's
#     judgement, exactly as it is for every row in the census.
#
# EXIT (the house semantics, and this file is held to them too):
#   0  every case drove its property and got it
#   1  a case FAILED — a refusal did not fire, or fired with the wrong code
#   2  COULD NOT LOOK — no docker, no postgres, no temporal, no python3. 2
#      outranks a pass: a driver that could not run its cases has not cleared them.
#
# `set -e` IS DELIBERATELY OFF. Every case runs a command whose whole purpose is
# to fail; under `set -e` the first refusal would end the driver and it would
# report a pass on the cases it never reached.

set -uo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before anything asks git a question ----
#
# A drive run from the pre-push hook inherits an absolute `GIT_DIR` from
# `git -C <linked worktree> push`. This drive runs no `git -C` of its own, so
# it cannot escape the way `scripts/tests/test_pm_merge.sh` did — but it is the
# one file in this repository that aims `--force-foreign` at a destroy path,
# and it decides what is safe to aim at by asking `lc_owning_checkout` which
# checkout derives an identity. That derivation reads `git rev-parse
# --show-toplevel` and `git worktree list`. Under an inherited `GIT_DIR` both
# answer for the PUSHING worktree instead of this one, so the driver would be
# vouching for a checkout it is not standing in before it destroys anything.
# Same environment, same class, so the same preamble.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_sweep: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the neutralisation that keeps this drive's safety check" >&2
    echo "   reading its own checkout. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

PASSED=0
FAILED=0
SKIPPED=0

cannot_look() {
    echo "!! test_sweep: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    # THE DEFINITION, NOT THE CALL. `^case_` matches the definition line AND the
    # column-zero invocation at the foot of this file, so every case was named
    # twice and a reader diffing two `--list` outputs was diffing a doubled list.
    # `test_list_legs.sh:149` is the form that was already right.
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    # A mistyped flag is never a silently different run.
    echo "!! unknown argument '$1': test_sweep.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v docker >/dev/null 2>&1 || cannot_look "no docker on PATH; both servers live in the compose stack"
command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH; the Temporal scans parse JSON with it"
[ -x scripts/sweep.sh ] || cannot_look "scripts/sweep.sh is not executable from $(pwd)"
[ -f scripts/lifecycle.sh ] || cannot_look "scripts/lifecycle.sh is missing from $(pwd)"

# shellcheck source=scripts/lifecycle.sh
source scripts/lifecycle.sh

db_query 'SELECT 1' -tA >/dev/null 2>&1 || cannot_look "the compose Postgres did not answer; the database classes cannot be censused"
lc_temporal operator cluster health >/dev/null 2>&1 ||
    lc_temporal schedule list -o json >/dev/null 2>&1 ||
    cannot_look "the compose Temporal did not answer; the schedule and execution classes cannot be censused"

# --- the scratch identity, and the guard that makes it safe -------------------

# THE SCRATCH IDENTITY IS DERIVED FROM THIS CHECKOUT, the way this repository
# derives every other identity that must not be shared.
#
# IT USED TO BE A CONSTANT — derivation-SHAPED (`djb_<word>_<8 hex>`) but derived
# from nothing, so every checkout on the machine invented the SAME one. Two
# checkouts running this drive at once therefore planted and destroyed each
# OTHER's machinery: ten spurious reds in one pass, reproduced twice, and a red
# `test_sweep` is unreadable on a shared box. The precondition below could not
# see it either — it asks whether a checkout it can SEE derives the name, and a
# concurrent peer's plant is not a derivation.
#
# `db_path_hash` is `scripts/db.sh`'s, sourced through `scripts/lifecycle.sh`
# above, and it is the same function `db_name` uses — never a second hash, so
# there is one answer to "which checkout is this" in the whole tree. The input is
# this checkout's absolute top level PLUS this drive's own name, so a checkout
# running two drives that both plant does not collide with itself either.
SCRATCH_TOPLEVEL="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD")"
SCRATCH_HASH="$(db_path_hash "${SCRATCH_TOPLEVEL}|test_sweep")"
case "$SCRATCH_HASH" in
[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
*)
    cannot_look "db_path_hash returned '${SCRATCH_HASH}' for this checkout, which is not
   eight hex digits. Every name this driver plants and later DESTROYS is built
   from it; a short or empty one would aim --force-foreign at a prefix"
    ;;
esac
SCRATCH_BASE="djb_lc2scratch_${SCRATCH_HASH}"
SCRATCH_QUEUE="djb-lc2scratch_${SCRATCH_HASH}"
SCRATCH_TEST_DB="test_${SCRATCH_BASE}_gw0"
SCRATCH_HP_DB="${SCRATCH_BASE}_hp"
SCRATCH_FAKE_DB="djb_zzz_${SCRATCH_HASH}_lc2fake"
# The foreign-but-ours-shaped database `case_new_classes_are_censused_as_foreign`
# creates and drops: `djb_<word>_<8 hex>` is the shape that says this repository
# made it, and the hex are this checkout's so a peer's run cannot drop it
# mid-assertion.
SCRATCH_FOREIGN_DB="djb_zzz_${SCRATCH_HASH}"
SCRATCH_SCHEDULE="lc2scratch-probe:${SCRATCH_QUEUE}"
SCRATCH_SCHEDULE_WORKFLOW="lc2scratch:probe:noun:${SCRATCH_HASH}"
SCRATCH_EXECUTION="lc2scratch:probe:open:${SCRATCH_HASH}"
# A schedule keyed to a queue with NO path digest in it — the shape an
# undigested name or a hand-pinned `TEMPORAL_TASK_QUEUE` produces. It must read REFUSED and
# survive even a `--force-foreign`. The QUEUE is the digest-less half and stays
# so; the schedule and workflow ids carry this checkout's hash, because a
# Temporal id is unique per namespace and two checkouts would otherwise be
# writing one another's.
SCRATCH_UNDERIVED_QUEUE="djb-lc2scratchnohash"
SCRATCH_UNDERIVED_SCHEDULE="lc2scratch-probe-${SCRATCH_HASH}:${SCRATCH_UNDERIVED_QUEUE}"
SCRATCH_UNDERIVED_WORKFLOW="lc2scratch:probe:noun:underived:${SCRATCH_HASH}"
# The strand this driver plants ON THE SIBLING when a worker is up on this
# checkout's own queue and the gate-leg's own scope therefore cannot hold one
# (the fork-on-the-worker pattern; see the remedy case).
SCRATCH_STRAND="lc2scratch:probe:strand:${SCRATCH_HASH}"
# The stray run planted on THIS checkout's queue to prove --assert-none keeps
# its teeth: owned, and polled by nothing, which is a strand and never a working
# set. Prefixed so it is attributable to this driver on a shared server, and
# hashed for the same reason every name above is.
OWN_STRAY_PROBE="lc2probe:stray:${SCRATCH_HASH}"
# Its mirror: an owned run on this checkout's queue WHILE A WORKER IS POLLING IT
# — the consumer's own scenario, planted only in the world that already has the
# worker (see the exemption case's fork).
OWN_WORKING_SET_PROBE="lc2probe:workingset:${SCRATCH_HASH}"
# The live-execution probe and the strand the gate-census remedy case clears.
OWN_LIVE_PROBE="lc2probe:live:${SCRATCH_HASH}"
OWN_REMEDY_STRAND="lc2probe:remedystrand:${SCRATCH_HASH}"

# THIS CHECKOUT'S OWN IDENTITY, AND IT IS THE DERIVATION — never `$DATABASE_NAME`.
# `scripts/db.sh` rule 1 lets an exported name WIN over the
# derivation, and `.github/workflows/ci.yml` exports `djb_main`; the frame
# attributes ownership by hashing checkout paths and by nothing else. A case that
# built "mine" out of the effective name was therefore asking for `live` and
# `mine` at once while handing the frame a name it refuses — green on a laptop
# where the two coincide, red on every pinned run. `case_a_dot_env_pin_does_not_
# decide_who_owns_what` says this in one direction; these two say it in the other.
OUR_BASE="$(db_name)"
OUR_QUEUE="djb-${OUR_BASE#djb_}"
# Set before the teardown is registered, so an early exit path can read it.
PLANTED_OUR_DATABASE=0

lc_load_live_bases
if [ "${#LC_LIVE_BASES[@]}" -eq 0 ]; then
    cannot_look "git worktree list named no checkout, so the frame itself would exit 2"
fi
if lc_owning_checkout "$SCRATCH_BASE" >/dev/null; then
    # Astronomically unlikely and checked anyway: every destructive case below
    # aims --force-foreign at this identity, and it must belong to nobody.
    cannot_look "a checkout this run can see derives ${SCRATCH_BASE}; this driver will not
   aim --force-foreign at an identity somebody owns"
fi

# THE SIBLING REFUSAL, and the two answer different questions. The one above asks
# whether somebody OWNS the name. This one asks whether the name is already
# THERE — a database under this checkout's own scratch identity, standing at the
# moment this run starts, which nothing can have left but a killed earlier run of
# this same file in this same checkout.
#
# WHY IT IS A REFUSAL AND NOT A SILENT DROP. Every destructive case below aims
# `--force-foreign` at this identity, and the cases that assert what was
# destroyed are assertions about what THIS RUN planted. Starting on top of a
# leftover makes the first plant's "created" a lie and the first destroy's
# "gone" an accident, and it does it silently. Dropping it here instead would be
# this driver quietly destroying a database nobody asked it to — the exact
# licence the whole file exists to keep narrow.
#
# So it names the broom and stops. `scripts/db_sweep.sh --name <it>` is the one
# that takes a name, and the operator who runs it is the one accountable for it.
if [ "$(db_query "SELECT 1 FROM pg_database WHERE datname = :'name'" -tA -v name="$SCRATCH_BASE" 2>/dev/null)" = "1" ]; then
    cannot_look "a database named ${SCRATCH_BASE} already exists and no checkout derives it.
   Nothing but a KILLED earlier run of this file in this checkout can have left it,
   and every destructive case below aims --force-foreign at that identity: starting
   on top of it would make this run's 'created' and 'destroyed' assertions about
   somebody else's residue. This driver will not drop a database it did not plant.
   The broom is:  ./scripts/db_sweep.sh --name ${SCRATCH_BASE}"
fi

WORK="$(mktemp -d)"
drive_require_scratch WORK "${WORK:-}"

# THE EVIDENCE THIS DRIVE NAMES when it authorises a destroy. `--force-foreign`
# is refused without `--roots <dir>`, and what a root MEANS is "I scanned
# here for checkouts of this repository". This one is empty on purpose: the
# scratch identity every destructive case below is aimed at is derived by no
# checkout anywhere, so a root holding none is the honest evidence to name — and
# an empty scan cannot promote anything to `live` by accident, which keeps the
# destroy cases proving what they always proved.
SCRATCH_ROOT="${WORK}/scratch-root"
mkdir -p "$SCRATCH_ROOT"

# The Temporal half of the teardown, as its own function so the required-empty
# case can reuse it to REPAIR residue from a killed earlier run rather than
# growing a second list of the same deletions — a second list is a list that
# stops matching the day a plant is added to only one of them.
teardown_scratch_temporal() {
    lc_temporal schedule delete --schedule-id "$SCRATCH_SCHEDULE" >/dev/null 2>&1
    lc_temporal schedule delete --schedule-id "$SCRATCH_UNDERIVED_SCHEDULE" >/dev/null 2>&1
    lc_temporal workflow terminate --workflow-id "$SCRATCH_EXECUTION" \
        --reason "test_sweep teardown" >/dev/null 2>&1
    lc_temporal workflow terminate --workflow-id "$SCRATCH_STRAND" \
        --reason "test_sweep teardown" >/dev/null 2>&1
}

teardown() {
    # Idempotent, and it runs on every exit path including a failed case: a
    # driver that leaks its own scratch machinery is the leak it is testing for.
    #
    # THE HELD SESSION FIRST. The --assert-none exemption fixture holds a real
    # connection to this checkout's own database; a leaked one would also block
    # the `DROP DATABASE` at the foot of this function for as long as it lived.
    drop_the_session >/dev/null 2>&1
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_BASE" >/dev/null 2>&1
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_TEST_DB" >/dev/null 2>&1
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_HP_DB" >/dev/null 2>&1
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_FAKE_DB" >/dev/null 2>&1
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_FOREIGN_DB" >/dev/null 2>&1
    teardown_scratch_temporal
    lc_temporal workflow terminate --workflow-id "$OWN_LIVE_PROBE" \
        --reason "test_sweep teardown" >/dev/null 2>&1
    # The stray probe: this checkout's OWN queue, planted to prove
    # --assert-none keeps its teeth on a run nothing is polling. Its own case
    # ends it — this line only fires when that case did not get that far.
    lc_temporal workflow terminate --workflow-id "$OWN_STRAY_PROBE" \
        --reason "test_sweep teardown" >/dev/null 2>&1
    lc_temporal workflow terminate --workflow-id "$OWN_WORKING_SET_PROBE" \
        --reason "test_sweep teardown" >/dev/null 2>&1
    # The strand `case_the_gate_census_remedy_actually_clears_a_strand` plants on
    # THIS checkout's queue. Its own body ends it by running the gate's printed
    # remedy — which is the assertion — so this line only ever fires when the
    # remedy did not work, i.e. exactly when the case has just gone red. A
    # driver that leaked a strand while proving strands get cleared would be
    # funny once.
    lc_temporal workflow terminate --workflow-id "$OWN_REMEDY_STRAND" \
        --reason "test_sweep teardown" >/dev/null 2>&1
    # ONLY IF THIS RUN CREATED IT. See plant_our_checkout_database.
    if [ "$PLANTED_OUR_DATABASE" -eq 1 ]; then
        db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$OUR_BASE" >/dev/null 2>&1
    fi
    # The rooted-clone case's decoy, dropped here only when that case did not get
    # as far as dropping it itself. A decoy that outlives its drive is a leak of
    # exactly the shape the census exists to find.
    if [ -n "${ROOTED_CLONE_DECOY:-}" ]; then
        db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$ROOTED_CLONE_DECOY" >/dev/null 2>&1
    fi
    if [ -n "${SECOND_ROOT_DECOY:-}" ]; then
        db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SECOND_ROOT_DECOY" >/dev/null 2>&1
    fi
    rm -rf "$WORK"
}
drive_at_exit teardown
trap 'exit 130' INT
trap 'exit 143' TERM

plant_our_checkout_database() {
    # A checkout database that EXISTS and that a visible checkout derives — the
    # `live` fixture two cases below need and neither of them may assume. On a
    # laptop `scripts/setup.sh` made it long ago and this is a no-op; on a runner
    # the database that exists is the PINNED name (`djb_main`), which is not
    # derivation-shaped, so the frame refuses it and there is no live checkout
    # database anywhere for the two instruments to agree about. So the driver
    # makes its own, exactly as it makes everything else it acts on, and drops it
    # again ONLY if this run is the one that created it: dropping a checkout
    # database somebody is working in is the very thing this whole file is about. Postgres
    # is the second belt — `DROP DATABASE` refuses a database with sessions on
    # it — so even the narrow window where a peer created one under this
    # checkout's name mid-run cannot take a database anybody is connected to.
    db_present "$OUR_BASE" && return 0
    db_query 'CREATE DATABASE :"name"' -v name="$OUR_BASE" >/dev/null 2>&1 &&
        PLANTED_OUR_DATABASE=1
}

plant_databases() {
    db_query 'CREATE DATABASE :"name"' -v name="$SCRATCH_BASE" >/dev/null 2>&1
    db_query 'CREATE DATABASE :"name"' -v name="$SCRATCH_TEST_DB" >/dev/null 2>&1
    db_query 'CREATE DATABASE :"name"' -v name="$SCRATCH_HP_DB" >/dev/null 2>&1
}

# THE SIBLING'S DEADNESS, ASKED EVERY PLANT AND ANNOUNCED ONCE.
#
# Asked every time because the property is what the plant means; announced once
# because four identical lines in a transcript teach a reader to skip all four.
# A poller on this queue would be a finding in its own right — something is
# polling an identity no checkout on this machine derives — and it is reported
# as a failure of the PREMISE rather than silently degrading every case that
# rests on it into a green that proves nothing.
SCRATCH_DEADNESS_SAID=0
require_dead_scratch_queue() {
    local pollers
    pollers="$(lc_queue_pollers "$SCRATCH_QUEUE" 2>/dev/null)"
    case "${pollers:-}" in
    '' | *[!0-9]*) pollers=0 ;;
    esac
    if [ "$pollers" != "0" ]; then
        echo "  FAILED   premise: ${SCRATCH_QUEUE} has ${pollers} poller(s) and must have none"
        echo "             the dead-queue cases below rest on this sibling identity being polled"
        echo "             by nothing in any world. Something is polling an identity no checkout"
        echo "             derives; that is the finding, and no case here may be read as green."
        FAILED=$((FAILED + 1))
        return 1
    fi
    if [ "$SCRATCH_DEADNESS_SAID" -eq 0 ]; then
        SCRATCH_DEADNESS_SAID=1
        echo "  ok       premise: ${SCRATCH_QUEUE} has 0 pollers — the dead queue every"
        echo "             dead-queue case below is proved on, REQUIRED here rather than assumed,"
        echo "             and true in both worlds because no checkout derives this sibling"
        PASSED=$((PASSED + 1))
    fi
    return 0
}

plant_temporal() {
    # Paused, and an interval a year long: nothing must ever actually start from
    # this schedule on a shared server. The execution is started deliberately and
    # stays Running forever because no worker polls the scratch queue — which is
    # exactly the "sweep-start stranded on a dead queue" shape being proven.
    #
    # THE DEAD QUEUE IS REQUIRED, NOT ASSUMED (its queue row, the third pattern:
    # prove on a pollerless, required-empty SIBLING). "No worker polls the
    # scratch queue" was a sentence in this comment and nothing else, and a
    # sentence in a comment is exactly the shape of premise a consumer found for
    # us on the other two cases. It happens to be true here for a structural
    # reason — `djb_lc2scratch_<hash>` is a SIBLING identity no checkout has
    # ever derived, so no worker in any world has a reason to poll it, which is
    # what makes it the right place to prove a dead-queue property in BOTH the
    # workerless template and a product running its local build. Structural or
    # not, it is now ASKED and PRINTED on every plant: a premise this whole file
    # rests on may not be the one thing nobody checks.
    require_dead_scratch_queue || return 1
    lc_temporal schedule create --schedule-id "$SCRATCH_SCHEDULE" \
        --interval 8760h --paused \
        --workflow-id "$SCRATCH_SCHEDULE_WORKFLOW" \
        --task-queue "$SCRATCH_QUEUE" --type "Lc2ScratchNeverRuns" >/dev/null 2>&1
    lc_temporal workflow start --workflow-id "$SCRATCH_EXECUTION" \
        --task-queue "$SCRATCH_QUEUE" --type "Lc2ScratchNeverRuns" >/dev/null 2>&1
}

# --- the two assertions every case makes -------------------------------------
#
# Usage: drive <label> <want-exit> -- <command...>
# Leaves the transcript in $DRIVE_OUT and the status in $DRIVE_EXIT, so a caller
# can add a `says` assertion about the SAME run rather than running it twice (two
# runs is two answers, and the second one is the one nobody read).
DRIVE_OUT=""
DRIVE_EXIT=0
CURRENT=""
drive() {
    local label="$1" want="$2"
    shift 3
    CURRENT="$label"
    DRIVE_OUT="${WORK}/$(printf '%s' "$label" | tr -c 'a-zA-Z0-9' '_').log"
    "$@" >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    if [ "$DRIVE_EXIT" -eq "$want" ]; then
        echo "  ok       ${label} — exit ${DRIVE_EXIT}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted exit ${want}, got ${DRIVE_EXIT}"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -20
        FAILED=$((FAILED + 1))
    fi
}

# THE FLOOR UNDER BOTH HALVES. `says_not` over a capture that is
# empty, missing or pathless is TRUE — it prints `ok` and counts a pass — and
# `says` over one is a red blaming the subject for a capture that was never
# taken. Neither is an answer about the run. `drive_capture_refusal`
# (`drive_preamble.sh` §7) is the shared shape; the refusal below is this
# drive's own voice.
capture_floor() {
    local why
    why="$(drive_capture_refusal "${CURRENT:-a case}" "${DRIVE_OUT:-}" "${DRIVE_EXIT:-<none>}")" &&
        cannot_look "$why"
    return 0
}

# The second half. A refusal with the right code and the wrong sentence is a
# refusal nobody can act on, so both are asserted about the same run.
says() {
    local needle="$1"
    capture_floor
    if grep -qF -- "$needle" "$DRIVE_OUT"; then
        echo "  ok       ${CURRENT} — says \"${needle}\""
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — does not say \"${needle}\""
        sed 's/^/             | /' "$DRIVE_OUT" | tail -20
        FAILED=$((FAILED + 1))
    fi
}

says_not() {
    local needle="$1"
    capture_floor
    if grep -qF -- "$needle" "$DRIVE_OUT"; then
        echo "  FAILED   ${CURRENT} — says \"${needle}\" and must not"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -20
        FAILED=$((FAILED + 1))
    else
        echo "  ok       ${CURRENT} — does not say \"${needle}\""
        PASSED=$((PASSED + 1))
    fi
}

# The floor above is only worth its name if it can be shown to
# fire, and the showing has to be a RUN of the shipped reader rather than a
# reading of it. Both readers are driven, in a subshell of this drive's own
# making, over a capture emptied exactly the way a refactor empties one — the
# variable cleared. A subshell does not run this shell's EXIT trap, so the
# plant costs nothing beyond its own two processes.
case_an_empty_capture_is_could_not_look() {
    local out="${WORK}/empty-capture.log" rc reader
    for reader in says says_not; do
        CURRENT="an emptied capture is could-not-look: ${reader}"
        rc=0
        (
            CURRENT="a planted case"
            DRIVE_OUT=""
            DRIVE_EXIT=0
            "$reader" "NOTHING THIS RUN COULD EVER HAVE PRINTED"
        ) >"$out" 2>&1 || rc=$?
        if [ "$rc" != "2" ]; then
            echo "  FAILED   ${CURRENT} — an emptied capture exited ${rc}, not 2; a reader that answers a question it could not look at is the whole of B.5"
            sed 's/^/             | /' "$out" | sed -n '1,10p'
            FAILED=$((FAILED + 1))
            continue
        fi
        if ! grep -qF 'capture with no path at all' "$out"; then
            echo "  FAILED   ${CURRENT} — exit 2, but the refusal never says the capture is what could not be read"
            sed 's/^/             | /' "$out" | sed -n '1,10p'
            FAILED=$((FAILED + 1))
            continue
        fi
        echo "  ok       ${CURRENT} — exit 2, naming the capture and the exit code of the run that did not fill it"
        PASSED=$((PASSED + 1))
    done

    # THE NEGATIVE, so the floor is not simply refusing everything: a capture
    # that IS there and does NOT carry the needle is a red or a pass about the
    # SUBJECT, never a could-not-look.
    CURRENT="a capture with bytes in it is judged, not refused"
    printf 'the subject said something\n' >"${WORK}/non-empty-capture.log"
    rc=0
    (
        CURRENT="a planted case"
        DRIVE_OUT="${WORK}/non-empty-capture.log"
        DRIVE_EXIT=0
        says_not "NOTHING THIS RUN COULD EVER HAVE PRINTED"
    ) >"$out" 2>&1 || rc=$?
    if [ "$rc" = "0" ] && grep -qF 'does not say' "$out"; then
        echo "  ok       ${CURRENT} — the floor is a floor, not an off switch"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — a readable capture exited ${rc}: $(sed -n 1p "$out")"
        FAILED=$((FAILED + 1))
    fi
}

# A plain property assertion, for the cases that are not about a transcript.
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

# A `says` for a STRING rather than a transcript, so a function's own words can
# be asserted without running a script to capture them.
says_contains() {
    local label="$1" haystack="$2" needle="$3"
    case "$haystack" in
    *"$needle"*)
        echo "  ok       ${label} — says \"${needle}\""
        PASSED=$((PASSED + 1))
        ;;
    *)
        echo "  FAILED   ${label} — does not say \"${needle}\""
        echo "             | ${haystack}"
        FAILED=$((FAILED + 1))
        ;;
    esac
}

# The mirror of `says_contains`, for a sentence that must have STOPPED being
# said. It exists for exactly one thing today: an inoperative remedy that was
# printed for a while must not come back, and "it is gone" is not something a
# positive assertion can express.
says_not_contains() {
    local label="$1" haystack="$2" needle="$3"
    case "$haystack" in
    *"$needle"*)
        echo "  FAILED   ${label} — says \"${needle}\" and must not"
        FAILED=$((FAILED + 1))
        ;;
    *)
        echo "  ok       ${label} — does not say \"${needle}\""
        PASSED=$((PASSED + 1))
        ;;
    esac
}

db_present() {
    [ "$(db_query "SELECT count(*) FROM pg_database WHERE datname = :'name'" -v name="$1" -tA 2>/dev/null)" = "1" ]
}

# --- THE BELT FOR THE TWO UNNARROWED REFUSALS, and it is load-bearing ---------
#
# Two refusals in this file can only be driven by TYPING THE MACHINE-WIDE FORM:
# `sweep.sh --sweep --force-foreign` with no `--roots` and no `--only`, and
# `db_sweep.sh --all-checkouts --orphans --sweep --force-foreign` with no
# `--roots`. That is the exact sentence that destroyed 1,472 databases on a
# consumer's box in one run, a live builder's among them, and it is the sentence
# these two cases exist to prove is now REFUSED.
#
# A DRIVE MAY NOT AIM THAT AT FOUND STATE — not even at a subject it believes
# refuses, because the subject is the thing under test and a regression that
# removed the refusal would be discovered by this file ENACTING the loss. So the
# belt does not come from the subject: every path from either script to a
# destroy runs through `docker compose exec` (`scripts/db.sh:446`,
# `scripts/lifecycle.sh:656-663` — there is no psql and no temporal CLI on the
# host), so a `docker` that cannot execute is a hard wall in front of every
# server, and a `python3` that cannot run is a second one in front of the
# Temporal JSON. With both shimmed, a run that got PAST the refusal enumerates an
# empty world and destroys nothing — which is exactly what it does on the
# baseline tree, where these two cases are red for the reason that matters (the
# status and the sentence) rather than for a reason that cost something.
#
# The refusals under test fire at FLAG PARSE, before `command -v docker` and
# before any scope is printed — so on the fixed tree the belt is never reached,
# and each case asserts that too (`says_not` on the could-not-look text): a
# refusal that fired only because the shim was there would be no refusal at all.
NO_SERVER_BIN=""
no_server_bin() {
    if [ -z "$NO_SERVER_BIN" ]; then
        NO_SERVER_BIN="${WORK}/no-server-bin"
        mkdir -p "$NO_SERVER_BIN"
        printf '#!/bin/sh\necho "test_sweep belt: docker is shimmed unreachable" >&2\nexit 127\n' \
            >"${NO_SERVER_BIN}/docker"
        printf '#!/bin/sh\necho "test_sweep belt: python3 is shimmed unreachable" >&2\nexit 127\n' \
            >"${NO_SERVER_BIN}/python3"
        chmod +x "${NO_SERVER_BIN}/docker" "${NO_SERVER_BIN}/python3"
    fi
    printf '%s' "$NO_SERVER_BIN"
}

# --- WHICH WORLD THIS RUN IS IN, and why the question has to be asked ---------
#
# THE PREMISE CLASS A CONSUMER FOUND FOR US (its queue row). Three cases in
# this repository's drives carried a premise that is true on THIS TEMPLATE and
# false on a product built from it: "nothing polls this checkout's queue". The
# template runs no worker, so a run planted on `$OUR_QUEUE` sits there for ever
# and every strand assertion built on it holds. A product running its local
# build has `./scripts/worker.sh` up, and on that machine an open run on that
# queue is WORK — the census says so, the gate's own leg says so
# (`scripts/check.sh`, the poller read before the open-execution assertion), and
# now `--assert-none` says so too by exempting this checkout's own working set.
# So a case that needs a STRAND cannot get one there, and one that pretends
# otherwise is green on the template and red on every real consumer.
#
# THE ANSWER IS NOT TO ASSUME EITHER WORLD. It is to ASK, once, and then either
# prove the property in the world this run is actually in or DECLARE the world
# it could not reach and PRINT the skip. A premise silently assumed is the
# defect; a premise printed beside the case that rests on it is a fact a reader
# can check.
#
# POSITIVE ONLY, exactly as `scripts/lifecycle.sh` declares this liveness:
# pollers ARE proof a worker is up; their absence proves nothing except that
# this run could not see one, which is precisely the template's world and the
# world every strand case needs.
OUR_POLLERS=""
our_pollers() {
    if [ -z "$OUR_POLLERS" ]; then
        OUR_POLLERS="$(lc_queue_pollers "$OUR_QUEUE" 2>/dev/null)"
        case "${OUR_POLLERS:-}" in
        '' | *[!0-9]*) OUR_POLLERS=0 ;;
        esac
    fi
    printf '%s' "$OUR_POLLERS"
}

# A world this run could NOT reach, named, counted and printed. It is neither a
# pass nor a failure: a case that says "I did not prove this, and here is why"
# is the honest third answer, and the summary line carries the count so a
# transcript full of skips cannot read as a clean run.
#
#   skipped <label> <the world not proved> <why this run cannot reach it>
skipped() {
    SKIPPED=$((SKIPPED + 1))
    echo "  SKIPPED  $1"
    echo "             world NOT proved: $2"
    echo "             why:              $3"
}

# The mirror: the world this case IS proving, said out loud so a green line is
# never mistaken for a green in the other world.
proving() {
    echo "  ...      $1 — proving in the world: $2"
}

# --- the presence probes, and why they are not `| grep -q` pipelines ---------
#
# THEY WERE, AND IT WAS A LATENT BUG THAT WENT OFF. The shape was
#
#     lc_scan_open_executions | awk -F'\t' -v want="$1" '$2 == want { found = 1 } END { exit !found }'
#
# and under this file's `set -o pipefail` it REPORTS ABSENT FOR SOMETHING THAT
# IS THERE. `grep -q` exits the instant it matches; `cut` upstream is still
# writing, gets SIGPIPE, and dies 141; `pipefail` hands the pipeline 141; the
# `if` reads that as "not present". Measured, not reasoned — the same shape over
# a 20 000-line stream with the match on line 1:
#
#     PIPESTATUS: 141 141 0        <- grep FOUND it (0) and the probe said no
#
# WHY IT PASSED FOR A YEAR AND THEN DID NOT. The race is between `cut` finishing
# its write and `grep` exiting. Over a short scan `cut` wins and the status is 0;
# over a long one it does not. The shared dev server's open-execution list has
# grown to ~308 (its graveyard of past executions), and `workflow list` returns NEWEST FIRST —
# so the scratch execution this drive has just planted is line ONE of three
# hundred, which is the worst case for this bug: 189 runs in 200 on this box read
# the wrong answer at that size (the GQ-1 verifier's re-measurement, 2026-09-05 — the numbers are
# in the sweep's own header below, with the 1-in-500 that also fails BELOW the
# buffer). The graveyard is the TRIGGER; the defect is this file's, and sweeping
# the graveyard would only hide it until the list grew again.
#
# THE SCHEDULE PROBE HAD THE IDENTICAL SHAPE and is fixed with it. It has not
# fired yet only because there are few schedules, which is not a property anyone
# should be relying on.
#
# ONE READER, NO EARLY EXIT. `awk` consumes the whole stream and reports through
# its exit status, so nothing upstream is ever handed a closed pipe.
schedule_present() {
    # FIELD ONE, not the whole line: the scan carries the clocks after the id
    # now, and a whole-line match would have quietly stopped finding
    # anything the day it did.
    lc_scan_schedules | awk -F'\t' -v want="$1" '$1 == want { found = 1 } END { exit !found }'
}

execution_present() {
    lc_scan_open_executions | awk -F'\t' -v want="$1" '$2 == want { found = 1 } END { exit !found }'
}

# --- CRITERION 1: the registry IS the population ------------------------------

case_registry_is_the_declared_population() {
    # THE PIN. Ten classes, by name, in declaration order. An eleventh cannot be
    # added without this line changing — which is the point: the registry is the
    # population, so a change to the population is a change somebody made on
    # purpose and a reviewer can see. It has done its job once already:
    # `migration-template` reddened this line the moment it was declared,
    # and the same run showed the class was claimed by `lc_class_of` and printed
    # by no census, because `scripts/sweep.sh`'s `DB_CLASSES` is a second list
    # and it did not know either.
    local want got
    want="migration-template checkout-database test-database hot-path-cache perf-world restore-drill-database task-queue schedule open-execution test-server-process"
    got="$(./scripts/sweep.sh --list-classes | tr '\n' ' ' | sed 's/ *$//')"
    holds "registry: the declared classes" "$want" "$got"
}

case_registry_declares_all_seven_columns() {
    # A class that does not say how it is enumerated is a class nothing
    # enumerates. `lc_registry_check` is the frame's own refusal; this drives it,
    # and then re-reads every field so a silently blank one cannot survive.
    local name blank=0 i value
    if lc_registry_check >/dev/null 2>&1; then
        echo "  ok       registry: lc_registry_check accepts every declaration"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   registry: lc_registry_check refuses its own declarations"
        FAILED=$((FAILED + 1))
    fi
    for name in $(lc_classes); do
        for i in 3 4 5 6 7 8; do
            value="$(lc_field "$name" "$i")"
            [ -n "$value" ] || blank=$((blank + 1))
        done
    done
    holds "registry: identity/enumerate/liveness/destroy/warm/disposable all declared" "0" "$blank"
}

case_registry_claims_every_planted_shape() {
    # The other half of "the registry IS the population": a shape the identity
    # grammar produces must be ATTRIBUTED to a class, not merely tolerated.
    holds "claim: the bare derived base is a checkout-database" \
        "checkout-database" "$(lc_class_of database "$SCRATCH_BASE")"
    holds "claim: test_<base>_gwN is a test-database" \
        "test-database" "$(lc_class_of database "$SCRATCH_TEST_DB")"
    holds "claim: <base>_hp is a hot-path-cache" \
        "hot-path-cache" "$(lc_class_of database "${SCRATCH_BASE}_hp")"
    holds "claim: <base>_perf is a perf-world" \
        "perf-world" "$(lc_class_of database "${SCRATCH_BASE}_perf")"
    holds "claim: <base>_drill is a restore-drill-database" \
        "restore-drill-database" "$(lc_class_of database "${SCRATCH_BASE}_drill")"
    holds "claim: <prefix>:<queue> is a schedule" \
        "schedule" "$(lc_class_of schedule "$SCRATCH_SCHEDULE")"
    holds "claim: a derived task queue is an open-execution's identity" \
        "open-execution" "$(lc_class_of open-execution "$SCRATCH_QUEUE")"
    # And the shape NO class claims — the whole point of the refusal below.
    holds "claim: a derived-shaped name with an undeclared suffix is claimed by nobody" \
        "" "$(lc_class_of database "$SCRATCH_FAKE_DB" || true)"
}

# --- CRITERION 2: four verdicts, one enumerator -------------------------------

case_verdict_grammar_answers_all_four() {
    # The verdict function, driven directly, because the ORDER between the four
    # is the part that matters and end-to-end cases can only reach two of them on
    # a machine this driver is not allowed to disturb.
    local mine
    mine="${LC_LIVE_BASES[0]}"
    holds "verdict: a name outside the derivation is REFUSED" \
        "REFUSED" "$(lc_verdict "djb_main" 0)"
    holds "verdict: a visible checkout's identity is live" \
        "live" "$(lc_verdict "$mine" 0)"
    holds "verdict: an unclaimed identity with a live session is IN USE" \
        "IN USE" "$(lc_verdict "$SCRATCH_BASE" 3)"
    holds "verdict: an unclaimed identity with no evidence is FOREIGN" \
        "FOREIGN" "$(lc_verdict "$SCRATCH_BASE" 0)"
    # REFUSED outranks everything, including a live session: a name this
    # repository never derived is not reasoned about at all.
    holds "verdict: REFUSED outranks a live session" \
        "REFUSED" "$(lc_verdict "postgres" 7)"
}

case_one_enumerator_two_consumers() {
    # `db_sweep.sh` reads liveness from `scripts/lifecycle.sh` now, so the two
    # instruments cannot come to disagree about whether a checkout is alive. The
    # property is AGREEMENT on the same name, not a shared line of source.
    local base reaper
    # The fixture first: a live checkout database has to EXIST before two
    # instruments can agree about one, and on a runner none does.
    plant_our_checkout_database
    # A base the FRAME judged `live`, taken from the frame's own transcript, then
    # put to the reaper. Not a hand-picked name: a name only one of them can see
    # would prove nothing about whether they agree.
    base="$(./scripts/sweep.sh --class checkout-database 2>/dev/null | awk '/^  live /{print $2; exit}')"
    if [ -z "$base" ]; then
        echo "  FAILED   one enumerator: the frame named no live checkout database to compare"
        FAILED=$((FAILED + 1))
        return 0
    fi
    echo "  ok       one enumerator: the frame calls ${base} live"
    PASSED=$((PASSED + 1))
    reaper="$(./scripts/db_sweep.sh --all-checkouts --orphans 2>&1 | grep -c "^  live     ${base} ")"
    holds "one enumerator: db_sweep's reaper calls the same base live" "1" "$reaper"
}

case_sweep_refuses_an_unknown_flag() {
    drive "sweep: unknown flag" 2 -- ./scripts/sweep.sh --no-such-flag
    says "unknown argument '--no-such-flag'"
}

case_sweep_refuses_force_foreign_without_sweep() {
    # --force-foreign is not a census setting. Read the census, then authorise.
    drive "sweep: --force-foreign without --sweep" 2 -- ./scripts/sweep.sh --force-foreign
    says "licence to DESTROY and means nothing without --sweep"
}

case_sweep_refuses_an_empty_only() {
    # The one way a scoped --force-foreign silently becomes a machine-wide one.
    drive "sweep: --only with no value" 2 -- ./scripts/sweep.sh --only
    says "--only needs an identity prefix"
}

case_sweep_refuses_a_root_that_is_not_there() {
    drive "sweep: --roots at a non-directory" 2 -- ./scripts/sweep.sh --roots "${WORK}/absent"
    says "is not a directory"
}

case_sweep_refuses_an_unknown_class() {
    drive "sweep: --class naming nothing" 2 -- ./scripts/sweep.sh --class no-such-class
    says "no class named 'no-such-class'"
}

# --- CRITERION 3: the two NEW classes, against scratch machinery --------------

# THE SIBLING IS REQUIRED EMPTY BEFORE ANYTHING IS PLANTED IN IT.
#
# The other half of that third pattern. Deadness (no poller) says the plants
# will sit still; EMPTINESS says that what the census reports afterwards is what
# THIS run planted and not what a killed earlier run left behind. Both halves
# were assumed and neither was asked, which is how a case can go on passing over
# somebody else's residue.
#
# RESIDUE IS REPAIRED AND PRINTED, NOT REDDENED. Anything under this identity
# prefix is by construction this driver's own — no checkout derives
# `djb_lc2scratch_<hash>`, and nothing else in the repository writes it — so a
# leftover is a killed run of THIS FILE, not a defect in the subject. A red for
# it would train a reader to ignore reds. It is removed, said out loud, and the
# premise is then re-asserted; only a scope that is still not empty after the
# repair is a failure.
case_the_dead_queue_sibling_is_required_empty_before_anything_is_planted() {
    local rc
    CURRENT="the dead-queue sibling starts empty"
    DRIVE_OUT="${WORK}/sibling_empty.log"

    ./scripts/sweep.sh --only "$SCRATCH_BASE" --assert-none >"$DRIVE_OUT" 2>&1
    rc=$?
    if [ "$rc" != "0" ]; then
        echo "  ...      ${CURRENT} — the sibling scope was NOT empty (exit ${rc}); that is"
        echo "             residue from a killed earlier run of this driver, since nothing else"
        echo "             in this repository writes ${SCRATCH_BASE}. Removing it and re-asking."
        teardown_scratch_temporal
        db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_BASE" >/dev/null 2>&1
        db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_TEST_DB" >/dev/null 2>&1
        db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_HP_DB" >/dev/null 2>&1
        ./scripts/sweep.sh --only "$SCRATCH_BASE" --assert-none >"$DRIVE_OUT" 2>&1
        rc=$?
    fi
    holds "sibling: the scratch scope is empty before the first plant" "0" "$rc"
    [ "$rc" = "0" ] || sed 's/^/             | /' "$DRIVE_OUT" | tail -20
    # And the deadness half, established here so the pair is asked together
    # rather than discovered one plant at a time. It prints and counts itself.
    require_dead_scratch_queue || true
}

case_new_classes_are_censused_as_foreign() {
    plant_databases
    plant_temporal
    drive "census: the scratch machinery reads FOREIGN" 0 -- \
        ./scripts/sweep.sh --only "$SCRATCH_BASE"
    says "FOREIGN  ${SCRATCH_SCHEDULE}"
    says "FOREIGN  ${SCRATCH_EXECUTION} (queue ${SCRATCH_QUEUE})"
    says "FOREIGN  ${SCRATCH_BASE}"
    says "FOREIGN  ${SCRATCH_TEST_DB}"
    # The warm-cache fence: shown, and NOT offered to the default broom.
    says "warm     ${SCRATCH_HP_DB}"
}

case_sweep_alone_leaves_foreign_alone() {
    # A correction bought once, restated frame-wide: --sweep is not a
    # licence over something nobody can vouch for.
    drive "sweep: --sweep alone does not touch FOREIGN" 0 -- \
        ./scripts/sweep.sh --sweep --only "$SCRATCH_BASE"
    says "--sweep --force-foreign to destroy"
    says_not "DESTROYED"
    holds "sweep: the scratch schedule survived --sweep" "yes" \
        "$(schedule_present "$SCRATCH_SCHEDULE" && echo yes || echo no)"
    holds "sweep: the scratch execution survived --sweep" "yes" \
        "$(execution_present "$SCRATCH_EXECUTION" && echo yes || echo no)"
    holds "sweep: the scratch database survived --sweep" "yes" \
        "$(db_present "$SCRATCH_BASE" && echo yes || echo no)"
}

# --- FOREIGN IS AN ABSENCE OF EVIDENCE, NEVER A LICENCE ---------------------
#
# The loss this pair pins: `--sweep --force-foreign` with no `--roots` once ran
# on a consumer's box as a verifier's teardown and reported
# `1709 found · 1472 destroyed` — a live builder's checkout database among them.
# Nothing was wrong with the census: every one of those names WAS FOREIGN to a
# run that had been pointed at no root. The defect is that an absence of
# evidence was accepted as authorisation.
#
# Both halves are now a refusal at flag parse, BEFORE the scope is printed and
# before anything is enumerated, so the transcript of a refused run contains no
# census at all — which is what the `says_not` assertions below are for.
case_force_foreign_without_roots_is_refused_and_drops_nothing() {
    # The machine-wide sentence itself, behind the belt (see `no_server_bin`):
    # this is the one command in this repository that must never be allowed to
    # reach a server from inside a drive, and the belt is what makes typing it
    # here legitimate rather than reckless.
    drive "sweep: --sweep --force-foreign with no --roots is REFUSED" 2 -- \
        env PATH="$(no_server_bin):${PATH}" ./scripts/sweep.sh --sweep --force-foreign
    says "REFUSED: --force-foreign needs --roots <dir>"
    says "Nothing was destroyed"
    # It refused BEFORE it looked, which is the whole property: no scope banner,
    # no verdict — and NOT the could-not-look the belt produces one step later
    # (`pg_catalog could not be read`), which is what a run that got past the
    # refusal says instead, and what this case saw on the baseline tree.
    says_not "the checkout-machinery census"
    says_not "pg_catalog could not be read"
    says_not "DESTROYED"
    # And the decoy this driver made is still there — the assertion the consumer
    # did not get to make.
    holds "sweep: the scratch database survived the refused run" "yes" \
        "$(db_present "$SCRATCH_BASE" && echo yes || echo no)"
}

case_only_does_not_license_force_foreign_without_roots() {
    # NARROWING IS NOT EVIDENCE. `--only` says where to look; it never says who
    # owns what is found there, so it cannot stand in for a root. This one needs
    # no belt: it is aimed at this driver's own scratch identity, so a regression
    # that let it through would destroy this file's decoy and nothing else —
    # which is what the `db_present` assertion below reads.
    drive "sweep: --only does not license --force-foreign without --roots" 2 -- \
        ./scripts/sweep.sh --sweep --force-foreign --only "$SCRATCH_BASE"
    says "REFUSED: --force-foreign needs --roots <dir>"
    says "narrowing is not evidence"
    says_not "DESTROYED"
    holds "sweep: --only did not license the destroy" "yes" \
        "$(db_present "$SCRATCH_BASE" && echo yes || echo no)"
}

case_db_sweep_force_foreign_without_roots_is_refused() {
    # The reaper says the same thing, because it is the same mistake: its mode is
    # every checkout's database on the server, and `--force-foreign` there with
    # no root is the exact command the consumer ran. Belted for the same reason
    # as the first case — the reaper has no `--only` to narrow it with.
    drive "db_sweep: the reaper refuses --force-foreign with no --roots" 2 -- \
        env PATH="$(no_server_bin):${PATH}" \
        ./scripts/db_sweep.sh --all-checkouts --orphans --sweep --force-foreign
    says "REFUSED: --force-foreign needs --roots <dir>"
    says "Nothing was dropped"
    says_not "scope: every derived-shaped name"
    says_not "DROPPING"
    holds "db_sweep: the scratch database survived the refused run" "yes" \
        "$(db_present "$SCRATCH_BASE" && echo yes || echo no)"
}

case_force_foreign_prints_then_acts() {
    # The promise the header makes: every name and its reason BEFORE the
    # consequence, so an operator can stop at the first surprise. Asserted by
    # LINE ORDER, not merely by both lines existing.
    #
    # `--roots` is now REQUIRED beside `--force-foreign` and the scratch
    # root is this drive's own empty one: the evidence named is "I scanned there
    # and found no checkout", which is true, and which leaves the scratch
    # identity FOREIGN exactly as it was before.
    drive "sweep: --force-foreign destroys the scratch machinery" 0 -- \
        ./scripts/sweep.sh --sweep --force-foreign --roots "$SCRATCH_ROOT" \
        --hot-path --only "$SCRATCH_BASE"
    says "--force-foreign given: DESTROYING it on the operator's word"
    says "DESTROYED ${SCRATCH_SCHEDULE}"
    says "DESTROYED ${SCRATCH_EXECUTION} (queue ${SCRATCH_QUEUE})"
    local claim_line consequence_line
    claim_line="$(grep -nF "FOREIGN  ${SCRATCH_SCHEDULE}" "$DRIVE_OUT" | head -1 | cut -d: -f1)"
    consequence_line="$(grep -nF "DESTROYED ${SCRATCH_SCHEDULE}" "$DRIVE_OUT" | head -1 | cut -d: -f1)"
    if [ -n "$claim_line" ] && [ -n "$consequence_line" ] && [ "$claim_line" -lt "$consequence_line" ]; then
        echo "  ok       ${CURRENT} — the name and its reason are printed BEFORE the destroy"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — the FOREIGN claim did not precede the destroy (claim ${claim_line:-none}, destroy ${consequence_line:-none})"
        FAILED=$((FAILED + 1))
    fi
}

case_the_scratch_machinery_is_actually_gone() {
    # The property, not the mechanism: the SERVERS no longer hold them.
    holds "destroy: the scratch schedule is gone from the server" "no" \
        "$(schedule_present "$SCRATCH_SCHEDULE" && echo yes || echo no)"
    holds "destroy: the scratch execution is gone from the open set" "no" \
        "$(execution_present "$SCRATCH_EXECUTION" && echo yes || echo no)"
    holds "destroy: the scratch base database is gone" "no" \
        "$(db_present "$SCRATCH_BASE" && echo yes || echo no)"
    holds "destroy: the scratch test database is gone" "no" \
        "$(db_present "$SCRATCH_TEST_DB" && echo yes || echo no)"
    holds "destroy: the scratch hot-path cache is gone (--hot-path was given)" "no" \
        "$(db_present "$SCRATCH_HP_DB" && echo yes || echo no)"
}

case_a_refused_shape_survives_force_foreign() {
    # The other side of the case above, and the one that keeps it honest: a
    # driver that only proved "it destroys" would still pass if somebody made it
    # destroy everything. This schedule is keyed to a queue with no path digest —
    # `$SCRATCH_UNDERIVED_QUEUE` — so nothing can say whose it is, and REFUSED means
    # never touched however loud the flags.
    lc_temporal schedule create --schedule-id "$SCRATCH_UNDERIVED_SCHEDULE" \
        --interval 8760h --paused \
        --workflow-id "$SCRATCH_UNDERIVED_WORKFLOW" \
        --task-queue "$SCRATCH_UNDERIVED_QUEUE" --type "Lc2ScratchNeverRuns" >/dev/null 2>&1
    drive "sweep: a schedule with no path digest is REFUSED" 0 -- \
        ./scripts/sweep.sh --class schedule --sweep --force-foreign \
        --roots "$SCRATCH_ROOT" --only "djb_lc2scratchnohash"
    says "REFUSED  ${SCRATCH_UNDERIVED_SCHEDULE}"
    says_not "DESTROYED"
    holds "sweep: the undeclared-identity schedule survived --force-foreign" "yes" \
        "$(schedule_present "$SCRATCH_UNDERIVED_SCHEDULE" && echo yes || echo no)"
    lc_temporal schedule delete --schedule-id "$SCRATCH_UNDERIVED_SCHEDULE" >/dev/null 2>&1
}

# --- the other half: a worktree somebody's `worktree list` names is LIVE -----
#
# The consumer's loss had two ingredients and the refusal above is only the
# first. The second: a LIVE builder's database read FOREIGN because its checkout
# was a linked worktree of a clone that no `--roots` had been pointed at. So the
# question this case asks is the one the operator is really asking when they type
# `--roots <dir>`: does the evidence reach a worktree that is NOT under the root,
# and is named only by a rooted clone's own `git worktree list`?
#
# IT IS A KEEP IF IT IS ALREADY TRUE, and it was: `lc_bases_for_repo`
# (`scripts/lifecycle.sh`) derives from `git worktree list --porcelain` run in
# each found clone, so a worktree anywhere on disk is named by the clone that
# owns it, and nothing about the refusal above changed that. What did not exist
# is a case that would notice the day it stopped being true — which, given what
# it cost once, is not a case this file should be without.
ROOTED_CLONE_DECOY=""
case_a_rooted_clones_linked_worktree_database_reads_live() {
    local roots="${WORK}/roots" clone="${WORK}/roots/clone-a" wtb="${WORK}/elsewhere/wt-b"
    local base
    mkdir -p "$roots" "${WORK}/elsewhere"
    # SHARED, NOT A COPY. Measured on this box from a linked
    # worktree: a plain clone of this repository is 6.5 s and `--local` is 5.0 s
    # — `--local` cannot hardlink across the worktree's gitdir here, so it copies
    # the object store either way — while `--shared --no-hardlinks` is 0.8 s.
    # The clone is read-only and lives for one case, so borrowing the parent's
    # objects is exactly what `test_loop_scope.sh:905` already does for the same
    # reason.
    if ! git clone --quiet --shared --no-hardlinks "$(pwd)" "$clone" >"${WORK}/clone.log" 2>&1; then
        echo "  FAILED   rooted clone: could not clone this repository into the scratch root"
        sed 's/^/             | /' "${WORK}/clone.log"
        FAILED=$((FAILED + 1))
        return 0
    fi
    # OUTSIDE the root, deliberately: the walk cannot find it, so only the
    # clone's own worktree list can vouch for it. That is the consumer's shape.
    if ! git -C "$clone" worktree add --quiet -b o2decoy "$wtb" >"${WORK}/wtadd.log" 2>&1; then
        echo "  FAILED   rooted clone: could not add a linked worktree outside the root"
        sed 's/^/             | /' "${WORK}/wtadd.log"
        FAILED=$((FAILED + 1))
        return 0
    fi
    # THE NAME IS DERIVED FROM INSIDE THE WORKTREE, by `scripts/db.sh` — the
    # producer — and then handed to the frame, the consumer. Deriving it with the
    # frame's own function would be the frame agreeing with itself.
    base="$(cd "$wtb" && env -u DATABASE_NAME bash -c '. scripts/db.sh >/dev/null 2>&1 && db_name')"
    if ! db_valid_name "${base:-}"; then
        echo "  FAILED   rooted clone: db.sh derived no name inside the linked worktree ('${base:-}')"
        FAILED=$((FAILED + 1))
        return 0
    fi
    echo "  ok       rooted clone: the linked worktree derives ${base}"
    PASSED=$((PASSED + 1))
    # THE DECOY THIS CASE CREATES, and the only thing it ever aims at.
    db_query 'CREATE DATABASE :"name"' -v name="$base" >/dev/null 2>&1
    ROOTED_CLONE_DECOY="$base"
    holds "rooted clone: the decoy database exists to begin with" "yes" \
        "$(db_present "$base" && echo yes || echo no)"

    # THE CONTROL, and it is a census so it destroys nothing: with no root, this
    # run cannot see the clone, and the honest verdict is FOREIGN.
    drive "rooted clone: with no --roots the worktree's database reads FOREIGN" 0 -- \
        ./scripts/sweep.sh --class checkout-database --only "$base"
    says "FOREIGN  ${base}"

    # THE PROPERTY: pointed at the root, the evidence reaches through the clone's
    # worktree list to a worktree the walk never saw.
    drive "rooted clone: with --roots the same database reads live" 0 -- \
        ./scripts/sweep.sh --class checkout-database --only "$base" --roots "$roots"
    says "live     ${base}"
    says_not "FOREIGN  ${base}"

    # AND THE DESTROY PATH AGREES WITH THE PRINTED LINE — the half that was
    # actually paid for. Narrowed to this case's own decoy, rooted, so the only
    # database in scope is the one this case created.
    drive "rooted clone: --force-foreign spares it because it is live" 0 -- \
        ./scripts/sweep.sh --sweep --force-foreign --roots "$roots" \
        --class checkout-database --only "$base"
    says_not "DESTROYED"
    holds "rooted clone: the live worktree's database is still there afterwards" "yes" \
        "$(db_present "$base" && echo yes || echo no)"

    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$base" >/dev/null 2>&1
    ROOTED_CLONE_DECOY=""
    git -C "$clone" worktree remove --force "$wtb" >/dev/null 2>&1
}

# --- TWO ROOTS, AND BOTH OF THEM DO WORK -------------------------------------
#
# `--roots` is repeatable: `LC_ROOTS` is an array, the flag appends to it, and
# the scope banner prints one `scanned` line per entry. Nothing drove more than
# one, so "the second root is read" rested on the array being an array — which
# is true until somebody replaces the append with an assignment, and a single
# `scanned` line for the last root typed is a transcript nobody re-reads.
#
# THE ASSERTION IS NOT THE TWO PRINTED LINES. A case that only counted banner
# lines would pass over a frame that printed both and scanned one. So the
# evidence lives under the SECOND root and the property is that it reached: a
# database a checkout under root B derives reads `live` only when root B was
# among the roots — and the control, root A alone, reads FOREIGN.
SECOND_ROOT_DECOY=""
case_two_roots_are_both_scanned_and_printed() {
    local roots_a="${WORK}/roots-a" roots_b="${WORK}/roots-b"
    local clone="${WORK}/roots-b/clone-b" base
    mkdir -p "$roots_a" "$roots_b"
    # SHARED, NOT A COPY. Measured on this box from a linked
    # worktree: a plain clone of this repository is 6.5 s and `--local` is 5.0 s
    # — `--local` cannot hardlink across the worktree's gitdir here, so it copies
    # the object store either way — while `--shared --no-hardlinks` is 0.8 s.
    # The clone is read-only and lives for one case, so borrowing the parent's
    # objects is exactly what `test_loop_scope.sh:905` already does for the same
    # reason.
    if ! git clone --quiet --shared --no-hardlinks "$(pwd)" "$clone" >"${WORK}/clone-b.log" 2>&1; then
        echo "  FAILED   two roots: could not clone this repository into the second root"
        sed 's/^/             | /' "${WORK}/clone-b.log"
        FAILED=$((FAILED + 1))
        return 0
    fi
    base="$(cd "$clone" && env -u DATABASE_NAME bash -c '. scripts/db.sh >/dev/null 2>&1 && db_name')"
    if ! db_valid_name "${base:-}"; then
        echo "  FAILED   two roots: db.sh derived no name inside the second root's clone ('${base:-}')"
        FAILED=$((FAILED + 1))
        return 0
    fi
    # THE GUARD THE SCRATCH IDENTITY GETS AT THE TOP OF THIS FILE, applied here
    # too. The clone INHERITS this checkout's branch, so only the path hash
    # separates its derived name from a real one — and this case creates that
    # name and drops it again. A collision would mean dropping somebody's
    # database to prove a banner line, so it is asked rather than assumed.
    if [ "$base" = "$OUR_BASE" ] || lc_owning_checkout "$base" >/dev/null; then
        echo "  FAILED   two roots: ${base} is derived by a checkout this run can see —"
        echo "             refusing to create and drop a name somebody owns (nothing was touched)"
        FAILED=$((FAILED + 1))
        return 0
    fi
    db_query 'CREATE DATABASE :"name"' -v name="$base" >/dev/null 2>&1
    SECOND_ROOT_DECOY="$base"
    holds "two roots: the decoy under root B exists to begin with" "yes" \
        "$(db_present "$base" && echo yes || echo no)"

    # THE CONTROL: root A alone. It is a real directory and legal evidence, and
    # it holds nothing — so the answer is the honest FOREIGN, and the case below
    # cannot pass by the frame being generous.
    drive "two roots: root A alone leaves root B's checkout FOREIGN" 0 -- \
        ./scripts/sweep.sh --class checkout-database --only "$base" --roots "$roots_a"
    says "scanned         ${roots_a}"
    says "FOREIGN  ${base}"

    # BOTH. Two banner lines AND the verdict only the second root can produce.
    drive "two roots: both are scanned, both are printed" 0 -- \
        ./scripts/sweep.sh --class checkout-database --only "$base" \
        --roots "$roots_a" --roots "$roots_b"
    says "scanned         ${roots_a}"
    says "scanned         ${roots_b}"
    says "live     ${base}"
    says_not "FOREIGN  ${base}"

    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$base" >/dev/null 2>&1
    SECOND_ROOT_DECOY=""
}

# --- CRITERION 4: an unrecognized shape is exit 2, naming it ------------------

case_an_unrecognized_shape_is_exit_2() {
    # A PLANTED FAKE, in the shape the design named: derivation-shaped
    # (`djb_zzz_<hash>`), so this repository demonstrably made it — and wearing
    # a suffix no declared class claims. Could-not-judge outranks a pass.
    db_query 'CREATE DATABASE :"name"' -v name="$SCRATCH_FAKE_DB" >/dev/null 2>&1
    drive "census: a derived-shaped name no class claims is exit 2" 2 -- \
        ./scripts/sweep.sh --only "$SCRATCH_FOREIGN_DB"
    says "UNRECOGNIZED database: ${SCRATCH_FAKE_DB}"
    says "Declare the class there"
    says "machinery class N+1 exists and the registry"
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_FAKE_DB" >/dev/null 2>&1
}

case_a_declared_shape_is_not_unrecognized() {
    # The negative that keeps the case above from passing vacuously: the same
    # census, over the same identity prefix, with only DECLARED shapes present,
    # is exit 0 and says nothing about an unrecognized anything.
    db_query 'CREATE DATABASE :"name"' -v name="$SCRATCH_FOREIGN_DB" >/dev/null 2>&1
    drive "census: the same prefix with only declared shapes is exit 0" 0 -- \
        ./scripts/sweep.sh --only "$SCRATCH_FOREIGN_DB"
    says_not "UNRECOGNIZED"
    says "FOREIGN  ${SCRATCH_FOREIGN_DB}"
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_FOREIGN_DB" >/dev/null 2>&1
}

# --- --assert-none: the census as an assertion (the gate's own-tree-census leg reads it) ------

case_assert_none_is_silent_on_an_empty_scope() {
    # The gate leg's green: nothing of this class under this identity. Driven
    # against the scratch identity rather than this checkout's, so the case says
    # the same thing on every machine and cannot pass or fail for a reason
    # belonging to whoever ran it.
    drive "assert-none: an empty scope is exit 0" 0 -- \
        ./scripts/sweep.sh --class schedule --only "$SCRATCH_BASE" --assert-none
    says "census: 0 found"
}

case_assert_none_fails_on_a_populated_scope() {
    # The gate leg's exit 1: `process` lifetime creates no Schedule object ever,
    # so one on this queue is a leak. Exit 1 and not 2 — a finding about the tree,
    # never a broken instrument.
    plant_temporal
    drive "assert-none: a populated scope is exit 1" 1 -- \
        ./scripts/sweep.sh --class schedule --only "$SCRATCH_BASE" --assert-none
    says "instance(s) are in scope and none should be"
    says "$SCRATCH_SCHEDULE"
    says "a finding about"
    lc_temporal schedule delete --schedule-id "$SCRATCH_SCHEDULE" >/dev/null 2>&1
    lc_temporal workflow terminate --workflow-id "$SCRATCH_EXECUTION" \
        --reason "test_sweep: assert-none case teardown" >/dev/null 2>&1
}

case_assert_none_refuses_to_be_a_broom() {
    # A run that destroyed and then reported on what it destroyed could always
    # make its own assertion true.
    drive "assert-none: refused with --sweep" 2 -- \
        ./scripts/sweep.sh --class schedule --only "$SCRATCH_BASE" --assert-none --sweep
    says "--assert-none and --sweep are opposites"
}

# --- --assert-none EXEMPTS THIS CHECKOUT'S OWN WORKING SET (its queue row) ---
#
# THE FALSE RED, found by a consumer on their product and not on this template:
# `--assert-none` failed them for a parked deal's return timer that was open on
# their own queue with two workers polling it. The census had already excused
# that row one line above — `live … (THIS CHECKOUT)`, then `kept — … it is a
# WORKING SET, not a leftover` — and the assertion counted it anyway, because it
# counted every row the census printed.
#
# THE FIXTURE IS A DATABASE AND NOT AN EXECUTION, deliberately, and the reason is
# this file's own declared limit two hundred lines up: a live DescribeTaskQueue
# POLLER needs a worker process, and this driver has no business starting one on
# a shared Temporal server. A live `pg_stat_activity` SESSION on this checkout's
# OWN database costs one short-lived child of this driver, touches no server-side
# durable object and reaches the identical branch of `scripts/sweep.sh` — the
# `live` + mine + not-disposable arm, with positive evidence. So the exemption is
# proved end to end here through the session half, and the poller half is
# DECLARED rather than claimed (the case prints which world it proved).
SESSION_PID=""
SESSION_BACKEND=""
SESSION_PIDFILE=""
hold_a_session_on_our_database() {
    # A real connection to this checkout's own database, held by a child of this
    # driver, so `pg_stat_activity` carries positive evidence the frame can read.
    #
    # IT REPORTS ITS OWN BACKEND PID FIRST, and that is not decoration.
    # `docker compose exec -T` puts a client between this driver and the server:
    # killing the CLIENT closes a socket the server does not look at again until
    # the running statement finishes, so a `kill` alone leaves the session
    # standing for the whole `pg_sleep` and the negative case below skips itself
    # for a reason that is this fixture's fault rather than the machine's
    # (measured: the first run of this case did exactly that). The backend pid
    # makes the drop server-side and immediate.
    SESSION_PIDFILE="${WORK}/held_session.pid"
    : >"$SESSION_PIDFILE"
    db_psql -d "$OUR_BASE" -tAc 'SELECT pg_backend_pid()' -c 'SELECT pg_sleep(25)' \
        >"$SESSION_PIDFILE" 2>/dev/null &
    SESSION_PID=$!
    local tries=0
    while [ "$tries" -lt 40 ]; do
        SESSION_BACKEND="$(tr -dc '0-9' <"$SESSION_PIDFILE" 2>/dev/null)"
        if [ -n "$SESSION_BACKEND" ] &&
            [ "$(lc_sessions_on "$OUR_BASE" 2>/dev/null || echo 0)" != "0" ]; then
            return 0
        fi
        sleep 0.5
        tries=$((tries + 1))
    done
    return 1
}

drop_the_session() {
    [ -n "$SESSION_PID" ] || return 0
    # SERVER-SIDE FIRST, by the backend pid this fixture was told, so the
    # evidence is really gone rather than merely disconnected-from.
    if [ -n "$SESSION_BACKEND" ]; then
        db_query "SELECT pg_terminate_backend(:'pid'::int)" -v pid="$SESSION_BACKEND" -tA \
            >/dev/null 2>&1
    fi
    # Then the client, BY PID and never by name (rung-execution §5; `pkill -f`
    # has killed other agents' gates twice).
    kill "$SESSION_PID" >/dev/null 2>&1
    wait "$SESSION_PID" >/dev/null 2>&1
    SESSION_PID=""
    SESSION_BACKEND=""
    local tries=0
    while [ "$tries" -lt 40 ]; do
        [ "$(lc_sessions_on "$OUR_BASE" 2>/dev/null || echo 1)" = "0" ] && return 0
        sleep 0.5
        tries=$((tries + 1))
    done
    return 1
}

case_assert_none_exempts_this_checkouts_own_working_set_in_use() {
    plant_our_checkout_database
    if ! hold_a_session_on_our_database; then
        drop_the_session
        skipped "assert-none: the owned working set is exempt" \
            "an owned, not-disposable instance WITH positive live-use evidence" \
            "no session on ${OUR_BASE} became visible in pg_stat_activity within 15s"
        return 0
    fi
    proving "assert-none: the owned working set is exempt" \
        "positive evidence = SESSIONS on this checkout's own database"
    drive "assert-none: this checkout's working set, in use, is exempt" 0 -- \
        ./scripts/sweep.sh --class checkout-database --only "$OUR_BASE" --assert-none
    says "(THIS CHECKOUT)"
    says "it is a working set, not a leftover"
    says "exempt from --assert-none — in use right now"
    # The exemption is not merely applied, it is REPORTED — what was exempted,
    # who owns it, which declaration excuses it and what the evidence was.
    says "instance(s) EXEMPT — this checkout's own working set"
    says "session(s) on it"
    says "is declared NOT disposable"
    drop_the_session || true

    # THE OTHER HALF, PROVED WHERE IT EXISTS AND DECLARED WHERE IT DOES NOT.
    # The consumer's own case was POLLERS on their queue, not sessions on their
    # database. This driver will not START a worker on a shared server — but a
    # product running its local build ALREADY HAS ONE, and on that machine the
    # exact scenario is one plant away. So the case forks: where a worker is up,
    # the poller half is proved for real, on the same queue the consumer met it
    # on; where none is, the world is named and skipped.
    if [ "$(our_pollers)" = "0" ]; then
        skipped "assert-none: the same exemption through POLLERS" \
            "an owned open execution exempted because a worker is polling its queue" \
            "no poller on ${OUR_QUEUE}: this driver does not start a worker on the shared Temporal server, and a product running its local build already has one"
        return 0
    fi
    proving "assert-none: the same exemption through POLLERS" \
        "$(our_pollers) poller(s) on ${OUR_QUEUE} — a product running its local build"
    lc_temporal workflow start --workflow-id "$OWN_WORKING_SET_PROBE" --task-queue "$OUR_QUEUE" \
        --type "N466WorkingSetProbeNeverRuns" >/dev/null 2>&1
    holds "exempt: the owned running work is really there" "yes" \
        "$(execution_present "$OWN_WORKING_SET_PROBE" && echo yes || echo no)"
    drive "assert-none: an owned run a worker IS polling is exempt" 0 -- \
        ./scripts/sweep.sh --class open-execution --only "$OUR_BASE" --assert-none
    says "$OWN_WORKING_SET_PROBE"
    says "exempt from --assert-none — in use right now"
    says "poller(s) on ${OUR_QUEUE}"
    lc_temporal workflow terminate --workflow-id "$OWN_WORKING_SET_PROBE" \
        --reason "test_sweep: working-set probe teardown" >/dev/null 2>&1
}

case_assert_none_keeps_its_teeth_on_an_owned_instance_nothing_is_using() {
    # THE NEGATIVE THAT KEEPS THE EXEMPTION FROM BEING A HOLE, on the SAME
    # instance the case above exempted. Ownership alone must never excuse
    # anything: an owned instance with nothing using it is indistinguishable
    # from a leftover, and the whole open-execution leg of the gate rests on
    # that being a finding.
    if [ "$(lc_sessions_on "$OUR_BASE" 2>/dev/null || echo 1)" != "0" ]; then
        skipped "assert-none: teeth on an owned instance nobody is using" \
            "the same owned instance failing the assertion once the evidence is gone" \
            "something else on this machine still holds a session on ${OUR_BASE}"
        return 0
    fi
    drive "assert-none: the same working set, with nothing using it, is exit 1" 1 -- \
        ./scripts/sweep.sh --class checkout-database --only "$OUR_BASE" --assert-none
    says "NOT exempt from --assert-none"
    says "is a strand, not a working set"
    says "instance(s) are in scope and none should be"
}

case_assert_none_still_fails_on_a_stray_run_this_checkout_owns() {
    # THE TEETH ON THE CLASS THAT ACTUALLY MATTERS. This is the population the
    # gate's own-tree census leg reddens on: a RUNNING execution this checkout
    # owns on a queue nothing is polling. It is `live` and it is `mine` and its
    # class is declared NOT disposable — every condition the exemption reads
    # except the one that counts — and it must still be exit 1.
    #
    # IT NEEDS THE STRAND WORLD, so it forks on the worker exactly as the remedy
    # case does: where a worker IS up on this checkout's queue, an open run there
    # is work and no strand can be planted to prove anything about.
    if [ "$(our_pollers)" != "0" ]; then
        skipped "assert-none: teeth on a stray run this checkout owns" \
            "an owned open execution with NO poller failing the assertion" \
            "$(our_pollers) poller(s) on ${OUR_QUEUE}: a run planted there is work, not a strand"
        return 0
    fi
    proving "assert-none: teeth on a stray run this checkout owns" \
        "no worker on ${OUR_QUEUE} — a run planted there really is stranded"
    lc_temporal workflow start --workflow-id "$OWN_STRAY_PROBE" --task-queue "$OUR_QUEUE" \
        --type "N466StrayProbeNeverRuns" >/dev/null 2>&1
    holds "teeth: the stray run is really there to begin with" "yes" \
        "$(execution_present "$OWN_STRAY_PROBE" && echo yes || echo no)"
    drive "assert-none: an owned run nothing is polling is still exit 1" 1 -- \
        ./scripts/sweep.sh --class open-execution --only "$OUR_BASE" --assert-none
    says "$OWN_STRAY_PROBE"
    says "NOT exempt from --assert-none"
    says "instance(s) are in scope and none should be"
    lc_temporal workflow terminate --workflow-id "$OWN_STRAY_PROBE" \
        --reason "test_sweep: teeth probe teardown" >/dev/null 2>&1
}

# --- live is never destroyed, and owning is not a licence ----------------
#
# THE INCIDENT. The owner's first real sweep destroyed 119 items. 117 were
# correct. Two carried the verdict `live … (THIS CHECKOUT)` on the line
# immediately above their own `DESTROYED` line: the main checkout's live
# development database, and one of its RUNNING workflow executions. The verdict
# was computed once and printed correctly; the destroy path then made a second,
# implicit decision by falling out of the `live` arm of a `case`.
#
# The pinned `.env` in that checkout was a coincidence, not the cause, and the
# first case below is what keeps that mistake from being made twice.

case_a_dot_env_pin_does_not_decide_who_owns_what() {
    # `scripts/db.sh` rule 1: a DATABASE_NAME already in the ENVIRONMENT wins.
    # A pin in `.env` is read by django-environ at settings import and by these
    # scripts NEVER — `db_announce_pin_disagreement` only says the two disagree.
    # So the pinned name cannot reach OUR_BASE, cannot make anything
    # `mine`, and cannot have caused the breach. Pinned here because the
    # incident's first hypothesis said otherwise, and a fix aimed at a pin would
    # have left the real defect running.
    local derived resolved
    derived="$(db_name)"
    resolved="$(unset DATABASE_NAME; . scripts/db.sh >/dev/null 2>&1; printf '%s' "$DATABASE_NAME")"
    holds "pin: the scripts resolve the DERIVED name, whatever .env pins" "$derived" "$resolved"
    resolved="$(DATABASE_NAME=djb_exported_wins; export DATABASE_NAME; . scripts/db.sh >/dev/null 2>&1; printf '%s' "$DATABASE_NAME")"
    holds "pin: an EXPORTED name is the one escape, and it wins" "djb_exported_wins" "$resolved"
}

case_an_exported_pin_does_not_move_this_checkouts_identity() {
    # THE OTHER HALF, and it is the frame's rather than the scripts'.
    # The case above proves `scripts/db.sh` resolves the DERIVED name when
    # nothing is exported. This one proves the CENSUS does not change hands when
    # something is: `.github/workflows/ci.yml` exports `DATABASE_NAME=djb_main`,
    # rule 1 makes that win, and `sweep.sh` used to read `OUR_BASE` straight off
    # it. `OUR_BASE` is compared against what `lc_owning_checkout` returns, which
    # is always a derived base — so on any pinned run `mine` was permanently 0,
    # and `live … (THIS CHECKOUT)`, the sentence the live-destroy wall speaks
    # with, could not be printed at all — which is exactly what the two
    # assertions in
    # `case_this_checkouts_running_work_survives_force_foreign` went red on in
    # CI, and on no laptop, where nothing is exported and the two names coincide.
    #
    # The pin planted here is deliberately NOT derivation-shaped, so it is also
    # the shape a runner really pins.
    plant_our_checkout_database
    drive "pin: an exported DATABASE_NAME does not move this checkout's identity" 0 -- \
        env DATABASE_NAME=djb_pinned_by_the_environment \
        ./scripts/sweep.sh --class checkout-database --only "$OUR_BASE"
    says "this checkout   ${OUR_BASE}"
    says "DATABASE_NAME is pinned to djb_pinned_by_the_environment"
    says "(THIS CHECKOUT)"
}

case_owning_is_not_a_licence_to_destroy() {
    # The decision function, driven straight, across the grid that matters. This
    # is the case that would have been red on the day the breach shipped, and it
    # needs no server, so it can name the two classes that were actually lost
    # without this driver having to plant a working database to lose.
    holds "decision: MY checkout-database is NOT destroyable" \
        "none" "$(lc_destroy_decision checkout-database live 1 | cut -d'|' -f1)"
    holds "decision: MY running execution is NOT destroyable" \
        "none" "$(lc_destroy_decision open-execution live 1 | cut -d'|' -f1)"
    holds "decision: another checkout's is never destroyable" \
        "none" "$(lc_destroy_decision test-database live 0 | cut -d'|' -f1)"
    holds "decision: IN USE is never destroyable" \
        "none" "$(lc_destroy_decision test-database "IN USE" 1 | cut -d'|' -f1)"
    holds "decision: REFUSED is never destroyable" \
        "none" "$(lc_destroy_decision test-database REFUSED 1 | cut -d'|' -f1)"
    # And the other half, so the rule cannot pass by refusing everything: the
    # own-tree broom still reaches this checkout's declared-disposable leftovers.
    holds "decision: MY leftover test database IS destroyable by --sweep" \
        "own" "$(lc_destroy_decision test-database live 1 | cut -d'|' -f1)"
    holds "decision: MY leaked schedule IS destroyable by --sweep" \
        "own" "$(lc_destroy_decision schedule live 1 | cut -d'|' -f1)"
    holds "decision: a FOREIGN working database is still --force-foreign's" \
        "foreign" "$(lc_destroy_decision checkout-database FOREIGN 0 | cut -d'|' -f1)"
    # The reason travels with the refusal — a wall that will not say why is a
    # wall somebody removes.
    says_contains "decision: the refusal names the declaration it rests on" \
        "$(lc_destroy_decision checkout-database live 1)" "declared NOT disposable"
}

case_this_checkouts_running_work_survives_force_foreign() {
    # END TO END, against this checkout's REAL identity, because that is the only
    # way to get the verdict `live` AND `mine` at once — the exact pair the
    # breach needed. An open execution is the safe half of the two that were
    # lost: planting one costs nothing and terminating one costs nothing, so a
    # red here damages a probe rather than somebody's database.
    #
    # THE DERIVED IDENTITY, NOT `$DATABASE_NAME`. The pair this case
    # needs is `live` AND `mine`, and both halves are read off the derivation;
    # an exported name is a name to connect with and never a claim of ownership.
    # It also narrows the one destructive call in this file that is not aimed at
    # the scratch identity: the scope is now this checkout's own derived base
    # whatever the environment says, instead of whatever an operator exported.
    local wid="$OWN_LIVE_PROBE"
    lc_temporal workflow start --workflow-id "$wid" --task-queue "$OUR_QUEUE" \
        --type "LiveProbeNeverRuns" >/dev/null 2>&1
    drive "live: my own running execution survives --sweep --force-foreign" 0 -- \
        ./scripts/sweep.sh --sweep --force-foreign --roots "$SCRATCH_ROOT" \
        --class open-execution --only "$OUR_BASE"
    says "(THIS CHECKOUT)"
    says "declared NOT disposable"
    says_not "DESTROYED ${wid}"
    holds "live: the execution is still running afterwards" "yes" \
        "$(execution_present "$wid" && echo yes || echo no)"
    lc_temporal workflow terminate --workflow-id "$wid" \
        --reason "test_sweep: live probe teardown" >/dev/null 2>&1
}

# --- the gate's own-tree census asks BOTH questions ---------------------------
#
# READ AS TEXT, and that is the weaker proof `test_db_pin.sh`,
# `test_loop_tier.sh` and `test_gate_lease.sh` each declare for their own
# wiring, for the same reason: running the real full gate from inside a drive
# that the full gate runs is not a thing a drive may do. What it buys is the
# thing that actually rots — a leg silently narrowed back to one class.
#
# 1,061 stranded executions accumulated while the census leg asked only about
# Schedules and was green every time. The invocation below is the belt; a
# deletion of it would be invisible in every transcript, which is exactly what
# a text assertion is for.
case_the_gate_census_asserts_open_executions_too() {
    local leg
    leg="$(cat scripts/check.sh)"

    says_contains "gate census: it asserts the open-execution class too" \
        "$leg" './scripts/sweep.sh --class open-execution --only "$DATABASE_NAME" --assert-none'
    says_contains "gate census: the schedule assertion is still there beside it" \
        "$leg" './scripts/sweep.sh --class schedule --only "$DATABASE_NAME" --assert-none'

    # Liveness is READ from this registry, not decided in the leg — a worker
    # that is up means the open runs on this queue are work, and a gate that
    # reddened on that is the "reddened by legitimate work" class the leg's own
    # header refuses.
    says_contains "gate census: live pollers are asked about before anything is asserted" \
        "$leg" 'lc_queue_pollers "$OWN_QUEUE"'
    says_contains "gate census: the queue is derived from the identity, never typed" \
        "$leg" 'OWN_QUEUE="djb-${DATABASE_NAME#djb_}"'

    # Both exit arms, because they mean different things and the house
    # semantics rest on the difference.
    says_contains "gate census: could-not-look on the new class is exit 2" \
        "$leg" "THE OPEN-EXECUTION CENSUS COULD NOT BE TAKEN"
    says_contains "gate census: a strand is exit 1, with a remedy" \
        "$leg" "THIS TREE STRANDED A RUNNING TEMPORAL EXECUTION"

    # THE REMEDY IS NOT ASSERTED HERE ANY MORE, and that absence is the whole
    # lesson of this file's own defect. What used to stand here was
    #
    #     says_contains "gate census: the remedy names this instrument" \
    #         "$leg" "--sweep --class open-execution --only"
    #
    # which passed for the entire life of an INOPERATIVE COMMAND. Two screens
    # up, `case_this_checkouts_running_work_survives_force_foreign` proves that
    # this very instrument refuses to destroy this checkout's own open
    # executions — so the leg was printing, as its remedy for a stranded run,
    # the one command this file had already proven could not clear one. A text
    # assertion vouched for it, because a text assertion can only ever say the
    # string is there.
    #
    # The replacement is `case_the_gate_census_remedy_actually_clears_a_strand`
    # below: it reaches the red, lifts the printed line out of the leg, RUNS it,
    # and asserts the strand is gone. Only the negative stays here — the dead
    # line must not come back.
    says_not_contains "gate census: the inoperative broom remedy is gone for good" \
        "$leg" "--sweep --class open-execution --only"
    # ... and the schedule arm, one class up, still names it, because for a
    # SCHEDULE the broom is operative: that class declares itself disposable.
    says_contains "gate census: the schedule arm still names the broom, which works there" \
        "$leg" "--sweep --class schedule --only"

    # A deployment-lifetime checkout is told the property does not apply,
    # exactly as it already is for Schedules (ADR platform-lifecycle-1).
    says_contains "gate census: non-process lifetime asserts nothing about either" \
        "$leg" "Nor does the open-execution property"
}

# --- the remedy is EXECUTED, because a printed command is a promise -----------
#
# THE DEFECT THIS CASE WAS BOUGHT WITH. The leg above printed a remedy for a
# stranded run for a whole cycle, and it did nothing. Run verbatim in the exact
# red situation it was printed for, `./scripts/sweep.sh --sweep --class
# open-execution --only <db>` reported `1 found · 0 destroyed · 1 left alone`
# and exited 0, and the gate stayed red — because `scripts/lifecycle.sh`
# declares this class disposable "no" and `scripts/sweep.sh` terminates open
# executions only on its FOREIGN path. Both of those are CORRECT and neither
# changed; the remedy was the thing that was wrong.
#
# WHY THE OLD ASSERTION COULD NOT SEE IT. It asked whether the leg SAID a
# string. A string is there or it is not; whether typing it achieves anything is
# a different question, and only running it asks that one. So this case runs it.
#
# THE COMMAND IS LIFTED OUT OF THE LEG, NEVER RETYPED HERE. A copy in this file
# would go on passing the day the leg's line changed, which is the same class of
# blindness one level along. The printed line carries no shell variable on
# purpose (see the leg), so the source text between `echo "` and `" >&2` IS what
# an operator reads, and the one thing this case supplies is the placeholder the
# line openly invites.
#
# WHAT IT DOES NOT DO: run the gate leg itself. `scripts/check.sh` is what runs
# this driver, and a drive that ran the full gate would be running itself. The
# leg's assertion is one command — pinned as text by the case above, so it
# cannot drift — and this case runs THAT, on either side of the remedy: red
# before, green after.
GATE_REMEDY_PLACEHOLDER="<an id above>"

gate_strand_remedy() {
    # The first indented command line the strand arm prints, un-echoed. Anchored
    # on the arm's own headline so a second command elsewhere in the file cannot
    # be picked up by accident.
    awk '
        /THIS TREE STRANDED A RUNNING TEMPORAL EXECUTION/ { seen = 1 }
        seen && /^ *echo "     / {
            line = $0
            sub(/^ *echo "/, "", line)
            sub(/" >&2$/, "", line)
            sub(/^ +/, "", line)
            print line
            exit
        }
    ' scripts/check.sh
}

# THE PREMISE THIS CASE CARRIED, AND THE FORK THAT REPLACES IT (its queue row).
#
# It planted a run on `$OUR_QUEUE` and asserted that the gate leg's own
# assertion went RED on it and re-GREENED after the remedy. Both halves rest on
# ONE unwritten premise: that nothing polls this checkout's queue. That is true
# on this template, which runs no worker, and FALSE on a product running its
# local build — where a worker is up, an open run on that queue is WORK rather
# than a strand, the census says so, the gate's own leg says so before it
# asserts anything, and `--assert-none` now says so too by exempting this
# checkout's working set (its queue row). On that machine the case would either
# plant a workflow type a live worker cannot run, or fail its re-green on the
# product's own legitimate open runs.
#
# SO IT ASKS WHICH WORLD IT IS IN, once, and proves what that world can prove:
#
#   NO POLLER  — the strand world. Exactly the case as it always was, end to
#                end, on `$OUR_BASE`: `live` AND `mine`, which is the pair the
#                remedy has to work against.
#   A POLLER   — the gate-leg's own scope cannot hold a strand at all, so that
#                world is SKIPPED and PRINTED, and the remedy is proved instead
#                on the pollerless sibling this file already owns. What survives
#                is the thing the case was bought for: the printed line is RUN
#                VERBATIM and the run it names is really gone afterwards. What
#                is declared lost is the `live`-and-`mine` pair — on the sibling
#                the verdict is FOREIGN — and the case says so rather than
#                letting a green stand for a property it did not reach.
case_the_gate_census_remedy_actually_clears_a_strand() {
    # THE RED. This checkout's own identity, because that is the only way to be
    # `live` AND `mine` at once — the pair the remedy has to work against. The
    # id is prefixed so it is attributable to this driver on a shared server.
    local wid="$OWN_REMEDY_STRAND" scope="$OUR_BASE" queue="$OUR_QUEUE"
    local remedy remedy_rc
    if [ "$(our_pollers)" != "0" ]; then
        skipped "remedy: the strand world on this checkout's own queue" \
            "the gate leg's own scope (live AND mine) going red on a strand and re-greening" \
            "$(our_pollers) poller(s) on ${OUR_QUEUE}: an open run there is WORK, not a strand — planting one would also hand a live worker a workflow type it does not know"
        wid="$SCRATCH_STRAND"
        scope="$SCRATCH_BASE"
        queue="$SCRATCH_QUEUE"
        require_dead_scratch_queue || return 0
        proving "remedy: the printed remedy really clears a run" \
            "the pollerless sibling ${SCRATCH_QUEUE} — FOREIGN, not live-and-mine"
    else
        proving "remedy: the printed remedy really clears a strand" \
            "this checkout's own queue ${OUR_QUEUE}, which nothing is polling — live AND mine"
    fi
    lc_temporal workflow start --workflow-id "$wid" --task-queue "$queue" \
        --type "GateStrandProbeNeverRuns" >/dev/null 2>&1
    holds "remedy: the strand is really there to begin with" "yes" \
        "$(execution_present "$wid" && echo yes || echo no)"
    drive "remedy: the leg's own assertion is RED on it" 1 -- \
        ./scripts/sweep.sh --class open-execution --only "$scope" --assert-none
    says "$wid"

    remedy="$(gate_strand_remedy)"
    holds "remedy: the leg prints a command at all" "yes" \
        "$([ -n "$remedy" ] && echo yes || echo no)"
    says_contains "remedy: it is the destroy verb the class declares, not the broom" \
        "$remedy" "workflow terminate"

    # THE ONE SUBSTITUTION THE PRINTED LINE INVITES, and nothing else is done to
    # it: no rewriting, no adding a flag, no second command. If what the operator
    # reads does not work, this goes red.
    if [ -n "$remedy" ]; then
        remedy="${remedy//$GATE_REMEDY_PLACEHOLDER/$wid}"
        says_not_contains "remedy: nothing unsubstituted is left in it" \
            "$remedy" "<"
        echo "  ...      running the printed remedy verbatim: ${remedy}"
        eval "$remedy" >"${WORK}/remedy.log" 2>&1
        remedy_rc=$?
        holds "remedy: it exits 0" "0" "$remedy_rc"
        [ "$remedy_rc" -eq 0 ] || sed 's/^/             | /' "${WORK}/remedy.log"
    fi

    # THE GREEN. Visibility is the store the census reads and it is not
    # contractually synchronous with the terminate, so the strand is given a
    # bounded moment to disappear rather than one instant — a flake here would
    # teach people to re-run this drive, which is worse than a slow case.
    local tries=0
    while [ "$tries" -lt 15 ] && execution_present "$wid"; do
        sleep 1
        tries=$((tries + 1))
    done
    holds "remedy: the strand is GONE after it" "no" \
        "$(execution_present "$wid" && echo yes || echo no)"
    drive "remedy: the leg's own assertion RE-GREENS" 0 -- \
        ./scripts/sweep.sh --class open-execution --only "$scope" --assert-none
}

# --- CRITERION 5: the Redis answer is written down ----------------------------

case_the_redis_answer_is_recorded() {
    # Criterion 5 is answered in prose, and prose that lives nowhere is an answer
    # that evaporates. This asserts the exemption and its REASON are in the
    # registry file, beside the classes it declined to join.
    local hits
    hits="$(grep -c "REDIS: DECLARED EXEMPT" scripts/lifecycle.sh)"
    holds "redis: the exemption is declared in the registry" "1" "$hits"
    hits="$(grep -c "N-ROW CANDIDATE" scripts/lifecycle.sh)"
    holds "redis: the shared-un-prefixed-cache finding is booked, not absorbed" "1" "$hits"
}

# --- CRITERION 6: the clocks, and the graveyard they describe ----------
#
# The four verdicts say WHOSE a thing is. These cases are about the other half —
# what it is DOING — because that is what a real finding once was: fifteen schedules that had
# been reading FOREIGN correctly for days while nothing said they were still
# firing into queues with no pollers.
#
# THE PARSER IS DRIVEN WITH FIXTURES AND NO SERVER. `scripts/lifecycle_temporal.py`
# takes a document on stdin, so its whole contract can be proven against JSON
# this file writes — including the shapes a real server produces rarely and at
# the worst moment (a stamp it cannot read, a document that is not there). The
# REAL namespace stays read-only to this driver: the only Temporal objects it
# creates or deletes are its own scratch ones.

TEMPORAL_PY="scripts/lifecycle_temporal.py"
# THE CHECKOUT'S OWN INTERPRETER, for every PYTHON FILE THIS REPOSITORY SHIPS
# that this drive runs. `python3` off PATH is some other environment's: on a
# verifier box it is the system 3.9, where `zip(…, strict=True)` — which these
# files use — is `TypeError: zip() takes no keyword arguments`, and the drive
# would report that as a finding about the file it was driving. Inline
# `python3 -c` and heredoc programs below stay as they are: they are stdlib on
# any Python 3, and their own `command -v python3` guard covers their absence.
DRIVE_PY="$PWD/.venv/bin/python"
[ -x "$DRIVE_PY" ] ||
    cannot_look "this checkout has no .venv/bin/python, and the python files this drive
   runs are written at the version that venv holds. Run ./scripts/setup.sh first"


# A stamp `<n>` seconds in the past, written the way Temporal writes one —
# trailing `Z`, NINE fractional digits — which is exactly the shape
# `datetime.fromisoformat` will not read as it finds it. A negative `<n>` is a
# stamp in the future. This is a fixture GENERATOR, not a second parser: it
# formats, it never reads.
#
# `timezone.utc`, NEVER `datetime.UTC`, and the box is the argument. The comment
# above says the inline programs are "stdlib on any Python 3" and this one was
# not: `datetime.UTC` is the 3.11 alias, and the `python3` first on PATH on a
# verifier box is Amazon Linux 2023's system 3.9, where the import is an
# `ImportError` on stderr and an empty stamp on stdout. Both clock assertions
# then read `unknown` and named the PARSER — a drive reporting its own fixture
# generator as a finding about the file it was driving. `timezone.utc` has been
# there since 3.2, which is what "any Python 3" has to mean for a program that
# deliberately does not use the checkout's interpreter.
stamp_ago() {
    python3 -c '
import sys
from datetime import datetime, timedelta, timezone

when = datetime.now(timezone.utc) - timedelta(seconds=int(sys.argv[1]))
print(when.strftime("%Y-%m-%dT%H:%M:%S.123456789Z"))
' "$1"
}

case_the_parser_reads_both_of_temporals_time_formats() {
    local fixture row last nxt status
    fixture="${WORK}/schedules.json"
    cat >"$fixture" <<JSON
[{"scheduleId": "probe:djb-clock_00000000",
  "info": {"workflowType": {"name": "ProbeWorkflow"},
           "recentActions": [{"actualTime": "$(stamp_ago 7230)",
                              "startWorkflowStatus": "WORKFLOW_EXECUTION_STATUS_RUNNING"}],
           "futureActionTimes": ["$(stamp_ago -5430)"]}}]
JSON
    row="$("$DRIVE_PY" "$TEMPORAL_PY" schedules <"$fixture")"
    last="$(printf '%s' "$row" | cut -f2)"
    nxt="$(printf '%s' "$row" | cut -f3)"
    status="$(printf '%s' "$row" | cut -f5)"
    # Nine fractional digits and a `Z`, both directions across now.
    holds "clock: a nine-digit fractional stamp in the past is dated" "2h0m" "$(lc_duration "$last")"
    holds "clock: a stamp in the future is dated forward" "1h30m" "$(lc_duration "$nxt")"
    # The column that explains a QUIET graveyard: the last action never finished,
    # so the schedule is not firing — and will resume the moment anything drains
    # the queue it is blocked on.
    holds "clock: the last action's outcome is carried" "RUNNING" "$status"
}

case_a_stamp_the_parser_cannot_read_is_unknown_and_never_zero() {
    local fixture row age
    fixture="${WORK}/badstamp.json"
    cat >"$fixture" <<'JSON'
[{"execution": {"workflowId": "probe:unreadable"},
  "taskQueue": "djb-clock_00000000",
  "type": {"name": "ProbeWorkflow"},
  "startTime": "the day before yesterday"}]
JSON
    row="$("$DRIVE_PY" "$TEMPORAL_PY" executions <"$fixture")"
    age="$(printf '%s' "$row" | cut -f3)"
    holds "clock: an unreadable stamp is the -1 sentinel" "-1" "$age"
    # THE WHOLE POINT OF THE SENTINEL. `0s` would read as "it started this
    # second", which is a fact this run does not have.
    holds "clock: -1 prints as 'unknown', never as a duration" "unknown" "$(lc_duration "$age")"
    holds "clock: a real zero still prints as a duration" "0s" "$(lc_duration 0)"
}

case_a_backlog_is_evidence_of_harm_and_never_of_liveness() {
    local fixture stats pollers backlog age
    fixture="${WORK}/queue.json"
    # A queue with a deep, old backlog and NOBODY POLLING — the graveyard shape.
    cat >"$fixture" <<'JSON'
{"pollers": null,
 "stats": [{"taskQueueType": "workflow", "approximateBacklogCount": 3,
            "approximateBacklogAge": "7h52m3s"},
           {"taskQueueType": "activity", "approximateBacklogCount": 1,
            "approximateBacklogAge": "12m"}]}
JSON
    stats="$("$DRIVE_PY" "$TEMPORAL_PY" queue <"$fixture")"
    pollers="${stats%%|*}"
    backlog="${stats#*|}"
    age="${backlog#*|}"
    backlog="${backlog%%|*}"
    holds "backlog: the depth is summed across the task-queue types" "4" "$backlog"
    holds "backlog: a Go duration is read, and the OLDEST one wins" "7h52m" "$(lc_duration "$age")"
    holds "backlog: pollers are counted separately and there are none" "0" "$pollers"
    # AND THE PROPERTY THAT MATTERS: four tasks piling up is not four workers.
    # The verdict reads the poller field and nothing else, so a queue nobody
    # polls stays FOREIGN however busy its backlog looks.
    holds "backlog: a piled-up queue is not IN USE" "FOREIGN" \
        "$(lc_verdict "$SCRATCH_BASE" "$pollers")"
}

case_the_parser_refuses_what_it_cannot_read() {
    # A server that said nothing is not a server that said "there is nothing",
    # and the difference has to reach the caller as a status.
    drive "parser: empty stdin is exit 2, not an empty population" 2 -- \
        bash -c "printf '' | ${DRIVE_PY} ${TEMPORAL_PY} schedules"
    drive "parser: a document that is not JSON is exit 2" 2 -- \
        bash -c "printf 'Error: connection refused' | ${DRIVE_PY} ${TEMPORAL_PY} executions"
    drive "parser: an unknown mode is exit 2, never a silent different read" 2 -- \
        bash -c "printf '[]' | ${DRIVE_PY} ${TEMPORAL_PY} pollers"
    says "takes exactly one of"
}

case_a_presence_probe_survives_a_long_scan() {
    # THE REGRESSION, pinned at the mechanism rather than at the symptom.
    #
    # The probes above answer "is this instance still there", and two of this
    # file's most load-bearing assertions — the FOREIGN execution surviving
    # `--sweep`, and the live-destroy wall's own run surviving `--force-foreign`
    # — are only ever
    # as true as the probe is. When the probe was `cut | grep -q` under
    # `pipefail` it answered ABSENT for something present, as soon as the scan
    # got long enough that `grep` exited before `cut` finished writing. Both
    # assertions went red on a tree where nothing about sweeping had changed.
    #
    # So this case drives the PROPERTY the probes need and the server's current
    # size cannot be trusted to provide: a match at the HEAD of a long stream
    # must still be found. It needs no server, so it cannot degrade to
    # could-not-look, and it fails on the old shape and passes on the new one.
    CURRENT=case_a_presence_probe_survives_a_long_scan
    DRIVE_OUT=""
    local rc

    rc=0
    {
        printf 'djb-q\tHEAD-OF-LIST\t1\tT\n'
        awk 'BEGIN { for (i = 1; i <= 20000; i++) print "djb-q\tfiller" i "\t1\tT" }'
    } | awk -F'\t' -v want="HEAD-OF-LIST" '$2 == want { found = 1 } END { exit !found }' || rc=$?
    if [ "$rc" -eq 0 ]; then
        echo "  ok       ${CURRENT} — a head-of-list match survives a 20 000-line scan"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — the matcher returned ${rc} for a row that IS there (SIGPIPE under pipefail?)"
        FAILED=$((FAILED + 1))
    fi

    # And the other direction, so a matcher that always said yes would be caught.
    rc=0
    {
        printf 'djb-q\tHEAD-OF-LIST\t1\tT\n'
        awk 'BEGIN { for (i = 1; i <= 200; i++) print "djb-q\tfiller" i "\t1\tT" }'
    } | awk -F'\t' -v want="NOT-IN-THE-LIST" '$2 == want { found = 1 } END { exit !found }' || rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "  ok       ${CURRENT} — a name that is not in the scan is still absent"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — the matcher found a name that is not there"
        FAILED=$((FAILED + 1))
    fi

    # The readers must not go back to short-circuiting. Read as TEXT, because
    # the failure is invisible at every scan size but the large one — and read
    # over the WHOLE instrument tree, not just this file's two probes. See
    # `quiet_tail_sites` above for the shape, the measurement and the
    # allow-list.
    quiet_tail_guard
}

# --- the pipeline-tail quiet-consumer sweep -----------------------------------
#
# THE DEFECT, GENERALISED FROM THIS FILE'S OWN. The two presence probes above
# were the first member found; the sweep below is the population. A reader that
# stops at its first match, at the tail of a pipeline, in a file under
# `pipefail`, leaves the producer writing into a closed pipe. The producer takes
# SIGPIPE and dies 141, `pipefail` hands the pipeline 141, and 141 is not zero —
# so the probe reports FALSE for something that is TRUE.
#
# A STEEP PROBABILITY STEP ON THIS BOX, NOT A WALL — and the numbers are here
# because the sentence that used to stand in their place claimed more than had
# been measured (comment-accuracy finding, 2026-09-05). Measured at rung time
# rather than reasoned
# (BSD grep 2.6.0-FreeBSD, macOS, this box):
#
#     producer wrote  32,906 bytes   ->   0/50 runs read the wrong answer
#     producer wrote  83,906 bytes   ->  50/50 runs read the wrong answer
#
# and re-measured at greater n by the GQ-1 verifier (V-GQ1), on the same box,
# which is what turned the wall into a step:
#
#     above the 64 KiB buffer         -> 189/200 runs read the wrong answer
#     above it, all on ONE line       ->   0/200 runs read the wrong answer
#     below the buffer                ->   1/500 runs read the wrong answer
#
# — the wrong answers reporting the pipeline's stages as `PIPESTATUS 141 0`.
# The step is the 64 KiB pipe buffer: under it the producer's whole write
# usually fits and it never blocks, so it usually never sees the closed pipe;
# over it the producer usually blocks mid-write and usually loses. Note the
# 1/500 BELOW the buffer — macOS pipes start at 16 KiB and grow, so "under the
# buffer" is not a guarantee, and neither end of the step is a wall. What the
# numbers do support is the conversion decision, unchanged: at 189/200 the
# defect is not a flake somebody will eventually see, it is the normal answer,
# on a size nobody checks when they add a line to the producer.
#
# TWO CONDITIONS, NOT ONE — re-measured when this branch folded main, and the
# second one is the argument for sweeping on SHAPE instead of measuring per
# site. The reader is line-oriented: it cannot decide a line it does not yet
# hold, so a producer that writes past the buffer WITHOUT a newline in it is
# read to EOF and never strangled at all. Same bytes, same box, same reader:
#
#     84,016 bytes on one line       ->   0/50 runs read the wrong answer
#     84,016 bytes over 2,101 lines  ->  50/50 runs read the wrong answer
#
# — the second one reporting the pipeline's stages as "141 0" every time. So
# the member is "over the buffer AND the match completes a line early", and
# NEITHER half is visible where the call is written: a producer grows past
# 64 KiB when somebody adds a field, and it grows a newline the day somebody
# pretty-prints it. A per-site measurement answers for the producer as it
# stands this morning; the shape answers for the producer as it will be.
#
# WHAT IS AND IS NOT THE SHAPE. The member is a quiet reader fed BY A PIPE with
# no file operand. A quiet reader given a FILE reads that file directly, has no
# producer to strangle, and stays — which is why the `||`-list forms in
# `test_serve_port.sh` are silent here rather than allow-listed. The fix form is
# uniform: let the reader run to EOF and redirect its output, flags preserved.
#
# THE ALLOW-LIST IS A CENSUS OF SITES, NOT OF FILES (guard-reach finding,
# 2026-09-05). Every entry carries
# the reason it is still here, and an entry with no reason is a bug in this
# guard, not a pass. It used to be keyed on (path-suffix, needle-in-line-or-next)
# — which admitted one FILE, not one site: a new member added to a censused file
# whose text happened to contain the needle was admitted silently, and the GQ-1
# verifier proved it by planting a second `PARTITION_KEY_RE` pipeline in
# `gate_ledger.sh` and watching the guard stay green. The key is now EQUALITY on
# the site's own normalised text, so a census row admits the one pipeline it
# quotes and nothing else. The canary below plants exactly that second pipeline
# and requires it to be reported.
#
# ROW FORMAT: `path|site-text|reason`, one row per site.
#   * `path` is read from the LEFT (up to the first `|`) and `reason` from the
#     RIGHT (after the last `|`), and the site text is everything between —
#     because the site text is a PIPELINE and therefore always contains `|`.
#     That is why the free-form field cannot be last, and why a reason may not
#     contain a `|`: one that did would silently annex part of the text, and the
#     row would then stop matching its own site and the guard would go red. It
#     is self-detecting, which is the property this format was chosen for.
#   * `site-text` is what `quiet_tail_sites` prints after the `path:line:`
#     prefix, put through `quiet_tail_normalise` (`tr -s '[:space:]' ' '`, then
#     the leading and trailing space trimmed so a row can be pasted without an
#     invisible blank). Re-derive a row rather than typing it:
#
#       quiet_tail_files | quiet_tail_sites
#
# WHAT THE FOUR ROWS ARE, and the one that is debt rather than a decision. Rows
# 1-3 are not the shape at all — a case label and a report sentence that QUOTE
# the shape, and the deliberate reproduction of the defect inside the drive
# whose job is to prove it. Row 4 IS a real member, unconverted, and it is here
# because it sits outside TIDY-1a's territory (the brief named `test_sweep.sh`,
# `pm_fold.sh`, `test_pm_fold.sh` and `instruments.md`), not because anybody
# decided it should stay. A builder does not edit outside its territory to make
# its own guard green; it says so where the next reader will find it, and the
# reason field is that saying-so.
#
# A FIFTH ROW STOOD HERE UNTIL IT COVERED NOTHING. It quoted a
# `sed … | grep -q` in `test_loop_scope.sh` whose needle was an `apps/` path;
# the site itself was converted to an `awk` that reads to EOF in some later
# rung, and this row went on being an allow-list for a pipeline that no longer
# exists. It is deleted for the reason the two GQ-1 rows above it were deleted
# — a census row covering zero live sites is an allow-list that has stopped
# meaning anything — and deleting it also takes the only `apps/` path this
# drive spells out of the file, so its `# drives:` declaration no longer has to
# claim the core app for a quotation. The census key is site text, so the
# deletion is provable: run `quiet_tail_files | quiet_tail_sites` and no hit
# names that file.
#
# The two rows that stood here until 2026-09-07 — `check.sh|^#!.*sh$` and
# `gate_ledger.sh|PARTITION_KEY_RE` — are GONE, and not because the sites were
# excused: both were converted to `>/dev/null` in the same GQ-1 rung that wrote
# the census, and today the only text matching those needles in either file sits
# in whole-line comments this scanner drops. Two census rows covering zero live
# sites is an allow-list that has stopped meaning anything, and under equality
# keying it is provable rather than arguable.

# quiet_tail_files — the population, DERIVED rather than rooted (guard-root
# finding, 2026-09-05). Every
# TRACKED shell file in the repository: the `.sh` extension, membership of a
# `githooks/` directory, or an `sh` shebang on the first line. That is exactly
# the derivation `scripts/check.sh`'s `mktemp_selfline_files` already makes for
# its own sweep, widened from that function's `-- scripts deploy` pathspec to
# the whole index, because `frontend/scripts/pin_client.sh` is a tracked shell
# file too and a root of `scripts` never sees it.
#
# TWO DERIVATIONS STAND FOR NOW, and that is a decision rather than an oversight:
# `scripts/tests/drive_preamble.sh` has no shared shell-file enumerator to call,
# and adding one is an edit to a file every drive in this directory sources —
# which is a rung of its own, not a line in this one. Named here so the next
# reader inherits the choice instead of rediscovering the duplication.
quiet_tail_files() {
    local f
    git ls-files 2>/dev/null | while IFS= read -r f; do
        [ -f "$f" ] || continue
        case "$f" in
        *.sh | */githooks/*) printf '%s\n' "$f" ;;
        # `grep PATTERN >/dev/null` and never a quiet reader at a pipeline tail:
        # this function is inside the population its own guard sweeps, and a
        # sweep that could not survive its own rule would be a rule nobody keeps.
        *) head -n 1 "$f" 2>/dev/null | grep -E '^#!.*sh$|^#!.*sh[[:space:]]' >/dev/null && printf '%s\n' "$f" ;;
        esac
    done
}

# quiet_tail_sites — every pipeline-tail quiet-consumer site in the files named
# on STDIN, one `path:line:text` per hit. It takes the file list rather than a
# root, so the population is derived once, by `quiet_tail_files`, and the
# canary can hand it a scratch tree instead. Whole-line comments are dropped
# before matching (the house rule is that prose does not spell a censused
# marker, so prose that does is reworded rather than exempted here);
# continuation lines are joined to the pipe that feeds them, so a reader on its
# own line is seen and is reported at the line where its pipeline STARTS.
quiet_tail_sites() {
    tr '\n' '\0' |
        xargs -0 awk '
            FNR == 1 { buf = ""; bufline = 0 }
            /^[[:space:]]*#/ { next }
            {
                line = $0
                if (buf == "") { bufline = FNR; buf = line }
                else { sub(/^[[:space:]]+/, " ", line); buf = buf line }
                if (buf ~ /(\||\\)[[:space:]]*$/) next
                print FILENAME ":" bufline ":" buf
                buf = ""
            }
            END { if (buf != "") print FILENAME ":" bufline ":" buf }
        ' |
        grep -E '(^|[^|])\|[[:space:]]*grep[[:space:]]+(-[A-Za-z]*q[A-Za-z]*|--quiet)'
}

# quiet_tail_normalise <text> — the census key. One run of whitespace becomes one
# space; the leading and trailing space go. Nothing else is touched: quoting,
# flags and operands are the identity of the site.
quiet_tail_normalise() {
    local t
    t="$(printf '%s' "$1" | tr -s '[:space:]' ' ')"
    t="${t# }"
    t="${t% }"
    printf '%s' "$t"
}

# quiet_tail_census — one line per SITE that stays, and why. Format
# `path|site-text|reason`; see the block above for how the three fields are split
# and why the reason is last. It is a FUNCTION printing a quoted heredoc, not a
# variable holding one, for two reasons: the heredoc carries a site's own quotes,
# `$` and backticks verbatim rather than escaped into unreadability, and
# `x=$(cat <<'EOF' ... )` mis-parses an unbalanced quote inside the body on bash
# 3.2 — which is what `#!/usr/bin/env bash` resolves to on this box, so it is the
# shell this drive actually runs under.
#
# THE ROWS ARE ASSEMBLED, NEVER SPELLED — the same rule the canary plants below
# obey, and for a sharper reason: a census row QUOTES the very shape the scanner
# hunts, this file is inside the population it sweeps, and a row written out
# longhand therefore becomes a site of its own. Five rows spelled longhand made
# five new unallowed sites on the first run of this block, which would then need
# five rows, which would be five more sites. So the reader's quiet flag is
# written `@Q@` in the heredoc and substituted at run time: what is on the page
# is not the shape, and what `quiet_tail_unallowed` compares against is.
quiet_tail_census() {
    cat <<'CENSUS' | sed "s/@Q@/-$(printf 'q')/g"
scripts/tests/test_loop_ledger.sh|CURRENT="no '| grep @Q@' at a pipeline tail in the selection machinery"|NOT THE SHAPE: a case label that quotes the shape it is about. The scanner reads text and cannot tell a pipeline from a sentence describing one; the equality key means this row admits this one label and no other line of that file.
scripts/tests/test_loop_ledger.sh|} | grep @Q@ MATCH|NOT DEBT, THE PROOF: the deliberate reproduction of this very defect, inside the drive whose job is to show it returns the wrong answer under pipefail. Converting it would delete the evidence the conversion rests on.
scripts/tests/test_loop_ledger.sh|ok "reproduced: '| grep @Q@' under pipefail returned ${red} on a MATCH"|NOT THE SHAPE: the sentence that reports the reproduction above. Prose, in a string, quoting the marker.
scripts/tests/test_secrets_baseline_guard.sh|if grep -n 'detect-secrets scan --baseline' "$f" | grep @Q@vE '^[0-9]+:[[:space:]]*(#|echo |printf )'; then|A REAL MEMBER, UNCONVERTED, out of TIDY-1a territory and flagged to the PM as a follow-up. Producer is one file's matching lines, short today; the guard it sits in is the one that catches a baseline being silently truncated, so a false ABSENT here is expensive.
CENSUS
}

# quiet_tail_unallowed <census-file> — the sites (`quiet_tail_sites` output on
# STDIN) that no census row covers. A row covers a site when the path
# suffix-matches AND the normalised site text is EQUAL to the row's, which is
# the whole of the guard-reach finding: one site, not one file. The census
# arrives as a FILE rather
# than a global so the canary below can hand it a census of its own making —
# a canary reading found state proves whatever the tree did last week.
quiet_tail_unallowed() {
    local census=$1 site path line text allowed entry rest ent_path ent_text
    while IFS= read -r site; do
        [ -n "$site" ] || continue
        path=${site%%:*}
        rest=${site#*:}
        line=${rest%%:*}
        text="$(quiet_tail_normalise "${rest#*:}")"
        allowed=no
        while IFS= read -r entry; do
            [ -n "$entry" ] || continue
            ent_path=${entry%%|*}
            rest=${entry#*|}
            ent_text=${rest%|*}
            case "$path" in
            *"$ent_path") ;;
            *) continue ;;
            esac
            if [ "$text" = "$ent_text" ]; then
                allowed=yes
                break
            fi
        done <"$census"
        [ "$allowed" = yes ] || printf '%s\n' "${path}:${line}"
    done
}

quiet_tail_guard() {
    local scanned files unallowed canary_dir canary_hits negative_hits reasoned rows census

    # FLOOR FIRST. A scan that reached no files is could-not-look wearing a
    # green, and it is the only way this guard can lie.
    #
    # THE FLOOR IS RE-DERIVED, NOT REMEMBERED. The population is now
    # every tracked shell file rather than everything under `scripts`, so the
    # old floor of 30 — set against a root of 56 — would have gone on passing
    # while two thirds of the tree fell out. Derived today with
    #
    #     git ls-files | grep -E '\.sh$|/githooks/' | wc -l
    #
    # which reads 71: scripts/ 56 (31 + 22 in tests/ + 3 githooks), deploy/ 14
    # (7 + 6 in tests/ + 1 under observability/alerts), frontend/scripts/ 1, and
    # 0 files reached only by the shebang sniff. The floor is 60 — eleven files
    # of slack, which is room for a tidy-up round to retire a handful of drives
    # without turning a real deletion into a false could-not-look, and nowhere
    # near enough room to lose a whole directory unnoticed.
    census="${WORK}/quiet-tail-census"
    quiet_tail_census >"$census"
    files="$(quiet_tail_files)"
    scanned="$(printf '%s\n' "$files" | grep -c .)"
    if [ "$scanned" -lt 60 ]; then
        echo "  FAILED   ${CURRENT} — the sweep reached ${scanned} tracked shell files; the population cannot have shrunk below 60 (71 today), so this scan looked at a fraction of the tree and proves nothing"
        FAILED=$((FAILED + 1))
        return
    fi

    unallowed="$(printf '%s\n' "$files" | quiet_tail_sites | quiet_tail_unallowed "$census")"
    if [ -n "$unallowed" ]; then
        echo "  FAILED   ${CURRENT} — a reader short-circuits its own producer at the tail of a pipeline under pipefail; over 64 KiB that reports the wrong answer EVERY run. Let the reader run to EOF and redirect its output instead (flags preserved), or add a census row with its reason:"
        printf '%s\n' "$unallowed" | sed 's/^/             /'
        FAILED=$((FAILED + 1))
    else
        echo "  ok       ${CURRENT} — ${scanned} tracked shell files swept (every root, derived — not just scripts/): no pipeline-tail reader short-circuits its producer outside the census"
        PASSED=$((PASSED + 1))
    fi

    # THE CENSUS SAYS WHY, or it is an off switch. Every row must carry a reason
    # field, and a row whose reason is empty is a failure of this guard. Counted
    # against the row TOTAL rather than a remembered constant, so a row added
    # without a reason is caught by the same arithmetic that catches a row
    # deleted — and the count itself is printed, because a census that shrinks
    # silently is the failure this whole block is about.
    reasoned=0
    rows=0
    while IFS= read -r entry; do
        [ -n "$entry" ] || continue
        rows=$((rows + 1))
        # `path|site-text|reason`: the reason is what follows the LAST `|`, and
        # the site text always contains at least one of its own (it is a
        # pipeline). A row with fewer than three fields therefore has a reason
        # equal to the whole row, which is how a missing reason is detected.
        case "${entry##*|}" in
        "" | "$entry") ;;
        *) reasoned=$((reasoned + 1)) ;;
        esac
    done <"$census"
    if [ "$rows" -gt 0 ] && [ "$reasoned" -eq "$rows" ]; then
        echo "  ok       ${CURRENT} — all ${rows} census rows carry their reason (a valve with no reason is an off switch)"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — ${reasoned} of ${rows} census rows carry a reason; a row without one is an off switch wearing an allow-list"
        FAILED=$((FAILED + 1))
    fi

    # THE CANARY, planted through the real scanner in a scratch tree of its own
    # making — never against found state. If this does not fire, the guard above
    # is decorative and its green means nothing.
    canary_dir="${WORK}/quiet-tail-canary"
    mkdir -p "${canary_dir}/scripts/tests"
    # THE PLANTS ARE ASSEMBLED, NEVER SPELLED. A guard that counts a shape
    # wherever it appears counts it in the line that plants it too, and a canary
    # that trips its own scanner from this file would make the sweep above
    # permanently red for a defect nobody wrote. So the flag is built at run
    # time: what is on this line is not the shape, and what lands in the scratch
    # file is.
    local q
    q="-$(printf 'q')"
    {
        echo '#!/usr/bin/env bash'
        echo 'set -o pipefail'
        echo "if printf \"%s\" \"\$body\" | grep ${q} \"NEEDLE\"; then :; fi"
    } >"${canary_dir}/scripts/planted.sh"
    {
        echo '#!/usr/bin/env bash'
        echo 'set -o pipefail'
        echo 'if printf "%s" "$body" |'
        echo "    grep ${q}E \"NEEDLE\"; then :; fi"
    } >"${canary_dir}/scripts/tests/planted_continuation.sh"
    canary_hits="$(find "${canary_dir}" -type f -name '*.sh' | quiet_tail_sites | wc -l | tr -d ' ')"
    if [ "$canary_hits" -eq 2 ]; then
        echo "  ok       ${CURRENT} — the canary fires: both planted shapes are seen, the one-liner and the one whose reader is on its own line"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — the canary found ${canary_hits} of 2 planted sites; a scanner that cannot see a planted defect cannot see a real one"
        FAILED=$((FAILED + 1))
    fi

    # THE NEGATIVE. A quiet reader handed a FILE has no producer to strangle and
    # must stay silent, or this guard converts the whole tree to buy nothing.
    rm -rf "${canary_dir:?}"
    mkdir -p "${canary_dir}/scripts"
    {
        echo '#!/usr/bin/env bash'
        echo 'set -o pipefail'
        echo 'if grep -q "NEEDLE" "$file"; then :; fi'
        echo 'if grep -qF -- "$1" "$ERR" || grep -qF -- "$1" "$OUT"; then :; fi'
        echo 'lc_scan | awk "/NEEDLE/ { f = 1 } END { exit !f }"'
    } >"${canary_dir}/scripts/negatives.sh"
    negative_hits="$(find "${canary_dir}" -type f -name '*.sh' | quiet_tail_sites | wc -l | tr -d ' ')"
    if [ "$negative_hits" -eq 0 ]; then
        echo "  ok       ${CURRENT} — the negatives stay silent: a file-argument reader, an ||-list of them, and a full-stream reader are all correctly not the shape"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — the sweep claimed ${negative_hits} hit(s) on shapes that are not the defect; a guard that cries wolf gets an allow-list entry per false alarm and then gets deleted"
        FAILED=$((FAILED + 1))
    fi
    rm -rf "${canary_dir:?}"

    # THE SECOND CANARY, and it is the guard-reach finding's whole argument made
    # executable: a
    # census row admits ONE SITE, not one file. The GQ-1 verifier planted a
    # second `PARTITION_KEY_RE` pipeline in `gate_ledger.sh` — a file the census
    # covered — and the guard stayed 6 ok / 0 failed, because the old key was
    # (path-suffix, needle-in-line-or-next) and the planted line carried the
    # needle too. So this plant reproduces exactly that: a scratch
    # `gate_ledger.sh` holding the censused pipeline AND a second, different one
    # that shares its distinctive token. Under substring keying the second is
    # admitted silently; under equality it must be reported by `path:line`.
    #
    # IT BRINGS ITS OWN CENSUS. The row it is admitted against is local to this
    # block (bash locals are dynamically scoped, so `quiet_tail_unallowed` reads
    # this one), which keeps the canary independent of whatever the real census
    # happens to hold — a canary whose subject is found state proves whatever
    # the tree did last week.
    local planted_line planted_at plant_hits plant_census
    canary_dir="${WORK}/quiet-tail-census-canary"
    mkdir -p "${canary_dir}/scripts"
    q="-$(printf 'q')"
    {
        echo '#!/usr/bin/env bash'
        echo 'set -o pipefail'
        echo "printf '%s' \"\$key\" | grep ${q}E \"\$PARTITION_KEY_RE\""
        echo 'other_thing'
        echo "printf '%s' \"\$other\" | grep ${q} \"\$PARTITION_KEY_RE\" && :"
    } >"${canary_dir}/scripts/gate_ledger.sh"
    plant_census="${canary_dir}/census"
    printf '%s\n' "scripts/gate_ledger.sh|$(quiet_tail_normalise "printf '%s' \"\$key\" | grep ${q}E \"\$PARTITION_KEY_RE\"")|the censused site, and the ONLY one this row may admit" >"$plant_census"

    # THE PLANT PRINTS THAT IT TOOK, before anything is measured. A plant that
    # did not land makes the guard below green for the wrong reason, and a green
    # for the wrong reason is worse than a red. `grep -c` reads the copy on
    # disk, not the variable that wrote it.
    planted_line="$(grep -n "grep ${q} " "${canary_dir}/scripts/gate_ledger.sh" | head -n 1 | cut -d: -f1)"
    plant_hits="$(grep -c "grep ${q} " "${canary_dir}/scripts/gate_ledger.sh")"
    if [ "$plant_hits" != "1" ] || [ -z "$planted_line" ]; then
        rm -rf "${canary_dir:?}"
        cannot_look "the census canary's second pipeline did not land in the scratch gate_ledger.sh (${plant_hits} occurrence(s)); nothing below was measured"
    fi
    planted_at="scripts/gate_ledger.sh:${planted_line}"
    echo "  PLANT TOOK at ${planted_at} — a second pipeline sharing the censused row's token, in a file the census covers"

    plant_hits="$(cd "${canary_dir}" && find . -type f -name '*.sh' | sed 's|^\./||' | quiet_tail_sites | quiet_tail_unallowed "$plant_census")"
    if [ "$plant_hits" = "$planted_at" ]; then
        echo "  ok       ${CURRENT} — the census admits one SITE, not one file: the planted second pipeline is reported at ${planted_at} while the row's own site stays admitted"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — wanted exactly ${planted_at} unallowed, got \"${plant_hits}\"; a census keyed loosely enough to admit a line nobody wrote is an off switch with a reason field"
        FAILED=$((FAILED + 1))
    fi

    # AND THE SAME PLANT AGAINST THE OLD KEY, which is the half that goes red on
    # the shape replaced here. The row carries the SHORT NEEDLE the
    # census used to be keyed on — the token both pipelines share — and it must
    # now admit NEITHER of them: under substring matching it admitted both, which
    # is precisely how the verifier's plant went unseen. Restore the substring
    # test in `quiet_tail_unallowed` and this case fails; the one above does not,
    # which is why both are here.
    printf '%s\n' 'scripts/gate_ledger.sh|$PARTITION_KEY_RE|an OLD-STYLE short needle: the key this census is no longer allowed to be' >"$plant_census"
    plant_hits="$(cd "${canary_dir}" && find . -type f -name '*.sh' | sed 's|^\./||' | quiet_tail_sites | quiet_tail_unallowed "$plant_census")"
    if [ "$plant_hits" = "scripts/gate_ledger.sh:3
${planted_at}" ]; then
        echo "  ok       ${CURRENT} — a short needle admits nothing: both planted pipelines are reported, where the old (path, needle-in-line) key admitted both"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — a census row carrying only a shared token still admits a site; got \"${plant_hits}\". The key is not the site's own text, and one row is covering a file again"
        FAILED=$((FAILED + 1))
    fi
    rm -rf "${canary_dir:?}"
}

case_the_frame_has_exactly_one_temporal_parser() {
    # The three inline `python3 -c` programs are gone; if one comes back, the
    # clocks have two readings and the second is the one nobody checked.
    local inline
    inline="$(grep -c "python3 -c '" scripts/lifecycle.sh)"
    holds "one parser: no inline python program remains in the registry" "0" "$inline"
}

# ONE RUN OF `--class schedule --only <scratch>`, TWO CASES. The
# two cases below asked byte-identical questions of the broom and read
# different answers out of the transcript — one that the census is dated, one
# that a HALF-SCANNED run prints no roll-up. Two runs is two answers, and the
# second one is the one nobody read; the memo is the idiom this file already
# uses for `$DRIVE_OUT` (the `drive`/`says` pair above).
SCHEDULE_CENSUS_READY=""
SCHEDULE_CENSUS_OUT=""
SCHEDULE_CENSUS_RC=0
schedule_census_once() {
    if [ -n "$SCHEDULE_CENSUS_READY" ]; then
        DRIVE_OUT="$SCHEDULE_CENSUS_OUT"
        DRIVE_EXIT="$SCHEDULE_CENSUS_RC"
        return 0
    fi
    plant_databases
    plant_temporal
    drive "census: the scratch schedule is dated, not just named" 0 -- \
        ./scripts/sweep.sh --class schedule --only "$SCRATCH_BASE"
    SCHEDULE_CENSUS_OUT="$DRIVE_OUT"
    SCHEDULE_CENSUS_RC="$DRIVE_EXIT"
    SCHEDULE_CENSUS_READY=1
}

case_the_census_says_what_a_schedule_is_doing() {
    schedule_census_once
    says "starts Lc2ScratchNeverRuns"
    says "NOTHING POLLING"
}

case_the_graveyard_rollup_counts_what_nothing_polls() {
    # NO SECOND PLANT. `schedule_census_once` above planted both, and nothing
    # between here and there sweeps: the only `--force-foreign` runs in this
    # file are hundreds of lines earlier and this pair is the last plant of the
    # run. A re-plant is two `lc_temporal` calls for a world already standing.
    drive "rollup: the scratch queue is reported stranded" 0 -- \
        ./scripts/sweep.sh --class task-queue --only "$SCRATCH_BASE"
    says "stranded: queues NOTHING IS POLLING that no visible checkout owns"
    says "1 schedule(s) still aimed at it · 1 open run(s)"
    # The standing rule, printed where the operator reads the count — and said
    # WITHOUT the word `DESTROYED`, which is the token every other case greps a
    # transcript for to find out whether anything died.
    says "This census TOUCHED NOTHING"
    says_not "DESTROYED"
}

case_the_rollup_is_silent_about_what_it_did_not_look_at() {
    # The roll-up needs BOTH Temporal scans. A `--class schedule` run took only
    # one, so it must not print a population figure at all: a roll-up assembled
    # from half the population is a number nobody can act on.
    #
    # THE SAME RUN THE CENSUS CASE READ, and that is the point rather than an
    # economy: the transcript this case says is missing a roll-up is the very
    # transcript the case above says carries the dated schedule, so the two
    # readings cannot drift apart onto two different runs of one command.
    schedule_census_once
    CURRENT="rollup: a half-scanned run prints no roll-up"
    says_not "stranded: queues NOTHING IS POLLING"
}

case_the_ownership_of_the_machine_state_layer_is_argued() {
    # The other half of that finding was a DECISION — who reaps the schedules of a checkout
    # that no longer exists — and a decision that lives in a report evaporates.
    local hits
    hits="$(grep -c "WHO OWNS THE MACHINE-STATE LAYER" scripts/sweep.sh)"
    holds "ownership: the argument is in the instrument's header" "1" "$hits"
    hits="$(grep -c "a deleted checkout cannot self-clean" scripts/sweep.sh)"
    holds "ownership: it names why a create-side self-clean cannot cover this" "1" "$hits"
}

# --- the two cases about the DERIVATION itself --------------------------------
#
# Both of them spawn a CHILD run of this same file, so both are disarmed inside
# one: a drive that ran itself inside itself would never stop. The guard is an
# environment variable the child carries, and it disarms nothing else — a nested
# run drives every other case exactly as a hand-run one does, which is what makes
# the concurrency case's two children real runs rather than a rehearsal.

case_a_leftover_plant_from_a_killed_run_is_a_refusal_naming_the_broom() {
    if [ -n "${DJB_SWEEP_DRIVE_NESTED:-}" ]; then
        skipped "leftover plant: the startup refusal names the broom" \
            "a killed run's residue refused rather than silently dropped" \
            "this is a nested run; it would spawn a third and never stop"
        return
    fi
    CURRENT="leftover plant: the startup refusal names the broom"
    # ITS OWN VICTIM: the database this driver would itself have planted, created
    # here on purpose so the child meets residue that is unmistakably ours.
    db_query 'CREATE DATABASE :"name"' -v name="$SCRATCH_BASE" >/dev/null 2>&1
    DRIVE_OUT="${WORK}/leftover-child.log"
    DRIVE_EXIT=0
    DJB_SWEEP_DRIVE_NESTED=1 ./scripts/tests/test_sweep.sh >"$DRIVE_OUT" 2>&1 || DRIVE_EXIT=$?
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_BASE" >/dev/null 2>&1
    holds "leftover plant: a child meeting its own residue is could-not-look" "2" "$DRIVE_EXIT"
    says "already exists and no checkout derives it"
    says "./scripts/db_sweep.sh --name ${SCRATCH_BASE}"
}

case_two_checkouts_run_the_sweep_drive_concurrently_and_both_stay_green() {
    if [ -n "${DJB_SWEEP_DRIVE_NESTED:-}" ]; then
        skipped "two concurrent checkouts: both stay green" \
            "two checkouts planting at once do not destroy each other's machinery" \
            "this is a nested run; it would spawn two more and never stop"
        return
    fi
    CURRENT="two concurrent checkouts: both stay green"
    # WHAT THIS CASE COULD NOT SAY, AND WHY IT CAN NOW. On CI run 35241431444
    # it printed one line — `clone b exited 0 — wanted '0', got '1'` — and
    # nothing else. The nested run's own transcript went to `$log_b` under
    # `$WORK`, `$WORK` is destroyed with the runner, and the whole of what
    # anybody could learn afterwards was that SOMETHING in a nested copy of this
    # drive reddened on Linux. It did not reproduce on a laptop under the
    # runner's own environment (209 passed · 0 failed · 1 skipped), so the cause
    # is still OPEN and is recorded as open rather than guessed at.
    #
    # Two things changed below so the next run answers instead of asking: a
    # non-zero clone prints the nested run's own reds (or its tail, if it died
    # before printing any), and a clone that exited 2 is reported as
    # could-not-look rather than as a red — 2 outranks 1 here exactly as it does
    # everywhere else, and a busy runner that could not create a database is not
    # a concurrency defect.
    #
    # TWO CLONES, so the two derivations differ the only way they can: by path.
    # `--local` hardlinks the object store, so this costs seconds rather than a
    # copy of the repository.
    local a="${WORK}/clone-a" b="${WORK}/clone-b"
    if ! git clone --quiet --local "$SCRATCH_TOPLEVEL" "$a" 2>"${WORK}/clone-a.err" ||
        ! git clone --quiet --local "$SCRATCH_TOPLEVEL" "$b" 2>"${WORK}/clone-b.err"; then
        skipped "two concurrent checkouts: both stay green" \
            "two checkouts planting at once do not destroy each other's machinery" \
            "git clone --local refused: $(cat "${WORK}/clone-a.err" "${WORK}/clone-b.err" 2>/dev/null | tr '\n' ' ')"
        return
    fi
    # THE WORKING TREE, NOT THE COMMIT. A clone carries what is COMMITTED, so a
    # change to this very file would be measured in its previous state and the
    # case would pass about code nobody is shipping — which is exactly what it
    # did the first time it ran. The scripts directory is the subject; it is
    # overlaid so each clone runs the tree under test at its own path.
    cp -R "${SCRATCH_TOPLEVEL}/scripts/." "${a}/scripts/"
    cp -R "${SCRATCH_TOPLEVEL}/scripts/." "${b}/scripts/"
    # AND THE INTERPRETER, BY SYMLINK, for the same reason the scripts are
    # overlaid: a clone carries tracked files and `.venv` is ignored, so each
    # clone would start with no interpreter of its own. `sweep.sh` and this
    # drive both now require the CHECKOUT'S python — a repository python file
    # run on whatever `python3` is first on PATH is what took the first off-box
    # gate run down — and a clone with none is a could-not-look, correctly, at
    # which point this case measures a refusal instead of a concurrency. The
    # symlink is what makes each clone a checkout rather than a source tree.
    ln -s "${SCRATCH_TOPLEVEL}/.venv" "${a}/.venv" 2>/dev/null || true
    ln -s "${SCRATCH_TOPLEVEL}/.venv" "${b}/.venv" 2>/dev/null || true
    local log_a="${WORK}/concurrent-a.log" log_b="${WORK}/concurrent-b.log"
    local pid_a pid_b rc_a=0 rc_b=0
    # BACKGROUNDED AND WAITED ON IN THE FOREGROUND, never detached: a run this
    # case does not wait for is a run this case did not measure.
    # NARROWED, AND THE CHILD SAYS WHICH CASES IT RAN. The four
    # things read out of each transcript below are claims about the DERIVATION,
    # and `DJB_SWEEP_DRIVE_CHILD=1` runs exactly the plant/destroy chain over
    # it — the argument, and what it gives up, is at `SWEEP_CHILD_CHAIN`.
    (cd "$a" && DJB_SWEEP_DRIVE_NESTED=1 DJB_SWEEP_DRIVE_CHILD=1 ./scripts/tests/test_sweep.sh) >"$log_a" 2>&1 &
    pid_a=$!
    (cd "$b" && DJB_SWEEP_DRIVE_NESTED=1 DJB_SWEEP_DRIVE_CHILD=1 ./scripts/tests/test_sweep.sh) >"$log_b" 2>&1 &
    pid_b=$!
    wait "$pid_a" || rc_a=$?
    wait "$pid_b" || rc_b=$?

    local base_a base_b
    base_a="$(sed -n 's/^  scratch identity \([^ ]*\) .*/\1/p' "$log_a" | sed -n '1p')"
    base_b="$(sed -n 's/^  scratch identity \([^ ]*\) .*/\1/p' "$log_b" | sed -n '1p')"
    if [ -z "$base_a" ] || [ -z "$base_b" ]; then
        DRIVE_OUT="$log_a"
        holds "two concurrent checkouts: both runs printed a scratch identity" "yes" "no"
        return
    fi
    if [ "$base_a" = "$base_b" ]; then
        holds "two concurrent checkouts: the two identities differ" "different" "both ${base_a}"
    else
        echo "  ok       two concurrent checkouts: the two identities differ — ${base_a} vs ${base_b}"
        PASSED=$((PASSED + 1))
    fi

    local which
    for which in a b; do
        local log rc other
        if [ "$which" = a ]; then
            log="$log_a"
            rc="$rc_a"
            other="$base_b"
        else
            log="$log_b"
            rc="$rc_b"
            other="$base_a"
        fi
        DRIVE_OUT="$log"
        CURRENT="two concurrent checkouts: clone ${which}"
        # THE STATUS AND THE TRANSCRIPT, because one without the other is a red
        # nobody can act on. `holds` prints a status and no words — which is the
        # right shape for every other caller and the wrong one here, where the
        # thing that failed is a WHOLE NESTED RUN of this same drive whose own
        # transcript went to a file under `$WORK`. On CI run 35241431444 that
        # produced exactly one line — `clone b exited 0 — wanted '0', got '1'` —
        # and `$WORK` was destroyed with the runner, so the only witness to why
        # a nested drive reddened was gone before anybody read the log.
        #
        # So the excerpt is the deliverable, not the path: the nested run's own
        # red lines if it printed any, and its tail if it died before it could.
        if [ "$rc" = "0" ]; then
            echo "  ok       two concurrent checkouts: clone ${which} exited 0 — 0"
            PASSED=$((PASSED + 1))
        else
            local excerpt=""
            excerpt="$(grep -aE '^  (FAILED|SKIPPED)|^!!|^ +!!' "$log" 2>/dev/null || true)"
            if [ "$rc" = "2" ]; then
                # 2 OUTRANKS 1, AND IT OUTRANKS IT HERE TOO. The nested run is
                # this same drive, so its statuses are this drive's: 1 is a
                # property that did not hold, 2 is a run that COULD NOT LOOK —
                # a database it could not create, a stack that did not answer,
                # a scratch path it refused. Reporting a could-not-look as a
                # red would send the next reader hunting for a concurrency bug
                # that is a busy machine, and reporting it as a pass is the
                # thing this repository refuses everywhere.
                echo "             | clone ${which} exited 2 — it could not look, which is not a red:"
                printf '%s\n' "${excerpt:-$(tail -n 30 "$log" 2>/dev/null || true)}" |
                    sed 's/^/             | /' | sed -n '1,40p'
                cannot_look "the nested run in clone ${which} exited 2 (could not look) — its own words are above. Nothing about concurrent checkouts was asserted, and a drive that could not run its cases has not cleared them."
            fi
            echo "  FAILED   two concurrent checkouts: clone ${which} exited 0 — wanted '0', got '${rc}'"
            if [ -z "$excerpt" ]; then
                excerpt="$(tail -n 30 "$log" 2>/dev/null || true)"
                echo "             | (it printed no red of its own — the last 30 lines of its transcript:)"
            else
                echo "             | (the nested run's own reds, from ${log##*/}:)"
            fi
            # Read whole, then slice: a pipeline tail that stops early takes its
            # producer's exit status with it (the pipefail census).
            printf '%s\n' "$excerpt" | sed 's/^/             | /' | sed -n '1,40p'
            FAILED=$((FAILED + 1))
        fi
        says_not "MUTATED THE REAL REPOSITORY"
        # The shape the shared constant produced: one run's sweep naming — and
        # destroying — the other's plant.
        if grep -qF -- "$other" "$log"; then
            echo "  FAILED   two concurrent checkouts: clone ${which} named the OTHER run's identity ${other}"
            grep -nF -- "$other" "$log" | sed 's/^/             | /' | sed -n '1,10p'
            FAILED=$((FAILED + 1))
        else
            echo "  ok       two concurrent checkouts: clone ${which} never named ${other}"
            PASSED=$((PASSED + 1))
        fi
    done
}

echo "test_sweep: driving scripts/sweep.sh and scripts/lifecycle.sh"
echo "  this checkout   ${OUR_BASE} (the derivation; ownership is never the pin)"
[ "$DATABASE_NAME" = "$OUR_BASE" ] ||
    echo "  DATABASE_NAME    ${DATABASE_NAME} — exported, so it wins for CONNECTING (db.sh rule 1)"
echo "  scratch identity ${SCRATCH_BASE} (created and torn down by this driver)"

# --- THE CHILD'S NARROWED SET ------------------------------------------------
#
# WHAT A CHILD IS FOR, and it is not "this drive again". The concurrency case
# below spawns two whole nested runs of this file from two clones, at once, and
# reads four things out of each: that it printed a scratch identity, that the
# two identities DIFFER, that neither transcript ever names the other's, and
# that neither exited non-zero. Every one of those is a claim about the
# DERIVATION and about a plant/destroy chain over it — and the chain is five
# cases long, not fifty. The other forty-four were re-proving, twice over and
# concurrently, properties the parent had already proved serially, which is what
# made this one case most of the drive's wall clock (395 s of it measured by the
# lead; 493 s on this box under load).
#
# SO THE CHILD RUNS THE CHAIN AND SAYS SO. `DJB_SWEEP_DRIVE_CHILD=1` selects
# the five cases that would REDDEN if two checkouts shared one derivation —
# plant, survive a non-force sweep, destroy with `--force-foreign`, and find it
# gone — and the child's banner names them, so a reader of a nested transcript
# can see what was and was not asked. It is set only by the concurrency case;
# `DJB_SWEEP_DRIVE_NESTED=1` alone (the leftover-plant child, which refuses at
# startup before any case) still means "every case".
#
# WHAT THIS GIVES UP, declared: a defect that appears only when two checkouts
# run some OTHER case at the same time is now invisible here. The trade is
# argued rather than assumed — the isolation the case exists to prove is the
# derivation's, the chain above is where the derivation is used destructively,
# and a case that neither plants nor destroys cannot collide with a peer's plant.
SWEEP_CHILD_CHAIN="case_the_dead_queue_sibling_is_required_empty_before_anything_is_planted
case_new_classes_are_censused_as_foreign
case_sweep_alone_leaves_foreign_alone
case_force_foreign_prints_then_acts
case_the_scratch_machinery_is_actually_gone"

if [ -n "${DJB_SWEEP_DRIVE_CHILD:-}" ]; then
    echo "  narrowed       DJB_SWEEP_DRIVE_CHILD=1 — this child runs the clone-isolation chain only:"
    printf '%s\n' "$SWEEP_CHILD_CHAIN" | sed 's/^/                   /'
    for case_fn in $SWEEP_CHILD_CHAIN; do
        "$case_fn"
    done
else
    case_an_empty_capture_is_could_not_look
    case_registry_is_the_declared_population
    case_registry_declares_all_seven_columns
    case_registry_claims_every_planted_shape
    case_verdict_grammar_answers_all_four
    case_one_enumerator_two_consumers
    case_sweep_refuses_an_unknown_flag
    case_sweep_refuses_force_foreign_without_sweep
    case_sweep_refuses_an_empty_only
    case_sweep_refuses_a_root_that_is_not_there
    case_sweep_refuses_an_unknown_class
    # BEFORE the first plant, because it plants the scratch database itself and
    # drops it again: a child of this file must meet residue and nothing else.
    case_a_leftover_plant_from_a_killed_run_is_a_refusal_naming_the_broom
    # BEFORE the first plant: the sibling this file proves every dead-queue property
    # on is REQUIRED pollerless and empty, not assumed to be (that third pattern).
    case_the_dead_queue_sibling_is_required_empty_before_anything_is_planted
    case_new_classes_are_censused_as_foreign
    case_sweep_alone_leaves_foreign_alone
    # The two refusals, run while the decoy is still planted: they have to be
    # asked with something in scope to lose, or "nothing was destroyed" is a sentence
    # about an empty world.
    case_force_foreign_without_roots_is_refused_and_drops_nothing
    case_only_does_not_license_force_foreign_without_roots
    case_db_sweep_force_foreign_without_roots_is_refused
    case_force_foreign_prints_then_acts
    case_the_scratch_machinery_is_actually_gone
    case_a_refused_shape_survives_force_foreign
    case_a_rooted_clones_linked_worktree_database_reads_live
    case_two_roots_are_both_scanned_and_printed
    case_an_unrecognized_shape_is_exit_2
    case_a_declared_shape_is_not_unrecognized
    case_a_dot_env_pin_does_not_decide_who_owns_what
    case_an_exported_pin_does_not_move_this_checkouts_identity
    case_owning_is_not_a_licence_to_destroy
    case_this_checkouts_running_work_survives_force_foreign
    case_assert_none_is_silent_on_an_empty_scope
    case_assert_none_fails_on_a_populated_scope
    case_assert_none_refuses_to_be_a_broom
    case_the_gate_census_asserts_open_executions_too
    case_the_gate_census_remedy_actually_clears_a_strand
    # AFTER the remedy case, on purpose: this one plants a run on this checkout's own
    # queue, and the remedy case's re-green assertion is over exactly that scope.
    case_assert_none_exempts_this_checkouts_own_working_set_in_use
    case_assert_none_keeps_its_teeth_on_an_owned_instance_nothing_is_using
    case_assert_none_still_fails_on_a_stray_run_this_checkout_owns
    case_the_redis_answer_is_recorded
    case_the_parser_reads_both_of_temporals_time_formats
    case_a_stamp_the_parser_cannot_read_is_unknown_and_never_zero
    case_a_backlog_is_evidence_of_harm_and_never_of_liveness
    case_the_parser_refuses_what_it_cannot_read
    case_a_presence_probe_survives_a_long_scan
    case_the_frame_has_exactly_one_temporal_parser
    case_the_census_says_what_a_schedule_is_doing
    case_the_graveyard_rollup_counts_what_nothing_polls
    case_the_rollup_is_silent_about_what_it_did_not_look_at
    case_the_ownership_of_the_machine_state_layer_is_argued
    # LAST, and the most expensive: it runs this whole file twice more, from two
    # clones, at once. Everything above has torn its own plants down by now, so the
    # two children meet a machine in the state a hand-run would leave it in.
    case_two_checkouts_run_the_sweep_drive_concurrently_and_both_stay_green
fi

echo "test_sweep: ${PASSED} passed · ${FAILED} failed · ${SKIPPED} skipped"
if [ "$SKIPPED" -gt 0 ]; then
    # NOT a footnote. A skip here means a WORLD this run could not reach — a
    # poller it may not start, a strand it may not plant on a polled queue — and
    # each one is named above with the property it did not prove. A count in the
    # summary is what keeps a transcript full of skips from reading as a clean
    # run (its queue row: a premise silently assumed is the defect).
    echo "            each skip names the world it did not prove and why; a skip is not a pass"
fi
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property did not hold. Both halves of a refusal are load-bearing: the" >&2
    echo "   status a caller branches on and the sentence a human acts on." >&2
    exit 1
fi
exit 0
