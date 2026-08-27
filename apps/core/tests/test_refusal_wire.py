"""One refusal, two doors, one grammar — over the wire rather than at the unit.

`test_refusals.py` proves the registry is complete and that the composer is the
only thing building a body. This module drives the two doors that render it and
asserts they say the same thing, because "one composer" is a claim about what a
*caller* receives, and a caller does not import `wire_refusal`.

Three claims:

* the REST body of a real 404 is `{detail, code, remedies}`, the
  remedies are structured, and the registry's internal `remedy` prose (which
  names `policies.py`, `X-Tenant` and the scoped selector) appears nowhere in
  it. Internal advice on the wire is advice somebody starts parsing.
* the same refusal through an MCP tool carries the same code, the
  same detail and the same remedies, rendered from the same body. A screen and
  an assistant offering different ways out is the drift the grammar exists
  against, and it is the failure no per-door test could ever catch.
* a **true race**: both doors saw an `IntegrityError`, the
  REST door has always answered 409 `conflict`, and the machine door used to
  let it escape unhandled. One behaviour now, from one translation.

DOES NOT COVER — declared: whether a remedy's `destination` points anywhere
real. It is an opaque string by ADR core-5's own boundary and stays one until a
product ships a navigation manifest; a label that lies passes everything here.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

import pytest
from django.db import transaction
from django.test import Client
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.core.actor import actor_for
from apps.core.exceptions import REFUSALS, Conflict, refusal_message, wire_refusal
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.models import Organization, Tenant
from apps.example.mcp import register
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = pytest.mark.django_db

WIDGETS = "/api/v1/widgets/"


# --- the machine door, driven as a function (§12 of django-conventions) ------


@dataclass
class _FakeRequest:
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def mcp_context(user: User, tenant: Tenant, org: Organization | None) -> Context[Any]:
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=org)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def tool(name: str) -> Any:
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server._tool_manager._tools[name].fn


# --- W1R1-5: the wire, REST --------------------------------------------------


def test_a_rest_refusal_carries_the_remedies_and_none_of_the_internal_prose(
    api: Client, owner: User
) -> None:
    """The 404 a caller actually gets, read key by key.

    `remedies` is the addition ADR core-5 makes and the reason the old pin was
    amended (see `test_api_errors.py`); `detail` and `code` are what
    they always were. What must NOT be there is the registry's `remedy` — the
    developer's sentence, which names the scoped selector and the two headers —
    and the `fact`, which is what the *code* means rather than what happened
    here.
    """
    api.force_login(owner)
    response = api.get(f"{WIDGETS}{uuid4()}/")
    assert response.status_code == 404

    body = response.json()
    assert set(body) == {"detail", "code", "remedies"}
    assert body["code"] == "not_found"
    assert body["remedies"] == [
        {"label": "Check which tenant you are acting in", "destination": "header:X-Tenant"},
        {"label": "Check which organization you are wearing", "destination": "header:X-Org"},
    ]
    for remedy in body["remedies"]:
        assert set(remedy) == {"label", "destination"}

    registered = REFUSALS["not_found"]
    rendered = json.dumps(body)
    assert registered.remedy not in rendered
    # Not just the whole sentence: no clause of it, either. The remedy names
    # the selector and the file, and a leak that dropped a full stop would
    # still be a leak.
    assert "for_tenant" not in rendered and "visible_to" not in rendered
    assert registered.fact not in rendered


# --- the wire, MCP --------------------------------------------------------------


def test_both_doors_render_one_refusal_the_same_way(
    api: Client, owner: User, tenant: Tenant, root_org: Organization
) -> None:
    """Door parity for a refusal, field by field against the REST body.

    The comparison is deliberately against the *human* door's body rather than
    against a string this test wrote: a message asserted on its own would still
    pass on the day the two doors drifted apart.
    """
    missing = uuid4()
    api.force_login(owner)
    rest = api.get(f"{WIDGETS}{missing}/")
    assert rest.status_code == 404
    body = rest.json()

    with pytest.raises(ToolError) as raised:
        tool("get_widget")(ctx=mcp_context(owner, tenant, root_org), widget_id=missing)

    message = str(raised.value)
    assert message.startswith(f"{body['code']}: {body['detail']}")
    for remedy in body["remedies"]:
        assert f"{remedy['label']} [{remedy['destination']}]" in message
    # And the whole string is what the one composer renders from the one body.
    assert message == refusal_message(body)


def test_the_machine_door_does_not_leak_the_internal_remedy_either(
    owner: User, tenant: Tenant, root_org: Organization
) -> None:
    """The same protection the REST body gets, given to the message.

    An assistant is the reader most likely to repeat internal advice verbatim
    to a person, which makes this the door where the leak would do the most
    damage rather than the least.
    """
    with pytest.raises(ToolError) as raised:
        tool("get_widget")(ctx=mcp_context(owner, tenant, root_org), widget_id=uuid4())
    assert REFUSALS["not_found"].remedy not in str(raised.value)


# --- an authorization refusal, in plain language, at both doors ----------------


def test_an_authorization_refusal_says_what_it_means_at_both_doors(
    api: Client, member: User, tenant: Tenant, root_org: Organization
) -> None:
    """`require` no longer publishes the action name, and the twin follows.

    Until 2026-08-24 a refused caller was told "You may not invitation.create."
    — the internal policy key, on the wire, from a product that has otherwise
    never shown a caller an identifier (FT-1's F7). The sentence now comes from
    the app's own `ACTION_PROSE` beside the policy that refused.

    **The machine door needed no change at all**, and that is the claim worth
    proving: `core.mcp.tool_call` renders the same body `config/api.py` sends,
    through `refusal_message`, so the REST body is the only place the prose
    exists. Asserted against the REST body rather than against a string this
    test wrote, for the reason stated above — a message asserted on its own
    still passes on the day the doors drift.
    """
    from apps.core.mcp import register as register_core

    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register_core(server)
    create_invitation = server._tool_manager._tools["create_invitation"].fn

    api.force_login(member)
    rest = api.post(
        "/api/v1/invitations/",
        data=json.dumps({"email": "dana@example.com", "role": "member"}),
        content_type="application/json",
    )
    assert rest.status_code == 403
    body = rest.json()
    assert body["code"] == "forbidden"
    assert body["detail"] == "You may not invite people into that organization."
    assert "invitation.create" not in json.dumps(body)

    with pytest.raises(ToolError) as raised:
        create_invitation(
            ctx=mcp_context(member, tenant, root_org), email="dana@example.com", role="member"
        )
    assert str(raised.value) == refusal_message(body)


# --- a true race, said the same way at both doors -------------------------------


def _plant_a_true_race(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `full_clean()` miss what the database will not.

    This is not a contrivance — it is precisely the loser of a real race. Two
    requests arrive together, both run `full_clean()` before either has
    inserted, both pass, and the second `save()` meets the unique constraint.
    Suppressing the check reproduces that window deterministically, so the
    assertion is about what happens when `IntegrityError` reaches the door,
    which is the only part either door owns.
    """
    monkeypatch.setattr(Widget, "full_clean", lambda self, *a, **k: None)


def test_a_true_race_is_a_conflict_at_the_machine_door(
    monkeypatch: pytest.MonkeyPatch,
    owner: User,
    tenant: Tenant,
    root_org: Organization,
) -> None:
    """The doors used to disagree about the same `IntegrityError`.

    REST answered 409 `conflict`; MCP translated only `RateLimited`, so this
    escaped as an unhandled exception and an assistant got a traceback where a
    client got a contract. Now `tool_call` performs the identical translation.
    """
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    create_widget(tenant=tenant, actor=acting, name="Only One")
    _plant_a_true_race(monkeypatch)

    with pytest.raises(ToolError) as raised, transaction.atomic():
        tool("create_widget")(ctx=mcp_context(owner, tenant, root_org), name="Only One")

    message = str(raised.value)
    assert message.startswith("conflict: ")
    # The database's own message names tables, columns and constraint names,
    # and none of it is a client's business — at either door.
    assert "widget_unique_name_per_owner_per_tenant" not in message
    assert "duplicate key" not in message


def test_the_rest_twin_of_that_race_is_still_a_409(
    monkeypatch: pytest.MonkeyPatch,
    api: Client,
    owner: User,
    tenant: Tenant,
    root_org: Organization,
) -> None:
    """The other half of the race: the door that was already right stays right.

    A fix that made the two doors agree by changing the one that was correct
    would be a regression wearing a parity argument.
    """
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    create_widget(tenant=tenant, actor=acting, name="Only One")
    _plant_a_true_race(monkeypatch)

    api.force_login(owner)
    with transaction.atomic():
        response = api.post(
            WIDGETS,
            data=json.dumps({"name": "Only One", "notes": ""}),
            content_type="application/json",
        )
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_the_two_translations_of_a_race_produce_the_same_body() -> None:
    """One behaviour, asserted as one object rather than as two matching strings.

    `config/api.py:on_integrity_error` and `core.mcp.tool_call` both answer an
    `IntegrityError` with a bare `Conflict()`, so the body each renders is the
    same body. Stated here so that a lane changing one of them has to come past
    this line to do it.
    """
    body = wire_refusal(Conflict())
    assert body["code"] == "conflict"
    assert body["remedies"] == [
        {
            "label": "Re-read the row and retry against what is true now",
            "destination": "self:reread",
        },
        {
            "label": "Ask for the first answer back instead of a second attempt",
            "destination": "header:Idempotency-Key",
        },
    ]
    assert refusal_message(body).startswith("conflict: ")
