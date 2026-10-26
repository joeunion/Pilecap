"""The portal's doors as a real client meets them, at the customer host and the staff host.

The worked example of the machine door under a narrowed surface. Every door is
driven through the one real ASGI application over `httpx` and compared on the
WIRE — the REST body against the tool's `structuredContent`, both against the
event the spine recorded and the frame the socket delivered
(`apps.core.tests.doors`):

* at the customer host a customer's bearer reads one `Widget` and sends and
  reads one `PortalRequest`, and REST, MCP and the socket agree on each; the
  `djb_notes` family — on no customer's surface — is refused at all three with
  one code;
* at the staff host the owner reads the same request, and it is the same row
  (the second viewer): a disagreement between two surfaces over one record is a
  finding.

`transaction=True` because the transport runs a tool body on a worker thread
with its own connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

# golden: portal begin
from typing import Any

import httpx
import pytest

from apps.example.models import Widget
from apps.example.schemas import WidgetOut
from apps.example_portal.events import PORTAL_REQUEST_SUBMITTED
from apps.example_portal.schemas import PortalRequestOut
from apps.example_portal.tests.conftest import CUSTOMER_HOST, STAFF_HOST
from pilecap.accounts import User
from pilecap.realtime import EventMessage, push_event
from pilecap.surfaces import Surface
from pilecap.tenancy import Tenant
from pilecap.testing import (
    MCP_HEADERS,
    a_token,
    an_event,
    assert_four_doors,
    assert_refused_at_every_door,
    mcp_call,
    mcp_session,
    opened,
    recorded_envelope,
    run_db,
    running,
)

#: House rule 46. The door pair this module answers for `apps/example_portal`.
DOOR_PAIR = ("rest", "mcp")

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

REQUESTS = "/api/v1/portal-requests/"
REQUEST = "/api/v1/portal-requests/{}/"
WIDGET_FRAME = "example.widget.created"
NOTE_FRAME = "djb_notes.note.created"
NOT_EXPOSED = "surface_does_not_expose"


def _at(host: str, token: str) -> list[tuple[bytes, bytes]]:
    return [(b"host", host.encode()), (b"authorization", f"Bearer {token}".encode())]


async def _heard(host: str, token: str, tenant: Tenant, envelope: dict[str, Any]) -> dict[str, Any]:
    """The frame a socket at `host` receives when the spine pushes `envelope`."""
    async with opened(headers=_at(host, token)) as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=EventMessage.model_validate(envelope))
        frame: dict[str, Any] = await socket.receive_json()
    return frame


async def _notes_heard(token: str, tenant: Tenant) -> bool:
    async with opened(headers=_at(CUSTOMER_HOST, token)) as (socket, handshake):
        assert handshake.accepted is True
        await push_event(tenant_id=tenant.pk, event=an_event(NOTE_FRAME))
        return not await socket.received_nothing()


async def test_one_widget_and_one_request_agree_on_every_door_at_the_customer_host(
    two_hosts: Surface,
    tenant: Tenant,
    owner: User,
    customer: User,
    widget: Widget,
    recorded_workflow_starts: None,
) -> None:
    from config.asgi import build_application

    as_customer = await a_token(user=customer, tenant=tenant)
    as_owner = await a_token(user=owner, tenant=tenant)
    bearer = {"authorization": f"Bearer {as_customer}"}
    staff_bearer = {"authorization": f"Bearer {as_owner}"}
    subject = f"widget:{widget.pk}"
    application = build_application()

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{CUSTOMER_HOST}"
        ) as client:
            sent = await client.post(
                REQUESTS,
                headers={**bearer, "idempotency-key": "ask-1"},
                json={"widget_id": str(widget.pk), "note": "Send another?"},
            )
            assert sent.status_code == 201, sent.text
            request_id = sent.json()["id"]
            rest_widgets = await client.get("/api/v1/widgets/", headers=bearer)
            rest_request = await client.get(REQUEST.format(request_id), headers=bearer)
            rest_notes = await client.get(f"/api/v1/djb_notes/?subject={subject}", headers=bearer)
            customer_mcp = {**MCP_HEADERS, **bearer}
            await mcp_session(client, customer_mcp)
            mcp_widgets = await mcp_call(client, customer_mcp, "list_widgets")
            mcp_request = await mcp_call(
                client, customer_mcp, "get_portal_request", {"request_id": request_id}
            )
            mcp_notes = await mcp_call(client, customer_mcp, "list_djb_notes", {"subject": subject})
        async with httpx.AsyncClient(transport=transport, base_url=f"http://{STAFF_HOST}") as staff:
            staff_rest = await staff.get(REQUEST.format(request_id), headers=staff_bearer)
            staff_mcp_headers = {**MCP_HEADERS, **staff_bearer}
            await mcp_session(staff, staff_mcp_headers)
            staff_mcp = await mcp_call(
                staff, staff_mcp_headers, "get_portal_request", {"request_id": request_id}
            )

    widget_envelope = await run_db(recorded_envelope, tenant=tenant, name=WIDGET_FRAME)
    request_envelope = await run_db(recorded_envelope, tenant=tenant, name=PORTAL_REQUEST_SUBMITTED)
    widget_frame = await _heard(CUSTOMER_HOST, as_customer, tenant, widget_envelope)
    request_frame = await _heard(CUSTOMER_HOST, as_customer, tenant, request_envelope)
    notes_heard = await _notes_heard(as_customer, tenant)

    # The widget, read-only: offered no act on either viewer door.
    (rest_widget,) = rest_widgets.json()["items"]
    (mcp_widget,) = mcp_widgets["structuredContent"]["items"]
    assert rest_widget["allowed_acts"] == []
    assert widget_frame["name"] == WIDGET_FRAME
    assert_four_doors(
        rest=rest_widget, mcp=mcp_widget, event_payload=widget_frame["payload"], out=WidgetOut
    )

    # The request the customer sent, on every door at their host.
    assert rest_request.status_code == 200, rest_request.text
    assert rest_request.json() == sent.json()
    assert request_frame["name"] == PORTAL_REQUEST_SUBMITTED
    assert "requester_email" not in request_frame["payload"]
    assert_four_doors(
        rest=rest_request.json(),
        mcp=mcp_request["structuredContent"],
        event_payload=request_frame["payload"],
        out=PortalRequestOut,
    )

    # The second viewer: the staff at their host read the same row.
    assert staff_rest.status_code == 200, staff_rest.text
    assert_four_doors(
        rest=staff_rest.json(),
        mcp=staff_mcp["structuredContent"],
        event_payload=request_frame["payload"],
        out=PortalRequestOut,
    )
    assert staff_rest.json() == rest_request.json()

    # A family no customer's surface exposes: refused at all three, one code.
    assert_refused_at_every_door(
        code=NOT_EXPOSED, rest=rest_notes.json(), mcp=mcp_notes, socket_heard=notes_heard
    )


async def test_the_submit_twin_writes_the_row_the_rest_door_reads(
    two_hosts: Surface,
    tenant: Tenant,
    customer: User,
    widget: Widget,
    recorded_workflow_starts: None,
) -> None:
    """Rule 17's twin, over the wire: a request sent on MCP is the request REST answers."""
    from config.asgi import build_application

    bearer = {"authorization": f"Bearer {await a_token(user=customer, tenant=tenant)}"}
    application = build_application()

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{CUSTOMER_HOST}"
        ) as client:
            headers = {**MCP_HEADERS, **bearer}
            await mcp_session(client, headers)
            sent = await mcp_call(
                client,
                headers,
                "submit_portal_request",
                {"widget_id": str(widget.pk), "note": "Sent by a program"},
            )
            request_id = sent["structuredContent"]["id"]
            read = await client.get(REQUEST.format(request_id), headers=bearer)

    assert read.status_code == 200, read.text
    assert read.json() == sent["structuredContent"]


async def test_both_doors_narrow_to_one_widget_and_refuse_a_malformed_id_alike(
    two_hosts: Surface,
    tenant: Tenant,
    owner: User,
    customer: User,
    widget: Widget,
    recorded_workflow_starts: None,
) -> None:
    """One filter, two doors: the same page for a widget, the same refusal for a non-id."""
    from config.asgi import build_application

    other = await run_db(_a_second_widget, tenant=tenant, owner=owner)
    bearer = {"authorization": f"Bearer {await a_token(user=customer, tenant=tenant)}"}
    application = build_application()

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{CUSTOMER_HOST}"
        ) as client:
            for about in (widget, other):
                sent = await client.post(
                    REQUESTS, headers=bearer, json={"widget_id": str(about.pk), "note": "Hi"}
                )
                assert sent.status_code == 201, sent.text
            rest = await client.get(REQUESTS, params={"widget_id": str(widget.pk)}, headers=bearer)
            rest_bad = await client.get(REQUESTS, params={"widget_id": "nope"}, headers=bearer)
            headers = {**MCP_HEADERS, **bearer}
            await mcp_session(client, headers)
            mcp = await mcp_call(
                client, headers, "list_portal_requests", {"widget_id": str(widget.pk)}
            )
            mcp_bad = await mcp_call(client, headers, "list_portal_requests", {"widget_id": "nope"})

    assert rest.status_code == 200, rest.text
    (only,) = rest.json()["items"]
    assert only["widget_id"] == str(widget.pk)
    assert mcp["structuredContent"]["items"] == rest.json()["items"]
    # The house's argument pair: `invalid_arguments` is MCP's narrower `invalid`; one sentence.
    (said,) = rest_bad.json()["errors"]["widget_id"]
    assert rest_bad.status_code == 400, rest_bad.text
    assert rest_bad.json()["code"] == "invalid"
    assert mcp_bad["isError"] is True
    assert "invalid_arguments: " in _told(mcp_bad)
    assert f"(widget_id: {said})" in _told(mcp_bad)


async def test_both_doors_send_and_narrow_by_priority_and_refuse_a_bad_one_alike(
    two_hosts: Surface,
    tenant: Tenant,
    customer: User,
    widget: Widget,
    recorded_workflow_starts: None,
) -> None:
    from config.asgi import build_application

    bearer = {"authorization": f"Bearer {await a_token(user=customer, tenant=tenant)}"}
    about = {"widget_id": str(widget.pk), "note": "Soon"}
    application = build_application()

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url=f"http://{CUSTOMER_HOST}"
        ) as client:
            plain = await client.post(REQUESTS, headers=bearer, json=about)
            rest_sent = await client.post(
                REQUESTS, headers=bearer, json={**about, "priority": "high"}
            )
            rest_bad = await client.post(
                REQUESTS, headers=bearer, json={**about, "priority": "urgent"}
            )
            headers = {**MCP_HEADERS, **bearer}
            await mcp_session(client, headers)
            mcp_sent = await mcp_call(
                client, headers, "submit_portal_request", {**about, "priority": "high"}
            )
            mcp_bad = await mcp_call(
                client, headers, "submit_portal_request", {**about, "priority": "urgent"}
            )
            rest = await client.get(REQUESTS, params={"priority": "high"}, headers=bearer)
            mcp = await mcp_call(client, headers, "list_portal_requests", {"priority": "high"})

    assert plain.json()["priority"] == "normal"
    assert rest_sent.json()["priority"] == mcp_sent["structuredContent"]["priority"] == "high"
    assert len(rest.json()["items"]) == 2
    assert mcp["structuredContent"]["items"] == rest.json()["items"]
    (said,) = rest_bad.json()["errors"]["priority"]
    assert rest_bad.status_code == 422, rest_bad.text
    assert rest_bad.json()["code"] == "invalid_body"
    assert mcp_bad["isError"] is True
    assert "invalid_arguments: " in _told(mcp_bad)
    assert f"(priority: {said})" in _told(mcp_bad)


def _told(result: dict[str, Any]) -> str:
    return " ".join(str(block.get("text", "")) for block in result.get("content", []))


def _a_second_widget(*, tenant: Tenant, owner: User) -> Widget:
    from apps.example.services import create_widget
    from pilecap.tenancy import root_organization
    from pilecap.testing import actor_for

    actor = actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant))
    return create_widget(tenant=tenant, actor=actor, name="Right mount")


# golden: portal end
