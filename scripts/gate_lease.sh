#!/usr/bin/env bash
# The machine-wide gate guards' shell face: one-line wrappers over `quality/djb/hold.py`.
# Sourced by `scripts/check.sh` and by `quality/tests/test_hold.py`.
#
# Three guards; every line any of them prints names its guard:
#   1. THE FULL-GATE LEASE: exclusive, taken by the full gate only; on contention it WAITS.
#   2. THE HOST SLOT: `DJB_GATE_HOST_SLOTS` (3) whole gates per machine, every mode; it WAITS.
#   3. THE PYTEST SLOT SEMAPHORE: N holders per machine, one per pytest leg, `-n <cores/N>`.
#
# THE LOCK ORDER: lease, then host slot, then pytest slot; a full gate out of order is exit 2.
#
# BASH ONLY: sourced into zsh, `local path` ties to `$PATH` and every helper dies silently.
# NOT EXECUTABLE: a library; the caller owns the exit status.
#
# does-not-cover: all that `quality/djb/hold.py` declares it does not cover — another machine,
# CI, sabotage, a bare pytest, fairness, another host's record, the mkdir/holder window.

# shellcheck source=scripts/gate_refuse.sh
if [ -z "${GATE_REFUSE_SOURCED:-}" ]; then
    case "${BASH_SOURCE[0]:-}" in
    */*) . "${BASH_SOURCE[0]%/*}/gate_refuse.sh" ;;
    *) . scripts/gate_refuse.sh ;;
    esac
fi

# The numbers check.sh and the drive read; quality/djb/hold.py holds the ones that decide.
GATE_LEASE_DEFAULT_ANNOUNCE=60
GATE_SLOT_CORES_PER_SLOT=5
GATE_SLOT_NOMINAL_LOOP=240
GATE_SLOT_NOMINAL_FULL=900

# The guard globals a caller reads: `gate_hold_cli` hands them to the verb and takes back what it set.
GATE_LEASE=""
GATE_LEASE_WAITED=0
GATE_SLOT=""
GATE_SLOTS_HELD=""
GATE_SLOT_WAITED=0
GATE_SLOT_TOTAL=""
GATE_SLOT_WORKERS=""
GATE_SLOT_WORKERS_PROV=""
GATE_SLOT_WORKERS_PHRASE=""
GATE_SLOT_LEASE_FIRST=""
GATE_LEASE_HOME=$(cd "${BASH_SOURCE[0]%/*}/.." 2>/dev/null && pwd)

# gate_hold_cli <verb> [args…] — `python -m quality.djb.hold <verb>` for this shell's pid and guards; exit 2 if it cannot start.
gate_hold_cli() {
    local verb=$1 state="" rc=0
    shift
    {
        state=$(python3 -E -S -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from quality.djb.hold import main; sys.exit(main())' \
            "$GATE_LEASE_HOME" "$verb" --pid "$$" --lease "${GATE_LEASE:-}" --slot "${GATE_SLOT:-}" \
            --held "${GATE_SLOTS_HELD:-}" --lease-first "${GATE_SLOT_LEASE_FIRST:-}" --state-fd 3 \
            -- ${1+"$@"} 3>&1 1>&4 4>&-) || rc=$?
    } 4>&1
    if [ "$rc" -ge 126 ]; then
        gate_refuse "python3 could not run quality/djb/hold.py for ${verb} (exit ${rc}) — no guard was taken or read."
        return 2
    fi
    eval "$state"
    return "$rc"
}

# rule-84: superseded by quality/djb/hold.py::lease_path while quality/tests/test_hold.py calls it
gate_lease_path() { gate_hold_cli gate_lease_path "$@"; }

# rule-84: superseded by quality/djb/hold.py::slots_dir while scripts/check.sh calls it
gate_slots_dir() { gate_hold_cli gate_slots_dir "$@"; }

# rule-84: superseded by quality/djb/hold.py::holder_of while quality/tests/test_hold.py calls it
gate_lease_holder() { gate_hold_cli gate_lease_holder "$@"; }

# rule-84: superseded by quality/djb/hold.py::holder_of while scripts/check.sh and quality/djb/cli.py call it
gate_hold_holder() { gate_hold_cli gate_hold_holder "$@"; }

# rule-84: superseded by quality/djb/hold.py::try_create while scripts/check.sh calls it
gate_hold() { gate_hold_cli gate_hold "$@"; }

# rule-84: superseded by quality/djb/hold.py::try_lease while quality/tests/test_hold.py calls it
gate_lease_try() { gate_hold_cli gate_lease_try "$@"; }

# rule-84: superseded by quality/djb/hold.py::Hold.release while scripts/check.sh calls it
gate_lease_release() { gate_hold_cli gate_lease_release "$@"; }

# rule-84: superseded by quality/djb/hold.py::acquire_lease while scripts/check.sh calls it
gate_lease_acquire() { gate_hold_cli gate_lease_acquire "$@"; }

# rule-84: superseded by quality/djb/hold.py::cores while scripts/check.sh calls it
gate_slot_cores() { gate_hold_cli gate_slot_cores "$@"; }

# rule-84: superseded by quality/djb/hold.py::slots_total while scripts/test.sh calls it
gate_slots_total() { gate_hold_cli gate_slots_total "$@"; }

# rule-84: superseded by quality/djb/hold.py::slot_workers while scripts/test.sh calls it
gate_slot_workers() { gate_hold_cli gate_slot_workers "$@"; }

# rule-84: superseded by quality/djb/hold.py::worker_count while scripts/check.sh calls it
gate_slot_worker_count() { gate_hold_cli gate_slot_worker_count "$@"; }

# rule-84: superseded by quality/djb/hold.py::record while quality/tests/test_hold.py calls it
gate_slot_line() { gate_hold_cli gate_slot_line "$@"; }

# rule-84: superseded by quality/djb/hold.py::slot_holders while scripts/check.sh calls it
gate_slot_holders() { gate_hold_cli gate_slot_holders "$@"; }

# rule-84: superseded by quality/djb/hold.py::try_slot while quality/tests/test_hold.py calls it
gate_slot_try() { gate_hold_cli gate_slot_try "$@"; }

# rule-84: superseded by quality/djb/hold.py::Hold.release while scripts/check.sh calls it
gate_slot_release() { gate_hold_cli gate_slot_release "$@"; }

# rule-84: superseded by quality/djb/hold.py::acquire_slot while scripts/check.sh calls it
gate_slot_acquire() { gate_hold_cli gate_slot_acquire "$@"; }

# rule-84: superseded by quality/djb/hold.py::slot_holder_phrase while quality/tests/test_hold.py calls it
gate_slot_holder_phrase() { gate_hold_cli gate_slot_holder_phrase "$@"; }
