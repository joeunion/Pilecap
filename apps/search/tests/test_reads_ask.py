"""PR4.g — **search is kinds ∩ readable, and the engine is never asked otherwise.**

`get_search_page()` answers a `SearchPage`, outside rule 54 (d)'s population by
ANNOTATION — the rule's `does_not_cover` says so. **This module is the belt for that
declared blind spot**: it proves the one read door no census reads asks the question
every other read door asks.

Three answers, and they are deliberately three rather than one:

* **`kinds` left out** — everything means everything you may read. A kind you
  may not read is simply not in the results, and the page is byte-identical to a
  page that matched nothing, which is this module's whole posture.
* **`kinds` naming a declared kind you may not read** — `Forbidden`, with that
  key's own sentence, BEFORE the engine is asked. The vocabulary is a published
  door (`GET /search/kinds/`), so a refusal that names a kind leaks nothing a
  `GET` did not already hand over; silently searching fewer kinds than were
  asked for is the shape `registry.resolve_kinds`' docstring records a field
  test finding.
* **`kinds` naming something nobody declares** — still `Invalid`. "No such kind
  anywhere" and "that kind, not you" want different actions from a caller.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from apps.core.actor import Actor, actor_for
from apps.core.authz import refusal_sentence
from apps.core.exceptions import Forbidden, Invalid
from apps.core.models import Grant, Membership
from apps.search import registry
from apps.search.selectors import get_search_page
from apps.search.types import RecordingEngine, Searchable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .conftest import World

pytestmark = pytest.mark.django_db

SEARCH_URL = "/api/v1/search/"
KINDS_URL = "/api/v1/search/kinds/"


def _acting(world: World) -> Actor:
    """A FRESH actor for the region admin, built after whatever the test changed.

    **Not `world.admin_at_a`, and the reason is the memo.** The `world`
    fixture creates a widget as that actor, which warms its permission memo —
    the actor holds the three tables' rows from before the test wrote anything,
    exactly as it is supposed to (one actor, one fetch, PR0). A `Grant` written
    afterwards is therefore invisible to it, which is correct for a request that
    already resolved and wrong for a test pretending to be the next request.
    Every real door builds its actor per request; so does every test here.
    """
    return actor_for(user=world.admin_at_a.user, tenant=world.tenant, org=world.a)


def _withhold(*, world: World, who: Actor, permission: str) -> Grant:
    """Take one key away from one person, the way a deployment would.

    A `withhold` beats everything — "forbid overrides permit" — so this is the
    smallest world in which an ordinary admin may not read one kind: nothing
    about the role or the tree changes, and the only difference between the two
    halves of every test below is this one row.
    """
    assert who.user is not None
    membership = Membership.objects.filter(tenant=world.tenant).get(user__pk=who.user.pk)
    return Grant.objects.create(
        tenant=world.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


# --- 1 · everything means everything you may read -----------------------------


def test_a_search_across_everything_omits_the_kinds_you_may_not_read(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """**PR4.g.** Two declared kinds, one withheld, and the engine sees one.

    What the ENGINE was handed is the evidence, not what the selector computed:
    a kind that reached the engine reached it, whatever a local variable said.

    *Absent (baseline `11b1a765`):* the engine is asked about both kinds — the
    read was free, so nothing narrowed it.
    """
    _withhold(world=world, who=world.admin_at_a, permission="widget.read")

    get_search_page(tenant=world.tenant, actor=_acting(world), q="x", kinds=None)

    assert recording.kinds_seen == [("orgs",)], recording.kinds_seen


def test_without_the_withhold_the_same_person_searches_both(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """The other half of the pair, and the non-vacuity line under this module.

    Without it, every assertion above would pass on a search that had stopped
    asking any engine anything.
    """
    get_search_page(tenant=world.tenant, actor=_acting(world), q="x", kinds=None)

    assert recording.kinds_seen == [("widgets",), ("orgs",)], recording.kinds_seen


def test_an_actor_who_may_read_nothing_gets_the_empty_page_not_a_refusal(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """Byte-identical to a page that matched nothing. **The posture, kept.**

    Nobody named a kind, so nobody is refused: a search across everything, by
    somebody entitled to none of it, is a page with no hits — the same page a
    search for a word nobody wrote returns. The engine is not asked, and the
    page still names the engine that would have answered, which is the one
    deliberate inaccuracy the route's contract already states.
    """
    _withhold(world=world, who=world.admin_at_a, permission="widget.read")
    _withhold(world=world, who=world.admin_at_a, permission="organization.read")

    page = get_search_page(
        tenant=world.tenant, actor=_acting(world), q="x", kinds=None, include_count=True
    )

    assert page.items == []
    assert page.count == 0
    assert page.has_more is False
    assert page.engine == "recording"
    assert recording.queries == [], "the engine was asked about a kind nobody may read"


# --- 2 · naming one you may not read -----------------------------------------


def test_naming_an_unreadable_kind_is_forbidden_with_the_lists_own_words(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """**PR4.g.** `Forbidden`, the key's own sentence, and no engine call.

    The sentence is read from `refusal_sentence` rather than typed, so the door
    is compared against the key's own prose and not against a third copy of it
    that could drift from both.

    *Absent (baseline):* a 200 page of widget hits.
    """
    _withhold(world=world, who=world.admin_at_a, permission="widget.read")

    with pytest.raises(Forbidden) as refused:
        get_search_page(tenant=world.tenant, actor=_acting(world), q="x", kinds=["widgets"])

    assert str(refused.value.detail) == refusal_sentence("widget.read")
    assert recording.queries == [], "the engine was asked before the refusal"


def test_an_unknown_kind_is_still_invalid(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """**PR4.g.** The vocabulary check comes first, and keeps its own answer.

    A name nobody declares is `Invalid` — 400, naming what you sent and listing
    what exists — even for somebody who may read nothing. "No such kind" and
    "not yours" are different mistakes and they get different answers.
    """
    _withhold(world=world, who=world.admin_at_a, permission="widget.read")

    with pytest.raises(Invalid) as refused:
        get_search_page(tenant=world.tenant, actor=_acting(world), q="x", kinds=["invoices"])

    assert "invoices" in refused.value.errors["kinds"][0]
    assert recording.queries == []


def test_a_readable_kind_named_beside_an_unreadable_one_refuses_the_whole_list(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """One unreadable name refuses the list rather than searching the rest.

    The same rule `resolve_kinds` applies to an unknown name, for the same
    reason: a `200` with fewer results than were asked for, and nothing in it
    saying which half was dropped, is the defect a field test found.
    """
    _withhold(world=world, who=world.admin_at_a, permission="widget.read")

    with pytest.raises(Forbidden):
        get_search_page(tenant=world.tenant, actor=_acting(world), q="x", kinds=["orgs", "widgets"])

    assert recording.queries == []


# --- 3 · the catalogue does not shrink ---------------------------------------


def test_the_kind_catalogue_does_not_shrink(world: World, declared: tuple[Searchable, ...]) -> None:
    """**PR4.g.** `GET /search/kinds/` is the PRODUCT's vocabulary, not yours.

    A kind you may not read is still a kind this product has. The catalogue is
    the same for every customer and every person — which is exactly what makes
    refusing a named unreadable kind safe, since the refusal names something a
    `GET` already hands over.

    *Absent:* `widgets` missing from the list for the withheld person, which is
    what a catalogue filtered by entitlement would produce.
    """
    _withhold(world=world, who=world.admin_at_a, permission="widget.read")
    api = world.session(world.admin_at_a)

    listed = api.get(KINDS_URL)

    assert listed.status_code == 200, listed.content
    assert {one["kind"] for one in listed.json()["items"]} == {"widgets", "orgs"}


# --- 4 · both doors, and the cost --------------------------------------------


def test_the_wire_refuses_a_named_unreadable_kind_with_the_same_words(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """**PR4.g.2.** 403 `forbidden` over HTTP, and the body is the key's sentence.

    The MCP twin is compared against this one in
    `test_doors_over_the_wire.py`, under the module's declared `DOOR_PAIR`.

    *Absent (baseline):* 200 with a page of widget hits.
    """
    _withhold(world=world, who=world.admin_at_a, permission="widget.read")
    api = world.session(world.admin_at_a)

    refused = api.get(SEARCH_URL, {"q": "x", "kinds": "widgets"})

    assert refused.status_code == 403, refused.content
    body = json.loads(refused.content)
    assert body["code"] == "forbidden"
    assert body["detail"] == refusal_sentence("widget.read")


def test_a_search_across_everything_is_still_two_hundred_for_a_plain_member(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """The flat-product half: a product that customised nothing observes nothing.

    `member` holds `*.read` by declaration, so a search across everything is the
    200 it always was. This is the line that would go red if the gate above were
    accidentally closed on everybody.
    """
    api = world.session(world.admin_at_a)

    page = api.get(SEARCH_URL, {"q": "x"})

    assert page.status_code == 200, page.content
    assert recording.kinds_seen == [("widgets",), ("orgs",)]


def test_the_readable_kinds_cost_the_memos_three_once(
    world: World, declared: tuple[Searchable, ...], django_assert_num_queries: Any
) -> None:
    """**PR4.g.** Three statements for the whole vocabulary, not three per kind.

    The actor carries the permission memo (PR0), so the first `allows` reads the
    three tables — the person's memberships in this tenant, the grants on them,
    the role-delta rows — and every kind after it reads none. Asserted as an
    equality over TWO declared kinds, so a lost memo (which would make it six)
    is a failure rather than a slow page.

    *Absent (baseline):* the function does not exist; there was no question to
    cost, because a read was free.
    """
    from apps.search.selectors import list_readable_kinds

    acting = _acting(world)
    with django_assert_num_queries(3):
        first = list_readable_kinds(acting)
    assert first == {"widgets", "orgs"}

    # ...and the same actor, asked again, pays nothing: the memo is the actor's.
    with django_assert_num_queries(0):
        assert list_readable_kinds(acting) == first


def test_every_declared_kind_resolves_to_a_key_the_vocabulary_holds(
    declared: tuple[Searchable, ...],
) -> None:
    """The population is closed: every searchable kind has a read key to ask for.

    Derived from the registry rather than listed, so a kind added tomorrow is in
    this assertion without anybody editing it — and a model that opted out of
    the vocabulary (`authz_kind = None`) would be named here rather than
    silently never searchable.
    """
    from apps.core.authz import kind_of, vocabulary

    words = vocabulary()
    for declaration in registry.declarations():
        kind = kind_of(declaration.model)
        assert kind is not None, declaration.label
        assert f"{kind}.read" in words, (declaration.label, kind)
