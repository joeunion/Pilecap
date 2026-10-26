"""The socket contract: what goes down the wire, and how a refusal is spelled.

Pydantic, like every other door in this repository, so that a socket client and
a REST client are reading the same shapes — the payload inside `EventMessage`
is literally the `Out` schema the REST route returns for the same row
(`django-conventions` §8: "payloads are schemas").

The close codes live here rather than next to the code that sends them because
they are contract too. A client that gets `4403` has to be able to tell "you
are not signed in" from "you are signed in but you belong to no tenant" without
reading the server, and a code invented at each call site is a code that drifts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from ninja import Schema
from pydantic import Field

from apps.core.schemas import example

# The application close codes. 4000-4999 is the range RFC 6455 reserves for
# private use, and these deliberately echo the HTTP statuses their reasons map
# to, so `4401` reads as "401 on a socket" to anyone who has met either.
CLOSE_UNAUTHENTICATED = 4401
"""No principal: no session, no bearer token, or a token that does not resolve."""

CLOSE_NO_TENANT = 4403
"""A real user with no tenant to act in. Tenancy fails closed on every door."""

CLOSE_NOT_A_COMMAND = 4400
"""The client sent something other than a ping. There are no client commands."""

CLOSE_KICKED = 4410
"""The principal behind this socket is gone — the token was revoked, or the user
was erased. "410 on a socket", and deliberately not `4401`: a client that reads
`4401` retries the handshake with the credential it has, which is exactly the
wrong move when that credential is the thing that stopped existing. This one says
*do not come back with this*. Sent by `bridge.kick_user`; see ADR realtime-2 (d).
"""

CLOSE_TOO_MANY_SOCKETS = 4429
"""429 on a socket: the credential or tenant is at its socket ceiling, or the count is unread."""

CLOSE_SESSION_EXPIRED = 4419
"""419 ("session expired" in some frameworks) on a socket: the session that opened it ended."""


# rule-16: the socket frame's published component name; renaming it moves the wire
class EventMessage(Schema):
    """One thing that happened, pushed to everyone connected for its tenant.

    `v` is the payload's version, not the envelope's (`architecture.md`, "`v` on
    every payload"): the envelope is this class and changes by adding optional
    fields, while a payload's shape belongs to the app that emitted it and needs
    its own number for a subscriber to branch on.

    `payload` is `dict[str, Any]` and that is the one place a bare dict is
    right. The conventions refuse a `dict` crossing a door because it is a
    contract nobody can read — but this envelope carries *another app's*
    schema, already serialised by `emit()`, and naming a union of every event
    type a product will ever declare would make `apps/realtime` depend on every
    app in the system. The typed shape is the emitting app's `Out` schema; this
    is the truck it rides in.

    `correlation_id` is the join key from `core.context` — the same value on the
    `Event` row, the `WorkflowRun`, the `AuditEntry` and the outbound webhook
    header, so a client can quote it in a support ticket and one query finds
    everything that chain touched.

    `organization_id` is **which part of the tenant this event belongs to**, and
    it is what the fan-out narrows on: an event carrying one goes to that
    branch's group and reaches the hats whose subtree contains it, while an
    event without one is tenant-wide and goes to the tenant's group (ADR
    realtime-2 b). It rides the envelope rather than the bridge signature (ADR
    realtime-2a) because the envelope is the one serialisation both the webhook
    door and the socket door are handed — `apps.events` cannot import this
    schema to build a second one, and a fan-out cannot narrow on a field it
    cannot see. Optional and defaulted, so a body composed before the column
    existed still validates.
    """

    name: str
    v: int = 1
    payload: dict[str, Any]
    correlation_id: str | None = None
    organization_id: UUID | None = None
    occurred_at: datetime


#: The ticket door's scope family; the event stream itself is no family's door (`_joins_on`).
TICKET_FAMILY = "socket-tickets"


class SocketTicketOut(Schema):
    """A socket ticket: present it once as `?ticket=` on `ws/events/` within `expires_in` s."""

    ticket: str = Field(..., json_schema_extra=example("q3Vb0cX9-one-use-ticket"))
    expires_in: int = Field(..., json_schema_extra=example(60))
    expires_at: datetime = Field(..., json_schema_extra=example("2026-10-23T18:01:00Z"))
