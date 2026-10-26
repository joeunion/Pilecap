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
house rule. A synchronous caller goes through `run_on_spine_loop` rather than
this module carrying a second copy of itself.

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

**Four things do NOT wait for a reconnect, and one thing deliberately does.**
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
  whose view actually shrank are closed;
* a **read set is narrowed** — a demotion, a `withhold`, a role's collection
  edited (`core.services.kick_if_reads_narrowed` and its two siblings), because
  since ADR core-27 a read IS a permission and a connection that resolved one at
  the handshake goes on delivering what its hat may no longer read. **This is
  the New Enemy Problem** — SpiceDB's name for the window between a permission
  shrinking and a cached decision noticing, which a ZedToken closes there and a
  kick closes here (BVB-3). A **widening** kicks nobody: nothing a socket is
  delivering has been taken away, and hanging up to give somebody more would be
  a reconnect storm with no security content.

**A role change closed no socket until Phase R, and the argument for that is
struck rather than deleted — it is why trigger 1 below reads FIRED.** Role gates
*verbs*, went the reasoning, never row visibility, at all four seams that decide
what a connection receives: the consumer's group set is
`tenant_group + org_group per subtree id + user_group` (`consumers.py`),
the subtree comes from `list_subtree_org_ids`, which is a pure path prefix scan
(`selectors.py`), the hat comes from `resolve_org`, which reads
`Membership.organization` and never `Membership.role` (`core.middleware`), and
`visible_to` is path-based (`core.models`). Every one of those sentences is
still true, and the conclusion no longer follows: a fifth seam now decides what
a connection receives — `consumers.may_hear`, against the read set — and role is
what fills it. A person demoted to a role holding no reads is refused
`list_widgets` over REST, so a socket that kept delivering widgets to them would
be the disagreement, not the invariant.

One attack worth recording, because it is the one that looks like it should
work: a demotion cannot shrink the set of hats a person may *wear* either.
`resolve_org`'s wearability test is membership *position*
(`is_descendant_path`), never role, and `set_role` writes only the role column
— the escalation wall (rule 24) is what guarantees it writes nothing else. The
acts that shrink the hat set are membership **removal** and a membership
**move**, which is exactly the leak above.

**The six triggers, so this is a decision that repairs itself rather than an
assumption that rots.** They keep their numbers; the first one FIRED and the
other five stand as written. Any one of them expires the reasoning above and
makes the demotion kick correct:

1. **FIRED (ADR core-27).** A product adds a `POLICIES` entry keyed on a
   **read** verb (`*.view` / `*.read` / `*.list` / `*.get`) — which is now every
   kind in the deployment: `core.authz.allows` no longer grants read verbs to
   any membership regardless of role, `read_kinds` is what a connection resolves
   at the handshake, and the kick is **three call sites in `core.services`,
   guarded on the read set** (`set_role` through `_write_role_and_kick`,
   `_kick_the_holders_of`, `_kick_if_a_read_was_taken`) rather than the one
   guarded line this paragraph used to promise;
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

Acting on a trigger used to be one guarded line. Trigger 1 fired and it is
**three call sites in `core.services`, guarded on the read set** — each one
computing `read_kinds_by_node` before and after its write and handing the pair
to `kick_if_reads_narrowed`, which is where the rule "a proper subset at any
node, never a widening" is written down. A trigger that fires next inherits that
seam rather than a rank comparison.
"""

from __future__ import annotations

import asyncio
import atexit
import os
import threading
from collections.abc import Callable, Coroutine, Mapping
from typing import Any
from uuid import UUID

from asgiref.sync import SyncToAsync, async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import ImproperlyConfigured

# **Re-exported, not re-implemented** (R4-F2). `kind_of_event` and
# `event_kinds_of` moved to `apps.core.authz` because `emit()` has to ask the
# same question — an org-scoped event that carries no branch is broadcast
# tenant-wide by `group_for` below — and `apps/events` may not import this app:
# `import-linter` holds the platform apps independent of each other. The answer
# is a registry read plus a per-app declaration and needs nothing either app
# owns, so it belongs below both. The `as` spelling is the explicit re-export
# form, so every reader that already says `from apps.realtime.bridge import
# kind_of_event` is unchanged and there is still exactly one implementation.
from apps.core.authz import event_kinds_of as event_kinds_of
from apps.core.authz import kind_of_event as kind_of_event
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


#: How long a synchronous caller waits for one push or kick on the spine loop, in seconds.
SPINE_CALL_TIMEOUT_SECONDS = 10.0


class _SpineLoop:
    """One event loop per process for the sync adapters, so the channel layer keeps one pool."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pid = 0

    def loop(self) -> asyncio.AbstractEventLoop:
        """The process's spine loop, started on first use and again after a fork."""
        with self._lock:
            if (
                self._loop is None
                or self._thread is None
                or self._pid != os.getpid()
                or not self._thread.is_alive()
            ):
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=loop.run_forever, name="realtime-spine-loop", daemon=True
                )
                thread.start()
                self._loop, self._thread, self._pid = loop, thread, os.getpid()
            return self._loop

    def close(self) -> None:
        """Stop the loop and close it, which flushes the channel layer's pools on it."""
        with self._lock:
            loop, thread, pid = self._loop, self._thread, self._pid
            self._loop, self._thread = None, None
        if loop is None or thread is None or pid != os.getpid():
            return
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=SPINE_CALL_TIMEOUT_SECONDS)
        if not thread.is_alive():
            loop.close()


_SPINE = _SpineLoop()
atexit.register(_SPINE.close)


def _outer_loop() -> asyncio.AbstractEventLoop | None:
    """The ASGI server's loop when this thread is one of its `sync_to_async` threads, else None."""
    if getattr(SyncToAsync.threadlocal, "main_event_loop_pid", None) != os.getpid():
        return None
    loop: asyncio.AbstractEventLoop | None = getattr(
        SyncToAsync.threadlocal, "main_event_loop", None
    )
    return loop if loop is not None and loop.is_running() else None


def run_on_spine_loop(call: Callable[..., Coroutine[Any, Any, None]], **kwargs: Any) -> None:
    """Run a coroutine for a sync caller on a loop that outlives it: the server's or the spine."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "A spine adapter was called from a thread running an event loop - await the coroutine."
        )
    if _outer_loop() is not None:
        async_to_sync(call)(**kwargs)
        return
    future = asyncio.run_coroutine_threadsafe(call(**kwargs), _SPINE.loop())
    try:
        future.result(timeout=SPINE_CALL_TIMEOUT_SECONDS)
    except TimeoutError:
        future.cancel()
        raise


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


def _names_no_row(name: str) -> bool:
    """Whether this event is about nothing a membership could hold a read on.

    A noun nobody decided about answers False rather than True, and that is the
    fail-open direction ON PURPOSE for this one question: an undecided noun is
    already handled one hop later by `consumers._may_read`, which drops the
    frame and says `realtime.frame.kind_undecided`. Dropping it HERE as well
    would put one configuration mistake behind two different log lines.
    """
    try:
        return kind_of_event(name) is None
    except ImproperlyConfigured:
        return False


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
    # **An org-less kind may not name a branch** (R4 F5, house rule 59). The
    # consumer's `_may_read` answers True for a None kind whatever branch the
    # frame carries — the org-less contract, and the right answer for
    # `search.engine.degraded` — so a frame combining the two would reach every
    # connection in the tenant AND skip the read set, which is the widest
    # delivery this product has. `emit()` refuses the combination at the write;
    # this is the belt for a body composed before that refusal existed or by a
    # producer that is not `emit`. DROPPED, never raised: a raise inside a
    # channel-layer handler takes the connection down, so one bad frame would
    # become a reconnect storm — the same argument `consumers._may_read` makes
    # about an undecided noun.
    if event.organization_id is not None and _names_no_row(event.name):
        log.error(
            "realtime.frame.org_on_orgless_kind",
            event_name=event.name,
            tenant_id=str(tenant_id),
            organization_id=str(event.organization_id),
        )
        return
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


async def kick_tenant(*, tenant_id: UUID | str, reason: str | None = None) -> None:
    """Close every socket open on this tenant. **The second kick primitive.**

    `kick_user` answers "this credential is gone"; this answers "this
    workspace is". A tenant suspended or closed is not a fact about one
    person, and there was no way to say it: R4 found that `suspend_tenant`
    wrote a status and registered nothing, so a NEW handshake was refused
    while every connection already open went on hearing for the life of the
    connection — hours, by this module's own docstring — and the REST door
    answered 403 to the same credential the whole time. Two doors, one
    question, two answers, which `architecture.md` calls a finding.

    **A `KICK_TYPE` frame on the bare tenant group, and that is the one
    message that legitimately goes there.** Rule 36 refuses an org-bearing
    PAYLOAD on `tenant_group` because a payload is about a row one branch
    owns; an instruction to hang up is about the tenant, so it reaches every
    socket in it by construction — which is exactly what a suspension means.
    The rule's statement says so since R4-F3 and a negative pins it.

    Fire-and-forget and idempotent, like every other kick: a tenant with
    nothing open is not an error, a `group_send` to an empty group is a
    no-op, and kicking twice closes nothing the second time.

    The client is told `CLOSE_KICKED`, the same code a revoked credential
    gets, because that is all a disconnected client can act on; which way
    the tenant went dark is the operator's business and rides the log line.
    """
    await _layer().group_send(
        tenant_group(tenant_id),
        {"type": KICK_TYPE, "reason": reason},
    )
    log.info("realtime.tenant.kicked", tenant_id=str(tenant_id), reason=reason)


def kick_tenant_from_spine(*, tenant_id: Any, reason: str | None = None) -> None:
    """The callable `core.bridge` holds under `realtime.kick_tenant`.

    Synchronous for `kick_from_spine`'s reason, unchanged one level up: the
    caller is `core.services.close_tenant_sockets`, reached from an
    `on_commit` hook on whatever thread committed the write, and a coroutine
    handed to a sync caller is a coroutine nobody awaits — a suspension that
    reports success and closes nothing.
    """
    run_on_spine_loop(kick_tenant, tenant_id=tenant_id, reason=reason)


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
    run_on_spine_loop(kick_user, user_id=user_id, reason=reason)


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
    run_on_spine_loop(push_event, tenant_id=tenant_id, event=message)
