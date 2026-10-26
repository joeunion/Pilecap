"""The guard in `apps/conftest.py`, driven directly.

The guard wraps the ONE function ~60 workflow tests resolve through —
`WorkflowEnvironment.start_time_skipping` — and promises three things about a
start: it is BOUNDED, the environment it hands back is checked to be OURS, and
anything it strands is reaped as this process's own child. Every other test in
this repository exercises that promise only on the happy path. This module is
where the promise is driven on the paths that fail, because a net nobody drops
anything into is a net nobody knows the size of the holes in.

Why it sits at `apps/` root rather than under an app: it tests the shared
conftest, which belongs to no app. `testpaths = ["apps"]` and
`python_files = ["test_*.py"]` collect it as `apps/test_temporal_guard.py`.

WHAT IS DRIVEN, and what each one costs:

  * A PLAIN TCP LISTENER on the named port — a socket that accepts and never
    speaks Temporal. The SDK's health probe reaches it and waits for an answer
    that is never coming, so an unbounded start never returns; this is the
    exact shape measured at >75 s on the named-port branch
    while the unnamed branch bounded the same occupant. The test's own
    `asyncio.wait_for(..., _RED_INSTRUMENT_SECONDS)` is the instrument that
    ends the red rather than the suite's patience: on the baseline it fires as
    `TimeoutError` (the red), and once the branch is bounded the guard's own
    `RuntimeError` arrives first (the green).
  * A REAL `temporal-test-server`, started by a SIBLING process on the named
    port, which is a different fact and must keep its own, different refusal:
    the collision path, where something DOES answer and it is not our child.
  * THE SAME COLLISION WITH NO SIBLING AT ALL — this process's own earlier
    environment holding the port. The predicate the guard actually
    applies is per-start-child, so this is the same refusal for the same
    reason; the two tests exist to hold ONE message to being true of both
    readings, because a message that said "another process" would send the
    reader of this one hunting for a sibling that was never there.
  * A CANCEL mid-start, which must still reap.
  * The happy path, because a bound that refuses a legitimate start is a worse
    defect than the one it fixes.

And one thing that is not driven but READ: the guard's SHAPE. Every promise
above rests on there being exactly ONE place a start is awaited, and the day
the two branches each kept their own copy only one of them ended up bounded
A second seam would not fail any test here — it would fail
silently, on whichever path nobody drove — so `test_the_bounded_start_seam_is
_the_only_one` reads the source instead, and proves itself by planting the
second seam into a COPY and watching its own check go red.

The guard's budgets are DECLARED CONSTANTS (`_FIRST_START_SECONDS`,
`_LATER_START_SECONDS`), so the two refusal tests lower them through
`monkeypatch` — the production constants are never edited, and a wall-clock
measurement is never what the assertion reads.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import os
import socket
import subprocess
import sys
import time
import warnings
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from temporalio.testing import WorkflowEnvironment

from apps import conftest
from apps.testing import teardown

# The instrument, not the bound. On the baseline the named-port branch never
# returns, and something has to end the test: this is the test's OWN outer
# timeout, deliberately far above every budget under test, so that a fired one
# is unambiguous — `TimeoutError` here means the guard did not refuse.
_RED_INSTRUMENT_SECONDS = 75.0

# What the guard's declared budgets are lowered to for the refusal tests. Small
# enough that the suite does not wait for the real 60 s, large enough that the
# SDK gets to spawn and probe before it fires.
_TEST_BUDGET_SECONDS = 5.0

# A real test server takes a moment to come up, and a cold checkout downloads
# the binary inside the first start. These bound the test's own waiting, not
# anything the guard promises.
_SIBLING_READY_SECONDS = 300.0
_CHILD_APPEARS_SECONDS = 60.0

# The sibling: a real time-skipping environment on a port we name, held open
# until its stdin closes, then shut down through the SDK's own context manager
# so it leaves nothing behind. Run in another process on purpose — its server
# is a child of ITS process, never of ours, which is the whole point of the
# parentage check the collision test exercises.
_SIBLING_PROGRAM = """
import asyncio
import sys

from temporalio.testing import WorkflowEnvironment


async def main() -> None:
    port = int(sys.argv[1])
    async with await WorkflowEnvironment.start_time_skipping(port=port):
        sys.stdout.write("READY\\n")
        sys.stdout.flush()
        await asyncio.to_thread(sys.stdin.readline)


asyncio.run(main())
"""


@contextlib.contextmanager
def _a_plain_listener() -> Iterator[int]:
    """A loopback listener that accepts a connection and says nothing.

    This is the occupant no Temporal client can ever finish talking to: the TCP
    handshake completes in the kernel, so a health probe connects and then
    waits forever for a server that is not there. A loopback bind is what is
    driven; a wildcard-bound occupant is the same hang under the same bound and
    is a stated blind spot of this module rather than a second test.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(16)
    try:
        yield int(sock.getsockname()[1])
    finally:
        sock.close()


def _a_free_port() -> int:
    """A port nothing holds at the moment it is asked for."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _test_server_children_of(pid: int) -> set[int]:
    """`_test_server_children()` for a parent that is not this process.

    Same matching rule as the conftest's — the EXECUTABLE's basename, never a
    command line that merely mentions the name — because this one is used to
    prove a sibling's server SURVIVED, and a census that counts the wrong
    process proves nothing in either direction.
    """
    listing = subprocess.run(
        ["ps", "-Ao", "pid=,ppid=,args="],  # noqa: S607 — `ps` resolved on PATH, as the gate's own legs run it
        capture_output=True,
        text=True,
        check=False,
    )
    parent = str(pid)
    found: set[int] = set()
    for line in listing.stdout.splitlines():
        fields = line.split(maxsplit=2)
        if len(fields) < 3 or fields[1] != parent:
            continue
        if os.path.basename(fields[2].split()[0]).startswith(conftest._TEST_SERVER):
            found.add(int(fields[0]))
    return found


@contextlib.contextmanager
def _a_sibling_serving(port: int) -> Iterator[int]:
    """A real `temporal-test-server` on `port`, owned by another process.

    Yields the SERVER's pid — the thing the collision test has to find still
    alive afterwards. Teardown closes the sibling's stdin so its `async with`
    exits normally, then makes sure by pid: a sibling killed without its
    teardown would orphan its own server, and this module refuses to be the
    reason `scripts/temporal_sweep.sh` reports one.
    """
    sibling = subprocess.Popen(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
        [sys.executable, "-c", _SIBLING_PROGRAM, str(port)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert sibling.stdout is not None
        deadline = time.monotonic() + _SIBLING_READY_SECONDS
        ready = ""
        while time.monotonic() < deadline:
            ready = sibling.stdout.readline()
            if ready.strip() == "READY" or ready == "":
                break
        if ready.strip() != "READY":
            raise AssertionError(
                f"the sibling never reported READY on port {port} (exit code {sibling.poll()!r})"
            )
        servers = _test_server_children_of(sibling.pid)
        if not servers:
            raise AssertionError(
                f"the sibling on port {port} reported READY but owns no "
                "temporal-test-server child — the collision this test needs "
                "was never set up"
            )
        yield next(iter(servers))
    finally:
        servers = _test_server_children_of(sibling.pid)
        if sibling.stdin is not None:
            with contextlib.suppress(OSError, ValueError):
                sibling.stdin.close()
        with contextlib.suppress(subprocess.TimeoutExpired):
            sibling.wait(timeout=30)
        if sibling.poll() is None:
            sibling.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                sibling.wait(timeout=10)
        if sibling.stdout is not None:
            with contextlib.suppress(OSError, ValueError):
                sibling.stdout.close()
        # By pid, only ever the pids this fixture watched the sibling father.
        conftest._reap({pid for pid in servers if conftest._alive(pid)})


@pytest.mark.asyncio
async def test_a_named_port_that_nothing_answers_on_is_refused_within_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound is on BOTH branches, or it is on neither.

    The occupant here is not a Temporal server, so the SDK's health probe never
    gets an answer and never gets a refusal either. Unbounded, that is a hang
    that ends when somebody kills the run — and a killed run is exactly what
    leaves the reparented children behind. The guard must end it itself,
    say which port, say what budget it spent, and say that NOTHING ANSWERED,
    which is a different fact from a collision and gets a different sentence.
    """
    monkeypatch.setattr(teardown, "_FIRST_START_SECONDS", _TEST_BUDGET_SECONDS)
    monkeypatch.setattr(teardown, "_LATER_START_SECONDS", _TEST_BUDGET_SECONDS)

    with _a_plain_listener() as port:
        started = time.monotonic()
        with pytest.raises(RuntimeError) as refusal:
            await asyncio.wait_for(
                WorkflowEnvironment.start_time_skipping(port=port),
                timeout=_RED_INSTRUMENT_SECONDS,
            )
        elapsed = time.monotonic() - started

    message = str(refusal.value)
    assert "has been reaped" in message
    assert str(port) in message
    assert "nothing answered" in message.lower()
    assert f"{_TEST_BUDGET_SECONDS:g}s" in message
    # The refusal, not the instrument: the guard ended this, not the test.
    assert elapsed < _RED_INSTRUMENT_SECONDS
    # And it took its own child with it.
    assert conftest._test_server_children() == set()


@pytest.mark.asyncio
async def test_a_real_server_on_the_named_port_still_refuses_with_parentage() -> None:
    """A bound that swallowed the ownership check would be a regression.

    Something answers here — a genuine `temporal-test-server`, owned by another
    process — so the start RETURNS, and returns a client pointed at somebody
    else's server. That is the silent failure the parentage check exists for,
    and it must keep its own message. The sibling's server is untouched
    (`os.kill(pid, 0)` is `kill -0`), our losing child is reaped, and the time
    it took is recorded rather than gated: a threshold here would be a
    wall-clock assertion.

    The words asserted here are the ones the same-process test above asserts,
    deliberately: one sentence, held to being true of both occupants.
    """
    port = _a_free_port()
    with _a_sibling_serving(port) as sibling_server:
        started = time.monotonic()
        with pytest.raises(RuntimeError) as refusal:
            await asyncio.wait_for(
                WorkflowEnvironment.start_time_skipping(port=port),
                timeout=_RED_INSTRUMENT_SECONDS,
            )
        elapsed = time.monotonic() - started

        message = str(refusal.value)
        assert conftest._NOT_THIS_STARTS_CHILD in message
        assert "has been reaped" in message
        # The two facts stay two sentences: this one is not the timeout's.
        assert "nothing answered" not in message.lower()
        # kill -0: the sibling's server survived our refusal.
        os.kill(sibling_server, 0)
        assert conftest._test_server_children() == set()

    warnings.warn(
        f"recorded (not gated): the collision on port {port} was refused in {elapsed:.2f}s.",
        stacklevel=1,
    )


@pytest.mark.asyncio
async def test_our_own_earlier_environment_on_the_named_port_refuses_the_same_way() -> None:
    """The occupant of a collision can be THIS process, and the text knows it.

    Nothing here is a sibling: the port is held by an environment this very
    pytest process started a few lines earlier, and the second start is refused
    anyway — correctly, and for a reason the guard has always had right. Time
    skipping is global to an environment and workflow ids are deterministic by
    house rule 18, so two environments sharing one server would share one clock
    and one id space; the refusal is what keeps `apps/conftest.py`'s header
    promise that a start either drives its OWN server or refuses.

    What was wrong was the sentence. `_the_server_answering_is_ours` asks
    whether the listener is a child THIS START spawned — not whether it belongs
    to some other process — and against this occupant the answer is no while
    "another process" is flatly false. So the message is held to the predicate,
    from both readings at once: this test and the sibling-server test above
    assert the SAME words about two different occupants, which is the only
    way one sentence stays true of both.
    """
    port = _a_free_port()
    async with await WorkflowEnvironment.start_time_skipping(port=port) as first:
        ours = conftest._test_server_children()
        assert conftest._port_of(first) == port
        assert len(ours) == 1, "the occupant of this collision must be our own child"

        with pytest.raises(RuntimeError) as refusal:
            await asyncio.wait_for(
                WorkflowEnvironment.start_time_skipping(port=port),
                timeout=_RED_INSTRUMENT_SECONDS,
            )

        message = str(refusal.value)
        assert "not this start's child" in message
        # The point: there is no other process in this story.
        assert "another process" not in message
        assert "has been reaped" in message
        # The two facts stay two sentences: this one is not the timeout's.
        assert "nothing answered" not in message.lower()
        # The loser was reaped and the FIRST environment was left alone —
        # same pid, and still answering as a time-skipping server.
        assert conftest._test_server_children() == ours
        await first.sleep(timedelta(seconds=1))

    deadline = time.monotonic() + 10.0
    while conftest._test_server_children() and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    assert conftest._test_server_children() == set()


@pytest.mark.asyncio
async def test_cancelling_a_named_port_start_reaps_the_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both branches reap on a cancel, because the reap is in the helper.

    A cancel is not the guard's to swallow — it re-raises — but the child the
    SDK already spawned is its own, and a child whose process is about to go is
    the reparented stray counts.
    """
    monkeypatch.setattr(teardown, "_FIRST_START_SECONDS", _RED_INSTRUMENT_SECONDS)
    monkeypatch.setattr(teardown, "_LATER_START_SECONDS", _RED_INSTRUMENT_SECONDS)

    with _a_plain_listener() as port:
        start = asyncio.ensure_future(WorkflowEnvironment.start_time_skipping(port=port))
        deadline = time.monotonic() + _CHILD_APPEARS_SECONDS
        spawned: set[int] = set()
        while not spawned and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
            spawned = conftest._test_server_children()
        assert spawned, "the SDK never spawned a child, so there was nothing to reap"

        start.cancel()
        with pytest.raises(asyncio.CancelledError):
            await start

    assert conftest._test_server_children() == set()


@pytest.mark.asyncio
async def test_a_named_port_nothing_holds_still_returns_a_working_environment() -> None:
    """The negative. A bound that refuses a legitimate start is the worse bug.

    `env.sleep()` is what makes this more than a socket check: only a real
    time-skipping Temporal test server answers it, so the environment handed
    back is one a workflow test could drive.
    """
    port = _a_free_port()
    async with await WorkflowEnvironment.start_time_skipping(port=port) as environment:
        assert conftest._port_of(environment) == port
        assert conftest._test_server_children()
        await environment.sleep(timedelta(seconds=1))

    deadline = time.monotonic() + 10.0
    while conftest._test_server_children() and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    assert conftest._test_server_children() == set()


# --- the seam is one, and this is what says so -------------------------------
#
# Every promise the guard makes rests on a shape rather than on a behaviour:
# there is exactly ONE place a start is awaited, and the bound is written into
# that one place. The header of `apps/conftest.py` says so ("This is the only
# place `original` is awaited, and that is the whole of it"), and the reason it
# says so is that the two branches once kept a copy each and only one of them
# ended up bounded — the named branch was still waiting past 75 s on the same
# occupant the unnamed branch refused in five.
#
# A second seam breaks no test above. It fails on whichever path nobody drove,
# quietly, exactly as the first one did. So this is the check that reads the
# shape instead of the behaviour — and, because a check that only ever passes
# proves nothing, it plants the second seam into a copy of the source and
# requires itself to object.

_SEAM = "_bounded_start"

# The one await that starts a server; and the two ways this file could write a
# bound. Each belongs inside the seam and nowhere else — a bound outside it is
# a second answer to "how long may a start take", which is the drift itself.
_ONE_AND_ONLY = "await original("
_BOUNDS = ("asyncio.timeout(", "asyncio.wait_for(")


def _seam_complaints(source: str) -> list[str]:
    """What is wrong with the SHAPE of `source`, as sentences. Empty is green.

    Reads text rather than the imported module on purpose: what is being
    checked is not what the guard does but that there is only one place it
    could be done from, and an import cannot see a second copy that nothing has
    called yet.

    The helper's line span comes from the AST (`end_lineno`), so "inside the
    seam" means what Python means by it rather than what an indentation guess
    would mean. Everything after that is a token count, which is the same grep
    a prior seam-check proposed — with a scope it can be honest about.
    """
    lines = source.splitlines()
    spans = [
        (node.lineno, node.end_lineno or node.lineno)
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == _SEAM
    ]
    if len(spans) != 1:
        return [f"`{_SEAM}` is defined {len(spans)} time(s); one seam means one definition"]
    first, last = spans[0]

    def outside(token: str) -> list[int]:
        return [
            number
            for number, line in enumerate(lines, start=1)
            if token in line and not first <= number <= last
        ]

    complaints: list[str] = []
    awaits = source.count(_ONE_AND_ONLY)
    if awaits != 1:
        complaints.append(
            f"`{_ONE_AND_ONLY}` appears {awaits} time(s); the start is awaited in exactly one "
            "place or the bound is not on every start"
        )
    for token in (_ONE_AND_ONLY, *_BOUNDS):
        strays = outside(token)
        if strays:
            complaints.append(
                f"`{token}` appears outside `{_SEAM}`, at line(s) "
                + ", ".join(str(number) for number in strays)
            )
    return complaints


def test_the_bounded_start_seam_is_the_only_one() -> None:
    """One place awaits the start, one place bounds it — read, not assumed.

    Three assertions, and the last two are what make the first mean anything:
    the live file is clean, a planted second await makes this same check object,
    and so does a planted second bound. The plants go into a COPY of the source
    held in memory; nothing on disk is touched, so this leaves the tree exactly
    as it found it however it ends.

    Declared blind spot, inherited from the grep a prior seam-check proposed: a third
    bounded-start shape that spells neither `await original(` nor either
    timeout — a wrapper around the wrapper, or a bound imported from elsewhere
    — is invisible here. This proves the seam is one, not that a seam is the
    only way to write one.
    """
    source = Path(teardown.__file__).read_text(encoding="utf-8")

    assert source.count(_ONE_AND_ONLY) == 1
    assert _seam_complaints(source) == [], "the live guard has grown a second seam"

    a_second_await = source + (
        "\n\nasync def _another_way_in(original: Any, kwargs: dict[str, Any]) -> Any:\n"
        "    return await original(**kwargs)\n"
    )
    complaints = _seam_complaints(a_second_await)
    assert any(_ONE_AND_ONLY in complaint for complaint in complaints), (
        "a second await outside the seam went unnoticed, so the check above proves nothing"
    )

    a_second_bound = source + (
        "\n\nasync def _another_bound(started: Any) -> Any:\n"
        "    return await asyncio.wait_for(started, timeout=1.0)\n"
    )
    complaints = _seam_complaints(a_second_bound)
    assert any("asyncio.wait_for(" in complaint for complaint in complaints), (
        "a bound written outside the seam went unnoticed — the drift measured earlier"
    )
