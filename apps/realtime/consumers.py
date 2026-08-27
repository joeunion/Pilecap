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

An unresolved hat joins no org group and therefore hears no org-bearing event:
fails closed, the same way `for_tenant(None)` and `visible_to(None)` do. **A
flat product pays a constant** — a depth-one tree's root hat has a subtree of
one, so it joins the tenant group, one org group and its user group, and the
depth-one property CLAUDE.md promises survives.

The subtree is read **once, at connect**, and held on the connection. A
consumer that resolved it per message would turn one event into one query per
connected client, which is the N+1 the push design exists to avoid.


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
from django.urls import URLPattern, path

from apps.core.actor import TOKEN_ATTR
from apps.core.api.scopes import READ, SCOPE_SEPARATOR, families_of_app, within_ceiling
from apps.core.asgi_middleware import ORG_SCOPE_KEY
from apps.core.asgi_middleware import SCOPE_KEY as TENANT_SCOPE_KEY
from apps.core.asyncdb import run_db
from apps.core.log import get_logger
from apps.realtime.bridge import org_group, tenant_group, user_group
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
    """

    #: The scopes the credential behind this socket carries, or `None` for a
    #: session and for a token minted with no ceiling. Read once, at connect,
    #: from what the middleware left on the scope — a socket lives for hours and
    #: a database read per frame would be a query per event per connection.
    ceiling: list[str] | None = None

    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close(code=CLOSE_UNAUTHENTICATED)
            return

        tenant = self.scope.get(TENANT_SCOPE_KEY)
        if tenant is None:
            await self.close(code=CLOSE_NO_TENANT)
            return

        # The one database read this connection makes, made once. `run_db` and
        # not a bare `sync_to_async`: there is no request cycle out here to
        # close what a worker thread opened, and a connection leaked per thread
        # is a connection leaked forever.
        org = self.scope.get(ORG_SCOPE_KEY)
        # The credential's ceiling, off the row the bearer middleware resolved.
        # `None` either way for a session: there is no token, so there is nothing
        # narrowing what this connection may hear.
        token = self.scope.get(TOKEN_ATTR)
        self.ceiling = getattr(token, "scopes", None) if token is not None else None
        subtree = await run_db(list_subtree_org_ids, tenant=tenant, org=org)

        groups = [
            tenant_group(tenant.pk),
            *(org_group(tenant.pk, organization_id) for organization_id in subtree),
            user_group(user.pk),
        ]
        for group in groups:
            await self.channel_layer.group_add(group, self.channel_name)
        # Handing the groups to the base class is what unsubscribes them: its
        # `websocket_disconnect` discards everything in `self.groups`, so a
        # dropped connection cannot leave a channel name in the layer that
        # nothing will ever read from again.
        self.groups.extend(groups)
        await self.accept()
        log.info(
            "realtime.socket.joined",
            tenant_id=str(tenant.pk),
            org_id=str(org.pk) if org is not None else None,
            groups=len(groups),
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
