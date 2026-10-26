"""The names of the things `core` says happened. **Names only** (ADR core-26).

`core` sits BELOW `apps/events` in the layer contract, so it may not import the
app that owns the outbox — every one of these is published by `services.py`
through `bridge.get(bridge.EMIT)`, inside the transaction of the write it
describes, exactly as `apps/example` publishes its own through the same seam.
Until the spine app is mounted an unpublished event is a log line rather than a
failure, which is what lets a checkout stripped back to `core` still run.

The grammar is house rule 16's — `<app>.<noun>.<past-tense verb>` — and the noun
is the authorization KIND the row belongs to (`role`, `membership`, `grant`), so
a subscriber filtering on `core.grant.*` is filtering on the same word the
permission vocabulary uses for those rows.

**`core.membership.updated` is not the socket kick reason, and the two are
deliberately different strings.** `services.KICK_MEMBERSHIP_REVOKED` is
`"core.membership.revoked"` — a reason carried on a channel-layer close frame,
read by `apps/realtime`, never by a webhook subscriber. This module's names are
the published contract; the kick reasons are an internal vocabulary with its own
census (`test_authorization_kick.py::test_the_kick_reasons_are_constants_and_distinct`).
They share a prefix because they are about the same rows; nothing reads both,
and no name appears in both lists. ADR core-26 names this collision as its own
trigger, so the note lives here rather than in a commit message.

Each payload is the row's `Out` through `event_payload`, at v1 (ADR core-26, rule 87).
"""

from __future__ import annotations

#: A tenant made a role of its own. `key` is the immutable half (§D10), so a
#: subscriber joins on it and a later rename moves nothing.
ROLE_CREATED = "core.role.created"

#: Either half of a role changed: its display name and description
#: (`update_role`) or its collection (`set_role_collection`). One name for both,
#: because a subscriber that cares about "what may this role do now" has to
#: re-read the role either way.
ROLE_UPDATED = "core.role.updated"

#: A tenant's own role is gone, and with it every delta row that named it. Only
#: a custom role reaches here: a declared role lives in code and a tenant cannot
#: delete it.
ROLE_DELETED = "core.role.deleted"

#: Somebody's role in one part of a tenant changed. **Not the kick reason** —
#: see the module docstring; `core.membership.revoked` is a close-frame reason
#: and this is a published event.
MEMBERSHIP_UPDATED = "core.membership.updated"

#: One permission handed to, or taken from, one membership. `effect` says which:
#: `allow` widens, `withhold` narrows, and a withhold beats everything.
GRANT_CREATED = "core.grant.created"

#: A grant is gone. The row said what it said; removing an `allow` narrows and
#: removing a `withhold` widens, so `effect` travels on the payload of the
#: deletion too — a subscriber cannot tell the two apart without it.
GRANT_DELETED = "core.grant.deleted"
