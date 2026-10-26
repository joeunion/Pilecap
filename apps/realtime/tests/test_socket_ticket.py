"""The socket's credential never rides the URL: a one-use, 60-second ticket does."""

from __future__ import annotations

import asyncio
import json
import logging
import logging.config
from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.realtime.bridge import push_event
from apps.realtime.schemas import CLOSE_NO_TENANT, CLOSE_UNAUTHENTICATED
from apps.realtime.tests.sockets import PATH, a_token, an_event, opened
from apps.realtime.tests.test_consumers import session_headers
from apps.realtime.tests.websocket import Socket

TICKET_ROUTE = "/api/v1/socket-tickets/"
UVICORN_HANDSHAKE = '%s - "WebSocket %s" [accepted]'


def mint(plaintext: str) -> dict[str, Any]:
    """`POST` the ticket door with `plaintext` as the header bearer; the 201 body."""
    response = Client().post(TICKET_ROUTE, HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    assert response.status_code == 201, response.content
    return dict(response.json())


async def a_ticket(*, user: User, tenant: Tenant) -> str:
    """A fresh ticket for `user` in `tenant`, minted over the REST door."""
    return str((await run_db(mint, await a_token(user=user, tenant=tenant)))["ticket"])


async def first_reply(
    path: str, *, extensions: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    """Offer one handshake and return every message the application sent before it ended."""
    from config.asgi import build_application

    application = build_application()
    scope = Socket(application, path).scope
    if extensions is not None:
        scope = {**scope, "extensions": extensions}
    inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    await inbox.put({"type": "websocket.connect"})
    await application(scope, inbox.get, send)
    return sent


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_bearer_in_the_query_string_is_refused_naming_the_ticket_door(
    tenant: Tenant, owner: User
) -> None:
    """Red on base: `?token=` was accepted, so the bearer reached every access log."""
    plaintext = await a_token(user=owner, tenant=tenant)

    async with opened(path=f"{PATH}?token={plaintext}") as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_UNAUTHENTICATED

    closed = await first_reply(f"{PATH}?token={plaintext}")
    assert closed[-1]["type"] == "websocket.close"
    assert f"POST {TICKET_ROUTE}" in closed[-1]["reason"]

    answered = await first_reply(
        f"{PATH}?token={plaintext}", extensions={"websocket.http.response": {}}
    )
    start, body = answered
    assert start["type"] == "websocket.http.response.start"
    assert start["status"] == 400
    refusal = json.loads(body["body"])
    assert refusal["code"] == "socket_credential_in_url"
    assert {"route:socket_ticket-create"} <= {r["destination"] for r in refusal["remedies"]}
    assert plaintext not in body["body"].decode()


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_ticket_opens_the_socket_and_a_push_arrives(tenant: Tenant, owner: User) -> None:
    ticket = await a_ticket(user=owner, tenant=tenant)

    async with opened(path=f"{PATH}?ticket={ticket}") as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event())
        assert (await socket.receive_json())["name"] == "example.widget.created"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_ticket_dies_after_one_use(tenant: Tenant, owner: User) -> None:
    ticket = await a_ticket(user=owner, tenant=tenant)

    async with opened(path=f"{PATH}?ticket={ticket}") as (_, first):
        assert first.accepted is True
    async with opened(path=f"{PATH}?ticket={ticket}") as (_, second):
        assert second.accepted is False
        assert second.code == CLOSE_UNAUTHENTICATED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_ticket_dies_after_sixty_seconds(
    tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fake clock moves past the TTL; nothing sleeps."""
    ticket = await a_ticket(user=owner, tenant=tenant)
    later = timezone.now() + timedelta(seconds=61)
    monkeypatch.setattr(timezone, "now", lambda: later)

    async with opened(path=f"{PATH}?ticket={ticket}") as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_UNAUTHENTICATED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_ticket_inside_sixty_seconds_still_opens(
    tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sibling of the death: the same clock one second short of it opens the socket."""
    ticket = await a_ticket(user=owner, tenant=tenant)
    later = timezone.now() + timedelta(seconds=59)
    monkeypatch.setattr(timezone, "now", lambda: later)

    async with opened(path=f"{PATH}?ticket={ticket}") as (_, handshake):
        assert handshake.accepted is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_ticket_is_bound_to_its_tenant(
    tenant: Tenant, other_tenant: Tenant, owner: User
) -> None:
    ticket = await a_ticket(user=owner, tenant=tenant)

    async with opened(path=f"{PATH}?ticket={ticket}&tenant={other_tenant.slug}") as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_NO_TENANT


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_unknown_ticket_is_refused() -> None:
    async with opened(path=f"{PATH}?ticket=never-minted") as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_UNAUTHENTICATED


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_session_mints_a_ticket_too(tenant: Tenant, owner: User) -> None:
    """The door takes `API_AUTH`, so a signed-in person's ticket opens their own socket."""
    cookie = dict(await session_headers(owner))[b"cookie"].decode()

    def mint_by_session() -> dict[str, Any]:
        response = Client().post(TICKET_ROUTE, HTTP_COOKIE=cookie)
        assert response.status_code == 201, response.content
        return dict(response.json())

    ticket = (await run_db(mint_by_session))["ticket"]
    async with opened(path=f"{PATH}?ticket={ticket}") as (_, handshake):
        assert handshake.accepted is True


@pytest.mark.django_db
def test_the_ticket_door_answers_a_sixty_second_ticket_and_refuses_anonymous(
    tenant: Tenant, owner: User
) -> None:
    from apps.core.tests.wire import bearer

    body = mint(bearer(user=owner, tenant=tenant))
    assert body["expires_in"] == 60
    assert body["ticket"]

    assert Client().post(TICKET_ROUTE).status_code == 401


# --- The handshake line as uvicorn prints it ------------------------------------------


@pytest.fixture
def base_logging() -> Iterator[None]:
    """`config/settings/base.py`'s LOGGING applied for the test; the loggers it names restored."""
    from config.settings import base

    named = [logging.getLogger(), *(logging.getLogger(n) for n in base.LOGGING.get("loggers", {}))]
    saved = [(lg, lg.level, list(lg.filters), list(lg.handlers), lg.propagate) for lg in named]
    logging.config.dictConfig(base.LOGGING)
    yield
    for lg, level, filters, handlers, propagate in saved:
        lg.setLevel(level)
        lg.filters[:] = filters
        lg.handlers[:] = handlers
        lg.propagate = propagate


@pytest.mark.usefixtures("base_logging")
@pytest.mark.parametrize("parameter", ["token", "ticket"])
def test_the_handshake_line_carries_no_credential(
    parameter: str, caplog: pytest.LogCaptureFixture
) -> None:
    """uvicorn 0.52 logs a handshake on `uvicorn.error`, never `uvicorn.access`; the same call."""
    secret = "-".join(("credential", "value", "that", "must", "not", "print"))
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        logging.getLogger("uvicorn.error").info(
            UVICORN_HANDSHAKE, "127.0.0.1:51000", f"/ws/events/?{parameter}={secret}&tenant=acme"
        )

    line = caplog.records[-1].getMessage()
    assert secret not in line
    assert f"{parameter}=[redacted]" in line
    assert "tenant=acme" in line


@pytest.mark.usefixtures("base_logging")
def test_a_line_off_the_socket_path_is_untouched(caplog: pytest.LogCaptureFixture) -> None:
    """The sibling: the filter rewrites `/ws/` handshake lines and no other."""
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        logging.getLogger("uvicorn.error").info(
            UVICORN_HANDSHAKE, "127.0.0.1:51000", "/api/v1/widgets/?token=kept"
        )

    line = caplog.records[-1].getMessage()
    assert line.endswith('"WebSocket /api/v1/widgets/?token=kept" [accepted]')
