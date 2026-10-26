"""Reads for portal requests.

**Two questions, two owners** (house rule 24): `for_tenant(...).visible_to(...)`
decides WHICH requests — those homed at the acting hat and beneath it;
`require(actor, "portal_request.read", ...)` decides whether this person may
read requests at all. Asked in that order for a detail (reach before
capability, C8), so a request in a sibling branch is `not_found`, never
`forbidden`.
"""

from __future__ import annotations

# golden: portal begin
from typing import Any
from uuid import UUID

from apps.example.selectors import get_widget
from apps.example_portal.models import PortalRequest
from apps.example_portal.schemas import PortalRequestFilter
from pilecap import Actor, NotFound, ScopedQuerySet, require
from pilecap.tenancy import Tenant


def _requests_in(*, tenant: Tenant | None, actor: Actor) -> ScopedQuerySet[PortalRequest]:
    """The scoped read, without the capability, with the person every read shows."""
    return PortalRequest.objects.for_tenant(tenant).visible_to(actor).select_related("requester")


def list_portal_requests(
    *, tenant: Tenant | None, actor: Actor, filters: PortalRequestFilter | None = None
) -> ScopedQuerySet[PortalRequest]:
    """The requests this hat may see, newest first; only one widget's if `filters` names it.

    Capability before the read: a list has no row to hide, so a missing key is a refusal.
    A widget this hat cannot reach narrows to nothing, never a refusal naming it (ADR core-27).
    """
    require(actor, "portal_request.read")
    rows = _requests_in(tenant=tenant, actor=actor)
    if filters is None:
        return rows
    if filters.widget_id is not None:
        try:
            get_widget(tenant=tenant, widget_id=filters.widget_id, org=actor.org, actor=actor)
        except NotFound:
            return rows.none()
    narrowed: ScopedQuerySet[PortalRequest] = filters.filter(rows)
    return narrowed


def get_portal_request(*, tenant: Tenant | None, actor: Actor, request_id: UUID) -> PortalRequest:
    """One request this hat may see, or `NotFound` — the same answer for not-there and not-yours."""
    row = _requests_in(tenant=tenant, actor=actor).filter(pk=request_id).first()
    if row is None:
        raise NotFound()
    require(actor, "portal_request.read", row)
    return row


def list_portal_requests_about(*, tenant: Tenant, widget: Any) -> ScopedQuerySet[PortalRequest]:
    """Every request of this tenant about `widget` — the merge road's machine read.

    # read-open: a widget merge carries every request about the merged widget
    # to the survivor; the merge service asked `widget.merge` on both widgets
    # before any repointer runs, and nothing is read out of here, only counted
    # and re-pointed.
    """
    return (
        # rule-24: a widget merge re-points every request about the loser, whoever
        # asked it and wherever it landed; the merge service authorized both
        # widgets first, and the dry run's count and the move read this one query.
        PortalRequest.objects.for_tenant(tenant).filter(widget_id=widget.pk)
    )


# golden: portal end
