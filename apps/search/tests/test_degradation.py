"""The circuit's criteria: Meili down is a **degraded state**, never an outage.

Every assertion here is about the one sentence ADR search-2 puts at the centre
of this app: *a degradation the system survives is a state it announces, never
just tolerates.* Three halves to that, and each has its own section below.

1. **It survives** — the same request that met a dead index is answered from
   Postgres, with the same walls, at `200`.
2. **It cools down** — a request inside the TTL never asks the dead engine
   again, asserted by a **call counter** rather than by a timing hope.
3. **It announces** — `search.engine.degraded` on the way down and
   `search.engine.recovered` on the way up, **once per transition**, asserted
   as event rows rather than as log lines.

The engines here are doubles for the PRIMARY only. `PostgresEngine` is never
faked: every fallback assertion below runs the real one against real rows in
the real database, because a fallback proved against a double is a fallback
proved against the thing that cannot fail.

**Which of the fallback's two paths runs here, and it is no longer a choice
this module makes.** `PostgresEngine` reads the declared `search_vector` column
when the model has one and computes the identical vector inline when it does
not. `example.Widget` HAS one — so the `widgets` half of the
planted pair now exercises the real-column path and the tenant-scoped `orgs`
half (over `core.Organization`, which declares no column) exercises the computed
one. Both branches therefore have a live driver, which is a better position than
this module was written in and worth stating rather than leaving to be
rediscovered: what is proved HERE is the CIRCUIT and the fallback MECHANISM, and
the column's own behaviour — the weights ranking, the GIN index, the
never-stale property — is proved in the adopting app, at
`apps/example/tests/test_search_adoption.py`.

**Still not proved anywhere:** the trigram half of typo tolerance. An earlier rung landed
`pg_trgm` and the index; no query in the tree reads it, so a misspelled word
still finds nothing while the circuit is open.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache

from apps.core.exceptions import SearchUnavailable
from apps.core.models import Organization
from apps.events.models import Event
from apps.example.models import Widget
from apps.example.services import create_widget
from apps.search import engine as engine_module
from apps.search import selectors
from apps.search.events import SEARCH_ENGINE_DEGRADED, SEARCH_ENGINE_RECOVERED
from apps.search.selectors import PostgresEngine, get_search_page
from apps.search.types import (
    EngineHit,
    EngineUnavailable,
    RecordingEngine,
    ScopeFilter,
    Searchable,
    SearchEngine,
)

from .conftest import World

pytestmark = pytest.mark.django_db

SEARCH_URL = "/api/v1/search/"


class DeadEngine(RecordingEngine):
    """A primary that cannot answer. **Counts the attempts**, which is criterion 2.

    A subclass of the recording double rather than a new one, so it satisfies
    `SearchEngine` for the same reason its parent does and cannot drift from the
    protocol on its own. It is constructed with `name="meili"` rather than
    declaring one, because the parent is a dataclass and `name` is one of its
    fields — a class attribute here would be shadowed by the field default and
    the announcement under test would name the wrong engine.
    """

    def query(self, **kwargs: Any) -> Any:
        self.queries.append(str(kwargs.get("q", "")))
        raise EngineUnavailable("Meilisearch did not answer a search.")


class FlakyEngine(RecordingEngine):
    """A primary that is down until somebody sets `alive`, then answers.

    One object across the whole drill, because the recovery half is only a real
    assertion if the thing that comes back is the thing that went away.
    """

    alive: bool = False

    def query(self, **kwargs: Any) -> Any:
        self.queries.append(str(kwargs.get("q", "")))
        if not self.alive:
            raise EngineUnavailable("Meilisearch did not answer a search.")
        return RecordingEngine.query(self, **kwargs)


@pytest.fixture
def dead(monkeypatch: pytest.MonkeyPatch) -> DeadEngine:
    """The primary, dead, installed at the ONE factory both callers use."""
    engine = DeadEngine(name="meili")
    monkeypatch.setattr(engine_module, "engine", lambda: engine)
    return engine


@pytest.fixture
def flaky(monkeypatch: pytest.MonkeyPatch) -> FlakyEngine:
    """The primary, down and recoverable, installed at the same one factory."""
    engine = FlakyEngine(
        hits=(EngineHit(kind="widgets", id=uuid4(), label="From the index", rank=9.0),),
        total=1,
        name="meili",
    )
    monkeypatch.setattr(engine_module, "engine", lambda: engine)
    return engine


def names(tenant_pk: Any) -> list[str]:
    """This tenant's SEARCH event names, oldest first. The announcement's evidence.

    Narrowed to this app's prefix on purpose: the world fixture commits widgets,
    which emit `example.widget.created`, and a test asserting on the whole event
    table would be asserting about a neighbouring app's contract as well as its
    own.
    """
    return [
        name
        for name in Event.objects.filter(tenant_id=tenant_pk)
        .order_by("created_at")
        .values_list("name", flat=True)
        if name.startswith("search.")
    ]


# --- (0) the engine itself ----------------------------------------------------


def test_the_postgres_engine_is_a_real_engine() -> None:
    """It satisfies the protocol the primary satisfies. Peer, never subclass."""
    assert isinstance(PostgresEngine(), SearchEngine)
    assert PostgresEngine().name == "postgres"


def test_its_index_writes_are_documented_no_ops(world: World) -> None:
    """`upsert` and `delete` do nothing, and doing nothing is the whole point.

    The generated column needs no sync, which is exactly why the fallback can
    never be stale — and why the indexer may hand it a batch without branching
    on which engine it holds. "Does nothing" is asserted as **the rows are
    untouched**, not as "returned None": a method that quietly deleted the
    widgets would also return `None`.
    """
    engine = PostgresEngine()
    before = set(Widget.objects.filter(tenant=world.tenant).values_list("id", flat=True))
    assert before, "no rows to leave alone — this test could not fail"

    engine.upsert(label="widgets", documents=[{"id": str(uuid4()), "label": "invented"}])
    engine.delete(label="widgets", ids=list(before))

    assert set(Widget.objects.filter(tenant=world.tenant).values_list("id", flat=True)) == before


def test_its_index_administration_refuses_rather_than_pretending(world: World) -> None:
    """The reconcile's vocabulary is Meilisearch's. Asking this engine says so.

    A plausible-looking `IndexState` here would let a future reconcile run
    against the wrong engine, do nothing, and report that it had reconciled —
    which is the one outcome worse than an error.
    """
    engine = PostgresEngine()
    with pytest.raises(NotImplementedError) as refused:
        engine.state(label="widgets")
    assert "no index" in str(refused.value)


# --- (1) it survives ----------------------------------------------------------


def test_a_dead_index_is_answered_from_postgres_rather_than_refused(
    world: World, declared: tuple[Searchable, ...], dead: DeadEngine
) -> None:
    """Criterion 2's first half: the SAME request that met the dead index answers.

    Not the next one, and not an empty page: the rows are the real widgets the
    world fixture committed, found by their real words.
    """
    page = get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])

    assert page.engine == "postgres"
    assert page.items, "the fallback answered nothing at all"
    assert {hit.kind for hit in page.items} == {"widgets"}


def test_the_wire_answers_200_and_says_which_engine_answered(
    world: World, declared: tuple[Searchable, ...], dead: DeadEngine
) -> None:
    """Zero 5xx at the door, and the honest surface saying why (ADR search-2)."""
    api = world.session(world.owner)
    response = api.get(SEARCH_URL, {"q": "Widget", "kinds": "widgets"})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["engine"] == "postgres"
    assert body["items"]


def test_the_fallback_receives_the_same_walls(
    world: World, declared: tuple[Searchable, ...], dead: DeadEngine
) -> None:
    """**What does not degrade: the walls.** The sibling test, driven through pg.

    The region hat sees its own branch's widgets and never the root's, never the
    sibling's — the same downward-only answer `visible_to` gives, computed from
    the same resolved ids. A fallback that widened the scope would be a
    degradation nobody survives.
    """
    page = get_search_page(
        tenant=world.tenant, actor=world.admin_at_a, q="Widget", kinds=["widgets"]
    )

    assert page.engine == "postgres"
    found = {hit.id for hit in page.items}
    visible = set(
        Widget.objects.filter(
            tenant=world.tenant, organization__in=[world.a, world.a1]
        ).values_list("id", flat=True)
    )
    unreachable = set(
        Widget.objects.filter(
            tenant=world.tenant, organization__in=[world.root, world.b]
        ).values_list("id", flat=True)
    )
    assert found == visible
    assert not (found & unreachable)


def test_another_tenants_rows_are_absent_from_the_fallback(
    world: World,
    other_tenant: Any,
    other_root_org: Any,
    stranger: Any,
    declared: tuple[Searchable, ...],
    dead: DeadEngine,
) -> None:
    """The test that cannot pass vacuously: a neighbour with a matching row.

    **On an ORG-SCOPED kind this proves less than it looks like it does**, and
    saying so is the point of the sibling below. Plant-verified: severing the
    tenant clause in `PostgresEngine._scoped` leaves this test GREEN, because
    the org clause happens to exclude the neighbour anyway — their widget is in
    their own root, which is not in this hat's subtree. So this test guards the
    org half twice and the tenant half not at all, and the tenant half needs a
    kind where it IS the whole wall.
    """
    from apps.core.actor import actor_for

    create_widget(
        tenant=other_tenant,
        actor=actor_for(user=stranger, tenant=other_tenant, org=other_root_org),
        name="Widget next door",
    )
    page = get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])

    theirs = set(Widget.objects.filter(tenant=other_tenant).values_list("id", flat=True))
    assert theirs, "the neighbour row was never created — this test could not fail"
    assert not ({hit.id for hit in page.items} & theirs)


def test_a_tenant_scoped_kind_is_walled_by_the_tenant_clause_alone(
    world: World,
    other_tenant: Any,
    other_root_org: Any,
    declared: tuple[Searchable, ...],
    dead: DeadEngine,
) -> None:
    """The tenant clause, where it is **the whole wall**: a tenant-scoped kind.

    `orgs` declares `Organization`, which carries a tenant and no organization
    column, so `ScopeFilter.org_ids` is `None` and the only thing standing
    between this hat and the neighbour's tree is `tenant_id`. Severing that
    clause turns this red and turns nothing else in this module red — which is
    exactly why it exists, and it was written because the plant-verify above
    found the org-scoped sibling could not see the difference.

    The neighbour's root is named for a match: `create_tenant` names a root
    after the tenant, and both tenants' fixtures produce organizations whose
    names share a word, so an unwalled read WOULD return theirs.
    """
    page = get_search_page(tenant=world.tenant, actor=world.owner, q="", kinds=["orgs"])

    theirs = set(Organization.objects.filter(tenant=other_tenant).values_list("id", flat=True))
    mine = set(Organization.objects.filter(tenant=world.tenant).values_list("id", flat=True))
    assert theirs and mine, "one of the two trees is empty — this test could not fail"
    found = {hit.id for hit in page.items}
    assert found <= mine
    assert not (found & theirs)


def test_a_just_created_row_is_found_with_nothing_drained(
    world: World, declared: tuple[Searchable, ...], dead: DeadEngine
) -> None:
    """The consistency note, proven: the fallback is fresh by construction.

    Nothing was indexed, nothing was dispatched and no outbox was drained. The
    degraded engine reads the rows themselves, so a row committed a microsecond
    ago is already findable — the one thing that is BETTER while degraded.
    """
    created = create_widget(tenant=world.tenant, actor=world.owner, name="Freshly minted flange")
    page = get_search_page(tenant=world.tenant, actor=world.owner, q="flange", kinds=["widgets"])

    assert created.pk in {hit.id for hit in page.items}


# --- (2) it cools down --------------------------------------------------------


def test_requests_inside_the_cooldown_never_ask_the_dead_engine(
    world: World, declared: tuple[Searchable, ...], dead: DeadEngine
) -> None:
    """Criterion 2's second half, asserted by a **call counter**.

    The first request pays one dead round trip. Every request inside the TTL
    pays none — which is what makes an outage cost latency once rather than
    once per request.
    """
    for _ in range(4):
        get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])

    assert len(dead.queries) == 1, dead.queries


def test_the_cooldown_expiring_lets_one_request_probe_again(
    world: World, declared: tuple[Searchable, ...], dead: DeadEngine
) -> None:
    """TTL expiry re-probes. Driven by expiring the key, not by sleeping."""
    get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])
    assert len(dead.queries) == 1

    cache.delete(selectors.COOLDOWN_KEY)
    get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])

    assert len(dead.queries) == 2


# --- (3) it announces ---------------------------------------------------------


def test_the_transition_announces_once_and_a_second_failure_announces_nothing(
    world: World, declared: tuple[Searchable, ...], dead: DeadEngine
) -> None:
    """Transitions only. A per-request announcement is an alert somebody silences."""
    get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])
    assert names(world.tenant.pk).count(SEARCH_ENGINE_DEGRADED) == 1

    cache.delete(selectors.COOLDOWN_KEY)
    get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])

    assert len(dead.queries) == 2, "the re-probe never happened — this proves nothing"
    assert names(world.tenant.pk).count(SEARCH_ENGINE_DEGRADED) == 1


def test_recovery_announces_when_the_primary_answers_again(
    world: World, declared: tuple[Searchable, ...], flaky: FlakyEngine
) -> None:
    """The pair closes: down, then up, each said exactly once."""
    page = get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])
    assert page.engine == "postgres"
    assert names(world.tenant.pk).count(SEARCH_ENGINE_DEGRADED) == 1

    flaky.alive = True
    cache.delete(selectors.COOLDOWN_KEY)
    back = get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])

    assert back.engine == "meili"
    assert names(world.tenant.pk).count(SEARCH_ENGINE_RECOVERED) == 1

    get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])
    assert names(world.tenant.pk).count(SEARCH_ENGINE_RECOVERED) == 1


def test_a_healthy_engine_announces_nothing_at_all(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """The negative that keeps the three above honest."""
    get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])

    assert names(world.tenant.pk) == []


# --- (4) the residual refusal, now machine-readable ---------------------------


def test_no_engine_at_all_is_a_registered_refusal(
    world: World,
    declared: tuple[Searchable, ...],
    dead: DeadEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An earlier frontier, closed. The 503 that SURVIVES the circuit has a code.

    After the circuit there is only one way the door can still refuse a search:
    the primary is unreachable AND the fallback could not answer either, which
    is a database that is not answering. That is a real published state rather
    than the earlier placeholder, so it carries a `code` a client can branch on.
    """

    def collapse(self: Any, **kwargs: Any) -> Any:
        raise EngineUnavailable("Postgres did not answer a search either.")

    monkeypatch.setattr(PostgresEngine, "query", collapse)

    with pytest.raises(SearchUnavailable) as refused:
        get_search_page(tenant=world.tenant, actor=world.owner, q="Widget", kinds=["widgets"])

    assert refused.value.code == "search_unavailable"


def test_the_door_renders_that_refusal_as_503_with_its_code(
    world: World,
    declared: tuple[Searchable, ...],
    dead: DeadEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One composer, one envelope — `detail` and `code`, like every other refusal."""

    def collapse(self: Any, **kwargs: Any) -> Any:
        raise EngineUnavailable("Postgres did not answer a search either.")

    monkeypatch.setattr(PostgresEngine, "query", collapse)
    api = world.session(world.owner)
    response = api.get(SEARCH_URL, {"q": "Widget", "kinds": "widgets"})

    assert response.status_code == 503, response.content
    assert response.json()["code"] == "search_unavailable"


# --- (5) the alert surface ----------------------------------------------------


def test_the_announcement_pair_joins_the_alert_census_with_no_edit() -> None:
    """The pair is DERIVED. Declaring the two names is the whole of joining.

    `deploy/observability/alerts/census.py` reads every app's `events.py` by AST
    and makes one alert per transition pair. This asserts the census sees ours —
    which is the criterion "the announcements reach the alert route", said
    against the artifact that decides it rather than against a runbook sentence.
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    out = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
        [sys.executable, str(root / "deploy/observability/alerts/census.py"), "--json"],
        capture_output=True,
        text=True,
        check=True,
        cwd=root,
    )
    census = json.loads(out.stdout)
    rendered = json.dumps(census)
    assert SEARCH_ENGINE_DEGRADED in rendered, census
    assert SEARCH_ENGINE_RECOVERED in rendered, census


# --- (6) the filter the fallback builds ---------------------------------------


def test_a_closed_scope_never_reaches_the_fallback(
    world: World, declared: tuple[Searchable, ...]
) -> None:
    """`()` matches nothing, and the fallback is not asked to confirm it."""
    engine = PostgresEngine()
    window = engine.query(
        kinds=["widgets"],
        q="Widget",
        scope=ScopeFilter(tenant_id=world.tenant.pk, org_ids=()),
        offset=0,
        limit=10,
    )
    assert window.hits == ()
    assert window.total == 0
