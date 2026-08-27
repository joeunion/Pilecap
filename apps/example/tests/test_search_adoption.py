"""The worked adoption, driven: declaration, spine, injection, degradation.

`apps/example/search.py` is the file a product copies when it wants its own rows
findable, and `Widget.search_vector` is the column that comes with it. This
module is what stops either of them from being a plausible-looking pair of
files: it holds the two halves to each other, drives the document through the
spine that keeps it current, and drives the fallback over the real column with
the primary engine dead.

Five sections, and each names the failure it exists to catch:

1. **The declaration and the column agree.** They are two spellings of one
   ranking — the `fields` list ranks the Meilisearch document AND builds the
   tsvector — so a `notes` that lost its `B`, or a config that drifted from the
   one the fallback parses queries under, is a search that quietly finds less
   with no error anywhere.
2. **The example in the contract is TRUE.** A stranger who reads
   `?kinds=…` in the published contract and sends what it shows must not get an
   empty page that means "no such kind". Asserted against the LIVE catalogue,
   at both renderings, so a doc that re-grows a kind nobody declares fails here.
3. **The document converges through the spine** (A3 — consumption, never
   import). Create, update and delete: the last one is the one that matters,
   because a document that survives its row is findable by everybody the filter
   lets in.
4. **The injection probe.** A hostile `q` reaches the engine as `q` and never as
   part of a filter — driven both against the recording double (what the
   chokepoint HANDED an engine is the only honest evidence about what it
   injected) and against the real fallback over real rows, where a widened
   scope would be a row from another tenant coming back.
5. **The real-column degradation drive** (R-d's declared untested branch). The
   circuit's fallback finally has a model that declares the column, so the
   `_declares_column` branch runs against a real GIN-indexed tsvector rather
   than against the computed vector R-d could only reach.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
from django.contrib.postgres.search import SearchQuery
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import User
from apps.core import bridge
from apps.core.actor import Actor, actor_for
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization
from apps.events.activities import SEARCH_INDEX_EVENT
from apps.events.models import Event
from apps.events.schemas import envelope
from apps.example import events as example_events
from apps.example import search as example_search
from apps.example.models import SEARCH_CONFIG, Widget
from apps.example.services import create_widget, delete_widget, update_widget
from apps.search import engine as engine_module
from apps.search import registry, selectors
from apps.search.events import SEARCH_ENGINE_DEGRADED
from apps.search.selectors import TEXT_SEARCH_CONFIG, VECTOR_FIELD, PostgresEngine
from apps.search.types import (
    EngineUnavailable,
    IndexState,
    RecordingEngine,
    ScopeFilter,
    Searchable,
)

pytestmark = pytest.mark.django_db

SEARCH_URL = "/api/v1/search/"
KINDS_URL = "/api/v1/search/kinds/"

#: The one kind this app declares, read out of the module under test rather than
#: rebuilt here — a test that constructed its own `Searchable` would pass while
#: the shipped declaration said something else.
DECLARATION: Searchable = example_search.SEARCHABLES[0]


def body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


class CapturingEngine(RecordingEngine):
    """A recording engine that also keeps the DOCUMENTS it was handed.

    `RecordingEngine.upsert` records `("upsert", label)` and drops the payload,
    which is enough for the reconcile's proven no-op and not enough here: the
    convergence criterion is about what the document SAYS after an update, not
    about how many calls were made. Subclassed rather than reimplemented so it
    stays a `SearchEngine` for the same reason its parent is one.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.upserted: list[dict[str, Any]] = []
        self.deleted: list[UUID] = []

    def upsert(self, *, label: str, documents: Any) -> None:
        super().upsert(label=label, documents=documents)
        self.upserted.extend(documents)

    def delete(self, *, label: str, ids: Any) -> None:
        super().delete(label=label, ids=ids)
        self.deleted.extend(ids)


class DeadEngine(RecordingEngine):
    """The primary, unable to answer. The circuit's input for section 5."""

    def query(self, **kwargs: Any) -> Any:
        self.queries.append(str(kwargs.get("q", "")))
        raise EngineUnavailable("Meilisearch did not answer a search.")


@pytest.fixture(autouse=True)
def _a_closed_circuit() -> Iterator[None]:
    """Every test here starts and ends with the search circuit closed.

    The circuit's state lives in the cache, not the database, so nothing in the
    test harness rolls it back: the injection probe below deliberately fails the
    primary over, and without this the next test would prove its assertion
    against the FALLBACK while believing it had asked the primary — a green test
    measuring the wrong engine, which is the worst shape a leak can take.
    `apps/search/tests/conftest.py` carries the same fixture for the same
    reason; it is repeated rather than shared because a conftest in one app is
    not a conftest in another, and the alternative is a fixture in the root one
    that every app in the tree pays for.
    """
    keys = [selectors.COOLDOWN_KEY, selectors.DEGRADED_KEY]
    cache.delete_many(keys)
    yield
    cache.delete_many(keys)


@pytest.fixture
def capturing(monkeypatch: pytest.MonkeyPatch) -> CapturingEngine:
    """Installed at the ONE factory every write path and the chokepoint call."""
    engine = CapturingEngine(name="meili")
    monkeypatch.setattr(engine_module, "engine", lambda: engine)
    return engine


@pytest.fixture
def dead(monkeypatch: pytest.MonkeyPatch) -> DeadEngine:
    engine = DeadEngine(name="meili")
    monkeypatch.setattr(engine_module, "engine", lambda: engine)
    return engine


# --- 1 · the declaration and the column are two spellings of one ranking -------


def vector_terms() -> list[tuple[str, str, str]]:
    """`(field, weight, config)` for every `setweight` in the generated column.

    Read off the expression TREE and not off its `str()`: the rendering collapses
    to `SearchVector(F(name)) || SearchVector(F(notes))`, which shows neither the
    weight nor the configuration — the two things most worth pinning. Walking the
    tree asserts about what Postgres was actually handed.
    """
    found: list[tuple[str, str, str]] = []

    def walk(node: Any) -> None:
        weight = getattr(node, "weight", None)
        if weight is not None:
            (source,) = node.get_source_expressions()
            (config,) = node.config.get_source_expressions()
            found.append((source.name, weight.value, config.value))
            return
        for child in node.get_source_expressions():
            if child is not None:
                walk(child)

    # `get_field` is typed as returning either a field or a reverse relation,
    # and only the first of those has an `expression`. Read off the class
    # attribute instead: the `GeneratedField` object itself, no narrowing to
    # argue with, and it fails loudly rather than silently walking nothing if
    # the column is ever renamed out from under `VECTOR_FIELD`.
    column = getattr(Widget, VECTOR_FIELD).field
    walk(column.expression)
    return found


def test_the_declaration_and_the_generated_column_carry_the_same_fields() -> None:
    """`search.py` and `models.py` rank on the same list, in the same order.

    They are edited in different files by different people and nothing in Django
    holds them together, so this does. A `notes` dropped from the column is a
    fallback that stops finding what the index finds; a weight changed in one
    place is two rankings that agree until the circuit opens.
    """
    assert [name for name, _weight in DECLARATION.fields] == ["name", "notes"]
    assert [weight for _name, weight in DECLARATION.fields] == ["A", "B"]
    assert [(name, weight) for name, weight, _config in vector_terms()] == list(DECLARATION.fields)


def test_the_column_is_built_under_the_config_the_fallback_parses_queries_under() -> None:
    """One text-search configuration, or the fallback quietly finds less.

    A vector built under `english` and a `to_tsquery` parsed under `simple`
    disagree about stemming and stop words, and the failure is silent: fewer
    hits, no error, nobody notified. The value has to be a literal in the model
    (a generated column must name an immutable configuration), so the agreement
    is pinned here instead of imported — at both ends: the constant the model
    declares, and the configuration every term of the column was actually built
    under.
    """
    assert SEARCH_CONFIG == TEXT_SEARCH_CONFIG
    assert {config for _name, _weight, config in vector_terms()} == {TEXT_SEARCH_CONFIG}


def test_the_declaration_survives_the_registrys_boot_refusal() -> None:
    """The real declaration, through the real validator, unplanted.

    `SearchConfig.ready()` runs this over every installed app at boot, so a green
    process is already evidence — but only until somebody catches the exception.
    Asserting it here names `apps/example` when it breaks.
    """
    assert registry.validate((DECLARATION,)) == (DECLARATION,)


def test_the_fallback_sees_this_model_as_declaring_the_real_column() -> None:
    """R-d's `_declares_column` branch has a member. The rest of section 5 rests here."""
    assert PostgresEngine()._declares_column(DECLARATION) is True


def test_the_generated_column_is_never_stale_because_nothing_writes_it(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """A row committed a microsecond ago is already findable. No sync, no backfill.

    This is the one thing the fallback does BETTER than the index it stands in
    for, and it is a property of the column being generated rather than of
    anybody remembering to update it — which is why `services.py` never mentions
    `search_vector` and this test never calls anything that would.
    """
    widget = create_widget(
        tenant=tenant, actor=owner_actor, name="Hydraulic sprocket", notes="needs a mount"
    )

    found = Widget.objects.filter(
        pk=widget.pk, **{VECTOR_FIELD: SearchQuery("sprocket", config=SEARCH_CONFIG)}
    )
    assert found.exists()

    update_widget(tenant=tenant, actor=owner_actor, widget=widget, name="Pneumatic flange")
    stale = Widget.objects.filter(
        pk=widget.pk, **{VECTOR_FIELD: SearchQuery("sprocket", config=SEARCH_CONFIG)}
    )
    fresh = Widget.objects.filter(
        pk=widget.pk, **{VECTOR_FIELD: SearchQuery("flange", config=SEARCH_CONFIG)}
    )
    assert not stale.exists()
    assert fresh.exists()


# --- 2 · The contract's worked example is true on this tree --------------------

#: Every `kinds=<value>` a rendered contract can advertise. Deliberately a
#: pattern over the text rather than a list of known examples: the point is that
#: NO rendering may name a kind this build does not declare, including one added
#: after this test was written.
KINDS_EXAMPLE = re.compile(r"kinds=([a-z0-9][a-z0-9_,-]*)")


def declared_now() -> set[str]:
    """The live catalogue, unplanted — what a stranger's `GET` would return."""
    return {entry.kind for entry in registry.catalogue()}


def test_this_build_declares_widgets_so_the_kinds_example_can_be_worked() -> None:
    """Half of what this test owns: the example's subject now exists.

    A drive against the deployed route sent `?kinds=widgets` because the route's own worked example
    said to, got `items: []` eight times over twenty-four seconds, and had no
    way to tell "no such kind" from "no matches". R-c made the refusal honest
    and pointed the doc at the kinds door; this test makes the kind real.
    """
    assert "widgets" in declared_now()
    assert registry.resolve_kinds(["widgets"]) == ("widgets",)


def test_no_rendering_of_the_contract_advertises_an_undeclared_kind(
    api: Client, owner: User
) -> None:
    """Both renderings, against the LIVE catalogue. One docstring feeds both.

    The route's contract docstring and `/llms.txt` are two renderings of one
    source, so a `?kinds=` example that comes back in either must name something
    this deployment can actually search. Derived from the catalogue rather than
    compared to a remembered string: that is what makes it hold for the next
    example somebody writes as well as for the one this test found.
    """
    from apps.search.api import list_search_kinds_route, search_route

    declared = declared_now()
    api.force_login(owner)
    llms = api.get("/llms.txt")
    assert llms.status_code == 200

    surfaces = {
        "search_route": search_route.__doc__ or "",
        "list_search_kinds_route": list_search_kinds_route.__doc__ or "",
        "llms.txt": llms.content.decode("utf-8"),
    }
    for where, text in surfaces.items():
        for advertised in KINDS_EXAMPLE.findall(text):
            for kind in advertised.split(","):
                assert kind in declared, f"{where} advertises kinds={kind!r}, which is not declared"


def test_the_kinds_door_and_the_search_door_agree_that_widgets_is_real(
    api: Client, owner: User, capturing: CapturingEngine
) -> None:
    """Over the wire: the vocabulary lists it, and sending it is not a refusal.

    The pair is the assertion. Listing a kind that the search door then refuses,
    or refusing one the door lists, is the disagreement this pairing is a special case
    of — and it is a disagreement no single-door test can see.
    """
    api.force_login(owner)

    listed = api.get(KINDS_URL)
    assert listed.status_code == 200
    assert {"kind": "widgets", "app": "example"} in body(listed)["items"]

    searched = api.get(SEARCH_URL, {"q": "anything", "kinds": "widgets"})
    assert searched.status_code == 200

    refused = api.get(SEARCH_URL, {"q": "anything", "kinds": "sprockets"})
    assert refused.status_code == 400
    assert body(refused)["code"] == "invalid"
    assert "widgets" in body(refused)["errors"]["kinds"][0]


# --- 3 · the document converges through the spine ------------------------------


def spine(event: Event) -> bool:
    """Hand one committed event to the indexer **the way the spine does**.

    By `bridge.find(SEARCH_INDEX_EVENT)` and the wire envelope — never by
    importing `apps.search`. That is the property under test as much as the
    convergence is: `apps/events` fans out a name it looked up, `apps/example`
    imports neither app, and the two meet at a registry filled from an
    `AppConfig.ready()`. An import here would prove the convergence and hide the
    coupling it is supposed to demonstrate.

    What it does not drive is the Temporal dispatch around it — the retry, the
    outbox, the ordering — which `apps/events` proves against a real worker and
    which this module does not re-prove. Stated in the module's blind spots.
    """
    index = bridge.find(SEARCH_INDEX_EVENT)
    assert index is not None, "apps.search did not register the indexer on the bridge"
    return bool(index(tenant_id=event.tenant_id, event=envelope(event)))


def last_event(*, tenant: Tenant, name: str) -> Event:
    found = Event.objects.filter(tenant=tenant, name=name).order_by("-created_at").first()
    assert found is not None, f"nothing emitted {name}"
    return found


def test_a_created_widget_becomes_a_document_through_the_spine(
    tenant: Tenant, owner_actor: Actor, capturing: CapturingEngine
) -> None:
    """Create → `example.widget.created` → the indexer → one document."""
    widget = create_widget(
        tenant=tenant, actor=owner_actor, name="Bench press #4", notes="heavy-duty mount"
    )

    assert spine(last_event(tenant=tenant, name=example_events.WIDGET_CREATED)) is True
    assert [document["id"] for document in capturing.upserted] == [str(widget.pk)]
    document = capturing.upserted[0]
    assert document["name"] == "Bench press #4"
    assert document["notes"] == "heavy-duty mount"
    assert document["label"] == "Bench press #4"
    assert document["tenant_id"] == str(tenant.pk)
    assert document["org_id"] == str(widget.organization_id)


def test_an_updated_widget_reindexes_from_the_row_and_not_from_the_payload(
    tenant: Tenant, owner_actor: Actor, capturing: CapturingEngine
) -> None:
    """Update → the document says what the ROW says now.

    The indexer re-reads the row rather than trusting the envelope, which is what
    makes a redelivered or out-of-order event converge instead of resurrecting an
    old value. Driven by handing it the OLD event after the row has moved on: a
    payload-trusting indexer writes the stale name, this one writes the new one.
    """
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Old name", notes="")
    stale = last_event(tenant=tenant, name=example_events.WIDGET_CREATED)
    update_widget(tenant=tenant, actor=owner_actor, widget=widget, name="New name")

    assert spine(stale) is True

    assert capturing.upserted[-1]["name"] == "New name"


def test_a_deleted_widget_takes_its_document_with_it(
    tenant: Tenant, owner_actor: Actor, capturing: CapturingEngine
) -> None:
    """Delete → the document is REMOVED. **The one that matters.**

    A document that outlives its row is a copy no filter closes: the row is gone
    from every list door and the words are still findable by everybody the
    tenant filter lets in. Absent this, the adoption would look complete and
    leak on every delete.
    """
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Doomed", notes="")
    assert spine(last_event(tenant=tenant, name=example_events.WIDGET_CREATED)) is True
    # The index exists now, which is the state a delete has to meet: the indexer
    # will not create an index in order to delete from it, so a double that
    # never reported one would prove the wrong branch.
    capturing.states["widgets"] = IndexState(label="widgets", exists=True)
    pk = widget.pk

    delete_widget(tenant=tenant, actor=owner_actor, widget=widget)
    assert spine(last_event(tenant=tenant, name=example_events.WIDGET_DELETED)) is True

    assert capturing.deleted == [pk]
    assert ("delete", "widgets") in capturing.writes


def test_an_event_no_kind_subscribed_to_is_an_ordinary_no_op(
    tenant: Tenant, owner_actor: Actor, capturing: CapturingEngine
) -> None:
    """The spine fans EVERY committed event at this leg; most are nobody's business.

    `example.widget.onboarded` is deliberately not in `refresh_on` — onboarding
    moves no searchable field — so it must cost no engine call at all rather
    than an upsert that rewrites the same document.
    """
    create_widget(tenant=tenant, actor=owner_actor, name="Unonboarded", notes="")
    created = last_event(tenant=tenant, name=example_events.WIDGET_CREATED)
    created.name = example_events.WIDGET_ONBOARDED

    assert spine(created) is False
    assert capturing.writes == []


# --- 4 · the injection probe ---------------------------------------------------

#: Strings that would widen a scope if `q` were ever concatenated into a filter,
#: rather than travelling as the engine's own query parameter. Three grammars,
#: because the two engines parse two different languages and the probe has to be
#: hostile in both: Meilisearch's filter expression, Postgres's `tsquery`, and
#: plain SQL for the fallback's `WHERE`.
HOSTILE = (
    '" OR tenant_id = "*',
    '" OR org_id IN ["*"] OR "" = "',
    "') OR 1=1 --",
    "'; DROP TABLE example_widget; --",
    "*",
    "tenant_id != x",
)


def test_a_hostile_q_reaches_the_engine_as_q_and_never_as_a_filter(
    tenant: Tenant, owner_actor: Actor, root_org: Organization, capturing: CapturingEngine
) -> None:
    """What the engine RECEIVED is the only honest evidence about the injection.

    For each hostile string: the filter the chokepoint handed down is exactly
    the resolved ids, and the string itself came through untouched in `q`. Then
    the filter is rendered by the module that renders it for real
    (`engine.scope_expression`) and the hostile text must not appear in the
    expression — which is the smuggling defence checked at the place it would
    fail, rather than asserted about a line of code.
    """
    create_widget(tenant=tenant, actor=owner_actor, name="Findable", notes="")

    for hostile in HOSTILE:
        selectors.search(tenant=tenant, actor=owner_actor, q=hostile, kinds=["widgets"])

    assert capturing.queries == list(HOSTILE)
    for received in capturing.filters:
        assert received.tenant_id == tenant.pk
        assert received.org_ids is not None
        assert set(received.org_ids) == {root_org.pk}
        rendered = engine_module.scope_expression(received)
        assert rendered == f'tenant_id = "{tenant.pk}" AND org_id IN ["{root_org.pk}"]'
        for hostile in HOSTILE:
            assert hostile not in rendered


def test_a_hostile_q_against_the_real_fallback_widens_nothing(
    tenant: Tenant,
    other_tenant: Tenant,
    owner_actor: Actor,
    stranger_actor: Actor,
    dead: DeadEngine,
) -> None:
    """The same probe against real SQL over real rows, with the primary dead.

    This is the half a recording double cannot reach: the fallback builds a
    `tsquery` out of `q` and a `WHERE` out of the scope, and if those two ever
    became one string a hostile `q` would return the neighbour's row. Every
    string must answer with nothing of theirs and must not raise — a 500 here
    would be its own finding, because a query that crashes is a query the parser
    took seriously.
    """
    create_widget(tenant=tenant, actor=owner_actor, name="Mine", notes="")
    theirs = create_widget(tenant=other_tenant, actor=stranger_actor, name="Theirs", notes="")

    for hostile in HOSTILE:
        page = selectors.search(
            tenant=tenant, actor=owner_actor, q=hostile, kinds=["widgets"], include_count=True
        )
        assert page.engine == "postgres"
        assert [hit.id for hit in page.items] == []
        assert page.count == 0

    assert Widget.objects.filter(pk=theirs.pk).exists()


def test_the_fallbacks_filter_is_ids_and_nothing_a_client_sent(
    tenant: Tenant, root_org: Organization
) -> None:
    """`_scoped` builds its `WHERE` from the `ScopeFilter` alone. No actor, no `q`.

    Read off the compiled SQL rather than off the source: the two ids are
    parameters, the widget table is the only table, and nothing a caller could
    have influenced is in the string.
    """
    scope = ScopeFilter(tenant_id=tenant.pk, org_ids=(root_org.pk,))
    compiled = str(PostgresEngine()._scoped(DECLARATION, scope=scope).query)

    assert "example_widget" in compiled
    assert "tenant_id" in compiled
    assert "organization_id" in compiled


# --- 5 · the real-column degradation drive ------------------------------------


def test_the_widget_list_still_answers_from_postgres_when_the_index_is_down(
    api: Client, owner: User, tenant: Tenant, owner_actor: Actor, dead: DeadEngine
) -> None:
    """R-d's circuit, over the wire, on a model that declares the real column.

    Meili unreachable → the same request is answered at `200` from the generated
    column, `engine` says `postgres` so the degradation is announced rather than
    hidden, and the transition reaches the spine as `search.engine.degraded`.
    """
    widget = create_widget(
        tenant=tenant, actor=owner_actor, name="Hydraulic sprocket", notes="steel mount"
    )
    api.force_login(owner)

    response = api.get(SEARCH_URL, {"q": "sprocket", "kinds": "widgets", "include_count": "true"})

    assert response.status_code == 200
    page = body(response)
    assert page["engine"] == "postgres"
    assert [hit["id"] for hit in page["items"]] == [str(widget.pk)]
    assert page["items"][0]["kind"] == "widgets"
    assert page["items"][0]["label"] == "Hydraulic sprocket"
    assert page["count"] == 1
    assert dead.queries == ["sprocket"]
    assert Event.objects.filter(tenant=tenant, name=SEARCH_ENGINE_DEGRADED).count() == 1


def test_the_declared_weights_rank_the_fallback_the_way_they_rank_the_index(
    tenant: Tenant, owner_actor: Actor, dead: DeadEngine
) -> None:
    """`A` over `B`: a word in the name outranks the same word in the notes.

    This is the assertion that makes the weights load-bearing rather than
    decorative — and the one that would go red if the generated column were
    built without `setweight`, which is exactly the drift section 1 pins the
    spelling of and this one pins the behaviour of.
    """
    in_the_name = create_widget(
        tenant=tenant, actor=owner_actor, name="Flange assembly", notes="unrelated text"
    )
    in_the_notes = create_widget(
        tenant=tenant, actor=owner_actor, name="Bracket", notes="fits a flange"
    )

    page = selectors.search(tenant=tenant, actor=owner_actor, q="flange", kinds=["widgets"])

    assert page.engine == "postgres"
    assert [hit.id for hit in page.items] == [in_the_name.pk, in_the_notes.pk]
    assert page.items[0].rank > page.items[1].rank


def test_the_fallback_keeps_both_walls_it_was_handed(
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    stranger_actor: Actor,
    root_org: Organization,
    dead: DeadEngine,
) -> None:
    """What you can see does not change when the engine does.

    The neighbouring tenant and the sibling BRANCH are both absent, and the
    second one is the half a tenant-only assertion would pass without: `Widget`
    is org-scoped, so a fallback that applied `tenant_id` alone would hand a
    branch its whole tenant the moment the index went down.
    """
    mine = create_widget(tenant=tenant, actor=owner_actor, name="Sprocket here", notes="")
    create_widget(tenant=other_tenant, actor=stranger_actor, name="Sprocket next door", notes="")

    sibling = create_organization(
        tenant=tenant, parent=root_org, name="Sibling", slug="sibling", actor=owner_actor
    )
    from apps.accounts.services import create_user

    neighbour = create_user(
        email="sibling@acme.com",
        password="a-long-enough-password-for-validators",  # pragma: allowlist secret
    )
    add_membership(
        user=neighbour,
        tenant=tenant,
        organization=sibling,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=owner_actor,
    )
    sibling_actor = actor_for(user=neighbour, tenant=tenant, org=sibling)
    create_widget(tenant=tenant, actor=sibling_actor, name="Sprocket sideways", notes="")

    from_the_root = selectors.search(
        tenant=tenant, actor=owner_actor, q="sprocket", kinds=["widgets"]
    )
    from_the_branch = selectors.search(
        tenant=tenant, actor=sibling_actor, q="sprocket", kinds=["widgets"]
    )

    assert from_the_root.engine == "postgres"
    assert mine.pk in {hit.id for hit in from_the_root.items}
    assert {hit.label for hit in from_the_root.items} == {"Sprocket here", "Sprocket sideways"}
    assert {hit.label for hit in from_the_branch.items} == {"Sprocket sideways"}
