"""One search, answered by both doors, compared ON THE WIRE.

House rule 46: every door pair an app has owes a parity test in that app.
`apps/search` has a REST door and an MCP door, so it owes `(rest, mcp)`, and
this module is the answer. **The pair is declared HERE rather than beside the adoption**: the
two doors are born together, and a parity test that arrived later
would leave a window in which the doors could have drifted.

**Why a registry diff is not this.** House rule 17 proves a capability exists on
both doors; it cannot see the two doors *disagree* about one. Both times they
did in this tree, both registries were complete: one case (REST renders by field
name, the MCP transport renders `structuredContent` by **alias**) and another (two
credentials, two different sets of frames). Neither is visible to a diff of two
registries.

**Search is the pair where this matters most**, and it is worth saying why: the
envelope is shared with every other list door, the hits are a nested list rather
than a flat row, and `engine` is a field only this app has. A nested list is
exactly where a serialiser difference hides — the outer keys can match perfectly
while the inner ones do not — so the comparison below descends into `items`
rather than stopping at the envelope.

`transaction=True` because the MCP transport runs a tool body on a worker thread
with its own database connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import pytest

from apps.accounts.services import issue_token
from apps.core.actor import actor_for

# The transport harness, from the module that owns it. Copying it here would be
# a second thing to keep in step with the MCP protocol version.
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.search import engine as engine_module
from apps.search import registry
from apps.search.types import EngineHit, RecordingEngine

from .conftest import WIDGETS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.models import Tenant

#: House rule 46. The door pair this module answers for `apps/search`, read by
#: the gate off this module-level assignment.
DOOR_PAIR = ("rest", "mcp")

SEARCH_URL = "/api/v1/search/"
KINDS_URL = "/api/v1/search/kinds/"
MCP_URL = "/mcp"
JSON = "application/json"

#: `SearchPage`'s wire contract, written out rather than derived from the schema.
#: A pin derived from the thing it pins cannot fail; this one fails the day
#: somebody adds a field, which is when a reviewer should be looking.
PAGE_KEYS = frozenset({"items", "has_more", "next_cursor", "count", "engine"})

#: And one hit's.
HIT_KEYS = frozenset({"kind", "id", "label", "rank"})

#: `SearchKindPage`'s, written out for the same reason: a page of the vocabulary
#: is the plain list envelope and has no `engine`, because nothing answered it.
KIND_PAGE_KEYS = frozenset({"items", "has_more", "next_cursor", "count"})


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """One JSON-RPC request body, spelled the way a real MCP client spells it."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def test_the_route_is_mounted_where_its_url_name_says() -> None:
    """The route's own handle, reversed rather than spelled.

    House rule 3's diff layer asks a new route for a test that names its
    `url_name`, and the reason is the one every other constant in this
    repository has: the literal path in the tests above would go on passing
    against a route that had quietly moved, and `reverse` would not. It also
    pins the resource-first mount (house rule 32's declared coincidence): the
    path is `/api/v1/search/` and not `/api/v1/search/search/`.
    """
    from django.urls import reverse

    assert reverse("api:search-query") == SEARCH_URL


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="search-door-parity",
        actor=actor_for(user=owner, tenant=tenant),
    )
    return plaintext


@pytest.fixture
def hatless_bearer(nomad: Any) -> str:
    """A real token for somebody who belongs to no account at all.

    A fixture rather than a line in the test, because minting one touches the
    database and these tests are `async`: a synchronous ORM call inside an async
    function is `SynchronousOnlyOperation`, and a fixture runs on the
    synchronous side where it belongs.
    """
    _, plaintext = issue_token(
        user=nomad, tenant=None, name="hatless-parity", actor=actor_for(user=nomad, tenant=None)
    )
    return plaintext


@pytest.fixture
def two_hits(monkeypatch: pytest.MonkeyPatch) -> RecordingEngine:
    """A declared kind and an engine holding two hits, for both doors to render.

    Two rather than one, because `items` is a list and a list of length one is
    the length at which an ordering difference cannot show.
    """
    monkeypatch.setattr(registry, "declarations", lambda: (WIDGETS,))
    engine = RecordingEngine(
        hits=(
            EngineHit(kind="widgets", id=uuid4(), label="Left-handed sprocket", rank=2.0),
            EngineHit(kind="widgets", id=uuid4(), label="Right-handed sprocket", rank=1.0),
        ),
        total=2,
    )
    monkeypatch.setattr(engine_module, "engine", lambda: engine)
    return engine


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_page_on_the_wire(
    bearer: str, root_org: Any, two_hits: RecordingEngine
) -> None:
    """The same query over HTTP and over JSON-RPC: one key set, one set of values.

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
                SEARCH_URL,
                params={"q": "sprocket", "kinds": "widgets", "include_count": "true"},
                headers={**bearer_header, "accept": JSON},
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
                        "clientInfo": {"name": "search-door-parity", "version": "1"},
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
                    {
                        "name": "search_query",
                        "arguments": {
                            "q": "sprocket",
                            "kinds": "widgets",
                            "include_count": True,
                        },
                    },
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
    assert set(rest_body) == PAGE_KEYS
    assert rest_body["count"] == 2
    assert len(rest_body["items"]) == 2

    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same page with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "A `Field(alias=...)` on a read schema does this: the MCP transport "
        "serialises `structuredContent` by alias and REST renders by field name."
    )
    assert over_mcp == rest_body, "the two doors disagree about the page's values"

    # And INSIDE the list, which is where a nested-serialiser difference hides.
    for rest_hit, mcp_hit in zip(rest_body["items"], over_mcp["items"], strict=True):
        assert set(rest_hit) == HIT_KEYS
        assert set(mcp_hit) == HIT_KEYS
        assert rest_hit == mcp_hit


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_publish_the_same_vocabulary(
    bearer: str, root_org: Any, two_hits: RecordingEngine
) -> None:
    """The second pair, compared the same way: `GET /search/kinds/` and its tool.

    Rule 46 is about a PAIR and not about a door, so the pair that arrived with
    the vocabulary route owes what the first pair owes. It matters more here than it looks: the
    machine door is the caller most likely to invent a kind name, so this is the
    read an assistant makes to stop guessing, and a vocabulary the two doors
    described differently would send the two callers to different products.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                KINDS_URL,
                params={"include_count": "true"},
                headers={**bearer_header, "accept": JSON},
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
                        "clientInfo": {"name": "search-kinds-parity", "version": "1"},
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
                    {"name": "list_search_kinds", "arguments": {"include_count": True}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(rest_body) == KIND_PAGE_KEYS
    assert rest_body["items"] == [{"kind": "widgets", "app": "example"}]
    assert rest_body["count"] == 1

    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the vocabulary with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}."
    )
    assert over_mcp == rest_body, "the two doors disagree about the vocabulary"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_an_unknown_kind_with_the_same_sentence(
    bearer: str, root_org: Any, two_hits: RecordingEngine
) -> None:
    """The unknown-kind refusal, on both doors, from the one composer.

    The MCP transport has no status codes, so the comparison is what a caller
    actually branches on: the code leads the tool's message, and the sentence
    the two doors say about which kinds exist is the same sentence. A door pair
    that agreed about results and disagreed about a refusal is exactly the drift
    rule 46 exists to catch — and this is the refusal a machine caller is most
    likely to hit, because it is the one an invented kind name produces.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}
    arguments = {"q": "sprocket", "kinds": "definitely-not-a-kind"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                SEARCH_URL, params=arguments, headers={**bearer_header, "accept": JSON}
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
                        "clientInfo": {"name": "search-refusal-parity", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc("tools/call", {"name": "search_query", "arguments": arguments}, 2),
            )

    assert over_http.status_code == 400, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "invalid"

    answered = called.json()
    rendered = str(answered)
    assert "invalid" in rendered
    assert "definitely-not-a-kind" in rendered
    assert rest_body["errors"]["kinds"][0] in rendered, (
        "the machine door says something different about an unknown kind than the "
        "HTTP door does — both render `wire_refusal` through the one composer"
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_caller_with_no_account_is_refused_at_the_door(
    hatless_bearer: str, two_hits: RecordingEngine
) -> None:
    """The refusal half of the pair — the half a caller has to branch on.

    A door pair can agree perfectly about the happy path and disagree about a
    refusal, and this is where the HTTP door's answer is pinned: a real
    credential belonging to nobody's account is `403 forbidden`, in the one
    envelope, and never a page of results and never a 500.
    """
    from config.asgi import build_application

    application = build_application()
    headers = {"authorization": f"Bearer {hatless_bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                SEARCH_URL, params={"q": "sprocket"}, headers={**headers, "accept": JSON}
            )

    # A caller with no tenant is refused before the selector, by the door — the
    # same refusal every other door in this product gives them.
    assert over_http.status_code == 403, over_http.text
    assert over_http.json()["code"] == "forbidden"


@pytest.fixture
def widget_read_withheld(tenant: Tenant, owner: User) -> Any:
    """One `withhold` row on the owner's own membership. **`widget.read`, gone.**

    A withhold beats everything — "forbid overrides permit" — and it beats it
    for an owner too, which is what makes this the smallest world in which an
    ordinary credential is refused a named kind at both doors. Nothing about the
    role, the hat or the declaration changes: the only difference between this
    test and its neighbours is this row.
    """
    from apps.core.models import Grant, Membership

    membership = Membership.objects.filter(tenant=tenant).get(user=owner)
    return Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="widget.read",
        effect=Grant.Effect.WITHHOLD,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_the_same_withheld_read_with_the_same_words(
    bearer: str, root_org: Any, two_hits: RecordingEngine, widget_read_withheld: Any
) -> None:
    """**PR4.g.2 — rule 46's named case for Phase R.**

    A read is a permission now (ADR core-27), so `?kinds=widgets` from somebody
    who may not read widgets is a NEW refusal — and a new refusal is exactly
    where two doors come apart, because one composes a body and the other
    stringifies an exception. Both go through `core.exceptions.wire_refusal`,
    and this says so: the code AND the sentence, not just the status.

    Read against its neighbour above, the pair is the whole claim: an UNKNOWN
    kind is `invalid` on both doors, an unreadable one is `forbidden` on both,
    and the two answers stay different from each other in the same way at each
    door.

    *Absent (baseline `11b1a765`):* 200 on both doors, with two widget hits.
    """
    from apps.core.authz import refusal_sentence
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}
    arguments = {"q": "sprocket", "kinds": "widgets"}
    sentence = refusal_sentence("widget.read")

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                SEARCH_URL, params=arguments, headers={**bearer_header, "accept": JSON}
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
                        "clientInfo": {"name": "search-read-parity", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc("tools/call", {"name": "search_query", "arguments": arguments}, 2),
            )

    assert over_http.status_code == 403, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "forbidden"
    assert rest_body["detail"] == sentence

    rendered = str(called.json())
    assert "forbidden" in rendered
    assert sentence in rendered, (
        "the machine door says something different about a withheld read than the "
        "HTTP door does — both render `wire_refusal` through the one composer"
    )
    assert two_hits.queries == [], "an engine was asked before the refusal"
