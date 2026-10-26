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
from typing import Any

import pytest
from django.core.management import call_command
from django.test import Client
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.comms.mcp import register
from apps.comms.models import Message, MessageTemplate, Recipient
from apps.comms.services import send
from apps.comms.tests.conftest import make_preference, make_recipient, make_template
from apps.core.actor import Actor
from apps.core.models import Organization, Tenant
from apps.core.services import root_organization
from apps.core.tests.mcp_context import context_for
from apps.core.tests.mcp_context import tool as core_tool
from apps.core.verbs import derive_tool_name
from config.api import as_the_door_renders

pytestmark = pytest.mark.django_db

MESSAGES_URL = "/api/v1/messages/"

#: A tool call is not a request: the page and the three reads `<kind>.read` costs once.
LIST_QUERY_BUDGET = 4


# --- A tool call, without a transport ------------------------------------------


def comms_server() -> MCPServer[Any]:
    """A server holding this app's tools and nothing else."""
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server


def tool(name: str) -> Callable[..., Any]:
    """The comms tool `name`, as `register` binds it."""
    return core_tool(name, register=register)


def introspected() -> dict[str, Any]:
    out = io.StringIO()
    call_command("introspect", stdout=out)
    payload: dict[str, Any] = json.loads(out.getvalue())
    return payload


# --- Door parity ----------------------------------------------------------------


def comms_routes() -> set[str]:
    """Every comms route's url_name, off the live registry."""
    payload = introspected()
    return {
        str(route["name"]).removeprefix("api:")
        for route in payload["routes"]
        if str(route["view"]).startswith("apps.comms.api.")
    }


def test_every_rest_capability_is_on_the_machine_door_as_its_derived_name() -> None:
    tools = {str(one["name"]) for one in introspected()["tools"]}
    missing = {name: derive_tool_name(name) for name in comms_routes()}
    assert {url: twin for url, twin in missing.items() if twin not in tools} == {}


def test_the_app_registers_those_tools_and_no_others() -> None:
    registered = {one.name for one in comms_server()._tool_manager.list_tools()}
    assert registered == {derive_tool_name(name) for name in comms_routes()}


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
        tool("get_message")(
            context_for(owner, tenant, root_organization(tenant=tenant)), message_id=message.pk
        ).model_dump_json()
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
    over_mcp = tool("get_message")(
        context_for(owner, tenant, root_organization(tenant=tenant)), message_id=message.pk
    )
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
    page = tool("list_messages")(context_for(owner, tenant, root_organization(tenant=tenant)))
    assert len(page.items) == len(over_http["items"])
    assert [str(item.id) for item in page.items] == [row["id"] for row in over_http["items"]]


# --- Behaviour -------------------------------------------------------------------


def test_the_tool_sends_and_the_row_says_queued(
    tenant: Tenant, owner: User, recipient: Recipient, receipt: MessageTemplate
) -> None:
    out = tool("send_message")(
        context_for(owner, tenant, root_organization(tenant=tenant)),
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
        context_for(owner, tenant, root_organization(tenant=tenant)),
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
        context_for(owner, tenant, root_organization(tenant=tenant)),
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
            context_for(owner, tenant, root_organization(tenant=tenant)),
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
        tool("get_message")(
            context_for(owner, tenant, root_organization(tenant=tenant)), message_id=theirs.pk
        )
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
    acting = context_for(owner, tenant, root_organization(tenant=tenant))
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        tool("list_messages")(acting)
