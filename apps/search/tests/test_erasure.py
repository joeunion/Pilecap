"""Erasure reaches the index. **Proved by reading the engine, never the selector.**

This module exists because of one failure mode, and every assertion in it is
shaped around that failure mode rather than around the code:

    the document survives in the shared index, and only the filter hides it.

A test that asked `selectors.search` whether the erased tenant's rows were gone
would pass in exactly that case — the chokepoint injects `tenant_id`, the erased
tenant is not the caller, the page is empty, and the document is sitting there
for anybody the filter does let in. So the absence is asserted through
`apps.search.engine` directly, which is what rule 33's allow-list means when it
names `apps/search/tests/`: the fence's own test scope reaches the real thing,
because a fence proved against a double is proved against something that cannot
fail.

Two tiers, and both are here on purpose:

* the **recorded** tier proves the ROUND TRIP — what filter the purge queries
  under, that it deletes what it was handed, and that a second run is a read and
  no writes. It runs in every `--loop` gate;
* the **live** tier proves the ABSENCE, against the Meilisearch container on
  `MEILI_URL`, with an unfiltered document count as the witness. It is an organ
  test (`live_label`), so it is derived into the slow tier and runs at push.

The recorded tier alone would be the mistake this module is about: it would
prove the calls were made and say nothing about whether the server obeyed them.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

import pytest

from apps.core.actor import system_actor
from apps.search import engine as engine_module
from apps.search import registry
from apps.search.activities import reconcile_search_index
from apps.search.services import PURGE_BATCH, delete_tenant_documents
from apps.search.types import EngineHit, RecordingEngine, ScopeFilter, Searchable

from .conftest import WIDGETS, World

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import Tenant

pytestmark = pytest.mark.django_db


# --- the recorded tier: the round trip ----------------------------------------


def test_the_purge_queries_the_tenant_alone_and_deletes_what_it_is_handed(
    world: World, declared: tuple[Searchable, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The filter is `tenant_id` and nothing else, and every kind is visited.

    `org_ids is None` is the assertion that matters. An erasure narrowed by the
    ACTOR's hat would empty the branch the operator happens to be standing in
    and leave the rest of the tenant in the index — an erasure that looks like
    it worked and did a fraction of the job, which is the worst shape this
    function could have. So the actor handed in here is deliberately the one
    standing in a BRANCH, not at the root: if the hat reached the filter, this
    is the test that would say so.
    """
    engine = _DrainingEngine(remaining={"widgets": [uuid4(), uuid4()], "orgs": [uuid4()]})
    monkeypatch.setattr(engine_module, "engine", lambda: engine)

    deleted = delete_tenant_documents(tenant=world.tenant, actor=world.region_actor)

    assert [scope.org_ids for scope in engine.filters] == [None] * len(engine.filters)
    assert {scope.tenant_id for scope in engine.filters} == {world.tenant.pk}
    assert [label for method, label in engine.writes if method == "delete"] == [
        "widgets",
        "orgs",
    ]
    assert deleted == 3


def test_a_second_purge_reads_once_per_kind_and_writes_nothing(
    world: World, declared: tuple[Searchable, ...], recording: RecordingEngine
) -> None:
    """Idempotence, proved as a write count of zero rather than as "no error".

    This is the property that makes the purge safe to retry, safe to run from a
    belt, and safe to run twice by accident — and the same no-op criterion is
    the precedent for proving it this way: an empty `writes` list is the
    assertion, not a log line somebody read.
    """
    delete_tenant_documents(tenant=world.tenant, actor=world.owner_actor)

    assert recording.writes == []
    assert len(recording.queries) == len(registry.labels())


def test_the_purge_keeps_asking_until_the_engine_says_there_are_none(
    world: World, declared: tuple[Searchable, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tenant larger than one window is emptied, not topped.

    The engine is asked at `offset=0` every round because the previous round's
    documents are gone; a purge that paged forward would skip exactly as many
    documents as it deleted, and would look completely correct on a tenant that
    fits in one window. Which is every tenant in every test anybody writes.
    """
    remaining = [uuid4() for _ in range(PURGE_BATCH + 3)]
    engine = _DrainingEngine(remaining={"widgets": list(remaining), "orgs": []})
    monkeypatch.setattr(engine_module, "engine", lambda: engine)

    deleted = delete_tenant_documents(tenant=world.tenant, actor=world.owner_actor)

    assert deleted == len(remaining)
    assert engine.remaining["widgets"] == []
    assert engine.rounds["widgets"] == 3, "one window, the remainder, and the empty confirmation"


class _DrainingEngine(RecordingEngine):
    """A `RecordingEngine` that actually forgets what it was told to delete.

    The plain recording double answers every query with the same hits for ever,
    which is right for a filter probe and useless for a convergence probe: a
    purge tested against it either loops or is written not to. This one holds
    state, so "does it converge" is a question the test can ask.
    """

    def __init__(self, *, remaining: dict[str, list[UUID]]) -> None:
        super().__init__()
        self.remaining = remaining
        self.rounds: dict[str, int] = {}

    def query(self, *, kinds, q, scope, offset, limit):  # type: ignore[no-untyped-def]
        label = kinds[0]
        self.rounds[label] = self.rounds.get(label, 0) + 1
        self.filters.append(scope)
        left = self.remaining.get(label, [])
        window = left[:limit]
        from apps.search.types import EngineHits

        return EngineHits(
            hits=tuple(EngineHit(kind=label, id=one, label="x") for one in window),
            total=len(left),
            offset=0,
            has_more=len(left) > limit,
            engine=self.name,
        )

    def delete(self, *, label, ids):  # type: ignore[no-untyped-def]
        self.writes.append(("delete", label))
        gone = set(ids)
        self.remaining[label] = [one for one in self.remaining.get(label, []) if one not in gone]


# --- the live tier: the absence, read out of the engine ------------------------


def _skip_without_meili() -> None:
    if not os.environ.get("MEILI_URL"):
        pytest.skip("no MEILI_URL — the search organ is not configured for this checkout")


@pytest.mark.django_db(transaction=True)
def test_an_erased_tenants_documents_leave_the_shared_index(
    live_label: str, tenant: Tenant, other_tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The criterion, against the real container: **gone from the index, not hidden.**

    The witness is `state().documents` — the index's own count of everything it
    holds, under no filter at all. If the purge had merely made the documents
    unreachable through the chokepoint, that number would not move and this test
    would fail, which is the whole reason it is the number being asserted.

    The neighbour tenant is in the same index throughout. Erasing one customer
    out of a shared index and taking a second one's rows with it is the other
    failure this pins, and it is the one a per-tenant index would have made
    impossible and a `tenant_id` filter has to be trusted for.
    """
    _skip_without_meili()

    declaration = Searchable(
        model=WIDGETS.model, label=live_label, fields=[("name", "A")], display="name"
    )
    monkeypatch.setattr(registry, "declarations", lambda: (declaration,))
    live = engine_module.engine()

    mine = [uuid4() for _ in range(3)]
    theirs = [uuid4() for _ in range(2)]
    try:
        live.apply_settings(declaration=declaration, digest="erasure-probe")
        live.upsert(
            label=live_label,
            documents=[
                *(_document(one, tenant.pk, "Left-handed sprocket") for one in mine),
                *(_document(one, other_tenant.pk, "Left-handed sprocket") for one in theirs),
            ],
        )
        assert live.state(label=live_label).documents == 5

        deleted = delete_tenant_documents(tenant=tenant, actor=system_actor(tenant=tenant))

        assert deleted == 3
        # (1) The raw, unfiltered count: the documents left the index. This is
        # the assertion a scoped read cannot make.
        assert live.state(label=live_label).documents == 2, (
            "the erased tenant's documents are still in the shared index — a scoped "
            "read would have reported them absent and been wrong"
        )
        # (2) And nothing answers under the erased tenant's own filter, which is
        # the same question asked the way a caller would ask it.
        gone = live.query(
            kinds=[live_label],
            q="sprocket",
            scope=ScopeFilter(tenant_id=tenant.pk),
            offset=0,
            limit=10,
        )
        assert gone.hits == ()
        assert gone.total == 0
        # (3) The neighbour is untouched, by id and not merely by count.
        survived = live.query(
            kinds=[live_label],
            q="sprocket",
            scope=ScopeFilter(tenant_id=other_tenant.pk),
            offset=0,
            limit=10,
        )
        assert sorted(hit.id for hit in survived.hits) == sorted(theirs)
    finally:
        _drop(live_label)


@pytest.mark.django_db(transaction=True)
def test_rebuilding_after_an_erasure_does_not_resurrect_anything(
    live_label: str, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The convergence criterion: re-run the reconcile, and the tenant stays gone.

    This is the half a purge alone cannot promise. The reconcile rebuilds each
    index FROM POSTGRES, so if the erasure left the rows behind, the very next
    hourly tick would put every document back and the purge would read as a
    fix that undoes itself. The rows are gone here — that is what erasing a
    tenant means — so the rebuild converges on an index with nothing in it, and
    a second rebuild changes nothing again.

    It is also the test that would catch a rebuild reading from a cache, a
    replica or a snapshot: three shapes that all look like "rebuilt from the
    source" and are not.
    """
    _skip_without_meili()

    declaration = Searchable(
        model=WIDGETS.model, label=live_label, fields=[("name", "A")], display="name"
    )
    monkeypatch.setattr(registry, "declarations", lambda: (declaration,))
    live = engine_module.engine()

    try:
        live.apply_settings(declaration=declaration, digest="resurrection-probe")
        live.upsert(
            label=live_label,
            documents=[_document(uuid4(), tenant.pk, "Left-handed sprocket") for _ in range(2)],
        )

        delete_tenant_documents(tenant=tenant, actor=system_actor(tenant=tenant))
        assert live.state(label=live_label).documents == 0

        # No `Widget` exists for this tenant in Postgres — the world fixture is
        # not used here on purpose — so a rebuild from the source is a rebuild
        # into nothing. Twice, because idempotence is the claim.
        reconcile_search_index(live_label)
        assert live.state(label=live_label).documents == 0, "the rebuild resurrected the erased"
        reconcile_search_index(live_label)
        assert live.state(label=live_label).documents == 0
    finally:
        _drop(live_label)


def _document(row_id: UUID, tenant_id: UUID, text: str) -> dict[str, object]:
    """One document in the shape `activities.document_for` builds."""
    return {
        "id": str(row_id),
        "tenant_id": str(tenant_id),
        "org_id": str(uuid4()),
        "label": text,
        "name": text,
    }


def _drop(label: str) -> None:
    """Both indexes, each in its own `try` — `test_engine.py`'s reasoning."""
    live = engine_module.engine()
    for uid in (engine_module.index_name(label), engine_module.staging_index_name(label)):
        try:
            live.drop_index(uid=uid)
        except Exception:  # noqa: BLE001 - a cleanup that raises hides the real failure
            pass
