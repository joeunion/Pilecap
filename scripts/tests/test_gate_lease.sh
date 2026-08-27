#!/usr/bin/env bash
# The drive for the MACHINE-WIDE FULL-GATE LEASE (`scripts/gate_lease.sh`) and
# for the caller field the ledger records beside it (`scripts/gate_ledger.sh`).
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
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
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

case_an_uncontended_lease_is_taken_at_once
case_a_second_gate_WAITS_and_SAYS_SO
case_a_waiter_gets_the_lease_when_the_holder_lets_go
case_a_dead_holders_lease_clears_itself
case_a_LIVE_holder_is_never_cleared
case_another_hosts_lease_is_never_cleared
case_a_lease_is_released_only_by_the_process_that_holds_it
case_exactly_one_of_two_racing_acquires_wins
case_a_relative_lease_directory_is_refused
case_the_caller_vocabulary_is_closed
case_the_ledger_and_run_log_carry_the_caller
case_a_pre_N353_line_still_parses
case_the_wiring_in_check_sh
case_the_declared_limit_is_written_down
case_gate_lease_sh_is_a_library_not_an_instrument

echo
echo "test_gate_lease: ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
