"""The usage read is a permission over the kind it hands back (PR4.h, ADR core-27).

**What moved, in one line.** The report used to be gated by `usage.read_report`
— a key with no kind, answered by a predicate that asked "do you hold any
membership here at all". Nothing a tenant could write moved it: a `withhold` on
the row's own kind (`usage_entry.read`) was a row the check never read, so an
administrator narrowing one person's sight of the bill got a `200` and no
error. That is the red this module was written against, and it is pasted in the
rung report.

Now the read asks `usage_entry.read` — the derived key of `UsageEntry`, which is
what the report is a total OVER — so every layer a tenant owns composes with it:
a role's collection, a `RolePermission` exclude, a `Grant` withhold.

**The aggregate valve is the honest half.** `get_usage` returns
`dict[str, MeasuredOut]` and not rows, so rule 54 (e) cannot see it; the
`# read-kind: usage_entry` line on the selector is the sentence that says which
kind answers for the total, and this module is what makes it true rather than
decorative.

`visible_to` still decides WHICH rows (rule 24, BVB-4) and is untouched: the
branch-anti-oracle cases live in `test_selectors.py` and none of them moved.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

import pytest
from django.test import Client
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.accounts.services import create_user, issue_token
from apps.core.actor import actor_for
from apps.core.authz import refusal_sentence
from apps.core.exceptions import Forbidden
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.middleware import ORG_HEADER
from apps.core.models import Grant, Membership, Organization, Tenant
from apps.core.services import add_membership
from apps.usage.api import _window
from apps.usage.mcp import register
from apps.usage.selectors import get_usage
from apps.usage.tests.conftest import PASSWORD, World
from apps.usage.types import PeriodKind

pytestmark = pytest.mark.django_db

URL = "/api/v1/usage/"

#: The key the report is authorized under — the derived key of the row it totals.
#: Spelled here as a literal on purpose: a test that imported the constant the
#: selector uses would pass on the day the selector asked for the wrong thing.
READ_KEY = "usage_entry.read"


@dataclass(frozen=True)
class Reader:
    """One plain member at the root, and the membership a withhold hangs on."""

    user: User
    membership: Membership
    tenant: Tenant
    org: Organization


@pytest.fixture
def reader(world: World) -> Reader:
    person = create_user(email="bill-reader@acme.com", password=PASSWORD)
    membership = add_membership(
        user=person,
        tenant=world.tenant,
        organization=world.root,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=world.root_actor,
    )
    return Reader(user=person, membership=membership, tenant=world.tenant, org=world.root)


def withhold(membership: Membership, permission: str) -> Grant:
    """A `withhold` row: the narrowing a tenant's administrator writes."""
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


def _month(world: World) -> Any:
    return _window(period=PeriodKind.MONTH, on=None)


@dataclass
class _FakeRequest:
    scope: dict[str, Any]


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def context_for(user: User, tenant: Tenant, org: Organization) -> Context[Any]:
    """The context a tool sees, with the principal the middleware would have left."""
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=org)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def tool(name: str) -> Callable[..., Any]:
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    found: Callable[..., Any] = cast(Any, server._tool_manager._tools[name]).fn  # noqa: SLF001
    return found


# --- PR4.h.1 · the selector asks, for the kind it totals -----------------------


def test_a_withheld_usage_read_is_refused_at_the_selector(world: World, reader: Reader) -> None:
    """A `withhold` on `usage_entry.read` reaches the report. **The red.**

    On the baseline tree this call returned an empty report: the selector asked
    `usage.read_report`, a kindless key whose predicate read the membership and
    nothing else, so the grant row was never consulted. The assertion below is
    the whole of what changed.

    Then the withhold is lifted and the same call answers — without that half
    this would pass with the selector refusing everybody.
    """
    withhold(reader.membership, READ_KEY)

    with pytest.raises(Forbidden) as refused:
        get_usage(
            tenant=world.tenant,
            actor=actor_for(user=reader.user, tenant=world.tenant, org=world.root),
            period=_month(world),
        )
    assert str(refused.value.args[0]) == refusal_sentence(READ_KEY)

    Grant.objects.filter(membership=reader.membership, permission=READ_KEY).delete()
    assert (
        get_usage(
            tenant=world.tenant,
            actor=actor_for(user=reader.user, tenant=world.tenant, org=world.root),
            period=_month(world),
        )
        == {}
    ), "an empty ledger is the answer; being refused is not"


def test_the_plain_member_still_reads_everything(api: Client, world: World, reader: Reader) -> None:
    """**A product that customised nothing observes no change** (principle 13).

    `member` is declared `("*.read",)`, so the derived `usage_entry.read` is a
    key it holds — the door answers exactly what it answered before the key
    moved. The 403 case above is what a tenant WRITES; this is what a tenant
    that wrote nothing still gets.
    """
    api.force_login(reader.user)

    answered = api.get(URL, headers={ORG_HEADER: world.root.slug})

    assert answered.status_code == 200, answered.content
    assert set(json.loads(answered.content)) == {"period", "starts_on", "ends_on", "meters"}


# --- PR4.h.2 · both doors, the same words --------------------------------------


def test_a_withheld_usage_read_is_forbidden_on_both_doors(
    api: Client, world: World, reader: Reader
) -> None:
    """One refusal, composed once, rendered by two doors (E9, rule 46).

    The REST body and the MCP message are compared against the SAME sentence
    rather than against each other, so a door that grew a friendlier wording of
    its own fails here rather than passing by symmetry.

    Driven with a session at the HTTP door and a bearer at the machine door,
    because the credential kinds are population members: a token whose ceiling
    carries `usage:read` is refused by the READ key and not by the ceiling, and
    telling those two apart is the point.
    """
    withhold(reader.membership, READ_KEY)
    sentence = refusal_sentence(READ_KEY)

    _, plaintext = issue_token(
        user=reader.user,
        tenant=world.tenant,
        name="withheld-read",
        scopes=["usage:read"],
        actor=actor_for(user=reader.user, tenant=world.tenant),
    )
    over_http = api.get(URL, headers={"authorization": f"Bearer {plaintext}"})

    assert over_http.status_code == 403, over_http.content
    body = json.loads(over_http.content)
    assert body["code"] == "forbidden"
    assert body["detail"] == sentence

    with pytest.raises(ToolError) as refused:
        tool("get_usage")(ctx=context_for(reader.user, world.tenant, world.root))

    said = str(refused.value)
    assert "forbidden" in said, said
    assert sentence in said, said
