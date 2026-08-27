"""The machine door onto the spine, and the three things it owes the human one.

**Parity** reads the *real* registries out of `manage.py introspect` — the ninja
routes and the MCP tools the server actually holds — and refuses a REST
capability with no tool. House rule 17 with teeth: adding a route to `api.py`
and forgetting `mcp.py` fails here, naming the missing tool.

**Byte-identity of refusals** (criterion E9, run per rung) is the one worth
reading. A service refuses; `config/api.py` renders that refusal as a JSON body
and `core.mcp.tool_call` renders the *same* body as one line of text. So the
machine door's message must be exactly `refusal_message(<the REST body>)` — not
similar to it, not carrying the same code, but equal, for every refusal this
rung can produce. The artifact is asserted here rather than described: an
assistant that offered a different way out than the screen did is the drift the
one-composer rule exists to close.

**The secret is shown once here too.** An agent holding an endpoint id can no
more read its signing key back than a browser can, because both doors return the
same `WebhookEndpointOut`, which has no field for one.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.test import Client
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.exceptions import refusal_message
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.models import Organization, Tenant
from apps.core.services import root_organization
from apps.events import services
from apps.events.mcp import register
from apps.events.models import Delivery, WebhookEndpoint
from apps.events.tests.test_api import _dead_letter
from apps.example.events import WIDGET_CREATED
from config.api import as_the_door_renders

pytestmark = pytest.mark.django_db

ENDPOINTS_URL = "/api/v1/webhook-endpoints/"
CATALOGUE_URL = "/api/v1/event-types/"
DEAD_LETTERS_URL = "/api/v1/dead-letters/"
JSON = "application/json"

# For every REST capability, the tool that is its twin. A new route with no
# entry here fails the parity test, and an entry with no tool fails it too.
TOOL_FOR_ROUTE: dict[str, str] = {
    "endpoint-list": "list_endpoints",
    "endpoint-create": "create_endpoint",
    "endpoint-detail": "get_endpoint",
    "endpoint-update": "update_endpoint",
    # `endpoint_secret-issue` rather than `endpoint-issue`: house rule 17 derives
    # the tool name from the url_name, and the thing being issued is the secret
    # rather than the endpoint.
    "endpoint_secret-issue": "issue_endpoint_secret",
    "endpoint-pause": "pause_endpoint",
    "endpoint-resume": "resume_endpoint",
    "event_type-list": "list_event_types",
    # `deliveries-list` and `dead_letters-list` rather than the singular nouns,
    # for the reason comms' `policies-list` gives: the derivation would look for
    # `list_deliverys`.
    "deliveries-list": "list_deliveries",
    "dead_letters-list": "list_dead_letters",
    "dead_letter-replay": "replay_dead_letter",
}

# Measured at twelve endpoints, not guessed: the page and its COUNT. There is no
# session row, no middleware and no savepoint out here — a tool call is not a
# request.
# ADR core-18 took one statement OFF this pin: the default list issues no
# COUNT any more — `has_more` comes from fetching one row more than asked
# for. `?include_count=true` puts it back, and costs exactly one more.
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


def events_server() -> MCPServer[Any]:
    """A server holding this app's tools and nothing else."""
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server


def tool(name: str) -> Callable[..., Any]:
    registered = events_server()._tool_manager.get_tool(name)
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
        if str(route["view"]).startswith("apps.events.api.")
    }
    assert routes == set(TOOL_FOR_ROUTE), (
        "An events route has no entry in TOOL_FOR_ROUTE: either the machine door "
        "is missing a capability the human door has, or this table is stale."
    )
    tools = {str(one["name"]) for one in payload["tools"]}
    assert set(TOOL_FOR_ROUTE.values()) <= tools


def test_the_app_registers_those_tools_and_no_others() -> None:
    registered = {one.name for one in events_server()._tool_manager.list_tools()}
    assert registered == set(TOOL_FOR_ROUTE.values())


def test_every_tool_describes_itself_in_the_words_the_document_uses() -> None:
    """One docstring, two doors (house rule 41): the tool renders the route's own.

    A `description=` typed here would be the first place the two doors drift, and
    prose drifts long before behaviour does.
    """
    from apps.core.api.docs import contract_of
    from apps.events import api

    route_for_tool = {tool_name: route for route, tool_name in TOOL_FOR_ROUTE.items()}
    views = {
        str(route["name"]).removeprefix("api:"): route["view"]
        for route in introspected()["routes"]
        if str(route["view"]).startswith("apps.events.api.")
    }
    for one in events_server()._tool_manager.list_tools():
        assert one.description, f"{one.name} has no description"
        view_path = views[route_for_tool[one.name]]
        view = getattr(api, str(view_path).rsplit(".", 1)[-1])
        assert one.description == contract_of(view), one.name


# --- The same rows, and the same absence of a secret ---------------------------


def test_a_tool_and_its_route_answer_with_the_same_endpoint(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    endpoint = services.register_endpoint(
        tenant=tenant, actor=owner_actor, url="https://subscriber.example/hook"
    )
    api.force_login(owner)
    over_http = json.loads(api.get(f"{ENDPOINTS_URL}{endpoint.pk}/").content)
    over_mcp = json.loads(
        tool("get_endpoint")(context_for(owner, tenant), endpoint_id=endpoint.pk).model_dump_json()
    )
    assert as_the_door_renders(over_mcp) == as_the_door_renders(over_http)


def test_the_tool_answers_with_the_same_KEYS_over_the_wire_too(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """Parity of key *names*, not only of values — the failure a value test misses.

    The MCP transport serialises a tool result **by alias**, so an aliased field
    answers one key at the machine door and another at the human one: the same
    row in two shapes, with every value assertion still green.
    """
    endpoint = services.register_endpoint(
        tenant=tenant, actor=owner_actor, url="https://subscriber.example/hook"
    )
    api.force_login(owner)
    over_http = json.loads(api.get(f"{ENDPOINTS_URL}{endpoint.pk}/").content)
    over_mcp = tool("get_endpoint")(context_for(owner, tenant), endpoint_id=endpoint.pk)
    assert set(over_mcp.model_dump(by_alias=True)) == set(over_http)
    assert "secret" not in over_mcp.model_dump(by_alias=True)


def test_the_machine_door_shows_the_secret_once_and_never_again(
    tenant: Tenant, owner: User
) -> None:
    """An agent has exactly the same one chance a browser does, and no more."""
    acting = context_for(owner, tenant)
    created = tool("create_endpoint")(acting, url="https://subscriber.example/hook")
    minted = created.secret
    assert minted

    for name, kwargs in (
        ("get_endpoint", {"endpoint_id": created.endpoint.id}),
        ("update_endpoint", {"endpoint_id": created.endpoint.id, "description": "renamed"}),
        ("pause_endpoint", {"endpoint_id": created.endpoint.id}),
        ("resume_endpoint", {"endpoint_id": created.endpoint.id}),
    ):
        rendered = tool(name)(acting, **kwargs).model_dump_json()
        assert minted not in rendered, f"{name} handed the signing key back"
        assert "secret" not in rendered, f"{name} has a field named for one"

    rotated = tool("issue_endpoint_secret")(acting, endpoint_id=created.endpoint.id)
    assert rotated.secret != minted


def test_the_catalogue_twin_is_byte_equal_to_the_route(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """E1: one schema per shape, shared — so one census, rendered identically."""
    api.force_login(owner)
    over_http = json.loads(api.get(f"{CATALOGUE_URL}?limit=200").content)
    over_mcp = json.loads(
        tool("list_event_types")(context_for(owner, tenant), limit=200).model_dump_json()
    )
    assert over_mcp == over_http
    assert WIDGET_CREATED in {item["name"] for item in over_mcp["items"]}


def test_the_delivery_lists_agree_across_the_doors(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    dead = _dead_letter(tenant, owner_actor)
    api.force_login(owner)
    over_http = json.loads(api.get(DEAD_LETTERS_URL).content)
    over_mcp = json.loads(tool("list_dead_letters")(context_for(owner, tenant)).model_dump_json())
    assert len(over_mcp["items"]) == len(over_http["items"]) == 1
    assert [as_the_door_renders(item) for item in over_mcp["items"]] == [
        as_the_door_renders(item) for item in over_http["items"]
    ]
    assert over_mcp["items"][0]["id"] == str(dead.pk)


# --- E9: the refusal is byte-identical through both doors -----------------------


def _rest_and_mcp_refusal(
    *,
    api: Client,
    owner: User,
    tenant: Tenant | None,
    request: Callable[[], Any],
    call: Callable[[], Any],
) -> tuple[dict[str, Any], str]:
    """Drive one refusal through each door and hand back both renderings."""
    api.force_login(owner)
    response = request()
    assert response.status_code >= 400, response.content
    body: dict[str, Any] = json.loads(response.content)
    with pytest.raises(ToolError) as refused:
        call()
    return body, str(refused.value)


@pytest.mark.parametrize("case", ["not_found", "invalid", "forbidden"])
def test_a_service_refusal_is_byte_identical_through_both_doors(
    api: Client,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    member: User,
    owner_actor: Actor,
    stranger_actor: Actor,
    case: str,
) -> None:
    """Criterion E9, for each refusal this door pair can produce.

    The assertion is equality with `refusal_message(<the REST body>)`, not
    similarity: the REST door sends the body `wire_refusal` composed and the MCP
    door renders that same body through `refusal_message`. Anything less than
    equality here would mean a second composer had appeared somewhere.
    """
    if case == "not_found":
        theirs = services.register_endpoint(
            tenant=other_tenant, actor=stranger_actor, url="https://elsewhere.example/hook"
        )
        body, message = _rest_and_mcp_refusal(
            api=api,
            owner=owner,
            tenant=tenant,
            request=lambda: api.get(f"{ENDPOINTS_URL}{theirs.pk}/"),
            call=lambda: tool("get_endpoint")(context_for(owner, tenant), endpoint_id=theirs.pk),
        )
        assert body["code"] == "not_found"
    elif case == "invalid":
        body, message = _rest_and_mcp_refusal(
            api=api,
            owner=owner,
            tenant=tenant,
            request=lambda: api.post(
                ENDPOINTS_URL,
                data=json.dumps(
                    {"url": "https://subscriber.example/hook", "event_names": ["nope.nope.nope"]}
                ),
                content_type=JSON,
            ),
            call=lambda: tool("create_endpoint")(
                context_for(owner, tenant),
                url="https://subscriber.example/hook",
                event_names=["nope.nope.nope"],
            ),
        )
        assert body["code"] == "invalid"
        assert body["errors"]["event_names"]
    else:
        body, message = _rest_and_mcp_refusal(
            api=api,
            owner=member,
            tenant=tenant,
            request=lambda: api.post(
                ENDPOINTS_URL,
                data=json.dumps({"url": "https://subscriber.example/hook"}),
                content_type=JSON,
            ),
            call=lambda: tool("create_endpoint")(
                context_for(member, tenant), url="https://subscriber.example/hook"
            ),
        )
        assert body["code"] == "forbidden"

    assert message == refusal_message(body), (
        "the machine door said something other than the REST body renders to"
    )
    # And the parts a client branches on are all there, in order.
    assert message.startswith(f"{body['code']}: {body['detail']}")
    assert "you can:" in message


def test_the_replay_refusal_is_byte_identical_too(
    api: Client,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    stranger_actor: Actor,
) -> None:
    """The write with the sharpest consequence gets its own E9 assertion."""
    theirs = _dead_letter(other_tenant, stranger_actor)
    body, message = _rest_and_mcp_refusal(
        api=api,
        owner=owner,
        tenant=tenant,
        request=lambda: api.post(f"{DEAD_LETTERS_URL}{theirs.pk}/replay/"),
        call=lambda: tool("replay_dead_letter")(context_for(owner, tenant), delivery_id=theirs.pk),
    )
    assert body["code"] == "not_found"
    assert message == refusal_message(body)


def test_a_nonexistent_id_and_another_tenants_id_refuse_identically_on_both_doors(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, stranger_actor: Actor
) -> None:
    """Not-there and not-yours are one answer — on the machine door as well."""
    theirs = services.register_endpoint(
        tenant=other_tenant, actor=stranger_actor, url="https://elsewhere.example/hook"
    )
    acting = context_for(owner, tenant)
    messages = []
    for endpoint_id in (theirs.pk, uuid4()):
        with pytest.raises(ToolError) as refused:
            tool("get_endpoint")(acting, endpoint_id=endpoint_id)
        messages.append(str(refused.value))
    assert messages[0] == messages[1]


# --- Tenancy, and the wall the machine door keeps -------------------------------


def test_the_tool_list_holds_only_this_tenants_endpoints(
    tenant: Tenant, other_tenant: Tenant, owner: User, owner_actor: Actor, stranger_actor: Actor
) -> None:
    mine = services.register_endpoint(
        tenant=tenant, actor=owner_actor, url="https://mine.example/hook"
    )
    services.register_endpoint(
        tenant=other_tenant, actor=stranger_actor, url="https://theirs.example/hook"
    )
    page = tool("list_endpoints")(context_for(owner, tenant))
    assert [item.id for item in page.items] == [mine.pk]
    assert len(page.items) == 1


def test_a_tokenless_tenant_is_refused_rather_than_guessed_at(nomad: User) -> None:
    """A user with no membership resolves no tenant, and a write is refused."""
    with pytest.raises(ToolError) as refused:
        tool("create_endpoint")(context_for(nomad, None), url="https://subscriber.example/hook")
    assert "no_tenant" in str(refused.value)
    assert not WebhookEndpoint.objects.exists()


def test_a_nomad_reads_an_empty_list_rather_than_everything(nomad: User) -> None:
    """Fails closed: no tenant means no rows, not all rows."""
    page = tool("list_endpoints")(context_for(nomad, None))
    assert page.items == []
    assert len(page.items) == 0


# --- Query pin (house rule 5, the machine door's own) --------------------------


def test_the_tool_list_query_budget(
    tenant: Tenant, owner: User, owner_actor: Actor, django_assert_num_queries: Any
) -> None:
    for index in range(12):
        services.register_endpoint(
            tenant=tenant, actor=owner_actor, url=f"https://sub-{index}.example/hook"
        )
    acting = context_for(owner, tenant)
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        tool("list_endpoints")(acting)


def test_the_delivery_tool_reads_the_event_name_without_an_n_plus_one(
    tenant: Tenant, owner: User, owner_actor: Actor, django_assert_num_queries: Any
) -> None:
    for _ in range(12):
        _dead_letter(tenant, owner_actor)
    acting = context_for(owner, tenant)
    with django_assert_num_queries(LIST_QUERY_BUDGET):
        page = tool("list_deliveries")(acting)
    assert len(page.items) == 12
    assert {item.event_name for item in page.items} == {WIDGET_CREATED}
    assert isinstance(Delivery.objects.first(), Delivery)
