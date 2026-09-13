"""A websocket client for tests, speaking raw ASGI to a real application.

**Why this is not `channels.testing.WebsocketCommunicator`.**
`channels/testing/__init__.py` imports `ChannelsLiveServerTestCase`, which
imports `daphne`, and this repository serves ASGI with `uvicorn` and does not
install daphne. Any import under `channels.testing` runs that `__init__` and
fails. Adding a server this template does not use as a development dependency
is the wrong trade — so the forty lines of the communicator this app actually
needs live here instead, typed, with no dependency of their own.

**Ruled: keep this client, do not add daphne.** The gap was
reported rather than papered over, and it was `build-contract.md` that moved:
it and the conventions skill now name this module as the socket test client,
so nothing in the contract points at a class the repository cannot import.

The application is driven exactly as a server drives it — two queues and a
task — which is the same shape `apps/core/tests/test_mcp.py` uses to run a
lifespan. Nothing about the stack under test is stubbed.

**Nothing here waits on a clock to decide a frame is not coming, and that is
SENT-1's result.** Every arrival wait is unbounded and settled by the
application's own task instead; the one duration left is `QUIET`, where the
absence IS the claim. The reasoning and the measurements are at `_ENDED` and
`QUIET` below.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

# **There is no arrival timeout here any more, and that is SENT-1's result.**
# There used to be a `TIMEOUT = 2.0` that every arrival wait in this module
# compared the box against — `output()`, `receive_json()` and `close()`,
# behind 15 `received_nothing()` call sites and every socket assertion in six
# modules. A duration cannot tell "the door will never answer" from "the door
# has not answered YET", so what it actually measured was the machine.
#
# **The class rule behind the change is the sibling's FLAKE-1, adopted here:
# prove by construction, never widen a margin.** The cheaper fix was 2.0 -> 5.0.
# It was rejected because a wider bet is still a bet, and this box is the
# counterexample generator: it has been measured at **load average 162 on 10
# cores** here during a six-wide builder wave, with `--loop` wall clocks of
# 1375s / 1491s / 2037s against 657s once the wave thinned. Nothing about a
# socket door changes across that spread; only the stopwatch does.
#
# The sibling's own instrumentation of the identical harness (their
# `apps/realtime/tests/websocket.py` @ ed58392, the intake evidence) measured
# `Socket.open()` at load 214: min 0.036s, median 0.049s, max 0.237s
# in memory, and min 0.042s / median 0.170s / **max 0.347s** on the real Redis
# layer. A seven-fold spread with the door unchanged. Their 2.0s budget
# delivered its verdict at ~2.5s — a loop that is not running cannot run its own
# timer either — with the accept frame landing some 40ms after that: mid-answer
# when the clock gave up. No arrival deadline can tell that apart from a door
# that never will.
#
# **What replaced it is `_ENDED`.** The application's task is watched instead of
# the clock: when it stops, for any reason, a sentinel goes into the outbound
# queue BEHIND every frame the application actually sent. An arrival wait is
# then a plain, unbounded `Queue.get()` — it returns the next real frame, or it
# returns the sentinel, which means the application stopped and names why.
# Ordering does the work a duration used to do badly, and the answer no longer
# depends on how busy the box is.
#
# **What the ordering rests on, stated so it can be checked.** `_ENDED` is
# queued by the task's own done-callback, so it lands behind every frame sent
# FROM THE APPLICATION TASK — that task cannot both still be sending and be
# done. It does NOT order behind a send from a task the application DETACHED: a
# consumer doing `asyncio.create_task(...)` and sending from inside it could
# have that frame land after the sentinel, and a reader would then call a live
# socket stopped. Checked by grep over `apps/realtime/`: the only task spawned
# anywhere in this app is `open()`'s own below — the very task this sentinel
# rides on, held on `self._task` rather than detached. `consumers.py`
# and `bridge.py` spawn nothing. That is why this is a precondition to name
# rather than a bug to fix, and it is a LIVE precondition: **a consumer that
# grows a detached task must not send from it**, or this sentinel starts calling
# live sockets dead. Nothing in the gate enforces that; this comment and the
# rung's report are the whole of the warning.
#
# **Liveness is the tree's ceiling, not this module's.** An unbounded read needs
# something above it or a genuinely stuck consumer hangs the suite silently.
# That ceiling is `timeout = 720` in `pyproject.toml`, with
# `timeout_method = "signal"` and `timeout_func_only` deliberately left false so
# it covers setup + call + teardown — its own comment argues all three at
# length, and names itself THE ONE CONFIG SITE for the number.
#
# The trade is LOUDER IN KIND AND QUIETER IN CONTENT. pytest-timeout's report on
# an async hang names the test but not a user frame, where the old `TimeoutError`
# pointed at a line in this file. What it gives back is an ordinary red the gate
# exits 1 on instead of a suite sitting silent — and it costs 720s where the old
# answer came in 2s. That applies to `close()` too, which now waits on teardown
# without a deadline rather than cancelling a consumer mid-disconnect.
_ENDED: dict[str, Any] = {"type": "websocket.__application-stopped__"}

# What "nothing arrived" is worth waiting for. **This one is still a duration,
# on purpose, because here the duration IS the claim** — the caller is asserting
# that a push was dropped, and only elapsed silence can say so. It is a
# different animal from the arrival waits above and it cannot flake the way they
# did: a loaded box makes this window pass MORE easily, never less, so its
# failure mode is a false green and never a red. What rules out "the socket was
# simply dead" is `received_nothing`'s own two guards below, and the frame the
# caller asserts next.
QUIET = 0.2

NORMAL_CLOSURE = 1000


@dataclass(frozen=True)
class Handshake:
    """What the server answered the connection offer with."""

    accepted: bool
    code: int | None


class Socket:
    """One websocket connection to an ASGI application."""

    def __init__(
        self,
        application: Any,
        path: str,
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        parsed = urlparse(path)
        self.scope: dict[str, Any] = {
            "type": "websocket",
            "path": unquote(parsed.path),
            "raw_path": parsed.path.encode(),
            "query_string": parsed.query.encode(),
            "headers": headers or [],
            "subprotocols": [],
            "client": ("127.0.0.1", 51000),
            "server": ("testserver", 80),
        }
        self._application = application
        self._to_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._from_app: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._task: asyncio.Task[Any] | None = None

    async def open(self) -> Handshake:
        """Offer the connection and read the server's answer.

        The wait for the answer is unbounded and that is deliberate: what this
        asserts is that the application ANSWERED and which answer it gave, never
        that it answered quickly. The done-callback below is what makes an
        unbounded wait safe — whatever ends the application task, in whatever
        way, puts `_ENDED` behind the frames it had already sent, so a consumer
        that dies during the handshake surfaces as its own exception rather than
        as a stopwatch expiring on a door that was about to answer.
        """
        self._task = asyncio.create_task(
            self._application(self.scope, self._to_app.get, self._from_app.put)
        )
        self._task.add_done_callback(lambda _: self._from_app.put_nowait(_ENDED))
        await self._to_app.put({"type": "websocket.connect"})
        answer = await self.output()
        if answer["type"] == "websocket.close":
            return Handshake(accepted=False, code=int(answer.get("code", NORMAL_CLOSURE)))
        assert answer["type"] == "websocket.accept", answer
        return Handshake(accepted=True, code=None)

    @property
    def alive(self) -> bool:
        """Whether the application is still running this connection.

        A consumer that died — the channel layer raised underneath it, say —
        stops answering rather than closing, so a test that only waited for a
        frame would report "nothing arrived" and hide the reason.

        **Since SENT-1 nobody has to remember to ask.** `_ENDED` makes the
        harness itself name that failure at every wait, which is why the two
        remaining callers of this property (`test_doors_over_the_wire`, and
        `received_nothing` below) read as belt and braces rather than as the
        only thing standing between a dead socket and a green test.
        """
        return self._task is not None and not self._task.done()

    def failure(self) -> BaseException | None:
        """Whatever killed the application task, if something did."""
        if self._task is None or not self._task.done() or self._task.cancelled():
            return None
        return self._task.exception()

    async def output(self) -> dict[str, Any]:
        """The next ASGI message the application sent, whatever it is.

        **No deadline, and no argument to give it one.** A parameter nobody can
        honour is a lie, and the one call site in this tree that passed a bigger
        number (`test_doors_over_the_wire`'s `PUSH_TIMEOUT = 5.0`) was buying
        margin, not meaning — it is gone with this signature.

        The queue is FIFO and `_ENDED` was put behind every frame the
        application really sent, so this returns real frames first and reaches
        the sentinel only when there are none left and none coming. The sentinel
        goes back so that a second read after the end answers the same way
        instead of hanging — which matters more now that hanging costs the 720s
        ceiling rather than two seconds.
        """
        message = await self._from_app.get()
        if message is _ENDED:
            self._from_app.put_nowait(_ENDED)
            raise AssertionError(
                "the application stopped without sending anything more "
                f"(failure: {self.failure()!r})"
            )
        return message

    async def send_json(self, data: dict[str, Any]) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def send_bytes(self, data: bytes) -> None:
        await self._to_app.put({"type": "websocket.receive", "bytes": data})

    async def receive_json(self) -> Any:
        message = await self.output()
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])

    async def received_nothing(self, timeout: float = QUIET) -> bool:
        """That the push just sent did NOT reach this socket.

        The only wait in this module that is still a duration, and the reason is
        in `QUIET`'s own comment: an absence has nothing to be woken by. It is
        also the only wait whose error is one-sided — a slow box makes it likelier
        to pass, never to fail — so it is not the shape that cost the sibling a
        gate, and widening it would not have been the same kind of bet.

        **What it will no longer do is call a corpse quiet.** Before SENT-1 a
        consumer that had crashed produced exactly the same reading as a
        correctly filtered event: nothing, for 0.2 seconds, `True`.

        **That hole has TWO ends, and they are two separate claims** — which is
        the sibling's fix round (their 05b499f), taken in with the sentinel. The
        application was already dead when the caller asked (the pre-check
        below), or it dies inside the window and `_ENDED` arrives (the branch
        after the wait). Each end is reachable without the other, so each carries
        its OWN wording — "had already stopped" against "during the quiet
        window" — and `test_websocket_harness` pins the DISTINGUISHING half of
        each. Their round found out why that matters the expensive way: both
        branches ended in "proves nothing", only that shared substring was
        asserted, and a verifier deleted either end alone with every socket test
        still green. A guard whose halves cannot be told apart is one guard
        wearing two coats.
        """
        if not self.alive:
            raise AssertionError(
                "this socket's application had already stopped, so its silence "
                f"proves nothing (failure: {self.failure()!r})"
            )
        try:
            message = await asyncio.wait_for(self._from_app.get(), timeout)
        except TimeoutError:
            return True
        if message is _ENDED:
            self._from_app.put_nowait(_ENDED)
            raise AssertionError(
                "the application stopped during the quiet window, so this "
                f"silence proves nothing (failure: {self.failure()!r})"
            )
        raise AssertionError(f"Expected silence on this socket, got {message!r}")

    async def close(self) -> None:
        """Hang up, and let the consumer finish so nothing is left running.

        **Unbounded since SENT-1, and that is a fix rather than a relaxation.**
        This used to give the consumer `TIMEOUT` seconds and then CANCEL it,
        which on a loaded box meant tearing down a consumer in the middle of an
        orderly disconnect — the one shape that can leave a group membership
        behind in a real Redis layer and bleed into the next test. Waiting is
        what "let the consumer finish" already said it did.

        **And it is priced in TEARDOWN, which is the expensive place to spend.**
        A consumer that ignores `websocket.disconnect` used to be cancelled here
        at 2s and let the test pass; it now runs to `pyproject.toml`'s 720s
        ceiling, and because that ceiling deliberately covers setup + call +
        teardown (its own comment explains why), the red lands on whichever test
        was holding the socket. Correct, and not cheap — the same trade the
        arrival waits make, in the phase where it costs most.

        Nothing here can raise: the application's exception is retrieved rather
        than propagated, because this runs in `open_socket`'s `finally` and an
        exception from a cleanup path would replace the test's own failure with
        a worse one. `failure()` is where that exception stays readable.
        """
        await self._to_app.put({"type": "websocket.disconnect", "code": NORMAL_CLOSURE})
        if self._task is None:
            return
        await asyncio.wait([self._task])
        if not self._task.cancelled():
            # Retrieved and deliberately dropped. Not dead code: asyncio logs
            # "Task exception was never retrieved" at collection otherwise, and
            # that line would arrive detached from the test that earned it.
            # `failure()` reads the same exception again whenever a test asks.
            self._task.exception()


@asynccontextmanager
async def open_socket(
    application: Any,
    path: str,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> AsyncIterator[tuple[Socket, Handshake]]:
    """Open a socket, hand it and the handshake to the test, always hang up."""
    socket = Socket(application, path, headers)
    try:
        yield socket, await socket.open()
    finally:
        await socket.close()
