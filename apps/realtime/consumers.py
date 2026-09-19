"""The socket door: one consumer, groups derived from the caller, pushes only.

`config/asgi.py` discovers `websocket_urlpatterns` here and mounts it behind
`AuthMiddlewareStack` and `TenantMiddlewareASGI`. Nothing in `config/` is
edited to add this app — the file being here is the registration.

Three properties, and every one of them is a refusal:

* **Nobody connects anonymously.** No principal, no socket (`4401`).
* **Nobody connects without a tenant.** A real, active user who belongs to no
  tenant is refused (`4403`) rather than connected to nothing — tenancy fails
  closed on this door exactly as it does on the others, superuser included.
* **Nobody names their own group.** Every group is derived from what the
  middleware stack resolved — the tenant, the acting hat, the user — and never
  from anything the client sent, so "subscribe me to Globex" is not a message
  this consumer has a handler for.

**The hierarchy reaches this door** (ADR realtime-2). A connection joins three
kinds of group and all three are derived:

* the **tenant** group, for events about something no branch owns;
* one **org** group per organization in the acting hat's **subtree**, which is
  the socket's half of house rule 24 — the REST door narrows rows with
  `visible_to`, and this narrows subscriptions to exactly the branches whose
  rows that hat would have been allowed to read;
* the caller's **user** group, so a revoked or erased principal's sockets can be
  closed from outside (`bridge.kick_user`).

**And the user group is joined FIRST, before either read.** The order is the
whole of the fix for the New Enemy window at the handshake: a narrowing that
commits while `connect` is still resolving the subtree and the read set sends
its kick to a group the connection has not joined, so the kick is lost and the
socket accepts holding the set from before the write. `connect` says why at the
line that does it, and the census over every consumer `introspect` lists is
`test_authorization_kick.py::test_the_user_group_is_joined_before_any_read`.

An unresolved hat joins no org group and therefore hears no org-bearing event:
fails closed, the same way `for_tenant(None)` and `visible_to(None)` do. **A
flat product pays a constant** — a depth-one tree's root hat has a subtree of
one, so it joins the tenant group, one org group and its user group, and the
depth-one property CLAUDE.md promises survives.

**Two reads, made once.** The subtree above, and the set of authorization kinds
the acting hat may READ (`core.authz.read_kinds`, ADR core-27) — both at
connect, both held on the connection. The first decides which groups this socket
joins; the second decides which frames it is told about once a group has reached
it, because a read is a permission on this door exactly as it is on the REST one
and a socket that kept delivering a kind its hat may no longer read would
disagree with the list that same client fetches. A consumer that resolved either
per message would turn one event into one query per connected client, which is
the N+1 the push design exists to avoid.

The read set narrows per **hat**, never per org × kind (Overrule 1, ratified
2026-09-15): REST asks once at the hat through `where_of`, so a per-org socket
set would disagree with the list — and the group set stays `1 + |subtree| + 1`,
which is what keeps the flat product's three groups three.


And one absence: **there are no client-to-server commands.** A socket in this
template is a delivery channel, not a second API — a command over a socket
would be a door with no `auth=`, no throttle, no idempotency key and no audit
row, sitting beside a REST API that has all four. A client that wants to *do*
something calls the API and watches the result arrive here. The only frame the
client may send is a ping, so that a proxy which times idle connections out has
something to keep alive on.
"""

from __future__ import annotations

from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.exceptions import ImproperlyConfigured
from django.urls import URLPattern, path

from apps.core.actor import TOKEN_ATTR
from apps.core.api.scopes import READ, SCOPE_SEPARATOR, families_of_app, within_ceiling
from apps.core.asgi_middleware import ORG_SCOPE_KEY
from apps.core.asgi_middleware import SCOPE_KEY as TENANT_SCOPE_KEY
from apps.core.asyncdb import run_db
from apps.core.authz import read_kinds
from apps.core.log import get_logger
from apps.realtime.bridge import kind_of_event, org_group, tenant_group, user_group
from apps.realtime.middleware import token_auth
from apps.realtime.schemas import (
    CLOSE_KICKED,
    CLOSE_NO_TENANT,
    CLOSE_NOT_A_COMMAND,
    CLOSE_UNAUTHENTICATED,
)
from apps.realtime.selectors import list_subtree_org_ids

log = get_logger(__name__)

PING = "ping"
PONG = "pong"

ROUTE = "ws/events/"
ROUTE_NAME = "realtime-events"


# `channels` ships no type information (no `py.typed`), and `pyproject.toml`
# therefore declares `ignore_missing_imports` for it — which makes every name it
# exports `Any`, and `mypy --strict` refuses to subclass `Any`. The alternative
# is hand-rolling the accept/receive/group protocol this base class exists to
# provide, which would trade one suppressed error for a hundred lines nobody
# should be maintaining.
class TenantEventsConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    """Every event for the caller's tenant, for as long as they are connected.

    **Unless the credential that opened it carries a ceiling** (ADR ident-7). A
    bearer token minted for a narrow job says which sections of the product it
    may read, and a socket is a read — so a frame from a section this token
    cannot read is not sent down it. The narrowing is per frame rather than per
    group, and that is the deliberate half: groups are the hierarchy's business
    (which *rows* this hat can see) and a ceiling is the credential's (which
    *capabilities* this token was given), and folding one into the other would
    make a re-mint require a reconnect and a hat change require a re-mint.

    A session and a token with no ceiling receive exactly what they always did.

    **THE EXTENSION SEAM: a product's fifteenth app subclasses this; it does not
    write a second consumer** (house rule 58). `config/asgi.py` discovers every
    app's `websocket_urlpatterns` and mounts them all the same way, so a
    consumer written *beside* this one is mounted with exactly the same standing
    and inherits none of the three refusals above — a reviewed, plausible
    `AsyncJsonWebsocketConsumer` doing `group_add(f"tenant.{query['tenant']}")`
    and `accept()` is an anonymous cross-tenant door, and R4 planted one and
    watched the whole gate pass it. So:

    * **subclass this class**, and reach `super().connect()` rather than
      re-deriving the handshake — the anonymous refusal, the tenant refusal, the
      user-group-first ordering (R4-F4) and the subtree join are all in it;
    * **mount through `token_auth(...)`**, which is what gives the pattern a
      machine credential at all;
    * **take every group from the bridge's three builders** — `tenant_group`,
      `org_group`, `user_group`. A name built at the join is a subscription to
      whatever the expression evaluates to.

    An app that needs its own *frames* overrides `receive_json` or adds a
    channel-layer handler; it does not need its own `connect`, and rule 58 is
    the gate's half of that sentence. What rule 58 cannot see is an override
    that subclasses this and then skips the refusals anyway — that is review's,
    and it is named in the rule's declared blind spots.
    """

    #: The scopes the credential behind this socket carries, or `None` for a
    #: session and for a token minted with no ceiling. Read once, at connect,
    #: from what the middleware left on the scope — a socket lives for hours and
    #: a database read per frame would be a query per event per connection.
    ceiling: list[str] | None = None

    #: The authorization kinds the hat behind this socket may READ, computed once
    #: at connect (ADR core-27). `None` until `connect` computes it, which is a
    #: consumer that has joined no group and is therefore reachable by no frame;
    #: a CONNECTED socket always holds a `frozenset`, and an unresolved hat holds
    #: the EMPTY one — `read_kinds` fails closed exactly as `for_tenant(None)`
    #: does, so "unresolved" means hearing only what nobody owns a row for.
    reads: frozenset[str] | None = None

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        tenant = self.scope.get(TENANT_SCOPE_KEY)
        if tenant is None:
            await self.close(code=CLOSE_NO_TENANT)
            return

        # **The user group is joined FIRST, before either read, and the ORDER is
        # the security property.** A read is two statements against the database
        # and the database is where a narrowing commits, so the window between
        # "this connection resolved what it may hear" and "this connection can
        # be hung up on" is exactly as long as those reads take. A demotion, a
        # `withhold` or a membership removal that commits inside that window
        # sends its kick (`bridge.kick_user` → `user_group`) to a group this
        # connection has not joined yet: the `group_send` lands in an empty
        # group, the kick is LOST, and the socket then accepts holding the read
        # set from before the write and delivers under it for hours. That is the
        # New Enemy window (BVB-3) at the handshake rather than mid-connection,
        # and no amount of kicking closes it from outside — the fix is ordering,
        # here, and nothing else can be.
        #
        # Joining before `accept()` is safe and is what makes this work: Channels
        # dispatches one message at a time, so a kick arriving while `connect` is
        # still running is delivered to `realtime_kick` only after `connect`
        # returns. The socket is therefore accepted and immediately closed, which
        # is the correct outcome — a client that sees an accept followed by
        # `CLOSE_KICKED` reconnects and recomputes, where a client that saw a
        # silent accept would not.
        mine = user_group(user.pk)
        await self.channel_layer.group_add(mine, self.channel_name)
        self.groups.append(mine)

        # **Two reads, made once.** The subtree decides which GROUPS this
        # connection joins; the read set decides which KINDS it may be told
        # about once a group has reached it. Both are resolved here, at the
        # handshake, and held for the life of the connection — a consumer that
        # resolved either per message would turn one event into one query per
        # connected client, which is the N+1 the push design exists to avoid.
        # `run_db` and not a bare `sync_to_async`: there is no request cycle out
        # here to close what a worker thread opened, and a connection leaked per
        # thread is a connection leaked forever.
        org = self.scope.get(ORG_SCOPE_KEY)
        # The credential's ceiling, off the row the bearer middleware resolved.
        # `None` either way for a session: there is no token, so there is nothing
        # narrowing what this connection may hear.
        token = self.scope.get(TOKEN_ATTR)
        self.ceiling = getattr(token, "scopes", None) if token is not None else None
        subtree = await run_db(list_subtree_org_ids, tenant=tenant, org=org)
        # The read set is asked at the HAT and not per org (Overrule 1, ratified
        # 2026-09-15): the REST door asks once at the hat through `where_of`, so
        # a per-org socket set would disagree with the list the same client just
        # fetched — and rule 46 is the rule that disagreement breaks. It is three
        # statements whatever the tree, and it does NOT move the group set.
        self.reads = await run_db(read_kinds, user, tenant, org)

        groups = [
            tenant_group(tenant.pk),
            *(org_group(tenant.pk, organization_id) for organization_id in subtree),
        ]
        for group in groups:
            await self.channel_layer.group_add(group, self.channel_name)
        # Handing the groups to the base class is what unsubscribes them: its
        # `websocket_disconnect` discards everything in `self.groups`, so a
        # dropped connection cannot leave a channel name in the layer that
        # nothing will ever read from again. The user group is already in that
        # list — it was appended above, FIRST — so the discard covers all three
        # kinds exactly as it did when all three were joined together.
        self.groups.extend(groups)
        await self.accept()
        log.info(
            "realtime.socket.joined",
            tenant_id=str(tenant.pk),
            org_id=str(org.pk) if org is not None else None,
            groups=len(self.groups),
            # How many kinds this connection may be told about. A number rather
            # than the set: it is what an operator needs to see a narrowing
            # happen ("this hat reconnected holding four fewer"), and the set
            # itself would put a tenant's authorization shape in the log.
            reads=len(self.reads),
        )

    async def receive(
        self,
        text_data: str | None = None,
        bytes_data: bytes | None = None,
        **kwargs: Any,
    ) -> None:
        """Text frames with something in them, or nothing.

        The JSON consumer's own version raises on a binary or empty frame, and
        an exception escaping a consumer takes the connection down with a
        traceback in the logs instead of a close code the client can read.
        Neither is a command, and neither is a ping, so both get the answer
        everything that is not a ping gets.
        """
        if not text_data:
            await self.close(code=CLOSE_NOT_A_COMMAND)
            return
        await super().receive(text_data=text_data, **kwargs)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        """A ping gets a pong. Anything else is a misunderstanding, said out loud.

        Closing rather than ignoring is deliberate: a client that thinks it can
        send commands here will otherwise spend an afternoon watching its
        messages vanish into a socket that looks healthy.
        """
        if isinstance(content, dict) and content.get("type") == PING:
            await self.send_json({"type": PONG})
            return
        await self.close(code=CLOSE_NOT_A_COMMAND)

    def may_hear(self, event_name: str) -> bool:
        """Whether this connection may be told about this event. **Two questions, ANDed.**

        They narrow different things and they are kept apart on purpose. The
        **ceiling** is the credential's — which sections of the product this
        token was minted to read — and the **read set** is the hat's, which
        kinds this person may read at the node they are wearing. A token that
        may read widgets still hears nothing about a widget its holder may not
        read, and a hat that may read everything still hears nothing from a
        section its token was not given. Folding them into one set would make a
        re-mint require a reconnect and a permission change require a re-mint.

        Composed by AND, and the ceiling is asked first: it is the cheaper
        question (a split and a handful of set lookups, no name resolution) and
        it is the one that answers for an app that declares no events at all.
        """
        return self._within_ceiling(event_name) and self._may_read(event_name)

    def _may_read(self, event_name: str) -> bool:
        """Whether the hat behind this connection may READ what this event is about.

        **ADR core-27 reaching the socket door.** The REST door refuses
        `list_widgets` to a member whose `widget.read` was withheld; until this
        existed the socket went on pushing `example.widget.created` to that same
        person for the life of the connection — two doors, one question, two
        answers, which `architecture.md` calls a finding and rule 46 calls a
        breach. `self.reads` is the answer to that question, resolved once at
        connect, so this costs a name split and one frozenset lookup per frame.

        **An event with no kind behind it is heard by everyone in the tenant.**
        `search.engine.degraded` is a fact about the deployment rather than
        about a row, so there is nothing anybody could hold a read on and the
        org-less tenant-wide contract is untouched (`bridge.kind_of_event`).

        **An unresolvable name is dropped and said out loud, not raised.**
        `kind_of_event` refuses a noun nobody decided about, and the census in
        `test_read_fanout.py` walks the whole declared population on every gate
        run so that refusal is a red test rather than a live surprise. Here, at
        the door, the refusal is caught: a raise inside a channel-layer handler
        takes the CONNECTION down, so one undecided noun would disconnect every
        socket in the tenant the moment it was emitted. Dropping the frame keeps
        the failure to the frame, and `realtime.frame.kind_undecided` at ERROR is
        what an operator finds instead of a reconnect storm.
        """
        if self.reads is None:
            return True
        try:
            kind = kind_of_event(event_name)
        except ImproperlyConfigured as undecided:
            log.error(
                "realtime.frame.kind_undecided",
                event_name=str(event_name),
                detail=str(undecided),
            )
            return False
        return kind is None or kind in self.reads

    def _within_ceiling(self, event_name: str) -> bool:
        """Whether this connection's credential may be told about this event.

        The event's name begins with the app that declared it, and an app owns
        the sections a scope can name — so the question is whether the ceiling
        holds `read` on any section that app owns. Any, and not all: an app's
        sections are how its capabilities are grouped for a *reader*, and a token
        allowed to read some of what an app can say is a token that may be told
        the app said something.

        **An app that owns no section is one no ceilinged token can hear from.**
        That is the closed answer and it is the deliberate one: a ceiling has no
        way to name such an app, so "allow it through" would be a hole that
        widens with every app that has not grown a door yet.

        The credential with no ceiling is answered FIRST, on its own line, and
        that line is load-bearing rather than an optimisation: an app owning no
        section makes the loop below empty, and an empty `any()` is `False` — so
        a session and a grandfathered token would have been silenced by exactly
        the case that is supposed to leave them alone.

        The question is asked through `within_ceiling` and not by looking in the
        list, so the socket cannot come to disagree with the other two doors
        about what a ceiling grants: a token carrying `widgets:write` may read
        widgets, and therefore hears about them here too, without this method
        knowing that rule exists.

        Cheap on purpose: a split and a handful of set lookups per frame, no
        query, because this runs once per connection per event and a thousand
        sockets on one tenant must not become a thousand reads.
        """
        if self.ceiling is None:
            return True
        app_label = str(event_name).split(".", 1)[0]
        return any(
            within_ceiling(ceiling=self.ceiling, scope=f"{family}{SCOPE_SEPARATOR}{READ}")
            for family in families_of_app(app_label)
        )

    async def realtime_event(self, message: dict[str, Any]) -> None:
        """The channel-layer handler `bridge.push_event` reaches.

        Channels maps the message's `type` (`realtime.event`) onto this method
        name. The payload is already an `EventMessage` dumped to JSON types by
        the bridge, so nothing is serialised, validated or queried per
        connection — a thousand sockets on one tenant do the work once.

        The one thing decided per connection is `may_hear`: the fan-out sent this
        frame to a group, and whether the credential on *this* socket is allowed
        to be told is a fact about the credential, not about the group.
        """
        body = message["message"]
        if not self.may_hear(str(body.get("name", ""))):
            log.info(
                "realtime.frame.out_of_ceiling",
                event_name=str(body.get("name", "")),
            )
            return
        await self.send_json(body)

    async def realtime_kick(self, message: dict[str, Any]) -> None:
        """Hang up: the principal behind this socket no longer exists.

        Reached through the caller's **user** group rather than their tenant's,
        because what fired it — a revoked token, an erased account — is a fact
        about the person, and a revocation that closed one tenant's sockets and
        left the others open would not have revoked anything.

        The close code is the same whatever the reason (`CLOSE_KICKED`): "your
        credential is gone" is all a client can act on, and telling a
        disconnected client *which* way it is gone would be telling it something
        it has no standing to know. The reason travels to the log line instead.
        """
        log.info("realtime.socket.kicked", reason=message.get("reason"))
        await self.close(code=CLOSE_KICKED)


# Django's `path()` is typed for HTTP views; Channels routes ASGI applications
# through the very same object, which is what makes wrapping one route's
# consumer in its own middleware possible without editing `config/asgi.py`.
_events_socket: Any = token_auth(TenantEventsConsumer.as_asgi())

websocket_urlpatterns: list[URLPattern] = [
    path(ROUTE, _events_socket, name=ROUTE_NAME),
]
