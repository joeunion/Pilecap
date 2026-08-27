"""The socket door, driven the way a client drives it.

Every test here builds the **real** ASGI application — the same object
`uvicorn` serves — and speaks the websocket protocol to it. Nothing is stubbed:
`config/asgi.py` discovers the patterns, `AuthMiddlewareStack` reads a real
session cookie, the token is a real `ApiToken`, and the push comes out of the
same bridge the events app will call. A test against a hand-built router would
prove the consumer works and leave the thing that actually breaks — discovery,
and the order of the middleware stack — untested.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from django.conf import settings
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.realtime.bridge import push_event
from apps.realtime.schemas import (
    CLOSE_NO_TENANT,
    CLOSE_NOT_A_COMMAND,
    CLOSE_UNAUTHENTICATED,
    EventMessage,
)
from apps.realtime.tests.websocket import Handshake, Socket, open_socket

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

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


async def session_headers(user: User) -> list[tuple[bytes, bytes]]:
    """A real signed-in session, as a cookie header on the handshake.

    Signing in touches the database and this is an async test, so it crosses to
    a thread the way every sync-ORM call in async code has to — through
    `run_db`, which closes the connection it opened at both ends. A bare
    `sync_to_async` here would leave one open per worker thread for the life of
    the run, which is exactly the class of leak the house has one crossing to prevent.
    """

    def sign_in() -> str:
        client = Client()
        client.force_login(user)
        return str(client.cookies[settings.SESSION_COOKIE_NAME].value)

    cookie = await run_db(sign_in)
    return [(b"cookie", f"{settings.SESSION_COOKIE_NAME}={cookie}".encode())]


async def a_token(*, user: User, tenant: Tenant) -> str:
    """A real `ApiToken` for this user, pinned to this tenant."""
    _, plaintext = await run_db(
        issue_token,
        user=user,
        tenant=tenant,
        name="socket",
        actor=actor_for(user=user, tenant=tenant),
    )
    return plaintext


def bearer_headers(plaintext: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {plaintext}".encode())]


@asynccontextmanager
async def opened(
    path: str = PATH,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> AsyncIterator[tuple[Socket, Handshake]]:
    """Open a socket against the real application and always close it."""
    from config.asgi import build_application

    async with open_socket(build_application(), path, headers) as pair:
        yield pair


async def test_an_anonymous_socket_is_refused() -> None:
    async with opened() as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_UNAUTHENTICATED


async def test_a_bad_bearer_token_is_refused() -> None:
    async with opened(headers=bearer_headers("djb_not-a-real-token")) as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_UNAUTHENTICATED


async def test_a_user_who_belongs_to_no_tenant_is_refused(nomad: User) -> None:
    """Authenticated is not the same as entitled, and the codes say which."""
    async with opened(headers=await session_headers(nomad)) as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_NO_TENANT


async def test_a_superuser_who_belongs_to_no_tenant_is_refused(root: User) -> None:
    """Tenancy has no superuser exemption on this door either."""
    async with opened(headers=await session_headers(root)) as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_NO_TENANT


async def test_a_session_joins_its_tenant_and_receives_a_push(tenant: Tenant, owner: User) -> None:
    async with opened(headers=await session_headers(owner)) as (socket, handshake):
        assert handshake.accepted is True
        event = an_event()
        await push_event(tenant_id=tenant.pk, event=event)
        received = await socket.receive_json()

    assert received["name"] == "example.widget.created"
    assert received["payload"] == event.payload


async def test_the_pushed_message_is_the_schema_and_nothing_else(
    tenant: Tenant, owner: User
) -> None:
    """What arrives validates as an `EventMessage` and carries no extra keys.

    The shape is the contract a client codegens against, so "it happens to
    contain the fields I need" is not enough — an accidental extra key today is
    a field somebody depends on tomorrow.
    """
    async with opened(headers=await session_headers(owner)) as (socket, handshake):
        assert handshake.accepted is True
        event = an_event()
        await push_event(tenant_id=tenant.pk, event=event)
        received = await socket.receive_json()

    assert set(received) == {
        "name",
        "v",
        "payload",
        "correlation_id",
        "organization_id",
        "occurred_at",
    }
    assert EventMessage.model_validate(received) == event


async def test_a_bearer_token_joins_and_receives_a_push(tenant: Tenant, owner: User) -> None:
    plaintext = await a_token(user=owner, tenant=tenant)

    async with opened(headers=bearer_headers(plaintext)) as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event())
        received = await socket.receive_json()

    assert received["name"] == "example.widget.created"


async def test_a_bearer_token_in_the_query_string_joins(tenant: Tenant, owner: User) -> None:
    """A browser cannot set a handshake header, so the query parameter exists."""
    plaintext = await a_token(user=owner, tenant=tenant)

    async with opened(path=f"{PATH}?token={plaintext}") as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event())
        assert (await socket.receive_json())["name"] == "example.widget.created"


async def test_a_token_pinned_to_one_tenant_may_not_ask_for_another(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    """The same rule the REST and MCP doors apply, applied here.

    A token pinned to Acme that names Globex is refused outright rather than
    quietly answered as Acme — otherwise a client could probe for tenants it
    has no business knowing exist.

    **The close code moved with ADR core-21 and the refusal did not.**
    It used to be `CLOSE_UNAUTHENTICATED`, because `authenticate_token` answered
    `None` and the credential was what appeared to fail. The credential is fine;
    what this handshake cannot be given is the ADDRESS it asked for, and
    `CLOSE_NO_TENANT` — "this handshake resolved nowhere it may act" — is that
    fact in the only vocabulary a websocket handshake has. It is the same code
    the session half of this door closes with, so the two credentials answer
    alike.
    """
    plaintext = await a_token(user=owner, tenant=tenant)
    headers = [*bearer_headers(plaintext), (b"x-tenant", other_tenant.slug.encode())]

    async with opened(headers=headers) as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_NO_TENANT


async def test_another_tenants_socket_sees_nothing(
    tenant: Tenant, other_tenant: Tenant, stranger: User
) -> None:
    """The test that cannot pass vacuously: it proves the socket is live first.

    A push for Acme has to be absent from a Globex socket, and a push for
    Globex has to arrive on it — otherwise "received nothing" would also pass
    against a socket that was quietly broken.
    """
    plaintext = await a_token(user=stranger, tenant=other_tenant)

    async with opened(headers=bearer_headers(plaintext)) as (socket, handshake):
        assert handshake.accepted is True

        await push_event(tenant_id=tenant.pk, event=an_event("example.widget.created"))
        assert await socket.received_nothing() is True

        await push_event(tenant_id=other_tenant.pk, event=an_event("example.widget.updated"))
        assert (await socket.receive_json())["name"] == "example.widget.updated"


async def test_a_ping_gets_a_pong(owner: User) -> None:
    async with opened(headers=await session_headers(owner)) as (socket, handshake):
        assert handshake.accepted is True
        await socket.send_json({"type": "ping"})
        assert await socket.receive_json() == {"type": "pong"}


async def test_a_client_command_is_refused_out_loud(owner: User) -> None:
    """There are no client-to-server commands, and the client is told so."""
    async with opened(headers=await session_headers(owner)) as (socket, handshake):
        assert handshake.accepted is True
        await socket.send_json({"type": "widgets.create", "name": "nope"})
        closed = await socket.output()

    assert closed["type"] == "websocket.close"
    assert closed["code"] == CLOSE_NOT_A_COMMAND


async def test_a_binary_frame_is_refused_rather_than_raised(owner: User) -> None:
    """A frame the consumer cannot read closes the socket; it does not crash it.

    The JSON consumer this one is built on raises on a binary frame, and an
    exception escaping a consumer gives the client a bare disconnect and the
    operator a traceback. A close code is the answer both of them can act on.
    """
    async with opened(headers=await session_headers(owner)) as (socket, handshake):
        assert handshake.accepted is True
        await socket.send_bytes(b"\x00\x01")
        closed = await socket.output()

    assert closed["type"] == "websocket.close"
    assert closed["code"] == CLOSE_NOT_A_COMMAND


async def test_the_socket_route_is_discovered_by_the_asgi_mount() -> None:
    """`apps/realtime` registered itself by existing. Nothing in `config/` changed."""
    from config.asgi import discovered_websocket_urlpatterns

    routes = {entry.name: str(entry.pattern) for entry in discovered_websocket_urlpatterns()}
    assert routes["realtime-events"] == "ws/events/"
