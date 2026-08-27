"""The shapes that cross the workflow boundary.

Workflow arguments and activity arguments are serialised and replayed, so they
are plain dataclasses in a module that imports nothing but the standard library.
A workflow that took a model instance would be a workflow that could not be
replayed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MarkRunFinished:
    """Ask the activity to close out a run's visibility row."""

    workflow_id: str
    status: str
    error: str = ""


@dataclass
class SendEmail:
    """One email, on its way to `send_email`.

    Everything here is replayed from Temporal's history, so it is all plain
    JSON-able data — a rendered template name and its context, never a model
    instance and never a queryset. **Never a credential either**: a token in
    this dataclass is a token in the workflow history for as long as retention
    says, which is why the invitation email carries none.

    The tenant is not a field: it rides on the workflow's headers and is
    restored in the activity by `workflow_context()`, so nothing in a payload
    can name somebody else's tenant.
    """

    to: list[str]
    subject: str
    template: str
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class EchoOutput:
    """What `EchoWorkflow` returns: the message, and the tenant it ran for.

    The tenant comes back from the activity rather than from the workflow, which
    is the point of the test that drives it: it proves the tenant survived the
    hop from the client, through the workflow, into the activity.
    """

    message: str
    tenant_slug: str


@dataclass
class MoveOrganization:
    """Which node is moving, and where to.

    Two primary keys and nothing else: the rows are read fresh in the activity,
    because a move that Temporal replays a week after it was started must act on
    the tree as it is now, not on a snapshot of the tree as it was. The tenant
    is not a field — it rides on the workflow's headers, so a payload cannot
    name somebody else's tenant.
    """

    organization_id: str
    new_parent_id: str


@dataclass
class ReconcileRuns:
    """How old a `RUNNING` row with no execution behind it must be to be swept.

    Seconds rather than a `timedelta`, for the reason every other schedule
    argument in this repository is: it crosses a Temporal history and is read
    back out of one years later, where an integer means the same thing in every
    language that will ever deserialise it.

    The threshold is not a tuning knob so much as a definition of "dead": a row
    is written inside the caller's transaction and its execution is started on
    commit, so the gap between them is milliseconds in the ordinary case. Only
    a process that died in that gap leaves a row this sweep can see, and
    `RECONCILE_AFTER` is how long the sweep waits before believing it.
    """

    after_seconds: int


@dataclass
class PurgeFinishedRuns:
    """How far back the ledger's housekeeping may reach.

    Seconds rather than a `timedelta`, and an integer rather than a date, for
    the reason every other schedule argument in this repository is one: it
    crosses a Temporal history and is read back out of it years later, where an
    integer means the same thing in every language that will ever deserialise
    it. A *date* baked into the schedule's action would freeze at the moment
    the schedule was created and the window would silently stop moving.

    It rides on the schedule's action so an operator can read the retention
    window off the schedule in the Temporal UI rather than out of the source —
    An already-applied finding, rather than rediscovered.
    """

    retention_seconds: int
