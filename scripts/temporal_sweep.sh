#!/usr/bin/env bash
# The census and the broom for LEFT-BEHIND TEMPORAL TEST SERVERS.
#
#   ./scripts/temporal_sweep.sh           census: every test server on this machine
#   ./scripts/temporal_sweep.sh --sweep   stop the ORPHANED ones; leave the rest
#
# WHY IT EXISTS. `WorkflowEnvironment.start_time_skipping()` spawns a real
# `temporal-test-server` binary as a child of the pytest process that asked for
# it. Two of them handed the same port is a collision, and the loser dies in
# `main` with a grpc-netty `BindException` while its non-daemon event-loop
# thread keeps the process alive FOREVER — listening on nothing, invisible to a
# loopback-scoped port probe, and reparented to pid 1 the moment its pytest
# worker exits. A census found eleven of them on one machine, one from the
# previous day, and one of them held the exact port a pass-2 test then failed
# to reach.
#
# `apps/conftest.py` is the fix and this is the SECOND layer, in that order on
# purpose. ONE OWNER FOR THE PORT CLAIM: what the conftest does and does not do
# about the port is stated in `apps/conftest.py`'s own section, beside the code
# that does it and beside the measurement that decided it — this script opens no
# socket and claims nothing about reservation. (It said the opposite of the
# conftest until a verification pass found the two headers disagreeing about
# one mechanism, which is the drift a second copy always ends in.) This script
# exists for the one case no in-process net can cover — a pytest worker that was
# SIGKILLed and never ran any teardown at all — and as the CENSUS that proves
# the conftest kept its promise. Run it before and after a suite: zero new
# servers is the property.
#
# TWO REFUSALS, both load-bearing, both the same shape as `db_sweep.sh`'s:
#
#   1. A PROCESS THAT IS NOT THE TEST-SERVER EXECUTABLE IS NEVER TOUCHED. The
#      match is on the EXECUTABLE — the first argv token's basename must begin
#      `temporal-test-server` — never on a command line that happens to mention
#      the name. That is the difference between a census and a `grep` that
#      counts itself, and it is why an agent running this script inside a shell
#      whose command line names the binary is not a candidate.
#      The compose dev server is not a candidate either: `temporal` in
#      `compose.yaml` is a CONTAINER, and no container process is a child of
#      this machine's process table under this name.
#   2. A SERVER WITH A LIVE PARENT IS NEVER TOUCHED. A running suite's test
#      server is a child of its own pytest process, so its parent is alive and
#      it is REPORTED and LEFT ALONE. Only an ORPHAN — parent pid 1, which is
#      what the kernel does to a child whose parent died — is swept. A peer
#      agent's suite running right now in another checkout therefore survives
#      this broom by construction, which is the hazard a `pkill -f
#      temporal-test-server` would walk straight into.
#
# There is no `--force`. A live parent is not an obstacle to route around.
#
# THE POPULATION IS THE FRAME'S NOW. The class this script executes is
# declared in `scripts/lifecycle.sh` — `test-server-process`: its identity
# grammar (there is NONE; a test server carries no checkout in its name and its
# owner is its parent pid), its enumerate (the process table, matched on the
# executable's basename), its liveness evidence (a live parent) and its destroy
# verb (this file, `--sweep`). The candidate scan is
# `lc_scan_test_server_processes`, sourced rather than copied, so
# `scripts/sweep.sh`'s census and this broom read exactly the same process table
# the same way. THE REFUSALS BELOW ARE STILL THIS FILE'S and are restated in its
# kill path: a list is not a licence.
#
# ONE PLACE WHERE THE FRAME IS STRICTER, and it is deliberate. `sweep.sh` maps
# ORPHAN onto its FOREIGN verdict — no identity, nothing visible owns it — so it
# needs `--force-foreign` to reach one. This script keeps its own semantics
# because it has something the frame's four verdicts do not model: parent pid 1
# is POSITIVE evidence the owner died, not an absence of evidence. `--sweep` here
# stays exactly what it was, and the gate goes on running it directly.
#
# DECLARED BLIND SPOT. "Orphan" is read as "parent is pid 1". That is exactly
# right on macOS and on a plain Linux init. Under a Linux child-subreaper (a
# systemd user session, some container runtimes) an orphan is reparented to the
# subreaper instead, and this script will report it as parented and REFUSE it.
# The failure is in the safe direction — nothing gets killed that should not —
# and it is stated here rather than discovered: on such a host, sweep by hand.
set -uo pipefail

cd "$(dirname "$0")/.."

# shellcheck source=scripts/lifecycle.sh
. scripts/lifecycle.sh

SWEEP=0
while [ "$#" -gt 0 ]; do
    case "$1" in
    --sweep) SWEEP=1 ;;
    *)
        echo "!! unknown argument '$1': temporal_sweep.sh takes --sweep" >&2
        exit 2
        ;;
    esac
    shift
done

# pid ppid exe, one candidate per line — `lc_scan_test_server_processes`, which
# is this file's own scan, moved into the frame so the census and the broom read
# the same process table the same way. Refusal 1 lives THERE and at the kill
# below: the list is built from the EXECUTABLE, and every line is re-checked
# before anything is signalled.
candidates() {
    lc_scan_test_server_processes
}

found=0
swept=0
spared=0

while read -r pid ppid exe; do
    [ -n "${pid:-}" ] || continue
    found=$((found + 1))
    base=${exe##*/}
    case "$base" in
    temporal-test-server*) ;;
    *)
        # Refusal 1, restated in the kill path — a list is not a licence.
        echo "  REFUSED  pid ${pid} — ${base} is not the test-server executable"
        spared=$((spared + 1))
        continue
        ;;
    esac
    if [ "$ppid" != "1" ]; then
        echo "  LIVE     pid ${pid} (parent ${ppid} is running) — a suite owns this one, left alone"
        spared=$((spared + 1))
        continue
    fi
    if [ "$SWEEP" -eq 0 ]; then
        echo "  ORPHAN   pid ${pid} — parent gone; --sweep would stop it"
        continue
    fi
    kill -TERM "$pid" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null
        sleep 0.5
    fi
    if kill -0 "$pid" 2>/dev/null; then
        echo "  FAILED   pid ${pid} — still running after TERM and KILL"
        spared=$((spared + 1))
    else
        echo "  STOPPED  pid ${pid}"
        swept=$((swept + 1))
    fi
done < <(candidates)

if [ "$found" -eq 0 ]; then
    echo "  (none)"
fi
echo "census: ${found} found · ${swept} stopped · ${spared} left alone"
