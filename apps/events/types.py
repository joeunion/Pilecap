"""The shapes that cross the workflow boundary. Standard library only.

Every one of these is serialised into Temporal's history and replayed from it,
possibly years later, so they are plain dataclasses of plain data: ids as
strings, never model instances, never a queryset, and never a secret — an
endpoint's signing key travels nowhere near this module, because a credential in
a workflow argument is a credential in the history for as long as retention
says. The activity looks the endpoint up by id and reads the secret from the
database, where it belongs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DispatchEvent:
    """Ask the dispatch workflow to fan one event out, with the deployment's retry floor."""

    event_id: str
    #: The first-retry interval in seconds, read on the Django side; `None` is the SDK's default.
    retry_floor: float | None = None


@dataclass
class DeliveryTarget:
    """One endpoint that has asked for this event."""

    endpoint_id: str
    url: str


@dataclass
class LoadedTargets:
    """What the load activity found, and whether there is anything to do.

    A dataclass rather than a bare list because a workflow's activity results
    are typed by their `result_type`, and a container is the shape that survives
    the round trip without a generic annotation in the workflow.
    """

    event_name: str
    targets: list[DeliveryTarget] = field(default_factory=list)


@dataclass
class DeliverWebhook:
    """One signed POST, to one endpoint, of one event."""

    event_id: str
    endpoint_id: str


@dataclass
class DeliveryOutcome:
    """How one delivery attempt went."""

    delivery_id: str
    status: str
    code: int | None = None


@dataclass
class DeadLetter:
    """Park a delivery that spent every retry."""

    event_id: str
    endpoint_id: str
    error: str = ""


@dataclass
class CloseOutbox:
    """Move the outbox row to its terminal state."""

    event_id: str
    status: str
    error: str = ""


@dataclass
class PushRealtime:
    """Hand the event to the socket bridge, if this deployment has one."""

    event_id: str


@dataclass
class IndexSearch:
    """Hand the event to the search indexer, if this deployment has one.

    The same one-field shape `PushRealtime` carries, and for the same reason:
    the activity re-reads the event row itself rather than being handed a body
    somebody could have assembled wrongly. Two dataclasses rather than one
    shared `EventFanout`, because a third leg that grows a field of its own must
    not be able to change what the other two are called with.
    """

    event_id: str


@dataclass
class DispatchOutcome:
    """What the dispatch workflow did: the numbers an operator asks for."""

    delivered: int = 0
    dead_lettered: int = 0
    pushed: bool = False
    #: Whether the search indexer took this event. `False` covers three
    #: different facts on purpose — no `apps.search` installed, no `Searchable`
    #: subscribed to this name, and an indexer that spent its retry budget —
    #: because none of the three is a failed dispatch and the log line beside
    #: each says which one it was.
    indexed: bool = False


@dataclass
class PurgeExpired:
    """How far back the housekeeping workflow may reach, per population.

    Two windows and not one, because the two populations are not the same
    question: an outbox row is a receipt for a dispatch we made, and a delivery
    is a record of what a subscriber's server said. `EVENTS_OUTBOX_RETENTION_DAYS`
    is a setting; the delivery window is ratified prose (ninety days) and
    a module constant, because this repository settled that no build adds an environment
    variable and because a retention window a deployment can quietly shorten is
    one nobody can reason about from the declaration on the model.
    """

    outbox_retention_days: int
    #: Zero means "the activity's declared default" — exactly
    #: `ReconcileOutbox.batch_size`'s shape and for the same reason: a schedule
    #: action written before this field existed replays out of a Temporal
    #: history as zero, and a replay that silently swept with a window of
    #: nothing would delete every finished delivery in the deployment.
    delivery_retention_days: int = 0


@dataclass
class PurgeOutcome:
    """What the purge removed."""

    idempotency_records: int = 0
    outbox_rows: int = 0
    deliveries: int = 0


@dataclass
class ReconcileOutbox:
    """One **batch** of the relay's drain: how far back, how many, and from where.

    Seconds rather than a `timedelta`, because this crosses a Temporal history
    and is read back from it years later: an integer means the same thing in
    every language that will ever deserialise it, and it is what the schedule's
    action carries.

    `batch_size` is the drain's **ceiling**, carried on the schedule's action so
    an operator can read it off the schedule rather than out of the source
    (the drain had none, before). Zero means "the activity's declared
    default" — a history written before this field existed replays as zero, and
    a replay that silently drained everything would be the finding back again.

    `already_seen` is the batch cursor, and it is a count rather than a key on
    purpose: the candidate set is ordered oldest-clock-first, a resumed row
    leaves the set (its clock is rewritten to `now()`), and the only rows a
    previous batch of *this* sweep can leave at the head are the ones it could
    not move — the `unresolved` ones. So skipping that many is exactly skipping
    them, and each batch starts strictly past the last one. Nothing ever enters
    the set ahead of the cursor: every writer of `next_attempt_at` sets it to
    `now()`, which is the tail.
    """

    grace_seconds: int
    batch_size: int = 0
    already_seen: int = 0


@dataclass
class ReconcileOutcome:
    """What one relay batch — or one whole sweep — did. Each number is asked for.

    `unresolved` is the honest half: a stranded row the dispatch service
    *refused* — most often one whose run has already finished, which cannot be
    healed under the id it claimed, and `NotFound` when the purge took the event
    out from under the sweep. The relay says so rather than inventing a second
    attempt. That is `manage.py replay_events`' population, which is why it is
    counted here and not swallowed.

    `faults` is the other half, and it is a different question.
    A refusal is a decision; a fault is an exception the relay cannot classify —
    a lock timeout, a dropped connection, an error out of the on-commit Temporal
    start. It is isolated per row so that one poison row cannot pin the sweep at
    a fixed offset and starve everything behind it, it is logged at error, and
    `activities.RECONCILE_MAX_FAULTS` of them in one batch fails the activity so
    Temporal's retry gets a systemic fault rather than the relay quietly
    absorbing it. **Both counts advance `already_seen`**: the cursor is "rows
    this batch could not move", not "rows the service refused".

    `more_remaining` is the ceiling speaking. From an activity it means "there
    is at least one candidate past this batch", which is what makes the
    workflow's loop terminate on an answer rather than on a guess. From the
    workflow it means "this sweep spent every batch it is allowed and the queue
    is still not empty" — the next scheduled sweep continues, and an operator
    who sees it stay true has a backlog, not a bug.
    """

    reconciled: int = 0
    unresolved: int = 0
    faults: int = 0
    more_remaining: bool = False
