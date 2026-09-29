"""The doors as a real client meets them — over the wire, not through a stub.

Two properties live here, and both of them were invisible to a test that drove
the doors any other way.

## 1 · CSRF, on the REST door

Every other API test in this repository drives `django.test.Client()`, and that
client sets `_dont_enforce_csrf_checks` on the request — so `SessionAuth`'s CSRF
check is a no-op in the whole suite. That is the blind spot the cycle-0 verifier
fell into (queue V4): a bearer `POST` returned **403 "CSRF check Failed"** over
the wire while every test in the tree was green, because ninja runs the auth
callbacks in order and `APIKeyCookie._get_key` *raises* rather than declining
when the CSRF check fails — so the token authenticator was never reached.

`Client(enforce_csrf_checks=True)` is the whole difference. These three tests
are the regression net for that, and they say the property from both sides:

* the **machine door** carries a bearer token and no CSRF material at all, and
  it writes — a token is not a cookie, so there is no cross-site request to
  forge;
* the **human door** carries a session cookie and no CSRF token, and it is
  refused — that is the attack CSRF exists for, and it must stay refused;
* the same human door with `X-CSRFToken` writes.

They live in `apps/example` because the widget router is the worked example of
a write route and `example` sits above `accounts` in the layer contract, so
naming the token service here costs no exemption.

## 2 · Door parity, in the shape each door actually puts on the wire

House rule 17 is checked twice in this tree and the two checks answer different
questions. `tests/test_mcp.py` asks whether the two registries hold the same
*capabilities*, and compares one row by calling the tool function and dumping
the returned `WidgetOut`. That comparison cannot see a serialization
disagreement, because both sides of it are the same `model_dump()` call — the
schema, not the wire.

The wire is where the doors disagreed. REST renders a response by
field name; the MCP transport renders a tool result's `structuredContent` **by
alias** — so a `Field(alias="owner.email")` made the machine door answer
`owner.email` where the human door answered `owner_email`. One row, two key
sets, and every value equal, which is exactly the class of finding a
value-by-value test is blind to.

So this test drives **both** doors through the one real ASGI application —
`config.asgi.build_application()`, the object `scripts/serve.sh` hands uvicorn
— over `httpx`, and compares `response.json()` against
`result["structuredContent"]`, **key set exact**. Nothing here calls a tool
function: a tool function returns a `WidgetOut`, and the bug lived in the
serializer between that object and the client.

It is `transaction=True` because the transport runs a tool body on a worker
thread with its own database connection, which cannot see an uncommitted row.

## 4 · Parity BEFORE either door has a caller

Sections 2 and 3 compare what the doors say when they answer and when they
refuse a caller they identified. The 401 is the refusal that happens *before*
that — no principal, no tool, no route — and it is the one refusal every
integrator meets first, which is exactly why the two doors had drifted on it:
REST told a caller holding a revoked token "We could not tell who is making
this request", and `/mcp` told the same caller "That bearer token is not
valid." The case below drives one revoked token at both doors and holds them to
one `code` and one `detail`.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from django.conf import settings
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import issue_token, revoke_token
from apps.core.actor import Actor, actor_for
from apps.core.models import Tenant

# The transport harness, from the module that owns it. Copying it here would be
# a second thing to keep in step with the MCP protocol version.
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.example.models import Widget
from apps.example.services import create_widget

#: House rule 46. The door pair this module answers for `apps/example`, read by
#: the gate off this module-level assignment. Section 2 below is the parity half:
#: the same row through the REST door and through the MCP door, compared ON THE
#: WIRE rather than through the schema both sides happen to share.
DOOR_PAIR = ("rest", "mcp")

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"
DETAIL_URL = "/api/v1/widgets/{}/"
STATS_URL = "/api/v1/widgets/stats/"
MCP_URL = "/mcp"
JSON = "application/json"
PASSWORD = "a-long-enough-password"  # pragma: allowlist secret

# The widget read shape, as a key set, written out rather than derived from the
# schema — a pin derived from the thing it pins cannot fail. This is the REST
# contract (E1): both doors are held to it, and a rename that reaches the wire
# has to change this line, in the diff, where a reviewer sees it.
WIDGET_KEYS = frozenset(
    {
        "id",
        "name",
        "notes",
        "owner_id",
        "owner_email",
        "tenant_id",
        "organization_id",
        "organization_slug",
        "created_at",
        "updated_at",
        "onboarded_at",
        "policy_id",
        # The archive shape (`ArchivedOut`) and the per-row acts: an archivable
        # noun's read shape says when and by whom, and what this caller may press.
        "archived_at",
        "archived_by",
        "allowed_acts",
        # The rest of the family: the version the next write names, where it
        # lives in words, and who owns it in words (null when the user model
        # has no name to give).
        "version",
        "organization_name",
        "owner_name",
        # The copy it was made from, the widget a merge made it into, and the id
        # an import finds it by.
        "duplicated_from_id",
        "merged_into_id",
        "external_ref",
    }
)

# The DETAIL answers the row and the words on it: `tags`, read through the tags
# app, on the record alone — a list's row and an event's payload are the row.
DETAIL_KEYS = WIDGET_KEYS | {"tags"}

# Any GET through the CSRF middleware leaves the cookie behind; the admin login
# page is the one page in this tree that is always mounted and always renders a
# form. Nothing about the admin is under test here — it is a source of a real,
# server-issued CSRF token, which is the only kind worth asserting against.
CSRF_SOURCE_URL = "/admin/login/"


def strict_client() -> Client:
    """A client that enforces CSRF, which the shared `api` fixture does not."""
    return Client(enforce_csrf_checks=True)


def csrf_token(client: Client) -> str:
    """A real CSRF token for this client, issued by the server."""
    client.get(CSRF_SOURCE_URL)
    return str(client.cookies[settings.CSRF_COOKIE_NAME].value)


def test_a_bearer_write_needs_no_csrf_material(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The machine door, over the wire: a token, a POST, a row. No cookie.

    This is the verifier's exact request. Pre-fix it was 403 "CSRF check
    Failed", because `SessionAuth` ran first and raised before `ApiTokenAuth`
    was ever called.
    """
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="over-the-wire", actor=actor_for(user=owner, tenant=tenant)
    )

    response = strict_client().post(
        LIST_URL,
        data=json.dumps({"name": "Minted by a machine"}),
        content_type=JSON,
        headers={"authorization": f"Bearer {plaintext}"},
    )

    assert response.status_code == 201, response.content
    assert Widget.objects.for_tenant(tenant).filter(name="Minted by a machine").exists()


def test_a_session_write_without_a_csrf_token_is_refused(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The human door keeps the whole of CSRF; nothing here was loosened."""
    client = strict_client()
    client.force_login(owner)

    response = client.post(
        LIST_URL,
        data=json.dumps({"name": "Forged"}),
        content_type=JSON,
    )

    assert response.status_code == 403, response.content
    assert not Widget.objects.for_tenant(tenant).filter(name="Forged").exists()


def test_a_session_write_with_a_csrf_token_is_allowed(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The other half of the same property: the browser that plays by the rules."""
    client = strict_client()
    client.force_login(owner)
    token = csrf_token(client)

    response = client.post(
        LIST_URL,
        data=json.dumps({"name": "Minted by a person"}),
        content_type=JSON,
        headers={"x-csrftoken": token},
    )

    assert response.status_code == 201, response.content
    assert Widget.objects.for_tenant(tenant).filter(name="Minted by a person").exists()


# --- Door parity, on the wire -------------------------------------------------


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """One JSON-RPC request body, spelled the way a real MCP client spells it."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="door-parity", actor=actor_for(user=owner, tenant=tenant)
    )
    return plaintext


@pytest.fixture
def widget(tenant: Tenant, owner_actor: Actor, recorded_workflow_starts: None) -> Widget:
    """One committed row for both doors to answer with.

    Built through the service rather than the manager, so it has the owner and
    the organization every read shape walks. `recorded_workflow_starts` because
    the commit is real in a `transaction=True` test, so `create_widget`'s
    on-commit hook would otherwise dial a Temporal server this test has no
    reason to start — the onboarding run is proved in `test_workflows.py`.
    """
    return create_widget(tenant=tenant, actor=owner_actor, name="Twin", notes="hello")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_key_set_on_the_wire(bearer: str, widget: Widget) -> None:
    """The same row, fetched over HTTP and over JSON-RPC: one key set, not two.

    The assertion is on the **keys**, deliberately and by itself. Values were
    never the disagreement — `owner.email` and `owner_email` carried the same
    string — so a test that compared values passed while the two doors described
    the same row in two vocabularies. Comparing the key sets is the assertion
    that could have failed on the day the alias landed.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(widget.pk), headers={**bearer_header, "accept": JSON}
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
                        "clientInfo": {"name": "door-parity", "version": "1"},
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
                    {"name": "get_widget", "arguments": {"widget_id": str(widget.pk)}},
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
    # direction that breaks a client (E1).
    assert set(rest_body) == DETAIL_KEYS

    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same widget with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "A `Field(alias=...)` on a read schema does this: the MCP transport "
        "serialises `structuredContent` by alias and REST renders by field "
        "name. Resolve a relation with a model property, not an alias "
        "(ADR example-3; `apps/comms/models.py` is the precedent)."
    )


# The measured-number shape, as a key set at both levels — written out rather
# than derived from `MeasuredOut`, for the same reason `WIDGET_KEYS` is: a pin
# derived from the thing it pins cannot fail. This is `Measured`'s wire contract
# (ADR core-7), and a product that adds a third key to a basis has to change
# this line where a reviewer sees it.
STATS_KEYS = frozenset({"count"})
MEASURED_KEYS = frozenset({"value", "basis"})
BASIS_KEYS = frozenset({"formula", "inputs"})


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_agree_on_a_measured_number_and_its_basis(
    bearer: str, widget: Widget
) -> None:
    """`/widgets/stats/` and `get_widget_stats`: one shape, one value, one basis.

    Three claims, and each of them is a different way the contract could rot:

    1. **The shape is `Measured`**, at both levels — a value and a basis, and a
       basis that is a formula and its inputs. A number that arrived naked would
       satisfy any test that only compared the two doors to each other.
    2. **The two doors put the same thing on the wire**, key for key and value
       for value. This is the alias-mismatch lesson applied to an aggregate: the two
       doors share `widget_stats`, so this asserts that the sharing survives
       serialization, which is where the doors have actually disagreed before.
    3. **The basis is honest** — the value is recomputed from the inputs by this
       test, using the formula the server sent, and has to match. That is the
       assertion that makes the basis a contract instead of decoration: a server
       that shipped `value=7` beside inputs summing to 6 fails here.

    `transaction=True` because the MCP transport runs a tool body on a worker
    thread with its own connection, which cannot see an uncommitted row.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(STATS_URL, headers={**bearer_header, "accept": JSON})
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
                        "clientInfo": {"name": "stats-parity", "version": "1"},
                    },
                    1,
                ),
            )
            assert initialize.status_code == 200, initialize.text

            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc("tools/call", {"name": "get_widget_stats", "arguments": {}}, 2),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    # (1) the shape, against the written-out contract.
    assert set(rest_body) == STATS_KEYS
    assert set(rest_body["count"]) == MEASURED_KEYS
    assert set(rest_body["count"]["basis"]) == BASIS_KEYS

    # (2) the two doors. The key sets first, because that is what actually
    # diverged the last time and because an equality failure on nested
    # dicts says less than a key-set failure does.
    assert set(over_mcp) == set(rest_body)
    assert set(over_mcp["count"]) == set(rest_body["count"])
    assert set(over_mcp["count"]["basis"]) == set(rest_body["count"]["basis"])
    # Then the whole structure, verbatim. It is asserted at this strength
    # because the two doors *can* meet it: `Decimal` renders as a string on both
    # sides — pydantic's JSON mode and ninja's encoder agree — so there is no
    # float to be tolerant about and no reason to compare leniently.
    assert over_mcp == rest_body
    assert rest_body["count"]["value"] == "1", "a Decimal on the wire is a string, not a float"

    # (3) the basis is honest: recompute the value from the inputs the server
    # sent, using the formula it sent, and require the two to agree.
    basis = rest_body["count"]["basis"]
    assert basis["formula"] == "onboarded + pending"
    recomputed = sum(Decimal(str(value)) for value in basis["inputs"].values())
    assert recomputed == Decimal(str(rest_body["count"]["value"]))
    # And the one row this fixture made is really in there, so the agreement
    # above is not two doors agreeing on zero.
    assert recomputed == Decimal(1)


# --- 3 · the read refusal, on both doors, in the same words --------------------


@pytest.fixture
def member_bearer(tenant: Tenant, member: User) -> str:
    """A real token for the plain member — the credential both doors accept."""
    _, plaintext = issue_token(
        user=member,
        tenant=tenant,
        name="read-parity",
        actor=actor_for(user=member, tenant=tenant),
    )
    return plaintext


@pytest.fixture
def withheld_widget_read(tenant: Tenant, member: User) -> str:
    """A committed `withhold` of `widget.read` on the member, and its sentence.

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
        permission="widget.read",
        effect=Grant.Effect.WITHHOLD,
    )
    return refusal_sentence("widget.read")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_the_same_withheld_read_with_the_same_words(
    member_bearer: str, withheld_widget_read: str, widget: Widget
) -> None:
    """House rule 46, applied to the read gate Phase R added (PR4.a.2).

    `test_the_two_doors_put_the_same_key_set_on_the_wire` above proves the two
    doors agree when they ANSWER. This proves they agree when they REFUSE, which
    is the half a parity test over happy paths cannot see — and refusals are
    where the doors have the most room to drift, because each has its own error
    envelope and neither shares the other's.

    The withheld key is `widget.read`, written as a raw `Grant` row on the
    member's own membership; the sentence both doors must speak is
    `refusal_sentence("widget.read")`, which is derived from the key rather than
    typed here, so a product that gives the key its own prose moves both doors at
    once or fails here.

    `transaction=True`, as everything in section 2 is: the MCP transport runs a
    tool body on a worker thread with its own connection, which cannot see an
    uncommitted `Grant`.
    """
    from config.asgi import build_application

    sentence = withheld_widget_read
    application = build_application()
    bearer_header = {"authorization": f"Bearer {member_bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(widget.pk), headers={**bearer_header, "accept": JSON}
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
                    {"name": "get_widget", "arguments": {"widget_id": str(widget.pk)}},
                    2,
                ),
            )

    # The human door: a row INSIDE the hat's subtree, refused by capability and
    # not hidden — 404 there would say "no such widget", which is false and is
    # the answer the scoping gives for a row in a branch you cannot reach.
    assert over_http.status_code == 403, over_http.text
    body = over_http.json()
    assert body["code"] == "forbidden"
    assert body["detail"] == sentence

    # The machine door: the same code and the same sentence, rendered through
    # `wire_refusal`. Compared as text because a tool error is text on the wire
    # — what matters is that the words a refused agent reads are the words a
    # refused person reads.
    answered = called.json()
    rendered = json.dumps(answered)
    assert "forbidden" in rendered, rendered
    assert sentence in rendered, rendered


# --- 4 · the 401, on both doors, in the same words ----------------------------

# The sentence a presented-but-unresolvable bearer reads, written out rather
# than imported from the door: a pin derived from the thing it pins cannot fail,
# the reason `WIDGET_KEYS` above is written out. It is wire contract — the first
# refusal most integrators ever meet.
BEARER_NOT_VALID = "That bearer token is not valid."


@pytest.fixture
def revoked_bearer(tenant: Tenant, owner: User) -> str:
    """A real token for a real person, withdrawn — and still in the caller's hand.

    Through the services, so the state both doors meet is the state a revocation
    really leaves; committed in a fixture, because the MCP transport runs on a
    worker thread with its own connection and the revocation has to be visible
    to it.
    """
    actor = actor_for(user=owner, tenant=tenant)
    token, plaintext = issue_token(user=owner, tenant=tenant, name="withdrawn", actor=actor)
    revoke_token(token=token, tenant=tenant, actor=actor)
    return plaintext


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_one_revoked_token_with_the_same_code_and_sentence(
    revoked_bearer: str,
) -> None:
    """House rule 46 at the door's own refusal, which has no principal behind it.

    The two other parity cases in this module need a caller the doors have
    identified. This one needs the opposite: the same string presented as a
    bearer at both doors, refused by both, and the two refusals compared on the
    two fields a client consumes — `code`, which it branches on, and `detail`,
    which it reads.

    `remedies` is deliberately NOT compared. The remedies are the DOOR's (E9):
    `/mcp` reads `Authorization` and nothing else, so it drops the remedy that
    sends a caller to sign in and REST — which honours a session — keeps it.
    Asserting equality there would pin the two doors to a promise one of them
    cannot keep, which is the defect the MCP door's own remedy test closes.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {revoked_bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(LIST_URL, headers={**bearer_header, "accept": JSON})
            over_mcp = await client.post(
                MCP_URL,
                headers={**MCP_HEADERS, **bearer_header},
                json=_rpc("tools/list", {}, 1),
            )

    assert over_http.status_code == 401, over_http.text
    assert over_mcp.status_code == 401, over_mcp.text
    rest_body = over_http.json()
    mcp_body = over_mcp.json()

    assert rest_body["code"] == mcp_body["code"] == "unauthenticated", (rest_body, mcp_body)
    assert rest_body["detail"] == mcp_body["detail"] == BEARER_NOT_VALID, (rest_body, mcp_body)


# --- One press, three tellings ------------------------------------------------


async def _mcp_call(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """`initialize`, then one `tools/call`; the result's `structuredContent`."""
    initialize = await client.post(
        MCP_URL,
        headers=headers,
        json=_rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "door-parity", "version": "1"},
            },
            1,
        ),
    )
    assert initialize.status_code == 200, initialize.text
    called = await client.post(
        MCP_URL, headers=headers, json=_rpc("tools/call", {"name": name, "arguments": arguments}, 2)
    )
    assert called.status_code == 200, called.text
    answered = called.json()
    assert "error" not in answered, answered
    assert not answered["result"].get("isError"), answered
    content: dict[str, Any] = answered["result"]["structuredContent"]
    return content


def _canonical(body: dict[str, Any]) -> str:
    """One byte string per body: sorted keys, the door's own separators."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _event_payload(tenant: Tenant, name: str) -> dict[str, Any]:
    """The outbox row's payload for the one event of this name, minus the spine's `v`.

    `v` is the envelope's payload version, which `events.emit` adds to every
    payload it records (a subscriber branches on it); it is not a field of the
    widget, so it is the one key the comparison sets aside — and says so here.
    """
    from django.apps import apps as django_apps

    outbox = django_apps.get_model("events", "Outbox")
    rows = list(
        outbox.objects.filter(event__tenant=tenant, event__name=name).select_related("event")
    )
    assert len(rows) == 1, [row.event.name for row in rows]
    payload: dict[str, Any] = dict(rows[0].event.payload)
    assert "v" in payload
    payload.pop("v")
    return payload


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["archive", "restore"])
async def test_one_press_is_one_body_on_rest_mcp_and_the_outbox(
    bearer: str, widget: Widget, tenant: Tenant, member: User, verb: str
) -> None:
    """M4: one viewer's REST and MCP answers are one byte string; the event is the row.

    REST presses first and changes the row (one event); MCP presses the same
    verb second, which is the idempotent repeat — the same row, unchanged, and
    no second event. So all three describe one state of one row, and any
    difference between them is a door disagreeing about the shape, not the
    data. For `restore` the widget is archived through the service first.

    **An event payload never carries a per-viewer field.** `allowed_acts` is
    what THIS caller may press; a webhook subscriber and every socket listener
    are other viewers, so the payload is the viewer's answer MINUS its acts. A
    second viewer (a member) reading the same row differs from the presser in
    `allowed_acts` and in nothing else — which is what makes the field
    per-viewer, and why it cannot ride the event.
    """
    from asgiref.sync import sync_to_async

    from apps.core.actor import actor_for
    from apps.example.services import archive_widget
    from config.asgi import build_application

    if verb == "restore":
        owner = await sync_to_async(lambda: widget.owner)()
        await sync_to_async(archive_widget)(
            tenant=tenant,
            actor=actor_for(
                user=owner, tenant=tenant, org=await sync_to_async(lambda: widget.organization)()
            ),
            widget=widget,
        )

    member_bearer = await sync_to_async(_token_for)(member, tenant)
    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.post(
                f"{LIST_URL}{widget.pk}/{verb}/", headers={**bearer_header, "accept": JSON}
            )
            assert over_http.status_code == 200, over_http.text
            over_mcp = await _mcp_call(
                client,
                {**MCP_HEADERS, **bearer_header},
                f"{verb}_widget",
                {"widget_id": str(widget.pk)},
            )
            as_member = await client.get(
                f"{LIST_URL}{widget.pk}/",
                headers={"authorization": f"Bearer {member_bearer}", "accept": JSON},
            )
            assert as_member.status_code == 200, as_member.text

    rest_body: dict[str, Any] = over_http.json()
    member_body: dict[str, Any] = as_member.json()
    event = await sync_to_async(_event_payload)(tenant, f"example.widget.{verb}d")
    assert set(rest_body) == WIDGET_KEYS
    assert (verb == "archive") == (rest_body["archived_at"] is not None)
    assert rest_body["allowed_acts"], rest_body

    # One viewer, two doors: one byte string.
    assert _canonical(over_mcp) == _canonical(rest_body)
    # The event is the row, never a viewer's acts.
    assert "allowed_acts" not in event, sorted(event)
    assert _canonical(event) == _canonical(_without_acts(rest_body))
    # A second viewer: the same row, other acts — and nothing else different.
    # The member read the DETAIL, which answers the row and the words on it;
    # the press answered the row.
    assert member_body.pop("tags") == []
    assert _canonical(_without_acts(member_body)) == _canonical(_without_acts(rest_body))
    assert member_body["allowed_acts"] != rest_body["allowed_acts"]
    assert not {"archive", "restore"} & set(member_body["allowed_acts"])


def _without_acts(body: dict[str, Any]) -> dict[str, Any]:
    """The row as every viewer sees it: the body minus this viewer's acts."""
    return {key: value for key, value in body.items() if key != "allowed_acts"}


def _token_for(user: User, tenant: Tenant) -> str:
    """A real bearer token for a second viewer of the same tenant."""
    _, plaintext = issue_token(
        user=user, tenant=tenant, name="second-viewer", actor=actor_for(user=user, tenant=tenant)
    )
    return plaintext


# --- 5 · The rest of the family, on both doors and the outbox (M4) --------------
#
# One presser (the owner's bearer) presses each verb on REST first and then the
# same press on MCP, which is the idempotent repeat — nothing to change, no
# second event — so the two bodies describe one state of one row and must be one
# byte string. The event is that row minus the viewer's acts (and, for a move,
# plus the one key that is true of the EVENT: the node it left). A SECOND viewer
# — the tenant's plain member — reads the same row and differs in `allowed_acts`
# and nothing else.


@pytest.fixture
def branch(tenant: Tenant, owner: User) -> Any:
    from apps.core.services import create_organization, root_organization

    root = root_organization(tenant=tenant)
    return create_organization(
        tenant=tenant,
        parent=root,
        name="Branch",
        slug="branch",
        actor=actor_for(user=owner, tenant=tenant, org=root),
    )


def _one_event(tenant: Tenant, name: str) -> dict[str, Any]:
    return _event_payload(tenant, name)


async def _press(
    client: httpx.AsyncClient,
    bearer_header: dict[str, str],
    verb: str,
    widget_id: str,
    version: int,
    branch_id: str,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    """The REST press, and the MCP press that repeats it: (REST response, REST body, MCP body)."""
    headers = {**bearer_header, "accept": JSON}
    mcp_headers = {**MCP_HEADERS, **bearer_header}
    if verb == "update":
        rest = await client.patch(
            f"{LIST_URL}{widget_id}/", headers=headers, json={"name": "Pressed", "version": version}
        )
        body = rest.json()
        # The repeat names the version REST answered and sends nothing to change.
        mcp = await _mcp_call(
            client,
            mcp_headers,
            "update_widget",
            {"widget_id": widget_id, "version": body["version"]},
        )
    elif verb == "move":
        rest = await client.post(
            f"{LIST_URL}{widget_id}/move/",
            headers=headers,
            json={"organization_id": branch_id, "version": version},
        )
        body = rest.json()
        mcp = await _mcp_call(
            client,
            mcp_headers,
            "move_widget",
            {"widget_id": widget_id, "organization_id": branch_id, "version": body["version"]},
        )
    elif verb == "bulk":
        rest = await client.post(
            f"{LIST_URL}bulk/", headers=headers, json={"verb": "archive", "ids": [widget_id]}
        )
        body = rest.json()
        mcp = await _mcp_call(
            client, mcp_headers, "bulk_widgets", {"verb": "archive", "ids": [widget_id]}
        )
    else:
        rest = await client.get(f"{LIST_URL}{widget_id}/history/", headers=headers)
        body = rest.json()
        mcp = await _mcp_call(client, mcp_headers, "list_widget_history", {"widget_id": widget_id})
    return rest, body, mcp


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["update", "move", "bulk", "history"])
async def test_each_family_verb_is_one_body_on_rest_mcp_and_the_outbox(
    bearer: str, widget: Widget, tenant: Tenant, member: User, branch: Any, verb: str
) -> None:
    from asgiref.sync import sync_to_async

    from config.asgi import build_application

    version = await sync_to_async(lambda: widget.version)()
    member_bearer = await sync_to_async(_token_for)(member, tenant)
    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            rest, rest_body, over_mcp = await _press(
                client, bearer_header, verb, str(widget.pk), version, str(branch.pk)
            )
            assert rest.status_code == 200, rest.text
            as_owner = await client.get(
                f"{LIST_URL}{widget.pk}/", headers={**bearer_header, "accept": JSON}
            )
            as_member = await client.get(
                f"{LIST_URL}{widget.pk}/",
                headers={"authorization": f"Bearer {member_bearer}", "accept": JSON},
            )
            assert as_member.status_code == 200, as_member.text

    # One viewer, two doors: one byte string. The bulk repeat is the idempotent
    # one, so its outcome reads `unchanged` where REST's read `done`, and
    # nothing else about the batch may differ.
    if verb == "bulk":
        assert [r["outcome"] for r in rest_body["results"]] == ["done"]
        assert [r["outcome"] for r in over_mcp["results"]] == ["unchanged"]
        repeated = {
            **rest_body,
            "done": 0,
            "unchanged": 1,
            "results": [{**rest_body["results"][0], "outcome": "unchanged"}],
        }
        assert _canonical(over_mcp) == _canonical(repeated)
        row = rest_body["results"][0]["item"]
    else:
        assert _canonical(over_mcp) == _canonical(rest_body)
        row = rest_body if verb != "history" else as_owner.json()

    # The event is the row, never a viewer's acts.
    said = {
        "update": "example.widget.updated",
        "move": "example.widget.moved",
        "bulk": "example.widget.archived",
    }.get(verb)
    if said is not None:
        event = await sync_to_async(_one_event)(tenant, said)
        assert "allowed_acts" not in event, sorted(event)
        if verb == "move":
            assert event.pop("from_organization_id") == str(widget.organization_id)
            assert event["organization_id"] == str(branch.pk)
        assert _canonical(event) == _canonical(_without_acts(row))

    # A second viewer: the same row, other acts — and nothing else different.
    owner_body = as_owner.json()
    member_body = as_member.json()
    assert set(owner_body) == DETAIL_KEYS
    assert _canonical(_without_acts(member_body)) == _canonical(_without_acts(owner_body))
    assert member_body["allowed_acts"] != owner_body["allowed_acts"]


@pytest.fixture
def branch_admin_bearer(tenant: Tenant, owner: User) -> tuple[str, list[str]]:
    """A token for an ADMIN at A in a root/A/A1/B world, and the ids of A and A1."""
    from apps.accounts.services import create_user
    from apps.core.actor import system_actor
    from apps.core.models import Membership
    from apps.core.services import add_membership, create_organization, root_organization

    root = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=acting)
    create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=acting)
    a1 = create_organization(tenant=tenant, parent=a, name="A1", slug="a1", actor=acting)
    manager = create_user(email="a-admin@example.com", password=PASSWORD)
    add_membership(
        user=manager,
        tenant=tenant,
        organization=a,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return _token_for(manager, tenant), sorted([str(a.pk), str(a1.pk)])


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_move_sheets_destinations_agree_on_both_doors(
    branch_admin_bearer: tuple[str, list[str]],
) -> None:
    """`?can=widget.move` and `list_organizations(can="widget.move")`: A and A1, on both."""
    from config.asgi import build_application

    token, expected = branch_admin_bearer
    header = {"authorization": f"Bearer {token}"}
    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                "/api/v1/organizations/",
                params={"can": "widget.move"},
                headers={**header, "accept": JSON},
            )
            assert over_http.status_code == 200, over_http.text
            over_mcp = await _mcp_call(
                client, {**MCP_HEADERS, **header}, "list_organizations", {"can": "widget.move"}
            )

    assert sorted(row["id"] for row in over_http.json()["items"]) == expected
    assert sorted(row["id"] for row in over_mcp["items"]) == expected


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_partial_bulk_answers_the_same_three_outcomes_on_the_machine_door(
    tenant: Tenant, owner: User, recorded_workflow_starts: None
) -> None:
    """`bulk_widgets`: done, refused(`not_found`), done — as `POST /widgets/bulk/` answers."""
    from asgiref.sync import sync_to_async

    from apps.core.services import create_organization, root_organization
    from config.asgi import build_application

    def world() -> tuple[str, list[str]]:
        from apps.accounts.services import create_user
        from apps.core.actor import system_actor
        from apps.core.models import Membership
        from apps.core.services import add_membership

        root = root_organization(tenant=tenant)
        acting = actor_for(user=owner, tenant=tenant, org=root)
        a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=acting)
        b = create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=acting)
        manager = create_user(email="a-admin@example.com", password=PASSWORD)
        add_membership(
            user=manager,
            tenant=tenant,
            organization=a,
            is_default=True,
            role=Membership.Role.ADMIN,
            actor=system_actor(tenant=tenant),
        )
        ids = [
            str(
                create_widget(
                    tenant=tenant, actor=actor_for(user=owner, tenant=tenant, org=node), name=name
                ).pk
            )
            for node, name in ((a, "first"), (b, "sibling"), (a, "third"))
        ]
        return _token_for(manager, tenant), ids

    token, ids = await sync_to_async(world)()
    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            answered = await _mcp_call(
                client,
                {**MCP_HEADERS, "authorization": f"Bearer {token}"},
                "bulk_widgets",
                {"verb": "archive", "ids": ids},
            )

    assert [r["outcome"] for r in answered["results"]] == ["done", "refused", "done"]
    assert [r["id"] for r in answered["results"]] == ids
    assert answered["results"][1]["refusal"]["code"] == "not_found"


# --- 6 · Duplicate and merge: one press, four tellings (M4) ----------------------
#
# `assert_four_doors` holds one presser's REST body and MCP `structuredContent`
# to one byte string, the recorded payload to the row minus its per-viewer
# fields, and no per-viewer key in the payload. REST presses first; MCP repeats
# the press — a duplicate with the same key answers the FIRST copy, a merge of
# the same pair answers the survivor unchanged — so all four describe one state
# of one row. A SECOND viewer (the tenant's member) reads the same row's detail
# and differs from the presser's detail in `allowed_acts` and nothing else.


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize("verb", ["duplicate", "merge"])
async def test_duplicate_and_merge_are_one_row_on_four_doors_for_two_viewers(
    bearer: str, widget: Widget, tenant: Tenant, owner: User, member: User, verb: str
) -> None:
    from asgiref.sync import sync_to_async

    from apps.core.tests.doors import assert_four_doors
    from config.asgi import build_application

    def survivor_and_versions() -> tuple[str, int, int]:
        into = create_widget(
            tenant=tenant,
            actor=actor_for(user=owner, tenant=tenant, org=widget.organization),
            name="Survivor",
        )
        return str(into.pk), Widget.objects.get(pk=widget.pk).version, into.version

    into_id, version, into_version = (
        await sync_to_async(survivor_and_versions)() if verb == "merge" else ("", 0, 0)
    )
    member_bearer = await sync_to_async(_token_for)(member, tenant)
    header = {"authorization": f"Bearer {bearer}"}
    application = build_application()
    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            if verb == "duplicate":
                rest = await client.post(
                    f"{LIST_URL}{widget.pk}/duplicate/",
                    headers={**header, "accept": JSON, "idempotency-key": "m4-press"},
                )
                assert rest.status_code == 201, rest.text
                over_mcp = await _mcp_call(
                    client,
                    {**MCP_HEADERS, **header},
                    "duplicate_widget",
                    {"widget_id": str(widget.pk), "idempotency_key": "m4-press"},
                )
            else:
                rest = await client.post(
                    f"{LIST_URL}{widget.pk}/merge/",
                    headers={**header, "accept": JSON},
                    json={"into_id": into_id, "version": version, "into_version": into_version},
                )
                assert rest.status_code == 200, rest.text
                over_mcp = await _mcp_call(
                    client,
                    {**MCP_HEADERS, **header},
                    "merge_widget",
                    {
                        "widget_id": str(widget.pk),
                        "into_id": into_id,
                        "version": version,
                        "into_version": into_version,
                    },
                )
            row_id = rest.json()["id"]
            as_owner = await client.get(f"{LIST_URL}{row_id}/", headers={**header, "accept": JSON})
            as_member = await client.get(
                f"{LIST_URL}{row_id}/",
                headers={"authorization": f"Bearer {member_bearer}", "accept": JSON},
            )
            assert as_member.status_code == 200, as_member.text

    payload = await sync_to_async(_event_payload)(tenant, f"example.widget.{verb}d")
    if verb == "merge":
        # What is true of the EVENT and not of the row: the widget folded away
        # and what each owning app moved.
        assert payload.pop("loser_id") == str(widget.pk)
        repoints = payload.pop("repoints")
        assert {row["title"]: row["left"] for row in repoints} == {
            "Notes": 0,
            "Tags": 0,
            "Files": 0,
        }
    assert_four_doors(rest=rest.json(), mcp=over_mcp, event_payload=payload)
    # The second viewer: the same row, other acts — and nothing else different.
    owner_body, member_body = as_owner.json(), as_member.json()
    assert set(owner_body) == DETAIL_KEYS
    assert _canonical(_without_acts(member_body)) == _canonical(_without_acts(owner_body))
    assert member_body["allowed_acts"] != owner_body["allowed_acts"]
