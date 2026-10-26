"""Writes for the exports app: every door and the build activity call these; each authorizes.

The archive is built in `activities.py`: a service's transaction must not span minutes of I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction

from apps.core.actor import Actor
from apps.core.authz import may_be_named, require
from apps.core.exceptions import Invalid, NotFound, as_invalid
from apps.core.log import get_logger
from apps.core.models import Tenant
from apps.core.retry import retry_floor_seconds
from apps.core.schemas import event_payload
from apps.core.service import service
from apps.core.time import now
from apps.events.services import emit
from apps.exports.events import EXPORT_COMPLETED, EXPORT_FAILED, EXPORT_REQUESTED
from apps.exports.models import Export
from apps.exports.schemas import ExportOut
from apps.exports.types import BuildExport, PurgeOutcome
from apps.files import storage as files_storage
from apps.workflows.services import start_workflow_on_commit, workflow_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import datetime

    from apps.files.models import FileVersion

log = get_logger("apps.exports.services")

#: What may appear un-redacted in log lines and audit `input`: an allow-list of non-personal words.
LOG_KEYS: frozenset[str] = frozenset({"scope", "idempotency_key"})


def _publish_export(name: str, *, tenant: Tenant, export: Export, actor: Actor) -> None:
    """Say what happened, in the transaction it happened in, in the REST shape."""
    emit(name=name, tenant=tenant, payload=event_payload(ExportOut.from_orm(export)), actor=actor)


@service
def create_export(
    *,
    tenant: Tenant,
    actor: Actor,
    scope: str = Export.Scope.ORGANIZATION,
    idempotency_key: str = "",
) -> Export:
    """Ask for an archive, and start the run that builds it.

    **The name is `create_` and not `request_`, and that is the lexicon rather
    than a preference**: `request` is not one of the verbs `quality/rules.yaml`
    declares for a service (house rule 16), and adding a verb is a change to a
    file this app does not own. What the row IS has not changed — an export
    somebody asked for — and the EVENT is still `exports.export.requested`,
    which is the name a subscriber matches on.

    **Two bars behind one action key.** `export.create` asks
    `policies.can_request`, which reads the scope off the row being made: an
    export of the actor's own subtree needs only the key a `member` holds by
    default, because the walk
    reads exactly what `visible_to` already lets this actor see at every other
    door; a **tenant-wide** export needs `administers_the_whole_tenant` — the
    same ceiling erasure stands behind, deliberately reused rather than
    restated.

    **The hat decides where the row lands**, as everywhere else here: there is
    no `organization=` parameter, so no caller can put an export in a branch it
    holds no membership over. A tenant-wide export still lands at the acting
    hat; what `scope` changes is how wide the WALK goes, not who owns the
    receipt.

    `idempotency_key` is the caller's own name for the request. Sending one
    twice returns the first row and starts no second run — which matters more
    here than almost anywhere, because the retry of a request nobody saw the
    answer to would otherwise be a second copy of a customer's whole database
    in a bucket.
    """
    if actor.org is None:
        # Fails closed, like every other unresolved scope here: a row written
        # with no organization would be invisible to every read in the product,
        # including the root's.
        raise Invalid(
            {"organization": ["This request resolved no acting organization to export from."]}
        )
    if scope not in Export.Scope.values:
        raise Invalid(
            {"scope": [f"An export covers one of {', '.join(Export.Scope.values)}; got {scope!r}."]}
        )

    if idempotency_key:
        # Both halves of the read, on the acting hat's own node rather than its
        # subtree: a key is this organization's name for its own request, and a
        # child's row carrying the same word is a different request.
        already = (
            Export.objects.for_tenant(tenant)
            .visible_to(actor.org)
            .filter(organization=actor.org, idempotency_key=idempotency_key)
            .first()
        )
        if already is not None:
            log.info(
                "exports.export.replayed",
                export_id=str(already.pk),
                idempotency_key=idempotency_key,
            )
            return already

    export = Export(
        tenant=tenant,
        organization=actor.org,
        # `requested_by_id` rather than `requested_by=`: `Actor.user` is typed
        # `AbstractBaseUser | None` because `core` may not name the concrete
        # `accounts.User` (house rule 1 and the layer contract), and the id is
        # the field the column actually holds.
        requested_by_id=actor.user.pk if actor.user is not None else None,
        scope=scope,
        idempotency_key=idempotency_key,
    )
    # Authorized against the row being made, so `can_request` can read the
    # scope off it — the same shape `widget.approve` uses to ask its question
    # over the widget's own branch. Before `save()`, so a refusal writes
    # nothing at all.
    require(actor, "export.create", export)
    with as_invalid():
        export.full_clean()
    export.save()
    _publish_export(EXPORT_REQUESTED, tenant=tenant, export=export, actor=actor)
    # Streaming a customer's whole database into a zip is exactly the shape that
    # must survive a deploy, so it is a workflow and not the rest of this
    # function. The start is registered on this transaction's commit: a request
    # that rolls back exports nothing. The id is deterministic and derived from
    # the row (house rule 18), so a retried request starts one run, not two.
    start_workflow_on_commit(
        workflow="ExportTenantDataWorkflow",
        arg=BuildExport(export_id=str(export.pk), retry_floor=retry_floor_seconds()),
        tenant=tenant,
        user=actor.user,
        # The hat rides along, so the activity that runs an hour later reads as
        # the branch that asked rather than as the whole tenant.
        org=actor.org,
        id=workflow_id(tenant=tenant, app="exports", noun="export", key=str(export.pk)),
    )
    return export


# door: only this tree's own hands reach it — the build activity's first step.
@service
def mark_export_running(*, tenant: Tenant, actor: Actor, export: Export) -> Export:
    """Say that the walk has started. **Idempotent, because Temporal retries.**

    A row that is already `running` stays `running` and a row that has already
    finished is left alone — a retry that landed after the first attempt
    completed must not reopen a finished export.
    """
    # Reach before capability (rule 26): a refusal about an unreachable row would confirm it exists.
    if not may_be_named(actor, export):
        raise NotFound()
    require(actor, "export.build", export)
    if export.status != Export.Status.PENDING:
        return export
    export.status = Export.Status.RUNNING
    export.save(update_fields=["status", "updated_at"])
    return export


# door: only this tree's own hands reach it — the build activity's last step.
@service
def finish_export(
    *,
    tenant: Tenant,
    actor: Actor,
    export: Export,
    # reach: this row is not a reference a caller supplied — it was created
    # three lines earlier, in the same activity, by `files.services.store_stream`
    # filing the archive this call is about, and there is no door to this
    # service at all (the build activity IS its door). `may_be_named` answers
    # "could this actor have reached this row through a door", and the actor
    # here is deliberately the SYSTEM (`activities._actor_for`), for which that
    # question has no useful answer — asking it would be a check that cannot
    # fail, which is worse than none because it reads like one that can. What
    # this parameter genuinely needs guarding against is a version belonging to
    # a DIFFERENT export, and that is a question about the two rows rather than
    # about the actor: the refusal below asks it directly.
    version: FileVersion,
    manifest: dict[str, Any],
) -> Export:
    """Record the archive that was built, and say so. **The run's last write.**

    **One parameter for the artifact, not three** (XPr). It used to take
    `artifact_key` and `artifact_bytes` as separate values a caller assembled,
    which is three chances for a row to describe an object that is not the one
    that was written. Now it takes the `FileVersion` the files seam handed back
    and reads all three off it in one statement — the key, the measured size and
    the relation — so the row cannot claim a size the store disagrees with.

    The manifest handed in here is the SAME object the activity wrote into the
    zip as `manifest.json`, which is what makes the row and the artifact unable
    to disagree — `tests/test_archive.py` compares the two against the database
    three ways, and the three-way is only meaningful because there is one
    document.

    Idempotent: a retry that arrives after the row is already `completed` keeps
    the first artifact rather than pointing the row at a second one. That is not
    politeness, it is the difference between an orphaned object in a bucket and
    an object the purge can still find.
    """
    # Reach before capability (rule 26): a refusal about an unreachable row would confirm it exists.
    if not may_be_named(actor, export):
        raise NotFound()
    require(actor, "export.build", export)
    if version.tenant_id != export.tenant_id or version.organization_id != export.organization_id:
        # The belt the reachability clause on the parameter above promises. A
        # version filed for one part of the network, recorded on another part's
        # export, would be a row pointing at bytes its own readers cannot see —
        # invisible under `visible_to`, undeletable by a purge that reads the
        # tenant off the export, and wrong in the one column a departing
        # customer checks.
        raise Invalid(
            {
                "version": [
                    "This artifact belongs to a different tenant or organization from the "
                    "export it is being recorded on."
                ]
            }
        )
    if export.status == Export.Status.COMPLETED:
        return export
    export.status = Export.Status.COMPLETED
    # All three off the one row the seam measured. `size_bytes` is null only
    # while a version is PENDING, and what `store_stream` returns is STORED —
    # the check constraint `fileversion_stored_is_measured` holds that in the
    # database, so the `or 0` is a type narrowing and never a real branch.
    export.artifact_version = version
    export.artifact_key = str(version.key)
    export.artifact_bytes = int(version.size_bytes or 0)
    export.manifest = manifest
    export.completed_at = now()
    export.error = ""
    export.save(
        update_fields=[
            "status",
            "artifact_version",
            "artifact_key",
            "artifact_bytes",
            "manifest",
            "completed_at",
            "error",
            "updated_at",
        ]
    )
    _publish_export(EXPORT_COMPLETED, tenant=tenant, export=export, actor=actor)
    return export


# door: only this tree's own hands reach it — the build workflow's way out once retries are spent.
@service
def record_export_failure(*, tenant: Tenant, actor: Actor, export: Export, error: str) -> Export:
    """Say that the walk did not finish, and why. **No partial artifact.**

    `artifact_key` is left blank on purpose and is the assertion this service
    exists to make: a run that died halfway wrote a half-built object into
    storage, and a row pointing at it would offer a customer a truncated
    archive that opens, lists some of their tables and is missing the rest. The
    key stays blank, `is_downloadable` stays false, and the object is left for
    the purge — which sweeps by age over every row and does not care what
    status it is in.

    `error` is the activity's own complaint, walked out of Temporal's cause
    chain by the workflow. A row that said "Activity task failed" would be true
    and useless to whoever reads it six weeks later.
    """
    # Reach before capability (rule 26): a refusal about an unreachable row would confirm it exists.
    if not may_be_named(actor, export):
        raise NotFound()
    require(actor, "export.build", export)
    export.status = Export.Status.FAILED
    export.error = error[:2000]
    export.save(update_fields=["status", "error", "updated_at"])
    _publish_export(EXPORT_FAILED, tenant=tenant, export=export, actor=actor)
    return export


# door: only this tree's own hands reach it — deployment housekeeping, run by its declared schedule.
@service
def purge_exports(*, before: datetime, tenant: Tenant | None) -> PurgeOutcome:
    """Delete the archives older than `before`, from storage AND from the table.

    **`tenant` is declared, must be `None`, and is REFUSED otherwise.**
    `@service` writes an `AuditEntry` for every service that DECLARES a `tenant`
    (ADR core-8), and `None` is that ADR's named population: the deployment's
    own actions, the ones a compliance trail exists for. A sweep that deleted
    two hundred customers' archives and left no record of having run is the
    second half of the poller that was never built — nobody can tell it apart
    from one that never fired. `apps.connections.purge_inbound_webhooks` is the
    sibling precedent and this is the same shape.

    So the parameter cannot be dropped — the audit row is read off the signature
    — and it used to be documented as "always `None`" with nothing enforcing
    it. That made the signature a lie a reader could act on: it offers a
    `tenant`, the body ignores it, and a caller who passed one got a
    **deployment-wide** purge over every customer's archives and a success
    return saying how many. Driven on the baseline: asked for one tenant, it took
    that tenant's expired row AND its neighbour's, `exports=2`, no complaint. A
    parameter is a promise; the only promise this one can keep is that it is not
    used, so a non-`None` value is refused here rather than silently widened.

    **The artifact goes first, then the row, and the order is the whole
    design.** A crash between the two leaves a row whose key names an object
    that is already gone — which `is_downloadable` handles and which the next
    sweep tidies. The other order leaves an object in a bucket that nothing in
    the database points at any more: nobody can find it, nobody can bill for it
    and nobody can delete it, which is the failure a retention rule exists to
    prevent.

    **Through the files seam** (XPr): `files.storage.delete_object` reaches
    exactly the archive's own key, belted by `refuse_foreign_key` so a purge can
    only ever destroy bytes inside the tenant that owns the row it read them
    off. `delete_prefix` — the other half of that seam — is a tenant's whole
    object store and is what tenant close will use; a retention sweep that
    reached for it would delete every document the customer still has.

    It is idempotent because the STORE is: S3 and MinIO both answer a delete of
    an absent key with `204`, so a re-run inside the same window is safe without
    anything here catching an exception and calling it success — which Temporal
    demands, because an activity runs at least once.

    **What it deletes and what it deliberately leaves.** The OBJECT goes and the
    `Export` row goes. The `files.StoredFile` / `files.FileVersion` rows that
    described the object stay, holding a key whose bytes are gone — the same
    honest half-state the ordering paragraph above already names, one table
    further along. They are metadata, they are a few hundred bytes, and the
    liability this declaration exists to end is the COPY, which is gone. Reaching
    them needs a document-retirement service `apps.files` does not have yet
    (`archived_at` hides a document; nothing deletes one), and writing another
    app's rows from here rather than through its services is what house rule 10
    forbids. Named here rather than discovered, and it is XPr's recorded frontier.

    Idempotent by construction: it deletes by age, so a second run in the same
    window removes nothing.

    # authz: deployment housekeeping, run by a schedule as the system. It names
    # no tenant and resolves no actor: it is scoped by the clock, it deletes
    # rows rather than returning any, and the only value that leaves is a pair
    # of counts — so there is nobody whose reach could be exceeded.
    """
    if tenant is not None:
        raise Invalid(
            {
                "tenant": [
                    "This sweep is deployment-wide and cannot be narrowed to one "
                    "tenant: it deletes every tenant's archives older than "
                    "`before`, in one pass, as the deployment's own retention "
                    "housekeeping. The parameter is declared only so the audit "
                    "row records a platform action (ADR core-8) and its one "
                    "legal value is None. Nothing was deleted."
                ]
            }
        )
    # `select_related("tenant")` and not `only("pk", "artifact_key")` as this
    # read used to be: `files.storage.delete_object` is belted by
    # `refuse_foreign_key`, which needs the tenant ROW to build the prefix it
    # checks the key against, so the sweep fetches it once per query rather than
    # once per expired export.
    #
    # rule-8: the population is every tenant's expired archives at once, which
    # is what a retention sweep is — there is no tenant to scope by because the
    # sweep is not acting for one, and no hat either. Nothing crosses a tenant
    # boundary: the rows are deleted rather than returned, and only two integers
    # leave this function.
    everything_expired = Export.objects.filter(created_at__lt=before)
    expired = list(everything_expired.select_related("tenant").only("pk", "artifact_key", "tenant"))
    artifacts = 0
    for export in expired:
        if not export.artifact_key:
            continue
        files_storage.delete_object(tenant=export.tenant, key=export.artifact_key)
        artifacts += 1
    with transaction.atomic():
        # rule-8: the second half of the same tenant-crossing sweep. The rows
        # were selected above by age across every tenant at once; this deletes
        # exactly the primary keys that read returned, so narrowing it to a
        # tenant would be narrower than the population it is deleting from and
        # would leave every other tenant's expired archives behind.
        deleted, _ = Export.objects.filter(pk__in=[one.pk for one in expired]).delete()
    log.info("exports.purge.done", exports=int(deleted), artifacts=artifacts)
    return PurgeOutcome(exports=int(deleted), artifacts=artifacts)
