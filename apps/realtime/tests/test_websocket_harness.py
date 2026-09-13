"""The socket test client's own guards — `tests/websocket.py` under test.

**Why a test file has tests.** `websocket.py` is not a helper any more; it is
the shared machinery behind every socket assertion in this app — 15
`received_nothing()` call sites across six modules, plus every `open()`,
`output()` and `receive_json()` those modules make — and since SENT-1 it
carries an ORDERING INVARIANT that is not obvious by reading it: when the
application's task stops, `_ENDED` enters the outbound queue *behind* every
frame the application really sent, and every arrival wait relies on that to
tell "nothing is coming" from "nothing has come yet" without consulting a
clock. An invariant that subtle, holding up that many assertions, with nothing
watching it, is how a harness quietly stops proving anything.

**None of these need a database, so they cost the suite almost nothing.** They
drive tiny hand-written ASGI applications rather than the real consumer, which
is what lets them arrange the adverse orderings on purpose.

Each one BREAKS something and asserts the harness says so BY ITS OWN NAME. That
last part is the sibling's fix-round lesson, taken in with the sentinel: the
dead-socket guard has two independently reachable halves, both of which used to
end in "proves nothing", and pinning only that shared substring meant either
half could be deleted with every socket test still green. A severance that
reddens nothing is not a guard.
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any

import pytest

from apps.realtime.tests.websocket import Socket, open_socket

pytestmark = [pytest.mark.asyncio]

PATH = "/ws/events/"

#: Bounds only the FAILING path of the dies-during-the-window claim. On the
#: passing path the sentinel arrives in a handful of ready-queue hops and this
#: is never approached; if the mechanism is broken the test waits this long and
#: then fails. Deliberately far above `QUIET`'s 0.2s default so that no amount
#: of contention can let the window expire before a `call_soon` chain completes
#: — the wait here is not the property, and this is the one place in the app
#: where a generous number is the right answer rather than the old bet.
GENEROUS = 30.0


async def test_an_application_that_dies_instead_of_accepting_is_named() -> None:
    """The handshake's guard. Before SENT-1 this was a 2.0s `TimeoutError`.

    Beyond criterion 4's named five, and kept because it is the only claim that
    covers `open()`'s own unbounded read — the wait that cost the sibling a gate
    at `websocket.py:106`. A stopwatch could only ever report that two seconds
    had passed; the sentinel reports WHY, which is what a reader of the failure
    actually needs.
    """

    async def dead_application(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        raise RuntimeError("the consumer fell over instead of accepting")

    socket = Socket(dead_application, PATH, [])
    with pytest.raises(AssertionError) as caught:
        await socket.open()
    assert "stopped without sending anything more" in str(caught.value)
    assert "fell over instead of accepting" in str(caught.value)


async def test_a_parked_reader_gets_the_last_frame_before_the_sentinel() -> None:
    """Claim 1 — sentinel ordering, in the arrangement that can actually go wrong.

    **This is the hard case, and the one the mechanism is FOR.** The test below
    pins the easy arrangement — every frame already in the queue before the
    first read — where nothing races because nothing is concurrent. The shape
    that matters is the opposite: a reader already parked inside `Queue.get()`
    at the moment the frame lands and the application dies in the same breath.
    If `_ENDED` could overtake that last frame, a live socket's final message
    would be reported as "the application stopped without sending anything
    more", and the failure mode SENT-1 removed would come straight back in a new
    coat.

    Arranged with no timers: `output()` suspends in `get()` on an empty queue
    before the loop can run the `call_soon` below, so the reader is provably
    parked when the application wakes, sends and raises.

    **What this locks, and what it does not** — the sibling measured this and it
    is taken in rather than re-derived: it reddens against a reader that prefers
    the task's death over the frame already in its hand, but NOT against a
    race-the-task design (`asyncio.wait` on frame-or-task, take the frame if
    ready), which happens to answer correctly in this interleaving because
    `put_nowait` wakes the getter before the task's completion callback runs.
    Nor against a reader that consults task-doneness before draining — the
    queue-populated case below catches that one. So this LOCKS THE ARRANGEMENT
    rather than discriminating between designs. The sentinel is still the one to
    keep, because its correctness is FIFO and not an argument about callback
    insertion order.
    """
    gate = asyncio.Event()

    async def sends_and_dies_in_one_breath(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "websocket.accept", "subprotocol": None})
        await gate.wait()
        await send({"type": "websocket.send", "text": '{"last": true}'})
        raise RuntimeError("sent and fell over together")

    socket = Socket(sends_and_dies_in_one_breath, PATH, [])
    assert (await socket.open()).accepted is True
    asyncio.get_running_loop().call_soon(gate.set)
    # Parked in `get()` on an empty queue, then the frame and the death arrive.
    assert await socket.receive_json() == {"last": True}
    # And only then the sentinel, carrying the reason.
    with pytest.raises(AssertionError) as caught:
        await socket.output()
    assert "stopped without sending anything more" in str(caught.value)
    assert "sent and fell over together" in str(caught.value)


async def test_frames_sent_before_the_end_are_read_before_the_sentinel() -> None:
    """Claim 2 — the sentinel goes BACK, so a second read answers identically.

    The same ordering invariant in the easy arrangement (queue fully populated
    first), kept beside the parked-reader case rather than replaced by it,
    because it is the one that pins REPEATABILITY: reading past the end twice
    answers the same way rather than hanging. That matters more here than it
    did before SENT-1 — a hang now costs `pyproject.toml`'s 720s ceiling instead
    of a 2s `TimeoutError`, so a harness that hung on the second read would
    convert a clear failure into twelve silent minutes.

    The loop reads THREE times past the end, not two: a put-back that fired only
    once would satisfy a single re-read.
    """

    async def sends_then_stops(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "websocket.accept", "subprotocol": None})
        await send({"type": "websocket.send", "text": '{"n": 1}'})
        await send({"type": "websocket.send", "text": '{"n": 2}'})
        await send({"type": "websocket.close", "code": 4000})

    socket = Socket(sends_then_stops, PATH, [])
    assert (await socket.open()).accepted is True
    assert await socket.receive_json() == {"n": 1}
    assert await socket.receive_json() == {"n": 2}
    assert await socket.output() == {"type": "websocket.close", "code": 4000}
    for _ in range(3):
        with pytest.raises(AssertionError) as caught:
            await socket.output()
        assert "stopped without sending anything more" in str(caught.value)


async def accepts_then_falls_over(scope: Any, receive: Any, send: Any) -> None:
    """An application that gets through the handshake and then dies."""
    await receive()
    await send({"type": "websocket.accept", "subprotocol": None})
    raise RuntimeError("the consumer fell over after accepting")


async def test_close_never_masks_the_tests_own_failure() -> None:
    """Claim 3a — teardown stays silent about its own troubles.

    `close()` runs in `open_socket`'s `finally`, which is the one place an
    exception does the most damage: it REPLACES whatever the test was actually
    failing on, and the report then blames the harness for the consumer's
    death — or blames the consumer for the test's. Here the body raises its own
    distinctive failure while the application is dead underneath it, and that is
    the failure that must arrive, with the consumer's `RuntimeError` nowhere in
    it.

    `failure()` afterwards is the readability half: the exception is dropped
    from the task's point of view, not from the reader's.
    """
    held: list[Socket] = []
    with pytest.raises(AssertionError) as caught:
        async with open_socket(accepts_then_falls_over, PATH, []) as (socket, handshake):
            assert handshake.accepted is True
            held.append(socket)
            raise AssertionError("the test's own failure, which teardown must not replace")

    # The test's failure survived teardown; the consumer's did not overwrite it.
    assert "the test's own failure" in str(caught.value)
    assert "fell over after accepting" not in str(caught.value)
    # And the consumer's exception is still readable afterwards.
    failure = held[0].failure()
    assert isinstance(failure, RuntimeError)
    assert "fell over after accepting" in str(failure)


async def test_close_retrieves_the_exception_rather_than_leaving_it_to_the_collector() -> None:
    """Claim 3b — the RETRIEVAL half, and it needs its own test to be provable.

    **Why this is not folded into the test above.** That one reads
    `socket.failure()`, and `failure()` calls `Task.exception()` itself — so it
    answers identically whether or not `close()` ever retrieved anything.
    Deleting `close()`'s retrieval line leaves it green. A guard that cannot
    tell the severed harness from the whole one is the shape this whole rung
    exists to refuse, so the claim is split out and driven where it discriminates.

    **What breaks when the retrieval is gone.** An exception left on a task
    nobody asked about is reported by `Task.__del__` through the loop's
    exception handler — "Task exception was never retrieved" — at COLLECTION
    time, which is to say in whatever test happened to be running when the
    garbage collector got round to it. A red in a module that never opened a
    socket is the worst kind of failure to be handed.

    Arranged with no durations: the loop's handler is swapped for a recorder,
    the socket is dropped, and the collector is run by hand. `Task.__del__`
    calls the handler synchronously, so there is nothing to wait for — and
    nothing here reads `failure()`, which would do the retrieving the assertion
    is about.
    """
    reported: list[dict[str, Any]] = []
    loop = asyncio.get_running_loop()
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    try:
        async with open_socket(accepts_then_falls_over, PATH, []) as (socket, handshake):
            assert handshake.accepted is True
        del socket
        gc.collect()
    finally:
        loop.set_exception_handler(previous)

    unretrieved = [c for c in reported if "never retrieved" in str(c.get("message", ""))]
    assert unretrieved == [], f"close() left the task exception for the collector: {unretrieved!r}"


async def test_a_socket_dead_BEFORE_the_window_is_not_called_quiet() -> None:
    """Claim 4 — half one of the dead-socket guard: the `alive` pre-check.

    A crashed consumer used to read exactly like a correctly filtered event:
    nothing, for 0.2 seconds, `True`. All 15 `received_nothing` call sites in
    this app were one dead consumer away from passing for the wrong reason.

    **Pinned on "had already stopped", not on "proves nothing".** The shared
    half of the sentence is what the other branch says too, so asserting only
    that let the sibling's verifier delete this pre-check outright with every
    socket test still green. The negative assert is the half that makes this
    test discriminate.
    """

    async def dies_after_accept(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "websocket.accept", "subprotocol": None})
        raise RuntimeError("nobody is home")

    socket = Socket(dies_after_accept, PATH, [])
    assert (await socket.open()).accepted is True
    # The application is already gone by the time the caller asks.
    assert socket.alive is False
    with pytest.raises(AssertionError) as caught:
        await socket.received_nothing()
    assert "had already stopped" in str(caught.value)
    assert "during the quiet window" not in str(caught.value)
    assert "nobody is home" in str(caught.value)


async def test_a_socket_that_dies_DURING_the_window_is_not_called_quiet() -> None:
    """Claim 5 — half two: the `_ENDED`-inside-the-window branch.

    The application must be alive when `received_nothing` looks — so the
    pre-check passes and cannot be what fires — and must then die while the
    caller is parked in the wait. That is arranged with a `call_soon` chain and
    no timers: `received_nothing` runs its `alive` check synchronously before it
    suspends, so the gate below is still shut at that moment; the loop then sets
    it, the application wakes, raises, and its done-callback queues `_ENDED`
    while the caller is still in `get()`.

    Every hop is a ready-queue hop, so no amount of load can reorder them
    against a clock — which is why `GENEROUS` may be passed here without
    reintroducing the thing SENT-1 removed.
    """
    gate = asyncio.Event()

    async def dies_when_told(scope: Any, receive: Any, send: Any) -> None:
        await receive()
        await send({"type": "websocket.accept", "subprotocol": None})
        await gate.wait()
        raise RuntimeError("died while you were listening")

    socket = Socket(dies_when_told, PATH, [])
    assert (await socket.open()).accepted is True
    # Alive at the moment of the pre-check: this is the half under test.
    assert socket.alive is True
    asyncio.get_running_loop().call_soon(gate.set)
    with pytest.raises(AssertionError) as caught:
        await socket.received_nothing(timeout=GENEROUS)
    assert "during the quiet window" in str(caught.value)
    assert "had already stopped" not in str(caught.value)
    assert "died while you were listening" in str(caught.value)
