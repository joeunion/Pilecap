"""The shapes that cross this app's workflow boundary. Standard library only.

Serialised into Temporal's history and replayed out of it, so nothing here may be
a model or reach the ORM (house rule 9). Ids are strings, parsed once, in the
activity, at the edge of the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

#: The workflow type names, in one place below both `workflows.py` and
#: `activities.py` (which may not import each other) and `services.py`.
CHECK_WORKFLOW = "ValidateImportWorkflow"
APPLY_WORKFLOW = "ApplyImportWorkflow"
PURGE_WORKFLOW = "PurgeImportsWorkflow"


@dataclass
class RunFinished:
    """What `mark_run_finished` is told; matches `apps.workflows.types.MarkRunFinished`."""

    workflow_id: str
    status: str
    error: str = ""


@dataclass
class CheckImport:
    """What the check workflow is started with. The tenant and hat ride the headers."""

    import_id: str


@dataclass
class ApplyImport:
    """What the apply workflow is started with."""

    import_id: str


@dataclass
class ImportSettled:
    """What an activity reports: the run's status when it returned, and its counts."""

    import_id: str
    status: str
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class ImportFailed:
    """Which run failed, and what actually broke (walked out of the cause chain)."""

    import_id: str
    reason: str


@dataclass
class PurgeImports:
    """The retention window, carried on the schedule's action."""

    retention_days: int


@dataclass
class PurgeOutcome:
    """What one sweep took. Filed on the swept model's label, as a population."""

    audit_object: ClassVar[tuple[str, None]] = ("djb_imports.Import", None)

    imports: int


@dataclass(frozen=True)
class RowPreview:
    """One line as the dry run judged it. Crosses no workflow boundary; the
    activity hands a list of these to the service that writes them."""

    row_no: int
    data: dict[str, Any]
    outcome_preview: str
    refusal: dict[str, Any] = field(default_factory=dict)
    object_id: str | None = None
