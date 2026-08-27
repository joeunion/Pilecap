"""The kinds vocabulary: published, refused when it is not there, and counted.

Two findings meet in this module, because they are the same
sentence said twice.

**One — a stranger could not tell "no such kind" from "no matches".** The route
advertised `?kinds=widgets`, nothing in the tree declared `widgets`, and the
answer to both questions was an empty page. So the vocabulary is a **door** now,
derived from the registry exactly as `GET /event-types/` is derived from the
apps' `events.py` modules — and, because the vocabulary is public, a kind this
build does not declare is **refused** rather than silently dropped. The two
halves are one decision: dropping was only defensible while the set of kinds was
a secret, and it is not one any more.

**The other — `count: null` when `include_count=true` was asked.** The endpoint's own
contract says "when you do ask, it is exact"; the empty short-circuits answered
`null`, which means "not counted". `0` is the true answer and it is what they say
now. The unresolved-hat page keeps saying whatever a page that matched nothing
says — that one is the anti-oracle exception and the route doc states it.

Every assertion here is over the wire or through the selector, never over a
local variable in `selectors.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from django.test import Client

from apps.core.exceptions import Invalid
from apps.search import registry
from apps.search.selectors import search
from apps.search.types import RecordingEngine, Searchable

from .conftest import ORGS, WIDGETS, World

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User

pytestmark = pytest.mark.django_db

SEARCH_URL = "/api/v1/search/"
KINDS_URL = "/api/v1/search/kinds/"


# --- The vocabulary is a door ---------------------------------------------------


def test_the_declared_kinds_are_published_as_a_page(
    api: Client, owner: User, declared: tuple[Searchable, ...]
) -> None:
    """The catalogue, derived from the registry and answered in the list envelope.

    Derived rather than listed, for `event_catalogue`'s reason: a hand-written
    vocabulary is wrong the morning after the next app declares a kind, and
    nothing fails.
    """
    api.force_login(owner)
    response = api.get(KINDS_URL)

    assert response.status_code == 200, response.content
    body = response.json()
    assert [item["kind"] for item in body["items"]] == ["orgs", "widgets"]
    assert {item["kind"]: item["app"] for item in body["items"]} == {
        "widgets": "example",
        "orgs": "core",
    }
    assert body["count"] is None
    assert set(body) == {"items", "has_more", "next_cursor", "count"}


def test_an_undeclared_kind_is_refused_and_names_the_vocabulary(
    api: Client, owner: User, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """Refused: `?kinds=<not a kind>` is `400 invalid`, not an empty page.

    The refusal names the field the caller sent (`kinds`) and points at the door
    that lists the vocabulary, so the next request is a correction rather than a
    guess. And the engine is never asked — a query nobody could have meant is
    not a query.
    """
    api.force_login(owner)
    # The queue row's repro, verbatim — `include_count=true` included, because
    # the same request repros the other finding too: it used to answer 200 with
    # `count: null` for a count that had been asked for.
    response = api.get(
        SEARCH_URL,
        {"q": "x", "kinds": "definitely-not-a-kind", "include_count": "true"},
    )

    assert response.status_code == 400, response.content
    body = response.json()
    assert body["code"] == "invalid"
    assert "definitely-not-a-kind" in body["errors"]["kinds"][0]
    assert "widgets" in body["errors"]["kinds"][0]
    assert any(remedy["destination"] == "route:search_kind-list" for remedy in body["remedies"])
    assert recording.queries == [], "the engine was asked about a kind nobody declares"


def test_a_declared_kind_beside_an_undeclared_one_still_refuses(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """One bad name refuses the whole list rather than searching the rest.

    Searching what it understood and dropping the rest is the shape that made
    that invisible: the caller gets a 200 with fewer results than they asked for
    and no way to tell which half was ignored.
    """
    with pytest.raises(Invalid) as refused:
        search(
            tenant=world.tenant,
            actor=world.owner_actor,
            q="x",
            kinds=["widgets", "invoices"],
        )

    assert "invoices" in refused.value.errors["kinds"][0]
    assert recording.queries == []


def test_naming_every_declared_kind_is_the_same_as_naming_none(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """The narrowing still narrows — the refusal is about names, not about count."""
    search(tenant=world.tenant, actor=world.owner_actor, q="x", kinds=["widgets"])
    assert recording.kinds_seen == [("widgets",)]

    recording.kinds_seen.clear()
    search(tenant=world.tenant, actor=world.owner_actor, q="x", kinds=None)
    assert recording.kinds_seen == [("widgets",), ("orgs",)]


# --- The count is honoured on every page that was asked to count -------------------


def test_the_empty_page_counts_zero_when_the_count_was_asked_for(
    world: World, recording: RecordingEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half: a build that declares no kind at all still answers `0`.

    `null` means "not counted", and this caller asked. Zero is the exact number
    of matches under the injected filter, which is what the endpoint's contract
    promises — "when you do ask, it is exact".
    """
    monkeypatch.setattr(registry, "declarations", tuple)

    page = search(tenant=world.tenant, actor=world.owner_actor, q="x", include_count=True)

    assert page.items == []
    assert page.count == 0
    assert recording.queries == []


def test_an_unresolved_hat_counts_exactly_what_a_matchless_page_counts(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """The anti-oracle exception, pinned: the two pages serialise identically.

    A hat that did not resolve must answer what "nothing matched" answers, to
    the byte — including the count it was asked for and including `engine`,
    which is the one deliberate lie in this module and the one the route doc
    states out loud. If a caller could tell the two apart, the refusal would be
    a probe: send `X-Org` for a branch you suspect exists and read the shape of
    the answer.
    """
    from apps.core.actor import Actor

    hatless = Actor(user=world.owner, token=None, kind="human", tenant=world.tenant, org=None)

    refused = search(tenant=world.tenant, actor=hatless, q="widget", include_count=True)
    matchless = search(
        tenant=world.tenant,
        actor=world.owner_actor,
        q="nothing-matches-this",
        include_count=True,
    )

    assert refused.model_dump() == matchless.model_dump()
    assert refused.count == 0
    assert refused.engine == matchless.engine


def test_no_tenant_counts_zero_and_still_names_no_engine_of_its_own(
    declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """`for_tenant(None)`'s posture, one level out, with the count honoured."""
    page = search(tenant=None, actor=None, q="anything", include_count=True)

    assert page.items == []
    assert page.count == 0
    assert recording.queries == []


def test_the_kinds_the_route_doc_advertises_are_kinds_this_build_could_declare(
    declared: tuple[Searchable, ...],
) -> None:
    """The documentation half, held to the tree rather than to a promise.

    The contract used to work `?kinds=widgets` as an example while nothing in
    the tree declared `widgets` — a worked example a stranger cannot work. The
    doc now points at the door instead of naming a kind, so it is true of every
    build including one that declares none.
    """
    from apps.search.api import search_route

    contract = search_route.__doc__ or ""
    assert "kinds=widgets" not in contract
    assert "/search/kinds/" in contract


def test_the_catalogue_is_derived_from_the_registry_and_not_from_a_list() -> None:
    """Add a kind, and the catalogue has it with no file here changing."""
    planted = Searchable(model=WIDGETS.model, label="sprockets", fields=[("name", "A")])
    catalogue = registry.catalogue(declarations_=(planted, ORGS))

    assert [entry.kind for entry in catalogue] == ["orgs", "sprockets"]
