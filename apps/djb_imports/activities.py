"""Where this app touches the world: the file's bytes, the rows, the sweep (rules 9, 10).

The bytes stream through `files.storage.iter_object` (rule 48) into `csv`, never whole into memory.
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
from temporalio.exceptions import CancelledError

from apps.core.context import current_actor
from apps.core.exceptions import DomainError, RunFailed, remedies_for_noun, wire_refusal
from apps.core.log import get_logger
from apps.core.schedules import ScheduleDeclaration, daily_purge
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


def _settled(run: Import) -> ImportSettled:
    return ImportSettled(import_id=str(run.pk), status=str(run.status), counts=run.counts)


def _run_of(import_id: str) -> Import:
    actor = current_actor()
    return get_import(tenant=actor.tenant, import_id=UUID(import_id), org=actor.org, actor=actor)


# --- the activities --------------------------------------------------------------------


@activity.defn(name="check_import", no_thread_cancel_exception=True)
def check_import(payload: CheckImport) -> ImportSettled:
    """The dry run: judge every row and write the preview, or fail the run with the refusal.

    A file refused whole RETURNS rather than raising, so Temporal does not retry it.
    """
    close_old_connections()
    try:
        run = _run_of(payload.import_id)
        if run.status != Import.Status.CHECKING:
            return _settled(run)
        actor = current_actor()
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
    """Apply every unsettled row, heartbeating per row, then close the run; resumable, cancellable.

    A retry starts at the first row with no outcome; each row settles in one transaction with it.
    A cancel is read after each row's heartbeat and acknowledged by raising `CancelledError`.
    """
    close_old_connections()
    try:
        run = _run_of(payload.import_id)
        if run.status != Import.Status.IMPORTING:
            return _settled(run)
        system = current_actor()
        person = current_actor(kind="agent")
        applied = 0
        while batch := list_unsettled_rows(
            tenant=run.tenant, import_=run, actor=system, limit=APPLY_CHUNK
        ):
            for row in batch:
                services.apply_import_row(tenant=run.tenant, actor=person, row=row)
                applied += 1
                activity.heartbeat(row.row_no)
                if activity.is_cancelled():
                    log.info(
                        "djb_imports.import.apply_cancelled",
                        import_id=str(run.pk),
                        rows=applied,
                        last_row=row.row_no,
                    )
                    raise CancelledError(f"cancelled after row {row.row_no}")
        run = services.finish_import(tenant=run.tenant, actor=system, import_=run)
        log.info("djb_imports.import.applied", import_id=str(run.pk), rows=applied)
        return _settled(run)
    finally:
        close_old_connections()


def _run_failed(reason: str) -> RunFailed:
    """`run_failed` for this run, its remedies' `<noun>` slot filled with the import's kind."""
    return RunFailed(reason[:2000], remedies=remedies_for_noun(RunFailed.code, Import.authz_kind))


@activity.defn(name="record_import_failure", no_thread_cancel_exception=True)
def record_import_failure(payload: ImportFailed) -> str:
    """Close a run `failed`: `run_failed` naming what broke, or no refusal when a cancel did."""
    close_old_connections()
    try:
        run = _run_of(payload.import_id)
        failed = services.record_import_failure(
            tenant=run.tenant,
            actor=current_actor(),
            import_=run,
            failure={} if payload.cancelled else wire_refusal(_run_failed(payload.reason)),
            cancelled=payload.cancelled,
        )
        return str(failed.pk)
    finally:
        close_old_connections()


@activity.defn(name="purge_expired_imports", no_thread_cancel_exception=True)
def purge_expired_imports(window: PurgeImports) -> PurgeOutcome:
    """Take the settled runs past their retention, through the service."""
    close_old_connections()
    try:
        swept = services.purge_imports(
            before=now() - timedelta(days=window.retention_days), tenant=None
        )
        return PurgeOutcome(imports=swept.count)
    finally:
        close_old_connections()


# --- the schedule ----------------------------------------------------------------------

#: The far end of `Import.lifecycle` (rule 31); `platform:djb_imports:purge:<queue>`.
PURGE_IMPORTS = daily_purge(
    app="djb_imports",
    noun="purge",
    workflow=PURGE_WORKFLOW,
    arg=PurgeImports(retention_days=IMPORT_RETENTION_DAYS),
    name="djb_imports.purge-expired",
    log_prefix="djb_imports",
)


ACTIVITIES: list[Callable[..., Any]] = [
    check_import,
    apply_import_rows,
    record_import_failure,
    purge_expired_imports,
]

SCHEDULES: list[ScheduleDeclaration] = [PURGE_IMPORTS]
