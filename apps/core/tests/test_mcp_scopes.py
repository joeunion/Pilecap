"""The machine door's half of the token ceiling (ADR ident-7).

Driven the way `test_mcp.py` drives it — the real ASGI application, a real
`ApiToken`, JSON-RPC over Streamable HTTP — because the thing under test is what
an agent meets, and an agent meets the wire.

Four properties: an out-of-ceiling tool refuses and says which scope it wanted;
the refusal is the one the HTTP door sends, field for field; the catalogue does
not shrink when the ceiling does, and every entry in it says what it costs; and
no tool in the product is left underivable, which is what makes "the ceiling
covers everything" a measurement rather than a hope.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.api.scopes import UnderivableScope, families_of_app
from apps.core.asyncdb import run_db
from apps.core.mcp import (
    NO_CEILING_ATTR,
    TOOL_SCOPE_SENTENCE,
    described_with_scope,
    reaches_no_capability,
    reset_scope_derivation,
    scope_for_tool,
    service_verbs,
    tool_scopes,
)
from apps.core.models import Tenant
from apps.core.tests.test_mcp import MCP_HEADERS, _result, _rpc, running
from apps.core.tests.wire import call as _call
from apps.core.tests.wire import session as _session

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

#: Arguments that satisfy `create_organization`'s signature. They name nothing
#: real: the call is refused before anything resolves them, and a test that had
#: to build a live parent in order to prove a refusal would be proving two
#: things at once.
NEW_ORGANIZATION = {
    "parent_id": "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21",
    "name": "Nope",
    "slug": "nope",
}


async def _listed(client: httpx.AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = await client.post("/mcp", headers=headers, json=_rpc("tools/list", {}, request_id=3))
    tools: list[dict[str, Any]] = _result(response)["tools"]
    return tools


def _text(result: dict[str, Any]) -> str:
    return " ".join(
        str(block.get("text", "")) for block in result.get("content", []) if isinstance(block, dict)
    )


# --- 1 · the ceiling in the one seam, and it is the HTTP door's own refusal -----


async def test_a_narrow_token_is_refused_by_name_and_told_what_to_ask_for(
    tenant: Tenant, owner: User
) -> None:
    """The whole of criterion 1, from an agent's seat.

    The token may read the org tree and nothing else; the tool that lists it
    answers, and the tool that creates one refuses with the scope it wanted said
    out loud — because an agent that is told only "no" has nothing to relay to
    the person who could fix it.
    """
    from config.asgi import build_application

    _, plaintext = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="narrow-mcp",
        scopes=["org-structure:read"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {plaintext}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _session(client, headers)

            allowed = await _call(client, headers, "list_organizations")
            assert allowed.get("isError") is not True, allowed

            refused = await _call(client, headers, "create_organization", NEW_ORGANIZATION)

    assert refused.get("isError") is True, refused
    message = _text(refused)
    assert "insufficient_scope" in message
    assert "org-structure:write" in message
    assert "org-structure:read" in message


async def test_the_two_doors_refuse_the_same_credential_with_the_same_words(
    tenant: Tenant, owner: User
) -> None:
    """One composer, two doors (rule 17, E9).

    The HTTP door sends a JSON body and the machine door sends a line of text,
    and the line is that body rendered — so every field a client could branch on
    over HTTP is present, verbatim, in what the agent is handed. Asserting the
    fields rather than the whole string is deliberate: the two doors are allowed
    to differ in punctuation and not in content.
    """
    from config.asgi import build_application

    _, plaintext = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="both-doors",
        scopes=["org-structure:read"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    def over_http() -> dict[str, Any]:
        api = Client()
        response = api.post(
            "/api/v1/organizations/",
            data=json.dumps({"name": "Nope"}),
            content_type="application/json",
            headers={"authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 403, response.content
        body: dict[str, Any] = json.loads(response.content)
        return body

    rest = await run_db(over_http)

    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {plaintext}"}
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _session(client, headers)
            refused = await _call(client, headers, "create_organization", NEW_ORGANIZATION)

    message = _text(refused)
    assert rest["code"] == "insufficient_scope"
    assert rest["code"] in message
    assert rest["detail"] in message
    assert rest["remedies"], "a refusal with no way out is a dead end"
    for remedy in rest["remedies"]:
        assert remedy["label"] in message
        assert remedy["destination"] in message


async def test_a_token_with_no_ceiling_calls_the_machine_door_as_it_always_did(
    tenant: Tenant, owner: User
) -> None:
    from config.asgi import build_application

    _, plaintext = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="wide-mcp",
        actor=actor_for(user=owner, tenant=tenant),
    )
    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {plaintext}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _session(client, headers)
            answered = await _call(client, headers, "list_organizations")

    assert answered.get("isError") is not True, answered


# --- 2 · refuse, never hide ----------------------------------------------------


async def test_a_narrow_token_still_sees_every_tool_and_what_each_one_costs(
    tenant: Tenant, owner: User
) -> None:
    """The catalogue is the agent's map, and a map with roads missing is worse
    than a road that says "toll".

    Two halves, and the second is the one that makes the first useful: the list
    does not shrink with the ceiling, and every entry says which scope reaches
    it — so an agent holding a narrow token can tell its human exactly what to
    mint instead of reporting that a capability does not exist.
    """
    from config.asgi import build_application

    _, narrow = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="narrow-list",
        scopes=["org-structure:read"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    _, wide = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="wide-list",
        actor=actor_for(user=owner, tenant=tenant),
    )
    application = build_application()

    async def names_and_descriptions(plaintext: str) -> dict[str, str]:
        headers = {**MCP_HEADERS, "authorization": f"Bearer {plaintext}"}
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _session(client, headers)
            return {
                str(tool["name"]): str(tool.get("description") or "")
                for tool in await _listed(client, headers)
            }

    async with running(application):
        narrowed = await names_and_descriptions(narrow)
        whole = await names_and_descriptions(wide)

    assert narrowed.keys() == whole.keys()
    assert len(narrowed) > 1, "the listing is empty, so this test cannot fail"

    from config.mcp import server

    census = tool_scopes(server)
    assert census.keys() == narrowed.keys()
    for name, scope in census.items():
        if scope is None:
            continue
        assert TOOL_SCOPE_SENTENCE.format(scope=scope) in narrowed[name], name

    # The out-of-ceiling one is there, and it says what it would take.
    assert "create_organization" in narrowed
    assert "org-structure:write" in narrowed["create_organization"]


def test_a_tool_that_needs_no_scope_gets_no_scope_line() -> None:
    """A line that said "this needs nothing" on every such tool would be noise."""
    assert described_with_scope("The prose.", None) == "The prose."
    assert "widgets:read" in described_with_scope("The prose.", "widgets:read")


# --- 3 · the tool derivation census --------------------------------------------


def test_every_registered_tool_derives_its_scope() -> None:
    """Total over the real registry — the tools this deployment actually mounts.

    `tool_scopes()` raises on the first tool nothing can classify, so a green
    assertion here is the census passing rather than the census being skipped.
    """
    from config.mcp import server

    census = tool_scopes(server)
    assert len(census) > 1, "no tools are registered, so this test cannot fail"
    for name, scope in census.items():
        assert scope is None or ":" in scope, f"{name} derived {scope!r}"


def test_the_tools_that_need_no_scope_each_say_why() -> None:
    """The declaration is a sentence a reviewer can disagree with, or it is a hole."""
    from config.mcp import server

    for tool in server._tool_manager.list_tools():
        reason = getattr(tool.fn, NO_CEILING_ATTR, "")
        if scope_for_tool(tool) is None:
            assert reason and len(reason.split()) > 3, tool.name


def test_a_blank_reason_is_refused_where_it_is_written() -> None:
    with pytest.raises(ValueError, match="has to say why"):
        reaches_no_capability("   ")


def _planted(name: str, *, module: str = "apps.example.mcp") -> Any:
    """A tool that is nobody's twin, in an app that owns exactly one section."""

    def body() -> None:  # pragma: no cover - never called
        return None

    body.__module__ = module
    return SimpleNamespace(
        name=name,
        fn=body,
        description=f"Prose no route in this product has ever written: {name}.",
    )


def test_the_census_refuses_a_twinless_tool_whose_verb_is_out_of_lexicon() -> None:
    """The plant criterion 3 names.

    A tool with no REST twin has only its own name to be classified by, and the
    two grammars this product speaks are reading (`get`, `list`) and the verbs
    its services use. A name outside both is not a tool with a permissive
    default — it is a tool nothing can place, and placing it by guess is how a
    capability ends up outside every ceiling in the product.
    """
    reset_scope_derivation()
    with pytest.raises(UnderivableScope) as refused:
        scope_for_tool(_planted("frobnicate_widgets"))
    assert "frobnicate" in str(refused.value)


def test_a_twinless_tool_named_after_what_it_does_derives() -> None:
    """The negative the plant would be worthless without."""
    reset_scope_derivation()
    assert scope_for_tool(_planted("get_doohickey")) == "widgets:read"
    assert scope_for_tool(_planted("list_doohickeys")) == "widgets:read"
    # `approve` is a verb this product's own services use, so it writes.
    assert "approve" in service_verbs()
    assert scope_for_tool(_planted("approve_doohickey")) == "widgets:write"


def test_a_twinless_tool_in_an_app_that_owns_several_sections_derives_nothing() -> None:
    """Honest rather than convenient: nothing here knows which of them it is.

    The count in the refusal is read off the live declaration rather than typed,
    because the number is exactly the thing a scope split changes — `core` owned
    two sections when this was written and owns four since the three-way split,
    and a hard-coded 2 would have made a correct refusal look like a regression.
    """
    reset_scope_derivation()
    owned = families_of_app("core")
    assert len(owned) > 1, "core owns one section — this test would pass vacuously"
    with pytest.raises(UnderivableScope, match=f"{len(owned)} sections"):
        scope_for_tool(_planted("get_doohickey", module="apps.core.mcp"))


def test_the_write_grammar_is_the_products_own_services() -> None:
    """A census of the tree, never a list beside it.

    Read off the `@service`-decorated functions themselves, so it agrees with
    house rule 16's declared lexicon by construction instead of by somebody
    keeping two lists in step.
    """
    verbs = service_verbs()
    assert {"create", "update", "delete", "invite", "issue", "revoke"} <= verbs
    assert "frobnicate" not in verbs
