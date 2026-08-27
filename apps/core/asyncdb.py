"""Running ORM work from async code without leaking database connections.

Django's request/response cycle closes stale connections for you. The MCP mount,
the socket middleware and Temporal activities have no request cycle, so a naive
`sync_to_async(...)` opens a connection in a worker thread and leaves it open —
one per thread, forever. `run_db` is the one way this repository crosses that
boundary, and it closes what it opened.

`run_async` crosses it the other way, and exists for exactly one caller: a
`transaction.on_commit` hook that has to talk to an async client (Temporal).
It refuses to run inside a live event loop rather than deadlocking there, which
is the failure a bare `asyncio.run` gives you at 3am.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from asgiref.sync import sync_to_async
from django.db import close_old_connections


async def run_db[**P, R](func: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
    """Run a synchronous, database-touching callable off the event loop."""

    def call() -> R:
        close_old_connections()
        try:
            return func(*args, **kwargs)
        finally:
            close_old_connections()

    return await sync_to_async(call, thread_sensitive=False)()


def run_async[R](make_coroutine: Callable[[], Coroutine[Any, Any, R]]) -> R:
    """Run a coroutine to completion from synchronous code, in its own loop.

    Used by `transaction.on_commit` hooks: the hook is called synchronously,
    right after the commit, by whichever thread committed — a Django request
    thread, a management command, a `sync_to_async` worker thread. None of them
    has a running loop, so a fresh one is correct and cheap.

    A *coroutine factory* rather than a coroutine, so that the refusal below
    does not leave an un-awaited coroutine behind for Python to warn about.

    It refuses rather than improvises when a loop is already running: calling
    this from async code would block the loop it is running on, forever. Async
    callers await the async API directly (`start_workflow(client=...)`) — which
    is why that one still exists.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(make_coroutine())
    raise RuntimeError(
        "run_async was called from a running event loop. Await the async API "
        "directly instead; this helper is for synchronous callers only."
    )
