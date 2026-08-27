"""The push side of the socket door: an event goes in, every live socket for
that tenant gets it.

**This is the function `core.bridge` names `"realtime.push"`.** `architecture.md`
rules that a lower layer never imports a higher one: `apps/events` fans an event
out from its dispatch workflow, and one of the places it fans out to is here —
reached by registry lookup (`core.bridge.get("realtime.push")`), never by
`from apps.realtime...`. `apps.events` and `apps.realtime` are the same layer in
the import contract, so an import either direction is refused, which is exactly
why the registry exists. Keep the dotted path stable:
**`apps.realtime.bridge.push_event`**.

It is `async` because the channel layer is: `group_send` is a coroutine, and the
one caller the design anticipates — a Temporal activity — is `async def` by
house rule. A synchronous caller wraps it (`async_to_sync(push_event)`) rather
than this module carrying a second copy of itself.

Nothing here reads the database, and that is deliberate. A push is fan-out to
whoever happens to be connected: it takes a tenant id and a message that is
already a schema, so a burst of events cannot turn into a burst of queries.

## Three kinds of group, and why (ADR realtime-2)

* **`tenant_group(tenant)`** — everyone in the tenant. Org-*less* events, and
  only those: an event about something no branch owns in particular.
* **`org_group(tenant, org)`** — one branch. An org-bearing event is sent here
  and **only** here, one send, and the subscribers who hear it are the hats
  whose subtree contains that branch. The narrowing happens at *join* time
  rather than at push time, which is the trade this ADR made: subtree-join cost
  rides only on connected sockets, where an ancestor-chain publish would ride
  on every emit including the socketless majority. The rejected alternative is
  recorded with its trigger — a measured join count at a wide hat.
* **`user_group(user)`** — one person, across every socket they have open.
  Nothing is *pushed* here; it exists so that `kick_user` can close them all
  when the credential behind them stops existing.

## What this channel promises, and what it does not

**It is lossy, and that is the contract, not a defect.** A push is a
`group_send` to whoever is joined *at that instant*: a client that is
reconnecting, paused by a backgrounded tab, or behind a proxy that dropped the
connection is simply not there, and nothing is queued for it. There is no
replay buffer, no cursor, no "since" parameter, and none is planned — durable
delivery is the outbox's job (`apps/events`), and a subscriber that needs every
event without exception is a webhook subscriber.

**So the seam is poll-on-reconnect.** A client that has just reconnected must
re-read the REST list it cares about and treat the socket as a *hint that
something changed*, never as the record of what changed. A UI built the other
way — applying socket frames as the source of truth — is correct right up to
the first dropped connection and silently wrong afterwards, which is the
failure this paragraph exists to prevent somebody discovering in production.

**A VOLUNTARY hat change rides the same seam.** Groups are computed once, at
connect, from the hat the middleware resolved then; a client that switches
`X-Org` mid connection keeps the groups it joined until it reconnects.
Reconnecting is what applies the new hat, and it is cheap.

**Three things do NOT wait for a reconnect, and one thing deliberately does.**
The old wording here said "revocation" and left a reader to decide what that
covered; a field test found that a reader takes it to include the withdrawal
of a *hat*, which it did not. Said precisely, the socket is closed immediately
(`CLOSE_KICKED`) when:

* a **credential** is withdrawn — a token revoked, a user erased, an identity
  revoked in Zitadel (`apps.accounts.services`), because "the credential is
  gone" cannot be left to the client's own timing;
* a **membership is removed** (`core.services.remove_membership`), because the
  person now resolves no hat in that tenant at all and every org group their
  connection holds is a branch they may no longer read;
* a **subtree is re-parented** out from under a hat
  (`core.services.apply_organization_move`), because a move withdraws
  visibility without touching a single membership row, and only the people
  whose view actually shrank are closed.

**A role change does not close the socket, and that is correct rather than an
omission.** Role gates *verbs*, never row visibility, at all four seams that
decide what a connection receives: the consumer's group set is
`tenant_group + org_group per subtree id + user_group` (`consumers.py`),
the subtree comes from `list_subtree_org_ids`, which is a pure path prefix scan
(`selectors.py`), the hat comes from `resolve_org`, which reads
`Membership.organization` and never `Membership.role` (`core.middleware`), and
`visible_to` is path-based (`core.models`). So a person demoted `owner` ->
`member` still reads exactly the same rows over REST, and a socket that kept
delivering them AGREES with the REST door — which is the invariant, not a
breach of it. Kicking on a role change would drop a live connection to enforce
a narrowing that does not exist.

One attack worth recording, because it is the one that looks like it should
work: a demotion cannot shrink the set of hats a person may *wear* either.
`resolve_org`'s wearability test is membership *position*
(`is_descendant_path`), never role, and `set_role` writes only the role column
— the escalation wall (rule 24) is what guarantees it writes nothing else. The
acts that shrink the hat set are membership **removal** and a membership
**move**, which is exactly the leak above.

**The six triggers, so this is a decision that repairs itself rather than an
assumption that rots.** Any one of these expires the reasoning and makes the
demotion kick correct:

1. a product adds a `POLICIES` entry keyed on a **read** verb
   (`*.view` / `*.read` / `*.list` / `*.get`) — today every action in every
   `policies.py` is a write verb, and `core.authz.allows` additionally grants
   the read verbs to any membership regardless of role;
2. a selector or a route branches on `effective_role` / `membership_for` /
   `is_privileged`, or a schema resolver picks an `Out` variant by role
   (field-level redaction — the socket ships the full body regardless);
3. a concrete model overrides `visible_to` / `for_tenant` / `governing` to
   consult role;
4. `resolve_org` grows a role floor for wearing a sub-hat;
5. "demote" stops being `set_role` — implemented as a membership move, or as
   remove-and-re-add, which changes the hat set (that is the removal leak
   above, not this one, and it is already closed);
6. a `Role.VIEWER`-style addition tempts somebody to make `is_read`
   role-ranked in `allows()`.

The seam is already here, so acting on a trigger is one guarded line: a
`close_sockets_on_commit(user_id=..., reason=...)` in `core.services.set_role`,
guarded on `rank(new) < rank(old)`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from apps.core.log import get_logger
from apps.realtime.schemas import EventMessage

log = get_logger(__name__)

# The group prefixes. Three kinds, all of them **derived** — a client never
# names a group, so a client can never join one that is not its own, and the
# prefixes are distinct so that no id could ever be read as the wrong kind.
GROUP_PREFIX = "tenant"
ORG_GROUP_PREFIX = "org"
USER_GROUP_PREFIX = "user"

# The channel-layer message type. Channels turns the dot into an underscore and
# calls `TenantEventsConsumer.realtime_event`; the name is namespaced so that a
# product adding its own message types cannot collide with this one.
MESSAGE_TYPE = "realtime.event"

# The kick's message type, mapping to `TenantEventsConsumer.realtime_kick` by the
# same dot-to-underscore rule. A separate type rather than a flag on the event
# message: one is a payload to deliver and the other is an instruction to hang
# up, and a consumer that had to inspect a push to find out which is a consumer
# that will one day deliver a hang-up as data.
KICK_TYPE = "realtime.kick"


def tenant_group(tenant_id: UUID | str) -> str:
    """The group every socket for this tenant belongs to. **Org-less events only.**

    Channel-layer group names are restricted to `[a-zA-Z0-9_.-]`, which a UUID
    satisfies. The tenant's *id* and not its slug, because a slug can be
    renamed and a group name that changes underneath a live connection would
    silently stop delivering.
    """
    return f"{GROUP_PREFIX}.{tenant_id}"


def org_group(tenant_id: UUID | str, organization_id: UUID | str) -> str:
    """The group for one branch of one tenant's tree.

    The tenant id is in the name as well as the organization's, and not because
    two tenants could mint the same UUID. It is so that a group name is
    self-describing in the channel layer, in a log line and in a `redis-cli`
    session — the same reason an audit row carries both.
    """
    return f"{ORG_GROUP_PREFIX}.{tenant_id}.{organization_id}"


def user_group(user_id: UUID | str) -> str:
    """Every socket one person currently has open, across tenants and hats.

    Deliberately **not** scoped by tenant: what this group exists for is the
    kick, and the events that fire it — a revoked token, an erased user — are
    facts about the person rather than about one of their memberships. A kick
    that closed the sockets for one tenant and left the others open would be a
    revocation that did not revoke.
    """
    return f"{USER_GROUP_PREFIX}.{user_id}"


def _layer() -> Any:
    layer = get_channel_layer()
    if layer is None:
        raise RuntimeError(
            "No channel layer is configured, so nothing can be pushed to a socket. "
            "CHANNEL_LAYERS in config/settings is what supplies one."
        )
    return layer


def group_for(*, tenant_id: UUID | str, event: EventMessage) -> str:
    """The one group this event is sent to. **One send, never a fan-out.**

    An event that knows its branch goes to that branch's group; an event that
    does not is tenant-wide. The choice is made from the envelope rather than
    from a parameter (ADR realtime-2a), so the spine's signature never had to
    learn about the hierarchy and the two doors keep reading one body.

    A function rather than three lines inside `push_event`, because this is the
    sentence house rule 36 is about to enforce — "an org-scoped payload is never
    pushed to a bare tenant group" — and a rule is easier to hold when the
    decision it is about has a name.
    """
    if event.organization_id is not None:
        return org_group(tenant_id, event.organization_id)
    return tenant_group(tenant_id)


async def push_event(*, tenant_id: UUID | str, event: EventMessage) -> None:
    """Push one event to the group it belongs to, and to nothing else.

    Fire-and-forget by design: a socket is a *live* channel, so an event that
    nobody is connected for is not a failure and is not retried here. Durable
    delivery is the outbox's job (`apps/events`), and the workflow that calls
    this already owns the retry.

    Which group is `group_for`'s answer — the row's branch when it has one, the
    tenant otherwise. The signature is unchanged from when only tenant groups
    existed, and that is the point of carrying the organization on the envelope:
    the spine hands over one body and this side decides where it goes.
    """
    group = group_for(tenant_id=tenant_id, event=event)
    await _layer().group_send(
        group,
        {"type": MESSAGE_TYPE, "message": event.model_dump(mode="json")},
    )
    log.info(
        "realtime.event.pushed",
        event_name=event.name,
        tenant_id=str(tenant_id),
        group=group,
    )


async def kick_user(*, user_id: UUID | str, reason: str | None = None) -> None:
    """Close every socket this person currently has open.

    The primitive behind revocation and erasure (ADR realtime-2 d). Socket auth
    is resolved once, at the handshake, which is the right design for a channel
    that then stays open for hours and the wrong one the moment a credential is
    withdrawn: without this, a revoked token keeps receiving until the client
    happens to disconnect. So the withdrawal *reaches* the connection instead of
    the connection eventually noticing.

    Fire-and-forget for the same reason a push is: a person with nothing open is
    not an error, and `group_send` to an empty group is a no-op. Idempotent by
    construction — kicking twice closes nothing the second time — which is what
    the retrying activity that will call this needs.
    """
    await _layer().group_send(
        user_group(user_id),
        {"type": KICK_TYPE, "reason": reason},
    )
    log.info("realtime.user.kicked", user_id=str(user_id), reason=reason)


def kick_from_spine(*, user_id: Any, reason: str | None = None) -> None:
    """The callable `core.bridge` holds under `realtime.kick`. **The one entry point.**

    Synchronous, exactly as `push_from_spine` is and for exactly the same
    reason: the caller is a plain `def` activity on the worker's thread pool
    with no event loop to await on, and a coroutine handed to a sync caller is a
    coroutine nobody awaits — a revocation that reports success and closes
    nothing, which is the worst failure available to this particular seam.

    `reason` is free text for the log line, not a close code: the client is told
    `CLOSE_KICKED` whatever the reason, because "your credential is gone" is all
    a client can act on and the difference between revoked and erased is the
    operator's business, not theirs.
    """
    async_to_sync(kick_user)(user_id=user_id, reason=reason)


def push_from_spine(*, tenant_id: UUID | str, event: Mapping[str, Any] | EventMessage) -> None:
    """The callable `core.bridge` holds under `realtime.push`. **The one entry point.**

    Two things stand between `push_event` and the caller, and both of them are
    the caller's constraints rather than this app's:

    * **It is synchronous.** The caller is `apps.events`' `push_realtime`
      activity, and every activity in this repository is a plain `def` running
      on the worker's thread pool (`apps/workflows/client.build_worker`), where
      there is no event loop to await on. A coroutine handed to a sync caller is
      a coroutine nobody awaits — `pushed=True` in the dispatch outcome and
      nothing on the wire, which is the worst of the available failures.
    * **It takes a mapping.** `apps.events` and `apps.realtime` are siblings in
      the layer contract, so the spine cannot import `EventMessage` to build
      one. It hands over the JSON body it already signs for a webhook
      subscriber — `apps.events.schemas.envelope` — and the coercion happens
      here, on the side that owns the schema. That is also the door-parity
      property in code: a socket client and a webhook subscriber are reading
      one serialisation, not two.

    `push_event` stays the in-app API — async, typed, the thing another
    coroutine calls. This is the adapter, and it is registered rather than
    `push_event` itself for the two reasons above.

    **The organization arrives here, in the body.** `EventOut.organization_id`
    is a field of the envelope the spine hands over, so the coercion below picks
    it up with everything else and `push_event` narrows on it — no third
    parameter, no change to `PushesToSockets`, and no second serialisation of
    one fact (ADR realtime-2a). A body composed before that field existed still
    validates: it is optional, and an absent organization means tenant-wide,
    which is what such a body always meant.
    """
    message = event if isinstance(event, EventMessage) else EventMessage.model_validate(dict(event))
    async_to_sync(push_event)(tenant_id=tenant_id, event=message)
