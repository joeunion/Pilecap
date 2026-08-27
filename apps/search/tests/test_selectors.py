"""The chokepoint's criteria: what the engine is handed, and what it never is.

Every assertion here reads the RECORDING ENGINE rather than the selector's own
variables. What the engine received is the only honest evidence about what the
chokepoint injected — a test that asserted on `scope_for(...)` directly would be
asserting that one line of this module equals the line above it, and would have
gone on passing the day somebody stopped passing the result down.
"""

from __future__ import annotations

import pytest

from apps.core.api.pagination import encode_cursor
from apps.core.exceptions import InvalidCursor, NotFound
from apps.core.models import Organization
from apps.search import selectors
from apps.search.selectors import CURSOR_ORDERING, list_visible_org_ids, search
from apps.search.types import EngineHit, RecordingEngine, ScopeFilter, Searchable, SearchEngine

from .conftest import World

pytestmark = pytest.mark.django_db


def test_the_recording_engine_is_a_real_engine() -> None:
    """The double satisfies the protocol it stands in for.

    Without this, every criterion below is proved against a shape that could
    have drifted from `SearchEngine` — which is the way a test double stops
    testing anything and nobody finds out.
    """
    assert isinstance(RecordingEngine(), SearchEngine)


def test_an_org_scoped_kind_is_filtered_by_tenant_and_the_visible_subtree(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """Criterion 3, the org-scoped half: `tenant_id = t AND org_id IN [resolved]`.

    The hat is `region`, so the ids are exactly `region` and `branch` — its own
    node and everything beneath it — and never the root above it or the sibling
    beside it. Asserted as a SET EQUALITY rather than a containment: a filter
    that named one id too many is the leak, and `in` would not see it.
    """
    search(tenant=world.tenant, actor=world.region_actor, q="widget", kinds=["widgets"])

    assert len(recording.filters) == 1
    scope = recording.filters[0]
    assert scope.tenant_id == world.tenant.pk
    assert scope.org_ids is not None
    assert set(scope.org_ids) == {world.region.pk, world.branch.pk}
    assert world.root.pk not in scope.org_ids
    assert world.sibling.pk not in scope.org_ids


def test_a_tenant_scoped_kind_is_filtered_by_tenant_alone(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """Criterion 3, the other half — and the half a one-shape injection gets wrong.

    `org_ids is None` is the assertion and it is not the same as `== ()`: `None`
    says "this kind carries no organization, so the tenant filter IS the wall",
    and `()` says "the hat resolved to nothing". Collapsing them is how an
    unresolved hat comes to read as an unscoped kind.
    """
    search(tenant=world.tenant, actor=world.region_actor, q="acme", kinds=["orgs"])

    assert len(recording.filters) == 1
    assert recording.filters[0].org_ids is None
    assert recording.filters[0].tenant_id == world.tenant.pk


def test_the_query_string_is_never_part_of_the_filter(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """`q` reaches the engine as `q`, and the scope reaches it as ids.

    The corpus here is small; the hostile-corpus probe's is hostile and large. What this pins is the
    *shape* — that the two are separate values all the way down — because that
    is what makes the hostile corpus a formality rather than a hope.
    """
    from apps.search.engine import scope_expression

    hostile = 'sprocket" OR tenant_id != "x'
    search(tenant=world.tenant, actor=world.owner_actor, q=hostile, kinds=["widgets"])

    assert recording.queries == [hostile]
    rendered = scope_expression(recording.filters[0])
    assert hostile not in rendered
    assert "OR" not in rendered
    assert str(world.tenant.pk) in rendered


def test_resolving_the_visible_subtree_is_one_query(
    world: World, declared: tuple[Searchable, ...], django_assert_num_queries: object
) -> None:
    """Criterion 4: one indexed prefix scan, not one query per level of the tree.

    Pinned at the resolution rather than at the whole route, so the number means
    something a reader can act on: a recursive walk up or down the tree is the
    regression this catches, and it would show up here as three.
    """
    with django_assert_num_queries(1):  # type: ignore[operator]
        ids = list_visible_org_ids(tenant=world.tenant, actor=world.region_actor)
    assert set(ids or ()) == {world.region.pk, world.branch.pk}


def test_no_tenant_returns_the_empty_page_without_asking_the_engine(
    declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """Criterion 5, first half. `for_tenant(None)`'s posture, one level out."""
    page = search(tenant=None, actor=None, q="anything")

    assert page.items == []
    assert page.count is None
    assert page.has_more is False
    assert page.next_cursor is None
    assert recording.queries == [], "the engine was asked about a request with no tenant"


def test_an_unresolved_hat_returns_the_empty_page_byte_identical_to_no_matches(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """Criterion 5, second half — and the comparison is the point.

    "Not there" and "not yours" are one answer here for the same reason they are
    one answer everywhere else. So the assertion is not "it was empty": it is
    that the refused page and a page that genuinely matched nothing **serialise
    identically**, which is what makes the difference unobservable from outside.
    """
    from apps.core.actor import Actor

    hatless = Actor(user=world.owner, token=None, kind="human", tenant=world.tenant, org=None)
    refused = search(tenant=world.tenant, actor=hatless, q="widget")

    empty = search(tenant=world.tenant, actor=world.owner_actor, q="nothing-matches-this")

    assert refused.model_dump() == empty.model_dump()
    assert refused.items == []


def test_a_hat_that_resolves_to_nothing_never_reaches_the_engine(
    world: World,
    declared: tuple[Searchable, ...],
    recording: RecordingEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The closed filter is answered here, not sent for confirmation.

    `org_ids == ()` matches nothing by construction. Asking the engine to agree
    would be a network call whose answer is already known — and, worse, a
    filter expression built from an empty list, which is the one shape a filter
    parser is most likely to be generous about.
    """
    monkeypatch.setattr(selectors, "list_visible_org_ids", lambda **_: ())
    page = search(tenant=world.tenant, actor=world.owner_actor, q="widget", kinds=["widgets"])

    assert page.items == []
    assert recording.queries == []


# The kind that nobody declared USED TO BE TESTED HERE, as "dropped rather than
# refused" — the posture chosen because the vocabulary was a secret. It is
# not a secret any more (`GET /search/kinds/`), and a field test measured what
# the silence cost a stranger. Both halves of the replacement — the
# narrowing that still narrows, and the refusal that replaced the drop — live in
# `test_kinds_vocabulary.py`, beside the door that made the change safe.


def test_the_page_speaks_the_cursor_envelope_and_walks(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """ADR core-18's envelope, over a ranked result set rather than a queryset.

    `page=` is gone product-wide, so search never had one. What it has instead is
    a cursor naming the offset into *this* ranked set — and the walk has to reach
    the second page for the token to be worth anything.
    """
    recording.hits = tuple(
        EngineHit(kind="widgets", id=widget_id, label=f"w{index}", rank=100 - index)
        for index, widget_id in enumerate(
            Organization.objects.for_tenant(world.tenant).values_list("id", flat=True)
        )
    )
    recording.total = len(recording.hits)

    first = search(
        tenant=world.tenant,
        actor=world.owner_actor,
        q="w",
        kinds=["widgets"],
        limit=2,
        include_count=True,
    )
    assert len(first.items) == 2
    assert first.has_more is True
    assert first.next_cursor
    assert first.count == recording.total

    second = search(
        tenant=world.tenant,
        actor=world.owner_actor,
        q="w",
        kinds=["widgets"],
        limit=2,
        cursor=first.next_cursor,
    )
    assert [hit.label for hit in second.items] != [hit.label for hit in first.items]


def test_count_is_null_unless_it_was_asked_for(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """`null` is "not counted", which is a different fact from zero.

    Narrowed to one kind on purpose: the count is a SUM across the kinds a
    request searched, and a two-kind assertion here would be pinning the fixture
    rather than the contract.
    """
    recording.total = 7
    recording.hits = (EngineHit(kind="widgets", id=world.tenant.pk, label="one", rank=1.0),)

    assert (
        search(tenant=world.tenant, actor=world.owner_actor, q="x", kinds=["widgets"]).count is None
    )
    assert (
        search(
            tenant=world.tenant,
            actor=world.owner_actor,
            q="x",
            kinds=["widgets"],
            include_count=True,
        ).count
        == 7
    )


def test_a_cursor_from_another_tenant_answers_not_found(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine, other_tenant: object
) -> None:
    """The pagination seam's own posture, inherited rather than re-decided.

    A foreign cursor is `not_found` and never `forbidden`: a refusal that told
    them apart would confirm the other tenant's walk exists.
    """
    foreign = encode_cursor(
        tenant_key=str(other_tenant.pk),  # type: ignore[attr-defined]
        ordering=CURSOR_ORDERING,
        keys=[10],
    )
    with pytest.raises(NotFound):
        search(tenant=world.tenant, actor=world.owner_actor, q="x", cursor=foreign)


def test_a_cursor_minted_for_a_list_endpoint_is_refused(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """A search cursor names a rank position; a list cursor names a row.

    They are not interchangeable, and the ordering token in the payload is what
    makes saying so mechanical rather than a matter of somebody noticing.
    """
    from datetime import UTC, datetime

    listish = encode_cursor(
        tenant_key=str(world.tenant.pk),
        ordering=("-created_at", "id"),
        keys=[datetime.now(UTC).isoformat(), str(world.tenant.pk)],
    )
    with pytest.raises(InvalidCursor):
        search(tenant=world.tenant, actor=world.owner_actor, q="x", cursor=listish)


def test_the_engine_never_sees_the_actor_or_a_path(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """The contract stated as an assertion: `ScopeFilter` carries ids and nothing else.

    A path in a document would make every re-parent a bulk rewrite; a path in a
    FILTER would make the engine responsible for understanding the hierarchy.
    Neither is available, and this is the test that says so out loud.
    """
    search(tenant=world.tenant, actor=world.region_actor, q="x", kinds=["widgets"])
    scope = recording.filters[0]

    assert isinstance(scope, ScopeFilter)
    assert set(vars(type(scope)).get("__slots__", ())) <= {"tenant_id", "org_ids"}
    assert world.region.path not in repr(scope)
