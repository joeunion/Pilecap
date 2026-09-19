"""Where this app touches the world: the walk, the zip, the bucket, the sweep.

Everything non-deterministic is here rather than in `workflows.py` (house rule
9), and every write to a model goes through a service (house rule 10). What is
here and is NOT in a service is the archive itself, and that is a decision with
a reason: `@service` wraps its body in `transaction.atomic()`, and building an
archive is minutes of streaming reads plus one large object written to storage,
so doing it inside a service would hold a database transaction open for the
whole of it. The two ends — "the walk started", "here is what it produced" —
are services, in short transactions, and they are what emit the events.

**Plain `def`, like every other activity in this repository**: the ORM is
synchronous and the worker runs activities in a thread pool, so a sync activity
is a sync query on a thread where one belongs. It closes stale connections at
both ends, because out here there is no request cycle to do it.

**Why the purge half exists at all.** `Export` declares itself `purged` (ADR
core-13), and a `purged` declaration is a promise: something deletes these rows
on a schedule. House rule 31 walks the promise outwards —

    purged_by -> an activity that references it
              -> a workflow that executes that activity
              -> a `ScheduleDeclaration` in this module's `SCHEDULES`

— because a table shaped for a sweeper with no sweeper looks exactly like a
table that is finished. Here the stakes are unusual: the rows this table names
are complete copies of customers' databases, so the sweep is not housekeeping,
it is the thing that stops an export from being a permanent liability.

**It only DECLARES.** Whether the declaration becomes a durable Temporal
Schedule the server owns, or a run a live worker starts on a timer, is decided
once by the deployment's lifetime class in `apps.workflows.client` (ADR
platform-lifecycle-1), so this app never has to know which one it is under.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from datetime import timedelta
from tempfile import SpooledTemporaryFile
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.core.serializers.json import DjangoJSONEncoder
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

from apps.core.actor import Actor, actor_for, system_actor
from apps.core.log import get_logger
from apps.core.schedules import ScheduleDeclaration
from apps.core.services import root_organization
from apps.core.time import now
from apps.exports import services
from apps.exports.census import plan
from apps.exports.models import EXPORT_RETENTION_DAYS, Export
from apps.exports.selectors import get_export, list_exportable_rows
from apps.exports.types import (
    PURGE_WORKFLOW,
    BuildExport,
    ExportBuilt,
    ExportFailed,
    PurgeExports,
    PurgeOutcome,
)
from apps.files.models import StoredFile
from apps.files.services import store_stream
from apps.workflows.context import workflow_context

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import Organization
    from apps.files.models import FileVersion

log = get_logger(__name__)

#: The version of the manifest document. A number rather than nothing, because
#: the manifest is a published shape a customer's own tooling will read, and the
#: first time its keys move somebody has to be able to tell which one they have.
#:
#: **2 since Phase R.** The document gained `omitted_models` — the tables the
#: requester may not read — and a reader that switches on this number can now
#: tell an archive that was complete-for-that-reader from one written before the
#: question was asked. Additive: every key of version 1 is still there and means
#: what it meant, which is the only kind of change this number is allowed to be
#: without a successor document.
MANIFEST_VERSION = 2

#: The reason string an omitted table carries. One word, in the manifest's own
#: vocabulary, so a customer's tooling can branch on it without parsing prose —
#: and the prose is in the API contract, where a sentence belongs.
UNREADABLE = "unreadable"

#: What the manifest is called inside the zip, and where the JSONL files live.
#: Constants rather than literals at three call sites, because a reader opening
#: somebody's archive to check a claim needs the two names to be one name.
MANIFEST_NAME = "manifest.json"
MODELS_DIRECTORY = "models"

#: What the archive IS, told to the store rather than guessed by it. A constant
#: because two call sites would be two chances to disagree, and because the
#: value travels: `store_stream` signs it into the object's metadata, and it is
#: what a presigned GET hands the browser that eventually fetches it.
ARCHIVE_CONTENT_TYPE = "application/zip"

#: How many rows come back from the database at a time. `.iterator()` is what
#: makes the walk O(1) queries and O(chunk) memory per model instead of loading
#: a table into a list; the number is a memory/round-trip trade and 2000 rows of
#: ordinary columns is a few megabytes.
CHUNK = 2000

#: How large the archive may get before it stops being built in memory. Below
#: this a `SpooledTemporaryFile` never touches the disk, which is the common
#: case for a small tenant; above it, it spills to a real file rather than
#: growing a worker's heap by the size of somebody's database.
SPOOL_BYTES = 32 * 1024 * 1024

# --- the archive ---------------------------------------------------------------


def _hat_for(export: Export) -> Organization:
    """The organization whose subtree this export may read.

    Two widths and ONE predicate. A tenant-wide export walks under the tenant's
    **root**, whose subtree is the whole tree, so `visible_to(root)` is every row
    the tenant owns — which means there is no branch of this code where the
    scoping is skipped and no second read path that could be widened by
    accident. A subtree export walks under the organization the request was made
    from, which is the row's own.

    That is the reason the tenant-wide bar is an authorization question and not
    a scoping one: the walk cannot read anything a root-hatted actor could not
    read at any other door, so what `policies.can_request` is really guarding is
    who gets to wear the root's hat.
    """
    if export.scope == Export.Scope.TENANT:
        return root_organization(tenant=export.tenant)
    return export.organization


def _exported_row(row: Any, fields: list[Any]) -> dict[str, Any]:
    """One row as a JSON-ready dict, read off the fields the census allowed.

    `field.value_from_object(row)` and not attribute access, and that difference
    is the query budget: on a foreign key it returns the stored id and never
    touches the related table, so the walk visits each model exactly once no
    matter how many relations its rows have. A serializer that reached through
    `row.organization` would be an N+1 that only shows up on a customer big
    enough for it to matter.
    """
    return {str(field.name): field.value_from_object(row) for field in fields}


def _write_the_archive(
    *, export: Export, hat: Organization, actor: Actor
) -> tuple[FileVersion, dict[str, Any]]:
    """Build the zip, file it as a document, and return `(version, manifest)`.

    One JSONL file per model in the census, streamed through `.iterator()`, plus
    one `manifest.json` written **last** — last because its row counts are the
    counts this walk actually wrote, not a second query's answer to the same
    question. That is what makes the three-way check in `tests/test_archive.py`
    meaningful: the manifest, the archive and the database are three
    measurements and the manifest is the one taken while the writing happened.

    **Never `pg_dump`.** A dump is the deployment's database, not one tenant's
    rows; it cannot honour `visible_to`, it cannot leave an encrypted column
    out, and it would put every other customer in the file.

    **The archive goes out through the files seam and nowhere else** (XPr, the
    supersession). It is `files.services.store_stream` that puts it, so the key
    is `files.storage.version_key` — the tenant's primary key, the document's,
    and a version ordinal — rather than the `"tenants/<slug>/<filename>"` this
    app used to build for itself. ADR files-2's grammar: a key quotes nothing
    renamable, nothing re-issuable and nothing a user supplied. What comes back
    is the `FileVersion`, carrying the key, the size and the digest of the bytes
    the store actually holds.

    **`store_stream` and not `store_bytes`, and the spool is the reason.** The
    archive is as large as the tenant, and it is already sitting in a
    `SpooledTemporaryFile` that spilled to disk above `SPOOL_BYTES`. Handing
    that file to the streaming seam sends it a chunk at a time; `store_bytes`
    would have taken a `bytes`, which is the whole of somebody's database in a
    worker's memory, twice over — once to build it and once for the SDK. A
    `SpooledTemporaryFile` satisfies `storage.Rewindable`, which is exactly what
    that seam asks for.

    **`actor` is the PERSON who asked**, not the system actor the rest of this
    activity runs as — see `_person_for` for the split and why it is not a
    fiction.

    **WHAT may be in the archive is a third question**, asked of a third actor —
    `_reader_for(export)`, built off the row rather than off the headers, and
    never `kind="system"`. See that function; the difference decides whether the
    read half of this walk can say no at all.
    """
    carried, skipped = plan(tenant_wide=export.scope == Export.Scope.TENANT)
    models_manifest: list[dict[str, Any]] = []
    omitted: dict[str, str] = {}
    reader = _reader_for(export)
    total = 0

    with SpooledTemporaryFile(max_size=SPOOL_BYTES) as spool:
        with zipfile.ZipFile(spool, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for label in sorted(carried):
                disposition = carried[label]
                left_out = {one.name for one in disposition.excluded_fields}
                fields = [
                    field
                    for field in disposition.model._meta.concrete_fields
                    if field.name not in left_out
                ]
                rows = list_exportable_rows(
                    tenant=export.tenant, org=hat, disposition=disposition, actor=reader
                )
                if rows is None:
                    # REFUSED, not empty. The selector says which by returning
                    # `None`, and the difference reaches the customer: an empty
                    # `.jsonl` would say "you have none of these", which is a
                    # different and false sentence.
                    omitted[label] = UNREADABLE
                    continue
                written = 0
                with archive.open(f"{MODELS_DIRECTORY}/{label}.jsonl", "w") as handle:
                    for row in rows.iterator(chunk_size=CHUNK):
                        line = json.dumps(_exported_row(row, fields), cls=DjangoJSONEncoder)
                        handle.write(line.encode("utf-8") + b"\n")
                        written += 1
                total += written
                models_manifest.append(
                    {
                        "label": label,
                        "file": f"{MODELS_DIRECTORY}/{label}.jsonl",
                        "rows": written,
                        "org_scoped": disposition.org_scoped,
                        "fields": [str(field.name) for field in fields],
                        "excluded_fields": [
                            {"name": one.name, "basis": one.basis}
                            for one in disposition.excluded_fields
                        ],
                    }
                )

            manifest = _manifest(
                export=export,
                hat=hat,
                models=models_manifest,
                skipped=skipped,
                omitted=omitted,
                rows=total,
            )
            archive.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, cls=DjangoJSONEncoder))

        spool.seek(0)
        # A SERVICE now, where this used to be a raw `default_storage.save` —
        # and house rule 10 is happier, not strained: filing a document is
        # `apps.files`' write and `store_stream` is its service. What the rule's
        # old exemption bought (not holding a transaction open for the length of
        # an archive) is paid for differently now and deliberately: F2 declares
        # that `store_stream` PUTs inside its own transaction because the row is
        # meaningless without the object, and that it is called from an activity
        # on a worker thread and never from a request. This is that activity.
        version = store_stream(
            tenant=export.tenant,
            actor=actor,
            filename=f"export-{export.pk}.zip",
            content_type=ARCHIVE_CONTENT_TYPE,
            body=spool,
            purpose=StoredFile.Purpose.EXPORT,
        )
    return version, manifest


def _manifest(
    *,
    export: Export,
    hat: Organization,
    models: list[dict[str, Any]],
    skipped: dict[str, str],
    omitted: dict[str, str],
    rows: int,
) -> dict[str, Any]:
    """What the archive says about itself. **The same object goes in both places.**

    Written into the zip as `manifest.json` and stored on the row's `manifest`
    column, from one dict, so the two cannot come to disagree — and both carry
    the exclusions, because an archive that is quietly short a table or a column
    looks exactly like a tenant that never had one. The reader is a customer who
    is leaving and cannot ask.
    """
    return {
        "version": MANIFEST_VERSION,
        # An ISO string and not a `datetime`: the manifest is a DOCUMENT, it is
        # stored in a `JSONField` and written into the zip, and the two copies
        # have to be byte-identical. A `datetime` would render one way through
        # `DjangoJSONEncoder` and refuse outright through the field's default
        # encoder, which is a manifest that is right in the file and missing
        # from the row.
        "generated_at": now().isoformat(),
        "export_id": str(export.pk),
        "scope": str(export.scope),
        "tenant": {"id": str(export.tenant_id), "slug": export.tenant.slug},
        "organization": {"id": str(hat.pk), "slug": hat.slug, "path": hat.path},
        "rows": rows,
        "models": models,
        "excluded_models": [
            {"label": label, "reason": reason}
            for label, reason in sorted(_declared_exclusions().items())
        ],
        "skipped_models": [
            {"label": label, "reason": reason} for label, reason in sorted(skipped.items())
        ],
        # The third and newest reason a table is missing, and the only one that
        # is about the READER rather than about the shape of the export: they
        # may not read that kind. Named beside the other two so a customer sees
        # one list of "what is not here and why" rather than two.
        "omitted_models": [
            {"label": label, "reason": reason} for label, reason in sorted(omitted.items())
        ],
    }


def _declared_exclusions() -> dict[str, str]:
    """Every model the census takes out, with its reason. Read at build time.

    Imported through the census rather than restated, so the reason a customer
    reads in their manifest is the same string a reviewer reads in
    `census.py` — one text, two audiences, no drift.
    """
    from apps.exports.census import exclusions

    return exclusions()


# --- the activities ------------------------------------------------------------


@activity.defn(name="build_export_archive")
def build_export_archive(payload: BuildExport) -> ExportBuilt:
    """Walk the census, write the zip, record the result.

    Three steps and the middle one is the only long one — restore the principal,
    read the row through the tenant's manager and the run's own hat, call a
    service at each end. Neither service call writes anything this activity
    decided by itself.

    **Idempotent**, which Temporal demands: `mark_export_running` leaves a
    finished row alone and `finish_export` keeps the first artifact rather than
    pointing the row at a second one. A retry after a worker crash therefore
    costs a second archive in storage and never a second row — and the orphan is
    swept by age with everything else.

    An export deleted while the run was queued raises `NotFound` from the
    selector; Temporal retries, it keeps raising, and the run fails saying so,
    which is the honest outcome rather than quietly succeeding at nothing.
    """
    close_old_connections()
    try:
        tenant, _user_id, org = workflow_context()
        # `system_actor` and not the requester: reading the export row to build it
        # is the product acting for itself, and the tenancy is still enforced by the
        # scoped manager on the way through. WHAT the archive may contain is a
        # different question, asked of the PERSON — see `_reader_for`.
        export = get_export(
            tenant=tenant,
            export_id=UUID(payload.export_id),
            org=org,
            actor=system_actor(tenant, org),
        )
        # The system actor: nobody clicked this. The hat still rides on it, so
        # the audit rows say which part of the network the work was done for.
        actor = _actor_for(export)
        services.mark_export_running(tenant=export.tenant, actor=actor, export=export)
        # ...and the PERSON, for the document's own `uploaded_by`. Two actors,
        # two questions; `_person_for` is where the difference is argued.
        version, manifest = _write_the_archive(
            export=export, hat=_hat_for(export), actor=_person_for(export)
        )
        services.finish_export(
            tenant=export.tenant,
            actor=actor,
            export=export,
            version=version,
            manifest=manifest,
        )
        log.info(
            "exports.archive.written",
            export_id=str(export.pk),
            rows=int(manifest["rows"]),
            bytes=int(version.size_bytes or 0),
            sha256=str(version.sha256),
        )
        return ExportBuilt(
            export_id=str(export.pk), artifact_key=str(version.key), rows=int(manifest["rows"])
        )
    finally:
        close_old_connections()


@activity.defn(name="record_export_failure")
def record_export_failure(payload: ExportFailed) -> str:
    """Mark an export failed, with the reason the workflow walked out of the cause.

    A separate activity from the build rather than a `try` inside it, and the
    reason is what a retry means: the build activity is retried by Temporal
    until its policy is spent, and a row marked `failed` on the first attempt
    would be a row that lied for as long as the retries went on. The workflow
    reaches this once, after the retries are done, which is the only moment
    "this export failed" is true.

    Its own shape rather than a reused one: `reason` is the activity's own
    complaint, walked out of Temporal's cause chain by the workflow
    (`workflows._reason`), and a field called `artifact_key` carrying a
    traceback is the kind of reuse nobody can read six weeks later.
    """
    close_old_connections()
    try:
        tenant, _user_id, org = workflow_context()
        # The system reads its own row to record the failure on it; nobody clicked
        # this, and the tenancy is the scoped manager's as it is everywhere else.
        export = get_export(
            tenant=tenant,
            export_id=UUID(payload.export_id),
            org=org,
            actor=system_actor(tenant, org),
        )
        failed = services.record_export_failure(
            tenant=export.tenant,
            actor=_actor_for(export),
            export=export,
            error=payload.reason,
        )
        return str(failed.pk)
    finally:
        close_old_connections()


@activity.defn(name="purge_expired_exports")
def purge_expired_exports(window: PurgeExports) -> PurgeOutcome:
    """Take the archives past their retention — the object first, then the row.

    Through the service, never around it (house rule 10): the order the two
    deletions happen in is a correctness property, and it lives in one place
    where a reader looking for it will go.

    Idempotent: it deletes by age, so a re-run inside the same window removes
    nothing.
    """
    close_old_connections()
    try:
        outcome = services.purge_exports(
            before=now() - timedelta(days=window.retention_days), tenant=None
        )
        log.info("exports.purge.done", exports=outcome.exports, artifacts=outcome.artifacts)
        return outcome
    finally:
        close_old_connections()


def _actor_for(export: Export) -> Actor:
    """The system actor, wearing the run's own hat. **For this app's own writes.**

    Nobody clicked this. Attributing it to whoever asked for the export last
    week would make the audit trail read plausibly and be false; the hat still
    rides, so the row says which part of the network the work was done for.

    Read `_person_for` below beside this one: the two exist because "who did
    this" and "whose document is this" are different questions, and XPr is where
    the product first had to answer both in one activity.
    """
    return system_actor(export.tenant, export.organization)


def _person_for(export: Export) -> Actor:
    """The person who asked, restored off the workflow headers. **For the file.**

    **The split, stated, because it looks at first like the fiction the function
    above refuses.** `_actor_for` answers *who performed this act* — and the act
    is a scheduled walk a worker did, so the honest answer is the system.
    `uploaded_by` on a `files.FileVersion` answers a different question:
    **whose document is this**. The archive is a copy of one person's request,
    made for them, delivered to them, and filing it under "nobody" would be the
    fiction — as well as impossible, since `uploaded_by` is non-null and
    `PROTECT` precisely so a document always answers it (F2's declared frontier:
    *`store_bytes`/`store_stream` needs a person*).

    So the export's own rows say the system built it and the file's row says
    whose it is, and neither has to lie for the other.

    **Where the person comes from, and why it is not `export.requested_by`.**
    The acting user rides the workflow's Temporal headers — `create_export`
    stamps it (`start_workflow_on_commit(..., user=actor.user)`) and
    `workflow_context()` unpacks it — which is the platform's one mechanism for
    "on whose behalf" across a process hop, the same one the tenant and the hat
    arrive by. Reading the column instead would be this app inventing a second
    channel that could disagree with the first.

    **`kind="system"`, with a person on it, and that pair is the point.**
    `Actor.kind` answers "was this a person, a machine acting as a person, or the
    system acting for nobody" — and this is the system, acting for SOMEBODY. So
    the audit row the file's service writes reads *the system filed this, on
    behalf of X*, which is what happened. Spelling it `human` would claim a click
    that never occurred and would be the fiction `_actor_for` exists to refuse;
    it would also re-ask `file.create` of the person a second time, a question
    `export.create` already answered at the door with the wider ceiling
    (`administers_the_whole_tenant` for a tenant-wide walk).
    Nothing is widened by the system kind here: what this run may READ was fixed
    by `_hat_for` before a byte was written.

    **It raises rather than filing under nobody.** A run whose header carries no
    user is a run started somewhere that resolved no person — a schedule, a
    machine credential — and `store_stream` would refuse it one call later with
    a message about `uploaded_by` that says nothing about exports. Refusing here
    says which run and which export, and the retry a Temporal activity gets will
    keep saying it rather than quietly succeeding at nothing.
    """
    _tenant, user_id, _org = workflow_context()
    if user_id is None:
        raise RuntimeError(
            f"Export {export.pk} is being built by a run that carries no acting user, and "
            "an archive is filed as a document under the person who asked for it "
            "(files.FileVersion.uploaded_by is non-null). A run started through "
            "apps.exports.services always stamps one; this one did not, so it is refused "
            "rather than filed under nobody."
        )
    return actor_for(
        user=_the_user(user_id),
        tenant=export.tenant,
        kind="system",
        org=export.organization,
    )


def _reader_for(export: Export) -> Actor:
    """The requester, **as somebody who can be told no**. For the archive's reads.

    Three actors touch one export build and each answers a different question:

    * `_actor_for` — *who performed this act*: the system, wearing the run's hat.
      The audit rows are its.
    * `_person_for` — *whose document is this*: the person, restored off the
      workflow headers, `kind="system"` because nobody clicked. The
      `FileVersion.uploaded_by` is its.
    * this one — *what may be IN the archive*: the person again, and this time
      not `kind="system"`, because `core.authz.allows` answers a system actor
      True at step 1, before it reads a key, a membership or a policy. Asking
      the archive's read question with `_person_for`'s actor would be asking
      nobody, and every kind would come back readable however the requester's
      permissions were set. A check that cannot say no is not a check.

    **Off the ROW rather than off the headers**, which is the one place this
    disagrees with `_person_for` and it is deliberate: what an archive contains
    must be the same on every attempt at it (principle 16 — a Temporal activity
    is retried, and a retry that arrived with a differently-shaped principal
    must not produce a differently-shaped archive). `Export.requested_by` is the
    stable answer to *whose archive is this*; the headers are the transport.

    **`kind="agent"` and not `"human"`**, for `_actor_for`'s own reason: nobody
    clicked this. What the kind buys is only that it is not `"system"`.

    **A requester who has since been erased holds nothing, and the manifest says
    so.** `requested_by` is `SET_NULL` on erasure by design, so a rebuild after
    one resolves an actor with no user — which holds no key, omits every kind,
    and writes every table into `omitted_models`. That is loud and it fails
    closed, which is the right pair of properties for the case; an archive
    rebuilt for somebody who no longer exists is not one to widen for.
    """
    return actor_for(
        user=export.requested_by,
        tenant=export.tenant,
        kind="agent",
        org=_hat_for(export),
    )


def _the_user(user_id: str) -> Any:
    """The acting user as a row. **Activities only** — it reads the database.

    Fetched through the auth model rather than through `apps.accounts`: house
    rule 1 says `auth.User` is never imported, and `get_user_model()` is the one
    way to name the concrete class this deployment configured.
    """
    from django.contrib.auth import get_user_model

    return get_user_model().objects.get(pk=user_id)


# --- the schedule --------------------------------------------------------------

#: Daily. The window is thirty days wide, so the cadence only has to be small
#: against it; running more often would delete the same nothing more often.
PURGE_EVERY = timedelta(hours=24)

#: **Both ids are namespaced by task queue**, and that is not cosmetic (ADR
#: events-2): a schedule id is global to the Temporal
#: namespace, so a constant one makes every worker's startup a silent fight over
#: where the sweep runs. There is no legacy un-suffixed id to drop here; this
#: schedule has never existed under one.
PURGE_SCHEDULE_PREFIX = "exports-purge-expired"
PURGE_WORKFLOW_PREFIX = "platform:exports:purge"

#: Deleting objects from a bucket one at a time, so the timeout is sized for the
#: first sweep of a table nobody has swept rather than for the steady state.
PURGE_TIMEOUT = timedelta(minutes=30)


def purge_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's export sweep."""
    return f"{PURGE_SCHEDULE_PREFIX}:{task_queue}"


def purge_workflow_id(task_queue: str) -> str:
    """The id of the run the schedule starts. Deterministic, and per queue too.

    Two schedules starting runs under one workflow id would be two deployments
    fighting over one execution — the schedule id alone is not enough.

    This is the **prefix** Temporal is given: the server appends the scheduled
    time to it, so an actual run is
    `platform:exports:purge:<queue>-2026-08-24T03:00:00Z`. That is the server's
    doing and not a random id; the part this repository chooses is
    deterministic, which is what house rule 18 is about.
    """
    return f"{PURGE_WORKFLOW_PREFIX}:{task_queue}"


def purge_exports_schedule(task_queue: str) -> Schedule:
    """The daily sweep, as a value so a test can read it.

    The retention rides on the ACTION rather than being read inside the
    activity, for the reason `apps.connections`' sweep carries its window there:
    an operator can read the number off the schedule in the Temporal UI instead
    of out of the source, and both lifetime classes read the same value out of
    the same declaration.

    `SKIP` on overlap: two sweeps at once would both read the same expired rows,
    and while a second delete is a harmless no-op there is no reason to pay for
    the race.
    """
    return Schedule(
        action=ScheduleActionStartWorkflow(
            PURGE_WORKFLOW,
            PurgeExports(retention_days=EXPORT_RETENTION_DAYS),
            id=purge_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=PURGE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


#: The one periodic machine this app owns, declared as data (ADR
#: platform-lifecycle-1).
#:
#: **This is the far end of `Export.lifecycle`.** House rule 31 walks from the
#: model's `purged_by` to the service, to the activity above that calls it, to
#: the workflow that executes that activity, to this declaration — and refuses
#: the declaration if the walk stops short. Delete this entry and the model's
#: promise becomes the poller that was never built, loudly, at the gate.
PURGE_EXPORTS = ScheduleDeclaration(
    name="exports.purge-expired",
    schedule_id=purge_schedule_id,
    schedule=purge_exports_schedule,
    log_prefix="exports",
)


ACTIVITIES: list[Callable[..., Any]] = [
    build_export_archive,
    record_export_failure,
    purge_expired_exports,
]

#: Discovered by `apps.workflows.client.discovered_schedules`, which the worker
#: consults at startup. One declaration per periodic machine this app owns.
SCHEDULES: list[ScheduleDeclaration] = [PURGE_EXPORTS]
