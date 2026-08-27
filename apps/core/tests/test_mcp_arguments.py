"""What a tool does with an argument it does not have, and how it says so.

Two findings, one shape, measured by the field test at the machine door.

**(a) An unknown argument was SILENTLY DROPPED.** `create_endpoint` called with
`event_types` instead of `event_names` behaved exactly as a call without it: the
misspelled name vanished on the way in, the tool answered success, and what came
back was an endpoint subscribed to nothing. It is the same 201-for-nothing trap
strict request bodies closed at the HTTP door (`test_strict_bodies.py`, FT-1'
F6) — and the worst failure shape a platform whose callers are agents can have,
because the caller's only evidence is a success.

**(b) An argument failure spoke pydantic.** `1 validation error for
create_organization_toolArguments … Field required [type=missing, input_value=…]`
— no `code` to branch on, no `errors` map, no remedies, while every in-body
domain refusal at the same door was correctly enveloped by `tool_call`. One door
answering one class of failure in two grammars, and the second grammar only ever
fired on the call the caller had already got wrong.

Driven over the wire, through the real ASGI application, for the same reason
`test_mcp_wall.py` is: what is under test is the *published* schema and the
*transport's* dispatch, and only the wire sees either. The tools are core's own
(`apps/core/api/routes.py`), so nothing here depends on another app having a
door.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.mcp import InvalidArguments
from apps.core.models import Tenant
from apps.core.tests.test_mcp import MCP_HEADERS, _result, _rpc, running
from apps.core.tests.test_mcp_wall import _call_with, _narrow, _session, _text

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

#: The code every one of these refusals carries, named once rather than spelled.
ARGUMENT_REFUSAL_CODE = InvalidArguments.code

#: `list_organizations` takes `depth`. This is the misspelling — the shape that
#: used to be dropped on the way in, leaving a filtered list that was not
#: filtered and a caller with no way to know.
MISSPELLED_FILTER: dict[str, Any] = {"dept": 2}

#: `create_organization` takes `parent_id`, `name` and `slug`; this is the call
#: with two of the three missing, which is what a caller sends to be told what
#: the other two are called.
HALF_AN_ORGANIZATION: dict[str, Any] = {"parent_id": "0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21"}

#: How pydantic spells its own complaint. None of it belongs on the wire: it is
#: the vocabulary of the validator rather than of the caller, and a client that
#: had to parse it would be parsing a library's internals.
PYDANTIC_VOCABULARY = (
    "validation error",
    "toolArguments",
    "input_value",
    "type=missing",
    "extra_forbidden",
    "pydantic",
)


async def _wide(tenant: Tenant, owner: User, *, name: str) -> str:
    """A token with no ceiling — the population that must reach every tool."""
    _, plaintext = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name=name,
        actor=actor_for(user=owner, tenant=tenant),
    )
    return str(plaintext)


async def _list_tools(plaintext: str) -> list[dict[str, Any]]:
    """`tools/list` over the real ASGI application — the catalogue a client reads.

    Its own helper rather than one added to `test_mcp_wall.py`: that module is
    a separate module's, whose ordering proof must stay untouched here, and
    a change that edits the file it is being measured against has measured itself.
    """
    from config.asgi import build_application

    application = build_application()
    headers = {**MCP_HEADERS, "authorization": f"Bearer {plaintext}"}
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await _session(client, headers)
            response = await client.post(
                "/mcp", headers=headers, json=_rpc("tools/list", {}, request_id=2)
            )
    listed: list[dict[str, Any]] = _result(response)["tools"]
    return listed


# --- 1 · an unknown argument is refused, not dropped ---------------------------


async def test_an_unknown_argument_is_refused_rather_than_silently_dropped(
    tenant: Tenant, owner: User
) -> None:
    """Closed.

    `dept` is not an argument `list_organizations` has. Previously the
    call answered a page of organizations — the filter the caller asked for
    simply never happened, and the success said nothing about it.
    """
    plaintext = await _wide(tenant, owner, name="args-dropped")

    refused = await _call_with(plaintext, "list_organizations", MISSPELLED_FILTER)

    assert refused.get("isError") is True, refused
    message = _text(refused)
    assert ARGUMENT_REFUSAL_CODE in message, message
    assert "dept" in message, message


async def test_the_refusal_names_the_arguments_the_tool_really_has(
    tenant: Tenant, owner: User
) -> None:
    """Naming the unknown one is half the answer; the other half is the real set.

    An agent that misspelled `depth` needs `depth`, and the machine door has no
    OpenAPI document to send it away to read. So the refusal carries the tool's
    own argument names — which is what the HTTP door's `docs:openapi` remedy
    points at, said inline because this medium is one line of text.
    """
    plaintext = await _wide(tenant, owner, name="args-named")

    refused = await _call_with(plaintext, "list_organizations", MISSPELLED_FILTER)

    message = _text(refused)
    assert "depth" in message, message
    assert "ordering" in message, message


async def test_the_published_schema_says_unknown_arguments_are_refused(
    tenant: Tenant, owner: User
) -> None:
    """The listing tells the truth about the door, so a client never has to guess.

    Every tool's `inputSchema` carries `additionalProperties: false`. A schema
    that omitted it published "anything else is fine" for a door that now
    refuses — and a generated client would go on sending a field that is
    refused, believing the document.
    """
    plaintext = await _wide(tenant, owner, name="args-schema")

    listed = await _list_tools(plaintext)

    assert listed, "the listing came back empty"
    lax = [
        tool["name"]
        for tool in listed
        if (tool.get("inputSchema") or {}).get("additionalProperties") is not False
    ]
    assert not lax, f"these tools still publish an open argument schema: {lax}"


# --- 2 · an argument failure wears the refusal grammar -------------------------


async def test_an_argument_failure_speaks_the_refusal_grammar(tenant: Tenant, owner: User) -> None:
    """Finding (b), closed.

    The same three moves every other refusal at this door makes: a `code` a
    client branches on, a plain sentence, the fields that failed, and the
    remedies. Composed by `wire_refusal` and rendered by `refusal_message` —
    the same pair `tool_call` uses for an in-body refusal — so an agent parses
    one grammar at this door rather than two.
    """
    plaintext = await _wide(tenant, owner, name="args-grammar")

    refused = await _call_with(plaintext, "create_organization", HALF_AN_ORGANIZATION)

    assert refused.get("isError") is True, refused
    message = _text(refused)
    assert message.startswith(
        f"Error executing tool create_organization: {ARGUMENT_REFUSAL_CODE}:"
    ), message
    assert "name" in message, message
    assert "slug" in message, message
    assert "you can:" in message, message
    assert "field:errors" in message, message


async def test_the_refusal_does_not_speak_pydantic(tenant: Tenant, owner: User) -> None:
    """The library's own vocabulary stays inside the library.

    This is the half of finding (b) that a `code` alone would not fix: the
    message used to be a validator's rendering of its own error object, and a
    client that started parsing it would be pinned to pydantic's spelling.
    """
    plaintext = await _wide(tenant, owner, name="args-no-pydantic")

    refused = await _call_with(plaintext, "create_organization", HALF_AN_ORGANIZATION)

    message = _text(refused)
    for spelling in PYDANTIC_VOCABULARY:
        assert spelling not in message, (
            f"the validator's own vocabulary reached the wire: {message}"
        )


# --- 3 · the order the two walls answer in is unchanged ------------------------


async def test_the_ceiling_still_answers_before_the_arguments(tenant: Tenant, owner: User) -> None:
    """The existing ordering, re-measured against the added shape.

    `test_mcp_wall.py` proves it for a call with arguments *missing*. This is
    the new shape — a call with an argument that does not exist — and the answer
    must still be about the credential: a token that may not reach
    `create_organization` learns nothing whatever about its arguments, not even
    that one of the ones it sent is not among them.
    """
    plaintext = await _narrow(tenant, owner, scopes=["tenant-settings:read"], name="args-order")

    refused = await _call_with(plaintext, "create_organization", {"dept": 1})

    assert refused.get("isError") is True, refused
    message = _text(refused)
    assert "insufficient_scope" in message, message
    assert ARGUMENT_REFUSAL_CODE not in message, message
    assert "dept" not in message, f"the refusal read the arguments it was refusing: {message}"
    assert "slug" not in message, message


async def test_a_well_formed_call_inside_the_ceiling_is_unchanged(
    tenant: Tenant, owner: User
) -> None:
    """The population that must not notice this change: everybody who is right.

    A well-formed call with a null ceiling answers exactly as it did — the
    strictness is a wall in front of the arguments a tool does not have, not a
    new hurdle in front of the ones it does.
    """
    plaintext = await _wide(tenant, owner, name="args-happy")

    answered = await _call_with(plaintext, "list_organizations", {"depth": 0, "limit": 5})

    assert answered.get("isError") is not True, answered
    assert answered["structuredContent"]["items"], answered


async def test_a_narrow_token_inside_its_ceiling_is_told_about_its_arguments(
    tenant: Tenant, owner: User
) -> None:
    """In-ceiling and malformed: the helpful answer, for a credential entitled to it.

    The mirror of the ordering test above. The wall refuses what the ceiling
    does not reach; everything the ceiling *does* reach is answered about its
    arguments, in the grammar, with the names.
    """
    plaintext = await _narrow(tenant, owner, scopes=["org-structure:write"], name="args-in-ceiling")

    refused = await _call_with(plaintext, "create_organization", {"parent_id": "x", "nome": "n"})

    assert refused.get("isError") is True, refused
    message = _text(refused)
    assert "insufficient_scope" not in message, message
    assert ARGUMENT_REFUSAL_CODE in message, message
    assert "nome" in message, message
