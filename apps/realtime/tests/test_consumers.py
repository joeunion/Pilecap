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

import json
import logging
import time
from contextlib import AsyncExitStack
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from redis.exceptions import ConnectionError as RedisConnectionError

from apps.accounts.models import ApiToken, User
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.core.tests.wire import socket_bearer
from apps.realtime import consumers
from apps.realtime.bridge import push_event
from apps.realtime.consumers import session_alive
from apps.realtime.schemas import (
    CLOSE_NO_TENANT,
    CLOSE_NOT_A_COMMAND,
    CLOSE_SESSION_EXPIRED,
    CLOSE_TOO_MANY_SOCKETS,
    CLOSE_UNAUTHENTICATED,
    EventMessage,
)
from apps.realtime.tests.sockets import PATH, a_ticket, a_token, an_event, opened
from apps.realtime.tests.test_doors_over_the_wire import redis_is_listening

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


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


async def test_an_anonymous_socket_is_refused() -> None:
    async with opened() as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_UNAUTHENTICATED


async def test_a_bad_bearer_token_is_refused() -> None:
    async with opened(headers=socket_bearer("djb_not-a-real-token")) as (_, handshake):
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

    async with opened(headers=socket_bearer(plaintext)) as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event())
        received = await socket.receive_json()

    assert received["name"] == "example.widget.created"


async def test_a_bearer_token_in_the_query_string_is_refused(tenant: Tenant, owner: User) -> None:
    """A URL lands in access logs, so `?token=` is refused whatever it holds."""
    plaintext = await a_token(user=owner, tenant=tenant)

    async with opened(path=f"{PATH}?token={plaintext}") as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_UNAUTHENTICATED


async def test_a_ticket_in_the_query_string_joins(tenant: Tenant, owner: User) -> None:
    """A browser cannot set a handshake header, so a one-use ticket rides the query instead."""
    ticket = await a_ticket(user=owner, tenant=tenant)

    async with opened(path=f"{PATH}?ticket={ticket}") as (socket, handshake):
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
    headers = [*socket_bearer(plaintext), (b"x-tenant", other_tenant.slug.encode())]

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

    async with opened(headers=socket_bearer(plaintext)) as (socket, handshake):
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


# --- The join count, and the socket closing with its session --------


@pytest.fixture(params=["local", "redis"])
def join_store(request: pytest.FixtureRequest, settings: Any) -> str:
    """Both stores the count runs on: the in-memory cache's twin, and the deployment's Redis."""
    if request.param == "redis":
        if not redis_is_listening():
            pytest.skip(f"no Redis listening on {settings.REDIS_URL}; start the compose stack")
        settings.CACHES = {
            "default": {
                "BACKEND": "django_redis.cache.RedisCache",
                "LOCATION": settings.CACHE_URL,
                "KEY_PREFIX": f"sf-socket-{uuid4().hex}",
                "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            }
        }
    return str(request.param)


def refusals(caplog: pytest.LogCaptureFixture, name: str) -> list[dict[str, Any]]:
    """Every structured line of this name that left the process."""
    lines = [json.loads(r.getMessage()) for r in caplog.records if r.getMessage().startswith("{")]
    return [line for line in lines if line.get("event") == name]


async def test_the_third_socket_of_one_credential_is_refused_and_the_two_still_hear(
    join_store: str, settings: Any, tenant: Tenant, owner: User
) -> None:
    settings.REALTIME_MAX_SOCKETS_PER_CREDENTIAL = 2
    plaintext = await a_token(user=owner, tenant=tenant)

    async with AsyncExitStack() as stack:
        first, one = await stack.enter_async_context(opened(headers=socket_bearer(plaintext)))
        second, two = await stack.enter_async_context(opened(headers=socket_bearer(plaintext)))
        assert one.accepted is True and two.accepted is True
        async with opened(headers=socket_bearer(plaintext)) as (_, three):
            assert three.accepted is False
            assert three.code == CLOSE_TOO_MANY_SOCKETS

        await push_event(tenant_id=tenant.pk, event=an_event())
        assert (await first.receive_json())["name"] == "example.widget.created"
        assert (await second.receive_json())["name"] == "example.widget.created"

        async with opened(headers=socket_bearer(plaintext)) as (_, still):
            assert still.accepted is False
        await first.close()
        async with opened(headers=socket_bearer(plaintext)) as (_, after):
            assert after.accepted is True


async def test_the_tenant_ceiling_holds_across_two_credentials(
    join_store: str, settings: Any, tenant: Tenant, owner: User
) -> None:
    settings.REALTIME_MAX_SOCKETS_PER_TENANT = 2
    machine = await a_token(user=owner, tenant=tenant, name="machine")
    human = await session_headers(owner)

    async with AsyncExitStack() as stack:
        _, one = await stack.enter_async_context(opened(headers=socket_bearer(machine)))
        _, two = await stack.enter_async_context(opened(headers=human))
        assert one.accepted is True and two.accepted is True
        async with opened(headers=human) as (_, three):
            assert three.accepted is False
            assert three.code == CLOSE_TOO_MANY_SOCKETS


async def test_a_dead_workers_joins_expire_with_their_lease(
    join_store: str, settings: Any, tenant: Tenant, owner: User
) -> None:
    """Two members scored before the lease are pruned by the next join, not counted by it."""
    settings.REALTIME_MAX_SOCKETS_PER_CREDENTIAL = 2
    plaintext = await a_token(user=owner, tenant=tenant)
    token_pk = await run_db(lambda: ApiToken.objects.get(user=owner, tenant=tenant).pk)
    stale = time.time() - settings.REALTIME_JOIN_LEASE_SECONDS - 10

    def plant() -> consumers.Seat:
        for phantom in ("dead-worker-1", "dead-worker-2"):
            seat = consumers.seat_for(
                credential=f"token:{token_pk}", tenant_id=tenant.pk, member=phantom
            )
            consumers._join_store().refresh(seat, now=stale)
        return seat

    seat = await run_db(plant)
    assert await run_db(consumers.live_count, seat.credential_key) == 2

    async with opened(headers=socket_bearer(plaintext)) as (_, handshake):
        assert handshake.accepted is True
        assert await run_db(consumers.live_count, seat.credential_key) == 1
        assert await run_db(consumers.live_count, seat.tenant_key) == 1


async def test_a_join_counted_twice_is_one_member(join_store: str, settings: Any) -> None:
    """Set semantics: the same channel name seated again is the same seat, never a second."""
    settings.REALTIME_MAX_SOCKETS_PER_CREDENTIAL = 1
    seat = consumers.seat_for(credential="user:twice", tenant_id=uuid4(), member="one-channel")

    assert await consumers.take_join(seat) is None
    assert await consumers.take_join(seat) is None
    assert await run_db(consumers.live_count, seat.credential_key) == 1
    other = consumers.seat_for(credential="user:twice", tenant_id=uuid4(), member="another-channel")
    assert await consumers.take_join(other) == "credential_ceiling"


async def test_a_store_that_does_not_answer_fails_the_handshake_closed(
    settings: Any,
    tenant: Tenant,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    settings.CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": settings.CACHE_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
        }
    }

    def unreachable(alias: str) -> Any:
        raise RedisConnectionError("connection refused")

    monkeypatch.setattr(consumers, "get_redis_connection", unreachable)
    caplog.set_level(logging.INFO)
    plaintext = await a_token(user=owner, tenant=tenant)

    async with opened(headers=socket_bearer(plaintext)) as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_TOO_MANY_SOCKETS

    [line] = refusals(caplog, "realtime.join.refused")
    assert line["reason"] == "count_unavailable"


async def test_a_ping_on_an_ended_session_closes_the_socket(owner: User) -> None:
    async with opened(headers=await session_headers(owner)) as (socket, handshake):
        assert handshake.accepted is True
        await socket.send_json({"type": "ping"})
        assert await socket.receive_json() == {"type": "pong"}

        await run_db(
            lambda: Session.objects.update(expire_date=timezone.now() - timedelta(seconds=1))
        )
        await socket.send_json({"type": "ping"})
        closed = await socket.output()

    assert closed["type"] == "websocket.close"
    assert closed["code"] == CLOSE_SESSION_EXPIRED


async def test_the_session_read_on_a_ping_is_one_query(owner: User) -> None:
    def measure() -> tuple[bool, int]:
        client = Client()
        client.force_login(owner)
        key = str(client.cookies[settings.SESSION_COOKIE_NAME].value)
        with CaptureQueriesContext(connection) as queries:
            alive = session_alive(key)
        return alive, len(queries)

    assert await run_db(measure) == (True, 1)
