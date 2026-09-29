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

# golden: import begin
WIDGET_CREATED = "example.widget.created"
# golden: import end
# golden: version move bulk history duplicate attach merge import begin
WIDGET_UPDATED = "example.widget.updated"
# golden: version move bulk history duplicate attach merge import end
WIDGET_DELETED = "example.widget.deleted"

# The one an app cannot emit from a request: onboarding waits for a human to
# approve it, so the statement that it happened is made by an activity, hours or
# days after the widget was created. Same grammar, same file, same contract.
WIDGET_ONBOARDED = "example.widget.onboarded"

# Archive and restore: a row leaving the book and coming back. Said only when the
# press CHANGED the row — a repeat press answers the row and says nothing, so a
# subscriber counting archives counts archives and not retries.
# golden: archive version move bulk history duplicate attach merge import begin
WIDGET_ARCHIVED = "example.widget.archived"
WIDGET_RESTORED = "example.widget.restored"
# golden: archive version move bulk history duplicate attach merge import end
WIDGET_POLICY_ARCHIVED = "example.widget_policy.archived"
WIDGET_POLICY_RESTORED = "example.widget_policy.restored"

# A widget re-homed at another node, or handed to another owner. The payload is
# the row where it now is, and `from_organization_id` names where it was, so a
# subscriber that filed it under the old node can take it out again.
# golden: move bulk history duplicate attach merge import begin
WIDGET_MOVED = "example.widget.moved"
# golden: move bulk history duplicate attach merge import end

# A copy made from a widget: the payload is the COPY, and `duplicated_from_id`
# names the widget it was made from. Said once per copy — a repeated press with
# the same key answers the first copy and says nothing.
# golden: duplicate attach merge import begin
WIDGET_DUPLICATED = "example.widget.duplicated"
# golden: duplicate attach merge import end

# Two widgets became one: the payload is the SURVIVOR, `loser_id` the widget
# folded into it, and `repoints` what each owning app moved across (`title`,
# `left`) — the apply's own counts, never the dry run's.
# golden: merge import begin
WIDGET_MERGED = "example.widget.merged"
# golden: merge import end
