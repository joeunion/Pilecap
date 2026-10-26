"""One webhook endpoint, answered by both doors, compared on the wire.

House rule 46: every door pair an app has owes a parity test in that app.
`apps/events` has a REST door (`api.py`) and an MCP door (`mcp.py`), so it owes
`(rest, mcp)`, and this module is the answer.

**Why a registry diff is not this.** House rule 17 proves a capability exists on
both doors; it cannot see the two doors *disagree* about one. Both times they
did in this tree, both registries were complete: once, REST rendered a response
by field name while the MCP transport rendered `structuredContent` by
**alias**, so one `Field(alias=...)` made the machine door answer `owner.email`
where the human door answered `owner_email`; another time, one consumer, one
person, two credentials, two different sets of frames. Neither is visible to a
diff of two registries, and each was found by a test of exactly this shape.

**The capability under test is `retrieve an endpoint`** — `GET
/api/v1/webhook-endpoints/{id}/` and the `get_endpoint` tool. It is the
representative one on purpose: it is a read of the app's central row, both doors
answer the *same* schema (`WebhookEndpointOut`), and that shared schema is
exactly the condition under which the alias mismatch hid — a value-by-value comparison of two
`model_dump()`s of one schema cannot fail, because both sides of it are the same
call. So nothing here calls a tool function: both doors are driven through the
one real ASGI application, over `httpx`, and `response.json()` is compared with
`result["structuredContent"]`.

**Two assertions, and the second is this app's own contract.** The key sets must
match, and they must match a written-out pin so that a future fix cannot
reconcile the doors by moving REST — the one direction that breaks a client. And
the signing secret must appear in **neither** body, by key and by substring:
`WebhookEndpointOut` has no field for it, which is the whole design
(`schemas.py`), and a parity test that did not check both doors for it would be
the place that regression could land unseen.

**What this test found** (the reason
rule 46 exists): the two doors render `created_at`/`updated_at` at **different
precision** — REST through ninja's `DjangoJSONEncoder`, truncated to
milliseconds; MCP through pydantic, in microseconds. Same instant, two strings.
It is the (rest, mcp) spelling of the same class of finding closed for the
event-payload-vs-REST-body pair and never for this one, and the fix is a single
encoder decision above both doors, which is not this app's to take. So the
relationship is pinned here meanwhile — same moment, REST a truncation of MCP —
exactly as comms-a pinned its own instance of that class. A divergence that ever becomes a different
*moment* fails; the day the encoders are unified, the pin still passes.

`transaction=True` because the MCP transport runs a tool body on a worker thread
with its own database connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from asgiref.sync import sync_to_async

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.models import Tenant
from apps.core.tests.doors import assert_four_doors, canonical

# The transport harness, from the module that owns it. Copying it here would be
# a second thing to keep in step with the MCP protocol version.
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.core.tests.wire import initialize, rpc, wire
from apps.events.events import ENDPOINT_REGISTERED
from apps.events.models import Event, WebhookEndpoint

#: House rule 46. The door pair this module answers for `apps/events`, read by
#: the gate off this module-level assignment. The population is DERIVED from the
#: doors the app has — a REST door beside an `mcp.py` owes `(rest, mcp)` — and
#: this is the claim that it is answered here.
DOOR_PAIR = ("rest", "mcp")

DETAIL_URL = "/api/v1/webhook-endpoints/{}/"
MCP_URL = "/mcp"
JSON = "application/json"

SECRET = "whsec-a-shared-secret-for-parity"  # noqa: S105 — a signing secret the test both signs and verifies with  # pragma: allowlist secret

#: `WebhookEndpointOut`'s wire contract, written out rather than derived from the
#: schema. A pin derived from the thing it pins cannot fail; this one fails the
#: day somebody adds a field, which is when a reviewer should be looking.
ENDPOINT_KEYS = frozenset(
    {"id", "url", "is_active", "event_names", "description", "created_at", "updated_at"}
)


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """One JSON-RPC request body, spelled the way a real MCP client spells it."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="events-door-parity",
        actor=actor_for(user=owner, tenant=tenant),
    )
    return plaintext


@pytest.fixture
def endpoint(tenant: Tenant) -> WebhookEndpoint:
    """One committed subscriber for both doors to answer with.

    Written through the manager rather than through `register_endpoint`: the
    service mints its own secret and emits `events.endpoint.registered`, and this
    test is about how a row is RENDERED, not about how it is made. A known secret
    is what lets the substring half of the assertion below mean something.
    """
    return WebhookEndpoint.objects.create(
        tenant=tenant,
        url="https://subscriber.example/parity",
        secret=SECRET,
        description="the parity subscriber",
        event_names=["example.widget.created"],
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_endpoint_on_the_wire(
    bearer: str, endpoint: WebhookEndpoint
) -> None:
    """The same row over HTTP and over JSON-RPC: one key set, one set of values.

    The keys are asserted first and by themselves, because keys were the
    disagreement and values were not — a test that compared only values
    passed while the two doors described one row in two vocabularies.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(endpoint.pk), headers={**bearer_header, "accept": JSON}
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
                        "clientInfo": {"name": "events-door-parity", "version": "1"},
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
                    {"name": "get_endpoint", "arguments": {"endpoint_id": str(endpoint.pk)}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    # The REST body first, against the written-out contract: whatever the two
    # doors are made to agree on, they agree on *this*. Without this half, a
    # future fix could reconcile the doors by moving REST, which is the one
    # direction that breaks a client.
    assert set(rest_body) == ENDPOINT_KEYS

    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same webhook endpoint with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "A `Field(alias=...)` on a read schema does this: the MCP transport "
        "serialises `structuredContent` by alias and REST renders by field name. "
        "Resolve a relation with a model property, not an alias."
    )

    # Values too — keys were the earlier finding, values are what a client uses. EVERY
    # field, timestamps included: this comparison used to have to exclude a
    # `TIMESTAMPS` tuple, because the REST door rendered through ninja's
    # `DjangoJSONEncoder` (milliseconds) while the MCP transport serialised
    # `structuredContent` through pydantic (microseconds) — one row, two
    # strings, one instant. `config/mcp.py` now puts every machine-door answer
    # out through the HTTP door's own encoder, so there is no exception left to
    # name and no relationship left to pin: the two doors write the same bytes.
    assert over_mcp == rest_body
    assert rest_body["url"] == endpoint.url
    assert rest_body["event_names"] == ["example.widget.created"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_neither_door_ever_answers_the_signing_secret(
    bearer: str, endpoint: WebhookEndpoint
) -> None:
    """No read of an endpoint carries the key, on either wire. By key AND by substring.

    `WebhookEndpointOut` has no field for the secret — it is not filtered out,
    there is nowhere to put it — and `test_api.py` holds that over the REST door
    across every shape a client can reach an endpoint through. What is only
    provable *here* is the same claim for the machine door, on the wire the MCP
    transport actually writes: a serialiser that rendered extra attributes, or a
    tool that answered `WebhookEndpointSecretOut` by mistake, would be invisible
    to a REST-only net and to a registry diff alike.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(endpoint.pk), headers={**bearer_header, "accept": JSON}
            )
            headers = {**MCP_HEADERS, **bearer_header}
            await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "events-door-parity", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "get_endpoint", "arguments": {"endpoint_id": str(endpoint.pk)}},
                    2,
                ),
            )

    assert "secret" not in over_http.json()
    assert SECRET not in over_http.text
    # The WHOLE JSON-RPC envelope, not just `structuredContent`: the transport
    # also writes a text rendering of the result, and a key that leaked into one
    # and not the other is still a key that left the building.
    assert SECRET not in called.text


# --- the read refusal, on both doors, in the same words -----------------------


@pytest.fixture
def member_bearer(tenant: Tenant, member: User) -> str:
    """A real token for the plain member — the credential both doors accept."""
    _, plaintext = issue_token(
        user=member,
        tenant=tenant,
        name="events-read-parity",
        actor=actor_for(user=member, tenant=tenant),
    )
    return plaintext


@pytest.fixture
def withheld_endpoint_read(tenant: Tenant, member: User) -> str:
    """A committed `withhold` of `endpoint.read` on the member, and its sentence.

    A fixture rather than three lines in the test body, because the body is
    `async def`: Django refuses a synchronous query from an async context, and
    the row has to be COMMITTED before the transport's worker thread looks for
    it anyway. Raw `Grant`, as everywhere in this lane until the hand-out
    services land.
    """
    from apps.core.authz import refusal_sentence
    from apps.core.models import Grant, Membership

    membership = Membership.objects.get(user=member, tenant=tenant)
    Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="endpoint.read",
        effect=Grant.Effect.WITHHOLD,
    )
    return refusal_sentence("endpoint.read")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_the_same_withheld_read_with_the_same_words(
    member_bearer: str, withheld_endpoint_read: str, endpoint: WebhookEndpoint
) -> None:
    """House rule 46, applied to the read gate.

    The parity case above proves the two doors agree when they ANSWER. This
    proves they agree when they REFUSE, which is the half a parity test over
    happy paths cannot see — and refusals are where the doors have the most room
    to drift, because each has its own error envelope and neither shares the
    other's.

    The withheld key is `endpoint.read`, and the sentence both doors must speak
    is `refusal_sentence("endpoint.read")` — derived from the key rather than
    typed here, so a product that gives the key its own prose moves both doors at
    once or fails here. The key is spelled `endpoint.*` and not
    `webhook_endpoint.*` because `WebhookEndpoint` declares its kind
    (`models.py`), which is the sweep this case arrived with.
    """
    import json as _json

    from config.asgi import build_application

    sentence = withheld_endpoint_read
    application = build_application()
    bearer_header = {"authorization": f"Bearer {member_bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(endpoint.pk), headers={**bearer_header, "accept": JSON}
            )

            headers = {**MCP_HEADERS, **bearer_header}
            initialize = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "read-parity", "version": "1"},
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
                    {"name": "get_endpoint", "arguments": {"endpoint_id": str(endpoint.pk)}},
                    2,
                ),
            )

    # The human door: a row INSIDE the tenant, refused by capability and not
    # hidden — 404 there would say "no such endpoint", which is false and is the
    # answer the scoping gives for a row in a tenant you cannot reach.
    assert over_http.status_code == 403, over_http.text
    body = over_http.json()
    assert body["code"] == "forbidden"
    assert body["detail"] == sentence

    # The machine door: the same code and the same sentence, through
    # `wire_refusal`. Compared as text because a tool error is text on the wire.
    rendered = _json.dumps(called.json())
    assert "forbidden" in rendered, rendered
    assert sentence in rendered, rendered


# --- one registration, told four ways -------------------------------------------


def _recorded_payload(tenant: Tenant) -> dict[str, Any]:
    payload: dict[str, Any] = Event.objects.for_tenant(tenant).get(name=ENDPOINT_REGISTERED).payload
    return payload


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("pressed_on", ["rest", "mcp"])
async def test_one_registration_is_one_row_on_both_doors_and_in_its_event(
    bearer: str, tenant: Tenant, recorded_workflow_starts: None, pressed_on: str
) -> None:
    """Registered on one door, read on both: the two reads and the recorded event agree."""
    auth = {"authorization": f"Bearer {bearer}"}
    body = {"url": "https://subscriber.example/four-doors", "description": "four doors"}
    async with wire() as client:
        await initialize(client, auth, who="events-four-doors")
        if pressed_on == "rest":
            pressed = await client.post(
                "/api/v1/webhook-endpoints/", headers={**auth, "accept": JSON}, json=body
            )
            assert pressed.status_code == 201, pressed.text
            created = pressed.json()["endpoint"]
        else:
            called = await client.post(
                MCP_URL,
                headers={**MCP_HEADERS, **auth},
                json=rpc("tools/call", {"name": "create_endpoint", "arguments": body}, 2),
            )
            assert "error" not in called.json(), called.text
            created = called.json()["result"]["structuredContent"]["endpoint"]
        over_http = await client.get(
            DETAIL_URL.format(created["id"]), headers={**auth, "accept": JSON}
        )
        assert over_http.status_code == 200, over_http.text
        read = await client.post(
            MCP_URL,
            headers={**MCP_HEADERS, **auth},
            json=rpc(
                "tools/call",
                {"name": "get_endpoint", "arguments": {"endpoint_id": created["id"]}},
                3,
            ),
        )
    over_mcp = read.json()["result"]["structuredContent"]
    assert canonical(created) == canonical(over_http.json())
    payload = await sync_to_async(_recorded_payload)(tenant)
    assert_four_doors(rest=over_http.json(), mcp=over_mcp, event_payload=payload)
