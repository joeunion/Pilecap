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
from apps.accounts.services import issue_token
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
    }
)

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
    assert set(rest_body) == WIDGET_KEYS

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
