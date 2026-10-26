"""The socket door resolves the surface: the host a handshake came in at narrows what it hears.

The world is `test_surfaces.py`'s: the implicit total `staff` surface at
`localhost`, and a scratch `customer` surface at `customer.localhost` exposing
the `widgets` family alone and choosing the tenant by membership. The surface
itself is resolved once, from the handshake's `Host`, by `TenantMiddlewareASGI`
(`scope["surface"]`); this door only asks it.

Groups are derived from the tenant, the hat and the person — never from a
family — so the family narrowing lands where the ceiling's does, per frame: a
frame from a section the host does not expose is not sent. What closes the
handshake is what closes it for an unresolvable tenant, with the same code: a
host no surface answers at (whichever credential opened it), a sent `X-Tenant`
on a membership surface, and a consumer that is one family's door at a host
that does not expose that family.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from channels.auth import AuthMiddlewareStack
from channels.routing import URLRouter
from django.urls import path

from apps.accounts.models import User
from apps.core.asgi_middleware import TenantMiddlewareASGI
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.core.surfaces import Surface
from apps.core.tests import test_surfaces as surface_world
from apps.core.tests.doors import (
    assert_four_doors,
    assert_refused_at_every_door,
    recorded_envelope,
)
from apps.core.tests.test_mcp import MCP_HEADERS, running
from apps.core.tests.test_surfaces import CUSTOMER_HOST, NOT_EXPOSED, STAFF_HOST
from apps.core.tests.wire import call as _call
from apps.core.tests.wire import session as _session
from apps.core.tests.wire import socket_bearer
from apps.example.schemas import WidgetOut
from apps.realtime.bridge import push_event
from apps.realtime.consumers import TenantEventsConsumer
from apps.realtime.middleware import token_auth
from apps.realtime.schemas import CLOSE_NO_TENANT, EventMessage
from apps.realtime.tests.sockets import a_token, an_event, opened
from apps.realtime.tests.test_consumers import session_headers
from apps.realtime.tests.websocket import open_socket

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

UNBOUND_HOST = "nowhere.localhost"
WIDGET_FRAME = "example.widget.created"
NOTE_FRAME = "djb_notes.note.created"

# The two-faced world, from the module that builds it.
customer_role = surface_world.customer_role
two_faces = surface_world.two_faces
customer = surface_world.customer


def at(host: str, *headers: tuple[bytes, bytes]) -> list[tuple[bytes, bytes]]:
    """The handshake's headers, sent at `host`."""
    return [(b"host", host.encode()), *headers]


# --- the frames: a section the host does not expose is not heard --------------


async def test_a_socket_at_the_customer_host_hears_widgets_and_not_notes(
    two_faces: Surface, tenant: Tenant, customer: User
) -> None:
    """The test that cannot pass vacuously: the socket is proved live after the silence."""
    plaintext = await a_token(user=customer, tenant=tenant)

    async with opened(headers=at(CUSTOMER_HOST, *socket_bearer(plaintext))) as (
        socket,
        handshake,
    ):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event(NOTE_FRAME))
        assert await socket.received_nothing() is True
        await push_event(tenant_id=tenant.pk, event=an_event(WIDGET_FRAME))
        assert (await socket.receive_json())["name"] == WIDGET_FRAME


async def test_a_session_at_the_customer_host_is_narrowed_the_same_way(
    two_faces: Surface, tenant: Tenant, customer: User
) -> None:
    async with opened(headers=at(CUSTOMER_HOST, *await session_headers(customer))) as (
        socket,
        handshake,
    ):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event(NOTE_FRAME))
        assert await socket.received_nothing() is True
        await push_event(tenant_id=tenant.pk, event=an_event(WIDGET_FRAME))
        assert (await socket.receive_json())["name"] == WIDGET_FRAME


async def test_a_socket_at_the_staff_host_hears_every_section(
    two_faces: Surface, tenant: Tenant, owner: User
) -> None:
    plaintext = await a_token(user=owner, tenant=tenant)

    async with opened(headers=at(STAFF_HOST, *socket_bearer(plaintext))) as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event(NOTE_FRAME))
        assert (await socket.receive_json())["name"] == NOTE_FRAME


# --- the handshake: closed as an unresolvable tenant is closed ----------------


async def test_a_bearer_at_an_unbound_host_is_closed_as_nowhere(
    two_faces: Surface, tenant: Tenant, owner: User
) -> None:
    """The session half already resolved nowhere here; the bearer half overrode it."""
    plaintext = await a_token(user=owner, tenant=tenant)

    async with opened(headers=at(UNBOUND_HOST, *socket_bearer(plaintext))) as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_NO_TENANT


@pytest.mark.parametrize("forwarded", [False, True])
async def test_a_forwarded_host_is_the_host_only_where_a_proxy_of_ours_sets_it(
    two_faces: Surface, tenant: Tenant, owner: User, settings: Any, forwarded: bool
) -> None:
    """Sent at an unbound host naming the staff host in `X-Forwarded-Host`: honoured
    only with `USE_X_FORWARDED_HOST` on, as `get_host()` honours it on the HTTP door."""
    settings.USE_X_FORWARDED_HOST = forwarded
    plaintext = await a_token(user=owner, tenant=tenant)
    headers = at(
        UNBOUND_HOST, *socket_bearer(plaintext), (b"x-forwarded-host", STAFF_HOST.encode())
    )

    async with opened(headers=headers) as (_, handshake):
        assert handshake.accepted is forwarded
        if not forwarded:
            assert handshake.code == CLOSE_NO_TENANT


async def test_a_bearer_naming_a_tenant_on_a_membership_surface_is_closed(
    two_faces: Surface, tenant: Tenant, customer: User
) -> None:
    """The addressing law the HTTP and MCP doors apply, said as a closed handshake."""
    plaintext = await a_token(user=customer, tenant=tenant)
    headers = at(CUSTOMER_HOST, *socket_bearer(plaintext), (b"x-tenant", tenant.slug.encode()))

    async with opened(headers=headers) as (_, handshake):
        assert handshake.accepted is False
        assert handshake.code == CLOSE_NO_TENANT


class _NotesConsumer(TenantEventsConsumer):
    """A consumer that is the `djb_notes` family's door, as a product's would be its app's."""


# Where a product's subclass would live: its module names the app whose families
# it is the door of — the same translation an event name gets.
_NotesConsumer.__module__ = "apps.djb_notes.consumers"


def _notes_socket() -> Any:
    """The stack `config.asgi` mounts every discovered pattern behind, around one consumer."""
    # `path()` is typed for HTTP views; Channels routes an ASGI application
    # through the same object — `consumers.py`'s own spelling of the same line.
    consumer: Any = token_auth(_NotesConsumer.as_asgi())
    return AuthMiddlewareStack(TenantMiddlewareASGI(URLRouter([path("ws/notes/", consumer)])))


async def test_a_join_for_a_family_the_host_does_not_expose_is_closed(
    two_faces: Surface, tenant: Tenant, customer: User, owner: User
) -> None:
    as_customer = socket_bearer(await a_token(user=customer, tenant=tenant))
    as_owner = socket_bearer(await a_token(user=owner, tenant=tenant))

    async with open_socket(_notes_socket(), "/ws/notes/", at(CUSTOMER_HOST, *as_customer)) as (
        _,
        at_customer,
    ):
        assert at_customer.accepted is False
        assert at_customer.code == CLOSE_NO_TENANT
    async with open_socket(_notes_socket(), "/ws/notes/", at(STAFF_HOST, *as_owner)) as (
        _,
        at_staff,
    ):
        assert at_staff.accepted is True


# --- The four doors at the customer host: one Widget, one family refused ------
#
# `apps.core.tests.doors`' per-surface pass, over the real doors: a customer's
# bearer reads one Widget on REST, on MCP and down the socket at the customer
# host, and the three agree with the recorded payload — the acts on both viewer
# doors are the customer surface's (none). The `djb_notes` family is refused at
# all three with one code. A disagreement between two doors is a finding.


async def test_one_widget_on_every_door_at_the_customer_host_and_one_family_refused_at_all(
    two_faces: Surface, tenant: Tenant, owner: User, customer: User
) -> None:
    from config.asgi import build_application

    as_owner = {"authorization": f"Bearer {await a_token(user=owner, tenant=tenant)}"}
    bearer = {"authorization": f"Bearer {await a_token(user=customer, tenant=tenant)}"}
    application = build_application()

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=f"http://{STAFF_HOST}") as staff:
            made = await staff.post("/api/v1/widgets/", headers=as_owner, json={"name": "W"})
        assert made.status_code == 201, made.text
        widget_id = str(made.json()["id"])
        notes_of_the_widget = f"widget:{widget_id}"
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{CUSTOMER_HOST}"
        ) as client:
            rest = await client.get("/api/v1/widgets/", headers=bearer)
            notes_rest = await client.get(
                f"/api/v1/djb_notes/?subject={notes_of_the_widget}", headers=bearer
            )
            mcp_headers = {**MCP_HEADERS, **bearer}
            await _session(client, mcp_headers)
            mcp = await _call(client, mcp_headers, "list_widgets")
            notes_mcp = await _call(
                client, mcp_headers, "list_djb_notes", {"subject": notes_of_the_widget}
            )
    recorded = await run_db(recorded_envelope, tenant=tenant, name=WIDGET_FRAME)

    handshake_headers = at(CUSTOMER_HOST, (b"authorization", bearer["authorization"].encode()))
    async with opened(headers=handshake_headers) as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event(NOTE_FRAME))
        notes_heard = not await socket.received_nothing()
        await push_event(tenant_id=tenant.pk, event=EventMessage.model_validate(recorded))
        frame = await socket.receive_json()

    assert rest.status_code == 200, rest.text
    (rest_row,) = rest.json()["items"]
    (mcp_row,) = mcp["structuredContent"]["items"]
    assert rest_row["id"] == widget_id
    assert rest_row["allowed_acts"] == []
    assert frame["name"] == WIDGET_FRAME
    assert_four_doors(rest=rest_row, mcp=mcp_row, event_payload=frame["payload"], out=WidgetOut)
    assert_refused_at_every_door(
        code=NOT_EXPOSED, rest=notes_rest.json(), mcp=notes_mcp, socket_heard=notes_heard
    )
