"""The machine door onto comms, and the parity it owes the human one.

Two kinds of test, answering different questions.

**Parity** reads the *real* registries out of `manage.py introspect` — the ninja
routes and the MCP tools the server actually holds — and refuses a REST
capability with no tool. House rule 17 with teeth: adding a route to `api.py`
and forgetting `mcp.py` fails here, naming the missing tool.

**Behaviour** calls the tool functions directly, with a fake `Context` carrying
the `Principal` `config.mcp`'s token middleware would have left on the ASGI
scope. The one that matters is
`test_the_tool_refuses_the_same_send_the_route_refuses`: the consent wall is
inside `send()`, so an agent gets the same "no" a browser does, and gets it as
a row rather than as an error it would be tempted to retry.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from django.core.management import call_command
from django.test import Client
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.comms.mcp import register
from apps.comms.models import Message, MessageTemplate, Recipient
from apps.comms.services import send
from apps.comms.tests.conftest import make_preference, make_recipient, make_template
from apps.core.actor import Actor
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.models import Organization, Tenant
from apps.core.services import root_organization
from config.api import as_the_door_renders

pytestmark = pytest.mark.django_db

MESSAGES_URL = "/api/v1/messages/"

# For every REST capability, the tool that is its twin. A new route with no
# entry here fails the parity test, and an entry with no tool fails it too.
TOOL_FOR_ROUTE: dict[str, str] = {
    "message-list": "list_messages",
    "message-detail": "get_message",
    "message-send": "send_message",
    "template-list": "list_templates",
    "template-detail": "get_template",
    "template-create": "create_template",
    "template-revise": "revise_template",
    "template-retire": "retire_template",
    "recipient-list": "list_recipients",
    "recipient-detail": "get_recipient",
    "recipient-create": "create_recipient",
    "recipient-update": "update_recipient",
    "recipient-archive": "archive_recipient",
    "recipient-suppress": "suppress_recipient",
    "recipient-unsuppress": "unsuppress_recipient",
    # C2-comms-b. `policies-list` rather than `policy-list` is deliberate and is
    # explained where the route is declared: house rule 17 derives the tool name
    # from the url_name, and the singular noun would have produced `list_policys`.
    "policies-list": "list_policies",
    "policy-detail": "get_policy",
    "policy-create": "create_policy",
    "policy-revise": "revise_policy",
    "policy-retire": "retire_policy",
    "preference-list": "list_preferences",
    "consent-grant": "grant_consent",
    "consent-revoke": "revoke_consent",
    "quiet_hours-set": "set_quiet_hours",
    # `engagement-list` rather than `message-engagement-list`, for the
    # reason the policies entry above records: the tool name is DERIVED from the
    # url_name by splitting on the last hyphen, and the longer spelling would
    # have produced `list_message-engagements` — a hyphen inside a machine-door
    # name.
    "message-cancel": "cancel_message",
    "engagement-list": "list_engagements",
    "device-register": "register_device",
    "device-retire": "retire_device",
}

# Measured at ten rows, not guessed: the page, and only the page. There is no
# session row, no middleware and no savepoint out here — a tool call is not a
# request — and after ADR core-18 there is no COUNT either unless the caller
# sends `include_count`, which is what took this from 2 to 1.
LIST_QUERY_BUDGET = 1


# --- A tool call, without a transport ------------------------------------------


@dataclass
class _FakeRequest:
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def context_for(user: User, tenant: Tenant | None, org: Organization | None = None) -> Context[Any]:
    resolved = org if org is not None else (root_organization(tenant=tenant) if tenant else None)
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=resolved)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def comms_server() -> MCPServer[Any]:
    """A server holding this app's tools and nothing else."""
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server


def tool(name: str) -> Callable[..., Any]:
    registered = comms_server()._tool_manager.get_tool(name)
    assert registered is not None, f"{name} is not registered"
    return registered.fn


def introspected() -> dict[str, Any]:
    out = io.StringIO()
    call_command("introspect", stdout=out)
    payload: dict[str, Any] = json.loads(out.getvalue())
    return payload


# --- Door parity ----------------------------------------------------------------


def test_every_rest_capability_is_on_the_machine_door_too() -> None:
    payload = introspected()
    routes = {
        str(route["name"]).removeprefix("api:")
        for route in payload["routes"]
        if str(route["view"]).startswith("apps.comms.api.")
    }
    assert routes == set(TOOL_FOR_ROUTE), (
        "A comms route has no entry in TOOL_FOR_ROUTE: either the machine door "
        "is missing a capability the human door has, or this table is stale."
    )
    tools = {str(one["name"]) for one in payload["tools"]}
    assert set(TOOL_FOR_ROUTE.values()) <= tools


def test_the_app_registers_those_tools_and_no_others() -> None:
    registered = {one.name for one in comms_server()._tool_manager.list_tools()}
    assert registered == set(TOOL_FOR_ROUTE.values())


def test_every_tool_describes_itself() -> None:
    for one in comms_server()._tool_manager.list_tools():
        assert one.description, f"{one.name} has no description"


def test_a_tool_and_its_route_answer_with_the_same_row(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    message = send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    api.force_login(owner)
    over_http = json.loads(api.get(f"{MESSAGES_URL}{message.pk}/").content)
    over_mcp = json.loads(
        tool("get_message")(context_for(owner, tenant), message_id=message.pk).model_dump_json()
    )
    assert as_the_door_renders(over_mcp) == as_the_door_renders(over_http)


def test_the_tool_answers_with_the_same_KEYS_over_the_wire_too(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    """Parity of key *names*, not only of values — the failure a value test misses.

    The MCP transport serialises a tool result **by alias**, so a schema field
    carrying `Field(alias="recipient.email")` answers `recipient.email` at the
    machine door and `recipient_email` at the human one: the same row in two
    shapes, and every value assertion still green. `MessageOut` therefore
    carries no aliases at all and reads two properties off `Message` instead;
    this dumps by alias, which is what the transport does, and demands the key
    set the REST door published.
    """
    message = send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    api.force_login(owner)
    over_http = json.loads(api.get(f"{MESSAGES_URL}{message.pk}/").content)
    over_mcp = tool("get_message")(context_for(owner, tenant), message_id=message.pk)
    assert set(over_mcp.model_dump(by_alias=True)) == set(over_http)


def test_the_list_tool_and_the_list_route_agree(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
) -> None:
    send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )
    api.force_login(owner)
    over_http = json.loads(api.get(MESSAGES_URL).content)
    page = tool("list_messages")(context_for(owner, tenant))
    assert len(page.items) == len(over_http["items"])
    assert [str(item.id) for item in page.items] == [row["id"] for row in over_http["items"]]


# --- Behaviour -------------------------------------------------------------------


def test_the_tool_sends_and_the_row_says_queued(
    tenant: Tenant, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    out = tool("send_message")(
        context_for(owner, tenant),
        recipient_id=recipient.pk,
        template="receipt",
        context={"name": "Ada"},
    )
    assert out.status == Message.Status.QUEUED
    assert Message.objects.for_tenant(tenant).count() == 1


def test_the_tool_refuses_the_same_send_the_route_refuses(
    tenant: Tenant, owner: User, recipient: Recipient, newsletter: MessageTemplate
) -> None:
    """The consent wall is inside `send()`, so the machine door cannot go round it.

    And it comes back as a **row**, not an error: a `ToolError` here would teach
    an agent to retry, which is the one response to "this person opted out" that
    must never happen.
    """
    out = tool("send_message")(
        context_for(owner, tenant),
        recipient_id=recipient.pk,
        template="newsletter",
        context={"name": "Ada"},
    )
    assert out.status == Message.Status.SUPPRESSED
    assert out.suppressed_reason == Message.SuppressedReason.NO_CONSENT


def test_the_tool_sends_once_they_consent(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    newsletter: MessageTemplate,
) -> None:
    make_preference(actor=owner_actor, recipient=recipient, consented=True)
    out = tool("send_message")(
        context_for(owner, tenant),
        recipient_id=recipient.pk,
        template="newsletter",
        context={"name": "Ada"},
    )
    assert out.status == Message.Status.QUEUED


def test_a_bad_context_is_a_tool_error_naming_the_field(
    tenant: Tenant, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    """Bad input *does* raise — it is the one thing an agent should fix and retry."""
    with pytest.raises(ToolError) as raised:
        tool("send_message")(
            context_for(owner, tenant),
            recipient_id=recipient.pk,
            template="receipt",
            context={},
        )
    assert "invalid" in str(raised.value)
    assert "name" in str(raised.value)


def test_a_tool_cannot_reach_another_tenants_message(
    tenant: Tenant,
    other_tenant: Tenant,
    other_root_org: Organization,
    owner: User,
    stranger: User,
    stranger_actor: Actor,
) -> None:
    make_template(actor=stranger_actor)
    theirs = send(
        recipient=make_recipient(actor=stranger_actor, email="them@example.com"),
        template="receipt",
        context={"name": "Grace"},
        channel="email",
        tenant=other_tenant,
        actor=stranger_actor,
    )
    with pytest.raises(ToolError) as raised:
        tool("get_message")(context_for(owner, tenant), message_id=theirs.pk)
    assert "not_found" in str(raised.value)


def test_the_list_tool_has_a_query_budget_too(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    django_assert_num_queries: Any,
) -> None:
    for index in range(10):
        send(
            recipient=recipient,
            template="receipt",
            context={"name": f"Reader {index}"},
            channel="email",
            tenant=tenant,
            actor=owner_actor,
        )
    acting = context_for(owner, tenant)
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        tool("list_messages")(acting)
