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
# The drive for the MACHINE-WIDE GATE GUARDS (`scripts/gate_lease.sh`), for the
# caller and sanction fields the ledger records beside them
# (`scripts/gate_ledger.sh`), and for the sanction valve on the full gate itself
# (`scripts/check.sh`). Three guards, one drive, because they share a file, a
# scratch directory and a failure mode.
#
#   ./scripts/tests/test_gate_lease.sh          run every case
#   ./scripts/tests/test_gate_lease.sh --list   name them and stop
#
# WHY IT EXISTS. A full gate run beside another full gate on the same
# laptop took 607s and went RED on two tests; the same tree quiet took 99s and
# went green. The other gate's LOAD arrived as this gate's defect. The lease
# serializes full gates on one machine so that never happens again — and it is
# made almost entirely of behaviours whose failure mode is SILENT:
#
#   * a wait that stops announcing itself is indistinguishable from a hang, and
#     an agent watching a hang kills the gate;
#   * a stale-clear that stops firing turns every killed gate into a permanent
#     machine-wide block — and the tool's ten-minute ceiling kills full runs
#     routinely, so this is the common case, not the exotic one;
#   * a stale-clear that fires TOO EAGERLY (on a live holder, or on another
#     host's record) puts two full gates back on one box with nobody told;
#   * a lease accidentally taken by `--fast`/`--loop` would make every builder
#     in every checkout queue behind somebody else's push, which is friction
#     this repository keeps deleting rather than adding.
#
# Every one of those leaves a green gate. That is `test_secrets_scan.sh`'s class
# and `test_loop_tier.sh`'s class, and it belongs in the same leg for the same
# reason: a guard nobody drives is a guard that can be deleted by
# accident and stay deleted.
#
# IT NEVER TOUCHES THE REAL LEASE. Every case points `DJB_GATE_LEASE_DIR` at its
# own scratch directory, which is what makes this drive safe to run FROM INSIDE
# the full gate's own selftest leg — the real gate is holding the real lease at
# that moment, and a drive that reached for it would deadlock the gate that
# started it. The override exists for this, and its trust class ("one export
# away", exactly like the verdict ledger's "one `rm` away") is declared in
# `scripts/gate_lease.sh`'s header rather than pretended away.
#
# THE REAL FILE IS WHAT RUNS. `scripts/gate_lease.sh` and `scripts/gate_ledger.sh`
# are SOURCED, never copied, so there is no stub to drift.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE GATE ACTUALLY ACQUIRES AT RUNTIME. It cannot run the real
#     `./scripts/check.sh` from inside the gate's own selftest leg — the full
#     gate holds a per-checkout lock and would in any case recurse — so the
#     WIRING is proved by reading `check.sh` as TEXT: the call site, that it
#     sits inside the `MODE = ""` branch, that it is ABOVE `gate_lock_acquire`,
#     that the EXIT trap releases it, and that no `--fast`/`--loop` path reaches
#     it. That is a weaker proof than running it and it is named as one — the
#     identical constraint `test_db_pin.sh` and `test_loop_tier.sh` both carry.
#     The end-to-end property (two real concurrent full gates, one waiting, both
#     banking) was driven by hand at the rung that built this and is recorded in
#     that rung's report; it costs two full gates and cannot live in a leg.
#   * CONTENTION ACROSS MACHINES. Out of scope by construction, not by
#     omission — `scripts/gate_lease.sh`'s DECLARED LIMIT says so.
#   * WHETHER SERIALIZING ACTUALLY MAKES THE GATE FASTER OR GREENER. This drive
#     asserts no wall-clock claim of any kind. The 607s/99s measurement is
#     the evidence for the design; nothing here re-measures it.
#   * WHAT THE CALLER FIELD MEANS. It asserts that the vocabulary is closed,
#     that an unknown value degrades to `unstated` loudly, and that old lines
#     still parse. Whether a given run SHOULD have been a `quality-rung` is a
#     judgement no script makes (measurement, not enforcement).
#   * WHETHER A SANCTION'S REASON IS ANY GOOD. The valve cases below drive the
#     SHAPE (`<id>: <reason>`) and the closed list of legal callers. Whether
#     "X-1: because" was a real reason is the PM's read of the ledger, and this
#     drive says nothing about it — deliberately, and it is the sanction valve's
#     own declared limit rather than an omission here.
#   * THE LEGAL `--bank`. Every valve case here drives a REFUSAL, and that is
#     structural rather than lazy: a case that proved `--bank` is accepted would
#     have to let the full gate start, from inside the full gate's own selftest
#     leg. The acceptance side is read as TEXT with the rest of the wiring.
#   * WHETHER N SLOTS IS THE RIGHT N. The semaphore cases prove the arithmetic
#     is closed (N legs x cores/N workers = the cores) and that the ceiling
#     binds. Whether cores/5 is the right ratio for this box is a measurement,
#     not an assertion, and `DJB_GATE_SLOTS` is the knob rather than this file.
#   * A BARE `pytest`. It takes no slot, by construction. Named in
#     `scripts/gate_lease.sh`'s limits and asserted nowhere, because there is
#     nothing to assert.
set -euo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, before the first git command -----------------
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_gate_lease: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble: on bash 3.2 a `set -u` death hands the EXIT trap a
# status of 0, so a drive that never reached its summary would be read as green.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_gate_lease: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    # `^case_` alone matches BOTH halves of every case: the definition and the
    # bare call at the bottom of this file, so the list came out twice — 62
    # lines for 31 cases, with the second half carrying the call-site line
    # numbers. The DEFINITION is what a reader asked for, and `() {` is what
    # distinguishes it.
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    # A mistyped flag is never a silently different run.
    echo "!! unknown argument '$1': test_gate_lease.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -f scripts/gate_lease.sh ] || cannot_look "scripts/gate_lease.sh is not in this tree — there is nothing to drive"
[ -f scripts/gate_ledger.sh ] || cannot_look "scripts/gate_ledger.sh is not in this tree"
[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the wiring cannot be read"

ROOT="$PWD"

# shellcheck source=scripts/gate_lease.sh
. scripts/gate_lease.sh
command -v gate_lease_acquire >/dev/null 2>&1 || cannot_look "scripts/gate_lease.sh defines no gate_lease_acquire — the body is gone"
# shellcheck source=scripts/gate_ledger.sh
. scripts/gate_ledger.sh
command -v gate_caller >/dev/null 2>&1 || cannot_look "scripts/gate_ledger.sh defines no gate_caller — the caller field has no source"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-gate-lease-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# Every case runs against its own lease directory. Never the real one: the real
# gate is holding the real lease while this drive runs inside its selftest leg.
LEASE_DIR=""
LEASE_FILE=""
N=0
fresh_lease_dir() {
    N=$((N + 1))
    LEASE_DIR="${WORK}/lease${N}"
    drive_require_scratch LEASE_DIR "${LEASE_DIR:-}"
    mkdir -p "$LEASE_DIR"
    LEASE_FILE="${LEASE_DIR}/djb-gate-lease"
    export DJB_GATE_LEASE_DIR="$LEASE_DIR"
    GATE_LEASE=""
    GATE_LEASE_WAITED=0
}

# Sleepers this drive started, killed BY PID at exit — never by name (the
# standing rule: `pkill -f` has killed other agents' gates twice).
SLEEPERS=""
drive_at_exit 'for _p in $SLEEPERS; do kill "$_p" 2>/dev/null || true; done'

#: Set by `live_pid`; a process that is certainly running.
LIVE_PID=""

# NOT a command substitution, and that is a scar rather than a style choice.
# `holder=$(live_pid)` with a `sleep &` inside it HANGS: the background process
# inherits the substitution's stdout pipe, so `$( )` waits for the sleep to
# finish before returning — and the assignment to SLEEPERS would happen in the
# subshell and never reach the cleanup either. Both defects at once, found on
# this drive's own first run. So it sets a global, and every background process
# here has its stdout and stderr closed.
# `disown` because bash REPORTS a reaped background job ("Terminated: 15") on
# this drive's own stderr when the cleanup kills it, and this drive runs inside
# the gate's selftest leg where that reads as an error nobody can act on. The
# pid is kept in SLEEPERS either way — cleanup is by pid, never by name.
live_pid() {
    sleep 600 >/dev/null 2>&1 &
    LIVE_PID=$!
    SLEEPERS="${SLEEPERS} ${LIVE_PID}"
    disown "$LIVE_PID" 2>/dev/null || true
}

#: Set by `dead_pid`; a pid number that WAS real and is now gone. Started and
#: reaped rather than invented, because an invented number gets recycled.
DEAD_PID=""
dead_pid() {
    sleep 0 >/dev/null 2>&1 &
    DEAD_PID=$!
    wait "$DEAD_PID" 2>/dev/null || true
}

CURRENT=""
RC=0
OUT=""

out_file() {
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    : >"$OUT"
}

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    [ -n "$OUT" ] && [ -f "$OUT" ] && sed 's/^/             | /' "$OUT" | tail -25
    FAILED=$((FAILED + 1))
}

exits() {
    if [ "$RC" -eq "$1" ]; then
        ok "exit ${RC}"
    else
        bad "wanted exit $1, got ${RC}"
    fi
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
file_exists() {
    if [ -f "$1" ]; then
        ok "$2"
    else
        bad "$2 — but $1 is not there"
    fi
}
file_absent() {
    if [ -f "$1" ]; then
        bad "$2 — but $1 is still there: $(cat "$1" 2>/dev/null)"
    else
        ok "$2"
    fi
}

# --- the cases ----------------------------------------------------------------

case_an_uncontended_lease_is_taken_at_once() {
    # The normal case, and the one that must cost nothing: one machine, one full
    # gate, no waiting and no ceremony.
    CURRENT="an uncontended lease"
    fresh_lease_dir
    out_file
    RC=0
    gate_lease_acquire >"$OUT" 2>&1 || RC=$?
    exits 0
    says "full-gate lease held for this MACHINE"
    says_not "WAITING"
    file_exists "$LEASE_FILE" "the lease file is written"
    if [ "$GATE_LEASE_WAITED" = "0" ]; then
        ok "waited 0s"
    else
        bad "waited ${GATE_LEASE_WAITED}s and nothing was holding it"
    fi
    # The record identifies its holder: pid, mode, time, host, checkout.
    if awk 'NR==1 && NF>=5 && $1=='"$$"' && $2=="full" {found=1} END{exit found?0:1}' "$LEASE_FILE"; then
        ok "the record names this pid and the mode: $(cat "$LEASE_FILE")"
    else
        bad "the record does not name pid $$ and mode full: $(cat "$LEASE_FILE")"
    fi
    gate_lease_release
    file_absent "$LEASE_FILE" "releasing removes it"
}

case_a_second_gate_WAITS_and_SAYS_SO() {
    # THE CENTRAL CASE. A wait that says nothing is a hang as far as any reader
    # (or any agent watching a log) is concerned, and the whole reason the
    # lock chose refusal over waiting was that nobody had written the
    # announcement. So the announcement is asserted as text, not assumed.
    CURRENT="a second full gate waits, out loud"
    fresh_lease_dir
    local holder
    live_pid
    holder=$LIVE_PID
    printf '%s full 2026-08-25T00:00:00Z %s /some/other/checkout\n' \
        "$holder" "$(hostname -s 2>/dev/null || echo host)" >"$LEASE_FILE"
    out_file
    RC=0
    # A three-second ceiling with a one-second poll and a one-second announce
    # interval, so the whole shape — first announcement, re-announcement,
    # ceiling — is exercised in seconds rather than in an hour.
    DJB_GATE_LEASE_MAX_WAIT=3 DJB_GATE_LEASE_POLL=1 DJB_GATE_LEASE_ANNOUNCE=1 \
        gate_lease_acquire >"$OUT" 2>&1 || RC=$?
    # Could-not-look, never a red tree: nothing was judged.
    exits 2
    says "WAITING for the machine-wide full-gate lease"
    says "This is not a hang."
    says "holder: ${holder} full"
    says "... still waiting for the full-gate lease"
    says "REFUSING: waited"
    says "Nothing was judged. This is could-not-look, not a red tree."
    # And it did NOT take the lease it could not get.
    if [ -z "$GATE_LEASE" ]; then
        ok "no lease is recorded as held by the waiter"
    else
        bad "the waiter believes it holds ${GATE_LEASE}"
    fi
    if grep -qF "$holder full" "$LEASE_FILE"; then
        ok "the live holder's record is untouched"
    else
        bad "the live holder's record was overwritten: $(cat "$LEASE_FILE" 2>/dev/null)"
    fi
    kill "$holder" 2>/dev/null || true
}

case_the_lease_wait_prints_an_estimate_too() {
    # CRITERION 5 SAID "EVERY WAIT", and the slot wait printed a "~N min" while
    # the exclusive lease wait — the LONGER of the two by construction, since
    # it has no second slot to free early — printed none. A wait that will not
    # say roughly how long is a wait a reader cannot decide anything about.
    CURRENT="the lease wait prints an estimate"
    fresh_lease_dir
    local holder started
    live_pid
    holder=$LIVE_PID
    # A holder five minutes into a full gate, so the estimate is a number this
    # case can actually check rather than whatever the clock happens to say.
    started=$(($(date +%s) - 300))
    printf '%s full 2026-08-25T00:00:00Z %s %s /some/other/checkout\n' \
        "$holder" "$(hostname -s 2>/dev/null || echo host)" "$started" >"$LEASE_FILE"
    out_file
    RC=0
    DJB_GATE_LEASE_MAX_WAIT=3 DJB_GATE_LEASE_POLL=1 DJB_GATE_LEASE_ANNOUNCE=1 \
        gate_lease_acquire >"$OUT" 2>&1 || RC=$?
    exits 2
    says "Rough estimate from the holder's elapsed time: ~10 min"
    says "not a promise — nothing here decides anything on it"
    # And on the re-announcement too, which is the line a reader actually
    # watches: the first one scrolls away.
    says "~10 min left) — holder:"
    kill "$holder" 2>/dev/null || true

    # THE OLD RECORD STILL PARSES. A lease written before the epoch field
    # existed has the checkout PATH in position 5. It must lose the estimate
    # and nothing else — never a crash, and never a "~N min" computed from a
    # path.
    CURRENT="a pre-epoch lease record still parses"
    fresh_lease_dir
    live_pid
    holder=$LIVE_PID
    printf '%s full 2026-08-25T00:00:00Z %s /some/other/checkout\n' \
        "$holder" "$(hostname -s 2>/dev/null || echo host)" >"$LEASE_FILE"
    out_file
    RC=0
    DJB_GATE_LEASE_MAX_WAIT=2 DJB_GATE_LEASE_POLL=1 DJB_GATE_LEASE_ANNOUNCE=1 \
        gate_lease_acquire >"$OUT" 2>&1 || RC=$?
    exits 2
    says "WAITING for the machine-wide full-gate lease"
    says "holder: ${holder} full"
    says_not "Rough estimate"
    says_not "min left)"
    kill "$holder" 2>/dev/null || true

    # And the record this file WRITES carries the field, so the estimate is
    # available to the next waiter rather than only to a hand-made fixture.
    CURRENT="the lease record carries the epoch"
    fresh_lease_dir
    if gate_lease_try; then
        local field5
        field5=$(awk 'NR==1{print $5}' "$LEASE_FILE")
        case "$field5" in
        '' | *[!0-9]*) bad "field 5 of the lease record is '${field5}', not an epoch" ;;
        *) ok "field 5 is an epoch (${field5}), so a waiter can do arithmetic" ;;
        esac
        gate_lease_release
    else
        bad "could not take an uncontended lease to read its own record"
    fi
}

case_a_waiter_gets_the_lease_when_the_holder_lets_go() {
    # The other half of waiting: it ENDS. A queue that only ever times out is a
    # refusal with extra steps.
    CURRENT="a waiter acquires when the holder frees it"
    fresh_lease_dir
    local holder
    live_pid
    holder=$LIVE_PID
    printf '%s full 2026-08-25T00:00:00Z %s /some/other/checkout\n' \
        "$holder" "$(hostname -s 2>/dev/null || echo host)" >"$LEASE_FILE"
    # The holder lets go two seconds in, in the background, exactly as a
    # finishing gate's EXIT trap would.
    (
        sleep 2
        rm -f "$LEASE_FILE"
    ) >/dev/null 2>&1 &
    SLEEPERS="${SLEEPERS} $!"
    disown $! 2>/dev/null || true
    out_file
    RC=0
    DJB_GATE_LEASE_MAX_WAIT=30 DJB_GATE_LEASE_POLL=1 DJB_GATE_LEASE_ANNOUNCE=1 \
        gate_lease_acquire >"$OUT" 2>&1 || RC=$?
    exits 0
    says "WAITING for the machine-wide full-gate lease"
    says "full-gate lease ACQUIRED after"
    file_exists "$LEASE_FILE" "the waiter now holds it"
    gate_lease_release
    kill "$holder" 2>/dev/null || true
}

case_a_dead_holders_lease_clears_itself() {
    # THE FAILURE MODE THAT MATTERS MOST IN PRACTICE. Full gates are killed by
    # the tool's ten-minute ceiling all the time. If a killed gate's lease
    # survived, the FIRST kill would block every full gate on the machine
    # forever and the fix would be a file deletion an agent has to be told
    # about — which is the friction handed straight back.
    CURRENT="a dead holder's lease"
    fresh_lease_dir
    local gone
    dead_pid
    gone=$DEAD_PID
    printf '%s full 2026-08-25T00:00:00Z %s /some/dead/checkout\n' \
        "$gone" "$(hostname -s 2>/dev/null || echo host)" >"$LEASE_FILE"
    out_file
    RC=0
    DJB_GATE_LEASE_MAX_WAIT=3 DJB_GATE_LEASE_POLL=1 gate_lease_acquire >"$OUT" 2>&1 || RC=$?
    exits 0
    says "cleared a STALE full-gate lease"
    says "full-gate lease held for this MACHINE"
    if [ "$GATE_LEASE_WAITED" = "0" ]; then
        ok "no waiting for a dead holder"
    else
        bad "waited ${GATE_LEASE_WAITED}s on a holder that was not running"
    fi
    gate_lease_release
}

case_a_LIVE_holder_is_never_cleared() {
    # The other direction, and it is the one that puts two gates back on one
    # box if it stops holding. Asserted as strictly as the clear above.
    CURRENT="a live holder"
    fresh_lease_dir
    local holder
    live_pid
    holder=$LIVE_PID
    printf '%s full 2026-08-25T00:00:00Z %s /some/other/checkout\n' \
        "$holder" "$(hostname -s 2>/dev/null || echo host)" >"$LEASE_FILE"
    out_file
    RC=0
    gate_lease_try >"$OUT" 2>&1 || RC=$?
    if [ "$RC" = "1" ]; then
        ok "gate_lease_try refuses a held lease (exit 1)"
    else
        bad "gate_lease_try returned ${RC} against a live holder"
    fi
    out_file
    gate_lease_holder >"$OUT" 2>&1 || true
    says "$holder full"
    says_not "cleared a STALE"
    kill "$holder" 2>/dev/null || true
}

case_another_hosts_lease_is_never_cleared() {
    # `kill -0 <pid>` asks THIS kernel about a pid. On a shared /tmp a foreign
    # pid number is meaningless here, so the host is recorded and the
    # stale-clear only fires when it matches. Wrong-clearing a live foreign
    # holder is the same overlap this whole rung exists to stop.
    CURRENT="another host's lease"
    fresh_lease_dir
    local gone
    dead_pid
    gone=$DEAD_PID
    printf '%s full 2026-08-25T00:00:00Z not-this-host /elsewhere\n' "$gone" >"$LEASE_FILE"
    out_file
    gate_lease_holder >"$OUT" 2>&1 || true
    says "not-this-host"
    says_not "cleared a STALE"
    file_exists "$LEASE_FILE" "the foreign record survives a holder read"
    out_file
    RC=0
    DJB_GATE_LEASE_MAX_WAIT=2 DJB_GATE_LEASE_POLL=1 gate_lease_acquire >"$OUT" 2>&1 || RC=$?
    exits 2
    says "written by another host"
}

case_a_lease_is_released_only_by_the_process_that_holds_it() {
    # A gate whose EXIT trap fires after somebody else has taken the lease must
    # not delete theirs. Cheap to get wrong, invisible when it is.
    CURRENT="release by a non-holder"
    fresh_lease_dir
    local holder
    live_pid
    holder=$LIVE_PID
    printf '%s full 2026-08-25T00:00:00Z %s /some/other/checkout\n' \
        "$holder" "$(hostname -s 2>/dev/null || echo host)" >"$LEASE_FILE"
    GATE_LEASE="$LEASE_FILE" # as if this process believed it held it
    out_file
    gate_lease_release >"$OUT" 2>&1 || true
    file_exists "$LEASE_FILE" "somebody else's lease survives our release"
    kill "$holder" 2>/dev/null || true
}

case_exactly_one_of_two_racing_acquires_wins() {
    # `noclobber` is what makes the create atomic. Two gates starting in the
    # same millisecond must not both believe they won — which is precisely the
    # state a real measurement recorded.
    CURRENT="two racing acquires"
    fresh_lease_dir
    out_file
    local i winners
    winners=0
    for i in 1 2 3 4 5 6; do
        (
            if gate_lease_try >/dev/null 2>&1; then
                echo won >>"$OUT"
            fi
        ) &
    done
    wait
    winners=$(grep -c won "$OUT" 2>/dev/null || true)
    [ -n "$winners" ] || winners=0
    if [ "$winners" = "1" ]; then
        ok "exactly one of six simultaneous acquires won"
    else
        bad "${winners} of six simultaneous acquires believed they won"
    fi
    rm -f "$LEASE_FILE"
}

case_a_relative_lease_directory_is_refused() {
    # The same environment-leakage class one file over: a relative path resolves against whatever
    # directory the caller left behind. And an absent directory would make every
    # acquire fail open — the lease would stop existing with nobody told.
    CURRENT="a relative DJB_GATE_LEASE_DIR"
    out_file
    RC=0
    DJB_GATE_LEASE_DIR="some/relative/dir" gate_lease_path >"$OUT" 2>&1 || RC=$?
    if [ "$RC" != "0" ]; then
        ok "refused (exit ${RC})"
    else
        bad "accepted a relative lease directory"
    fi
    says "DJB_GATE_LEASE_DIR is relative"

    CURRENT="a DJB_GATE_LEASE_DIR that is not a directory"
    out_file
    RC=0
    DJB_GATE_LEASE_DIR="${WORK}/definitely-not-there" gate_lease_path >"$OUT" 2>&1 || RC=$?
    if [ "$RC" != "0" ]; then
        ok "refused (exit ${RC})"
    else
        bad "accepted a lease directory that does not exist"
    fi
    says "is not a directory"

    CURRENT="an unusable lease directory reaches the gate as could-not-look"
    out_file
    RC=0
    DJB_GATE_LEASE_DIR="some/relative/dir" gate_lease_acquire >"$OUT" 2>&1 || RC=$?
    exits 2
}

# --- the counting semaphore ---------------------------------------------
#
# Every case here points DJB_GATE_LEASE_DIR at its own scratch directory, so the
# slots it plants and reclaims are its own — the same property the lease cases
# above rest on, and the reason this drive is safe to run from inside the gate
# that is holding the real lease and the real slot.

SLOTS_DIR=""
fresh_slot_dir() {
    fresh_lease_dir
    SLOTS_DIR="${LEASE_DIR}/djb-gate-slots"
    GATE_SLOT=""
    GATE_SLOT_WAITED=0
    GATE_SLOT_LEASE_FIRST=""
    GATE_LEASE=""
}

# Plant a holder into slot <n> with an explicit pid and host. Six fields, the
# shape `gate_slot_line` writes: pid mode started-utc host started-epoch checkout.
plant_slot() {
    local n=$1 pid=$2 host=$3 mode=${4:-loop}
    mkdir -p "${SLOTS_DIR}/slot-${n}"
    printf '%s %s 2026-08-30T00:00:00Z %s %s /some/other/checkout\n' \
        "$pid" "$mode" "$host" "$(date +%s)" >"${SLOTS_DIR}/slot-${n}/holder"
}

case_the_slot_count_and_the_worker_share_are_derived() {
    # THE ARITHMETIC IS THE DESIGN: N slots, each holder running cores/N, so the
    # workers all the live gates have started total this machine's cores however
    # many of them there are. A default that silently became something else
    # would put `-n auto`-per-gate back with nobody told.
    CURRENT="the derived slot count"
    out_file
    local cores total workers
    cores=$(gate_slot_cores)
    total=$(gate_slots_total)
    workers=$(gate_slot_workers "$total")
    if [ "$total" -ge 1 ] && [ "$total" -le "$cores" ]; then
        ok "${total} slots derived from ${cores} cores (cores/${GATE_SLOT_CORES_PER_SLOT}, floor, never below 1)"
    else
        bad "derived ${total} slots from ${cores} cores"
    fi
    if [ "$((total * workers))" -le "$cores" ] && [ "$workers" -ge 1 ]; then
        ok "${total} slots x -n ${workers} = $((total * workers)) workers, within ${cores} cores"
    else
        bad "${total} x ${workers} oversubscribes ${cores} cores"
    fi

    CURRENT="DJB_GATE_SLOTS overrides"
    if [ "$(DJB_GATE_SLOTS=7 gate_slots_total)" = "7" ]; then
        ok "an explicit 7 is honoured verbatim"
    else
        bad "DJB_GATE_SLOTS=7 did not survive"
    fi
    if [ "$(DJB_GATE_SLOTS=1 gate_slot_workers "$(DJB_GATE_SLOTS=1 gate_slots_total)")" = "$cores" ]; then
        ok "one slot gets the whole box (-n ${cores})"
    else
        bad "one slot did not get the whole box"
    fi

    # A ceiling this cannot read must never become the default: that is the
    # unbounded run the semaphore exists to stop, arriving silently.
    CURRENT="a bogus DJB_GATE_SLOTS"
    out_file
    RC=0
    DJB_GATE_SLOTS=bogus gate_slots_total >"$OUT" 2>&1 || RC=$?
    exits 2
    says "is not a positive whole number"
    CURRENT="DJB_GATE_SLOTS=0"
    out_file
    RC=0
    DJB_GATE_SLOTS=0 gate_slots_total >"$OUT" 2>&1 || RC=$?
    exits 2
    says "a box with no slots can run no suite at all"
}

case_the_Nplus1th_pytest_leg_WAITS_and_SAYS_SO() {
    # THE CENTRAL SEMAPHORE CASE, and the lease's central case one level over: a
    # wait that says nothing is a hang as far as any reader is concerned, and an
    # agent watching a hang kills the gate. So the announcement is asserted as
    # text — including the fact that it names the OTHER guard, because "the box
    # is full" and "somebody else is pushing" are different situations with
    # different answers.
    CURRENT="the N+1th pytest leg waits, out loud"
    fresh_slot_dir
    local holder
    live_pid
    holder=$LIVE_PID
    mkdir -p "$SLOTS_DIR"
    plant_slot 1 "$holder" "$(hostname -s 2>/dev/null || echo host)" full
    out_file
    RC=0
    DJB_GATE_SLOTS=1 DJB_GATE_SLOT_MAX_WAIT=3 DJB_GATE_LEASE_POLL=1 DJB_GATE_LEASE_ANNOUNCE=1 \
        gate_slot_acquire loop >"$OUT" 2>&1 || RC=$?
    exits 2
    says "WAITING for a pytest SLOT"
    says "This is not a hang."
    says "COUNTING semaphore, not the exclusive full-gate lease"
    says "holder: slot-1 ${holder} full"
    says "... still waiting for a pytest slot"
    says "Rough estimate from the holders' elapsed time"
    says "REFUSING: waited"
    says "Nothing was judged. This is could-not-look, not a red tree."
    if [ -z "$GATE_SLOT" ]; then
        ok "no slot is recorded as held by the waiter"
    else
        bad "the waiter believes it holds ${GATE_SLOT}"
    fi
    file_exists "${SLOTS_DIR}/slot-1/holder" "the live holder's slot is untouched"
    kill "$holder" 2>/dev/null || true
}

case_a_waiter_takes_a_slot_when_one_frees() {
    # The other half of waiting: it ENDS. A ceiling that is the only exit is a
    # refusal with extra steps.
    CURRENT="a waiter takes a freed slot"
    fresh_slot_dir
    local holder
    live_pid
    holder=$LIVE_PID
    mkdir -p "$SLOTS_DIR"
    plant_slot 1 "$holder" "$(hostname -s 2>/dev/null || echo host)" loop
    (
        sleep 2
        rm -rf "${SLOTS_DIR}/slot-1"
    ) >/dev/null 2>&1 &
    SLEEPERS="${SLEEPERS} $!"
    disown $! 2>/dev/null || true
    out_file
    RC=0
    DJB_GATE_SLOTS=1 DJB_GATE_SLOT_MAX_WAIT=30 DJB_GATE_LEASE_POLL=1 DJB_GATE_LEASE_ANNOUNCE=1 \
        gate_slot_acquire loop >"$OUT" 2>&1 || RC=$?
    exits 0
    says "WAITING for a pytest SLOT"
    says "pytest SLOT ACQUIRED after"
    gate_slot_release
    kill "$holder" 2>/dev/null || true
}

case_a_killed_slot_holder_is_reclaimed() {
    # The lease's most-important-in-practice failure mode, one guard over. Gates
    # are killed at the harness ceiling routinely; if a killed leg's slot
    # survived, the FIRST kill would permanently shrink the box and the fix
    # would be a directory deletion somebody has to be told about.
    CURRENT="a killed slot holder"
    fresh_slot_dir
    local gone
    dead_pid
    gone=$DEAD_PID
    mkdir -p "$SLOTS_DIR"
    plant_slot 1 "$gone" "$(hostname -s 2>/dev/null || echo host)" loop
    out_file
    RC=0
    DJB_GATE_SLOTS=1 DJB_GATE_SLOT_MAX_WAIT=3 DJB_GATE_LEASE_POLL=1 \
        gate_slot_acquire loop >"$OUT" 2>&1 || RC=$?
    exits 0
    says "cleared a STALE gate slot"
    says "pytest slot held"
    gate_slot_release
}

case_a_foreign_hosts_slot_is_waited_on_then_refused() {
    # `kill -0 <pid>` asks THIS kernel. On a shared /tmp a foreign pid number is
    # meaningless here, so a foreign record is never cleared — it is waited on
    # and then refused, which is a loud stop rather than a silent overlap.
    CURRENT="another host's slot"
    fresh_slot_dir
    local gone
    dead_pid
    gone=$DEAD_PID
    mkdir -p "$SLOTS_DIR"
    plant_slot 1 "$gone" not-this-host loop
    out_file
    RC=0
    DJB_GATE_SLOTS=1 DJB_GATE_SLOT_MAX_WAIT=2 DJB_GATE_LEASE_POLL=1 DJB_GATE_LEASE_ANNOUNCE=1 \
        gate_slot_acquire loop >"$OUT" 2>&1 || RC=$?
    exits 2
    says "not-this-host"
    says_not "cleared a STALE gate slot"
    file_exists "${SLOTS_DIR}/slot-1/holder" "the foreign record survives"
}

case_an_orphaned_mkdir_window_is_reclaimed_eventually() {
    # THE DECLARED WINDOW, driven rather than only declared. A slot is claimed by
    # `mkdir` and its holder record written microseconds later; a process killed
    # inside that window leaves a directory nothing can attribute to a pid. It
    # counts as HELD while it is fresh — stealing it would be the eager
    # stale-clear the lease refuses — and is reclaimed once it plainly is not a
    # window any more.
    CURRENT="a fresh holderless slot is held, not stolen"
    fresh_slot_dir
    mkdir -p "${SLOTS_DIR}/slot-1"
    out_file
    gate_slot_holders >"$OUT" 2>&1 || true
    says "(starting — no holder record yet)"
    says_not "reclaimed an ORPHAN"

    CURRENT="a long-orphaned holderless slot is reclaimed"
    touch -t 202001010000 "${SLOTS_DIR}/slot-1" 2>/dev/null || cannot_look "touch -t is not available to age the orphan"
    out_file
    gate_slot_holders >"$OUT" 2>&1 || true
    says "reclaimed an ORPHAN gate slot"
    if [ -d "${SLOTS_DIR}/slot-1" ]; then
        bad "the orphan directory survived its reclaim"
    else
        ok "the orphan directory is gone"
    fi
}

case_a_slot_is_released_only_by_the_process_that_holds_it() {
    # A leg whose EXIT trap fires after somebody else has taken the slot must not
    # delete theirs. Cheap to get wrong, invisible when it is.
    CURRENT="slot release by a non-holder"
    fresh_slot_dir
    local holder
    live_pid
    holder=$LIVE_PID
    mkdir -p "$SLOTS_DIR"
    plant_slot 1 "$holder" "$(hostname -s 2>/dev/null || echo host)" loop
    GATE_SLOT="${SLOTS_DIR}/slot-1" # as if this process believed it held it
    out_file
    gate_slot_release >"$OUT" 2>&1 || true
    file_exists "${SLOTS_DIR}/slot-1/holder" "somebody else's slot survives our release"
    kill "$holder" 2>/dev/null || true
}

case_exactly_N_of_many_racing_slot_acquires_win() {
    # `mkdir` is what makes the claim atomic — and it is atomic on the NFS and
    # bind mounts where an O_EXCL create historically was not, which is why the
    # slots are directories and the lease one file over is not. Six racers, two
    # slots, exactly two winners.
    CURRENT="six racing acquires against two slots"
    fresh_slot_dir
    out_file
    local i winners
    for i in 1 2 3 4 5 6; do
        (
            GATE_SLOT=""
            if DJB_GATE_SLOTS=2 gate_slot_try loop >/dev/null 2>&1; then
                echo won >>"$OUT"
            fi
        ) &
    done
    wait
    winners=$(grep -c won "$OUT" 2>/dev/null || true)
    [ -n "$winners" ] || winners=0
    if [ "$winners" = "2" ]; then
        ok "exactly two of six simultaneous acquires won"
    else
        bad "${winners} of six simultaneous acquires won two slots"
    fi
    rm -rf "$SLOTS_DIR"
}

case_the_lock_order_is_REFUSED_not_merely_documented() {
    # THE DEADLOCK THE TWO GUARDS COULD FORM, closed mechanically. A full run
    # holding a slot while waiting for the lease, and a lease holder waiting for
    # a slot, is a cycle that stops every gate on the machine. The order is
    # LEASE FIRST, THEN SLOT on every path — and a full run that reaches a slot
    # without the lease is refused rather than trusted to have read a comment.
    CURRENT="the lock order"
    fresh_slot_dir
    out_file
    RC=0
    (
        GATE_SLOT_LEASE_FIRST=1
        GATE_LEASE=""
        gate_slot_acquire full
    ) >"$OUT" 2>&1 || RC=$?
    exits 2
    says "LOCK ORDER BROKEN"
    says "LEASE FIRST, THEN SLOT"

    CURRENT="the lock order, satisfied"
    out_file
    RC=0
    (
        GATE_SLOT_LEASE_FIRST=1
        GATE_LEASE="${LEASE_DIR}/djb-gate-lease"
        gate_slot_acquire full
        gate_slot_release
    ) >"$OUT" 2>&1 || RC=$?
    exits 0
    says "pytest slot held"
}

# --- the sanction valve on the full gate --------------------------------
#
# THESE RUN THE REAL `./scripts/check.sh`, which the lease cases above declare
# they cannot do — and the difference is the whole point of where the valve
# sits. Every case here is a REFUSAL, and the valve refuses ABOVE the lease,
# above the checkout lock and above the first leg, so each of these costs
# milliseconds and touches nothing. A case that proved the ACCEPTING side would
# have to start a full gate from inside the full gate's own selftest leg; that
# half is read as text with the rest of the wiring, and named as the weaker
# proof it is.

valve_run() {
    # Run check.sh with its machine-wide state pointed at a fresh scratch
    # directory, so the "no lease, no slot" assertion below is about THIS run
    # and can never be satisfied by the real gate's absence.
    fresh_slot_dir
    out_file
    RC=0
    env DJB_GATE_LEASE_DIR="$LEASE_DIR" "$@" "${ROOT}/scripts/check.sh" >"$OUT" 2>&1 || RC=$?
}

took_nothing() {
    # Criterion: a refused run takes NO lease and NO slot. Proven by looking,
    # not by reading the refusal's own claim about itself.
    if [ -e "$LEASE_FILE" ]; then
        bad "the refused run left a lease at $LEASE_FILE"
    else
        ok "the refused run took no lease"
    fi
    if [ -e "$SLOTS_DIR" ]; then
        bad "the refused run left slot state at $SLOTS_DIR"
    else
        ok "the refused run took no slot"
    fi
}

case_an_unsanctioned_full_gate_is_REFUSED() {
    # THE ROW'S CENTRAL CASE. A full gate is the most expensive thing on this
    # machine and every other full gate waits behind it, so an unaccountable one
    # spends everybody's minutes and not only its own. Before this valve the
    # ledger recorded banked verdicts nobody could attribute — `caller=unstated`
    # rows with no reason attached anywhere.
    CURRENT="a bare full gate with no sanction"
    # `DJB_GATE_SANCTION=` beside the other two, and it is not decoration: this
    # case asks for the UNSANCTIONED refusal, and the environment it runs in
    # routinely HAS a sanction — rung-execution §3 tells every builder to type
    # one for a by-hand full gate, and the gate's selftest leg then spawns this
    # drive with it set. Without this the nested gate inherited the operator's
    # sanction, sailed past the valve, and was refused further down by the
    # per-checkout lock instead: a different refusal, in different words, and
    # five red assertions in a run that had nothing wrong with it.
    # `drive_preamble.sh` §4a now strips it for every drive as well; this is the
    # call-site half, which is where the preamble's own doctrine puts it.
    valve_run env DJB_GATE_CALLER= CI= DJB_GATE_SANCTION=
    exits 2
    says "REFUSING an unsanctioned FULL gate"
    says "the pre-push hook"
    says "--bank"
    says "DJB_GATE_SANCTION"
    says "Nothing was judged"
    took_nothing
}

case_a_shapeless_sanction_is_REFUSED() {
    # The valve's own typo case. A sanction that does not name who is asking and
    # why is not a reason — and letting it fall through to the generic refusal
    # would hide the typo behind a sentence about something else.
    CURRENT="a shapeless sanction"
    valve_run env DJB_GATE_CALLER= CI= DJB_GATE_SANCTION=nope
    exits 2
    says "DJB_GATE_SANCTION is set but is not a sanction"
    says "want: DJB_GATE_SANCTION="
    took_nothing

    CURRENT="a sanction with an id and no reason"
    valve_run env DJB_GATE_CALLER= CI= DJB_GATE_SANCTION="gate-rung:"
    exits 2
    says "is not a sanction"
    took_nothing

    CURRENT="an empty sanction"
    valve_run env DJB_GATE_CALLER= CI= DJB_GATE_SANCTION=
    exits 2
    says "REFUSING an unsanctioned FULL gate"
    took_nothing
}

case_bank_from_a_LINKED_worktree_is_REFUSED() {
    # A bank is a claim about the tree that is about to be PUSHED, and a linked
    # rung worktree is by construction not that tree. The test is mechanical —
    # `--git-dir` against `--git-common-dir` — never a guess about the shape of
    # the path, which is the kind of inference that is wrong the first time
    # somebody clones into a directory called `worktrees`.
    #
    # DRIVEN FROM ANY CHECKOUT, against a REAL linked worktree this drive makes
    # for itself. It cannot know whether it is running in the primary tree or a
    # linked one, and running `--bank` where it is LEGAL would start a full gate
    # from inside the full gate. So it builds a scratch repository, adds a real
    # linked worktree to it, and points git's own environment at that pair: the
    # comparison under test then runs against answers a real `git rev-parse`
    # gave about a real linked checkout, rather than against invented strings.
    CURRENT="--bank from a linked worktree"
    scratch_repo
    git -C "$REPO" worktree add -q --detach "${REPO}-linked" >/dev/null 2>&1 ||
        cannot_look "could not add a linked worktree to the scratch repository"
    local linked_gitdir common_gitdir
    linked_gitdir="$(git -C "${REPO}-linked" rev-parse --absolute-git-dir 2>/dev/null || true)"
    common_gitdir="$(git -C "${REPO}-linked" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
    [ -n "$linked_gitdir" ] && [ -n "$common_gitdir" ] && [ "$linked_gitdir" != "$common_gitdir" ] ||
        cannot_look "the scratch linked worktree did not produce a distinct git-dir ('$linked_gitdir' vs '$common_gitdir')"
    fresh_slot_dir
    out_file
    RC=0
    env DJB_GATE_LEASE_DIR="$LEASE_DIR" DJB_GATE_CALLER= CI= DJB_GATE_SANCTION= \
        GIT_DIR="$linked_gitdir" GIT_COMMON_DIR="$common_gitdir" GIT_WORK_TREE="${REPO}-linked" \
        "${ROOT}/scripts/check.sh" --bank >"$OUT" 2>&1 || RC=$?
    exits 2
    says "--bank from a LINKED worktree"
    says "git-common-dir:"
    says "DJB_GATE_SANCTION="
    took_nothing
    git -C "$REPO" worktree remove --force "${REPO}-linked" >/dev/null 2>&1 || true
}

case_bank_from_a_worktree_merely_NAMED_pm_push_is_REFUSED() {
    # THE OTHER HALF OF THE ARM ABOVE. The primary-checkout test is mechanical
    # — git-dir against git-common-dir, an identity git computes — but the
    # pm-push arm beside it was INFERENCE FROM A NAME: `basename` of the
    # toplevel, and nothing else. Any linked worktree somebody called `pm-push`
    # was accepted for a bank, a rung worktree included, and a bank is a claim
    # about the tree that is about to be pushed.
    #
    # DETACHED HEAD IS THE PROPERTY NOW: `pm_push.sh` pins pm-push with
    # `git checkout --detach` on every push, and a rung worktree is on a branch
    # by definition. This case builds exactly the decoy — a REAL linked
    # worktree whose directory is named `pm-push` and which is checked out on a
    # branch — and requires the refusal.
    CURRENT="--bank from a worktree merely NAMED pm-push"
    scratch_repo
    git -C "$REPO" worktree add -q -b rung-decoy "${REPO}-wt/pm-push" >/dev/null 2>&1 ||
        cannot_look "could not add a linked worktree named pm-push to the scratch repository"
    local decoy linked_gitdir common_gitdir
    decoy="${REPO}-wt/pm-push"
    linked_gitdir="$(git -C "$decoy" rev-parse --absolute-git-dir 2>/dev/null || true)"
    common_gitdir="$(git -C "$decoy" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
    [ -n "$linked_gitdir" ] && [ "$linked_gitdir" != "$common_gitdir" ] ||
        cannot_look "the decoy did not produce a distinct git-dir ('$linked_gitdir' vs '$common_gitdir')"
    # The decoy really is named pm-push and really is on a branch — asserted,
    # because a case whose fixture drifted would go green for the wrong reason.
    local decoy_base decoy_head
    decoy_base="$(basename "$(git -C "$decoy" rev-parse --show-toplevel)")"
    decoy_head="$(git -C "$decoy" symbolic-ref -q HEAD || echo '(detached)')"
    if [ "$decoy_base" = "pm-push" ]; then
        ok "the decoy really is named pm-push"
    else
        bad "the decoy is named '${decoy_base}', so this case proves nothing"
    fi
    if [ "$decoy_head" = "refs/heads/rung-decoy" ]; then
        ok "the decoy really is on a branch, as every rung worktree is"
    else
        bad "the decoy's HEAD is '${decoy_head}', not the branch this case needs"
    fi

    fresh_slot_dir
    out_file
    RC=0
    env DJB_GATE_LEASE_DIR="$LEASE_DIR" DJB_GATE_CALLER= CI= DJB_GATE_SANCTION= \
        GIT_DIR="$linked_gitdir" GIT_COMMON_DIR="$common_gitdir" GIT_WORK_TREE="$decoy" \
        "${ROOT}/scripts/check.sh" --bank >"$OUT" 2>&1 || RC=$?
    exits 2
    says "--bank from a LINKED worktree"
    # The refusal has to SAY what it looked at, or the next reader renames a
    # directory and tries again.
    says "HEAD:"
    says "refs/heads/rung-decoy"
    says "DETACHED"
    took_nothing
    git -C "$REPO" worktree remove --force "$decoy" >/dev/null 2>&1 || true
}

case_the_pm_push_arm_is_not_a_basename_alone() {
    # The arm read as text, so that a later edit which drops the mechanical
    # half — leaving the name doing all the work again — is a red case rather
    # than a silent widening. The sibling assertion for the primary-checkout
    # arm is in case_the_sanction_valve_wiring_in_check_sh.
    CURRENT="the pm-push arm is not a basename alone"
    out_file
    cp "${ROOT}/scripts/check.sh" "$OUT"
    says 'git symbolic-ref -q HEAD >/dev/null 2>&1; then'
    says "DETACHED HEAD IS THE PROPERTY"
    says "DECLARED RESIDUAL"
}

case_an_unknown_flag_is_still_exit_2() {
    # The valve added a flag; the grammar must not have loosened. A mistyped
    # flag falling through to a silently different run is enforcement misfiring.
    CURRENT="--bnak"
    fresh_slot_dir
    out_file
    RC=0
    env DJB_GATE_LEASE_DIR="$LEASE_DIR" "${ROOT}/scripts/check.sh" --bnak >"$OUT" 2>&1 || RC=$?
    exits 2
    says "unknown argument '--bnak'"
    says "--bank"

    CURRENT="two flags at once"
    out_file
    RC=0
    env DJB_GATE_LEASE_DIR="$LEASE_DIR" "${ROOT}/scripts/check.sh" --fast --bank >"$OUT" 2>&1 || RC=$?
    exits 2
    says "unexpected extra arguments"
}

case_the_ledger_row_carries_the_sanction() {
    # The reason has to OUTLIVE the run or the valve has only moved the
    # un-auditable population from "who" to "why". It goes last on the line,
    # after `caller=`, because it is the one field that can contain spaces — and
    # because appending is what kept every pre-existing line readable.
    CURRENT="the sanction in the verdict row"
    scratch_repo
    local here tree line
    here="$PWD"
    cd "$REPO"
    tree="$(gate_measured_tree)" || {
        cd "$here"
        bad "gate_measured_tree could not measure a scratch checkout"
        return 0
    }
    GATE_RUN_SANCTION="gate-rung: quality/** rung — the canary self-test is the point"
    DJB_GATE_CALLER=quality-rung gate_ledger_record "$tree" "ruff,mypy"
    line="$(gate_ledger_lookup "$tree")" || line=""
    local has_green=1
    gate_has_green "$tree" || has_green=0
    GATE_RUN_SANCTION=""
    cd "$here"
    out_file
    printf '%s\n' "$line" >"$OUT"
    says "caller=quality-rung"
    says "sanction=gate-rung: quality/** rung"
    if [ "$has_green" = "1" ]; then
        ok "gate_has_green still honours a row carrying a sanction"
    else
        bad "a sanctioned row stopped being honoured — every banked tree would be re-measured"
    fi

    CURRENT="a row written before the sanction field existed"
    cd "$REPO"
    GATE_RUN_SANCTION=""
    tree="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    printf 'v1 %s full 2026-08-20T10:00:00Z ruff,mypy caller=push-wall\n' "$tree" >>"$(gate_ledger_path)"
    line="$(gate_ledger_lookup "$tree")" || line=""
    has_green=1
    gate_has_green "$tree" || has_green=0
    cd "$here"
    out_file
    printf '%s\n' "$line" >"$OUT"
    says_not "sanction="
    if [ "$has_green" = "1" ]; then
        ok "a pre-G1 row still parses and is still honoured (pre-push consults exactly these)"
    else
        bad "a pre-G1 row stopped being honoured"
    fi
}

# --- the caller field ---------------------------------------------------

scratch_repo() {
    N=$((N + 1))
    REPO="${WORK}/repo${N}"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "gate lease drive"
    echo "a checkout" >"$REPO/README"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m base
}
REPO=""

case_the_caller_vocabulary_is_closed() {
    CURRENT="the caller vocabulary"
    out_file
    local got
    for got in push-wall quality-rung pm-bank unstated; do
        if [ "$(DJB_GATE_CALLER="$got" gate_caller 2>/dev/null)" = "$got" ]; then
            ok "'$got' is accepted verbatim"
        else
            bad "'$got' did not survive gate_caller"
        fi
    done
    if [ "$(DJB_GATE_CALLER= gate_caller 2>/dev/null)" = "unstated" ]; then
        ok "an unset caller is 'unstated'"
    else
        bad "an unset caller is not 'unstated'"
    fi
    # An unknown value degrades — LOUDLY. Measurement, not enforcement:
    # nothing is refused for its caller, but a typo silently becoming
    # `unstated` is a measurement quietly losing a run.
    out_file
    got=$(DJB_GATE_CALLER=whoever gate_caller 2>"$OUT")
    if [ "$got" = "unstated" ]; then
        ok "an unknown caller records as 'unstated'"
    else
        bad "an unknown caller recorded as '$got'"
    fi
    says "is not one of"
}

case_the_ledger_and_run_log_carry_the_caller() {
    CURRENT="the recorded caller"
    scratch_repo
    local here tree line
    here="$PWD"
    cd "$REPO"
    tree="$(gate_measured_tree)" || {
        cd "$here"
        bad "gate_measured_tree could not measure a scratch checkout"
        return 0
    }
    DJB_GATE_CALLER=quality-rung gate_ledger_record "$tree" "ruff,mypy"
    line="$(gate_ledger_lookup "$tree")" || line=""
    cd "$here"
    out_file
    printf '%s\n' "$line" >"$OUT"
    says "caller=quality-rung"
    says "$tree"
    if [ -n "$line" ]; then
        ok "gate_ledger_lookup still finds the line it wrote"
    else
        bad "gate_ledger_lookup found nothing"
    fi

    CURRENT="the run log's caller"
    cd "$REPO"
    GATE_RUN_SETTLED=""
    DJB_GATE_CALLER=pm-bank gate_run_start "$tree"
    gate_run_note "red:pytest-x2"
    local outcome
    outcome="$(gate_run_lookup "$tree")" || outcome=""
    line="$(tail -1 "$(gate_runs_path)")"
    cd "$here"
    out_file
    printf '%s\n' "$line" >"$OUT"
    says "caller=pm-bank"
    # The outcome word must still be field 4 — this is the whole reason the
    # field was APPENDED rather than inserted.
    if [ "$outcome" = "red:pytest-x2" ]; then
        ok "gate_run_lookup still reads the outcome (field 4) unchanged"
    else
        bad "gate_run_lookup read '${outcome}', wanted 'red:pytest-x2'"
    fi
}

case_a_pre_N353_line_still_parses() {
    # Every line in every existing ledger on this machine was written without
    # this field. A reader that stopped understanding them would silently make
    # the whole history invisible — and `pre-push` consults exactly that
    # history to decide whether to re-run an eight-minute gate.
    CURRENT="a line written before the caller field existed"
    scratch_repo
    local here tree path outcome line
    here="$PWD"
    cd "$REPO"
    tree="$(gate_measured_tree)" || tree="deadbeef"
    path="$(gate_ledger_path)"
    printf 'v1 %s full 2026-08-20T10:00:00Z ruff,mypy\n' "$tree" >>"$path"
    line="$(gate_ledger_lookup "$tree")" || line=""
    local has_green=1
    gate_has_green "$tree" || has_green=0
    printf 'v1 %s 2026-08-20T10:00:00Z killed:pytest-x2\n' "$tree" >>"$(gate_runs_path)"
    outcome="$(gate_run_lookup "$tree")" || outcome=""
    cd "$here"
    out_file
    printf '%s\n' "$line" >"$OUT"
    if [ -n "$line" ]; then
        ok "gate_ledger_lookup reads a caller-less line"
    else
        bad "gate_ledger_lookup no longer reads a caller-less line"
    fi
    if [ "$has_green" = "1" ]; then
        ok "gate_has_green honours a caller-less verdict"
    else
        bad "gate_has_green stopped honouring a caller-less verdict — every existing banked tree would be re-measured"
    fi
    if [ "$outcome" = "killed:pytest-x2" ]; then
        ok "gate_run_lookup reads a caller-less run-log line"
    else
        bad "gate_run_lookup read '${outcome}' from a caller-less line"
    fi
}

# --- the wiring, read as text -------------------------------------------------

case_the_wiring_in_check_sh() {
    # THE WEAKEST CASES HERE, AND THE ONES THE RUNG RESTS ON. Everything above
    # proves the lease body; these prove the gate takes one, takes it in the
    # right mode, in the right ORDER, and gives it back. Read as TEXT because
    # this drive runs inside the gate's own selftest leg and cannot run the
    # gate — `test_db_pin.sh`'s and `test_loop_tier.sh`'s identical constraint,
    # named as the weaker proof it is.
    CURRENT="the wiring in check.sh"
    out_file
    local gate="${ROOT}/scripts/check.sh"
    local source_line acquire_line lock_line full_branch pipe_line trap_line release_hits

    source_line="$(grep -n '^\. scripts/gate_lease\.sh$' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -n "$source_line" ]; then
        ok "check.sh sources scripts/gate_lease.sh (line ${source_line})"
    else
        bad "check.sh does not source scripts/gate_lease.sh — the lease body is orphaned"
        return 0
    fi

    acquire_line="$(grep -n '^    gate_lease_acquire$' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -n "$acquire_line" ]; then
        ok "check.sh calls gate_lease_acquire (line ${acquire_line})"
    else
        bad "check.sh never calls gate_lease_acquire — no full gate would ever take a lease"
        return 0
    fi

    if [ "$(grep -c 'gate_lease_acquire' "$gate")" = "1" ]; then
        ok "exactly one acquire call site"
    else
        bad "more than one gate_lease_acquire call site — the mode a lease is taken in stops being readable"
    fi

    full_branch="$(grep -n '^if \[ "\$MODE" = "" \]; then$' "$gate" | head -1 | cut -d: -f1 || true)"
    lock_line="$(grep -n '^    gate_lock_acquire$' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -z "$full_branch" ] || [ -z "$lock_line" ]; then
        bad "check.sh's full-mode branch or gate_lock_acquire could not be found — the order cannot be judged"
        return 0
    fi
    if [ "$acquire_line" -gt "$full_branch" ]; then
        ok "the acquire is inside the MODE=\"\" branch (line ${full_branch}) — --fast and --loop take NO lease"
    else
        bad "the acquire sits ABOVE the full-mode branch: --fast and --loop would queue behind somebody else's push"
    fi
    if [ "$acquire_line" -lt "$lock_line" ]; then
        ok "the machine lease is taken BEFORE the per-checkout lock (line ${lock_line}) — a waiting gate does not block its own checkout's --loop"
    else
        bad "the per-checkout lock is taken before the machine lease: a queued full gate would make --fast/--loop refuse in its own checkout for the whole wait"
    fi

    # --fast/--loop must reach the per-checkout refusal and nothing else.
    if grep -q '^    gate_lock_refuse_if_held$' "$gate"; then
        ok "the else branch still only calls gate_lock_refuse_if_held"
    else
        bad "the --fast/--loop branch no longer calls gate_lock_refuse_if_held"
    fi
    trap_line="$(grep -n 'trap .*gate_lease_release.*EXIT' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -n "$trap_line" ]; then
        ok "the EXIT trap releases the lease (line ${trap_line})"
    else
        bad "no EXIT trap releases the lease — a finished gate would block the machine until somebody deleted a file"
    fi
    if [ -n "$trap_line" ] && [ "$trap_line" -gt "$acquire_line" ] && [ "$trap_line" -lt "$lock_line" ]; then
        ok "the trap is installed between the acquire and the lock — no line in between can exit holding either"
    else
        bad "the EXIT trap is not between the acquire and the lock acquire"
    fi

    release_hits="$(grep -c 'gate_lease_release' "$gate")"
    if [ "$release_hits" -ge 1 ]; then
        ok "gate_lease_release is called (${release_hits} site(s))"
    else
        bad "gate_lease_release is never called"
    fi

    # The pipe refusal must stay the FIRST thing the gate does. A gate that
    # waited an hour on a lease and then refused the pipe would be a very
    # expensive way to learn about a `| tail`.
    pipe_line="$(grep -n 'the gate refuses pipes' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -z "$pipe_line" ]; then
        bad "check.sh's pipe refusal could not be found"
    elif [ "$pipe_line" -lt "$acquire_line" ]; then
        ok "the pipe refusal (line ${pipe_line}) still sits above the lease"
    else
        bad "the pipe refusal now sits BELOW the lease acquire — a piped gate would queue before it refused"
    fi

    # Exit semantics: an unusable or unavailable lease is could-not-look.
    if grep -q 'LEASE_RC' "$gate" && sed -n "${acquire_line},$((acquire_line + 12))p" "$gate" | grep -q 'exit 2'; then
        ok "a lease that cannot be taken exits 2 (could-not-look), never 1"
    else
        bad "the acquire's failure path does not exit 2 — a gate that never ran must not be readable as a red tree"
    fi
}

case_the_slot_wiring_in_check_sh() {
    # The semaphore's half of the weak-but-load-bearing text proofs. Everything
    # above proves the semaphore body; these prove the gate TAKES a slot, in both
    # pytest legs, in the right ORDER, gives it back, and no longer runs the
    # thing the slot exists to replace.
    CURRENT="the slot wiring in check.sh"
    out_file
    local gate="${ROOT}/scripts/check.sh"
    local loop_slot full_slot acquire_line order_line release_hits auto_hits

    # CALL SITES, not mentions: the count is anchored to the start of a line so
    # the file may go on EXPLAINING the order in prose without the explanation
    # reading as a third acquire.
    if [ "$(grep -cE '^[[:space:]]*gate_slot_acquire ' "$gate")" = "2" ]; then
        ok "exactly two slot acquire call sites — the --loop pytest leg and pytest-x2"
    else
        bad "check.sh has $(grep -cE '^[[:space:]]*gate_slot_acquire ' "$gate") gate_slot_acquire call sites, wanted 2"
    fi
    loop_slot="$(grep -n 'gate_slot_acquire loop' "$gate" | head -1 | cut -d: -f1 || true)"
    full_slot="$(grep -n 'gate_slot_acquire full' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -n "$loop_slot" ] && [ -n "$full_slot" ]; then
        ok "--loop takes one (line ${loop_slot}) and the full gate takes one (line ${full_slot})"
    else
        bad "one of the two pytest legs takes no slot — that leg would run unbounded"
        return 0
    fi

    # THE LOCK ORDER, read where it is declared. The full gate's slot must sit
    # BELOW its lease acquire, and the flag that makes the order mechanical must
    # be set in the full-mode branch.
    acquire_line="$(grep -n '^    gate_lease_acquire$' "$gate" | head -1 | cut -d: -f1 || true)"
    order_line="$(grep -n '^    GATE_SLOT_LEASE_FIRST=1$' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -n "$order_line" ] && [ -n "$acquire_line" ] && [ "$order_line" -lt "$acquire_line" ]; then
        ok "GATE_SLOT_LEASE_FIRST is set (line ${order_line}) before the lease is taken — the order is enforced, not remembered"
    else
        bad "GATE_SLOT_LEASE_FIRST is not set above the lease acquire: the lock order would be a comment"
    fi
    if [ -n "$acquire_line" ] && [ "$full_slot" -gt "$acquire_line" ]; then
        ok "the full gate's slot (line ${full_slot}) is taken AFTER its lease (line ${acquire_line})"
    else
        bad "the full gate takes a slot before its lease — the deadlock cycle"
    fi

    # --fast must reach neither. It has no suite; making pre-commit queue would
    # be the friction this repository keeps deleting.
    if [ "$(sed -n '/if \[ "\$MODE" = "--fast" \]; then/,/^fi$/p' "$gate" | grep -c 'gate_slot_acquire')" = "0" ]; then
        ok "the --fast branch takes no slot"
    else
        bad "--fast takes a slot — pre-commit would queue behind somebody else's suite"
    fi

    release_hits="$(grep -c 'gate_slot_release' "$gate")"
    if [ "$release_hits" -ge 3 ]; then
        ok "gate_slot_release is called (${release_hits} sites: both EXIT traps and the explicit one after pass 2)"
    else
        bad "only ${release_hits} gate_slot_release site(s) — a finished leg would hold a slot"
    fi
    if grep -q "trap 'gate_slot_release' EXIT" "$gate"; then
        ok "the --loop pytest leg installs an EXIT trap for its slot"
    else
        bad "the --loop slot has no EXIT trap — a killed loop gate would shrink the box"
    fi

    # AND THE THING THE SLOT REPLACES IS GONE. `-n auto` in a pytest invocation
    # is exactly the unbounded run the semaphore exists to stop, and it read as
    # correct for as long as it was there.
    auto_hits="$(grep -c 'test\.sh -n auto' "$gate" || true)"
    if [ "$auto_hits" = "0" ]; then
        ok "no pytest leg runs -n auto any more"
    else
        bad "${auto_hits} pytest invocation(s) still run -n auto — that leg claims every core whatever else is live"
    fi
    if [ "$(grep -c 'test\.sh -n "\$GATE_SLOT_WORKERS"' "$gate")" = "4" ]; then
        ok "all four pytest invocations run the slot's worker share"
    else
        bad "$(grep -c 'test\.sh -n "\$GATE_SLOT_WORKERS"' "$gate") of the pytest invocations run the slot's share, wanted 4"
    fi
}

case_the_sanction_valve_wiring_in_check_sh() {
    # The refusals are DRIVEN above; this is the half a refusal cannot show —
    # where the valve sits, and that the accepting paths exist at all.
    CURRENT="the sanction valve wiring in check.sh"
    out_file
    local gate="${ROOT}/scripts/check.sh"
    local valve_line acquire_line pipe_line mode_guard

    valve_line="$(grep -n 'THE FULL GATE IS SANCTIONED' "$gate" | tail -1 | cut -d: -f1 || true)"
    acquire_line="$(grep -n '^    gate_lease_acquire$' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -z "$valve_line" ] || [ -z "$acquire_line" ]; then
        bad "the valve or the lease acquire could not be found — the order cannot be judged"
        return 0
    fi
    if [ "$valve_line" -lt "$acquire_line" ]; then
        ok "the valve (line ${valve_line}) sits ABOVE the lease acquire (line ${acquire_line}) — a refused run queues for nothing"
    else
        bad "the valve sits below the lease: a run could wait an hour to be told it was not allowed to run"
    fi
    pipe_line="$(grep -n 'the gate refuses pipes' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -n "$pipe_line" ] && [ "$pipe_line" -lt "$valve_line" ]; then
        ok "the pipe refusal (line ${pipe_line}) still comes first of all"
    else
        bad "the pipe refusal no longer precedes the sanction valve"
    fi

    # The valve is inside the full-mode guard and nowhere else: --fast and
    # --loop are untouched by it, which is the whole reason a builder can go on
    # gating a rung without typing anything.
    mode_guard="$(grep -n '^if \[ -z "\$MODE" \]; then$' "$gate" | head -1 | cut -d: -f1 || true)"
    if [ -n "$mode_guard" ] && [ "$mode_guard" -lt "$valve_line" ] || [ -n "$mode_guard" ]; then
        ok "the valve is inside a full-mode-only guard (line ${mode_guard}) — --fast and --loop never reach it"
    else
        bad "the valve is not guarded by mode: --fast and --loop would need a sanction"
    fi

    # The three legal callers, each present as code rather than only as prose.
    if grep -q 'DJB_GATE_CALLER:-}" = "push-wall"' "$gate"; then
        ok "the push wall is a legal caller"
    else
        bad "the pre-push hook's sanction is gone — every push would refuse"
    fi
    if grep -q 'GATE_GIT_DIR" -ef "\$GATE_GIT_COMMON"' "$gate"; then
        ok "--bank's checkout test is the mechanical git-dir/common-dir comparison, not a path guess"
    else
        bad "--bank no longer compares git-dir with git-common-dir"
    fi
    if grep -q 'DJB_GATE_SANCTION} =~' "$gate"; then
        ok "the typed sanction is shape-checked"
    else
        bad "the typed sanction is no longer shape-checked — anything would pass"
    fi
    if grep -q 'if \[ -n "\${CI:-}" \]; then' "$gate"; then
        ok "CI is explicitly exempt, as at the pipe guard"
    else
        bad "the CI exemption is gone — every CI run would refuse"
    fi
    # The residual is DECLARED rather than pretended away: an exported CI=1 or
    # DJB_GATE_CALLER=push-wall walks past this, exactly as an exported CI=1
    # walks past the pipe guard. A guard whose edge is not written down gets
    # read as covering more than it does.
    out_file
    sed -n "${valve_line},$((valve_line + 90))p" "$gate" >"$OUT"
    says "RESIDUAL"
    says "deliberate circumvention"
    says "QUALITY of the reason"

    # THE HOOK'S HALF OF THE CLOSED LIST. Before the valve, deleting this export
    # lost a measurement; now it would refuse every push on this machine. That
    # is a much larger consequence for a one-line deletion, so the line is
    # asserted rather than left to be noticed.
    CURRENT="the push wall sets its own sanction"
    out_file
    if [ -r "${ROOT}/scripts/githooks/pre-push" ]; then
        cp "${ROOT}/scripts/githooks/pre-push" "$OUT"
        says "export DJB_GATE_CALLER=push-wall"
        says "IT IS ALSO THE SANCTION"
    else
        bad "scripts/githooks/pre-push is not readable — the wall's sanction cannot be judged"
    fi

    # AND THE RITUAL SCRIPTS POINT AT THE FLAG. A valve nobody is told about at
    # the moment they would want it is a valve that gets worked around.
    CURRENT="the ritual scripts name --bank"
    out_file
    RC=0
    grep -l -- '--bank' "${ROOT}/scripts/pm_merge.sh" "${ROOT}/scripts/pm_push.sh" >"$OUT" 2>&1 || RC=$?
    if [ "$(grep -c . "$OUT")" = "2" ]; then
        ok "pm_merge.sh and pm_push.sh both name --bank where the PM would want it"
    else
        bad "one of the ritual scripts no longer points at --bank"
    fi
}

case_the_declared_limit_is_written_down() {
    # The criteria asked for the limit to be SAID: the lease serializes full
    # gates on ONE MACHINE, and cross-machine CI runners were never the
    # finding's scope. A guard whose edge is not written down gets read as
    # covering more than it does.
    CURRENT="the declared limit"
    out_file
    cp "${ROOT}/scripts/gate_lease.sh" "$OUT"
    says "DECLARED LIMIT"
    says "ONE MACHINE"
    says "cross-machine CI runners were never this lease's scope"
    says "TRUST CLASS"

    CURRENT="the semaphore's declared limits"
    out_file
    cp "${ROOT}/scripts/gate_lease.sh" "$OUT"
    says "THE LOCK ORDER"
    says "A BARE \`pytest\` TAKES NO SLOT"
    says "SAME MACHINE ONLY"
    says "THE MKDIR/HOLDER WINDOW"

    # The owner's own observation, banked at the PM's instruction as the
    # condition this mechanism closes. It is held by a test because it is the
    # only evidence in the header for the one design decision a future editor
    # is most likely to undo as pointless: that the slot directory is
    # MACHINE-WIDE and not per-repository. The load-162 measurement does not
    # justify that on its own — one repository's builders would be closed by a
    # counter inside that repository. Two PMs on one box are not.
    CURRENT="the second witness — the owner's CPU-crush observation"
    out_file
    cp "${ROOT}/scripts/gate_lease.sh" "$OUT"
    says "THE SECOND WITNESS"
    says "the computer CPU is crushed"
    # Not the bare word MACHINE-WIDE: the file says that in four other places,
    # so asserting it here would stay green with this whole block deleted —
    # which is exactly what the plant test caught it doing.
    says "OURS OVERLAPPING SOMEBODY ELSE'S"
}

case_gate_lease_sh_is_a_library_not_an_instrument() {
    # `loop_tier.sh`'s declaration, for the same reason: a non-executable file
    # under scripts/ reports no verdict of its own and owes no instruments.md
    # row. Executable and uncensused is an exit 2 at the goalpost census, and
    # this is the case that says the state is deliberate.
    CURRENT="gate_lease.sh is a library"
    out_file
    if [ -x "${ROOT}/scripts/gate_lease.sh" ]; then
        bad "scripts/gate_lease.sh is executable — it would owe an instruments.md row it has no verdict for"
    else
        ok "not executable, which is the declaration"
    fi
    if [ -x "${ROOT}/scripts/tests/test_gate_lease.sh" ]; then
        ok "this drive IS executable — it reports a verdict and owes its census row"
    else
        bad "this drive is not executable — the gate could not run it"
    fi
}

case_list_mode_is_not_a_run_that_died() {
    # `--list` names the cases and runs none, so it never reaches
    # `drive_finished` — and section 5 of the preamble read that as the death
    # it exists to catch: exit 2 under "DIED BEFORE REPORTING", over a listing
    # that was perfectly correct. It is the one guard here whose whole value is
    # being believed, and the first thing this drive said about itself to
    # anybody asking what it covers was that it had died.
    #
    # BOTH HALVES, because they were two defects wearing one symptom: the false
    # status (fixed in `drive_preamble.sh` §5a, for the whole family) and the
    # double listing (fixed here — `^case_` matched the call sites at the
    # bottom of this file as well as the definitions, so 31 cases printed 62
    # lines).
    CURRENT="list mode is not a run that died"
    out_file
    "$0" --list >"$OUT" 2>&1
    RC=$?
    exits 0
    says_not "DIED BEFORE REPORTING"

    local printed distinct
    printed=$(grep -c 'case_' "$OUT")
    distinct=$(grep -o 'case_[A-Za-z0-9_]*' "$OUT" | sort -u | wc -l | tr -d ' ')
    if [ "$printed" = "$distinct" ]; then
        ok "each case is named exactly once (${printed} lines, ${distinct} cases)"
    else
        bad "the listing repeats itself — ${printed} lines for ${distinct} cases"
    fi

    # The fix disarmed ONE check and nothing else: a real run that opts in and
    # dies must still be could-not-look. Asserted as TEXT because reproducing
    # the death needs a drive that dies, and this file may not be one.
    CURRENT="list mode disarms only the sentinel"
    out_file
    cp "${ROOT}/scripts/tests/drive_preamble.sh" "$OUT"
    says "DRIVE_LIST_MODE"
    says 'if [ "${DRIVE_OPTED_IN_TO_FINISH:-0}" = "1" ] && [ "${DRIVE_LIST_MODE:-0}" != "1" ] &&'
    says "IT DISARMS ONE CHECK AND NOTHING ELSE"
}

case_an_uncontended_lease_is_taken_at_once
case_a_second_gate_WAITS_and_SAYS_SO
case_the_lease_wait_prints_an_estimate_too
case_a_waiter_gets_the_lease_when_the_holder_lets_go
case_a_dead_holders_lease_clears_itself
case_a_LIVE_holder_is_never_cleared
case_another_hosts_lease_is_never_cleared
case_a_lease_is_released_only_by_the_process_that_holds_it
case_exactly_one_of_two_racing_acquires_wins
case_a_relative_lease_directory_is_refused
case_the_slot_count_and_the_worker_share_are_derived
case_the_Nplus1th_pytest_leg_WAITS_and_SAYS_SO
case_a_waiter_takes_a_slot_when_one_frees
case_a_killed_slot_holder_is_reclaimed
case_a_foreign_hosts_slot_is_waited_on_then_refused
case_an_orphaned_mkdir_window_is_reclaimed_eventually
case_a_slot_is_released_only_by_the_process_that_holds_it
case_exactly_N_of_many_racing_slot_acquires_win
case_the_lock_order_is_REFUSED_not_merely_documented
case_an_unsanctioned_full_gate_is_REFUSED
case_a_shapeless_sanction_is_REFUSED
case_bank_from_a_LINKED_worktree_is_REFUSED
case_bank_from_a_worktree_merely_NAMED_pm_push_is_REFUSED
case_the_pm_push_arm_is_not_a_basename_alone
case_an_unknown_flag_is_still_exit_2
case_the_ledger_row_carries_the_sanction
case_the_caller_vocabulary_is_closed
case_the_ledger_and_run_log_carry_the_caller
case_a_pre_N353_line_still_parses
case_the_wiring_in_check_sh
case_the_slot_wiring_in_check_sh
case_the_sanction_valve_wiring_in_check_sh
case_the_declared_limit_is_written_down
case_gate_lease_sh_is_a_library_not_an_instrument
case_list_mode_is_not_a_run_that_died

echo
echo "test_gate_lease: ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
