"""The two doors answering one question, compared **on the wire** (house rule 46).

House rule 17 diffs two registries and proves the capability exists on both
sides. It cannot see the two doors DISAGREE about it, and both times they did in
this tree the finding came from a test of exactly this shape and from nothing
else — one case (REST renders a response by field name, the MCP transport renders
`structuredContent` by alias: one row, two key sets, every value equal) and another
(one consumer, one person, two different sets of frames).

So this drives both doors through the one real ASGI application —
`config.asgi.build_application()`, the object `scripts/serve.sh` hands uvicorn —
over `httpx`, and compares `response.json()` against `result["structuredContent"]`,
**key set exact and then whole**. Nothing here calls a tool function: a tool
function returns a `UsageReportOut`, and the class of bug this exists for lives
in the serializer between that object and the client.

The subject is a REPORT rather than a row, which gives this module a third claim
the worked example (`apps/example/tests/test_doors_over_the_wire.py`) makes for
its `Measured` stats and this one makes for money-adjacent numbers: the basis is
**re-added here** from the body each door sent, using the formula it sent. A
door that shipped a total its own days do not sum to would be a bill nobody
could check, and it would be invisible to a test that only compared the two
doors to each other.

`transaction=True` because the MCP transport runs a tool body on a worker thread
with its own database connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest

from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.middleware import ORG_HEADER
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.usage.services import record_usage
from apps.usage.tests.conftest import METER, OTHER_METER, World

#: House rule 46. The door pair this module answers for `apps/usage`, read by
#: the gate off this module-level assignment. This app is born with its pair
#: answered — it has never been in the backlog `rules.yaml` records, and the
#: number it would have started at is the number it stays at: none owed.
DOOR_PAIR = ("rest", "mcp")

REST_URL = "/api/v1/usage/"
METERS_URL = "/api/v1/meters/"
MCP_URL = "/mcp"
JSON = "application/json"

NOON = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
ON = NOON.date().isoformat()

# The report's wire shape at each level, written out rather than derived from
# the schemas — a pin taken from the thing it pins cannot fail. This is the REST
# contract and both doors are held to it, so a rename that reaches the wire
# has to change these lines in the diff.
REPORT_KEYS = frozenset({"period", "starts_on", "ends_on", "meters"})
MEASURED_KEYS = frozenset({"value", "basis"})
BASIS_KEYS = frozenset({"formula", "inputs"})
#: The list envelope, ADR core-18's, written out here for the same reason: the
#: catalogue rides the one paginator and a door that grew its own would show up
#: as a key set rather than as a subtle disagreement about a cursor.
PAGE_KEYS = frozenset({"items", "has_more", "next_cursor", "count"})


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """One JSON-RPC request body, spelled the way a real MCP client spells it."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.fixture
def seeded(recorded_workflow_starts: None, world: World, a_declared_meter: str) -> World:
    """Two days of consumption in one branch, so a basis has something to say.

    Written through `record_usage` rather than the manager, so the rows are the
    shapes production makes — the append-only belt, the org placement and the
    idempotency key all apply.

    `recorded_workflow_starts` first in the signature, and it is load-bearing:
    the commit is real in a `transaction=True` test, so `world`'s own
    `create_widget` would otherwise dial a Temporal server this module has no
    reason to start.
    """
    for index, (quantity, day) in enumerate(((Decimal("30"), 0), (Decimal("12.5"), 1))):
        record_usage(
            tenant=world.tenant,
            actor=world.north_actor,
            meter=METER,
            quantity=quantity,
            ref=world.widget,
            idempotency_key=f"parity-{index}",
            occurred_at=NOON + timedelta(days=day),
        )
    return world


@pytest.fixture
def bearer(seeded: World) -> str:
    """A token scoped exactly to this section — minted in a SYNC fixture.

    Every ORM call this module makes happens out here rather than in the test
    body: an `async def` test runs with a live event loop in its thread, and
    Django refuses a synchronous query there. That is a property of the harness
    rather than of the doors, so it is arranged once and never worked around.
    """
    _, plaintext = issue_token(
        user=seeded.owner,
        tenant=seeded.tenant,
        name="door-parity",
        scopes=["usage:read"],
        actor=actor_for(user=seeded.owner, tenant=seeded.tenant),
    )
    return plaintext


@pytest.fixture
def elsewhere_bearer(seeded: World) -> str:
    """A token minted for another section entirely, for the ceiling probe."""
    _, plaintext = issue_token(
        user=seeded.owner,
        tenant=seeded.tenant,
        name="elsewhere",
        scopes=["widgets:read"],
        actor=actor_for(user=seeded.owner, tenant=seeded.tenant),
    )
    return plaintext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_report_on_the_wire(bearer: str) -> None:
    """One window, two doors: one key set, one body, one basis that re-adds.

    Three claims, and each is a different way the contract could rot:

    1. **the shape is the published one**, at all three levels — the report, the
       measured number inside it, and the basis inside that. A number that
       arrived naked would satisfy any test that only compared the doors to each
       other;
    2. **the two doors agree**, key for key and then value for value. Asserted at
       that strength because the two doors *can* meet it: a `Decimal` renders as
       a string on both sides — pydantic's JSON mode and ninja's encoder agree —
       so there is no float to be tolerant about;
    3. **the basis is honest**, recomputed here from the days the server sent.
       That is what makes the basis a contract rather than decoration, and on a
       ledger that reaches an invoice it is the assertion that matters most.
    """
    from config.asgi import build_application

    application = build_application()
    credential = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                f"{REST_URL}?period=month&on={ON}", headers={**credential, "accept": JSON}
            )
            assert over_http.status_code == 200, over_http.text

            headers = {**MCP_HEADERS, **credential}
            initialize = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "usage-door-parity", "version": "1"},
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
                    {"name": "get_usage", "arguments": {"period": "month", "on": ON}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    # (1) the REST body first, against the written-out contract: whatever the two
    # doors are made to agree on, they agree on *this*. Without this half a
    # future fix could reconcile them by moving REST, which is the one direction
    # that breaks a client.
    assert set(rest_body) == REPORT_KEYS
    measured = rest_body["meters"][METER]
    assert set(measured) == MEASURED_KEYS
    assert set(measured["basis"]) == BASIS_KEYS

    # (2) the two doors. Key sets first, because that is what actually diverged
    # the last time and because an equality failure on nested dicts says
    # far less than a key-set failure does.
    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same report with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "A `Field(alias=...)` on a read schema does this: the MCP transport "
        "serialises `structuredContent` by alias and REST renders by field name."
    )
    assert set(over_mcp["meters"]) == set(rest_body["meters"])
    assert over_mcp == rest_body

    # (3) the basis is honest, and it is really measuring something: the two
    # entries are in there, so the agreement above is not two doors agreeing on
    # an empty ledger.
    assert measured["basis"]["formula"] == "sum(day_totals)"
    recomputed = sum(Decimal(str(value)) for value in measured["basis"]["inputs"].values())
    assert recomputed == Decimal(measured["value"])
    assert recomputed == Decimal("42.5")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_the_same_narrow_token(elsewhere_bearer: str) -> None:
    """The ceiling probe at the machine door, beside the one at the human door.

    A token minted for another section is refused at both, and both name
    `usage:read` — an agent that is told "no" without the name of what to ask
    for cannot tell its human what to mint. The refusals are worded by two
    different composers (`config/api.py` and `core.mcp.tool_call`), which is
    exactly why the property is asserted on both rather than on one.
    """
    from config.asgi import build_application

    application = build_application()
    credential = {"authorization": f"Bearer {elsewhere_bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(REST_URL, headers={**credential, "accept": JSON})

            headers = {**MCP_HEADERS, **credential}
            await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "usage-ceiling", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc("tools/call", {"name": "get_usage", "arguments": {}}, 2),
            )

    assert over_http.status_code == 403, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "insufficient_scope"
    assert "usage:read" in rest_body["detail"]

    answered = called.json()
    said = str(answered)
    assert "insufficient_scope" in said, answered
    assert "usage:read" in said, answered


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_publish_the_same_vocabulary(bearer: str) -> None:
    """**The vocabulary, at both doors.** One catalogue, one envelope, one derivation.

    The vocabulary is the half that makes the read door's refusal usable: an
    agent told "not a meter" needs somewhere to find out what the meters are,
    and a machine door that could not list them would leave it guessing at a
    closed set. So the pair lands together and is compared the same way the
    report is — key set exact, then whole — because a catalogue the two doors
    described differently would be two vocabularies, which is the one thing a
    derived registry exists not to become.
    """
    from config.asgi import build_application

    application = build_application()
    credential = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(METERS_URL, headers={**credential, "accept": JSON})
            assert over_http.status_code == 200, over_http.text

            headers = {**MCP_HEADERS, **credential}
            await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "usage-vocabulary", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc("tools/call", {"name": "list_meters", "arguments": {}}, 2),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(rest_body) == PAGE_KEYS
    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same catalogue with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}."
    )
    assert over_mcp == rest_body
    # And it is really measuring something: the planted registry is in there, so
    # the agreement above is not two doors agreeing on an empty vocabulary.
    assert [item["name"] for item in rest_body["items"]] == [METER, OTHER_METER]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_the_same_unresolved_hat(bearer: str) -> None:
    """**The zero-bill hazard, at both doors.** A hat that was sent and did not resolve is refused.

    The report is the one answer in this product where failing closed to `None`
    is not safe: an empty ledger and a mistyped `X-Org` produce the same body,
    and that body reads "you consumed nothing". At the machine door it is worse,
    because an assistant repeats the number in a sentence.

    The two doors reach the decision by different routes — one reads
    `request.headers`, the other the ASGI scope — which is exactly why the
    property is driven on both rather than on one, and why the decision itself
    is a single function each of them calls.

    **That function moved out of this app** (ADR core-21). It was
    `apps/usage/api.py`'s, the first place this hazard was closed; it is
    `core.middleware.addressing_refusal` now, asked by every door before any
    route or tool runs. So the machine door refuses at the transport — the call
    is refused before anything parses it as a request, which is why the
    `initialize` handshake is refused too and no tool is dispatched at all — and
    the two bodies are not merely equivalent but **byte-identical**, because
    both are `wire_refusal` over the same exception class.
    """
    from config.asgi import build_application

    application = build_application()
    credential = {"authorization": f"Bearer {bearer}", ORG_HEADER: "nosuchorg"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                f"{REST_URL}?period=month&on={ON}", headers={**credential, "accept": JSON}
            )

            headers = {**MCP_HEADERS, **credential}
            await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "usage-bad-hat", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "get_usage", "arguments": {"period": "month", "on": ON}},
                    2,
                ),
            )

    assert over_http.status_code == 403, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "addressing_header_not_honoured"
    assert ORG_HEADER in rest_body["detail"], rest_body

    assert called.status_code == 403, called.text
    assert called.json() == rest_body, (called.text, over_http.text)
    said = called.text
    assert "meters" not in said, "a refused hat must never come back as a report at all"
