"""The shapes that cross this app's workflow boundary. Standard library only (rule 9)."""

from __future__ import annotations

from dataclasses import dataclass, field

#: The workflow type names, in one place below both `workflows.py` and
#: `activities.py` (which may not import each other) and `services.py`.
CHECK_WORKFLOW = "ValidateImportWorkflow"
APPLY_WORKFLOW = "ApplyImportWorkflow"
PURGE_WORKFLOW = "PurgeImportsWorkflow"


@dataclass
class CheckImport:
    """What the check workflow is started with; the tenant and hat ride the headers.

    `retry_floor` is `apps.core.retry.retry_floor_seconds()`, read on the Django side.
    """

    import_id: str
    retry_floor: float | None = None


@dataclass
class ApplyImport:
    """What the apply workflow is started with; `retry_floor` as `CheckImport`'s."""

    import_id: str
    retry_floor: float | None = None


@dataclass
class ImportSettled:
    """What an activity reports: the run's status when it returned, and its counts."""

    import_id: str
    status: str
    counts: dict[str, int] = field(default_factory=dict)


@dataclass
class ImportFailed:
    """Which run ended, what broke (`determinism.reason_of`), and whether a cancel ended it."""

    import_id: str
    reason: str
    cancelled: bool = False


@dataclass
class PurgeImports:
    """The retention window, carried on the schedule's action."""

    retention_days: int


@dataclass
class PurgeOutcome:
    """What one sweep took, across the workflow boundary; the service's audit answer is `Swept`."""

    imports: int
