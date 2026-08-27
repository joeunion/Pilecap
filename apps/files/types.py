"""The shapes that cross this app's workflow boundary. Standard library only.

Everything here is serialised into Temporal's history and replayed out of it,
possibly years later by a worker running code nobody has looked at since. A
workflow argument that was a `FileVersion` could not be replayed at all: the row
may have changed, or gone.

The ids are strings rather than `UUID`s for the same reason `apps/exports`'
records: what comes back out of history is JSON, and a string parsed once, in
the activity, at the edge of the database, is one conversion in one place.

**The tenant and the acting hat are deliberately NOT here.** They ride on the
workflow's Temporal headers (`apps.workflows.context`) and are restored inside
the activity, so nobody can reach into another tenant — or another branch — by
putting a different id in a payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

#: The workflow type name, in one place. `workflows.py` registers under it and
#: `services.py` starts it by it — two modules that may not import each other
#: (a workflow module imports only its own `types.py`), so the string lives
#: below both.
FINALIZE_WORKFLOW = "FinalizeUpload"

#: The sweep's workflow type name, on the same reasoning as `FINALIZE_WORKFLOW`
#: above: `workflows.py` registers under it and `activities.py`'s
#: `ScheduleDeclaration` names it in the action it starts, and those two modules
#: may not import each other.
SWEEP_WORKFLOW = "SweepPendingUploads"


@dataclass
class RunFinished:
    """What `mark_run_finished` is told when this app's workflow ends.

    The activity belongs to `apps.workflows` and is invoked **by name**, which is
    how every activity is invoked (house rule 9) — so the shape crosses the
    boundary and the class does not. Keep the three fields matching
    `apps.workflows.types.MarkRunFinished`; the worker deserialises into that.
    """

    workflow_id: str
    status: str
    error: str = ""


@dataclass
class FinalizeUpload:
    """Which version to go and look at. **One id, and it is the whole payload.**

    Not the key: the key is on the row, the row is the only legitimate way to
    learn it, and a key on a workflow argument would be a second place the
    address of somebody's bytes lives — one that survives in Temporal's history
    long after the row that owns it.
    """

    version_id: str


@dataclass
class VerifiedObject:
    """What the store actually holds at that version's key, measured by us.

    `sha256` and `size_bytes` come from one streamed pass over the object
    (`storage.sha256_of`), so they cannot disagree with each other the way a HEAD
    and a later GET could. Nothing an uploader declared appears here — that is
    the entire point of the type: what crosses this boundary is evidence, and a
    number a client sent is not evidence.

    `head_size_bytes` is the store's own count from the cheap HEAD that ran
    first. It is carried so the activity's own two answers are both in the
    history: if a store ever reports a length it did not serve, the run that saw
    it says so rather than quietly preferring one.
    """

    sha256: str
    size_bytes: int
    head_size_bytes: int


@dataclass
class StoreMeasurement:
    """What the finalize workflow hands to the service that writes it down.

    The version id travels again rather than the workflow carrying state between
    activities: an activity's result is history, and the second activity has to
    be able to run on a different worker, in a different process, after a deploy,
    with nothing but its own argument.

    `sha256` and `size_bytes` are the measured pair from `VerifiedObject`, carried
    forward unchanged. They are not re-derived in the second activity, because
    re-reading the object there would be a second measurement — and two
    measurements are two chances to disagree about one immutable thing.
    """

    version_id: str
    sha256: str
    size_bytes: int


@dataclass
class SweepPendingUploads:
    """How old an unfinished upload has to be before the sweep takes it.

    **The window rides on the workflow argument rather than being read inside
    the activity**, which is the shape `apps/exports`' and `apps/connections`'
    sweeps both take: an operator can read the number off the schedule in the
    Temporal UI instead of out of the source, and both machinery lifetime
    classes read the same value out of the same declaration.

    Hours rather than days because this window is short — an upload URL is good
    for fifteen minutes, so a version nobody finalized within a day is one
    nobody is going to.
    """

    ttl_hours: int


@dataclass
class SweepOutcome:
    """What one sweep did, in the two numbers that are worth a log line.

    `versions` is how many abandoned `PENDING` rows went; `documents` is how many
    documents were left with nothing at all behind them and were archived for it.
    The second is never larger than the first and is usually much smaller — a
    replace that was abandoned takes a version and leaves a perfectly good
    document.
    """

    #: The population this sweep files under (ADR core-22): the swept
    #: model's label, a NULL id, and the counts above. A lazy model reference
    #: because this module is stdlib-only; the census test resolves it.
    audit_object: ClassVar[tuple[str, None]] = ("files.FileVersion", None)

    versions: int
    documents: int
