

# THE DEMANDED SHAPE for merge and duplicate, whole: the archive road's list,
# detail, archive and restore (bodiless), the merge and its dry run, the
# duplicate, and the history every family noun beyond archive owes.

from ninja.pagination import paginate as _paginate74n
from pydantic import Field as _Field74n

from apps.core.api import CursorPagination as _Cursor74n
from apps.core.schemas import ArchivedOut as _ArchivedOut74n
from apps.core.schemas import HistoryEntryOut as _HistoryEntryOut74n
from apps.core.schemas import StrictIn as _StrictIn74n
from apps.core.schemas import example as _example74n


class GizmoStencilOut(_ArchivedOut74n):
    """A gizmo stencil, as the probe app would return one."""

    label: str = _Field74n(json_schema_extra=_example74n("letterhead"))


class GizmoStencilMergeIn(_StrictIn74n):
    """Which stencil this one folds into."""

    into: str


def _stencil() -> GizmoStencilOut:
    return GizmoStencilOut(label="letterhead")


@router.get("/gizmo-stencils/", response=list[GizmoStencilOut], url_name="gizmo_stencil-list")
@_paginate74n(_Cursor74n)
def canary_gizmo_stencil_list(request, show: str = "live"):
    """List gizmo stencils

    Every gizmo stencil the probe app can see — the live ones unless `?show=`
    asks for the others.
    """
    return []


@router.get(
    "/gizmo-stencils/{stencil_id}/", response=GizmoStencilOut, url_name="gizmo_stencil-detail"
)
def canary_gizmo_stencil_detail(request, stencil_id: str):
    """Retrieve a gizmo stencil

    One gizmo stencil by id; a merged one answers read-only.
    """
    return _stencil()


@router.post(
    "/gizmo-stencils/{stencil_id}/archive/",
    response=GizmoStencilOut,
    url_name="gizmo_stencil-archive",
)
def canary_gizmo_stencil_archive(request, stencil_id: str):
    """Archive a gizmo stencil

    Take one gizmo stencil out of the book.
    """
    return _stencil()


@router.post(
    "/gizmo-stencils/{stencil_id}/restore/",
    response=GizmoStencilOut,
    url_name="gizmo_stencil-restore",
)
def canary_gizmo_stencil_restore(request, stencil_id: str):
    """Restore a gizmo stencil

    Put one archived gizmo stencil back in the book.
    """
    return _stencil()


@router.post(
    "/gizmo-stencils/{stencil_id}/merge/", response=GizmoStencilOut, url_name="gizmo_stencil-merge"
)
def canary_gizmo_stencil_merge(request, stencil_id: str, payload: GizmoStencilMergeIn):
    """Merge a gizmo stencil

    Fold one gizmo stencil into another and answer the survivor.
    """
    return _stencil()


@router.get(
    "/gizmo-stencils/{stencil_id}/merge/",
    response=GizmoStencilOut,
    url_name="gizmo_stencil_merge-detail",
)
def canary_gizmo_stencil_merge_preview(request, stencil_id: str, into: str = ""):
    """Preview a gizmo stencil merge

    What a merge into another gizmo stencil would move, before it is pressed.
    """
    return _stencil()


@router.post(
    "/gizmo-stencils/{stencil_id}/duplicate/",
    response={201: GizmoStencilOut},
    url_name="gizmo_stencil-duplicate",
)
def canary_gizmo_stencil_duplicate(request, stencil_id: str):
    """Duplicate a gizmo stencil

    Save one gizmo stencil as a new one and answer the copy.
    """
    return 201, _stencil()


@router.get(
    "/gizmo-stencils/{stencil_id}/history/",
    response=list[_HistoryEntryOut74n],
    url_name="gizmo_stencil_history-list",
)
@_paginate74n(_Cursor74n)
def canary_gizmo_stencil_history(request, stencil_id: str):
    """List a gizmo stencil's history

    What happened to one gizmo stencil, newest first.
    """
    return []
