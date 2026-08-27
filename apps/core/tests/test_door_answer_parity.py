"""One row, two doors, the datetimes BYTE-EQUAL.

**The gap this closes, in its own words.** `test_door_schema_parity.py` compares
what the two doors PUBLISH — every twin tool's `outputSchema` against the
OpenAPI components, structurally — and it says out loud that it compares
documents and not answers. That blind spot is exactly where the mismatch lived for five
sightings: two doors publishing one schema and putting two different strings for
one instant on the wire, `…:56.123Z` on REST and `…:56.123456Z` on MCP. No
document comparison can see that, because both documents say `date-time`.

So this drives one representative pair to an ANSWER and compares the values —
over the real transports, not by calling the tool function and dumping it. That
distinction is the whole point: a test that renders the model itself is testing
its own `model_dump`, and it is why the five `_to_the_millisecond` helpers could
exist for months without anybody noticing that the doors disagreed. What is
asserted here is what a client receives.

**One pair, deliberately.** Rule 17 already proves every capability exists at
both doors and `test_door_schema_parity` already proves their published shapes
agree; per-app wire modules (`test_doors_over_the_wire.py`, rule 46) already
drive their own rows. What was missing was a single place that owns the
ENCODER's promise, and an encoder is not per-app — it is one seam in
`config/api.py` that `config/mcp.py` consumes. A representative pair is the
honest scope for a claim about a shared seam; the per-app modules are what make
it a claim about every row.

DOES NOT COVER — declared: this drives one route/tool pair. A door that
diverged on some other app's row would be caught by that app's own wire module
under rule 46, not here, and a row with no datetime at all proves nothing about
the encoder. The floor below refuses to let that become vacuous.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.models import Organization, Tenant
from apps.core.services import create_organization, root_organization
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running

DOOR_PAIR = ("rest", "mcp")

MCP_URL = "/mcp"
JSON = "application/json"

#: The representative pair: one organization, read through both doors. Chosen
#: because `core` owns both halves — the route and its twin tool are in this
#: app, so the pair cannot be broken by another app's rung — and because an
#: `Organization` carries two datetimes and nothing that needs seeding.
ROUTE = "/api/v1/organizations/{}/"
TOOL = "get_organization"

#: A datetime the door renders to MILLISECONDS keeps at most three fractional
#: digits. Asserted rather than assumed, so "the two doors agree" cannot be
#: satisfied by both of them being wrong in the same new way.
MAX_FRACTIONAL_DIGITS = 3


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def _datetimes(body: dict[str, Any]) -> dict[str, str]:
    """Every value in this row that is a rendered instant, by key.

    Derived from the values rather than from a list of field names — a
    `TIMESTAMPS` tuple per app is exactly the workaround this fix retired, and
    reintroducing one here to check that the workaround is gone would be funny
    in the wrong way.
    """
    return {
        key: value
        for key, value in body.items()
        if isinstance(value, str) and _looks_like_an_instant(value)
    }


def _looks_like_an_instant(value: str) -> bool:
    return (
        len(value) >= 20
        and value[4] == "-"
        and value[7] == "-"
        and value[10] in {"T", " "}
        and value[13] == ":"
    )


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="answer-parity", actor=actor_for(user=owner, tenant=tenant)
    )
    return plaintext


@pytest.fixture
def node(tenant: Tenant, owner: User) -> Organization:
    """One branch under the tenant's root — a row with two rendered instants.

    Made through the service rather than the manager, so `created_at` and
    `updated_at` are whatever the product actually writes; a hand-built row
    could carry a rounder number than production ever does and quietly make the
    fractional-digit assertion below easier to pass.
    """
    root = root_organization(tenant=tenant)
    return create_organization(
        tenant=tenant,
        parent=root,
        name="Branch A",
        slug="branch-a",
        actor=actor_for(user=owner, tenant=tenant, org=root),
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_put_the_same_instant_on_the_wire(
    bearer: str, tenant: Tenant, node: Organization
) -> None:
    """The mismatch's closure, asserted where it was invisible: at the answer.

    Byte-equal, not "the same moment to within a millisecond". The weaker
    assertion is what the per-app modules had to make while the doors disagreed
    — `_instant(rest) == _to_milliseconds(_instant(mcp))` — and it passes on a
    tree where a client still cannot compare two strings for equality.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                ROUTE.format(node.pk), headers={**bearer_header, "accept": JSON}
            )
            assert over_http.status_code == 200, over_http.text

            headers = {**MCP_HEADERS, **bearer_header}
            initialize = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "answer-parity", "version": "1"},
                    },
                    1,
                ),
            )
            assert initialize.status_code == 200, initialize.text

            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": TOOL, "arguments": {"organization_id": str(node.pk)}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    rest_times = _datetimes(rest_body)
    mcp_times = _datetimes(over_mcp)

    assert rest_times, (
        "the representative row carries no rendered instant, so this test proves "
        "nothing about the encoder. Point it at a pair that has one."
    )
    assert set(rest_times) == set(mcp_times), (
        f"the two doors disagree about WHICH values are instants: only on REST "
        f"{sorted(set(rest_times) - set(mcp_times))}, only on MCP "
        f"{sorted(set(mcp_times) - set(rest_times))}."
    )

    assert mcp_times == rest_times, (
        "the two doors put different strings on the wire for the same instants: "
        f"REST {rest_times}, MCP {mcp_times}. One encoder in "
        "`config/api.py`, consumed by `config/mcp.py`. It is a difference "
        "between two JSON encoders and never between two doors, and a client "
        "cannot compare two rows for equality while it stands."
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_shared_instant_is_the_doors_own_precision_and_not_merely_shared(
    bearer: str, tenant: Tenant, node: Organization
) -> None:
    """Agreement is half the claim; the OTHER half is which door won.

    The direction was ruled once — the REST door's millisecond rendering is the truth
    and everything truncates to match — so a future change that reconciled the
    two by pushing REST UP to microseconds would satisfy the test above and
    break every client that already parses the published contract. This is what
    makes the direction assertable rather than merely intended.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                ROUTE.format(node.pk), headers={**bearer_header, "accept": JSON}
            )

    for key, rendered in _datetimes(over_http.json()).items():
        _, _, fraction = rendered.partition(".")
        digits = "".join(ch for ch in fraction if ch.isdigit())
        assert len(digits) <= MAX_FRACTIONAL_DIGITS, (
            f"{key} carries {len(digits)} fractional digits ({rendered!r}). The "
            "door encoder writes milliseconds; more than that means REST was "
            "moved UP to meet the machine door, which is the one direction that "
            "was ruled against because it breaks published clients."
        )
