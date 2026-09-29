"""Writes for the imports app. Every door calls these; nothing else writes.

The run's life is five services and one sweep:

* `create_import` — stage a file: authorize (`import.create` AND the noun's own
  `<kind>.create`), find the run these bytes already have or make one, start the
  check on commit;
* `record_import_preview` — the dry run's result: every row judged by the
  importer's row schema and a read-only natural-key lookup, written as
  `ImportRow`s with the counts — **and nothing written to the noun**;
* `apply_import` — the person's press: `previewed → importing`, start the apply;
* `apply_import_row` — ONE row, in ONE transaction with its outcome, which is
  what makes the apply idempotent per row: a retried activity finds the row
  settled and moves on, and a crash can never leave a noun row written without
  the outcome that says so;
* `finish_import` / `record_import_failure` / `cancel_import` — the ways out.

**The file itself is never read here.** Streaming bytes out of the object store
is I/O, and it is the check activity's (`activities.py`) — it hands this module
the parsed lines. A service holding a transaction open across a network read
would be principle 8's failure.

Refusals are `apps.core.exceptions` only (house rule 14). `import_invalid` is
this app's own and is registered below, beside the class that raises it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction
from pydantic import ValidationError

from apps.core.actor import Actor
from apps.core.authz import may_be_named, require
from apps.core.exceptions import (
    NON_FIELD_KEY,
    Conflict,
    DomainError,
    Invalid,
    NotFound,
    Remedy,
    register_refusal,
    wire_refusal,
)
from apps.core.log import get_logger
from apps.core.models import Tenant
from apps.core.service import service
from apps.core.time import now
from apps.events.services import emit
from apps.imports.events import IMPORT_APPLIED, IMPORT_FAILED, IMPORT_PREVIEWED, IMPORT_STAGED
from apps.imports.models import MAX_IMPORT_ROWS, Import, ImportRow
from apps.imports.schemas import ImportOut
from apps.imports.selectors import get_importer
from apps.imports.types import (
    APPLY_WORKFLOW,
    CHECK_WORKFLOW,
    ApplyImport,
    CheckImport,
    PurgeOutcome,
)
from apps.workflows.services import start_workflow_on_commit, workflow_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import datetime

    from apps.core.verbs import Importer
    from apps.files.models import FileVersion

log = get_logger("apps.imports.services")

#: What may appear un-redacted in this app's log lines and audit `input`: the
#: kind is a word from a declared vocabulary and the key is the caller's own
#: label. Row data is a customer's data and never logged.
LOG_KEYS: frozenset[str] = frozenset({"kind", "idempotency_key"})

#: How many rows one `bulk_create` writes at a time.
WRITE_BATCH = 500


register_refusal(
    code="import_invalid",
    boundary="service",
    remedy=(
        "The FILE was refused whole, before any row was judged: it is not UTF-8 CSV, its "
        "header does not match the importer's row schema (`errors` names the columns), "
        f"or it has more than {MAX_IMPORT_ROWS} data rows. The run is `failed` with this "
        "body in `failure`; nothing was written. Per-row refusals are NOT this code — "
        "those are listed on the run's rows and the rest of the file still applies."
    ),
    fact=(
        "This file cannot be imported as it is. It is not a UTF-8 CSV file, or its header "
        "row does not name the columns this kind of import reads, or it has more rows than "
        "one import takes. Nothing was imported."
    ),
    remedies=(
        Remedy("Fix the file and stage it again", "field:file_id"),
        Remedy("Read the columns this kind of import reads", "docs:openapi"),
    ),
    status=400,
)


class ImportInvalid(Invalid):
    """The whole file is refused — not CSV, the wrong header, or too many rows."""

    code = "import_invalid"
    default_detail = "This file cannot be imported as it is."


def _publish(name: str, *, tenant: Tenant, import_: Import, actor: Actor) -> None:
    """Say what happened, in the transaction it happened in, in the REST shape."""
    emit(
        name=name,
        tenant=tenant,
        payload=ImportOut.from_orm(import_).model_dump(mode="json"),
        actor=actor,
    )


def _importer_or_invalid(kind: str) -> Importer:
    importer = get_importer(kind)
    if importer is None:
        raise Invalid({"kind": [f"No importer is declared for {kind!r}."]})
    return importer


def _live_run_for(
    *, tenant: Tenant, actor: Actor, kind: str, digest: str, key: str
) -> Import | None:
    """The run these bytes (or this key) already have at the acting hat, if any."""
    runs = Import.objects.for_tenant(tenant).visible_to(actor.org).filter(organization=actor.org)
    if key:
        by_key = runs.filter(idempotency_key=key).first()
        if by_key is not None:
            return by_key
    return runs.filter(kind=kind, digest=digest).exclude(status=Import.Status.FAILED).first()


@service
def create_import(
    *,
    tenant: Tenant,
    actor: Actor,
    kind: str,
    file_version: FileVersion,
    idempotency_key: str = "",
) -> tuple[Import, bool]:
    """Stage one file for one kind of row. `(the run, whether this call made it)`.

    **Idempotent by the file's measured digest** (principle 16): the same bytes
    staged again for the same kind at the same organization return the run they
    already have — `(run, False)` — unless that run failed, in which case a new
    one is made. The digest is the files seam's measurement, never a client's
    claim. An `idempotency_key` the caller sent is honoured the same way.

    **Two permissions, both asked here**: `import.create`, and `<kind>.create` —
    the noun's own key — so a person who may not make the rows may not stage a
    file of them. The apply asks the second again, per row.
    """
    if actor.org is None:
        raise Invalid({"organization": ["This request resolved no acting organization."]})
    _importer_or_invalid(kind)
    require(actor, "import.create")
    # authz-key: the noun's own create key, `<kind>.create`, for the kind this
    # file makes — every kind an importer is declared for is one the vocabulary
    # derives, and importing a row needs what making it by hand needs.
    require(actor, f"{kind}.create")
    if not may_be_named(actor, file_version):
        raise NotFound()
    if file_version.status != file_version.Status.STORED or not file_version.sha256:
        raise Invalid({"file_id": ["This document has no stored version to import yet."]})

    digest = str(file_version.sha256)
    already = _live_run_for(
        tenant=tenant, actor=actor, kind=kind, digest=digest, key=idempotency_key
    )
    if already is not None:
        log.info("imports.import.replayed", import_id=str(already.pk), kind=kind)
        return already, False

    run = Import(
        tenant=tenant,
        organization=actor.org,
        kind=kind,
        file_version=file_version,
        file_name=str(file_version.file.filename)[:255],
        digest=digest,
        requested_by_id=actor.user.pk if actor.user is not None else None,
        idempotency_key=idempotency_key,
    )
    try:
        # A savepoint, so a concurrent stage of the same bytes that won the
        # partial unique constraint is read back rather than surfaced as a 500.
        with transaction.atomic():
            run.save()
    except IntegrityError:
        raced = _live_run_for(
            tenant=tenant, actor=actor, kind=kind, digest=digest, key=idempotency_key
        )
        if raced is None:
            raise
        return raced, False
    _publish(IMPORT_STAGED, tenant=tenant, import_=run, actor=actor)
    start_workflow_on_commit(
        workflow=CHECK_WORKFLOW,
        arg=CheckImport(import_id=str(run.pk)),
        tenant=tenant,
        user=actor.user,
        org=actor.org,
        # One run per phase per import: `<tenant>:imports:import:<pk>-check`.
        id=workflow_id(tenant=tenant, app="imports", noun="import", key=f"{run.pk}-check"),
    )
    return run, True


def _judged(importer: Importer, data: dict[str, Any]) -> tuple[Any, dict[str, Any]]:
    """`(the parsed row, {})` or `(None, the refusal body)` for one line's values."""
    try:
        return importer.row.model_validate(data), {}
    except ValidationError as exc:
        errors: dict[str, list[str]] = {}
        for error in exc.errors():
            field = ".".join(str(part) for part in error["loc"]) or NON_FIELD_KEY
            errors.setdefault(field, []).append(str(error["msg"]))
        return None, wire_refusal(Invalid(errors))


# door: the check activity's own step. The preview is what the
# dry run MEASURED; a door that could write one would let a caller claim a file
# says what it does not. Its one caller is `activities.check_import`.
@service
def record_import_preview(
    *, tenant: Tenant, actor: Actor, import_: Import, rows: Sequence[dict[str, Any]]
) -> Import:
    """Write the dry run: one `ImportRow` per line, the counts, `previewed`.

    **Nothing is written to the noun.** Each line is validated with the
    importer's row schema and looked up with its read-only `natural_key`, asked
    at the run's hat (the actor wears it) — where the apply will look: a line
    that finds its row would UPDATE it, one that finds none would CREATE, and one
    the schema refuses is `refused` with the schema's field errors.

    Idempotent: a run that is no longer `checking` (already previewed by an
    earlier attempt, or cancelled meanwhile) is returned unchanged.
    """
    if not may_be_named(actor, import_):
        raise NotFound()
    require(actor, "import.update", import_)
    run = (
        Import.objects.for_tenant(tenant)
        .visible_to(actor)
        .select_for_update(of=("self",))
        .get(pk=import_.pk)
    )
    if run.status != Import.Status.CHECKING:
        return run
    if len(rows) > MAX_IMPORT_ROWS:
        raise ImportInvalid({"file": [f"More than {MAX_IMPORT_ROWS} rows."]})
    importer = _importer_or_invalid(run.kind)

    built: list[ImportRow] = []
    counts = {"create": 0, "update": 0, "refused": 0}
    for number, data in enumerate(rows, start=1):
        parsed, refusal = _judged(importer, data)
        existing = None
        if parsed is None:
            preview = ImportRow.Preview.REFUSED
            counts["refused"] += 1
        else:
            existing = importer.natural_key(tenant=tenant, actor=actor, row=parsed)
            preview = ImportRow.Preview.CREATE if existing is None else ImportRow.Preview.UPDATE
            counts["create" if existing is None else "update"] += 1
        built.append(
            ImportRow(
                tenant=tenant,
                organization=run.organization,
                run=run,
                row_no=number,
                data=dict(data),
                outcome_preview=preview,
                refusal=refusal,
                object_id=getattr(existing, "pk", None),
            )
        )
    # rule-8: a WRITE, not a read — every row built above carries this run's
    # tenant and organization, taken off the locked run.
    ImportRow.objects.bulk_create(built, batch_size=WRITE_BATCH)
    run.status = Import.Status.PREVIEWED
    run.count_create = counts["create"]
    run.count_update = counts["update"]
    run.count_unchanged = 0
    run.count_refused = counts["refused"]
    run.save(
        update_fields=[
            "status",
            "count_create",
            "count_update",
            "count_unchanged",
            "count_refused",
            "updated_at",
        ]
    )
    _publish(IMPORT_PREVIEWED, tenant=tenant, import_=run, actor=actor)
    return run


@service
def apply_import(*, tenant: Tenant, actor: Actor, import_: Import) -> Import:
    """Apply a previewed run: `previewed → importing`, and start the apply.

    A repeat press on a run already importing or imported answers the run
    unchanged. A run still checking is a `conflict` (there is no preview to
    apply yet); a failed one answers the refusal it failed with when the file
    was refused whole (`import_invalid`), and `conflict` otherwise.
    """
    if not may_be_named(actor, import_):
        raise NotFound()
    require(actor, "import.apply", import_)
    # authz-key: the noun's own create key again at the press, as at stage.
    require(actor, f"{import_.kind}.create")
    run = (
        Import.objects.for_tenant(tenant)
        .visible_to(actor)
        .select_for_update(of=("self",))
        .get(pk=import_.pk)
    )
    if run.status in (Import.Status.IMPORTING, Import.Status.IMPORTED):
        return run
    if run.status == Import.Status.CHECKING:
        raise Conflict("This file is still being checked; apply it once the preview is ready.")
    if run.status == Import.Status.FAILED:
        if run.failure.get("code") == ImportInvalid.code:
            raise ImportInvalid(
                run.failure.get("errors") or {}, detail=str(run.failure.get("detail") or "")
            )
        raise Conflict("This import did not reach a preview; stage the file again.")
    run.status = Import.Status.IMPORTING
    run.applied_by_id = actor.user.pk if actor.user is not None else None
    run.save(update_fields=["status", "applied_by", "updated_at"])
    start_workflow_on_commit(
        workflow=APPLY_WORKFLOW,
        arg=ApplyImport(import_id=str(run.pk)),
        tenant=tenant,
        user=actor.user,
        org=run.organization,
        id=workflow_id(tenant=tenant, app="imports", noun="import", key=f"{run.pk}-apply"),
    )
    return run


# door: the apply activity's own step, one row at a time. A person's
# door onto it is `apply_import` (the press), which starts the run that calls
# this; a door straight onto one row would skip the preview the press is for.
@service
def apply_import_row(*, tenant: Tenant, actor: Actor, row: ImportRow) -> ImportRow:
    """Settle ONE row: write it through the importer, and its outcome, together.

    **One transaction for the noun write and the outcome** — the whole of the
    per-row idempotency. The row is locked and re-read; one already settled is
    returned as it is (a retried activity resumes past it). Otherwise it is
    re-authorized (`<kind>.create`, per row), re-validated (the world may have
    moved since the preview), and handed to the importer's `apply`, which calls
    the noun's OWN services. A refusal from any of the three is recorded on the
    row as the wire body and the row is `refused`; the noun's write, if it had
    started, rolls back with its savepoint and the rest of the file goes on.
    """
    if not may_be_named(actor, row):
        raise NotFound()
    locked = (
        ImportRow.objects.for_tenant(tenant)
        .visible_to(actor)
        .select_for_update(of=("self",))
        .select_related("run")
        .get(pk=row.pk)
    )
    if locked.outcome:
        return locked
    run = locked.run
    importer = _importer_or_invalid(run.kind)
    outcome = ImportRow.Outcome.REFUSED
    refusal: dict[str, Any] = {}
    object_id = None
    try:
        with transaction.atomic():
            # authz-key: the noun's own create key, asked per row at apply.
            require(actor, f"{run.kind}.create")
            parsed, refusal = _judged(importer, locked.data)
            if parsed is not None:
                written, said = importer.apply(tenant=tenant, actor=actor, row=parsed)
                outcome = ImportRow.Outcome(said)
                object_id = getattr(written, "pk", None)
    except DomainError as exc:
        refusal = wire_refusal(exc)
        outcome = ImportRow.Outcome.REFUSED
    locked.outcome = outcome
    locked.refusal = refusal
    if object_id is not None:
        locked.object_id = object_id
    locked.save(update_fields=["outcome", "refusal", "object_id", "updated_at"])
    return locked


# door: the apply activity's last step: the counts as they happened.
# A door that could close a run would mark a file imported that never was.
@service
def finish_import(*, tenant: Tenant, actor: Actor, import_: Import) -> Import:
    """Close an applied run: the counts as they happened, `imported`, the event.

    Idempotent: a run already `imported` is returned unchanged, and emits nothing.
    """
    if not may_be_named(actor, import_):
        raise NotFound()
    require(actor, "import.update", import_)
    run = (
        Import.objects.for_tenant(tenant)
        .visible_to(actor)
        .select_for_update(of=("self",))
        .get(pk=import_.pk)
    )
    if run.status == Import.Status.IMPORTED:
        return run
    tally = {outcome: 0 for outcome in ImportRow.Outcome.values}
    rows = (
        ImportRow.objects.for_tenant(tenant).visible_to(actor).filter(run=run).exclude(outcome="")
    )
    for outcome in rows.values_list("outcome", flat=True):
        tally[outcome] += 1
    run.status = Import.Status.IMPORTED
    run.count_create = tally[ImportRow.Outcome.CREATED]
    run.count_update = tally[ImportRow.Outcome.UPDATED]
    run.count_unchanged = tally[ImportRow.Outcome.UNCHANGED]
    run.count_refused = tally[ImportRow.Outcome.REFUSED]
    run.applied_at = now()
    run.save(
        update_fields=[
            "status",
            "count_create",
            "count_update",
            "count_unchanged",
            "count_refused",
            "applied_at",
            "updated_at",
        ]
    )
    _publish(IMPORT_APPLIED, tenant=tenant, import_=run, actor=actor)
    return run


# door: the workflow's way out once retries are spent, and the
# check's answer to a file refused whole. A person ends a run with `cancel_import`.
@service
def record_import_failure(
    *, tenant: Tenant, actor: Actor, import_: Import, failure: dict[str, Any]
) -> Import:
    """End a run as `failed`, with the refusal (or the complaint) that ended it.

    Idempotent: a run already failed or imported is returned unchanged.
    """
    if not may_be_named(actor, import_):
        raise NotFound()
    require(actor, "import.update", import_)
    run = (
        Import.objects.for_tenant(tenant)
        .visible_to(actor)
        .select_for_update(of=("self",))
        .get(pk=import_.pk)
    )
    if run.status in (Import.Status.FAILED, Import.Status.IMPORTED):
        return run
    run.status = Import.Status.FAILED
    run.failure = failure
    run.save(update_fields=["status", "failure", "updated_at"])
    _publish(IMPORT_FAILED, tenant=tenant, import_=run, actor=actor)
    return run


@service
def cancel_import(*, tenant: Tenant, actor: Actor, import_: Import) -> Import:
    """Stop a run before it applies: `checking` or `previewed` → `failed`.

    A run already failed is returned unchanged; one importing or imported is a
    `conflict` — rows may already be written, and a cancel that pretended
    otherwise would be a lie.
    """
    if not may_be_named(actor, import_):
        raise NotFound()
    require(actor, "import.cancel", import_)
    run = (
        Import.objects.for_tenant(tenant)
        .visible_to(actor)
        .select_for_update(of=("self",))
        .get(pk=import_.pk)
    )
    if run.status == Import.Status.FAILED:
        return run
    if run.status in (Import.Status.IMPORTING, Import.Status.IMPORTED):
        raise Conflict("This import is already being applied; it can no longer be cancelled.")
    run.status = Import.Status.FAILED
    run.cancelled_at = now()
    run.save(update_fields=["status", "cancelled_at", "updated_at"])
    _publish(IMPORT_FAILED, tenant=tenant, import_=run, actor=actor)
    return run


# door: deployment housekeeping, started by the declared schedule
# (`activities.PURGE_IMPORTS`) as the system; there is no caller to give a door.
@service
def purge_imports(*, before: datetime, tenant: Tenant | None, actor: Actor) -> PurgeOutcome:
    """Delete settled runs last changed before `before`; their rows go with them.

    **`tenant` is declared, must be `None`, and is refused otherwise** — the
    shape `apps.exports.services.purge_exports` argues in full: the parameter is
    what makes the audit row a platform action, and a caller who passed one
    must not get a deployment-wide sweep in answer. A run still `checking` or
    `importing` is never swept, however old: a worker is (or will be) on it.

    `actor` is the system the schedule runs as, taken so the audit row names
    who acted (house rule 49).

    Idempotent by construction: it deletes by age.

    # authz: deployment housekeeping, run by a schedule as the system. It names
    # no tenant and returns one count.
    """
    if tenant is not None:
        raise Invalid(
            {
                "tenant": [
                    "This sweep is deployment-wide and cannot be narrowed to one tenant; "
                    "its one legal value is None. Nothing was deleted."
                ]
            }
        )
    settled = (Import.Status.PREVIEWED, Import.Status.IMPORTED, Import.Status.FAILED)
    # rule-8: the population is every tenant's expired runs at once, which is
    # what a retention sweep is; rows are deleted, never returned, and one
    # integer leaves this function.
    expired = Import.objects.filter(updated_at__lt=before, status__in=settled)
    runs = expired.count()
    with transaction.atomic():
        # rule-8: the same tenant-crossing sweep; CASCADE takes the rows.
        expired.delete()
    log.info("imports.purge.done", imports=runs)
    return PurgeOutcome(imports=runs)
