"""The names of the things this app says happened.

**Names only, and that is the whole file.** `services.py` publishes them with
`_publish(WIDGET_CREATED, ...)` inside the write's transaction, through
`core.bridge` — so `apps/events` (the outbox, the signed webhook deliveries, the
realtime push) can land later and every one of these names is already being
said. Until it does, an unpublished event is a log line rather than a failure.

Declaring them in one file, rather than as literals at the call sites, is
deliberate:

* the naming rule is `<app>.<noun>.<past-tense verb>` (house rule 16), and it is
  much easier to keep when the names live in one file per app than when each is
  a string literal at a call site;
* an event name is a **published contract**. A webhook subscriber matches on it
  and a rename breaks every integration silently, so the name is a constant with
  one definition and never a literal;
* `introspect` reports this file, so a client integrating with the product can
  read the list of events it may subscribe to without reading the source.

A past-tense verb, always: an event is a statement that something *has*
happened. `widget.create` would be an instruction, and an instruction is a
service call, not an event.
"""

from __future__ import annotations

WIDGET_CREATED = "example.widget.created"
WIDGET_UPDATED = "example.widget.updated"
WIDGET_DELETED = "example.widget.deleted"

# The one an app cannot emit from a request: onboarding waits for a human to
# approve it, so the statement that it happened is made by an activity, hours or
# days after the widget was created. Same grammar, same file, same contract.
WIDGET_ONBOARDED = "example.widget.onboarded"
