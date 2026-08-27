"""Planted: `apps/accounts` grows a socket door while its REST/MCP pair is unpaid.

THE RATCHET REFUSING TO GROW. `accounts` is recorded at one unanswered pair — it
has both halves of the (rest, mcp) pair and no test claiming it — and that debt
is a standing note, not a pass. Adding a `consumers.py` takes on a SECOND debt in
the same class, which is one over the recorded number, and at that point every
finding in the class becomes a violation naming the growth.

This is the form that proves the backlog cannot be used as an allowance: an app
already in debt does not get to open a new door for free.
"""

from __future__ import annotations

from typing import Any


class ConnectionEvents:
    """A socket door: session cookie and bearer token both reach it."""

    async def connect(self) -> None: ...

    async def receive_json(self, content: Any) -> None: ...
