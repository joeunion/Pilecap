"""Where this app's workflows are allowed to touch the world.

Everything `workflows.py` may not name lives here: the ORM, the AWS SDK (through
`storage.py`, which is the only module under `apps/` that imports it) and the
services that write. So does the app's one **declared periodic machine** — the
`ScheduleDeclaration` at the foot of this module, which is data rather than
behaviour and which the worker discovers at startup (ADR platform-lifecycle-1).

The finalize pair take the same three steps every activity in this repository
takes —
**restore the principal, read the row through the tenant's manager and the acting
hat, then act.** Neither takes the tenant or the organization as an argument:
both arrive on the workflow's Temporal headers and are unpacked by the
interceptor, which is what makes it impossible to reach into somebody else's
tenant — or somebody else's branch — by putting the wrong id in a payload. It is
also what makes the METER land on the right branch: `record_usage` attributes
consumption to the acting hat, so a run started by a sub-seller meters that
sub-seller.

**Plain `def`**, like every activity in this repository: the ORM is synchronous,
the AWS SDK is synchronous, and the worker runs these in its thread pool, where
a synchronous call belongs. The one thing a sync activity owes that pool is
`close_old_connections` at both ends — there is no request cycle out here to do
it, and a connection left open per thread is a connection leaked forever.

**All three are idempotent**, because Temporal guarantees an activity runs at
least once: `verify_object` reads and measures and writes nothing at all;
`record_stored` re-asserts the same row and re-asks the usage ledger with the
same idempotency key — which recognises the replay and returns the first entry
rather than recording a second, so two runs make one `UsageEntry` and nobody is
billed twice for one document; and `sweep_pending_uploads` selects by age and
status, so a second pass inside the same window finds nothing left to take.

**`sweep_pending_uploads` is the one that restores no principal**, and its
docstring says why at length: it is the deployment's own housekeeping, started by
a schedule for nobody, and its scope is the clock rather than a tenant.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from django.db import close_old_connections
from temporalio import activity
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from apps.core.actor import system_actor
from apps.core.exceptions import NotFound
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.schedules import ScheduleDeclaration
from apps.core.time import now
from apps.files import services, storage
from apps.files.models import PENDING_UPLOAD_TTL_HOURS, FileVersion
from apps.files.types import (
    SWEEP_WORKFLOW,
    FinalizeUpload,
    StoreMeasurement,
    SweepOutcome,
    SweepPendingUploads,
    VerifiedObject,
)
from apps.workflows.context import workflow_context

log = get_logger(__name__)


def _the_version(*, version_id: str) -> FileVersion:
    """The row this run is about, read the way every read in this product is read.

    **Both halves, in this order** (house rule 24): `for_tenant` answers whose
    data and `visible_to` answers which part of their network, and both fail
    closed — an unresolved tenant or an unresolved hat reads an empty table
    rather than the table. The tenant and the hat are the run's own, restored
    from its Temporal headers, so this cannot be pointed anywhere else by a
    payload.

    `NotFound` and not a bare `DoesNotExist`: house rule 14 keeps untranslated
    exceptions below the doors, and this refusal reaches a workflow that puts its
    sentence on the `WorkflowRun` row somebody will read.
    """
    tenant, _user_id, org = workflow_context()
    version = (
        FileVersion.objects.for_tenant(tenant)
        .visible_to(org)
        .select_related("file")
        .filter(pk=UUID(version_id))
        .first()
    )
    if version is None:
        raise NotFound(
            "This run's version is not readable under the tenant and organization it was "
            "started for. Either the document was removed, or the hat the run carries no "
            "longer covers the branch it was filed in."
        )
    return version


def _restored(version: FileVersion) -> tuple[Tenant, Organization | None]:
    """The tenant to act in and the hat to act under. Read once, used twice."""
    _tenant, _user_id, org = workflow_context()
    return version.tenant, org


@activity.defn(name="verify_object", no_thread_cancel_exception=True)
def verify_object(payload: FinalizeUpload) -> VerifiedObject:
    """Go and look at what is actually at that key, and measure it.

    **The whole point of this app in one function.** A client told us it uploaded
    something and told us how big it was; neither statement is evidence. This
    heads the object — the cheap question, "did anything land at all" — and then
    streams it through a SHA-256, counting bytes as they go past. What comes back
    is what was on the wire.

    It **writes nothing**, which is what makes it safe to retry against a bucket
    that was briefly unreachable: the only state it touches is the object store's,
    read-only.

    A missing object raises out of the SDK, Temporal retries, it keeps raising,
    and the run fails with the store's own complaint on the row — which is the
    honest outcome for a confirm of an upload that never happened, rather than a
    version quietly marked stored over nothing.
    """
    close_old_connections()
    try:
        version = _the_version(version_id=payload.version_id)
        tenant, _org = _restored(version)
        seen = storage.head(tenant=tenant, key=version.key)
        measured = storage.sha256_of(tenant=tenant, key=version.key)
        log.info(
            "files.object.verified",
            version_id=str(version.pk),
            size_bytes=measured.size_bytes,
            head_size_bytes=seen.size_bytes,
        )
        return VerifiedObject(
            sha256=measured.sha256,
            size_bytes=measured.size_bytes,
            head_size_bytes=seen.size_bytes,
        )
    finally:
        close_old_connections()


@activity.defn(name="record_stored", no_thread_cancel_exception=True)
def record_stored(payload: StoreMeasurement) -> str:
    """Write the measurement down, through the service that owns the transaction.

    The activity does not touch a model itself (house rule 10): the status flip,
    the promotion, the meter and the event are one transaction and the service is
    where that transaction lives. What the activity contributes is the principal
    and the row.

    **The system actor, wearing the run's hat.** Nobody clicked this: the person
    who confirmed the upload is not the one finalizing it a minute later, and
    attributing the write to them would make the audit trail read plausibly and
    be false. The HAT still rides, which is what makes the metered bytes land on
    the branch that filed the document rather than on the whole tenant — and
    `record_usage` refuses outright when there is no hat, rather than defaulting
    to the root.

    Returns the version's id as a string: a workflow's history is JSON, and the
    id is the useful thing to be able to read out of it later.
    """
    close_old_connections()
    try:
        version = _the_version(version_id=payload.version_id)
        tenant, org = _restored(version)
        stored = services.record_stored(
            tenant=tenant,
            actor=system_actor(tenant, org),
            version=version,
            sha256=payload.sha256,
            size_bytes=payload.size_bytes,
        )
        return str(stored.pk)
    finally:
        close_old_connections()


@activity.defn(name="sweep_pending_uploads", no_thread_cancel_exception=True)
def sweep_pending_uploads(window: SweepPendingUploads) -> SweepOutcome:
    """Expire the abandoned uploads, through the service that owns the decision.

    **The one activity here that restores no principal, and that is the point.**
    `verify_object` and `record_stored` above act inside one tenant, for one
    document, on somebody's behalf; this is the deployment's own housekeeping.
    Its run carries no tenant on its headers because a schedule started it for
    nobody, and asking `workflow_context()` for one would get `None` and then read
    an empty table — a sweep that quietly swept nothing, which is the worst shape
    this bug can take. So the tenant and the hat are resolved PER ROW inside the
    service, off the documents it found, and the clock is the only scope this
    activity has.

    **The clock is read here rather than in the workflow** (house rule 9): a
    workflow that called `now()` could not replay. The WINDOW arrives on the
    argument, off the `ScheduleDeclaration`, so what an operator reads in the
    Temporal UI is the number the sweep actually used.

    Idempotent: it selects by age and status, so a second run inside the same
    window finds nothing to take.
    """
    close_old_connections()
    try:
        outcome = services.purge_pending_versions(
            before=now() - timedelta(hours=window.ttl_hours), tenant=None
        )
        log.info(
            "files.sweep.done",
            versions=outcome.versions,
            documents=outcome.documents,
        )
        return outcome
    finally:
        close_old_connections()


# --- the declared machine (ADR platform-lifecycle-1) --------------------------

#: How often the sweep runs. **Hourly, and the cadence only has to be small
#: against the window** — the TTL is a day, so an hourly pass means an abandoned
#: document leaves somebody's list within an hour of becoming abandoned rather
#: than within a day of it. It is cheap to run that often: the read is a
#: two-column filter over a population that is normally empty, and the overlap
#: policy below means a long first sweep is never joined by a second.
SWEEP_EVERY = timedelta(hours=1)

#: **Both ids are namespaced by task queue**, and that is not cosmetic (ADR
#: events-2, observed live): a schedule id is global to the Temporal
#: namespace, so a constant one makes every worker's startup a silent fight over
#: where the sweep runs. There is no legacy un-suffixed id to drop here; this
#: schedule has never existed under one.
SWEEP_SCHEDULE_PREFIX = "files-sweep-pending-uploads"
SWEEP_WORKFLOW_PREFIX = "platform:files:sweep-pending"


def sweep_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's abandoned-upload sweep."""
    return f"{SWEEP_SCHEDULE_PREFIX}:{task_queue}"


def sweep_workflow_id(task_queue: str) -> str:
    """The id of the run the schedule starts. Deterministic, and per queue too.

    Two schedules starting runs under one workflow id would be two deployments
    fighting over one execution — the schedule id alone is not enough.

    This is the **prefix** Temporal is given: the server appends the scheduled
    time to it, so an actual run is
    `platform:files:sweep-pending:<queue>-2026-08-25T03:00:00Z`. That is the
    server's doing and not a random id; the part this repository chooses is
    deterministic, which is what house rule 18 is about.
    """
    return f"{SWEEP_WORKFLOW_PREFIX}:{task_queue}"


def sweep_pending_uploads_schedule(task_queue: str) -> Schedule:
    """The hourly sweep, as a value so a test can read it.

    The TTL rides on the ACTION rather than being read inside the activity, for
    the reason `apps.exports`' and `apps.connections`' sweeps both carry their
    windows there: an operator can read the number off the schedule in the
    Temporal UI instead of out of the source, and both lifetime classes read the
    same value out of the same declaration.

    `SKIP` on overlap: two sweeps at once would both select the same expired
    rows, and while the second delete is a harmless no-op there is no reason to
    pay for the race — or for two of them arguing over the same document's
    archive lock.
    """
    return Schedule(
        action=ScheduleActionStartWorkflow(
            SWEEP_WORKFLOW,
            SweepPendingUploads(ttl_hours=PENDING_UPLOAD_TTL_HOURS),
            id=sweep_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=SWEEP_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


#: The one periodic machine this app owns, declared as data (ADR
#: platform-lifecycle-1).
#:
#: **This is the far end of `FileVersion.lifecycle`.** House rule 31 walks from
#: the model's `purged_by` to the service, to the activity above that calls it,
#: to the workflow that executes that activity, to this declaration — and refuses
#: the declaration if the walk stops short. Delete this entry and the model's
#: promise becomes the poller that was never built, loudly, at the gate.
SWEEP_PENDING_UPLOADS = ScheduleDeclaration(
    name="files.sweep-pending-uploads",
    schedule_id=sweep_schedule_id,
    schedule=sweep_pending_uploads_schedule,
    log_prefix="files",
)


ACTIVITIES: list[Callable[..., Any]] = [verify_object, record_stored, sweep_pending_uploads]

#: Discovered by `apps.workflows.client.discovered_schedules`, which the worker
#: consults at startup. One declaration per periodic machine this app owns.
SCHEDULES: list[ScheduleDeclaration] = [SWEEP_PENDING_UPLOADS]
