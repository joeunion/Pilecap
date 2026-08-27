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
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

# Long enough that a loaded machine does not fail a passing test, short enough
# that a genuinely silent socket does not hold the suite up.
TIMEOUT = 2.0

# What "nothing arrived" is worth waiting for. A push travels in-process
# through the in-memory channel layer, so if it were coming it would be here.
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
        """Offer the connection and read the server's answer."""
        self._task = asyncio.create_task(
            self._application(self.scope, self._to_app.get, self._from_app.put)
        )
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
        frame would report "nothing arrived" and hide the reason. Ask this
        first and the failure names itself.
        """
        return self._task is not None and not self._task.done()

    def failure(self) -> BaseException | None:
        """Whatever killed the application task, if something did."""
        if self._task is None or not self._task.done() or self._task.cancelled():
            return None
        return self._task.exception()

    async def output(self, timeout: float = TIMEOUT) -> dict[str, Any]:
        """The next ASGI message the application sent, whatever it is."""
        return await asyncio.wait_for(self._from_app.get(), timeout)

    async def send_json(self, data: dict[str, Any]) -> None:
        await self._to_app.put({"type": "websocket.receive", "text": json.dumps(data)})

    async def send_bytes(self, data: bytes) -> None:
        await self._to_app.put({"type": "websocket.receive", "bytes": data})

    async def receive_json(self, timeout: float = TIMEOUT) -> Any:
        message = await self.output(timeout)
        assert message["type"] == "websocket.send", message
        return json.loads(message["text"])

    async def received_nothing(self, timeout: float = QUIET) -> bool:
        try:
            message = await self.output(timeout)
        except TimeoutError:
            return True
        raise AssertionError(f"Expected silence on this socket, got {message!r}")

    async def close(self) -> None:
        """Hang up, and let the consumer finish so nothing is left running."""
        await self._to_app.put({"type": "websocket.disconnect", "code": NORMAL_CLOSURE})
        if self._task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(self._task), TIMEOUT)
        except (TimeoutError, asyncio.CancelledError):
            self._task.cancel()


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
