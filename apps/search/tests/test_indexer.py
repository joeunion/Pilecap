"""The spine tap: what happens to a document when a row changes.

**The one sentence everything here is a consequence of:** the indexer never
trusts the event's payload. It reads the `id` out of it and then re-reads the
row from Postgres, so the document is always what the row says *now*.

Every hard property of the design falls out of that and is proved below rather
than argued: a redelivered event, a `replay_events` sweep and an old event
arriving after a newer write all converge on the same document (there is no
version fence to maintain and no ordering assumption to violate); a row that has
gone or been archived leaves the index rather than rotting behind a filter
nobody applies; and an organization re-parent mutates zero documents, because a
document carries `org_id` and never ancestry.

The last two tests run against the **real Meilisearch** on `MEILI_URL`, through
the **real `DispatchEventWorkflow`**, because everything above is only as true
as the wiring is — a handler that is perfect and unregistered indexes nothing.
"""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.core.actor import system_actor
from apps.core.asyncdb import run_db
from apps.core.models import Organization, Tenant
from apps.core.services import apply_organization_move
from apps.events import schemas as event_schemas
from apps.events import services as event_services
from apps.events.types import DispatchEvent, DispatchOutcome
from apps.example.events import WIDGET_CREATED, WIDGET_DELETED, WIDGET_UPDATED
from apps.example.models import Widget
from apps.example.schemas import WidgetOut
from apps.example.services import create_widget, delete_widget, update_widget
from apps.search import engine as engine_module
from apps.search import registry
from apps.search.activities import document_for, index_event
from apps.search.types import (
    EngineUnavailable,
    IndexState,
    RecordingEngine,
    ScopeFilter,
    Searchable,
)

from .conftest import World

pytestmark = pytest.mark.django_db

#: The kind these tests plant. `refresh_on` names constants from
#: `apps/example/events.py` and never literals — which is house rule 16, and
#: which the registry now refuses at boot when it is broken.
WIDGETS = Searchable(
    model=Widget,
    label="widgets",
    fields=[("name", "A"), ("notes", "B")],
    refresh_on=(WIDGET_CREATED, WIDGET_UPDATED, WIDGET_DELETED),
    display="name",
)


@pytest.fixture
def declared_widgets(monkeypatch: pytest.MonkeyPatch) -> Searchable:
    """One kind, planted at the registry's single discovery seam.

    Patched at `declarations` rather than by writing an `apps/example/search.py`,
    because everything else in the registry — `refresh_map`,
    `searchables_for_event`, `by_label` — is derived from it, so patching here
    exercises the derivation instead of bypassing it.
    """
    monkeypatch.setattr(registry, "declarations", lambda: (WIDGETS,))
    return WIDGETS


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> RecordingEngine:
    """The indexer's engine, recording. Patched at the one factory both callers use."""
    recorder = RecordingEngine()
    monkeypatch.setattr(engine_module, "engine", lambda: recorder)
    return recorder


class CapturingEngine(RecordingEngine):
    """A `RecordingEngine` that also keeps the DOCUMENTS handed to `upsert`.

    This double records that an `upsert` happened, which is what the reconcile's
    proven-no-op needs. The indexer's criteria need the other half — *what* was
    written — so this subclass adds it here rather than changing a double four
    other modules already assert against.
    """

    def __init__(self, *, index_exists: bool = True) -> None:
        super().__init__()
        self.upserted: list[tuple[str, dict[str, Any]]] = []
        self.deleted: list[tuple[str, str]] = []
        #: Whether the kind's index is already out there. `True` by default
        #: because that is the steady state the reconcile leaves behind, and a
        #: double whose default was "nothing exists" would quietly exercise the
        #: first-deploy branch in every test that did not mean to.
        self.index_exists = index_exists

    def state(self, *, label: str) -> IndexState:
        return IndexState(label=label, exists=self.index_exists, digest="whatever-is-out-there")

    def upsert(self, *, label: str, documents: Any) -> None:
        super().upsert(label=label, documents=documents)
        self.upserted.extend((label, dict(document)) for document in documents)

    def delete(self, *, label: str, ids: Any) -> None:
        super().delete(label=label, ids=ids)
        self.deleted.extend((label, str(value)) for value in ids)


@pytest.fixture
def capturing(monkeypatch: pytest.MonkeyPatch) -> CapturingEngine:
    recorder = CapturingEngine()
    monkeypatch.setattr(engine_module, "engine", lambda: recorder)
    return recorder


def envelope_for(*, tenant: Tenant, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """A real spine envelope, built the way the spine builds one.

    `record_event` + `schemas.envelope` rather than a hand-written dict: the
    envelope is the contract between the two apps, and a test that assembled its
    own would keep passing on the day the real one changed shape.
    """
    event = event_services.record_event(
        tenant=tenant, name=name, payload=payload, actor=system_actor(tenant=tenant)
    )
    return event_schemas.envelope(event)


def widget_payload(widget: Widget) -> dict[str, Any]:
    """The payload `apps/example` publishes: the row's own `Out` schema."""
    return dict(WidgetOut.from_orm(widget).model_dump(mode="json"))


# --- routing: most events are nobody's business here ---------------------------


def test_an_event_no_kind_subscribed_to_is_a_silent_no_op(
    world: World, declared_widgets: Searchable, engine: RecordingEngine
) -> None:
    """The spine fans EVERY committed event at this leg. Most are not ours.

    A no-op and not a complaint: an indexer that logged a warning for every
    unsubscribed event would drown the one line that matters in the deployment's
    entire event stream.
    """
    body = envelope_for(
        tenant=world.tenant, name="comms.message.sent", payload={"id": str(uuid4())}
    )

    assert index_event(tenant_id=world.tenant.pk, event=body) is False
    assert engine.writes == []


def test_a_payload_with_no_id_is_refused_without_failing_the_dispatch(
    world: World, declared_widgets: Searchable, engine: RecordingEngine
) -> None:
    """An emitting app that did not publish its `Out` schema.

    A log line and a `False`, not a raise: retrying it would never produce an
    id, and the dispatch it rides on is not this app's to fail.
    """
    body = envelope_for(tenant=world.tenant, name=WIDGET_CREATED, payload={"v": 1})

    assert index_event(tenant_id=world.tenant.pk, event=body) is False
    assert engine.writes == []


# --- criterion 4: the payload's field values are never trusted -----------------


def test_the_document_carries_the_ROW_and_not_the_payload(
    world: World, declared_widgets: Searchable, capturing: CapturingEngine
) -> None:
    """A stale payload, a current row, and the row wins. **The load-bearing test.**

    Everything else in this module is a consequence of this one. The payload
    here says what the row said before an update; the document has to say what
    it says now, because a payload is a snapshot of a moment and an index is a
    claim about the present.
    """
    widget = create_widget(tenant=world.tenant, actor=world.owner, name="Before")
    stale = widget_payload(widget)
    update_widget(
        tenant=world.tenant, actor=world.owner, widget=widget, name="After", notes="fresh"
    )

    body = envelope_for(tenant=world.tenant, name=WIDGET_UPDATED, payload=stale)
    assert index_event(tenant_id=world.tenant.pk, event=body) is True

    assert stale["name"] == "Before", "the fixture must actually be stale for this to mean anything"
    ((_label, document),) = capturing.upserted
    assert document["name"] == "After"
    assert document["notes"] == "fresh"
    assert document["label"] == "After"


# --- criterion 5: at-least-once, and order-free --------------------------------


def test_the_same_event_twice_leaves_one_document_with_current_state(
    world: World, declared_widgets: Searchable, capturing: CapturingEngine
) -> None:
    """At-least-once delivery, and a redelivery that changes nothing.

    The upsert is keyed on the document id and the document is built from
    current state, so a second delivery writes the same bytes to the same id.
    Idempotency here is a property of the shape rather than a check somebody
    remembered to add.
    """
    widget = create_widget(tenant=world.tenant, actor=world.owner, name="Twice")
    body = envelope_for(tenant=world.tenant, name=WIDGET_CREATED, payload=widget_payload(widget))

    assert index_event(tenant_id=world.tenant.pk, event=body) is True
    assert index_event(tenant_id=world.tenant.pk, event=body) is True

    ids = {document["id"] for _label, document in capturing.upserted}
    assert ids == {str(widget.pk)}
    assert {document["name"] for _label, document in capturing.upserted} == {"Twice"}


def test_an_old_event_replayed_after_a_newer_write_converges_forward(
    world: World, declared_widgets: Searchable, capturing: CapturingEngine
) -> None:
    """The order that would break a naive indexer, and the reason there is no fence.

    `replay_events` re-dispatches a stranded row whenever somebody asks it to,
    which means an event from before a later write can arrive after it. An
    indexer that wrote the payload would roll the document backwards. This one
    cannot: it re-reads, so the *stale* event still produces the *current*
    document.
    """
    widget = create_widget(tenant=world.tenant, actor=world.owner, name="v1")
    old = envelope_for(tenant=world.tenant, name=WIDGET_CREATED, payload=widget_payload(widget))
    update_widget(tenant=world.tenant, actor=world.owner, widget=widget, name="v2")
    new = envelope_for(
        tenant=world.tenant,
        name=WIDGET_UPDATED,
        payload=widget_payload(Widget.objects.get(pk=widget.pk)),
    )

    assert index_event(tenant_id=world.tenant.pk, event=new) is True
    assert index_event(tenant_id=world.tenant.pk, event=old) is True

    assert [document["name"] for _label, document in capturing.upserted] == ["v2", "v2"]


# --- criterion 7: gone and archived are one case -------------------------------


def test_a_deleted_row_takes_its_document_with_it(
    world: World, declared_widgets: Searchable, capturing: CapturingEngine
) -> None:
    """The row is gone, so the re-read finds nothing, so the document goes."""
    widget = create_widget(tenant=world.tenant, actor=world.owner, name="Doomed")
    payload = widget_payload(widget)
    delete_widget(tenant=world.tenant, actor=world.owner, widget=widget)

    body = envelope_for(tenant=world.tenant, name=WIDGET_DELETED, payload=payload)
    assert index_event(tenant_id=world.tenant.pk, event=body) is True

    assert capturing.deleted == [("widgets", str(widget.pk))]
    assert capturing.upserted == []


def test_an_archived_row_takes_its_document_with_it_too(
    world: World, capturing: CapturingEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The soft-delete case: absent from every list door means absent from search.

    `comms.Recipient` is borrowed because it is this tree's worked example of an
    archived-not-deleted row and `apps/example` has none — the declaration is a
    plant either way, and the point under test is the `archived_at` branch and
    not which app owns the model. The `refresh_on` name is a real, declared
    comms event for the same reason every other one here is: the registry
    refuses an undeclared name at boot, and a test that dodged that would be
    testing a shape the deployment cannot have.
    """
    from apps.comms.events import MESSAGE_SENT
    from apps.comms.models import Recipient
    from apps.comms.services import archive_recipient, create_recipient

    kind = Searchable(
        model=Recipient,
        label="contacts",
        fields=[("email", "A")],
        refresh_on=(MESSAGE_SENT,),
        display="email",
    )
    monkeypatch.setattr(registry, "declarations", lambda: (kind,))

    recipient = create_recipient(tenant=world.tenant, actor=world.owner, email="closed@acme.com")
    body = envelope_for(tenant=world.tenant, name=MESSAGE_SENT, payload={"id": str(recipient.pk)})

    assert index_event(tenant_id=world.tenant.pk, event=body) is True
    assert [document["email"] for _label, document in capturing.upserted] == ["closed@acme.com"]

    archive_recipient(tenant=world.tenant, actor=world.owner, recipient=recipient)
    assert index_event(tenant_id=world.tenant.pk, event=body) is True
    assert capturing.deleted == [("contacts", str(recipient.pk))]


def test_a_row_in_another_tenant_is_not_reachable_through_the_tap(
    world: World, other_tenant: Tenant, declared_widgets: Searchable, capturing: CapturingEngine
) -> None:
    """The `for_tenant` floor under the re-read, stated as an assertion.

    An envelope naming somebody else's tenant beside our row id must not produce
    a document; it produces a delete, which is the fail-closed answer — the same
    posture `for_tenant(None)` has one level out.
    """
    widget = create_widget(tenant=world.tenant, actor=world.owner, name="Ours")
    body = envelope_for(tenant=world.tenant, name=WIDGET_UPDATED, payload=widget_payload(widget))

    assert index_event(tenant_id=other_tenant.pk, event=body) is True
    assert capturing.upserted == []
    assert capturing.deleted == [("widgets", str(widget.pk))]


# --- the first-deploy window, found live ---------------------------------------


def test_the_first_document_of_a_new_kind_materializes_its_index_first(
    world: World, declared_widgets: Searchable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**A defect measured against the real container, not anticipated.**

    `engine.upsert` creates a missing index with a primary key and nothing else,
    which is right for a rebuild's staging index and wrong here: the document
    lands, `filterableAttributes` is empty, and the very next scoped query dies
    with `Attribute 'org_id' is not filterable`. That is not a stale result — it
    is a 503 for **every kind in the request**, for the whole window between a
    new kind's first deploy and the hourly reconcile reaching it.

    So the tap materializes the index from the declaration before writing into
    it, and the order is what is asserted: settings, then document.
    """
    engine = CapturingEngine(index_exists=False)
    monkeypatch.setattr(engine_module, "engine", lambda: engine)

    widget = create_widget(tenant=world.tenant, actor=world.owner, name="First ever")
    body = envelope_for(tenant=world.tenant, name=WIDGET_CREATED, payload=widget_payload(widget))

    assert index_event(tenant_id=world.tenant.pk, event=body) is True
    assert engine.writes == [("apply_settings", "widgets"), ("upsert", "widgets")]


def test_the_tap_never_rebuilds_a_kind_whose_digest_has_moved(
    world: World, declared_widgets: Searchable, capturing: CapturingEngine
) -> None:
    """It materializes a MISSING index and does nothing else. The reconcile rebuilds.

    `CapturingEngine` answers a digest that matches no declaration, which is the
    deploy-changed-the-fields case. The documents are stale and that is the
    reconcile's job: a tap that rebuilt would re-stream a whole table on the
    first row anybody touched after a deploy.
    """
    widget = create_widget(tenant=world.tenant, actor=world.owner, name="Ordinary")
    body = envelope_for(tenant=world.tenant, name=WIDGET_UPDATED, payload=widget_payload(widget))

    assert index_event(tenant_id=world.tenant.pk, event=body) is True
    assert capturing.writes == [("upsert", "widgets")]


def test_a_delete_against_a_kind_with_no_index_does_nothing_at_all(
    world: World, declared_widgets: Searchable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """There is no document to remove, so creating an index to remove it from
    would be the bug above in its most pointless form."""
    engine = CapturingEngine(index_exists=False)
    monkeypatch.setattr(engine_module, "engine", lambda: engine)

    body = envelope_for(tenant=world.tenant, name=WIDGET_DELETED, payload={"id": str(uuid4())})

    assert index_event(tenant_id=world.tenant.pk, event=body) is True
    assert engine.writes == []


# --- criterion 8: a move changes no document; a reassignment changes one -------


def test_an_organization_re_parent_changes_zero_documents(
    world: World, declared_widgets: Searchable
) -> None:
    """**By construction, and this proves the construction rather than the count.**

    A re-parent changes an organization's ancestry (`path`), not the
    `organization_id` on any row — and a document carries `org_id` and never a
    path. So the document a row produces is byte-identical before and after the
    move, which is *why* zero documents need rewriting; asserting an empty write
    list would only prove that nothing happened to call the indexer.

    The querying side absorbs the move instead: the visible-org-id set is
    resolved from the actor's hat in Postgres per request, so the first query
    after the move already filters against the new subtree.
    """
    widget = create_widget(tenant=world.tenant, actor=world.admin_at_a, name="Under region")
    before = document_for(WIDGETS, widget)
    assert world.a.path != world.a1.path

    apply_organization_move(
        tenant=world.tenant,
        organization=world.a,
        new_parent=world.b,
        actor=world.owner,
    )
    moved = Organization.objects.get(pk=world.a.pk)
    assert moved.parent_id == world.b.pk, "the fixture has to have actually moved"

    after = document_for(WIDGETS, Widget.objects.get(pk=widget.pk))
    assert after == before
    assert "path" not in after and moved.path not in after.values()


def test_a_row_level_org_reassignment_moves_the_document(
    world: World, declared_widgets: Searchable, capturing: CapturingEngine
) -> None:
    """The one case a document's `org_id` DOES change, and it is an ordinary write.

    A row handed from one branch to another is a service write on the row
    itself, which emits the row's own refresh event and converges through the
    ordinary path. No special case, no second mechanism.
    """
    widget = create_widget(tenant=world.tenant, actor=world.owner, name="Handed over")
    payload = widget_payload(widget)

    Widget.objects.filter(pk=widget.pk).update(organization=world.a)

    body = envelope_for(tenant=world.tenant, name=WIDGET_UPDATED, payload=payload)
    assert index_event(tenant_id=world.tenant.pk, event=body) is True

    (_label, document) = capturing.upserted[-1]
    assert document["org_id"] == str(world.a.pk)
    assert payload["organization_id"] != str(world.a.pk), "the payload still says the old one"


# --- criterion 6: a failing engine raises, so Temporal can retry ---------------


def test_an_engine_that_did_not_confirm_RAISES_rather_than_reporting_success(
    world: World, declared_widgets: Searchable, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole reason the retry policy at the call site can do anything.

    `engine.upsert` waits for Meilisearch to settle the task and turns a
    non-success into `EngineUnavailable`. If this handler swallowed that,
    the activity would return `True` for work the server rejected and the retry
    — the only thing standing between a transient failure and a permanently
    stale document — would never fire.
    """

    class Refusing(RecordingEngine):
        def upsert(self, *, label: str, documents: Any) -> None:
            raise EngineUnavailable("Meilisearch failed a task on widgets: failed ({})")

    monkeypatch.setattr(engine_module, "engine", lambda: Refusing())

    widget = create_widget(tenant=world.tenant, actor=world.owner, name="Unlucky")
    body = envelope_for(tenant=world.tenant, name=WIDGET_CREATED, payload=widget_payload(widget))

    with pytest.raises(EngineUnavailable):
        index_event(tenant_id=world.tenant.pk, event=body)


# --- the wiring, against the real container and the real workflow --------------


def _skip_without_meili() -> None:
    if not os.environ.get("MEILI_URL"):
        pytest.skip("no MEILI_URL — the search organ is not configured for this checkout")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_an_emitted_event_puts_a_real_document_in_a_real_index(
    world: World, live_label: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: a widget, an event, the spine, the tap, Meilisearch.

    Nothing here is a double. The workflow is `DispatchEventWorkflow` on a real
    Temporal server, the activity is the discovered `index_search`, the bridge
    is whatever `SearchConfig.ready()` registered in this process, and the index
    is the container on `MEILI_URL`. That is deliberate: every test above is a
    claim about a handler, and a handler that is perfect and unregistered
    indexes nothing.

    Both directions in one test, because the delete half is the one that would
    silently never run: a document that is written and never removed reads as a
    working search right up until somebody finds a deleted row in it.
    """
    _skip_without_meili()

    from temporalio.testing import WorkflowEnvironment

    from apps.workflows.client import attach_interceptors, build_worker
    from apps.workflows.services import start_workflow

    kind = Searchable(
        model=Widget,
        label=live_label,
        fields=[("name", "A")],
        refresh_on=(WIDGET_CREATED, WIDGET_DELETED),
        display="name",
    )
    monkeypatch.setattr(registry, "declarations", lambda: (kind,))
    live = engine_module.engine()
    queue = f"djb-search-{live_label}"

    def make() -> tuple[Widget, dict[str, Any]]:
        widget = create_widget(tenant=world.tenant, actor=world.owner, name="Findable")
        event = event_services.record_event(
            tenant=world.tenant,
            name=WIDGET_CREATED,
            payload=widget_payload(widget),
            actor=system_actor(tenant=world.tenant),
        )
        return widget, {"event_id": str(event.pk)}

    def remove(widget: Widget) -> dict[str, Any]:
        payload = widget_payload(widget)
        delete_widget(tenant=world.tenant, actor=world.owner, widget=widget)
        event = event_services.record_event(
            tenant=world.tenant,
            name=WIDGET_DELETED,
            payload=payload,
            actor=system_actor(tenant=world.tenant),
        )
        return {"event_id": str(event.pk)}

    def found(widget: Widget) -> list[dict[str, Any]]:
        expression = engine_module.scope_expression(
            ScopeFilter(tenant_id=world.tenant.pk, org_ids=(widget.organization_id,))
        )
        answer = live._search_one(
            kind=live_label, q="Findable", expression=expression, offset=0, limit=10
        )
        return list(answer.get("hits", []) or [])

    try:
        widget, started = await run_db(make)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            client = attach_interceptors(env.client)
            async with build_worker(client, queue=queue):
                run = await start_workflow(
                    workflow=event_services.DISPATCH_WORKFLOW,
                    arg=DispatchEvent(event_id=started["event_id"]),
                    tenant=world.tenant,
                    client=client,
                    task_queue=queue,
                    id=f"{world.tenant.slug}:events:event:{started['event_id']}",
                )
                handle = client.get_workflow_handle(run.workflow_id, result_type=DispatchOutcome)
                created: DispatchOutcome = await handle.result()

                assert created.indexed is True, "the spine did not reach the tap"
                hits = await run_db(found, widget)
                assert [hit["id"] for hit in hits] == [str(widget.pk)]

                gone = await run_db(remove, widget)
                run = await start_workflow(
                    workflow=event_services.DISPATCH_WORKFLOW,
                    arg=DispatchEvent(event_id=gone["event_id"]),
                    tenant=world.tenant,
                    client=client,
                    task_queue=queue,
                    id=f"{world.tenant.slug}:events:event:{gone['event_id']}",
                )
                handle = client.get_workflow_handle(run.workflow_id, result_type=DispatchOutcome)
                deleted: DispatchOutcome = await handle.result()

        assert deleted.indexed is True
        assert await run_db(found, widget) == [], "a deleted row is still findable"
    finally:
        # Each drop in its own `try`: a cleanup whose first call raised would
        # leak the second, and a leaked index outlives the checkout that made
        # one — `scripts/sweep.sh` has no Meili class yet, so this is the
        # whole of the tidying.
        for uid in (
            engine_module.index_name(live_label),
            engine_module.staging_index_name(live_label),
        ):
            try:
                live.drop_index(uid=uid)
            except Exception:  # noqa: BLE001, S110 — a cleanup that raises hides the real failure
                pass


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_a_failing_index_is_retried_and_converges_rather_than_being_lost(
    world: World, live_label: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Temporal's retries ARE the catch-up queue** (ADR search-2), demonstrated.

    An engine that refuses the first two writes and accepts the third: the
    document still lands, with nobody running a reindex and nothing dropped. The
    time-skipping environment collapses the backoff, so what is being asserted
    is the convergence and not the wall clock.

    This is half of the outage drill: the drill stops the real
    container, and it can only assert convergence because this seam retries.
    """
    _skip_without_meili()

    from temporalio.testing import WorkflowEnvironment

    from apps.workflows.client import attach_interceptors, build_worker
    from apps.workflows.services import start_workflow

    kind = Searchable(
        model=Widget,
        label=live_label,
        fields=[("name", "A")],
        refresh_on=(WIDGET_CREATED,),
        display="name",
    )
    monkeypatch.setattr(registry, "declarations", lambda: (kind,))
    live = engine_module.engine()
    refusals: list[int] = []

    class FlakyEngine:
        """The real engine, refusing its first two writes. Everything else is real."""

        name = live.name

        def __getattr__(self, attribute: str) -> Any:
            return getattr(live, attribute)

        def upsert(self, *, label: str, documents: Any) -> None:
            refusals.append(1)
            if len(refusals) <= 2:
                raise EngineUnavailable("Meilisearch did not settle a task on widgets.")
            live.upsert(label=label, documents=documents)

    monkeypatch.setattr(engine_module, "engine", FlakyEngine)
    queue = f"djb-search-retry-{live_label}"

    def make() -> tuple[Widget, str]:
        widget = create_widget(tenant=world.tenant, actor=world.owner, name="Persistent")
        event = event_services.record_event(
            tenant=world.tenant,
            name=WIDGET_CREATED,
            payload=widget_payload(widget),
            actor=system_actor(tenant=world.tenant),
        )
        return widget, str(event.pk)

    try:
        widget, event_id = await run_db(make)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            client = attach_interceptors(env.client)
            async with build_worker(client, queue=queue):
                run = await start_workflow(
                    workflow=event_services.DISPATCH_WORKFLOW,
                    arg=DispatchEvent(event_id=event_id),
                    tenant=world.tenant,
                    client=client,
                    task_queue=queue,
                    id=f"{world.tenant.slug}:events:event:{event_id}",
                )
                handle = client.get_workflow_handle(run.workflow_id, result_type=DispatchOutcome)
                outcome: DispatchOutcome = await handle.result()

        assert len(refusals) == 3, "the failures were swallowed instead of retried"
        assert outcome.indexed is True

        def found() -> list[dict[str, Any]]:
            expression = engine_module.scope_expression(
                ScopeFilter(tenant_id=world.tenant.pk, org_ids=(widget.organization_id,))
            )
            answer = live._search_one(
                kind=live_label, q="Persistent", expression=expression, offset=0, limit=10
            )
            return list(answer.get("hits", []) or [])

        assert [hit["id"] for hit in await run_db(found)] == [str(widget.pk)]
    finally:
        for uid in (
            engine_module.index_name(live_label),
            engine_module.staging_index_name(live_label),
        ):
            try:
                live.drop_index(uid=uid)
            except Exception:  # noqa: BLE001, S110 — a cleanup that raises hides the real failure
                pass


# --- the world this module needs beyond the shared one ------------------------


def test_the_planted_kind_is_one_the_registry_would_accept(declared_widgets: Searchable) -> None:
    """A plant the boot refusal would reject proves nothing about the real thing.

    Every fixture in this module is a `Searchable` that a real
    `apps/<x>/search.py` could have held, and this is what says so — the same
    reason the live tests use the real container rather than a fake.
    """
    assert registry.validate([declared_widgets]) == (declared_widgets,)
    with pytest.raises(ImproperlyConfigured):
        registry.validate([Searchable(model=Widget, label="widgets", fields=[("nope", "A")])])
