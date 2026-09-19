"""The names of the things this app says happened.

Names only. `services.py` publishes them with `emit(name=THRESHOLD_CROSSED, ...)`
inside the write's transaction, and the grammar is `<app>.<noun>.<past-tense
verb>` (house rule 16).

**There is exactly one event, and the absence of the obvious one is the design.**
ADR usage-1 rejected a per-entry event out loud: an outbox row per LLM call
doubles the write volume of the hottest path in the product for zero
subscribers, and the ledger already IS the record — a subscriber that wants to
know what was consumed reads it. The rejection named its own trigger ("a
quota/threshold feature"), the owner fired that trigger, and this
is what came out of it: **the crossing gets an event, the entry still never
does.** A threshold is crossed once per period; an entry happens thousands of
times a minute.

**What a subscriber may conclude from it, and what it may not.** It may conclude
that a tenant's total for one meter passed a line that tenant configured. It may
NOT conclude that anything was stopped: metering observes and never refuses (ADR
usage-1, the owner's word is quota-*counting*). No write path anywhere in this
platform consults this ledger to block an action. A product that wants a hard
quota builds that refusal in its own services, on this event and on
`selectors.get_usage` — with its own ADR, because deciding to stop somebody
working is a product decision and never the platform's.
"""

from __future__ import annotations

#: A tenant's total for one meter passed a line that tenant configured, in the
#: period the entry that crossed it landed in. Payload: `ThresholdCrossingOut`.
THRESHOLD_CROSSED = "usage.threshold.crossed"


#: Which authorization kind the noun above is about, for the socket door's read
#: check (`apps.realtime.bridge.kind_of_event`, ADR core-27).
EVENT_KINDS: dict[str, str | None] = {
    # A crossing is a fact about the ledger it was counted from: whoever may
    # read a tenant's `UsageEntry` rows may be told that their total passed a
    # line, and nobody else.
    "threshold": "usage_entry",
}
