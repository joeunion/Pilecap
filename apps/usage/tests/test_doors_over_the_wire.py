"""The two usage doors answering one question, compared on the wire (rule 46).

The basis is re-added from each door's body: a total its days do not sum to is uncheckable.
`transaction=True`: the transport runs a tool body on a worker thread with its own connection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from apps.accounts.services import create_user
from apps.core.authz import refusal_sentence
from apps.core.middleware import ORG_HEADER
from apps.core.models import Grant, Membership
from apps.core.services import add_membership
from apps.core.tests.wire import MCP_HEADERS, MCP_URL, PROTOCOL_VERSION, bearer, rpc, wire
from apps.usage.services import record_usage
from apps.usage.tests.conftest import METER, OTHER_METER, PASSWORD, World, metered, user_of

#: House rule 46. The door pair this module answers for `apps/usage`.
DOOR_PAIR = ("rest", "mcp")

#: The key the report is read under (ADR core-27), a literal: a rename must show here.
READ_KEY = "usage_entry.read"

REST_URL = "/api/v1/usage/"
METERS_URL = "/api/v1/meters/"
JSON = "application/json"

NOON = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
ON = NOON.date().isoformat()

# The wire shape at each level, written out: a pin taken from the thing it pins cannot fail.
REPORT_KEYS = frozenset({"period", "starts_on", "ends_on", "meters"})
MEASURED_KEYS = frozenset({"value", "basis"})
BASIS_KEYS = frozenset({"formula", "inputs"})
#: The list envelope (ADR core-18), written out for the same reason.
PAGE_KEYS = frozenset({"items", "has_more", "next_cursor", "count"})


@pytest.fixture
def seeded(recorded_workflow_starts: None, world: World, a_declared_meter: str) -> World:
    """Two days of consumption at A, so a basis has something to say.

    `recorded_workflow_starts` first: the commit is real, and `create_widget` would dial Temporal.
    """
    for index, (quantity, day) in enumerate(((Decimal("30"), 0), (Decimal("12.5"), 1))):
        record_usage(
            tenant=world.tenant,
            actor=world.admin_at_a,
            meter=METER,
            quantity=quantity,
            ref=metered(world),
            idempotency_key=f"parity-{index}",
            occurred_at=NOON + timedelta(days=day),
        )
    return world


@pytest.fixture
def token(seeded: World) -> str:
    """A token scoped exactly to this section, minted in a sync fixture."""
    return _scoped(seeded, ["usage:read"], "door-parity")


@pytest.fixture
def elsewhere_token(seeded: World) -> str:
    """A token minted for another section entirely, for the ceiling probe."""
    return _scoped(seeded, ["widgets:read"], "elsewhere")


def _scoped(world: World, scopes: list[str], name: str) -> str:
    from apps.accounts.services import issue_token
    from apps.core.actor import actor_for

    user = user_of(world.owner)
    _, plaintext = issue_token(
        user=user,
        tenant=world.tenant,
        name=name,
        scopes=scopes,
        actor=actor_for(user=user, tenant=world.tenant, org=world.root),
    )
    return plaintext


async def _both(
    credential: dict[str, str], rest_url: str, tool: str, arguments: dict[str, Any]
) -> tuple[httpx.Response, httpx.Response]:
    """One question to the REST route and its MCP twin: both raw responses."""
    async with wire() as client:
        over_http = await client.get(rest_url, headers={**credential, "accept": JSON})
        await client.post(
            MCP_URL,
            headers={**MCP_HEADERS, **credential},
            json=rpc(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "usage-door-parity", "version": "1"},
                },
            ),
        )
        called = await client.post(
            MCP_URL,
            headers={**MCP_HEADERS, **credential},
            json=rpc("tools/call", {"name": tool, "arguments": arguments}, 2),
        )
    return over_http, called


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_report_on_the_wire(token: str) -> None:
    """One window, two doors: the published shape, one body, and a basis that re-adds."""
    over_http, called = await _both(
        {"authorization": f"Bearer {token}"},
        f"{REST_URL}?period=month&on={ON}",
        "get_usage",
        {"period": "month", "on": ON},
    )
    assert over_http.status_code == 200, over_http.text
    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(rest_body) == REPORT_KEYS
    measured = rest_body["meters"][METER]
    assert set(measured) == MEASURED_KEYS
    assert set(measured["basis"]) == BASIS_KEYS
    assert set(over_mcp) == set(rest_body)
    assert over_mcp == rest_body

    assert measured["basis"]["formula"] == "sum(day_totals)"
    recomputed = sum(Decimal(str(value)) for value in measured["basis"]["inputs"].values())
    assert recomputed == Decimal(measured["value"])
    assert recomputed == Decimal("42.5")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_the_same_narrow_token(elsewhere_token: str) -> None:
    """A token minted for another section is refused at both doors, each naming `usage:read`."""
    over_http, called = await _both(
        {"authorization": f"Bearer {elsewhere_token}"}, REST_URL, "get_usage", {}
    )
    assert over_http.status_code == 403, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "insufficient_scope"
    assert "usage:read" in rest_body["detail"]
    said = called.text
    assert "insufficient_scope" in said, said
    assert "usage:read" in said, said


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_publish_the_same_vocabulary(token: str) -> None:
    """One catalogue, one envelope, one derivation, at both doors."""
    over_http, called = await _both(
        {"authorization": f"Bearer {token}"}, METERS_URL, "list_meters", {}
    )
    assert over_http.status_code == 200, over_http.text
    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(rest_body) == PAGE_KEYS
    assert over_mcp == rest_body
    assert [item["name"] for item in rest_body["items"]] == [METER, OTHER_METER]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_the_same_unresolved_hat(token: str) -> None:
    """A sent `X-Org` that does not resolve is refused at both doors, byte-identical (ADR core-21).

    Core's addressing law refuses it before any route or tool runs, so no report is ever drawn.
    """
    over_http, called = await _both(
        {"authorization": f"Bearer {token}", ORG_HEADER: "nosuchorg"},
        f"{REST_URL}?period=month&on={ON}",
        "get_usage",
        {"period": "month", "on": ON},
    )
    assert over_http.status_code == 403, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "addressing_header_not_honoured"
    assert ORG_HEADER in rest_body["detail"], rest_body
    assert called.status_code == 403, called.text
    assert called.json() == rest_body, (called.text, over_http.text)
    assert "meters" not in called.text, "a refused hat must never come back as a report"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_a_caller_with_no_account(nomad: Any) -> None:
    """A credential of no account is `no_acting_scope` at both doors — never a bill of zero."""
    from asgiref.sync import sync_to_async

    plaintext = await sync_to_async(bearer)(user=nomad, tenant=None, name="usage-no-account")
    over_http, called = await _both(
        {"authorization": f"Bearer {plaintext}"},
        f"{REST_URL}?period=month&on={ON}",
        "get_usage",
        {"period": "month", "on": ON},
    )
    assert over_http.status_code == 403, over_http.text
    assert over_http.json()["code"] == "no_acting_scope"
    answered = called.json()
    assert answered["result"]["isError"] is True, answered
    assert "no_acting_scope" in str(answered["result"]["content"])


@pytest.fixture
def withheld_token(seeded: World) -> str:
    """A member whose tenant took `usage_entry.read` away, with a full `usage:read` ceiling."""
    from apps.accounts.services import issue_token
    from apps.core.actor import actor_for

    person = create_user(email="withheld-on-the-wire@acme.com", password=PASSWORD)
    membership = add_membership(
        user=person,
        tenant=seeded.tenant,
        organization=seeded.root,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=seeded.owner,
    )
    Grant.objects.create(
        tenant=seeded.tenant,
        membership=membership,
        permission=READ_KEY,
        effect=Grant.Effect.WITHHOLD,
    )
    _, plaintext = issue_token(
        user=person,
        tenant=seeded.tenant,
        name="withheld",
        scopes=["usage:read"],
        actor=actor_for(user=person, tenant=seeded.tenant),
    )
    return plaintext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_the_same_withheld_read_with_the_same_words(
    withheld_token: str,
) -> None:
    """One withhold, two doors, the key's own sentence — and no report at all (ADR core-27)."""
    sentence = refusal_sentence(READ_KEY)
    over_http, called = await _both(
        {"authorization": f"Bearer {withheld_token}"},
        f"{REST_URL}?period=month&on={ON}",
        "get_usage",
        {"period": "month", "on": ON},
    )
    assert over_http.status_code == 403, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "forbidden"
    assert rest_body["detail"] == sentence
    said = called.text
    assert "forbidden" in said, said
    assert sentence in said, said
    assert "sum(day_totals)" not in said, "a withheld read must not come back as a report"
