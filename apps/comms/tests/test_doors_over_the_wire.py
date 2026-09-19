"""The comms doors as a real client meets them — over the wire, not through a stub.

House rule 46's answer for `apps/comms`, and the reason it is a new module
rather than a marker dropped on `test_mcp.py`.

`test_mcp.py` already compares the two doors twice, and both comparisons are
worth having: one asserts the same row value-for-value, the other asserts the
same key set with `model_dump(by_alias=True)`. Neither is being replaced, and
the second is **not** blind to the alias class — a planted `serialization_alias`
(driven live when this module was written) fails it
too. The honest difference is narrower and it is the whole reason this module
exists: both of those call the tool function and then *imitate* the transport.
`model_dump(by_alias=True)` is this suite's opinion about what the MCP transport
does with a returned `MessageOut`, checked against itself. Anything the
transport does that the imitation does not — a protocol version that changes how
`structuredContent` is built, a serializer that is not pydantic's, an auth or
routing difference that only exists once a request is real — is invisible to an
opinion and visible to a wire.

So this module drives **both doors through the one real ASGI application** —
`config.asgi.build_application()`, the object `scripts/serve.sh` hands uvicorn —
over `httpx`, and compares `response.json()` against
`result["structuredContent"]`, **key set exact**. Nothing here calls a tool
function. `apps/example/tests/test_doors_over_the_wire.py` is the worked example
this is built to, and the two are deliberately the same shape.

Why comms is worth the second instance rather than a marker on the example's:
`MessageOut` is the schema whose class docstring cites this door-parity
mechanism as the reason it
carries no aliases and resolves two relations through model properties instead.
That is an argument in a comment, and this is the test that makes it a fact —
including the two properties (`recipient_email`, `organization_slug`) that are
exactly what an alias would have been used for.

`transaction=True` because the MCP transport runs a tool body on a worker thread
with its own database connection, which cannot see an uncommitted row. The real
commit is also why `recorded_workflow_starts` is declared: `send()` starts
`DeliverMessageWorkflow` on commit, and this test has no reason to dial a
Temporal server (`apps/comms/tests/test_workflows.py` is where that is proved).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.comms.models import Message, MessageTemplate, Recipient
from apps.comms.services import send
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import refusal_message
from apps.core.models import Grant, Membership, Organization, Tenant

# The transport harness, from the module that owns it. Copying it here would be
# a second thing to keep in step with the MCP protocol version.
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running

#: House rule 46. The door pair this module answers for `apps/comms`, read by
#: the gate off this module-level assignment. `apps/comms` has `api.py` and
#: `mcp.py` and no `consumers.py`, so `(rest, mcp)` is the whole of what it
#: owes — the socket pair belongs to `apps/realtime`, which answers its own.
DOOR_PAIR = ("rest", "mcp")

DETAIL_URL = "/api/v1/messages/{}/"
LIST_URL = "/api/v1/messages/"
MCP_URL = "/mcp"
JSON = "application/json"

# `MessageOut`'s wire contract as a key set, written out rather than derived
# from the schema — a pin derived from the thing it pins cannot fail. This is
# the REST contract both doors are held to, so a rename that reaches the wire
# has to change this line, in the diff, where a reviewer sees it.
MESSAGE_KEYS = frozenset(
    {
        "id",
        "recipient_id",
        "recipient_email",
        "organization_id",
        "organization_slug",
        "template_name",
        "template_version",
        "channel",
        "category",
        "status",
        "suppressed_reason",
        "provider",
        "provider_message_id",
        "subject",
        "error",
        "correlation_id",
        "created_at",
        "send_at",
        "sent_at",
        "delivered_at",
        "bounced_at",
        "bounce_kind",
    }
)

# The two keys that would have been aliases. `MessageOut` resolves them as
# properties on `Message` instead, and its docstring says why; these are named
# separately so a failure points at the specific claim rather than at a diff of
# twenty-one strings.
THE_KEYS_AN_ALIAS_WOULD_HAVE_BROKEN = frozenset({"recipient_email", "organization_slug"})


#: **RETIRED.** This module used to name the fields whose PRECISION the
#: two doors disagreed about. `config/mcp.py` now puts every machine-door answer
#: out through the HTTP door's own encoder, so the two doors write the same
#: bytes and there is no exception left to name.

# The two keys that would have been aliases. `MessageOut` resolves them as
# properties on `Message` instead, and its docstring says why; these are named
# separately so a failure points at the specific claim rather than at a diff of
# twenty-one strings.
THE_KEYS_AN_ALIAS_WOULD_HAVE_BROKEN = frozenset({"recipient_email", "organization_slug"})


#: **RETIRED.** This module used to name the fields whose PRECISION the
#: two doors disagreed about — the FOURTH independent confirmation of one
#: platform gap, after `apps/events`, `apps/exports` and `apps/files`.
#: `config/mcp.py` now puts every machine-door answer out through the HTTP
#: door's own encoder, so the two doors write the same bytes and there is no
#: exception left to name.


def assert_same_row(*, over_mcp: dict[str, Any], over_rest: dict[str, Any]) -> None:
    """Two renderings of one row, value for value — **timestamps included**.

    Driven off the REST row's own keys, not a name list: this helper serves two
    shapes in this module (a device and an engagement) and neither carries every
    field the other does.
    """
    for key in over_rest:
        assert over_mcp[key] == over_rest[key], f"the two doors disagree about {key}"


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """One JSON-RPC request body, spelled the way a real MCP client spells it."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="comms-door-parity",
        actor=actor_for(user=owner, tenant=tenant),
    )
    return plaintext


@pytest.fixture
def message(
    tenant: Tenant,
    owner_actor: Actor,
    recipient: Recipient,
    receipt: MessageTemplate,
    recorded_workflow_starts: None,
) -> Message:
    """One committed message for both doors to answer with.

    Sent through `send()` rather than written with the manager, so the row has
    the template name and version, the provider, the correlation id and the
    organization every read shape walks — a hand-built row would let the two
    doors agree about a shape the product never actually produces.
    """
    return send(
        recipient=recipient,
        template="receipt",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=owner_actor,
    )


async def _initialize(client: httpx.AsyncClient, headers: dict[str, str], who: str) -> None:
    """The MCP handshake, which every `tools/call` on this transport needs first."""
    initialize = await client.post(
        MCP_URL,
        headers=headers,
        json=_rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": who, "version": "1"},
            },
            1,
        ),
    )
    assert initialize.status_code == 200, initialize.text


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_key_set_on_the_wire(
    bearer: str, message: Message
) -> None:
    """The same message, over HTTP and over JSON-RPC: one key set, not two.

    **Keys first, then every value** — and the order is the history. The key
    comparison came first because keys were the disagreement:
    `recipient.email` and `recipient_email` carry the same string, so a
    value-only test passed while the two doors described one row in two
    vocabularies. That half still leads, because it is the one that fails
    legibly on the day an alias lands.

    **A later pass added the second half**, and it was owed: rule 46's own
    `does_not_cover` says the marker proves existence and never strength, and
    this module named that frontier while sitting on the other side of
    it. A key-set test cannot see a tool that returns the right FIELDS with a
    wrong VALUE in one of them — planted live (`subject.upper()` on
    `get_message_tool`) and green on all four tests before the change.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(message.pk), headers={**bearer_header, "accept": JSON}
            )
            assert over_http.status_code == 200, over_http.text

            headers = {**MCP_HEADERS, **bearer_header}
            await _initialize(client, headers, "comms-door-parity")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "get_message", "arguments": {"message_id": str(message.pk)}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    # The REST body first, against the written-out contract: whatever the two
    # doors are made to agree on, they agree on *this*. Without this half a
    # future fix could reconcile them by moving REST, which is the one
    # direction that breaks a client already in the field.
    assert set(rest_body) == MESSAGE_KEYS

    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same message with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "A `Field(alias=...)` on a read schema does this: the MCP transport "
        "serialises `structuredContent` by alias and REST renders by field "
        "name. Resolve a relation with a model property, not an alias — "
        "`MessageOut`'s own docstring records the rule and `Message` carries "
        "the two properties."
    )

    # The specific claim `MessageOut`'s docstring makes, named on its own so a
    # regression points at the argument it falsifies rather than at a diff.
    assert THE_KEYS_AN_ALIAS_WOULD_HAVE_BROKEN <= set(over_mcp)
    assert THE_KEYS_AN_ALIAS_WOULD_HAVE_BROKEN <= set(rest_body)

    # And the row is really this row, so the agreement above is not two doors
    # agreeing about the wrong message.
    assert rest_body["id"] == str(message.pk)
    assert rest_body["recipient_email"] == message.recipient.email

    # **VALUE FOR VALUE, and this is that later pass's whole point** (the
    # rule-46 frontier this app named out loud: the marker proves existence,
    # never strength). Until now these two tests compared KEY SETS and
    # spot-checked exactly two of twenty-one values — so a tool that returned
    # the right fields with a wrong value in one of them passed, driven live
    # by planting `subject.upper()` on `get_message_tool` and watching all four
    # tests stay green. Every field is compared now; timestamps by their moment.
    assert_same_row(over_mcp=over_mcp, over_rest=rest_body)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_list_doors_put_the_same_envelope_on_the_wire(
    bearer: str, message: Message
) -> None:
    """The list door's envelope, on both wires — the half a detail test cannot see.

    `MessagePage` exists because the MCP tool has to *name* the envelope REST
    gets for free from ninja's `@paginate`, and two spellings of one envelope is
    the same defect as two spellings of one row, one level up: a machine client
    that has learned to unwrap the REST list must not have to learn a second
    shape. The item keys are asserted too, because an envelope can agree while
    the rows inside it do not.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(LIST_URL, headers={**bearer_header, "accept": JSON})
            assert over_http.status_code == 200, over_http.text

            headers = {**MCP_HEADERS, **bearer_header}
            await _initialize(client, headers, "comms-list-parity")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc("tools/call", {"name": "list_messages", "arguments": {}}, 2),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(over_mcp) == set(rest_body), (
        "The two list doors put different envelopes on the wire. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "`MessagePage` is declared to be the SAME envelope ninja's `@paginate` "
        "produces, so a client unwraps one shape and not two."
    )

    # One row, and it is the fixture's — an envelope comparison over two empty
    # lists is two doors agreeing about nothing.
    assert len(rest_body["items"]) == 1, rest_body
    assert len(over_mcp["items"]) == 1, over_mcp
    assert rest_body["items"][0]["id"] == str(message.pk)
    assert set(over_mcp["items"][0]) == set(rest_body["items"][0]) == MESSAGE_KEYS

    # And the row INSIDE the envelope, value for value (T-pr). An envelope can
    # agree while the rows in it do not, and a list door is the one where that
    # is easiest to miss: `MessagePage` re-validates each `MessageOut` on the
    # way out, which is exactly where the `resolve_`-hook class of defect this
    # module's own conventions note records bites.
    assert_same_row(over_mcp=over_mcp["items"][0], over_rest=rest_body["items"][0])

    # The envelope's own three, which are not a row and are not timestamps.
    for key in ("has_more", "next_cursor", "count"):
        assert over_mcp[key] == rest_body[key], f"the two doors disagree about {key}"


# --- two new capabilities ---------------------------------------------------
#
# **`apps/comms`' rule-46 ratchet was ALREADY at zero** — an earlier pass paid it,
# and `quality/rules.yaml` records that in the backlog beside the entry. So this
# module moved no ratchet and edited no yaml; what it owes instead is the harder
# half the rule's own `does_not_cover` names as its frontier: *the marker proves
# existence, never strength*. A door pair answered by one module and then grown
# by two capabilities nobody drove over the wire is a claim that has quietly
# stopped covering the app it claims for.
#
# So the engagement list and the device registration are driven here, through the
# same one real ASGI application, and compared key-set-exact — which is also
# where the two new schemas' aliases would show up if anybody ever added one.

DEVICES_URL = "/api/v1/devices/"
ENGAGEMENT_URL = "/api/v1/messages/{}/engagement/"

#: `DeviceOut`'s wire contract as a key set, written out rather than derived —
#: `MESSAGE_KEYS`' reason: a pin derived from the thing it pins cannot fail.
DEVICE_KEYS = frozenset(
    {
        "id",
        "recipient_id",
        "organization_id",
        "platform",
        "label",
        "retired_at",
        "created_at",
        "updated_at",
    }
)

#: What must never be on either door's answer, at any level of either envelope.
#: A separate constant rather than an inversion of the set above, because the
#: failure worth catching is a NEW field carrying token material, and a set
#: comparison would have to be updated to allow it while this would not.
NOTHING_ABOUT_THE_TOKEN = ("push_token", "token_hash", "push_token_hash")


@pytest.fixture
def witnessed(tenant: Tenant, owner_actor: Actor, message: Message) -> Any:
    """One message a transport accepted, with one engagement recorded on it.

    Sync, like every other fixture here, and through the services: the handle a
    provider gave us is what `record_engagement` joins on, so a message that was
    only queued has no handle and the write is `not_found` — which is the first
    thing this drive found when the engagement was recorded inline.
    """
    from apps.comms.services import record_engagement, record_message_sent
    from apps.core.actor import system_actor
    from apps.core.services import root_organization

    sent = record_message_sent(
        tenant=tenant,
        actor=owner_actor,
        message=message,
        provider="anymail:resend",
        provider_message_id="parity-handle-1",
    )
    engagement = record_engagement(
        tenant=tenant,
        actor=system_actor(tenant, root_organization(tenant=tenant)),
        provider_message_id=sent.provider_message_id,
        kind="opened",
        provider_event_id="evt-parity-1",
    )
    return sent, engagement


@pytest.fixture
def a_device(tenant: Tenant, owner_actor: Actor, recipient: Recipient) -> Any:
    """One committed device for the retire parity drive to address."""
    from apps.comms.services import register_device

    return register_device(
        tenant=tenant,
        actor=owner_actor,
        recipient=recipient,
        platform="ios",
        push_token="not-a-real-registration-token-0009",
        label="Ada's iPhone",
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_engagement_doors_put_the_same_envelope_on_the_wire(
    bearer: str, witnessed: Any
) -> None:
    """The read door, over both wires, envelope and item keys.

    The list added here is the one a product reads to answer "did anybody
    open it", and it is the first comms list whose MCP twin has to name an
    envelope that ninja gives REST for free. Two spellings of one envelope is
    the same defect as two spellings of one row.

    The engagement is recorded by the `witnessed` fixture, as the system, through
    the service — and the message is marked accepted first, because
    `record_engagement` joins on the handle a provider gave us and a merely
    queued message has none.
    """
    message, recorded = witnessed

    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                ENGAGEMENT_URL.format(message.pk), headers={**bearer_header, "accept": JSON}
            )
            assert over_http.status_code == 200, over_http.text

            headers = {**MCP_HEADERS, **bearer_header}
            await _initialize(client, headers, "comms-engagement-parity")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "list_engagements", "arguments": {"message_id": str(message.pk)}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(over_mcp) == set(rest_body), (
        "The two engagement doors put different envelopes on the wire. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}."
    )
    # One row, and it is the one recorded above — an envelope comparison over
    # two empty lists is two doors agreeing about nothing.
    assert len(rest_body["items"]) == 1, rest_body
    assert len(over_mcp["items"]) == 1, over_mcp
    assert rest_body["items"][0]["id"] == str(recorded.pk)
    # And the row inside the envelope, value for value — an envelope can agree
    # while the rows in it do not, which is the failure a key-set comparison at
    # this level would sail past.
    assert_same_row(over_mcp=over_mcp["items"][0], over_rest=rest_body["items"][0])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_device_doors_answer_the_same_row_and_neither_carries_the_token(
    bearer: str, a_device: Any
) -> None:
    """T3's write door, over both wires — and the one thing neither may say.

    Two claims in one drive because they are one property of this schema: the
    doors agree, and what they agree on carries nothing anybody could push with.
    The second half is asserted over the whole serialised body rather than as an
    absence of named keys, because the failure being guarded against is a field
    somebody adds later.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}
    token = "not-a-real-registration-token-0009"

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.post(
                f"{DEVICES_URL}{a_device.pk}/retire/",
                headers={**bearer_header, "accept": JSON, "content-type": JSON},
            )
            assert over_http.status_code == 200, over_http.text

            headers = {**MCP_HEADERS, **bearer_header}
            await _initialize(client, headers, "comms-device-parity")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "retire_device", "arguments": {"device_id": str(a_device.pk)}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(rest_body) == DEVICE_KEYS
    assert set(over_mcp) == set(rest_body), (
        "The two device doors describe the same row with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}."
    )
    assert rest_body["id"] == str(a_device.pk)
    # **Value for value**, not just key for key — which is the half rule 46's
    # `does_not_cover` names as its frontier and the half this app's existing
    # message parity tests do not do. Timestamps by their moment; see TIMESTAMPS.
    assert_same_row(over_mcp=over_mcp, over_rest=rest_body)
    # Idempotent at both doors: the MCP call is the SECOND retirement of the
    # same row, and it answers the first timestamp rather than a new one.
    assert rest_body["retired_at"] is not None

    for body in (rest_body, over_mcp):
        rendered = json.dumps(body)
        assert token not in rendered
        for forbidden in NOTHING_ABOUT_THE_TOKEN:
            assert forbidden not in rendered


# --- rule 46's named case for PR4.b: one withheld read, two doors, one sentence ---


@pytest.fixture
def withheld_bearer(tenant: Tenant, member: User, root_org: Organization) -> str:
    """A real token for somebody whose `message.read` has been taken away.

    A `member` and not an owner, because the whole point of the case is a person
    the product still lets in: the credential authenticates, the tenancy
    resolves, the row exists and is inside the hat's subtree — and the ONLY
    thing missing is the one key ADR core-27 made a key. An owner could not be
    withheld (`owner` is the vocabulary) and a stranger would be refused three
    steps earlier, so neither would be driving this property.
    """
    Grant.objects.create(
        tenant=tenant,
        membership=Membership.objects.get(user=member, tenant=tenant),
        permission="message.read",
        effect=Grant.Effect.WITHHOLD,
    )
    _, plaintext = issue_token(
        user=member,
        tenant=tenant,
        name="comms-withheld-read",
        actor=actor_for(user=member, tenant=tenant, org=root_org),
    )
    return plaintext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_the_same_withheld_read_with_the_same_words(
    withheld_bearer: str, message: Message
) -> None:
    """House rule 46's case for PR4.b, driven over the real transport.

    Rule 17 proves a capability exists on both doors; only this sees them
    **refusing differently**. A read is a permission since ADR core-27, so there
    is a new refusal on every read door in this app — and a new refusal is
    exactly where two doors drift, because the REST half goes through
    `config/api.py`'s exception seam and the MCP half through `tool_call`'s
    `wire_refusal`. Two seams, one grammar, or the assistant offers a way out
    the screen does not.

    What is asserted is the whole envelope a client branches on: the code, and
    the sentence. **The sentence and never the key** — `message.read` is an
    internal word and publishing it on the wire tells a caller to go and read
    our source (the owner's plain-language ruling of 2026-08-23).
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {withheld_bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(message.pk), headers={**bearer_header, "accept": JSON}
            )
            assert over_http.status_code == 403, over_http.text

            headers = {**MCP_HEADERS, **bearer_header}
            await _initialize(client, headers, "comms-withheld-read")
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "get_message", "arguments": {"message_id": str(message.pk)}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    rest_body = over_http.json()
    answered = called.json()
    # **The MCP door renders the refusal as TEXT, not as a JSON body**, and this
    # test compares what each wire really carries rather than what it would be
    # convenient to compare. `refusal_message` builds that line from
    # `wire_refusal`'s output — the same mapping the REST door serialises — so
    # the parity claim is that the rendered line is exactly what the REST body
    # says, rebuilt here from the REST body and asserted string for string.
    over_mcp = answered["result"]["content"][0]["text"]

    assert rest_body["code"] == "forbidden", rest_body
    assert rest_body["detail"] == "You may not read this message.", rest_body
    assert f"{rest_body['code']}: {rest_body['detail']}" in over_mcp, (over_mcp, rest_body)
    assert refusal_message(rest_body) in over_mcp, (over_mcp, rest_body)
    # And the remedies travel with it: an assistant offers the way out the
    # screen offers, which is the half ADR core-5 exists for.
    for remedy in rest_body["remedies"]:
        assert remedy["label"] in over_mcp, (remedy, over_mcp)
    # The internal key reaches neither wire.
    assert "message.read" not in json.dumps(rest_body), rest_body
    assert "message.read" not in over_mcp, over_mcp
