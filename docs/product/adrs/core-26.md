# ADR core-26

**ADR core-26 · `core` says what happened, through the bridge.** *Accepted
2026-09-15 (P20, P4).* *Context*: `core` emitted no events at all. It sits
BELOW `apps/events` in the layer contract (rule 7), so it may not import the app
that owns the outbox — and the six most consequential writes in the platform
(a role made, renamed, deleted; a role's collection edited; a permission handed
to or taken from one person) were therefore invisible to every webhook
subscriber and every socket, while a widget creation was not. *Decision*:
`apps/core/events.py` declares `core.role.created`, `core.role.updated`,
`core.role.deleted`, `core.membership.updated`, `core.grant.created`,
`core.grant.deleted` — names only, house rule 16's grammar, the noun being the
authorization KIND the row belongs to — and `services.py` publishes each one
through `bridge.get(bridge.EMIT)` **inside the transaction of the write it
describes** (principle 8; the relay is outside it). Payload v1 is the
row's `Out` through `event_payload` (rule 87) — the shape the doors answer:
`RoleOut` on the three role names (`key`, `name`, `description`, `kind`,
`permissions`, `default_permissions`, `added`, `removed`,
`is_default_for_new_members`, `created_at`, `updated_at`), `MembershipOut` less
its `personal` field (`user_email`) on `core.membership.updated` (`id`, `user_id`, `organization_id`, `role`,
`is_default`, `created_at`, `updated_at`), `GrantOut` on the grant
names (`id`, `membership_id`, `organization_id`, `permission`, `sentence`,
`effect`, `created_at`); a deletion carries the row as it stood before the
delete, and `organization_id` is there wherever the row belongs to one part of
the tenant (rule 38). *Rejected*: importing `apps.events` from `core` (rule
7 — and the spine apps are removable, so a checkout stripped back to `core` must
still run); emitting from the door (rule 10); shipping the hand-out family with
no events at all (rule 42's class — a write nobody can subscribe to). *The one
collision, named*: `services.KICK_MEMBERSHIP_REVOKED` is the string
`"core.membership.revoked"` — a channel-layer close reason, read by
`apps/realtime` and by nobody else. The two vocabularies share a prefix because
they are about the same rows; no name appears in both, nothing reads both, and
`apps/core/events.py`'s docstring is where that is written down. *Trigger to
revisit*: the first `core.membership.*` event beyond `updated` — a creation or a
revocation published as an event rather than only kicked — at which point the
two lists are close enough together that one of them is renamed.
