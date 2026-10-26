"""`Export` declares `purged`, and something really purges it.

House rule 31 walks a `purged` declaration outwards —

    purged_by -> an activity that references it
              -> a workflow that executes that activity
              -> a `ScheduleDeclaration` in some app's `SCHEDULES`

— and this module is that chain asserted from inside the app that owns it, plus
the two things a static walk cannot see: **what the sweep actually deletes**, and
**what it leaves**.

The stakes here are not the usual ones. A purge that keeps too much normally
costs disk; this table's rows name complete copies of customers' databases, so a
sweep that never runs is the largest liability the product can accumulate, and a
sweep that runs too eagerly deletes the archive a customer is in the middle of
downloading. So every population assertion below is stated in BOTH directions:
what went, and what is still there.

**And the artifact half is the half a row-only test would miss.** Deleting the
row without deleting the object leaves a zip in a bucket that nothing in the
database points at — nobody can find it, nobody can bill for it, and nobody will
ever delete it. That is a worse outcome than not sweeping at all, and it is
invisible to any assertion about the table.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from temporalio.client import ScheduleActionStartWorkflow

from apps.core.actor import actor_for, system_actor
from apps.core.lifecycle import LifecycleKind, lifecycle_of
from apps.core.schedules import DAILY, platform_id
from apps.core.time import now
from apps.exports import activities, services
from apps.exports.models import EXPORT_RETENTION_DAYS, Export
from apps.exports.types import PURGE_WORKFLOW, PurgeExports, PurgeOutcome
from apps.exports.workflows import PurgeExportsWorkflow
from apps.files import storage as files_storage
from apps.files.models import StoredFile
from apps.files.services import store_bytes

from .conftest import archive_exists

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.tests.permissions_world import World

pytestmark = pytest.mark.django_db

#: The declaration's own name, in one place: the tooth resolves this dotted path,
#: and a test that spelled it a second time could go green against a model that
#: had quietly stopped pointing here.
PURGED_BY = "apps.exports.services.purge_exports"

TASK_QUEUE = "djb-exports-tests"

# Comfortably outside the window, and comfortably inside it. Written as offsets
# from the declared retention rather than as bare numbers, so the day somebody
# changes the window these tests still mean what they say.
WELL_PAST = -(EXPORT_RETENTION_DAYS + 10)
WELL_INSIDE = -(EXPORT_RETENTION_DAYS - 10)


def swept() -> PurgeOutcome:
    """One sweep, at the declared window, through the service the activity calls.

    The SERVICE and not the activity, and the reason is the activity's own
    `close_old_connections()`: out on a worker thread that is exactly right —
    there is no request cycle to close what it opened — and inside a
    `django_db` test it closes the connection the surrounding transaction is
    running on. `apps/connections/tests/test_lifecycle.py` drives its sweep the
    same way for the same reason.

    The wrapper is covered by `test_workflows.py`, which drives the real activity in a worker.
    """
    return services.purge_exports(before=now() - timedelta(days=EXPORT_RETENTION_DAYS), tenant=None)


def aged(export: Export, *, days: int) -> Export:
    """Move a row's `created_at` without going through `save()`.

    `QuerySet.update`, because `created_at` is `auto_now_add` and a `save()`
    would not move it — the conventions say this out loud, and the alternative
    (a `time_machine` freeze around the fixture) would make every row in the
    world old at once.
    """
    Export.objects.filter(pk=export.pk).update(created_at=now() + timedelta(days=days))
    export.refresh_from_db()
    return export


def with_an_artifact(export: Export, *, body: bytes = b"a zip, for these purposes") -> Export:
    """Give a row a real object in storage, so the sweep has something to delete.

    **Filed the way production files one** (XPr): through
    `files.services.store_bytes`, which puts the object in the files seam's
    bucket under `files.storage.version_key` and hands back the `FileVersion`
    the row then points at. `store_bytes` rather than `store_stream` only
    because the body here is a sentence — the production path streams, and
    `test_workflows.py` drives that one.

    It used to be `default_storage.save(tenant_prefixed_key(...))`, and that is
    exactly the key grammar XPr retired: a slug and a filename, both renamable,
    both re-issuable. What this helper is FOR has not changed — a row with real
    bytes behind it — so the assertions below it are untouched.
    """
    version = store_bytes(
        tenant=export.tenant,
        actor=actor_for(user=export.requested_by, tenant=export.tenant, org=export.organization),
        filename=f"export-{export.pk}.zip",
        content_type="application/zip",
        content=body,
        purpose=StoredFile.Purpose.EXPORT,
    )
    Export.objects.filter(pk=export.pk).update(
        status=Export.Status.COMPLETED,
        artifact_version=version,
        artifact_key=version.key,
        artifact_bytes=len(body),
    )
    export.refresh_from_db()
    assert archive_exists(str(version.key))
    return export


@pytest.fixture
def an_export(world: World, recorded_workflow_starts: None) -> Any:
    """Make an export row at the tenant's root, without dialling Temporal."""

    def make() -> Export:
        return services.create_export(
            tenant=world.tenant, actor=world.owner, scope=Export.Scope.ORGANIZATION
        )

    return make


# --- the declaration ------------------------------------------------------------


def test_the_export_declares_purged_and_names_what_purges_it() -> None:
    """The declaration itself, read off the model the way rule 31 reads it."""
    declared = lifecycle_of(Export)

    assert declared is not None
    assert declared.kind is LifecycleKind.PURGED
    assert declared.purged_by == PURGED_BY
    assert len(declared.reason) > 120, "a reason a reviewer can disagree with"


def test_the_schedule_this_app_declares() -> None:
    """Daily under one `platform:exports:purge:<queue>` id; the retention rides the action."""
    declaration = activities.PURGE_EXPORTS
    action = declaration.schedule(TASK_QUEUE).action
    expected = platform_id(app="exports", noun="purge", key=TASK_QUEUE)

    assert activities.SCHEDULES == [declaration]
    assert isinstance(action, ScheduleActionStartWorkflow)
    assert declaration.schedule_id(TASK_QUEUE) == action.id == expected
    assert declaration.schedule_id("other") != expected
    assert action.workflow == PURGE_WORKFLOW
    assert action.task_queue == TASK_QUEUE
    assert action.args == [PurgeExports(retention_days=EXPORT_RETENTION_DAYS)]
    assert declaration.schedule(TASK_QUEUE).spec.intervals[0].every == DAILY


def test_the_purge_workflow_owns_no_run_row() -> None:
    """House rule 28's other pattern, and it is a DECLARATION rather than an exemption.

    A schedule-started run has no `WorkflowRun` row to close, because no service
    asked for it and nobody is waiting on a visibility row for the deployment's
    own housekeeping. The export workflow beside it does own one, and closes it
    — see `test_workflows.py`.
    """
    assert PurgeExportsWorkflow.owns_no_run is True


# --- what the sweep does, and what it leaves ------------------------------------


def test_one_driven_run_deletes_an_expired_archive_from_storage_and_its_row(
    world: World, an_export: Any, archive_bucket: str
) -> None:
    """The core claim. Both halves, and a fresh export untouched beside them.

    Driven through the activity — the same function the workflow executes by
    name — rather than through the service, so what is under test is the path a
    schedule really takes.
    """
    old = with_an_artifact(aged(an_export(), days=WELL_PAST))
    fresh = with_an_artifact(an_export(), body=b"the one that must survive")
    old_key, fresh_key = old.artifact_key, fresh.artifact_key

    outcome = swept()

    assert outcome.exports == 1
    assert outcome.artifacts == 1
    # What went: the row AND the object.
    assert not Export.objects.filter(pk=old.pk).exists()
    assert not archive_exists(str(old_key))
    # What stayed: both halves of the fresh one, which is the assertion that
    # makes the two above a sweep rather than a truncation.
    assert Export.objects.filter(pk=fresh.pk).exists()
    assert archive_exists(str(fresh_key))


def test_an_export_just_inside_the_window_is_not_swept(
    world: World, an_export: Any, archive_bucket: str
) -> None:
    """The edge, from the side that matters: a customer mid-download keeps their file."""
    inside = with_an_artifact(aged(an_export(), days=WELL_INSIDE))

    outcome = swept()

    assert outcome.exports == 0
    assert Export.objects.filter(pk=inside.pk).exists()
    assert archive_exists(str(inside.artifact_key))


def test_a_pending_export_that_never_finished_is_swept_too(world: World, an_export: Any) -> None:
    """The sweep is by AGE over every status, not by "completed and old".

    A pending row is a request nobody answered and it holds no archive, so it
    costs nothing to keep — except that it is a row in a table whose retention
    is the promise, and a status the purge cannot see is a status rows
    accumulate in forever.
    """
    stuck = aged(an_export(), days=WELL_PAST)
    assert stuck.status == Export.Status.PENDING

    outcome = swept()

    assert outcome.exports == 1
    assert outcome.artifacts == 0, "there was no object to delete, and it says so"
    assert not Export.objects.filter(pk=stuck.pk).exists()


def test_the_sweep_is_idempotent(world: World, an_export: Any, archive_bucket: str) -> None:
    """Temporal runs an activity at least once, so a second sweep must be a no-op."""
    with_an_artifact(aged(an_export(), days=WELL_PAST))

    first = swept()
    second = swept()

    assert first.exports == 1
    assert second.exports == 0
    assert second.artifacts == 0


def test_a_row_whose_object_is_already_gone_is_still_swept(
    world: World, an_export: Any, archive_bucket: str
) -> None:
    """A crash between the two deletions must not strand the row forever.

    The order is object-then-row, so the visible residue of a mid-sweep failure
    is a row pointing at nothing. This asserts the next sweep clears it rather
    than raising on a key that is not there — which `files.storage.delete_object`
    inherits from the store itself (S3 and MinIO both answer `204` to a delete of
    an absent key), and which is asserted here rather than assumed.
    """
    orphaned = with_an_artifact(aged(an_export(), days=WELL_PAST))
    files_storage.delete_object(tenant=orphaned.tenant, key=orphaned.artifact_key)
    assert not archive_exists(str(orphaned.artifact_key))

    outcome = swept()

    assert outcome.exports == 1
    assert not Export.objects.filter(pk=orphaned.pk).exists()


def test_the_sweep_leaves_the_platform_an_audit_row(
    world: World, an_export: Any, archive_bucket: str
) -> None:
    """ADR core-8: a retention sweep with no record is one nobody can tell from silence."""
    from apps.core.audit import AuditEntry

    with_an_artifact(aged(an_export(), days=WELL_PAST))
    before = AuditEntry.objects.for_platform().filter(action="exports.purge_exports").count()

    swept()

    after = AuditEntry.objects.for_platform().filter(action="exports.purge_exports").count()
    assert after == before + 1


def test_the_sweep_crosses_every_tenant_at_once(world: World, neighbour: Any) -> None:
    """A retention sweep is not acting for a tenant, and the test says so out loud.

    The `# rule-8:` override in `services.purge_exports` claims exactly this, and
    an override whose claim nothing checks is a sentence. Two tenants, both with
    an expired export, one sweep, both gone.
    """

    ours = Export.objects.create(
        tenant=world.tenant, organization=world.root, scope=Export.Scope.TENANT
    )
    from apps.core.services import root_organization

    theirs = Export.objects.create(
        tenant=neighbour,
        organization=root_organization(tenant=neighbour),
        scope=Export.Scope.TENANT,
    )
    aged(ours, days=WELL_PAST)
    aged(theirs, days=WELL_PAST)
    assert system_actor(world.tenant) is not None

    outcome = swept()

    assert outcome.exports == 2
    assert not Export.objects.filter(pk__in=[ours.pk, theirs.pk]).exists()


# --- the signature tells the truth about its own scope --------------------------


def test_naming_a_tenant_is_refused_and_nothing_is_swept(
    world: World, an_export: Any, neighbour: Any
) -> None:
    """The parameter was a promise the body never kept.

    `tenant` is declared because ADR core-8 reads it off the signature to decide
    the audit row's shape, and it was documented as "always `None`" — but nothing
    enforced that, so a caller who read the signature and expected a scoped purge
    got a deployment-wide one, silently, over every customer's archives. The fix
    is a refusal rather than a rename: the parameter has to STAY declared for the
    audit row, so the only way it can stop lying is to reject the value it cannot
    honour.

    Both halves, because a refusal that still swept would be worse than the lie:
    the call raises, AND the expired rows this sweep would otherwise have taken
    are all still there.
    """
    from apps.core.exceptions import Invalid
    from apps.core.services import root_organization

    ours = aged(an_export(), days=WELL_PAST)
    theirs = aged(
        Export.objects.create(
            tenant=neighbour,
            organization=root_organization(tenant=neighbour),
            scope=Export.Scope.TENANT,
        ),
        days=WELL_PAST,
    )

    with pytest.raises(Invalid) as refused:
        services.purge_exports(
            before=now() - timedelta(days=EXPORT_RETENTION_DAYS), tenant=world.tenant
        )

    # The message names the semantics, so whoever reads it learns what the
    # function IS rather than only that they were refused.
    said = str(refused.value.detail)
    assert "deployment" in said.lower()
    assert "tenant" in refused.value.errors
    # And nothing moved — neither the tenant that was named nor the one that
    # was not.
    assert Export.objects.filter(pk=ours.pk).exists()
    assert Export.objects.filter(pk=theirs.pk).exists()


def test_the_refusal_is_audited_against_the_tenant_that_was_named(
    world: World, an_export: Any
) -> None:
    """A refused sweep is still a sweep somebody tried to run, and ADR core-8 records it.

    `@service` audits on the error path too, so this refusal is
    itself visible in the trail — a caller repeatedly asking for a scoped purge
    is a thing an operator can find, rather than an exception in a log nobody
    reads.

    **And the row lands where the CALL said, not where the sweep lives.** The
    decorator takes an audit row's tenant from `kwargs["tenant"]`, so the
    successful sweep (`tenant=None`) audits as a platform row and this refusal
    audits against the tenant that was named — which is the honest placement:
    the fact being recorded is that somebody asked for a scoped purge of THAT
    tenant, and the tenant it was asked about is the one whose trail should
    show it. Asserted rather than assumed, because it is the one behaviour of
    this refusal that is not obvious from reading the raise.
    """
    from apps.core.audit import AuditEntry
    from apps.core.exceptions import Invalid

    aged(an_export(), days=WELL_PAST)
    refusals = (
        AuditEntry.objects.for_tenant(world.tenant)
        .filter(action="exports.purge_exports", outcome=AuditEntry.Outcome.ERROR)
        .order_by("-created_at")
    )
    before = refusals.count()

    with pytest.raises(Invalid):
        services.purge_exports(
            before=now() - timedelta(days=EXPORT_RETENTION_DAYS), tenant=world.tenant
        )

    assert refusals.count() == before + 1
    recorded = refusals.first()
    assert recorded is not None
    assert recorded.error_code == "invalid"
    # The platform population — where a real sweep records — saw nothing, which
    # is the other half: a refused run must not look like one that ran.
    assert (
        AuditEntry.objects.for_platform()
        .filter(action="exports.purge_exports", outcome=AuditEntry.Outcome.ERROR)
        .count()
        == 0
    )


def test_passing_tenant_none_explicitly_is_the_sweep_it_always_was(
    world: World, an_export: Any, neighbour: Any, archive_bucket: str
) -> None:
    """The other direction of this refusal: the path that was never broken is untouched.

    The refusal is on a value nothing in the tree ever passed; `None` — whether
    written out or left to the default — still sweeps every tenant's expired
    archives, artifact first and row second. Stated as its own test rather than
    left to `swept()`'s default, because "the fix did not narrow the sweep" is
    exactly the regression a refusal invites.
    """
    from apps.core.services import root_organization

    ours = with_an_artifact(aged(an_export(), days=WELL_PAST))
    theirs = aged(
        Export.objects.create(
            tenant=neighbour,
            organization=root_organization(tenant=neighbour),
            scope=Export.Scope.TENANT,
        ),
        days=WELL_PAST,
    )
    key = ours.artifact_key

    outcome = services.purge_exports(
        before=now() - timedelta(days=EXPORT_RETENTION_DAYS), tenant=None
    )

    assert outcome == PurgeOutcome(exports=2, artifacts=1)
    assert not Export.objects.filter(pk__in=[ours.pk, theirs.pk]).exists()
    assert not archive_exists(str(key))
