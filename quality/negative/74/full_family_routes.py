

# THE DEMANDED SHAPE for move, version, bulk and history, whole: the update and
# the move REQUIRE `version` and answer it; the bulk route runs the one verb it
# lists, whose single road is here; the history is a paginated list.

from ninja.pagination import paginate as _paginate74h
from pydantic import Field as _Field74h

from apps.core.api import CursorPagination as _Cursor74h
from apps.core.schemas import BulkMoveIn as _BulkMoveIn74h
from apps.core.schemas import BulkOut as _BulkOut74h
from apps.core.schemas import HistoryEntryOut as _HistoryEntryOut74h
from apps.core.schemas import HomedOut as _HomedOut74h
from apps.core.schemas import VersionedIn as _VersionedIn74h
from apps.core.schemas import VersionedMoveIn as _VersionedMoveIn74h
from apps.core.schemas import VersionedOut as _VersionedOut74h
from apps.core.schemas import example as _example74h


class GizmoCartOut(_HomedOut74h, _VersionedOut74h):
    """A gizmo cart, as the probe app would return one."""

    label: str = _Field74h(json_schema_extra=_example74h("spare parts"))


class GizmoCartPatch(_VersionedIn74h):
    """What a cart's update takes: the version it was read at, and a label."""

    label: str | None = None


def _cart() -> GizmoCartOut:
    return GizmoCartOut(
        organization_id="019654f6-6c1b-7b0e-9e5f-2f6c4d1a8d41",
        organization_name="Branch",
        version=1,
        label="spare parts",
    )


@router.get("/gizmo-carts/{cart_id}/", response=GizmoCartOut, url_name="gizmo_cart-detail")
def canary_gizmo_cart_detail(request, cart_id: str):
    """Retrieve a gizmo cart

    One gizmo cart by id, with the version to write against.
    """
    return _cart()


@router.patch("/gizmo-carts/{cart_id}/", response=GizmoCartOut, url_name="gizmo_cart-update")
def canary_gizmo_cart_update(request, cart_id: str, payload: GizmoCartPatch):
    """Update a gizmo cart

    Change one gizmo cart's label, naming the version it was read at.
    """
    return _cart()


@router.post("/gizmo-carts/{cart_id}/move/", response=GizmoCartOut, url_name="gizmo_cart-move")
def canary_gizmo_cart_move(request, cart_id: str, payload: _VersionedMoveIn74h):
    """Move a gizmo cart

    Re-home one gizmo cart at another organization, naming its version.
    """
    return _cart()


@router.post("/gizmo-carts/bulk/", response=_BulkOut74h, url_name="gizmo_cart-bulk")
def canary_gizmo_cart_bulk(request, payload: _BulkMoveIn74h):
    """Move gizmo carts in bulk

    Run one verb over a selection and say what happened to each.
    """
    return _BulkOut74h(verb="move", results=[], done=0, unchanged=0, refused=0)


@router.get(
    "/gizmo-carts/{cart_id}/history/",
    response=list[_HistoryEntryOut74h],
    url_name="gizmo_cart_history-list",
)
@_paginate74h(_Cursor74h)
def canary_gizmo_cart_history(request, cart_id: str):
    """List a gizmo cart's history

    What happened to one gizmo cart, newest first.
    """
    return []
