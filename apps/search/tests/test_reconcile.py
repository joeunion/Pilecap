"""The declaration-digest startup reconcile, planted both ways.

`design-agreements.md`'s "Search materializes
from its declarations" is one sentence with two failure modes, and this module
exists because only one of them is obvious.

**The obvious one:** an index that is missing, or built from a declaration this
build no longer holds, must be rebuilt. If it is not, search answers from
whatever happens to be out there — which on a fresh checkout is nothing, and
after a deploy is yesterday's ranking.

**The one that actually bites:** a matching digest must do *nothing*. A reconcile
that rebuilt on every boot would be correct and unusable — every deploy would
re-stream every table, every worker restart would compete with its siblings for
the container, and the whole mechanism would be turned off within a week. So the
no-op is asserted as a **write count of zero**, against a recording engine, and
not inferred from a log line or from how long it took.

The last test here runs against the **real Meilisearch container** on
`MEILI_URL`, because the two above are only as true as the engine's `state()`
is, and `state()` is a claim about somebody else's server.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

import pytest

from apps.search import activities, registry
from apps.search.activities import (
    CREATED,
    REBUILT,
    UNCHANGED,
    document_for,
    list_search_kinds,
    reconcile_search_index,
    reconcile_workflow_id,
)
from apps.search.types import IndexState, RecordingEngine, ScopeFilter, Searchable

from .conftest import ORGS, WIDGETS, World

pytestmark = pytest.mark.django_db


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> RecordingEngine:
    """The reconcile's engine, recording. Patched where the activity reads it."""
    recorder = RecordingEngine()
    from apps.search import engine as engine_module

    monkeypatch.setattr(engine_module, "engine", lambda: recorder)
    return recorder


# --- the digest itself ---------------------------------------------------------


def test_the_digest_moves_when_a_rebuild_would_change_the_index(
    declared: tuple[Searchable, ...],
) -> None:
    """Reordering the fields is a different ranking, so it is a different digest.

    Declaration order IS the ranking. A digest that ignored order would let a
    deploy change what comes first and leave every index alone.
    """
    reordered = replace(WIDGETS, fields=[("notes", "B"), ("name", "A")])
    assert registry.declaration_digest(WIDGETS) != registry.declaration_digest(reordered)


def test_the_digest_does_not_move_for_a_change_no_rebuild_could_fix(
    declared: tuple[Searchable, ...],
) -> None:
    """`refresh_on` changes what happens NEXT, never what is already indexed.

    A digest that moved for reasons a rebuild cannot address would rebuild every
    index on a change to the event names, and everybody would learn to ignore
    it. The honesty of the mechanism is the reason anybody will leave it on.
    """
    resubscribed = replace(WIDGETS, refresh_on=("example.widget.updated",))
    assert registry.declaration_digest(WIDGETS) == registry.declaration_digest(resubscribed)


def test_the_scope_shape_is_inside_the_digest(declared: tuple[Searchable, ...]) -> None:
    """An org-scoped kind and a tenant-scoped one cannot share a digest.

    They cannot share `filterableAttributes` either — one filters on `org_id`
    and the other must not be able to — so an index built for one and reused for
    the other is exactly the drift this digest exists to catch.
    """
    assert registry.declaration_digest(WIDGETS) != registry.declaration_digest(ORGS)
    assert registry.filterable_attributes(ORGS) == ("tenant_id",)
    assert registry.filterable_attributes(WIDGETS) == ("tenant_id", "org_id")


def test_bumping_the_digest_version_stales_every_index(
    declared: tuple[Searchable, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The honest half: a build can change without any declaration changing.

    The day this app starts putting one more attribute into a document, every
    index in every deployment is stale and nothing in any app has moved.
    `DIGEST_VERSION` is how a build says so.
    """
    before = registry.declaration_digest(WIDGETS)
    monkeypatch.setattr(registry, "DIGEST_VERSION", registry.DIGEST_VERSION + 1)
    assert registry.declaration_digest(WIDGETS) != before


# --- the three answers ---------------------------------------------------------


def test_a_missing_index_is_built_from_the_declaration(
    world: World, declared: tuple[Searchable, ...], engine: RecordingEngine
) -> None:
    """No index → `created`, and the whole rebuild sequence in order.

    The order is the assertion, not just the membership: staging is made first,
    documents go into staging, and the swap is LAST. A swap before the documents
    would make the live index the empty one.
    """
    outcome = reconcile_search_index("widgets")

    assert outcome == CREATED
    assert [call for call, _ in engine.writes] == [
        "begin_rebuild",
        "stage",
        "swap",
    ]
    assert {document["label"] for document in engine.staged} == {
        "Widget at acme",
        "Widget at region",
        "Widget at sibling",
    }


def test_a_matching_digest_is_a_proven_no_op(
    world: World, declared: tuple[Searchable, ...], engine: RecordingEngine
) -> None:
    """The half the whole mechanism's usability rests on: **zero writes.**

    Asserted as an empty write log rather than as a returned word, because the
    word is what the code says about itself and the write log is what it did.
    """
    engine.states["widgets"] = IndexState(
        label="widgets", exists=True, digest=registry.declaration_digest(WIDGETS)
    )

    assert reconcile_search_index("widgets") == UNCHANGED
    assert engine.writes == [], "a matching digest rebuilt anyway"
    assert engine.staged == []


def test_a_digest_that_differs_rebuilds(
    world: World, declared: tuple[Searchable, ...], engine: RecordingEngine
) -> None:
    """An index built from a declaration this build no longer holds → `rebuilt`.

    Distinguished from `created` on purpose: "there was nothing" and "there was
    something wrong" are two different pieces of news for whoever is reading the
    run's result after a deploy.
    """
    engine.states["widgets"] = IndexState(label="widgets", exists=True, digest="from-last-week")

    assert reconcile_search_index("widgets") == REBUILT
    assert ("swap", "widgets") in engine.writes


def test_an_index_with_no_digest_at_all_reads_as_different(
    world: World, declared: tuple[Searchable, ...], engine: RecordingEngine
) -> None:
    """An index built before digests existed is stale, not trusted.

    The alternative — treating a missing sentinel as "probably fine" — is how a
    reconcile learns to leave exactly the indexes it cannot vouch for alone.
    """
    engine.states["widgets"] = IndexState(label="widgets", exists=True, digest="")
    assert reconcile_search_index("widgets") == REBUILT


def test_a_kind_that_vanished_mid_reconcile_is_not_an_error(
    world: World, declared: tuple[Searchable, ...], engine: RecordingEngine
) -> None:
    """A deploy landing between the enumeration and the reconcile of one kind.

    Failing here would make every mid-deploy boot look like an outage. The next
    boot enumerates the truth, which is the whole point of a reconcile.
    """
    assert reconcile_search_index("a-kind-nobody-declares") == UNCHANGED
    assert engine.writes == []


# --- the document a rebuild writes ---------------------------------------------


def test_the_document_is_lean_and_carries_no_path(
    world: World, declared: tuple[Searchable, ...]
) -> None:
    """`id`, `tenant_id`, `org_id`, `label`, the declared fields. **No path, ever.**

    A materialized path in a document would make re-parenting an organization a
    bulk rewrite of every document beneath it — and it would put Postgres's
    private vocabulary inside somebody else's server. The assertion is on the
    KEY SET, so a field added by accident fails here rather than in production.
    """
    widget = WIDGETS.model.objects.for_tenant(world.tenant).first()
    document = document_for(WIDGETS, widget)

    assert set(document) == {"id", "tenant_id", "org_id", "label", "name"}
    assert world.root.path not in str(document)
    assert document["tenant_id"] == str(world.tenant.pk)


def test_a_tenant_scoped_kind_gets_no_org_id(
    world: World, declared: tuple[Searchable, ...]
) -> None:
    """The document's shape follows the model, exactly as the filter's does."""
    org = ORGS.model.objects.for_tenant(world.tenant).first()
    assert "org_id" not in document_for(ORGS, org)


# --- the machinery around it ---------------------------------------------------


def test_the_enumeration_is_the_registry(world: World, declared: tuple[Searchable, ...]) -> None:
    """The workflow's first activity returns exactly what this build declares."""
    assert list_search_kinds() == ["widgets", "orgs"]


def test_the_rebuild_workflow_id_is_deterministic_and_per_queue() -> None:
    """One rebuild across N booting workers, and never two deployments' one run.

    Deterministic is what makes the first half true — every worker derives the
    same id — and per-queue is what makes the second: two checkouts polling two
    queues must not collide on one execution.
    """
    first = reconcile_workflow_id("djb-alpha")
    again = reconcile_workflow_id("djb-alpha")
    other = reconcile_workflow_id("djb-beta")

    assert first == again
    assert first != other
    assert first.startswith("platform:search:reconcile:")
    assert len(first.split(":")) == 4


def test_the_schedule_declares_skip_on_overlap() -> None:
    """Two reconciles at once would both rebuild the same index into one staging uid."""
    from temporalio.client import ScheduleActionStartWorkflow, ScheduleOverlapPolicy

    schedule = activities.reconcile_schedule("djb-alpha")
    assert schedule.policy is not None
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP
    # Narrowed rather than duck-typed: `Schedule.action` is the union of every
    # action kind Temporal has, and only the start-a-workflow one carries an id.
    action = schedule.action
    assert isinstance(action, ScheduleActionStartWorkflow)
    assert action.id == reconcile_workflow_id("djb-alpha")


def test_the_workflow_owns_no_run_row() -> None:
    """House rule 28's second population, declared rather than forgotten.

    A schedule-started run has no `WorkflowRun`: no service asked for it and
    nobody is waiting on a visibility row for the deployment's own housekeeping.
    """
    from apps.search.workflows import ReconcileSearchIndexesWorkflow

    assert ReconcileSearchIndexesWorkflow.owns_no_run is True


# --- against the real container ------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_reconcile_materializes_a_real_index_and_then_no_ops(
    world: World, live_label: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole ruling, end to end, against the Meilisearch on `MEILI_URL`.

    The two recorded tests above are only as true as `state()` is, and `state()`
    is a claim about somebody else's server: that a missing index answers
    `index_not_found` and not something else, that a settings update settles,
    that the sentinel document comes back. This is where that claim is measured.

    Both directions in one test, deliberately: the second call is the one that
    matters, and running it against a *freshly built by us* index is the only
    way to know the digest we wrote is the digest we read.
    """
    if not os.environ.get("MEILI_URL"):
        pytest.skip("no MEILI_URL — the search organ is not configured for this checkout")

    from apps.search import engine as engine_module

    declaration = Searchable(
        model=WIDGETS.model, label=live_label, fields=[("name", "A")], display="name"
    )
    monkeypatch.setattr(registry, "declarations", lambda: (declaration,))
    live = engine_module.engine()

    try:
        assert live.state(label=live_label).exists is False, (
            "a fresh label already has an index — the per-test label is not unique"
        )

        assert reconcile_search_index(live_label) == CREATED

        built = live.state(label=live_label)
        assert built.exists is True
        assert built.digest == registry.declaration_digest(declaration)
        assert built.documents >= 3, "the rebuild stamped a digest over an empty index"

        # And now the half that makes the mechanism usable rather than merely
        # correct: asked again, it does nothing at all.
        assert reconcile_search_index(live_label) == UNCHANGED

        # The documents really are findable, under the injected filter and only
        # under it — which is what makes the index worth materializing.
        expression = engine_module.scope_expression(
            ScopeFilter(
                tenant_id=world.tenant.pk,
                org_ids=(world.root.pk, world.region.pk, world.branch.pk, world.sibling.pk),
            )
        )
        found = live._search_one(
            kind=live_label, q="Widget", expression=expression, offset=0, limit=10
        )
        assert found["hits"], "the rebuilt index answered nothing for a term it holds"
    finally:
        # Each drop in its own `try`: a cleanup whose first call raised would
        # leak the second, and a leaked index outlives the checkout that made
        # one — `scripts/sweep.sh` has no Meili class yet, so this is the whole
        # of the tidying. (Measured: an earlier RED run of this file left
        # exactly one orphaned `_staging` index behind for that reason.)
        for uid in (
            engine_module.index_name(live_label),
            engine_module.staging_index_name(live_label),
        ):
            try:
                live.drop_index(uid=uid)
            except Exception:  # noqa: BLE001 - a cleanup that raises hides the real failure
                pass


# --- The world the suite measures, and the pass that always ends -------------------
#
# Three things went wrong together and each of the tests below
# holds one of them shut.
#
# 1. `engine.py` read `MEILI_URL` and `MEILI_MASTER_KEY` out of `os.environ`,
#    so the suite dialled whatever the developer's `.env` said — the ONE
#    external service outside `config/settings/test.py`'s pin.
# 2. `RECONCILE_RETRY` had no `maximum_attempts`, so a refusing engine was
#    retried for ever INSIDE one run and the run never completed.
# 3. **Two different triggers, one spin.** A black-holed address refuses the
#    connection; a reachable engine with the wrong key — or no key, against a
#    keyed container, which is the compose posture — answers `401
#    invalid_api_key`. Both are the world saying no, both must read the same
#    way, and the second is the one that actually bit: main's `.env` carried no
#    MEILI lines at all, so the default address answered and the absent key was
#    refused.


def test_the_ambient_test_world_has_no_search_index() -> None:
    """The pin, asserted where a reader will look for it.

    Both halves: a pinned URL with an ambient KEY is the same escape, because a
    key is what decides whether a reachable engine answers or refuses. Port 1 is
    the TCP port-reservation port — nothing may listen, so the connection is
    refused rather than hanging on a SYN timeout.
    """
    from django.conf import settings

    assert settings.MEILI_URL == "http://127.0.0.1:1"
    assert settings.MEILI_MASTER_KEY == ""


def test_the_engine_reads_settings_and_not_the_environment(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 33's fence held, and the pin made reachable.

    Planted in both directions in one test: an environment variable that
    disagrees with settings must change NOTHING, and moving settings must change
    everything. Before the fix the first pair failed — which is precisely how a
    developer's `.env` came to configure the gate.
    """
    from apps.search import engine as engine_module

    monkeypatch.setenv("MEILI_URL", "http://10.255.255.1:7700")
    monkeypatch.setenv("MEILI_MASTER_KEY", "an-ambient-key-nobody-asked-for")

    assert engine_module.meili_url() == "http://127.0.0.1:1"
    assert engine_module.meili_master_key() == ""

    settings.MEILI_URL = "http://127.0.0.1:7788"
    settings.MEILI_MASTER_KEY = "a-key-this-test-chose"
    assert engine_module.meili_url() == "http://127.0.0.1:7788"
    assert engine_module.meili_master_key() == "a-key-this-test-chose"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_refusing_engine_completes_the_pass_with_a_finding() -> None:
    """The run ENDS, and carries the bad news. Driven with a refusing activity.

    What is under test is the workflow's choice, not the engine — the
    conventions' form for workflow decision logic, and
    `apps/core/tests/test_integrations.py` is the sibling this copies.

    Previously this test could not have been written: an activity that
    raises was retried without bound, so the execution never reached a
    completion event at all and `execute_workflow` would have hung until the
    client gave up.
    """
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from apps.search.workflows import (
        LIST_KINDS_ACTIVITY,
        RECONCILE_ACTIVITY,
        ReconcileSearchIndexesWorkflow,
    )

    @activity.defn(name=LIST_KINDS_ACTIVITY)
    async def two_kinds() -> list[str]:
        return ["widgets", "orgs"]

    @activity.defn(name=RECONCILE_ACTIVITY)
    async def refusing(kind: str) -> str:
        raise RuntimeError("Meilisearch refused a read: invalid_api_key")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="reconcile-refusal",
            workflows=[ReconcileSearchIndexesWorkflow],
            activities=[two_kinds, refusing],
        ):
            outcome = await env.client.execute_workflow(
                ReconcileSearchIndexesWorkflow.run,
                id="reconcile-refusal-1",
                task_queue="reconcile-refusal",
            )

    assert not outcome.is_complete
    assert "invalid_api_key" in outcome.incomplete, (
        "the pass completed but says nothing about WHY. Temporal's wrapper alone is "
        "`Activity task failed`, which is true and useless six weeks later — `_reason` "
        "walks the cause chain for exactly this."
    )
    assert outcome.incomplete.startswith("widgets:"), "the finding names the kind it is about"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_pass_that_reconciles_some_kinds_and_not_others_says_both() -> None:
    """Partial is said as partial: one of two is not the same fact as none."""
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from apps.search.workflows import (
        LIST_KINDS_ACTIVITY,
        RECONCILE_ACTIVITY,
        ReconcileSearchIndexesWorkflow,
    )

    @activity.defn(name=LIST_KINDS_ACTIVITY)
    async def two_kinds() -> list[str]:
        return ["widgets", "orgs"]

    @activity.defn(name=RECONCILE_ACTIVITY)
    async def one_of_each(kind: str) -> str:
        if kind == "orgs":
            raise RuntimeError("Meilisearch did not answer")
        return "unchanged"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="reconcile-partial",
            workflows=[ReconcileSearchIndexesWorkflow],
            activities=[two_kinds, one_of_each],
        ):
            outcome = await env.client.execute_workflow(
                ReconcileSearchIndexesWorkflow.run,
                id="reconcile-partial-1",
                task_queue="reconcile-partial",
            )

    assert outcome.outcomes == {"widgets": "unchanged"}
    assert outcome.incomplete.startswith("orgs:")


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_healthy_pass_carries_its_outcomes_and_no_finding() -> None:
    """The other half, so neither test above can pass by the run always failing."""
    from temporalio import activity
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    from apps.search.workflows import (
        LIST_KINDS_ACTIVITY,
        RECONCILE_ACTIVITY,
        ReconcileSearchIndexesWorkflow,
    )

    @activity.defn(name=LIST_KINDS_ACTIVITY)
    async def one_kind() -> list[str]:
        return ["widgets"]

    @activity.defn(name=RECONCILE_ACTIVITY)
    async def unchanged(kind: str) -> str:
        return "unchanged"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="reconcile-healthy",
            workflows=[ReconcileSearchIndexesWorkflow],
            activities=[one_kind, unchanged],
        ):
            outcome = await env.client.execute_workflow(
                ReconcileSearchIndexesWorkflow.run,
                id="reconcile-healthy-1",
                task_queue="reconcile-healthy",
            )

    assert outcome.outcomes == {"widgets": "unchanged"}
    assert outcome.is_complete


@pytest.mark.django_db(transaction=True)
def test_an_unreachable_engine_and_a_refused_key_are_the_same_class(live_meili: str) -> None:
    """**The two triggers, proved equal at the engine.** Against the real container.

    This is the assertion the sharpened retry policy asked for. The workflow's
    `except Exception` treats them the same by construction, but "by
    construction" is only true while both really do raise — and an auth refusal
    arrives as a `MeilisearchApiError`, which is the SAME class `state()` reads
    to mean "no such index" and answers with `exists=False` rather than an
    error. One line in `_is_index_not_found` stands between a 401 and a silent
    "there is no index here, rebuild it", which against a keyed engine would be
    an infinite REBUILD loop rather than an infinite retry loop — the same spin
    wearing a different hat.

    So: a wrong key against a REACHABLE engine must be `EngineUnavailable`, and
    it must not read as `exists=False`.
    """
    from django.test import override_settings

    from apps.search import engine as engine_module
    from apps.search.types import EngineUnavailable

    with override_settings(MEILI_URL=live_meili, MEILI_MASTER_KEY="deliberately-the-wrong-key"):
        with pytest.raises(EngineUnavailable) as refused:
            engine_module.MeiliEngine().state(label="a-kind-that-does-not-exist")

    assert "invalid_api_key" in str(refused.value), (
        "the refusal does not name the auth failure — if this ever read as "
        "`index_not_found` the reconcile would rebuild for ever instead"
    )

    with override_settings(MEILI_URL="http://127.0.0.1:1", MEILI_MASTER_KEY=""):
        with pytest.raises(EngineUnavailable):
            engine_module.MeiliEngine().state(label="a-kind-that-does-not-exist")
