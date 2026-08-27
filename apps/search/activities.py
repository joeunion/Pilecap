"""The two write paths into the index: the startup reconcile, and the spine tap.

**The reconcile** materializes a kind's whole index from its declaration.
**The indexer** (`index_event`, at the bottom) keeps one document current as
rows change, riding the event spine. They are the same act at two scales and
they share one document builder, which is why they share a file: a rebuild and
a refresh that disagreed about what a document is would be a search that
answered differently depending on when a row was last touched.

**The declaration is the intent; the index is materialized from it**
(`design-agreements.md` — rule 27's shape applied to search). Every act here
serves one sentence: a worker that has just come up
makes the indexes agree with what this build declares, and it does so without
anybody remembering to run anything.

Per kind, one question and three answers:

* **no index** → build it;
* **an index whose stored digest differs from the declaration's** → re-apply the
  settings and rebuild;
* **an index whose digest matches** → nothing at all, and the criterion is that
  the nothing is *proven* — zero write calls, asserted against a recording
  engine, not assumed from a log line.

That is what demotes `manage.py search_reindex` to the **manual backstop**
it now is: still the way to force a rebuild, no longer the only way one happens.
A materializer whose sole trigger is a human remembering is the silent class in
`operating-protocol.md`'s intent-materialization lens; a boot is a moment that
always happens.

**Why the I/O is here and the ordering is in `workflows.py`** (house rule 9): a
workflow may not read a registry, open a socket or ask what time it is, and all
three happen below. The workflow calls these and decides nothing else.

**Rebuilds are serial by construction.** One workflow, one kind at a time, one
task queue — so a deploy that changes five declarations pays five rebuilds in
sequence rather than five concurrent index builds competing for the same
container's memory. The deterministic workflow id is the other half: N workers
booting at once converge on one run rather than N.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from temporalio import activity
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from apps.core.log import get_logger
from apps.core.models import Tenant, is_org_scoped
from apps.core.schedules import ScheduleDeclaration
from apps.search import engine as engine_module
from apps.search import registry
from apps.search.registry import ORG_ATTRIBUTE, TENANT_ATTRIBUTE
from apps.search.types import Searchable

log = get_logger(__name__)

#: How many rows are read and shipped at a time during a rebuild. Small enough
#: that a large table never materialises in memory, large enough that a rebuild
#: is not a million round trips.
REBUILD_BATCH = 500

#: The three outcomes, named so a log line, a test and a report all say the same
#: word. A rebuild that reported "ok" would be indistinguishable from a no-op,
#: which is precisely the distinction this whole mechanism exists to make.
UNCHANGED = "unchanged"
REBUILT = "rebuilt"
CREATED = "created"


def document_for(declaration: Searchable, row: Any) -> dict[str, Any]:
    """One lean document, built from the row's **current** state.

    `id`, `tenant_id`, `org_id` (org-scoped kinds only), `label`, and the
    declared text fields. Nothing else — no snapshot of the row, no relations,
    no counts, and **never a materialized path**: the path is Postgres's private
    vocabulary, and copying it out would turn every re-parent into a bulk
    rewrite of every document beneath the moved node.

    Building from the row rather than from an event payload is what makes the
    whole indexing story idempotent and order-free (the validated registry leans on this): a
    redelivered event, a replay, and an old event arriving after a newer write
    all converge on the same document, because the document is always what the
    row says now.
    """
    document: dict[str, Any] = {
        "id": str(row.pk),
        TENANT_ATTRIBUTE: str(row.tenant_id),
        "label": display_for(declaration, row),
    }
    if is_org_scoped(declaration.model):
        organization = getattr(row, "organization_id", None)
        document[ORG_ATTRIBUTE] = str(organization) if organization else None
    for name, _weight in declaration.fields:
        document[name] = _walk(row, name)
    return document


def display_for(declaration: Searchable, row: Any) -> str:
    """What a hit is CALLED, off the row: the declared `display`, or `str(row)`.

    Public, and it is public because the degradation engine needs the same
    answer (the degradation engine). A hit rendered `Widget object (…)` while Meilisearch is down
    and `Left-handed sprocket` while it is up would be a difference a user sees
    every time this product fails over — the fallback's whole promise is that
    what you can see does not change, and a label is what you see.

    It lives here rather than in `registry.py` because it reads a ROW, and this
    module is the one that walks rows; the registry decides what is declared,
    not what a declared thing looks like today.
    """
    if declaration.display:
        return str(_walk(row, declaration.display) or "")
    return str(row)


def _walk(row: Any, dotted: str) -> Any:
    """`"owner.name"` on a row. A missing link is `None`, never an exception.

    The registry refuses an undeclarable field at import time, which is where
    a typo belongs; by the time a rebuild is walking a million rows, a `None` is
    a better answer than an activity that dies on row 700,000.
    """
    value: Any = row
    for part in dotted.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _rows(declaration: Searchable) -> Iterator[Any]:
    """Every row of a kind, streamed. **Not scoped, and that is correct here.**

    A rebuild materialises the whole index, which holds every tenant's documents
    together — isolation rides the filter injected at *query* time, never the
    topology (ADR search-2). This is the one read in the app that is deliberately
    not `for_tenant(...)`, and it is a write-side walk that returns nothing to
    anybody: no actor is present, no page is composed, and what it produces is
    documents stamped with the `tenant_id` that will fence every later read.
    """
    return iter(
        declaration.model._default_manager.order_by("pk").iterator(chunk_size=REBUILD_BATCH)
    )


@activity.defn
def list_search_kinds() -> list[str]:
    """Which kinds this build declares. The reconcile's first act.

    An activity rather than a workflow-side read because it imports application
    modules — discovery is I/O in every sense that matters to determinism, and a
    workflow that enumerated the registry would replay differently the day an
    app is added.
    """
    return list(registry.labels())


@activity.defn
def reconcile_search_index(label: str) -> str:
    """Make one kind's index agree with its declaration. Returns the outcome word.

    Idempotent by construction, because it is driven by a comparison and not by
    a flag: running it twice in a row does the work once and then reports
    `unchanged`, which is exactly what a Temporal retry needs and exactly what a
    second worker booting a second later needs.
    """
    declaration = registry.by_label(label)
    if declaration is None:
        # A kind that vanished between the enumeration and now — a deploy
        # landing mid-reconcile. Not an error: the next boot enumerates the
        # truth.
        log.info("search.reconcile.kind_gone", kind=label)
        return UNCHANGED
    digest = registry.declaration_digest(declaration)
    engine = engine_module.engine()
    state = engine.state(label=label)
    if state.exists and state.digest == digest:
        log.info("search.reconcile.unchanged", kind=label, digest=digest)
        return UNCHANGED
    outcome = REBUILT if state.exists else CREATED
    log.info(
        "search.reconcile.rebuilding",
        kind=label,
        outcome=outcome,
        found=state.digest or None,
        declared=digest,
    )
    staging = engine.begin_rebuild(declaration=declaration, digest=digest)
    batch: list[dict[str, Any]] = []
    staged = 0
    for row in _rows(declaration):
        batch.append(document_for(declaration, row))
        if len(batch) >= REBUILD_BATCH:
            engine.stage(staging=staging, documents=batch)
            staged += len(batch)
            batch = []
    if batch:
        engine.stage(staging=staging, documents=batch)
        staged += len(batch)
    # The swap is last and it is atomic: queries answer from the old index right
    # up to it and from the new one immediately after, so a rebuild is invisible
    # to everyone except the person reading this log line.
    engine.swap(label=label, staging=staging)
    engine.drop_index(uid=staging)
    log.info("search.reconcile.rebuilt", kind=label, outcome=outcome, documents=staged)
    return outcome


# --- the indexer: what the spine hands us --------------------------------------
#
# `index_event` is the second write-side chokepoint in this module, beside the
# reconcile. It is not an `@activity.defn` and it is not called by a workflow
# here: it is the callable `apps/search/apps.py` registers on `core.bridge` as
# `search.index_event`, and the activity that calls it lives in
# `apps/events/activities.py` — beside the fan-out, where the retry that makes
# it converge is declared (ADR search-2, § "The indexer — riding the spine").
#
# WHY IT IS IN THIS FILE AND NOT IN `services.py`, said plainly because ADR
# search-2 puts the write chokepoints there: house rule 16 requires every public
# function in a `services.py` to begin with a verb from `rules.yaml`'s declared
# lexicon, and `index` is not in it. Adding the verb is a `quality/` edit, which
# is out of scope here — so the ADR's NAME is kept
# (four later criteria cite `index_event`) and the module placement is deferred
# to whoever lands the verb. `reindex` needs it too: the same word.
# `rules.yaml`'s rule-33 allow-list already names this file, for the same reason.


def index_event(*, tenant_id: Any, event: dict[str, Any]) -> bool:
    """Make the documents for one committed event agree with the rows. **The tap.**

    The spine hands over the envelope — the same JSON body a webhook subscriber
    is signed and sent — and this decides everything about it: which kinds
    subscribed to the name, which row it is about, and whether the document is
    written or removed. The events side decides none of that, because none of it
    is knowable without the registry.

    **The payload's field values are never trusted.** Only the `id` is read out
    of it; the document is built by **re-reading the row through the model's own
    `for_tenant` manager** and asking what it says now. That single decision is
    what makes the whole indexing story idempotent and order-free (ADR
    search-2): a redelivered event, a
    `replay_events` sweep, and an old event arriving after a newer write all
    converge on the same document, because the document is always current state.
    There is no version fence to maintain and no ordering assumption to violate.

    **Gone and archived are one case.** A row the tenant-scoped read cannot find
    — deleted, or belonging to somebody else — and a row carrying `archived_at`
    both mean the same thing to a reader: it is absent from every list door, so
    it is absent from search (ADR search-2). The document is deleted rather
    than left to rot behind a filter nobody applies.

    **It returns whether it did anything**, and it raises when the engine did
    not confirm. Returning `False` for "no kind subscribed to this name" is the
    ordinary answer — the spine fans every committed event at this leg — and it
    is a different fact from a raised `EngineUnavailable`, which is the one the
    Temporal retry behind the caller exists to fix.
    """
    kinds = registry.searchables_for_event(str(event.get("name") or ""))
    if not kinds:
        return False
    payload = event.get("payload") or {}
    raw = payload.get("id")
    if raw is None:
        # A payload with no `id` is an emitting app that did not publish its
        # `Out` schema (ADR search-2 assumes it does). A log line and a no-op
        # rather than a raise: retrying it would never produce an id, and the
        # dispatch it rides on is not this app's to fail.
        log.warning("search.index.no_id", event_name=event.get("name"), event_id=event.get("id"))
        return False
    try:
        pk = UUID(str(raw))
    except (TypeError, ValueError):
        log.warning("search.index.bad_id", event_name=event.get("name"), row_id=str(raw))
        return False
    tenant = Tenant.objects.filter(pk=tenant_id).first()
    engine = engine_module.engine()
    for declaration in kinds:
        row = _current_row(declaration, tenant=tenant, pk=pk)
        state = engine.state(label=declaration.label)
        if row is None:
            if not state.exists:
                # Nothing to remove, and creating an index to delete from would
                # be the bug below in its most pointless form.
                continue
            # rule-10: `engine` is a Meilisearch client and this is not a model
            # write — it removes a DOCUMENT from a derived view whose source of
            # record is the row that has already gone. The rule's subject is a
            # door reaching past `services.py` to write a ROW; nothing here can,
            # and the deleting service (`delete_widget`, or whatever archived it)
            # ran before the event this is reacting to was ever committed. The
            # exports archive-write carries the same override for the same
            # reason: not every `.delete()` in the tree is an ORM call.
            engine.delete(label=declaration.label, ids=[pk])
            log.info("search.index.deleted", kind=declaration.label, row_id=str(pk))
            continue
        if not state.exists:
            _materialize(engine, declaration)
        engine.upsert(label=declaration.label, documents=[document_for(declaration, row)])
        log.info("search.index.upserted", kind=declaration.label, row_id=str(pk))
    return True


def _materialize(engine: Any, declaration: Searchable) -> None:
    """Give a kind's index its settings before the first document goes in.

    **MEASURED, not anticipated** (against the container on `MEILI_URL`):
    an `upsert` into a kind whose index does not exist yet creates it with a
    primary key and *nothing else* — no `filterableAttributes` — and the very
    next scoped query dies with `Attribute 'org_id' is not filterable`, which
    `_search_one` correctly reports as `EngineUnavailable` and the door
    turns into a 503. So the window between "a row changed" and "the hourly
    reconcile got to this kind" is not a window of stale results; it is a window
    where **search is down for every kind in the request**. A new kind's first
    deploy is exactly that window.

    The settings are the reconcile's own — one function decides them
    (`registry.index_settings`) and one module applies them — so this is the
    same materialization, done by whichever write path arrives first. It never
    REBUILDS: a digest that has moved means the documents themselves are stale
    and that is the reconcile's job, not the tap's. This one only ever turns "no
    index" into "an index shaped like the declaration".

    THE COST, stated: one `state()` per kind per indexed event, which is three
    small GETs to a container on the same network, on a background activity that
    is on nobody's request path. The cheaper shape is a narrow
    `ensure_configured` on the engine that pays one HEAD — `engine.py` is
    out of this module's territory, so it is written down rather
    than reached into.
    """
    digest = registry.declaration_digest(declaration)
    engine.apply_settings(declaration=declaration, digest=digest)
    log.info("search.index.materialized", kind=declaration.label, digest=digest)


def _current_row(declaration: Searchable, *, tenant: Tenant | None, pk: UUID) -> Any:
    """The row as Postgres has it now, or `None` if a reader would not see it.

    `for_tenant(tenant)` and not `for_tenant(tenant).visible_to(...)`: there is
    no actor here and nothing is being returned to anybody. This is a write-side
    read that produces a document **stamped with the ids every later query is
    filtered by** — the walls go into the document, they are not applied to this
    read. `for_tenant(None)` is the fail-closed floor under it: an event naming a
    tenant that has gone finds nothing and the document is removed.
    """
    row = declaration.model._default_manager.for_tenant(tenant).filter(pk=pk).first()
    if row is None:
        return None
    if getattr(row, "archived_at", None) is not None:
        return None
    return row


# --- the periodic machine ------------------------------------------------------
#
# A `ScheduleDeclaration` and not a hook in `apps/workflows/worker.py`, for the
# reason discovery exists at all: an app declares its own machinery and the
# worker discovers it, so adding search to a product edits no shared file. It is
# also what makes the reconcile visible to the machinery census and to LF-Q's
# reachability tooth for free.
#
# **A boot is the moment this exists for**, and both lifetime classes give it
# one: in `process` mode `run_declared_machinery` fires every declaration
# immediately and then on its interval (catch-up first, then wait), and in
# `deployment` mode the durable Schedule's first tick follows the worker that
# created it. The interval behind it is the belt: a container restarted out of
# band, or a Meili volume lost at three in the morning, converges within it
# rather than waiting for somebody to notice.

#: The id prefix Temporal is given for the run. House-shaped
#: `<tenant>:<app>:<noun>:<key>` with `platform` in the tenant position — this
#: is the deployment's own housekeeping and belongs to no tenant — and per task
#: queue, so two deployments never fight over one execution (the events purge's
#: precedent, exactly).
RECONCILE_WORKFLOW_PREFIX = "platform:search:reconcile"
RECONCILE_SCHEDULE_PREFIX = "system:search:reconcile"

#: How often the belt tightens. Hourly: long enough that it is not a load, short
#: enough that a lost index is a lunch break rather than a day.
RECONCILE_EVERY = timedelta(hours=1)


def reconcile_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's reconcile. One per task queue."""
    return f"{RECONCILE_SCHEDULE_PREFIX}:{task_queue}"


def reconcile_workflow_id(task_queue: str) -> str:
    """The **deterministic** id of the run the schedule starts.

    Deterministic and per queue is what makes "one rebuild across N booting
    workers" true rather than hoped for: every worker in a deployment derives
    the same id from the same queue, and Temporal's `SKIP` overlap policy means
    the second one to ask is told the work is already happening.

    This is the prefix the server is given; it appends the scheduled time, so an
    actual run is `platform:search:reconcile:<queue>-2026-08-24T14:13:48Z`. The
    part this repository chooses is deterministic, which is house rule 18's
    subject.
    """
    return f"{RECONCILE_WORKFLOW_PREFIX}:{task_queue}"


def reconcile_schedule(task_queue: str) -> Schedule:
    """The reconcile's schedule, as a value so a test can read it.

    `SKIP` on overlap, and here it is load-bearing rather than tidy: two
    reconciles at once would both find the same stale digest and both start
    rebuilding the same index into the same staging uid.
    """
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "ReconcileSearchIndexesWorkflow",
            id=reconcile_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=RECONCILE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


RECONCILE = ScheduleDeclaration(
    name="search.reconcile-indexes",
    schedule_id=reconcile_schedule_id,
    schedule=reconcile_schedule,
    log_prefix="search",
)


ACTIVITIES: list[Callable[..., Any]] = [list_search_kinds, reconcile_search_index]

#: Discovered by `apps.workflows.client.discovered_schedules`, which the worker
#: consults at startup. One declaration, and it is the startup reconcile.
SCHEDULES: list[ScheduleDeclaration] = [RECONCILE]


__all__: Sequence[str] = (
    "ACTIVITIES",
    "CREATED",
    "REBUILT",
    "RECONCILE",
    "SCHEDULES",
    "UNCHANGED",
    "document_for",
    "index_event",
    "list_search_kinds",
    "reconcile_schedule",
    "reconcile_schedule_id",
    "reconcile_search_index",
    "reconcile_workflow_id",
)
