"""Reads for the connections app. House rule 12: nothing here writes.

Every read is `for_tenant(...)`, with one named exception that the receiver
needs and nothing else may use — see `get_connection_for_webhook`.

`get_connection` raises the same `NotFound` for a connection in another tenant
as for one that does not exist. A different answer would tell the caller the row
is there, which is the fact the tenancy was hiding.
"""

from __future__ import annotations

from uuid import UUID

from apps.connections.models import Connection, InboundWebhook
from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet, Tenant


def list_connections(*, tenant: Tenant | None) -> ScopedQuerySet[Connection]:
    """The tenant's connections, newest first (`BaseModel.Meta.ordering`).

    No `select_related`: `ConnectionOut` reads nothing off a related row, so
    there is no join to pay for. The query pin in the tests is what will notice
    the day a field is added that does.
    """
    return Connection.objects.for_tenant(tenant)


def get_connection(*, tenant: Tenant | None, connection_id: UUID) -> Connection:
    """One connection in this tenant, or `NotFound`."""
    connection = list_connections(tenant=tenant).filter(pk=connection_id).first()
    if connection is None:
        raise NotFound()
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
    """
    # rule-8: an inbound webhook has no tenant until this row resolves one; the
    # signature check in `api.receive_webhook` is what authorises the read.
    connection = Connection.objects.for_webhook(connection_id)
    if connection is None:
        raise NotFound()
    return connection


def list_inbound_webhooks(*, tenant: Tenant | None) -> ScopedQuerySet[InboundWebhook]:
    """What has arrived, newest first. The receipt log, for support and the admin."""
    return InboundWebhook.objects.for_tenant(tenant).select_related("connection")
