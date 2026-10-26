"""The test databases come down clean."""

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import time
import warnings
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from asgiref.sync import AsyncToSync, SyncToAsync
from django.db import DEFAULT_DB_ALIAS, connections
from pytest_django import DjangoDbBlocker

# --- the test databases come down clean ---------------------------------------
#
# The defect, named. `sync_to_async(fn)` with asgiref's default
# `thread_sensitive=True`, called with no surrounding `ThreadSensitiveContext`,
# runs `fn` on `asgiref.sync.SyncToAsync.single_thread_executor` — ONE
# `ThreadPoolExecutor(max_workers=1)` built as a class attribute at import and
# never shut down (asgiref 3.12.1, `asgiref/sync.py:409`; its thread is the one
# called `ThreadPoolExecutor-0_0`). A database call made there opens a
# connection in that thread and nothing ever closes it: there is no request
# cycle to fire `close_old_connections`, `CONN_MAX_AGE = 0` only decides what
# happens when something DOES check, and the thread outlives every test in the
# process. At the end of the session pytest-django asks Postgres to drop the
# worker's test database, Postgres answers `database "test_<name>_gwN" is being
# accessed by other users`, and pytest-django turns that into a WARNING and
# carries on — so the run stays green and the database stays on disk, per
# checkout, silently, forever.
#
# Reproduced deterministically at rung time by the one test
# `test_an_emitted_event_arrives_on_a_connected_socket`
# (`apps/realtime/tests/test_spine_end_to_end.py`) run alone: its last act is a
# bare `sync_to_async(...objects.get)`, so the pool thread's connection is still
# open when the drop is attempted.
#
# Why the fix is here and not at the call sites. Closing the call sites would
# close today's holder and nothing else; the class comes back with the next
# pool, the next `sync_to_async`, the next library that keeps a thread. This
# closes it where the drop happens, once, for every holder.


def _close_connections_in_persistent_pools() -> None:
    """Close what asgiref's long-lived worker threads still hold.

    Asked of each pool *from inside the pool*, so Django's own bookkeeping does
    the closing (`connections.close_all()` is thread-local, which is exactly
    why the connection could not be reached from here in the first place).
    Reached by attribute rather than by import path because these are asgiref's
    internals: if a future asgiref renames them the net below still holds.
    """
    pools: list[ThreadPoolExecutor] = []
    single = getattr(SyncToAsync, "single_thread_executor", None)
    if isinstance(single, ThreadPoolExecutor):
        pools.append(single)
    for holder in (SyncToAsync, AsyncToSync):
        # Per-`ThreadSensitiveContext` pools. Weak-keyed, so listed before use.
        by_context = getattr(holder, "context_to_thread_executor", {})
        pools.extend(
            pool for pool in list(by_context.values()) if isinstance(pool, ThreadPoolExecutor)
        )
    for pool in pools:
        try:
            pool.submit(connections.close_all).result(timeout=30)
        except RuntimeError:
            # Already shut down: its threads are gone and so are their sockets.
            continue


def _terminate_strays_on_this_workers_database() -> int:
    """The net: hang up on anything still connected to OUR test database.

    Scoped to `current_database()`, which under `-n auto` is this worker's own
    `test_<DATABASE_NAME>_gwN` and under a serial run this checkout's own
    `test_<DATABASE_NAME>` — a name no other checkout and no other worker can
    reach (`scripts/db.sh`). So this cannot touch a neighbour's live database,
    which is the hazard a broad sweep would be.

    It returns the count rather than swallowing it: a stray that survives the
    close above is a holder nobody has diagnosed yet, and the caller says so out
    loud instead of leaving the next reader a mystery.
    """
    connection = connections[DEFAULT_DB_ALIAS]
    if connection.vendor != "postgresql":
        return 0
    others = "FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()"
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) {others}")
        row = cursor.fetchone()
        strays = int(row[0]) if row else 0
        if strays:
            cursor.execute(f"SELECT pg_terminate_backend(pid) {others}")
    return strays


# --- what this fixture costs, and where the lever for it is (V1-c) -----------
#
# MEASURED, not estimated (V1-c, ten-core laptop, 2026-08-24). Under `-n auto`
# every xdist worker creates and migrates its OWN `test_<DATABASE_NAME>_gwN`,
# and pytest's own `--durations` report shows the bill as exactly ten setup
# entries of ~5.5–6.2s, one per worker, charged to whichever test happened to
# ask for a database first. That is ~57 CPU-seconds per pass, and ~5.7s of it
# is on EVERY worker's critical path — a floor the per-rung leg cannot get
# under by running fewer tests, and a floor the FULL gate pays twice.
#
# THE LEVER IS NOT HERE, and this note exists so the next reader does not go
# looking for it here. `--reuse-db` would remove the cost and is refused: a
# reused database is not re-migrated, so a rung that adds a migration would test
# against a stale schema in silence, which is a correctness hole bought with
# seconds. **THE SEAM IS A TEMPLATE**: Django's Postgres backend issues
# `CREATE DATABASE … WITH TEMPLATE …` when the connection's
# `TEST["TEMPLATE"]` is set, so a migrated template — which is V1-b's subject in
# `scripts/db.sh` — turns each worker's migrate into a file copy. One line, in
# `config/settings/test.py`, pointed at whatever name V1-b derives. Nothing here
# needs to change for it.


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup: None, django_db_blocker: DjangoDbBlocker) -> Iterator[None]:
    """pytest-django's database setup, with the connections released after it.

    An override that REQUESTS the fixture it overrides, which is what puts this
    teardown in the right place: a fixture set up after `django_db_setup` is
    finalised before it, so this runs while the test databases still exist and
    before the drop is attempted.
    """
    yield
    _close_connections_in_persistent_pools()
    with django_db_blocker.unblock():
        strays = _terminate_strays_on_this_workers_database()
    if strays:
        warnings.warn(
            f"{strays} connection(s) to this worker's test database outlived the suite and were "
            "terminated so it could be dropped. A thread pool is holding a Django connection "
            "past teardown and apps/testing/teardown.py does not know about it — find the "
            "holder's class, do not widen this net.",
            stacklevel=2,
        )


# --- the ephemeral Temporal test servers come down clean too ------------------
#
# THE DEFECT, NAMED. `WorkflowEnvironment.start_time_skipping()` spawns a real
# `temporal-test-server` binary as a CHILD OF THIS PROCESS, and every call site
# in this repository already uses it as an async context manager, so the happy
# path shuts it down — a full green `-n auto` pass leaks nothing, measured. What
# breaks is what happens when two of them are handed one port, and all three
# steps below were MEASURED on this machine rather than reasoned about:
#
#   1. THE LOSER OF A COLLISION NEVER EXITS. Two servers on one port: the second
#      dies in `main` with `java.io.IOException: Failed to bind to address
#      0.0.0.0/0.0.0.0:<port>` / `java.net.BindException: Address already in
#      use` out of grpc-netty — the trace that failed a push at
#      `apps/workflows/tests/test_context.py` — but its netty event-loop thread
#      is not a daemon, so the PROCESS WEDGES: alive, listening on nothing,
#      ~24 MB resident, immortal. Launched against an occupied port it was
#      still running at t+30s with `rc=None`.
#   2. THE CALLER IS NOT TOLD. The loser's `start_time_skipping()` RETURNS
#      SUCCESSFULLY in 0.1s, because the health check reaches the port and the
#      WINNER answers it. The test then runs against another xdist worker's
#      Temporal server without either of them knowing — which is what a burst
#      of unreproducible workflow failures in one pass looks like from outside.
#   3. IT NEVER TIMES OUT. When the thing answering the port is not a Temporal
#      server at all, the start waits FOREVER — no timeout of any kind (killed
#      at 120s). A run aborted in that state leaves the child behind, and a
#      child whose pytest parent is gone is reparented to pid 1 and survives
#      for days: the specimen found on this machine had been up 21 minutes with
#      no listener and the netty boss thread parked, which is step 1's state
#      exactly, and is E1's eleven strays.
#
# A HYPOTHESIS THAT DID NOT SURVIVE, recorded so nobody spends the afternoon on
# it again: the SDK probes the LOOPBACK for a free port and the server binds the
# WILDCARD, and `bind(("127.0.0.1", P))` with SO_REUSEADDR — which is what
# Rust's `std::net::TcpListener::bind` sets — DOES succeed while a server holds
# P on the wildcard. It looked like the whole story. It is not: the kernel's
# ephemeral allocator does not hand out a wildcard-held port even to that
# socket. Measured against 400 held ports: 0/400 collisions from an SDK-shaped
# probe, 0/400 from a wildcard one. Reserving the port here would therefore buy
# nothing, so this does not do it — the residual window is between the probe
# closing and the server binding, and no probe can close that.
#
# WHY THE FIX IS HERE. There are ~60 `async with await
# WorkflowEnvironment.start_time_skipping()` call sites across seven apps and
# every one of them is already correct. What is wrong is what the SDK does when
# a start goes sideways, so this wraps the ONE function they all resolve
# through: the start is bounded instead of infinite, the environment it returns
# is checked to be OURS before a test is allowed to trust it, and anything left
# running is this process's own child and is reaped as one.
#
# WHAT THIS DELIBERATELY DOES NOT DO: share one environment per worker. Time
# skipping is global to an environment (the SDK's own docstring says so),
# workflow ids here are deterministic by house rule 18 — `test_context.py`
# starts `acme:workflows:parent:seen` by name — and pytest-randomly reorders
# every run, so a shared server would make each test's clock and id space
# depend on whichever test happened to run before it. That is precisely the
# coupling the one-seed two-pass gate leg exists to catch, bought for a few
# seconds of wall time.

_TEST_SERVER = "temporal-test-server"

# The predicate the collision check actually applies, in words, in ONE place so
# that both refusals below say the same true thing. It is per-START-
# CHILD and not per-process: `_the_server_answering_is_ours` asks whether the
# listener is a process THIS start spawned, and the honest answer against an
# environment this same pytest process started a minute ago is "no". The text
# used to say "another process", which is correct for the xdist collision it was
# written against and flatly false for the same-process one — and sent whoever
# read it hunting for a sibling that was never there.
_NOT_THIS_STARTS_CHILD = "something that is not this start's child"

# The census's own budget, and the sentence it says when it runs out.
# Ten seconds is not a guess about how long `ps -A` takes — it takes
# milliseconds — it is the line past which the only remaining explanations are
# a wedged kernel table or a machine so loaded that the suite's answer is
# worthless either way. Both are worth a red.
_PS_SECONDS = 10.0
_PS_HUNG = (
    f"the `ps -Ao pid=,ppid=,args=` census in `_test_server_children` did not answer within "
    f"{_PS_SECONDS:.0f}s. Without this timeout, the call is unbounded work inside an "
    "autouse fixture: it once froze the whole gate at 96% with every "
    "xdist worker at 0% CPU and nothing said why. The suite cannot tell whether a Temporal test "
    "server leaked, so it refuses rather than reporting a census it could not take — "
    "`scripts/temporal_sweep.sh` is the census to run by hand, and a machine this loaded should "
    "not be running a gate."
)

# A cold checkout downloads a 64 MB binary INSIDE the first start, so the first
# attempt in a process gets a download-sized budget and later ones do not. Any
# finite number beats what is there now, which is no timeout at all (step 3
# above): the hang is what orphans the child when the run is eventually killed.
_FIRST_START_SECONDS = 300.0
_LATER_START_SECONDS = 60.0
_START_ATTEMPTS = 3

#: Whether a start FINISHED here (a cancelled or timed-out one never does): a named port's budget.
_a_start_has_finished_here = False

# Servers THIS process started and has not yet seen exit, and whether the test
# now running asked for one at all. Per process, so each xdist worker keeps its
# own and never reasons about a sibling's.
_servers_started_here: set[int] = set()
_a_server_was_started_this_test = False


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _test_server_children() -> set[int]:
    """The `temporal-test-server` processes whose parent is THIS process.

    The parentage is the whole safety argument, and it is the same shape as
    `scripts/db_sweep.sh`'s refusals: a peer agent's live worker in another
    checkout is a child of ITS pytest process, never of ours, so nothing here
    can reach it however loaded the machine is.

    Matched on the EXECUTABLE — the first argv token's basename — never on a
    command line that merely mentions the name, which is the difference between
    a census and a `grep` that counts itself.

    **The reaper cannot be allowed to hang the reaper.** This `ps` is
    called from an autouse fixture, so every test in the suite passes through
    it; without a timeout it is an unbounded wait inside test teardown, and on
    2026-08-24 that is exactly what it became — the merge gate sat 22+
    minutes at 96% with every xdist worker at 0% CPU because this call never
    returned (macOS, machine under two concurrent full suites). A `ps -A` that
    has not answered in ten seconds is not slow, it is stuck, so the wait is
    bounded and the refusal is LOUD: `RuntimeError` naming the call and the
    budget, which surfaces as an errored fixture with a sentence a reader can
    act on. Never a silent `set()` — a census that answers "no children" when
    it could not look is how a leaked server becomes invisible, which is the
    same failure shape this helper exists to prevent.
    """
    try:
        listing = subprocess.run(
            ["ps", "-Ao", "pid=,ppid=,args="],  # noqa: S607 — `ps` from PATH, listing this machine's own processes
            capture_output=True,
            text=True,
            check=False,
            timeout=_PS_SECONDS,
        )
    except subprocess.TimeoutExpired as expired:
        raise RuntimeError(_PS_HUNG) from expired
    ours = str(os.getpid())
    found: set[int] = set()
    for line in listing.stdout.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) < 3 or fields[1] != ours:
            continue
        if os.path.basename(fields[2].split()[0]).startswith(_TEST_SERVER):
            found.add(int(fields[0]))
    return found


def _the_server_answering_is_ours(children: set[int], port: int) -> bool:
    """Is the process serving `port` the child this start just spawned?

    This is the collision detector, and it is the whole of step 2 in the header:
    a losing start returns a client pointed at a server IT DID NOT SPAWN and
    says nothing. Asking who actually holds the listening socket separates the
    two cases exactly — measured on a forced collision, the winner's child came
    back as the holder and the loser's child came back holding nothing.

    The question is per START, not per process, and the difference is not
    academic: the winner may be another xdist worker's server, or it may be an
    environment THIS process started earlier and has not shut down. Both are
    equally fatal to a caller that wanted its own clock, both answer False
    here, and `_NOT_THIS_STARTS_CHILD` is the sentence both refusals say.

    Answers TRUE whenever it cannot tell: no child could be attributed to this
    start (the `ps` scan and the spawn raced), or there is no `lsof` on the
    machine. A start that worked must never be thrown away because the check
    was blind.
    """
    if not children:
        return True
    for pid in children:
        try:
            held = subprocess.run(  # noqa: S603 — argv list to `lsof` with an int pid and port; no shell
                ["lsof", "-nP", "-a", "-p", str(pid), f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],  # noqa: S607 — `lsof` from PATH, asking about this machine's own port
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return True  # no lsof: unknowable, and unknowable is not guilty
        if held.stdout.strip():
            return True
    return False


def _port_of(environment: Any) -> int | None:
    """The port the returned environment is actually talking to, or None."""
    try:
        target = str(environment.client.service_client.config.target_host)
        return int(target.rsplit(":", 1)[1])
    except (AttributeError, ValueError, IndexError):
        return None


def _reap(pids: set[int]) -> None:
    """Stop test servers this process started. TERM, then KILL what ignores it.

    A wedged loser has already lost its `main` thread, so TERM is the courtesy
    and KILL is the guarantee.
    """
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        alive = {pid for pid in pids if _alive(pid)}
        if not alive:
            return
        for pid in alive:
            try:
                os.kill(pid, signal_number)
            except (ProcessLookupError, PermissionError):
                continue
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and any(_alive(pid) for pid in alive):
            time.sleep(0.05)


async def _bounded_start(original: Any, kwargs: dict[str, Any], *, budget: float) -> Any:
    """Await ONE start under a finite budget, reaping the child a cancel strands.

    This is the only place `original` is awaited, and that is the whole of it.
    Both branches below want the same three things — a bound, a reap on cancel,
    and the note that a start has now finished in this process — and when each
    branch kept its own copy, only one of them ended up with the bound: on the
    same plain TCP occupant, the unnamed branch ended each attempt at its
    declared budget while the named branch was still waiting past 75 s, when the
    verifier's own timeout ended it — with the header above
    claiming both were bounded. One copy cannot drift from itself.

    `TimeoutError` comes back out as itself, because the two callers mean
    different things by a budget that ran out — a named port that nothing
    answers on is refused, an unnamed one is retried onto another port — and the
    caller is the one that knows which. `CancelledError` is re-raised after the
    reap: a cancel is not ours to swallow, but the child is ours to bury, and it
    is orphaned the moment this process goes.
    """
    global _a_start_has_finished_here

    before = _test_server_children()
    try:
        async with asyncio.timeout(budget):
            environment = await original(**kwargs)
    except asyncio.CancelledError:
        # `asyncio.timeout` turns its OWN expiry into `TimeoutError` on the way
        # out, so a `CancelledError` reaching here came from outside: somebody
        # cancelled the task that is starting a server. Reap and re-raise.
        _reap(_test_server_children() - before)
        raise
    # FINISHED, not succeeded: the caller above may still refuse this
    # environment as a collision, and the download happened all the same. The
    # flag's own docstring is where that is argued (N106b).
    _a_start_has_finished_here = True
    return environment


@pytest.fixture(scope="session", autouse=True)
def _temporal_test_servers_are_ours_to_clean_up() -> Iterator[None]:
    """Wrap the one call every workflow test makes, for the whole session.

    Session-scoped and not per-test: the wrapper has to be in place for the
    first workflow test whatever order pytest-randomly picks, and the class
    attribute is the single thing all ~60 call sites resolve through.
    """
    from temporalio.testing import WorkflowEnvironment

    original = WorkflowEnvironment.start_time_skipping

    async def start_time_skipping(**kwargs: Any) -> Any:
        global _a_server_was_started_this_test
        _a_server_was_started_this_test = True
        named_port = kwargs.get("port")
        if named_port is not None:
            # A caller that named a port meant THAT port, so a collision here
            # is not retried onto another one — it is refused. Silently handing
            # back a server this start did not spawn is the one answer that is
            # never right, whoever fathered it.
            before = _test_server_children()
            budget = (
                _FIRST_START_SECONDS if not _a_start_has_finished_here else _LATER_START_SECONDS
            )
            try:
                environment = await _bounded_start(original, kwargs, budget=budget)
            except TimeoutError:
                # NOTHING ANSWERED — a different fact from the collision below,
                # and it gets its own sentence because the reader's next move is
                # different. Something holds this port without speaking Temporal
                # (a plain listener, a wedged loser, a foreign service), so the
                # SDK's health probe waits for an answer that is never coming.
                # Unbounded, that is a hang that ends only when somebody kills
                # the run — and a killed run is exactly what reparents the child
                # to pid 1 and leaves it there for days (step 3 in the header).
                _reap(_test_server_children() - before)
                raise RuntimeError(
                    f"nothing answered as a Temporal server on port {named_port} within "
                    f"{budget:g}s, so this start could never have finished. Something "
                    "holds that port without speaking Temporal; anything this start spawned "
                    "has been reaped. Ask for a port nothing holds, or ask for none and let "
                    "one be chosen."
                ) from None
            ours = _test_server_children() - before
            port = _port_of(environment)
            if port is not None and not _the_server_answering_is_ours(ours, port):
                try:
                    await environment.shutdown()
                except Exception:  # noqa: BLE001, S110 — the reap below is the guarantee
                    pass
                _reap(ours)
                raise RuntimeError(
                    f"port {port} is already served by {_NOT_THIS_STARTS_CHILD}, so this "
                    "environment would have driven a Temporal server this start did not "
                    "spawn — a sibling worker's, or one this same process started "
                    "earlier; either way the clock and the workflow-id space would be "
                    "shared. Our own server lost the bind and has been reaped; ask for a "
                    "port nothing holds, or ask for none and let one be chosen."
                )
            _servers_started_here.update(ours)
            return environment

        failures: list[str] = []
        for attempt in range(1, _START_ATTEMPTS + 1):
            before = _test_server_children()
            budget = _FIRST_START_SECONDS if attempt == 1 else _LATER_START_SECONDS
            try:
                environment = await _bounded_start(original, kwargs, budget=budget)
            except Exception as exc:
                _reap(_test_server_children() - before)
                failures.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                continue

            ours = _test_server_children() - before
            port = _port_of(environment)
            if port is not None and not _the_server_answering_is_ours(ours, port):
                # The collision, caught where the SDK stays silent: this start
                # was handed another worker's server, and OUR child is the
                # wedged loser. Both go, and the next attempt takes a new port.
                try:
                    await environment.shutdown()
                except Exception:  # noqa: BLE001, S110 — the reap below is the guarantee
                    pass
                _reap(ours)
                failures.append(
                    f"attempt {attempt}: port {port} was already served by "
                    f"{_NOT_THIS_STARTS_CHILD} — our own server lost the bind and was reaped"
                )
                continue

            _servers_started_here.update(ours)
            return environment

        raise RuntimeError(
            f"no time-skipping Temporal test server of our own would start in {_START_ATTEMPTS} "
            "attempts. Every attempt was bounded, checked to be serving OUR child, and reaped "
            "before the next, so nothing was left behind by this call: " + " | ".join(failures)
        )

    patch = pytest.MonkeyPatch()
    patch.setattr(WorkflowEnvironment, "start_time_skipping", staticmethod(start_time_skipping))
    try:
        yield
    finally:
        patch.undo()
        # The last word for this worker: whatever it started and did not stop
        # dies with it, rather than reparenting to launchd and living for days.
        _reap(_test_server_children())


@pytest.fixture(autouse=True)
def _no_test_server_outlives_the_test_that_started_it() -> Iterator[None]:
    """The invariant, checked where it is cheap to check.

    Every call site owns its environment for the length of one test, so at the
    end of a test this process should own ZERO test-server children. Anything
    still running is a leak; it is reaped and SAID OUT LOUD, because a silent
    broom would hide the next holder exactly as a silent warning does.

    The check is by PARENTAGE and not by the pids the wrapper recorded, so it
    also catches a server this process fathered without going through the
    wrapper at all — which is the one the wrapper can never know about. Only a
    test that asked for a server pays for it: the ~1300 tests that never touch
    Temporal read one boolean and stop.
    """
    global _a_server_was_started_this_test
    yield
    if not _a_server_was_started_this_test:
        return
    _a_server_was_started_this_test = False
    # A `shutdown()` that has just returned may still be reaping its child, so
    # the ordinary case gets a moment before it is called a leak. `_alive` on
    # the recorded pids first, because it costs no process at all.
    deadline = time.monotonic() + 2.0
    known = {pid for pid in _servers_started_here if _alive(pid)}
    while known and time.monotonic() < deadline:
        time.sleep(0.05)
        known = {pid for pid in known if _alive(pid)}
    _servers_started_here.clear()
    strays = _test_server_children()
    if strays:
        _reap(strays)
        warnings.warn(
            f"{len(strays)} ephemeral Temporal test server(s) outlived the test that started "
            "them and were reaped. The `async with` around "
            "WorkflowEnvironment.start_time_skipping() did not run its exit — find out why "
            "before widening this net; scripts/temporal_sweep.sh is the census.",
            stacklevel=2,
        )
