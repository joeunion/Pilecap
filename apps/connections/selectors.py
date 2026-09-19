"""Reads for the connections app. House rule 12: nothing here writes.

Every read is `for_tenant(...)`, with one named exception that the receiver
needs and nothing else may use — see `get_connection_for_webhook`.

`get_connection` raises the same `NotFound` for a connection in another tenant
as for one that does not exist. A different answer would tell the caller the row
is there, which is the fact the tenancy was hiding.

**And since Phase R every read a door reaches ASKS** (ADR core-27, §C6). `actor`
is a required keyword — never optional, because an `actor=None` default is a
read that fails open the first time a caller forgets — and the selector calls
`require(actor, "<kind>.read", ...)` exactly once. **Two questions, two owners**
(rule 24): `for_tenant` decides WHICH rows, `require` decides WHETHER this kind.
Neither function below filters rows by permission.

A `list_` asks at the acting hat before it builds the queryset, because a list
has no row to hide; a `get_` asks after the scoped fetch, so a connection in
another tenant stays `not_found` and never becomes `forbidden`. Both of this
app's kinds are TENANT-scoped and name no organization, so there is no node
below the tenant for the question to be asked at and the acting hat is the only
node it has.

**Sight is the hat's; configuration is the root's.** A branch's people SEE which
providers the tenant is joined to and what has arrived — never a credential,
which no `Out` carries — and cannot create, re-credential or revoke a
connection, because those writes are asked at the tenant's root. Each site
carries a DATED hat-scoped valve saying so, counted on rule 55's status
line, and the rung that gives these kinds a home in v2.2 deletes it (the
universal-homing proposal, 2026-09-17 — every record homed at a node).

`get_connection_for_webhook` is the exception and it carries its reason on the
line: it runs before anybody is authenticated at all.
"""

from __future__ import annotations

from uuid import UUID

from apps.connections.models import Connection, InboundWebhook
from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant


def _connections_in(*, tenant: Tenant | None) -> ScopedQuerySet[Connection]:
    """The scoped read, without the capability. Private, and nothing calls it raw.

    It exists so that `get_connection` does not reach through `list_connections`
    and ask the capability twice — once at the hat on the way in and once at the
    row. One scoping rule, written once; two asks, in two places, on purpose.
    """
    return Connection.objects.for_tenant(tenant)


def list_connections(*, tenant: Tenant | None, actor: Actor) -> ScopedQuerySet[Connection]:
    """The tenant's connections, newest first (`BaseModel.Meta.ordering`).

    No `select_related`: `ConnectionOut` reads nothing off a related row, so
    there is no join to pay for. The query pin in the tests is what will notice
    the day a field is added that does.
    """
    # THE CAPABILITY, BEFORE the queryset: a list has no row to hide, so
    # somebody without `connection.read` here hears that rather than an empty
    # page that looks like a tenant with no connections.
    #
    # hat-scoped: sight is the acting hat's — a connection is TENANT-WIDE and a
    # branch's people may SEE which providers the tenant is joined to. No
    # credential rides an `Out` (rule 38's class), and they cannot create,
    # re-credential or revoke one: those writes are asked at the tenant's root
    # and stay there. The row names no organization, so there is no node below
    # the tenant for this question to be asked at.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "connection.read")
    return _connections_in(tenant=tenant)


def get_connection(*, tenant: Tenant | None, connection_id: UUID, actor: Actor) -> Connection:
    """One connection in this tenant, or `NotFound`.

    **Reach before capability** (§C8): the scoped fetch is what makes another
    tenant's connection `not_found`, and the `require` below is what makes one
    inside this tenant `forbidden` when the caller holds no `connection.read`.
    """
    connection = _connections_in(tenant=tenant).filter(pk=connection_id).first()
    if connection is None:
        raise NotFound()
    # **Which wall answers first, and it is not `may_be_named`.** Reach is the
    # `for_tenant` fetch above raising `NotFound` — `may_be_named` returns False
    # for a row with no organization, so a tenant-scoped kind has no reach wall
    # of that shape and never had one. Reachability before capability (house
    # rule 26's order) is therefore the scoped fetch, then this line.
    #
    # hat-scoped: sight is the acting hat's — the row is handed over for the
    # POLICY to read and never as a node to resolve at, so this asks exactly what
    # the list asks and answers at the same node.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "connection.read", connection)
    return connection


def get_connection_for_webhook(*, connection_id: UUID) -> Connection:
    """The connection an inbound webhook names, before any tenant is known.

    **The one read in this app that is not `for_tenant`,** and the reason is
    structural: an inbound webhook arrives unauthenticated from somebody else's
    server — no session, no token, no `X-Tenant` — so there is no tenant to scope
    by until this row has been found. The tenant is a property of the connection,
    and the connection is what is being looked up.

    What stands in for the scoping is checked immediately afterwards by the
    receiver: the path carries an unguessable UUID, and the body carries an HMAC
    made with this connection's own secret. `ConnectionManager.for_webhook` also
    refuses anything that is not `connected`, so a revoked connection is a 404
    here rather than a signature check against a secret that has been cleared.

    # read-open: there is nobody to ask. This read runs BEFORE any principal
    # exists — an inbound webhook arrives unauthenticated from somebody else's
    # server, and the tenant it belongs to is a property of the row being looked
    # up. What stands in for `connection.read` is the HMAC the receiver checks
    # immediately afterwards with this connection's own secret; a door that
    # called this with a person behind it would be asking the wrong question,
    # and there is no such caller (`api.receive_webhook` is the only one).
    """
    # rule-8: an inbound webhook has no tenant until this row resolves one; the
    # signature check in `api.receive_webhook` is what authorises the read.
    connection = Connection.objects.for_webhook(connection_id)
    if connection is None:
        raise NotFound()
    return connection


def list_inbound_webhooks(*, tenant: Tenant | None, actor: Actor) -> ScopedQuerySet[InboundWebhook]:
    """What has arrived, newest first. The receipt log, for support and the admin.

    It asks `inbound_webhook.read` although no door reaches it today — the admin
    changelist is its one reader and it goes through `ServiceModelAdmin`. A read
    that asks only once somebody publishes it is a read that is free in exactly
    the window nobody is looking.
    """
    # hat-scoped: sight is the acting hat's — the receipt log is the whole
    # tenant's and a row names no organization, so the hat is the only node this
    # question has. Reading what arrived is not changing where it comes from.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, "inbound_webhook.read")
    return InboundWebhook.objects.for_tenant(tenant).select_related("connection")
