"""The socket door's test helpers: an event, a token, a ticket, a socket on the real application."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.realtime.schemas import EventMessage
from apps.realtime.services import issue_socket_ticket
from apps.realtime.tests.websocket import Handshake, Socket, open_socket

PATH = "/ws/events/"


def an_event(name: str = "example.widget.created") -> EventMessage:
    """One event, shaped the way a service's `emit()` will shape it."""
    return EventMessage(
        name=name,
        v=1,
        payload={"id": "8f14e45f-ea1e-7c2b-8000-000000000001", "name": "A widget"},
        correlation_id="c0ffee",
        occurred_at=timezone.now(),
    )


async def a_token(*, user: User, tenant: Tenant, name: str = "socket") -> str:
    """A real `ApiToken` for this user, pinned to this tenant."""
    _, plaintext = await run_db(
        issue_token,
        user=user,
        tenant=tenant,
        name=name,
        actor=actor_for(user=user, tenant=tenant),
    )
    return plaintext


async def a_ticket(*, user: User, tenant: Tenant, name: str = "socket") -> str:
    """A one-use socket ticket for this user in this tenant, from the REST door's service."""

    def issue() -> str:
        token, _ = issue_token(
            user=user, tenant=tenant, name=name, actor=actor_for(user=user, tenant=tenant)
        )
        actor = actor_for(user=user, tenant=tenant, kind="agent", token=token)
        return issue_socket_ticket(tenant=tenant, actor=actor).ticket

    return await run_db(issue)


@asynccontextmanager
async def opened(
    path: str = PATH,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> AsyncIterator[tuple[Socket, Handshake]]:
    """Open a socket against the real application and always close it."""
    from config.asgi import build_application

    async with open_socket(build_application(), path, headers) as pair:
        yield pair
