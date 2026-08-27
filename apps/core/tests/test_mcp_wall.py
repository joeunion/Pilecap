"""Where the ceiling stands relative to argument validation.

`test_mcp_scopes.py` proves the ceiling refuses a **well-formed** call. This
file is about the other shape, and about the wall being in the right place.

The machine door's transport parses and validates a tool's arguments before it
runs the tool body — and the ceiling used to be checked inside `tool_call`,
which is *in* the body. So a token with no scope on a family could send a
deliberately malformed call to one of that family's tools and be answered
about the arguments: the tool's required parameter names, read straight off a
capability the credential was never allowed to reach. The HTTP door has never
had this, because the ceiling wrapper there answers before a body is parsed;
rule 17's spirit is that the two doors agree.

Driven over the wire, the same way `test_mcp_scopes.py` is, because the thing
under test is the order two pieces of machinery run in and only the wire can
see it.

The families are core's own (`apps/core/api/routes.py::TAGS`): a token
scoped to `tenant-settings` holds nothing whatever on `org-structure`, so
`create_organization` is out of its ceiling by the whole family — the shape the
defect describes — and neither half of the test depends on another app having
a door.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.mcp import TOOL_ERROR_SENTENCE
from apps.core.models import Tenant
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, _result, _rpc, running

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

#: `create_organization` takes `parent_id`, `name` and `slug`. This is the call
#: with two of the three missing — the malformed shape a caller sends precisely
#: to be told what the third one is called.
HALF_AN_ORGANIZATION: dict[str, Any] = {"parent_id": "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21"}

#: The whole call, for the well-formed leg. It names nothing real: the call is
#: refused before anything resolves it.
WHOLE_ORGANIZATION: dict[str, Any] = {
    "parent_id": "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21",
    "name": "Nope",
    "slug": "nope",
}

#: The parameter name a leak would spell, chosen because it appears nowhere in
#: the refusal's own grammar. `name` would be the obvious second sentinel and is
#: deliberately not one: the word occurs in the refusal's remedies ("the scope
#: named here"), so an assertion on it would fire on prose rather than on a
#: leak. The invariance test below is what covers the rest of the schema.
SCHEMA_SENTINEL = "slug"

#: How pydantic spells an argument complaint. Its presence in a refusal aimed at
#: a credential means validation ran first, which is the whole defect.
VALIDATION_VOCABULARY = ("validation error", "Field required", "input_value", "pydantic")


async def _session(client: httpx.AsyncClient, headers: dict[str, str]) -> None:
    """Complete the MCP handshake so later calls are accepted."""
    await client.post(
        "/mcp",
        headers=headers,
        json=_rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        ),
    )
    await client.post(
        "/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )


async def _call_with(
    plaintext: str, name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    """One `tools/call` over the real ASGI application, as an agent makes it."""
    from config.asgi import build_application

    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {plaintext}"}
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _session(client, headers)
            response = await client.post(
                "/mcp",
                headers=headers,
                json=_rpc("tools/call", {"name": name, "arguments": arguments or {}}, request_id=2),
            )
    result: dict[str, Any] = _result(response)
    return result


def _text(result: dict[str, Any]) -> str:
    return " ".join(
        str(block.get("text", "")) for block in result.get("content", []) if isinstance(block, dict)
    )


async def _narrow(tenant: Tenant, owner: User, *, scopes: list[str], name: str) -> str:
    _, plaintext = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name=name,
        scopes=scopes,
        actor=actor_for(user=owner, tenant=tenant),
    )
    return str(plaintext)


# --- 1 · the wall answers first ------------------------------------------------


async def test_a_malformed_call_outside_the_ceiling_is_answered_about_the_credential(
    tenant: Tenant, owner: User
) -> None:
    """The defect, closed.

    A token holding nothing on `org-structure` sends a `create_organization`
    call with arguments missing. What comes back is about the token — the code
    a client branches on and the scope it would have to be minted with — and
    **not one argument name**, because the argument names are the schema of a
    capability this credential was never allowed to reach.
    """
    plaintext = await _narrow(tenant, owner, scopes=["tenant-settings:read"], name="wall-malformed")

    refused = await _call_with(plaintext, "create_organization", HALF_AN_ORGANIZATION)

    assert refused.get("isError") is True, refused
    message = _text(refused)
    assert "insufficient_scope" in message, message
    assert "org-structure:write" in message, message
    assert SCHEMA_SENTINEL not in message, f"the refusal leaked a parameter: {message}"
    for spelling in VALIDATION_VOCABULARY:
        assert spelling not in message, f"validation ran before the wall: {message}"


async def test_the_refusal_says_the_same_thing_whatever_the_arguments_were(
    tenant: Tenant, owner: User
) -> None:
    """The property the sentinel above is only a sample of.

    Nothing whatever about the arguments can be read out of a refusal that is
    the same string for a call with all of them, a call with two missing and a
    call with none — which is the exact sense in which the schema no longer
    crosses the wall. It is also the byte-compare that keeps the well-formed
    refusal what it always was: the shape an agent already knows is the shape
    the new one wears, rather than a second dialect of it.
    """
    plaintext = await _narrow(tenant, owner, scopes=["tenant-settings:read"], name="wall-parity")

    whole = await _call_with(plaintext, "create_organization", WHOLE_ORGANIZATION)
    half = await _call_with(plaintext, "create_organization", HALF_AN_ORGANIZATION)
    empty = await _call_with(plaintext, "create_organization", {})

    assert whole.get("isError") is True, whole
    assert _text(whole) == _text(half) == _text(empty)
    assert "insufficient_scope" in _text(whole)


async def test_the_transport_still_dresses_a_refusal_the_way_this_module_says(
    tenant: Tenant, owner: User
) -> None:
    """The tripwire on `TOOL_ERROR_SENTENCE`, measured rather than assumed.

    Refusing in front of the tool body means putting on by hand the coat the
    transport puts on anything a body raises. That coat is somebody else's
    prose, so this measures it: an in-body refusal (a `not_found` from a tool
    the token may reach) and the ceiling refusal must wear the same one. The day
    the transport rewords it, this goes red and names the constant to fix,
    instead of the two refusal shapes quietly drifting apart.
    """
    reader = await _narrow(tenant, owner, scopes=["org-structure:read"], name="wall-coat-read")
    narrow = await _narrow(tenant, owner, scopes=["tenant-settings:read"], name="wall-coat-narrow")

    in_body = await _call_with(
        reader, "get_organization", {"organization_id": "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21"}
    )
    at_the_wall = await _call_with(narrow, "create_organization", WHOLE_ORGANIZATION)

    assert in_body.get("isError") is True, in_body
    assert "not_found" in _text(in_body), _text(in_body)
    assert _text(in_body).startswith(
        TOOL_ERROR_SENTENCE.format(name="get_organization", message="")
    ), _text(in_body)
    assert _text(at_the_wall).startswith(
        TOOL_ERROR_SENTENCE.format(name="create_organization", message="")
    ), _text(at_the_wall)


# --- 2 · the wall did not make validation worse for legitimate callers ---------


async def test_a_malformed_call_inside_the_ceiling_still_gets_told_what_is_missing(
    tenant: Tenant, owner: User
) -> None:
    """The leak is fixed at the wall, not by taking the help away.

    A token that *does* carry `org-structure:write` is a caller entitled to the
    schema, and the whole value of an argument error is that it names the
    argument. This is the test that fails if the fix were "say less to
    everybody".
    """
    plaintext = await _narrow(tenant, owner, scopes=["org-structure:write"], name="wall-inside")

    refused = await _call_with(plaintext, "create_organization", HALF_AN_ORGANIZATION)

    assert refused.get("isError") is True, refused
    message = _text(refused)
    assert "insufficient_scope" not in message, message
    assert SCHEMA_SENTINEL in message, f"the caller was not told what is missing: {message}"
    assert "name" in message, message


async def test_a_token_with_no_ceiling_is_told_what_is_missing_too(
    tenant: Tenant, owner: User
) -> None:
    """`*` — or a token minted before ceilings existed — reaches everything.

    The null-ceiling population is the one that must not notice the wall at
    all, on either shape: the malformed call gets the argument error and the
    well-formed one is not refused by the wall.
    """
    _, plaintext = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="wall-wide",
        actor=actor_for(user=owner, tenant=tenant),
    )

    refused = await _call_with(str(plaintext), "create_organization", HALF_AN_ORGANIZATION)

    assert refused.get("isError") is True, refused
    message = _text(refused)
    assert "insufficient_scope" not in message, message
    assert SCHEMA_SENTINEL in message, message

    answered = await _call_with(str(plaintext), "list_organizations")
    assert answered.get("isError") is not True, answered
