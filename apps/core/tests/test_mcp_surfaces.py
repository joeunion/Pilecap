"""The machine door resolves the surface: the host a call came in at narrows what it reaches.

Driven the way `test_mcp.py` drives it — the real ASGI application, a real
`ApiToken`, JSON-RPC over Streamable HTTP — in the world `test_surfaces.py`
builds: the implicit total `staff` surface at `localhost`, and a scratch
`customer` surface at `customer.localhost` exposing the `widgets` family alone,
admitting the `customer` role alone and choosing the tenant by membership.

What the HTTP door already answers, this door must answer the same way: a tool
whose family the host does not expose is `surface_does_not_expose` in the
tool-call body; a host no surface answers at is `surface_unknown_host` before
the credential; the listing at a host is that host's, as the OpenAPI document
is; a sent `X-Tenant` on a membership surface is the addressing refusal; and a
write made at the customer host is audited as made there.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.audit import AuditEntry
from apps.core.models import Organization, Tenant
from apps.core.surfaces import STAFF, Surface
from apps.core.tests import test_surfaces as surface_world
from apps.core.tests.test_mcp import MCP_HEADERS, running
from apps.core.tests.test_mcp_scopes import _listed, _text
from apps.core.tests.test_surfaces import CUSTOMER_HOST, NOT_EXPOSED, STAFF_HOST
from apps.core.tests.wire import call as _call
from apps.core.tests.wire import session as _session
from apps.example.services import create_widget

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

UNBOUND_HOST = "nowhere.localhost"

# The two-faced world, from the module that builds it — the same fixtures, by
# name, so the machine door is judged in exactly the world the HTTP door was.
customer_role = surface_world.customer_role
two_faces = surface_world.two_faces
customer = surface_world.customer


def _bearer(user: User, tenant: Tenant) -> str:
    _, plaintext = issue_token(
        user=user, tenant=tenant, name="surface", actor=actor_for(user=user, tenant=tenant)
    )
    return plaintext


def _widget(tenant: Tenant, owner: User, root_org: Organization) -> str:
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    return str(create_widget(tenant=tenant, actor=acting, name="W").pk)


async def _at(host: str, headers: dict[str, str], *calls: tuple[str, dict[str, Any]]) -> list[Any]:
    """Open one session at `host`, make each call in order, and answer each result."""
    from config.asgi import build_application

    application = build_application()
    answers: list[Any] = []
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url=f"http://{host}") as client:
            await _session(client, headers)
            for name, arguments in calls:
                if name == "tools/list":
                    answers.append(await _listed(client, headers))
                else:
                    answers.append(await _call(client, headers, name, arguments))
    return answers


# --- the tool call: an unexposed family is not there --------------------------


async def test_a_tool_whose_family_the_host_does_not_expose_answers_surface_does_not_expose(
    two_faces: Surface, tenant: Tenant, owner: User, root_org: Organization, customer: User
) -> None:
    widget_id = await run_db(_widget, tenant, owner, root_org)
    headers = {**MCP_HEADERS, "authorization": f"Bearer {await run_db(_bearer, customer, tenant)}"}

    notes, widgets = await _at(
        CUSTOMER_HOST,
        headers,
        ("list_djb_notes", {"subject": f"widget:{widget_id}"}),
        ("list_widgets", {}),
    )

    assert notes.get("isError") is True, notes
    assert NOT_EXPOSED in _text(notes)
    assert "surface:customer" in _text(notes)
    assert widgets.get("isError") is not True, widgets
    assert [row["id"] for row in widgets["structuredContent"]["items"]] == [widget_id]


async def test_the_same_tool_answers_at_the_staff_host(
    two_faces: Surface, tenant: Tenant, owner: User, root_org: Organization
) -> None:
    widget_id = await run_db(_widget, tenant, owner, root_org)
    headers = {**MCP_HEADERS, "authorization": f"Bearer {await run_db(_bearer, owner, tenant)}"}

    (notes,) = await _at(
        STAFF_HOST, headers, ("list_djb_notes", {"subject": f"widget:{widget_id}"})
    )

    assert notes.get("isError") is not True, notes


async def test_the_surface_is_asked_before_the_arguments(
    two_faces: Surface, tenant: Tenant, customer: User
) -> None:
    """A malformed call to an unexposed tool learns nothing of the tool's schema."""
    headers = {**MCP_HEADERS, "authorization": f"Bearer {await run_db(_bearer, customer, tenant)}"}

    (notes,) = await _at(CUSTOMER_HOST, headers, ("list_djb_notes", {}))

    assert notes.get("isError") is True, notes
    assert NOT_EXPOSED in _text(notes)
    assert "subject" not in _text(notes)


async def test_a_tool_that_reaches_no_capability_answers_on_every_surface(
    two_faces: Surface, tenant: Tenant, customer: User
) -> None:
    headers = {**MCP_HEADERS, "authorization": f"Bearer {await run_db(_bearer, customer, tenant)}"}

    (ping,) = await _at(CUSTOMER_HOST, headers, ("ping", {}))

    assert ping.get("isError") is not True, ping
    assert ping["structuredContent"]["tenant"] == tenant.slug


# --- the listing is the host's, as the document is ----------------------------


async def test_the_listing_at_a_host_is_what_that_host_exposes(
    two_faces: Surface, tenant: Tenant, owner: User, customer: User
) -> None:
    as_customer = {
        **MCP_HEADERS,
        "authorization": f"Bearer {await run_db(_bearer, customer, tenant)}",
    }
    as_owner = {**MCP_HEADERS, "authorization": f"Bearer {await run_db(_bearer, owner, tenant)}"}

    (at_customer,) = await _at(CUSTOMER_HOST, as_customer, ("tools/list", {}))
    (at_staff,) = await _at(STAFF_HOST, as_owner, ("tools/list", {}))
    customer_names = {tool["name"] for tool in at_customer}
    staff_names = {tool["name"] for tool in at_staff}

    assert {"list_widgets", "get_widget", "ping"} <= customer_names
    assert not {name for name in customer_names if "djb_note" in name}
    assert {"list_djb_notes", "get_djb_note"} <= staff_names
    assert customer_names < staff_names


# --- the host before the credential -------------------------------------------


async def test_an_unbound_host_is_refused_before_the_credential(two_faces: Surface) -> None:
    from config.asgi import build_application

    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{UNBOUND_HOST}"
        ) as client:
            response = await client.post("/mcp", headers=MCP_HEADERS, json={})

    assert response.status_code == 404, response.text
    body = response.json()
    assert body["code"] == "surface_unknown_host"
    assert body["remedies"]
    assert "customer" not in response.text


@pytest.mark.parametrize("forwarded", [False, True])
async def test_a_forwarded_host_is_the_host_only_where_a_proxy_of_ours_sets_it(
    two_faces: Surface, settings: Any, forwarded: bool
) -> None:
    """Sent at an unbound host naming the staff host in `X-Forwarded-Host`: with
    `USE_X_FORWARDED_HOST` off the raw `Host` wins and the host is refused; on, the
    forwarded host is the one the door resolves, and the call reaches the credential."""
    from config.asgi import build_application

    settings.USE_X_FORWARDED_HOST = forwarded
    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{UNBOUND_HOST}"
        ) as client:
            response = await client.post(
                "/mcp", headers={**MCP_HEADERS, "x-forwarded-host": STAFF_HOST}, json={}
            )

    if forwarded:
        assert response.status_code == 401, response.text
    else:
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "surface_unknown_host"


# --- the addressing law and the audit row carry the surface -------------------


async def test_a_sent_tenant_on_a_membership_surface_is_refused_as_at_the_http_door(
    two_faces: Surface, tenant: Tenant, customer: User
) -> None:
    from config.asgi import build_application

    headers = {
        **MCP_HEADERS,
        "authorization": f"Bearer {await run_db(_bearer, customer, tenant)}",
        "x-tenant": tenant.slug,
    }
    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{CUSTOMER_HOST}"
        ) as client:
            response = await client.post("/mcp", headers=headers, json={})

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "addressing_header_not_honoured"


async def test_a_write_at_the_customer_host_is_audited_as_made_there(
    two_faces: Surface, tenant: Tenant, customer: User
) -> None:
    headers = {**MCP_HEADERS, "authorization": f"Bearer {await run_db(_bearer, customer, tenant)}"}

    (refused,) = await _at(CUSTOMER_HOST, headers, ("create_widget", {"name": "From a customer"}))

    # The customer role holds exactly its declaration: the create is refused,
    # and the refusal's `outcome=error` row carries the surface it came in at.
    assert refused.get("isError") is True, refused
    written = await run_db(
        lambda: list(
            AuditEntry.objects.filter(
                action="example.create_widget", actor_user_id=customer.pk
            ).values_list("surface", "outcome", "object_id")
        )
    )
    assert {surface for surface, _, _ in written} == {"customer"}
    assert {(outcome, object_id) for _, outcome, object_id in written} == {("error", None)}


async def test_a_write_at_the_staff_host_is_audited_as_staff(
    two_faces: Surface, tenant: Tenant, owner: User
) -> None:
    headers = {**MCP_HEADERS, "authorization": f"Bearer {await run_db(_bearer, owner, tenant)}"}

    (created,) = await _at(STAFF_HOST, headers, ("create_widget", {"name": "From staff"}))

    assert created.get("isError") is not True, created
    widget_id = created["structuredContent"]["id"]
    surfaces_written = await run_db(
        lambda: set(
            AuditEntry.objects.filter(object_id=widget_id).values_list("surface", flat=True)
        )
    )
    assert surfaces_written == {STAFF}
    assert created["structuredContent"]["allowed_acts"]
