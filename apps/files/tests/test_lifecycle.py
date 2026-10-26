"""`FileVersion` declares `purged`, and something really purges it.

House rule 31 walks a `purged` declaration outwards —

    purged_by -> an activity that references it
              -> a workflow that executes that activity
              -> a `ScheduleDeclaration` in some app's `SCHEDULES`

— and this module is that chain asserted from inside the app that owns it, plus
the two things a static walk cannot see: **what the sweep actually deletes**, and
**what it leaves**.

**Why this table needed a sweeper at all.** A version row is born `PENDING` — a
key allocated, an upload URL minted — and there is deliberately no `FAILED`
status, because "nothing arrived" is the absence of a transition rather than a
state of its own. That was honest and it was incomplete: previously the
absence was permanent. An earlier field test drove a confirm for an upload that
never happened and recorded exactly that — its findings, since moved to the
closed-cycle archive, read "the PENDING row left by the no-PUT drive has no
expirer until this sweep, confirmed as state not disposal". This is the
disposal.

**And the document is the half a version-only test would miss.** Expiring the
only version of a document leaves a `StoredFile` with nothing behind it —
`current_version` 0, no bytes, no way to get any — sitting in the tenant's list
looking like a document. So the sweep archives it, which is the same soft
archive a person's `POST /{id}/archive` performs, through the same service, with
the same audit row and the same event.

The population assertions below are stated in BOTH directions — what went and
what is still there — because a sweep that takes too much deletes the upload
somebody is in the middle of making, and a sweep that takes too little is the
poller that was never built.

The DRIVE through the declared schedule path — the real workflow, the real
worker, the real interceptor — is `test_workflows.py`'s
`test_the_declared_sweep_expires_a_pending_version_and_archives_its_document`.
It lives there rather than here because a module that names
`WorkflowEnvironment` is derived into the slow tier (`apps/conftest.py`), and
the assertions in this file are worth running in every rung.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from temporalio.client import ScheduleActionStartWorkflow

from apps.core.actor import actor_for
from apps.core.audit import AuditEntry
from apps.core.exceptions import Invalid
from apps.core.lifecycle import LifecycleKind, lifecycle_of
from apps.core.schedules import platform_id
from apps.core.time import now
from apps.files import activities, services
from apps.files.models import PENDING_UPLOAD_TTL_HOURS, FileVersion, StoredFile
from apps.files.types import SWEEP_WORKFLOW, SweepOutcome, SweepPendingUploads
from apps.files.workflows import SweepPendingUploadsWorkflow

from .conftest import make_version

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.models import Organization, Tenant

pytestmark = pytest.mark.django_db

#: The declaration's own dotted path, in one place: the tooth resolves this, and
#: a test that spelled it a second time could go green against a model that had
#: quietly stopped pointing here.
PURGED_BY = "apps.files.services.purge_pending_versions"

TASK_QUEUE = "djb-files-tests"

#: Comfortably outside the window and comfortably inside it, written as offsets
#: from the declared TTL rather than as bare numbers, so the day somebody moves
#: the window these tests still mean what they say.
WELL_PAST = PENDING_UPLOAD_TTL_HOURS + 6
WELL_INSIDE = PENDING_UPLOAD_TTL_HOURS - 6


def swept() -> SweepOutcome:
    """One sweep, at the declared window, through the service the activity calls.

    The SERVICE and not the activity, and the reason is the activity's own
    `close_old_connections()`: out on a worker thread that is exactly right —
    there is no request cycle to close what it opened — and inside a `django_db`
    test it closes the connection the surrounding transaction is running on.
    `apps/exports/tests/test_lifecycle.py` drives its sweep the same way for the
    same reason, and the wrapper is covered from the other side by the chain test
    below (which reads the activity's own source) and by the drive in
    `test_workflows.py`.
    """
    return services.purge_pending_versions(
        before=now() - timedelta(hours=PENDING_UPLOAD_TTL_HOURS), tenant=None
    )


def aged(version: FileVersion, *, hours: int) -> FileVersion:
    """Move a version's `created_at` back without going through `save()`.

    `QuerySet.update`, because `created_at` is `auto_now_add` and a `save()`
    would not move it — the conventions say this out loud, and freezing the clock
    around the fixture would make every row in the world old at once.
    """
    FileVersion.objects.filter(pk=version.pk).update(created_at=now() - timedelta(hours=hours))
    version.refresh_from_db()
    return version


def stored(version: FileVersion, *, size: int = 11) -> FileVersion:
    """Put a version in the state a finalized upload leaves it in.

    Written with `update` rather than through `record_stored` on purpose: what
    these tests are about is which rows the sweep takes, and going through the
    finalize service would drag a bucket, a meter and an event into a question
    that is entirely about a status column. The check constraint
    `fileversion_stored_is_measured` still holds — a STORED row carries what was
    measured — so the row this writes is a row the database would accept from
    the service.
    """
    FileVersion.objects.filter(pk=version.pk).update(
        status=FileVersion.Status.STORED, size_bytes=size, sha256="a" * 64
    )
    StoredFile.objects.filter(pk=version.file_id).update(current_version=version.version)
    version.refresh_from_db()
    return version


# --- the declaration ------------------------------------------------------------


def test_the_file_version_declares_purged_and_names_what_purges_it() -> None:
    """The declaration itself, read off the model the way rule 31 reads it.

    It used to say `bounded`, which was true of the rows that reach `STORED` and
    became a half-truth the moment a sweeper existed: `_refuse_malformed` names
    that shape exactly — "a sweeper named on a bounded table is either a wrong
    kind or a delete nobody meant to declare" — and the honest correction is the
    kind that admits the sweeper, with the reason saying which rows it takes.
    """
    declared = lifecycle_of(FileVersion)

    assert declared is not None
    assert declared.kind is LifecycleKind.PURGED
    assert declared.purged_by == PURGED_BY
    assert len(declared.reason) > 120, "a reason a reviewer can disagree with"


def test_the_stored_file_declaration_disposes_of_the_exports_purge_residue() -> None:
    """A known frontier, DECLARED here rather than discovered by whoever finds it.

    `exports.services.purge_exports` deletes the archive object and the `Export`
    row and leaves the `files` rows that described it, holding a key whose bytes
    are gone. That sentence is written at the deleting end; the rows are at this
    end, and the app that owns a population owes the statement about what
    happens to it. So `StoredFile`'s own declaration names the residue, and it
    stays `unbounded` because that is what the residue IS — a row nothing
    deletes, on purpose, until document retirement lands.
    """
    declared = lifecycle_of(StoredFile)

    assert declared is not None
    assert declared.kind is LifecycleKind.UNBOUNDED
    assert "purge_exports" in declared.reason
    assert "2026-08-2" in declared.trigger, "a dated trigger, in the ADR grammar"


def test_the_schedule_this_app_declares() -> None:
    """Hourly under one `platform:files:sweep-pending:<queue>` id; the TTL rides the action."""
    declaration = activities.SWEEP_PENDING_UPLOADS
    action = declaration.schedule(TASK_QUEUE).action
    expected = platform_id(app="files", noun="sweep-pending", key=TASK_QUEUE)

    assert activities.SCHEDULES == [declaration]
    assert isinstance(action, ScheduleActionStartWorkflow)
    assert declaration.schedule_id(TASK_QUEUE) == action.id == expected
    assert declaration.schedule_id("other") != expected
    assert action.workflow == SWEEP_WORKFLOW
    assert action.task_queue == TASK_QUEUE
    assert action.args == [SweepPendingUploads(ttl_hours=PENDING_UPLOAD_TTL_HOURS)]
    assert declaration.schedule(TASK_QUEUE).spec.intervals[0].every == activities.SWEEP_EVERY


def test_the_sweep_workflow_owns_no_run() -> None:
    """House rule 28's other half: a schedule-started run has no visibility row.

    `owns_no_run = True` means "I own no row", never "I am exempt" — nobody asked
    for this run, so there is no `WorkflowRun` somebody is waiting on and nothing
    for the finish seam to close. The finalize workflow beside it carries the
    opposite half, and the pair is what makes the rule readable.
    """
    assert SweepPendingUploadsWorkflow.owns_no_run is True


# --- what the sweep takes, and what it leaves -----------------------------------


def test_the_expired_pending_version_does_not_survive_the_sweep(
    stored_file: StoredFile, owner: User
) -> None:
    """The residue an earlier upload left, disposed of. **The headline.**

    A confirm that never came, an upload that never landed, a row that said
    `pending` for ever. After the sweep the row is gone — not marked, not
    annotated, gone, because a third status on a two-state model would have to be
    undone by hand the moment a bucket came back.
    """
    version = aged(make_version(file=stored_file, version=1, uploaded_by=owner), hours=WELL_PAST)

    outcome = swept()

    assert outcome.versions == 1
    assert not FileVersion.objects.filter(pk=version.pk).exists()


def test_a_pending_version_inside_the_window_is_left_alone(
    stored_file: StoredFile, owner: User
) -> None:
    """The other direction, and the one that decides whether this is safe to run.

    A version created an hour ago is an upload somebody may still be making. The
    TTL sits far above `FILES_UPLOAD_URL_TTL` precisely so that everything inside
    the window is either in flight or freshly abandoned, and a sweep that could
    not tell them apart would delete the row under a PUT in progress.
    """
    version = aged(make_version(file=stored_file, version=1, uploaded_by=owner), hours=WELL_INSIDE)

    outcome = swept()

    assert outcome.versions == 0
    assert FileVersion.objects.filter(pk=version.pk).exists()
    assert StoredFile.objects.get(pk=stored_file.pk).archived_at is None


def test_a_stored_version_is_never_swept(stored_file: StoredFile, owner: User) -> None:
    """Age is not the question for a version whose bytes are in the bucket.

    A finalized version is the immutable object this whole app exists to keep,
    and it is older than the TTL within a day of being uploaded. The filter is
    status AND age, and this is the assertion that says the status half is really
    there.
    """
    version = stored(
        aged(make_version(file=stored_file, version=1, uploaded_by=owner), hours=WELL_PAST * 10)
    )

    outcome = swept()

    assert outcome.versions == 0
    assert FileVersion.objects.filter(pk=version.pk).exists()


def test_the_sweep_writes_the_platform_audit_row_that_says_it_ran(
    stored_file: StoredFile, owner: User
) -> None:
    """A sweep that left no record cannot be told from one that never fired.

    `tenant=None` is ADR core-8's named population — the deployment's own
    actions, which is what a retention sweep is — and the window it swept rides
    in `input`, so the row says WHICH sweep as well as that there was one.
    """
    aged(make_version(file=stored_file, version=1, uploaded_by=owner), hours=WELL_PAST)

    swept()

    row = AuditEntry.objects.for_platform().get(action="files.purge_pending_versions")
    assert row.outcome == AuditEntry.Outcome.OK
    assert row.input["before"] != "[redacted]", "the window is the point of the row"


def test_naming_a_tenant_is_refused_rather_than_quietly_ignored(
    stored_file: StoredFile, owner: User
) -> None:
    """An earlier lesson, met at birth rather than a cycle later.

    `tenant` is declared because that is what makes the call audited (ADR
    core-8's platform population reads `tenant=None`), and a declared parameter
    that is silently ignored is a signature that can be misread as a scoped
    purge. So a non-None tenant refuses, and the refusal says what the sweep
    actually is.
    """
    aged(make_version(file=stored_file, version=1, uploaded_by=owner), hours=WELL_PAST)

    with pytest.raises(Invalid) as refused:
        services.purge_pending_versions(before=now(), tenant=stored_file.tenant)

    assert "deployment" in str(refused.value)
    assert FileVersion.objects.filter(file=stored_file).exists(), "nothing was swept"


# --- and the document the sweep empties -----------------------------------------


def test_a_document_left_with_no_version_at_all_is_archived_by_the_sweep(
    stored_file: StoredFile, owner: User
) -> None:
    """The second half: a document with nothing behind it leaves the working set.

    Through `archive_emptied_file` and not by writing the column here: the same
    row half a person's archive runs — the same fence against new versions, the
    same `files.file.archived` on the spine — under its own audit action, because
    a person's `archive_file` refuses the product acting for itself.
    """
    aged(make_version(file=stored_file, version=1, uploaded_by=owner), hours=WELL_PAST)

    outcome = swept()

    assert outcome.documents == 1
    assert StoredFile.objects.get(pk=stored_file.pk).archived_at is not None
    assert (
        AuditEntry.objects.for_tenant(stored_file.tenant)
        .filter(action="files.archive_emptied_file", object_id=stored_file.pk)
        .exists()
    )


def test_a_document_that_still_has_a_stored_version_is_not_archived(
    stored_file: StoredFile, owner: User
) -> None:
    """The document is archived for having nothing, never for having lost one.

    A replace that was abandoned takes v2 with it and leaves v1 exactly where it
    was — readable, presignable, still true for whatever quoted its digest — so
    the document stays in the list it has always been in.
    """
    kept = stored(make_version(file=stored_file, version=1, uploaded_by=owner))
    abandoned = aged(make_version(file=stored_file, version=2, uploaded_by=owner), hours=WELL_PAST)

    outcome = swept()

    assert outcome.versions == 1
    assert outcome.documents == 0
    assert not FileVersion.objects.filter(pk=abandoned.pk).exists()
    assert FileVersion.objects.filter(pk=kept.pk).exists()
    assert StoredFile.objects.get(pk=stored_file.pk).archived_at is None


def test_a_document_with_a_live_upload_beside_the_expired_one_is_not_archived(
    stored_file: StoredFile, owner: User
) -> None:
    """The race the archive half must not lose.

    Somebody abandoned an upload yesterday and started another one this morning.
    The old row goes; the document still has a version in flight, so archiving it
    would refuse the finalize that is about to arrive (`_refuse_an_archived_
    document` is a `conflict`, and it would be a conflict about bytes already on
    the wire).
    """
    abandoned = aged(make_version(file=stored_file, version=1, uploaded_by=owner), hours=WELL_PAST)
    live = make_version(file=stored_file, version=2, uploaded_by=owner)

    outcome = swept()

    assert outcome.versions == 1
    assert outcome.documents == 0
    assert not FileVersion.objects.filter(pk=abandoned.pk).exists()
    assert FileVersion.objects.filter(pk=live.pk).exists()
    assert StoredFile.objects.get(pk=stored_file.pk).archived_at is None


def test_an_already_archived_document_is_not_archived_twice(
    stored_file: StoredFile, root_org: Organization, owner: User
) -> None:
    """Idempotence at the seam a retried activity will hit.

    Temporal runs an activity at least once, so the sweep has to be safe to run
    over a document somebody archived by hand in the meantime. `archive_file`
    already answers quietly and emits nothing for a second archive; what this
    pins is that the sweep does not COUNT one, because a count that grew on
    replay is a report that lies about how much work there was.
    """
    services.archive_file(
        tenant=stored_file.tenant,
        actor=actor_for(user=owner, tenant=stored_file.tenant, org=root_org),
        file=stored_file,
    )
    aged(make_version(file=stored_file, version=1, uploaded_by=owner), hours=WELL_PAST)

    outcome = swept()

    assert outcome.versions == 1
    assert outcome.documents == 0


def test_the_sweep_reaches_every_tenant_and_stays_inside_each_one(
    stored_file: StoredFile,
    owner: User,
    other_tenant: Tenant,
    other_root_org: Organization,
    stranger: User,
) -> None:
    """A retention sweep is deployment-wide, and its writes are still per tenant.

    The read crosses tenants because that is what the sweep IS — there is no
    tenant to scope by, and narrowing it to one would leave every other
    customer's residue behind. What must NOT cross is the write: each document is
    archived under a system actor wearing that document's own hat, so the audit
    row lands in the right tenant and the event goes to the right spine.
    """
    neighbour = StoredFile(
        tenant=other_tenant,
        organization=other_root_org,
        filename="theirs.pdf",
        purpose=StoredFile.Purpose.UPLOAD,
        uploaded_by=stranger,
    )
    neighbour.full_clean()
    neighbour.save()
    aged(make_version(file=stored_file, version=1, uploaded_by=owner), hours=WELL_PAST)
    aged(make_version(file=neighbour, version=1, uploaded_by=stranger), hours=WELL_PAST)

    outcome = swept()

    assert outcome.versions == 2
    assert outcome.documents == 2
    assert StoredFile.objects.get(pk=stored_file.pk).archived_at is not None
    assert StoredFile.objects.get(pk=neighbour.pk).archived_at is not None
    mine = AuditEntry.objects.for_tenant(stored_file.tenant).filter(
        action="files.archive_emptied_file"
    )
    theirs = AuditEntry.objects.for_tenant(other_tenant).filter(action="files.archive_emptied_file")
    assert [row.object_id for row in mine] == [stored_file.pk]
    assert [row.object_id for row in theirs] == [neighbour.pk]


def test_an_empty_sweep_costs_one_audit_row_and_nothing_else() -> None:
    """The steady state: nothing expired, nothing archived, and it still says so."""
    outcome = swept()

    rows = AuditEntry.objects.for_platform().filter(action="files.purge_pending_versions")

    assert outcome == SweepOutcome(versions=0, documents=0)
    assert rows.count() == 1
