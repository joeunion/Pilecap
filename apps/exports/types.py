"""The shapes that cross this app's workflow boundary.

Plain dataclasses in a module that imports nothing but the standard library,
because everything here is serialised into Temporal's history and replayed out
of it — possibly years later, by a worker running code nobody has looked at
since. A workflow argument that was an `Export` could not be replayed at all:
the row may have changed, or gone.

The ids are strings rather than `UUID`s for the same reason: what comes back out
of history is JSON, and a string parsed once, in the activity, at the edge of the
database, is one conversion in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

#: The workflow type name, in one place. `workflows.py` registers under it and
#: `activities.py` names it in the schedule's action — two modules that may not
#: import each other (the workflow module imports only its own `types.py`), so
#: the string lives below both.
EXPORT_WORKFLOW = "ExportTenantDataWorkflow"
PURGE_WORKFLOW = "PurgeExportsWorkflow"


@dataclass
class RunFinished:
    """What `mark_run_finished` is told when this app's workflow ends.

    The activity belongs to `apps.workflows` and is invoked **by name**, which
    is how every activity is invoked (house rule 9) — so the shape crosses the
    boundary and the class does not. Keep the three fields matching
    `apps.workflows.types.MarkRunFinished`; the worker deserialises into that.
    """

    workflow_id: str
    status: str
    error: str = ""


@dataclass
class BuildExport:
    """What the export workflow is started with, and what its activity is told.

    The tenant is deliberately not here: it rides on the workflow's Temporal
    headers (`apps.workflows.context`) and is restored inside the activity, so
    no caller can reach into somebody else's tenant by putting the wrong id in a
    payload. The acting **hat** rides the same way, which is what makes a branch
    manager's export a branch's export in an activity that runs an hour later.
    """

    export_id: str


@dataclass
class ExportBuilt:
    """What the build activity reports, and what the run returns.

    `rows` is the total across every model in the archive — one number, so a
    Temporal history says whether this run moved anything without anybody
    opening the manifest.
    """

    export_id: str
    artifact_key: str
    rows: int


@dataclass
class ExportFailed:
    """What the failure activity is told: which export, and what actually broke.

    `reason` is the activity's own complaint, walked a bounded number of links
    out of Temporal's cause chain by the workflow — `ActivityError.__str__()` is
    "Activity task failed", which is true and useless to whoever reads the row
    six weeks later.
    """

    export_id: str
    reason: str


@dataclass
class PurgeExports:
    """The retention window, carried on the SCHEDULE rather than read inside.

    `apps.connections`' sweep puts its window here for the same reason: an
    operator can then read the number off the schedule in the Temporal UI
    instead of out of the source, and both lifetime classes (a durable Temporal
    Schedule, or a timer on a live worker — ADR platform-lifecycle-1) read the
    same value out of the same declaration.
    """

    retention_days: int


@dataclass
class PurgeOutcome:
    """What one sweep took: rows deleted, and artifacts deleted from storage.

    **`audit_object` is the population this sweep files under** (ADR core-22,
    L6): the swept model's label with a NULL id, because a sweep acts on a
    population and not on an object. The label is a lazy model reference — the
    `apps.Model` string Django's own `ForeignKey("accounts.ApiToken")` uses —
    because this module is stdlib-only by contract and may not import the ORM;
    the census test resolves it through `django.apps` so a rename fails by name.

    Two numbers and not one, because they can legitimately differ — a pending or
    failed export has a row and no artifact — and a single count would hide the
    case that matters: rows going while objects stay is a bucket filling with
    archives nothing points at any more.
    """

    #: See the docstring: the population, not an object. Read by
    #: `core.service._object_of`, which refuses a blank label rather than
    #: filing a row whose `object_type` names nothing.
    audit_object: ClassVar[tuple[str, None]] = ("exports.Export", None)

    exports: int
    artifacts: int
