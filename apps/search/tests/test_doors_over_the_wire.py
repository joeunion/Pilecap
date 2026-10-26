"""One search, answered by both doors, compared on the wire (rule 46).

`transaction=True`: the transport runs a tool body on a worker thread with its own connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import pytest

from apps.core.tests.wire import MCP_HEADERS, MCP_URL, bearer, initialize, rpc, wire
from apps.search import engine as engine_module
from apps.search import registry
from apps.search.types import EngineHit, RecordingEngine

from .conftest import WIDGETS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.models import Tenant

#: House rule 46. The door pair this module answers for `apps/search`.
DOOR_PAIR = ("rest", "mcp")

SEARCH_URL = "/api/v1/search/"
KINDS_URL = "/api/v1/search/kinds/"
JSON = "application/json"

#: `SearchPage`'s wire contract, written out: a pin derived from the schema cannot fail.
PAGE_KEYS = frozenset({"items", "has_more", "next_cursor", "count", "engine"})
HIT_KEYS = frozenset({"kind", "id", "label", "rank"})
#: A page of the vocabulary has no `engine`: nothing answered it.
KIND_PAGE_KEYS = frozenset({"items", "has_more", "next_cursor", "count"})


def test_the_route_is_mounted_where_its_url_name_says() -> None:
    """The route's own handle, reversed rather than spelled (rules 3 and 32)."""
    from django.urls import reverse

    assert reverse("api:search-query") == SEARCH_URL


@pytest.fixture
def token(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    return bearer(user=owner, tenant=tenant, name="search-door-parity")


@pytest.fixture
def hatless_token(nomad: Any) -> str:
    """A real token for somebody who belongs to no account at all."""
    return bearer(user=nomad, tenant=None, name="hatless-parity")


@pytest.fixture
def two_hits(monkeypatch: pytest.MonkeyPatch) -> RecordingEngine:
    """A declared kind and an engine holding two hits — two, so an ordering difference shows."""
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


async def _both(
    token: str, url: str, params: dict[str, str], tool: str, arguments: dict[str, Any]
) -> tuple[httpx.Response, dict[str, Any]]:
    """One question to the REST route and its MCP twin: the HTTP response and the JSON-RPC body."""
    auth = {"authorization": f"Bearer {token}"}
    async with wire() as client:
        over_http = await client.get(url, params=params, headers={**auth, "accept": JSON})
        await initialize(client, auth, who="search-door-parity")
        called = await client.post(
            MCP_URL,
            headers={**MCP_HEADERS, **auth},
            json=rpc("tools/call", {"name": tool, "arguments": arguments}, 2),
        )
        assert called.status_code == 200, called.text
    answered: dict[str, Any] = called.json()
    return over_http, answered


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_page_on_the_wire(
    token: str, root_org: Any, two_hits: RecordingEngine
) -> None:
    """The same query over HTTP and JSON-RPC: one key set and one set of values, `items` too."""
    over_http, answered = await _both(
        token,
        SEARCH_URL,
        {"q": "sprocket", "kinds": "widgets", "include_count": "true"},
        "search_query",
        {"q": "sprocket", "kinds": "widgets", "include_count": True},
    )
    assert over_http.status_code == 200, over_http.text
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(rest_body) == PAGE_KEYS
    assert rest_body["count"] == 2
    assert len(rest_body["items"]) == 2
    assert set(over_mcp) == set(rest_body)
    assert over_mcp == rest_body, "the two doors disagree about the page's values"
    for rest_hit, mcp_hit in zip(rest_body["items"], over_mcp["items"], strict=True):
        assert set(rest_hit) == HIT_KEYS
        assert rest_hit == mcp_hit


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_publish_the_same_vocabulary(
    token: str, root_org: Any, two_hits: RecordingEngine
) -> None:
    """The second pair: `GET /search/kinds/` and `list_search_kinds`, compared the same way."""
    over_http, answered = await _both(
        token, KINDS_URL, {"include_count": "true"}, "list_search_kinds", {"include_count": True}
    )
    assert over_http.status_code == 200, over_http.text
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    assert set(rest_body) == KIND_PAGE_KEYS
    assert rest_body["items"] == [{"kind": "widgets", "app": "example"}]
    assert rest_body["count"] == 1
    assert over_mcp == rest_body, "the two doors disagree about the vocabulary"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_refuse_an_unknown_kind_with_the_same_sentence(
    token: str, root_org: Any, two_hits: RecordingEngine
) -> None:
    """An unknown kind is `invalid` at both doors, in the one composer's sentence."""
    arguments = {"q": "sprocket", "kinds": "definitely-not-a-kind"}
    over_http, answered = await _both(token, SEARCH_URL, arguments, "search_query", arguments)

    assert over_http.status_code == 400, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "invalid"
    rendered = str(answered)
    assert "definitely-not-a-kind" in rendered
    assert rest_body["errors"]["kinds"][0] in rendered


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "params", "tool"),
    [(SEARCH_URL, {"q": "sprocket"}, "search_query"), (KINDS_URL, {}, "list_search_kinds")],
)
async def test_a_caller_with_no_account_is_refused_at_both_doors(
    hatless_token: str,
    two_hits: RecordingEngine,
    url: str,
    params: dict[str, str],
    tool: str,
) -> None:
    """A credential of no account is `no_acting_scope` at REST and at MCP, never a page."""
    over_http, answered = await _both(hatless_token, url, params, tool, dict(params))

    assert over_http.status_code == 403, over_http.text
    assert over_http.json()["code"] == "no_acting_scope"
    assert answered["result"]["isError"] is True, answered
    assert "no_acting_scope" in str(answered["result"]["content"])
    assert two_hits.queries == [], "an engine was asked before the refusal"


@pytest.fixture
def widget_read_withheld(tenant: Tenant, owner: User) -> Any:
    """One `withhold` row on the owner's own membership: `widget.read`, gone."""
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
    token: str, root_org: Any, two_hits: RecordingEngine, widget_read_withheld: Any
) -> None:
    """A kind the caller may not read is `forbidden` at both doors, before any engine is asked."""
    from apps.core.authz import refusal_sentence

    arguments = {"q": "sprocket", "kinds": "widgets"}
    sentence = refusal_sentence("widget.read")
    over_http, answered = await _both(token, SEARCH_URL, arguments, "search_query", arguments)

    assert over_http.status_code == 403, over_http.text
    rest_body = over_http.json()
    assert rest_body["code"] == "forbidden"
    assert rest_body["detail"] == sentence
    rendered = str(answered)
    assert "forbidden" in rendered
    assert sentence in rendered
    assert two_hits.queries == [], "an engine was asked before the refusal"
