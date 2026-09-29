"""Where this app touches the world: the file's bytes, the rows, the sweep.

Everything non-deterministic is here rather than in `workflows.py` (house rule
9), and every write goes through a service (house rule 10). **Plain `def`**, like
every activity in this repository, closing stale connections at both ends.

**The bytes come through the files seam's server-side stream**,
`files.storage.iter_object` — the one module that reaches the object store (house
rule 48) streams them to this activity's parser, and no door ever sees them.
The parser is stdlib `csv` over an incremental UTF-8 decoder, so a file is read
once, in chunks, and never whole into one string.

Four activities:

* `check_import` — the dry run: read, parse, judge, write the preview (no noun
  write), or refuse the whole file (`import_invalid`) and say so on the run;
* `apply_import_rows` — the apply, in chunks, **heartbeating per row**: a worker
  killed mid-apply stops heartbeating, Temporal hands the activity to another
  worker within the heartbeat timeout, and the retry starts at the first row
  with no outcome — each row was settled in one transaction with its outcome,
  so nothing is applied twice;
* `record_import_failure` — what the workflow calls once retries are spent;
* `purge_expired_imports` — the retention sweep the schedule starts.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable, Iterable, Iterator
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

from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import DomainError, wire_refusal
from apps.core.log import get_logger
from apps.core.schedules import ScheduleDeclaration
from apps.core.time import now
from apps.djb_imports import services
from apps.djb_imports.models import IMPORT_RETENTION_DAYS, MAX_IMPORT_ROWS, Import
from apps.djb_imports.selectors import get_import, get_importer, list_unsettled_rows
from apps.djb_imports.services import ImportInvalid
from apps.djb_imports.types import (
    PURGE_WORKFLOW,
    ApplyImport,
    CheckImport,
    ImportFailed,
    ImportSettled,
    PurgeImports,
    PurgeOutcome,
)
from apps.files import storage as files_storage
from apps.workflows.context import workflow_context

log = get_logger("apps.djb_imports.activities")

#: How many rows the apply reads at a time. Each row is still its own
#: transaction; the chunk bounds how much one read holds in memory.
APPLY_CHUNK = 200

#: What a CSV file may say it is. A spreadsheet's own format is not one of them
#: (principle 12: reading XLSX is a new dependency a product proposes).
CSV_CONTENT_TYPES = frozenset(
    {"text/csv", "application/csv", "text/plain", "application/vnd.ms-excel"}
)


# --- reading the file ------------------------------------------------------------


class _Chunks(io.RawIOBase):
    """A readable stream over the seam's chunk iterator, so `io` does the decoding."""

    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = iter(chunks)
        self._left = b""

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        while not self._left:
            try:
                self._left = next(self._chunks)
            except StopIteration:
                return 0
        size = min(len(buffer), len(self._left))
        buffer[:size] = self._left[:size]
        self._left = self._left[size:]
        return size


def _lines(chunks: Iterable[bytes]) -> Iterator[str]:
    """The file as text lines, decoded as it streams, line endings untouched.

    `utf-8-sig` drops the byte-order mark a spreadsheet's "save as CSV" writes;
    `newline=""` is what `csv` asks for, so a quoted field spanning a line reads
    as one field. A byte that is not UTF-8, or a NUL, refuses the whole file.
    """
    text = io.TextIOWrapper(
        io.BufferedReader(_Chunks(chunks)), encoding="utf-8-sig", errors="strict", newline=""
    )
    try:
        for line in text:
            if "\x00" in line:
                raise ImportInvalid({"file": ["The file contains a NUL byte; it is not text."]})
            yield line
    except UnicodeDecodeError:
        raise ImportInvalid({"file": ["The file is not UTF-8 text."]}) from None


def _header(cells: list[str], row_type: Any) -> list[str]:
    """The header, checked against the row schema: known columns, required ones present."""
    fields = row_type.model_fields
    header = [cell.strip() for cell in cells]
    errors: dict[str, list[str]] = {}
    unknown = [name for name in header if name not in fields]
    if unknown:
        errors["header"] = [f"Unknown column(s): {', '.join(unknown)}."]
    doubled = sorted({name for name in header if header.count(name) > 1})
    if doubled:
        errors.setdefault("header", []).append(f"Repeated column(s): {', '.join(doubled)}.")
    missing = [name for name, info in fields.items() if info.is_required() and name not in header]
    if missing:
        errors.setdefault("header", []).append(f"Missing column(s): {', '.join(missing)}.")
    if errors:
        errors["columns"] = [", ".join(fields)]
        raise ImportInvalid(errors)
    return header


def _read_rows(run: Import) -> list[dict[str, Any]]:
    """Every data row of the run's file, as `{column: value}`. **Refuses the file whole.**"""
    version = run.file_version
    if version is None:
        raise ImportInvalid({"file": ["The document this import reads is gone."]})
    content_type = str(version.content_type).split(";")[0].strip().lower()
    if content_type not in CSV_CONTENT_TYPES:
        raise ImportInvalid({"file": [f"A {content_type or 'typeless'} file is not CSV."]})
    importer = get_importer(run.kind)
    if importer is None:
        raise ImportInvalid({"kind": [f"No importer is declared for {run.kind!r}."]})
    # The files seam's server-side stream (ADR files-2, amended): the one module
    # that reads an object's bytes hands them to this parser and to no door.
    chunks = files_storage.iter_object(tenant=run.tenant, key=str(version.key))
    reader = csv.reader(_lines(chunks))
    rows: list[dict[str, Any]] = []
    header: list[str] | None = None
    try:
        for cells in reader:
            if not any(cell.strip() for cell in cells):
                continue
            if header is None:
                header = _header(cells, importer.row)
                continue
            if len(rows) >= MAX_IMPORT_ROWS:
                raise ImportInvalid(
                    {"file": [f"The file has more than {MAX_IMPORT_ROWS} rows; split it."]}
                )
            data: dict[str, Any] = dict(zip(header, cells, strict=False))
            if len(cells) > len(header):
                data["_extra"] = cells[len(header) :]
            rows.append(data)
    except csv.Error as exc:
        raise ImportInvalid({"file": [f"The file is not valid CSV: {exc}."]}) from None
    if header is None:
        raise ImportInvalid({"header": ["The file has no header row."]})
    return rows


# --- the actors --------------------------------------------------------------------


def _actor_for(run: Import) -> Actor:
    """The system, wearing the run's hat. **For this app's own writes.**"""
    return system_actor(run.tenant, run.organization)


def _person_for(run: Import) -> Actor:
    """The person who pressed apply, restored off the workflow headers.

    **The noun writes are theirs**, authorized as them: `kind="agent"` because
    nobody clicked each row, and not `"system"`, because a system actor passes
    every permission and the per-row `<kind>.create` would ask nobody.
    """
    _tenant, user_id, _org = workflow_context()
    if user_id is None:
        raise RuntimeError(
            f"Import {run.pk} is being applied by a run that carries no acting user; an "
            "apply writes rows as the person who pressed it, so it is refused rather "
            "than written as nobody."
        )
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(pk=user_id)
    return actor_for(user=user, tenant=run.tenant, kind="agent", org=run.organization)


def _settled(run: Import) -> ImportSettled:
    return ImportSettled(import_id=str(run.pk), status=str(run.status), counts=run.counts)


def _run_of(import_id: str) -> Import:
    tenant, _user_id, org = workflow_context()
    return get_import(
        tenant=tenant, import_id=UUID(import_id), org=org, actor=system_actor(tenant, org)
    )


# --- the activities --------------------------------------------------------------------


@activity.defn(name="check_import", no_thread_cancel_exception=True)
def check_import(payload: CheckImport) -> ImportSettled:
    """The dry run. Read the file, judge every row, write the preview — or refuse it.

    A file refused whole is a domain answer, not a crash: the run is marked
    `failed` with the `import_invalid` body and the activity RETURNS, so Temporal
    does not retry a file that will be just as wrong the next time. Idempotent:
    a run no longer `checking` is reported as it is.
    """
    close_old_connections()
    try:
        run = _run_of(payload.import_id)
        if run.status != Import.Status.CHECKING:
            return _settled(run)
        actor = _actor_for(run)
        try:
            rows = _read_rows(run)
            run = services.record_import_preview(
                tenant=run.tenant, actor=actor, import_=run, rows=rows
            )
        except DomainError as refused:
            run = services.record_import_failure(
                tenant=run.tenant, actor=actor, import_=run, failure=wire_refusal(refused)
            )
        log.info("djb_imports.import.checked", import_id=str(run.pk), status=str(run.status))
        return _settled(run)
    finally:
        close_old_connections()


@activity.defn(name="apply_import_rows", no_thread_cancel_exception=True)
def apply_import_rows(payload: ApplyImport) -> ImportSettled:
    """Apply every unsettled row, chunk by chunk, heartbeating per row; then close the run.

    **Resumable**: it reads the rows with no outcome, so a retry — after a
    worker was killed, after a deploy — starts where the last attempt stopped.
    Each row settles in its own transaction with its outcome
    (`services.apply_import_row`), so a row is never applied twice.
    """
    close_old_connections()
    try:
        run = _run_of(payload.import_id)
        if run.status != Import.Status.IMPORTING:
            return _settled(run)
        system = _actor_for(run)
        person = _person_for(run)
        applied = 0
        while batch := list_unsettled_rows(
            tenant=run.tenant, import_=run, actor=system, limit=APPLY_CHUNK
        ):
            for row in batch:
                services.apply_import_row(tenant=run.tenant, actor=person, row=row)
                applied += 1
                activity.heartbeat(row.row_no)
        run = services.finish_import(tenant=run.tenant, actor=system, import_=run)
        log.info("djb_imports.import.applied", import_id=str(run.pk), rows=applied)
        return _settled(run)
    finally:
        close_old_connections()


@activity.defn(name="record_import_failure", no_thread_cancel_exception=True)
def record_import_failure(payload: ImportFailed) -> str:
    """Mark a run failed with the reason the workflow walked out of the cause chain."""
    close_old_connections()
    try:
        run = _run_of(payload.import_id)
        failed = services.record_import_failure(
            tenant=run.tenant,
            actor=_actor_for(run),
            import_=run,
            failure={"detail": payload.reason[:2000]},
        )
        return str(failed.pk)
    finally:
        close_old_connections()


@activity.defn(name="purge_expired_imports", no_thread_cancel_exception=True)
def purge_expired_imports(window: PurgeImports) -> PurgeOutcome:
    """Take the settled runs past their retention, through the service."""
    close_old_connections()
    try:
        return services.purge_imports(
            before=now() - timedelta(days=window.retention_days),
            tenant=None,
            actor=system_actor(),
        )
    finally:
        close_old_connections()


# --- the schedule ----------------------------------------------------------------------

#: Daily; the window is thirty days wide.
PURGE_EVERY = timedelta(hours=24)

#: Namespaced by task queue (ADR events-2): a schedule id is global to the
#: Temporal namespace.
#:
#: NOT re-spelled with the `djb_` label, on purpose. A schedule id is state a
#: running deployment already holds: the reconcile finds the schedule by this
#: id and updates it in place, so a new id would leave the old schedule
#: running beside the new one, starting the sweep twice a day for good.
#: `legacy_ids` cannot retire it either — they are constants, and this id
#: carries the task queue. The id is a Temporal name, not an app label.
PURGE_SCHEDULE_PREFIX = "imports-purge-expired"
PURGE_WORKFLOW_PREFIX = "platform:djb_imports:purge"


def purge_schedule_id(task_queue: str) -> str:
    """The schedule id for one deployment's import sweep."""
    return f"{PURGE_SCHEDULE_PREFIX}:{task_queue}"


def purge_workflow_id(task_queue: str) -> str:
    """The id prefix of the runs the schedule starts (the server appends the time)."""
    return f"{PURGE_WORKFLOW_PREFIX}:{task_queue}"


def purge_imports_schedule(task_queue: str) -> Schedule:
    """The daily sweep, as a value a test can read; the window rides the action."""
    return Schedule(
        action=ScheduleActionStartWorkflow(
            PURGE_WORKFLOW,
            PurgeImports(retention_days=IMPORT_RETENTION_DAYS),
            id=purge_workflow_id(task_queue=task_queue),
            task_queue=task_queue,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=PURGE_EVERY)]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )


#: The far end of `Import.lifecycle` (house rule 31): `purged_by` → the service
#: → `purge_expired_imports` → `PurgeImportsWorkflow` → this declaration.
PURGE_IMPORTS = ScheduleDeclaration(
    name="djb_imports.purge-expired",
    schedule_id=purge_schedule_id,
    schedule=purge_imports_schedule,
    log_prefix="djb_imports",
)


ACTIVITIES: list[Callable[..., Any]] = [
    check_import,
    apply_import_rows,
    record_import_failure,
    purge_expired_imports,
]

SCHEDULES: list[ScheduleDeclaration] = [PURGE_IMPORTS]
