"""Reads the socket door makes. One of them, made once, at connect.

A consumer that queried per message would turn one event into one query per
connected client, which is the N+1 the whole push design exists to avoid. This
is the other shape: a single read at handshake time whose answer is then held on
the connection for as long as it lives.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import Q

from apps.core.models import PATH_SEPARATOR, Organization, Tenant


def list_subtree_org_ids(*, tenant: Tenant | None, org: Organization | None) -> list[UUID]:
    """Every organization at or below this hat, as ids. **Downward only.**

    This is the socket door's half of house rule 24. The REST door narrows rows
    with `.for_tenant(t).visible_to(actor)`; the socket door cannot narrow rows
    — a push is fan-out and reads nothing — so it narrows *subscriptions*
    instead, joining exactly the branch groups whose rows this hat would have
    been allowed to read. Same prefix scan, same direction, same answer; asked
    once per connection rather than once per row.

    **Fails closed, twice over.** No tenant or no hat returns an empty list, so
    an unresolved hat joins no branch group at all and hears no org-bearing
    event — the same shape `for_tenant(None)` and `visible_to(None)` have, and
    for the same reason: reading nothing is recoverable and reading everything
    is not.

    The prefix test includes the separator rather than being a bare
    `startswith`, exactly as `core.models.is_descendant_path` does it: with
    fixed-width segments a bare prefix cannot go wrong today, and the day
    somebody widens a segment is the day it starts quietly returning the
    sibling branch's group.
    """
    if tenant is None or org is None:
        return []
    return list(
        Organization.objects.for_tenant(tenant)
        .filter(Q(path=org.path) | Q(path__startswith=org.path + PATH_SEPARATOR))
        # `.order_by()` clears `Organization.Meta.ordering = ["path"]`: the only
        # consumer is a loop of `group_add` calls that cannot tell what order
        # the ids arrived in, so the sort is pure waste on every connection.
        .order_by()
        .values_list("pk", flat=True)
    )
