"""The shapes that cross the workflow boundary. Standard library only.

Everything here is serialised into a Temporal history and replayed out of it,
possibly years later, so they are plain dataclasses of plain data: no model
instances, no queryset, no `timedelta`, and — the one that matters most in this
app — **never a credential**. A `Connection`'s tokens and its webhook secret
travel nowhere near this module; an activity looks the row up by id and reads
the encrypted blob from the database, where it belongs. A secret in a workflow
argument is a secret in the history for as long as retention says.

The sibling of `apps/events/types.py`, and separate from it for the reason the
layer contract gives: `apps.connections` and `apps.events` are siblings and
neither may import the other, so a shape that crosses this app's boundary is
restated here rather than shared.
"""

from __future__ import annotations

from dataclasses import dataclass

#: The name Temporal knows the purge workflow by, in one place.
#:
#: `activities.py` needs it to build the schedule's action and `workflows.py`
#: needs it to register the class, and the two must not be able to drift — a
#: schedule pointed at a workflow name nothing registers is a machine that
#: starts nothing and says nothing. It lives HERE rather than in either of them
#: because `workflows.py` may import this module and nothing else of ours
#: (house rule 9), and `activities.py` importing `workflows.py` would drag a
#: workflow definition into the module that holds the ORM.
PURGE_WORKFLOW = "PurgeInboundWebhooksWorkflow"


@dataclass
class PurgeInboundWebhooks:
    """How far back the housekeeping workflow may reach.

    Days as an integer rather than a `timedelta`, because this crosses a
    Temporal history and is read back from it years later: an integer means the
    same thing in every language that will ever deserialise it, and it is what
    the schedule's action carries so that an operator can read the retention off
    the schedule rather than out of the source.
    """

    retention_days: int


@dataclass
class PurgeOutcome:
    """What the purge removed. The number an operator asks for.

    why-not `core.types.Swept`: rule 9 lets `workflows.py` import only this app's own `types.py`.
    """

    inbound_webhooks: int = 0


#: The name Temporal knows a receipt's handler run by, shared by its starter and its class.
HANDLE_WORKFLOW = "InboundWebhookWorkflow"


@dataclass
class HandleInboundWebhook:
    """Which stored receipt the registered handler is handed; the row is read in the activity."""

    inbound_webhook_id: str
    retry_floor: float | None = None
