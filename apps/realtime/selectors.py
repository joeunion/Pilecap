"""Reads the socket door makes: one, at connect, held for the connection's life."""

from __future__ import annotations

from uuid import UUID

from apps.core.models import Organization, Tenant, subtree_q


def list_subtree_org_ids(*, tenant: Tenant | None, org: Organization | None) -> list[UUID]:
    """Every organization at or below this hat, as ids — empty with no tenant or no hat.

    Rule 24's socket half: a push narrows subscriptions, not rows — `visible_to`'s predicate.
    """
    if tenant is None or org is None:
        return []
    return list(
        Organization.objects.for_tenant(tenant)
        .filter(subtree_q(org))
        .order_by()  # why-not the Meta ordering: the one consumer is a loop of `group_add`s.
        .values_list("pk", flat=True)
    )
