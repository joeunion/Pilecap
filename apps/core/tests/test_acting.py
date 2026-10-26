"""The `acting` road: no acting scope is ONE registered refusal at both doors.

Before `apps/core/api/acting.py` every app's REST door carried its own
`_acting(request)` and refused a request that resolved no tenant with
`raise HttpError(403, "No tenant for this request.")` — which the HTTP door
translated to `forbidden` with a sentence nobody could branch on — while the
machine door raised `ToolError("no_tenant: …")` with a code the registry did not
hold. One absence, two answers, neither registered.

Now both doors raise `no_acting_scope` (`apps.core.exceptions.NoActingScope`),
composed by the one `wire_refusal`: REST sends the body, MCP renders that same
body as its one line. Driven over the wire below, at the core routes that call
the road, with a person who holds no membership at all.

**The addressing half (2a.2) was already one law.** A SENT `X-Org` that names
nowhere the caller can act refuses `addressing_header_not_honoured` at every
door — `test_addressing_headers.py`'s REST and MCP tables, and
`apps/realtime/tests/test_addressing_headers.py`'s `SOCKET_ROWS` for the socket.
The case the consolidation's survey measured as `200 []` is pinned here so a
regression to the empty page fails by name.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import Actor, actor_for
from apps.core.api.acting import Acting, acting, require_hat
from apps.core.exceptions import (
    REFUSALS,
    WIRE_COMMON_KEYS,
    NoActingScope,
    refusal_message,
    wire_refusal,
)
from apps.core.models import Organization, Tenant
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running

CODE = "no_acting_scope"
ORGANIZATIONS = "/api/v1/organizations/"
WIDGETS = "/api/v1/widgets/"


def test_the_code_is_registered_at_the_door_with_its_number() -> None:
    """`introspect` lists it; it is the door's, and it is a 403 — the credential is fine."""
    registered = REFUSALS[CODE]
    assert registered.boundary == "door"
    assert registered.status == 403
    assert registered.remedies
    assert issubclass(NoActingScope, Exception)
    assert NoActingScope.code == CODE


@pytest.mark.django_db
def test_rest_answers_a_person_with_no_membership_with_the_registered_code(nomad: User) -> None:
    """RED on the baseline: `403 {"code": "forbidden", "detail": "No tenant for this request."}`."""
    client = Client()
    client.force_login(nomad)
    answered = client.get(ORGANIZATIONS)
    assert answered.status_code == 403, answered.content
    body = answered.json()
    assert body["code"] == CODE, body
    assert set(body) <= WIRE_COMMON_KEYS, body
    assert body["remedies"], body
    assert body == wire_refusal(NoActingScope())


@pytest.mark.django_db
def test_a_tenant_with_no_hat_is_the_same_code_in_its_own_words(tenant: Tenant) -> None:
    """`require_hat` — the subtree reads' root — refuses with the same code, the hat's sentence."""
    with pytest.raises(NoActingScope) as refused:
        require_hat(Actor(user=None, token=None, kind="human", tenant=tenant, org=None))
    assert refused.value.detail == NoActingScope.no_hat_detail
    assert refused.value.code == CODE
    # Neither resolved: the tenant's absence is the one named, as at MCP.
    with pytest.raises(NoActingScope) as neither:
        require_hat(Actor(user=None, token=None, kind="human", tenant=None, org=None))
    assert neither.value.detail == NoActingScope.default_detail


@pytest.mark.django_db
def test_acting_resolves_and_unpacks(tenant: Tenant, owner: User, root_org: Organization) -> None:
    """The value a route reads: the request's actor and tenant, and the hat on the actor."""
    request = RequestFactory().get("/")
    request.user = owner
    request.tenant = tenant  # type: ignore[attr-defined]
    request.org = root_org  # type: ignore[attr-defined]
    resolved = acting(request)
    assert isinstance(resolved, Acting)
    actor, unpacked_tenant = resolved
    assert unpacked_tenant == tenant
    assert actor is resolved.actor
    assert resolved.hat == root_org == resolved.org


def test_acting_refuses_a_request_that_resolved_no_tenant() -> None:
    request = RequestFactory().get("/")
    request.tenant = None  # type: ignore[attr-defined]
    with pytest.raises(NoActingScope):
        acting(request)


@pytest.mark.django_db
def test_a_sent_unresolvable_hat_refuses_rather_than_answering_empty(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    """2a.2's measured RED was `200 {"items": []}` — on this tree it refuses, at the list.

    A pin and not a change: the addressing law (ADR core-21) already reaches every
    route through the mount's one seam (`config/api.py::_refused_for_addressing`).
    """
    client = Client()
    client.force_login(owner)
    answered = client.get(WIDGETS, headers={"x-org": "nope"})
    assert answered.status_code == 403, answered.content
    assert answered.json()["code"] == "addressing_header_not_honoured", answered.json()


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_say_the_same_refusal(nomad: User) -> None:
    """The same person, no membership, a token with no tenant: one body, both doors.

    RED on the baseline: REST answered `forbidden` with "No tenant for this
    request." and MCP answered `no_tenant: …` — two codes, neither registered as
    that meaning.
    """
    from apps.core.asyncdb import run_db
    from config.asgi import build_application

    _, bearer = await run_db(
        issue_token,
        user=nomad,
        tenant=None,
        name="nowhere",
        actor=actor_for(user=nomad, tenant=None),
    )
    headers = {"authorization": f"Bearer {bearer}"}
    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                ORGANIZATIONS, headers={**headers, "accept": "application/json"}
            )
            rpc_headers = {**MCP_HEADERS, **headers}
            initialize = await client.post(
                "/mcp",
                headers=rpc_headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "acting", "version": "1"},
                    },
                    1,
                ),
            )
            assert initialize.status_code == 200, initialize.text
            called = await client.post(
                "/mcp",
                headers=rpc_headers,
                json=_rpc("tools/call", {"name": "list_organizations", "arguments": {}}, 2),
            )

    assert over_http.status_code == 403, over_http.text
    body = over_http.json()
    assert body["code"] == CODE, body
    result = called.json()["result"]
    assert result.get("isError"), result
    line = str(result["content"][0]["text"])
    # The machine door's line is the one composer's rendering of REST's body —
    # every key, the remedies included (the transport prefixes the tool's name).
    assert line.endswith(refusal_message(body)), (line, body)
