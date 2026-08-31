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
# `djb_lc2scratch_0badc0de`, derivation-shaped so the frame judges it exactly as
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
#   * `IN USE` END TO END. A live `pg_stat_activity` session or a live
#     `DescribeTaskQueue` poller needs another process holding one, which this
#     driver has no business starting on a shared server. The verdict FUNCTION is
#     driven directly instead (`case_verdict_grammar_answers_all_four`), which is
#     where the ordering between the four actually lives.
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

cannot_look() {
    echo "!! test_sweep: $*" >&2
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

SCRATCH_BASE="djb_lc2scratch_0badc0de"
SCRATCH_QUEUE="djb-lc2scratch_0badc0de"
SCRATCH_TEST_DB="test_${SCRATCH_BASE}_gw0"
SCRATCH_HP_DB="${SCRATCH_BASE}_hp"
SCRATCH_FAKE_DB="djb_zzz_deadbeef_lc2fake"
SCRATCH_SCHEDULE="lc2scratch-probe:${SCRATCH_QUEUE}"
SCRATCH_EXECUTION="lc2scratch:probe:open:key"
# A schedule keyed to a queue with NO path digest in it — the shape an
# undigested name or a hand-pinned `TEMPORAL_TASK_QUEUE` produces. It must read REFUSED and
# survive even a `--force-foreign`.
SCRATCH_UNDERIVED_SCHEDULE="lc2scratch-probe:djb-lc2scratchnohash"

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

WORK="$(mktemp -d)"
drive_require_scratch WORK "${WORK:-}"

teardown() {
    # Idempotent, and it runs on every exit path including a failed case: a
    # driver that leaks its own scratch machinery is the leak it is testing for.
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_BASE" >/dev/null 2>&1
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_TEST_DB" >/dev/null 2>&1
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_HP_DB" >/dev/null 2>&1
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_FAKE_DB" >/dev/null 2>&1
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="djb_zzz_deadbeef" >/dev/null 2>&1
    lc_temporal schedule delete --schedule-id "$SCRATCH_SCHEDULE" >/dev/null 2>&1
    lc_temporal schedule delete --schedule-id "$SCRATCH_UNDERIVED_SCHEDULE" >/dev/null 2>&1
    lc_temporal workflow terminate --workflow-id "$SCRATCH_EXECUTION" \
        --reason "test_sweep teardown" >/dev/null 2>&1
    lc_temporal workflow terminate --workflow-id "liveprobe:this:checkout:open" \
        --reason "test_sweep teardown" >/dev/null 2>&1
    # The strand `case_the_gate_census_remedy_actually_clears_a_strand` plants on
    # THIS checkout's queue. Its own body ends it by running the gate's printed
    # remedy — which is the assertion — so this line only ever fires when the
    # remedy did not work, i.e. exactly when the case has just gone red. A
    # driver that leaked a strand while proving strands get cleared would be
    # funny once.
    lc_temporal workflow terminate --workflow-id "g3fixprobe:this:checkout:strand" \
        --reason "test_sweep teardown" >/dev/null 2>&1
    # ONLY IF THIS RUN CREATED IT. See plant_our_checkout_database.
    if [ "$PLANTED_OUR_DATABASE" -eq 1 ]; then
        db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$OUR_BASE" >/dev/null 2>&1
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

plant_temporal() {
    # Paused, and an interval a year long: nothing must ever actually start from
    # this schedule on a shared server. The execution is started deliberately and
    # stays Running forever because no worker polls the scratch queue — which is
    # exactly the "sweep-start stranded on a dead queue" shape being proven.
    lc_temporal schedule create --schedule-id "$SCRATCH_SCHEDULE" \
        --interval 8760h --paused \
        --workflow-id "lc2scratch:probe:noun:key" \
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

# The second half. A refusal with the right code and the wrong sentence is a
# refusal nobody can act on, so both are asserted about the same run.
says() {
    local needle="$1"
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
    if grep -qF -- "$needle" "$DRIVE_OUT"; then
        echo "  FAILED   ${CURRENT} — says \"${needle}\" and must not"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -20
        FAILED=$((FAILED + 1))
    else
        echo "  ok       ${CURRENT} — does not say \"${needle}\""
        PASSED=$((PASSED + 1))
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
# hundred, which is the worst case for this bug and hits every single run. The
# graveyard is the TRIGGER; the defect is this file's, and sweeping the
# graveyard would only hide it until the list grew again.
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

case_force_foreign_prints_then_acts() {
    # The promise the header makes: every name and its reason BEFORE the
    # consequence, so an operator can stop at the first surprise. Asserted by
    # LINE ORDER, not merely by both lines existing.
    drive "sweep: --force-foreign destroys the scratch machinery" 0 -- \
        ./scripts/sweep.sh --sweep --force-foreign --hot-path --only "$SCRATCH_BASE"
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
    # `djb-lc2scratchnohash` — so nothing can say whose it is, and REFUSED means
    # never touched however loud the flags.
    lc_temporal schedule create --schedule-id "$SCRATCH_UNDERIVED_SCHEDULE" \
        --interval 8760h --paused \
        --workflow-id "lc2scratch:probe:noun:underived" \
        --task-queue "djb-lc2scratchnohash" --type "Lc2ScratchNeverRuns" >/dev/null 2>&1
    drive "sweep: a schedule with no path digest is REFUSED" 0 -- \
        ./scripts/sweep.sh --class schedule --sweep --force-foreign --only "djb_lc2scratchnohash"
    says "REFUSED  ${SCRATCH_UNDERIVED_SCHEDULE}"
    says_not "DESTROYED"
    holds "sweep: the undeclared-identity schedule survived --force-foreign" "yes" \
        "$(schedule_present "$SCRATCH_UNDERIVED_SCHEDULE" && echo yes || echo no)"
    lc_temporal schedule delete --schedule-id "$SCRATCH_UNDERIVED_SCHEDULE" >/dev/null 2>&1
}

# --- CRITERION 4: an unrecognized shape is exit 2, naming it ------------------

case_an_unrecognized_shape_is_exit_2() {
    # A PLANTED FAKE, in the shape the design named: derivation-shaped
    # (`djb_zzz_deadbeef`), so this repository demonstrably made it — and wearing
    # a suffix no declared class claims. Could-not-judge outranks a pass.
    db_query 'CREATE DATABASE :"name"' -v name="$SCRATCH_FAKE_DB" >/dev/null 2>&1
    drive "census: a derived-shaped name no class claims is exit 2" 2 -- \
        ./scripts/sweep.sh --only "djb_zzz_deadbeef"
    says "UNRECOGNIZED database: ${SCRATCH_FAKE_DB}"
    says "Declare the class there"
    says "machinery class N+1 exists and the registry"
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="$SCRATCH_FAKE_DB" >/dev/null 2>&1
}

case_a_declared_shape_is_not_unrecognized() {
    # The negative that keeps the case above from passing vacuously: the same
    # census, over the same identity prefix, with only DECLARED shapes present,
    # is exit 0 and says nothing about an unrecognized anything.
    db_query 'CREATE DATABASE :"name"' -v name="djb_zzz_deadbeef" >/dev/null 2>&1
    drive "census: the same prefix with only declared shapes is exit 0" 0 -- \
        ./scripts/sweep.sh --only "djb_zzz_deadbeef"
    says_not "UNRECOGNIZED"
    says "FOREIGN  djb_zzz_deadbeef"
    db_query 'DROP DATABASE IF EXISTS :"name"' -v name="djb_zzz_deadbeef" >/dev/null 2>&1
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
    local wid="liveprobe:this:checkout:open"
    lc_temporal workflow start --workflow-id "$wid" --task-queue "$OUR_QUEUE" \
        --type "LiveProbeNeverRuns" >/dev/null 2>&1
    drive "live: my own running execution survives --sweep --force-foreign" 0 -- \
        ./scripts/sweep.sh --sweep --force-foreign --class open-execution --only "$OUR_BASE"
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

case_the_gate_census_remedy_actually_clears_a_strand() {
    # THE RED. This checkout's own identity, because that is the only way to be
    # `live` AND `mine` at once — the pair the remedy has to work against. The
    # id is prefixed so it is attributable to this driver on a shared server.
    local wid="g3fixprobe:this:checkout:strand" remedy remedy_rc
    lc_temporal workflow start --workflow-id "$wid" --task-queue "$OUR_QUEUE" \
        --type "GateStrandProbeNeverRuns" >/dev/null 2>&1
    holds "remedy: the strand is really there to begin with" "yes" \
        "$(execution_present "$wid" && echo yes || echo no)"
    drive "remedy: the leg's own assertion is RED on it" 1 -- \
        ./scripts/sweep.sh --class open-execution --only "$OUR_BASE" --assert-none
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
        ./scripts/sweep.sh --class open-execution --only "$OUR_BASE" --assert-none
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

# A stamp `<n>` seconds in the past, written the way Temporal writes one —
# trailing `Z`, NINE fractional digits — which is exactly the shape
# `datetime.fromisoformat` will not read as it finds it. A negative `<n>` is a
# stamp in the future. This is a fixture GENERATOR, not a second parser: it
# formats, it never reads.
stamp_ago() {
    python3 -c '
import sys
from datetime import UTC, datetime, timedelta

when = datetime.now(UTC) - timedelta(seconds=int(sys.argv[1]))
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
    row="$(python3 "$TEMPORAL_PY" schedules <"$fixture")"
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
    row="$(python3 "$TEMPORAL_PY" executions <"$fixture")"
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
    stats="$(python3 "$TEMPORAL_PY" queue <"$fixture")"
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
        bash -c "printf '' | python3 ${TEMPORAL_PY} schedules"
    drive "parser: a document that is not JSON is exit 2" 2 -- \
        bash -c "printf 'Error: connection refused' | python3 ${TEMPORAL_PY} executions"
    drive "parser: an unknown mode is exit 2, never a silent different read" 2 -- \
        bash -c "printf '[]' | python3 ${TEMPORAL_PY} pollers"
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

    # The probes must not go back to a short-circuiting reader. Read as TEXT,
    # because the failure is invisible at every scan size but the large one.
    if grep -qE '^\s*(lc_scan_open_executions|lc_scan_schedules) \| .*grep -q' "$0"; then
        echo "  FAILED   ${CURRENT} — a presence probe is a \`| grep -q\` pipeline again; under pipefail that reports ABSENT for something present"
        FAILED=$((FAILED + 1))
    else
        echo "  ok       ${CURRENT} — neither presence probe short-circuits its own reader"
        PASSED=$((PASSED + 1))
    fi
}

case_the_frame_has_exactly_one_temporal_parser() {
    # The three inline `python3 -c` programs are gone; if one comes back, the
    # clocks have two readings and the second is the one nobody checked.
    local inline
    inline="$(grep -c "python3 -c '" scripts/lifecycle.sh)"
    holds "one parser: no inline python program remains in the registry" "0" "$inline"
}

case_the_census_says_what_a_schedule_is_doing() {
    plant_databases
    plant_temporal
    drive "census: the scratch schedule is dated, not just named" 0 -- \
        ./scripts/sweep.sh --class schedule --only "$SCRATCH_BASE"
    says "starts Lc2ScratchNeverRuns"
    says "NOTHING POLLING"
}

case_the_graveyard_rollup_counts_what_nothing_polls() {
    plant_databases
    plant_temporal
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
    drive "rollup: a half-scanned run prints no roll-up" 0 -- \
        ./scripts/sweep.sh --class schedule --only "$SCRATCH_BASE"
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

echo "test_sweep: driving scripts/sweep.sh and scripts/lifecycle.sh"
echo "  this checkout   ${OUR_BASE} (the derivation; ownership is never the pin)"
[ "$DATABASE_NAME" = "$OUR_BASE" ] ||
    echo "  DATABASE_NAME    ${DATABASE_NAME} — exported, so it wins for CONNECTING (db.sh rule 1)"
echo "  scratch identity ${SCRATCH_BASE} (created and torn down by this driver)"

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
case_new_classes_are_censused_as_foreign
case_sweep_alone_leaves_foreign_alone
case_force_foreign_prints_then_acts
case_the_scratch_machinery_is_actually_gone
case_a_refused_shape_survives_force_foreign
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

echo "test_sweep: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property did not hold. Both halves of a refusal are load-bearing: the" >&2
    echo "   status a caller branches on and the sentence a human acts on." >&2
    exit 1
fi
exit 0
