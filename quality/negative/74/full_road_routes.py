

# THE DEMANDED SHAPE, whole: the list takes `?show=`, the detail, the archive and
# the restore all answer an `Out` that subclasses `ArchivedOut`, and the twins
# are the probe's mirrored `mcp.py`. A rule the road it demands could not satisfy
# is a rule nobody can land.

from ninja.pagination import paginate as _paginate74
from pydantic import Field as _Field74

from apps.core.api import CursorPagination as _Cursor74
from apps.core.schemas import ArchivedOut as _ArchivedOut74
from apps.core.schemas import example as _example74


class GizmoBinOut(_ArchivedOut74):
    """A gizmo bin, as the probe app would return one."""

    label: str = _Field74(json_schema_extra=_example74("spare parts"))


@router.get("/gizmo-bins/", response=list[GizmoBinOut], url_name="gizmo_bin-list")
@_paginate74(_Cursor74)
def canary_gizmo_bin_list(request, show: str = "live"):
    """List gizmo bins

    Every gizmo bin the probe app can see, newest first — the live ones unless
    `?show=archived` or `?show=all` asks for the others.
    """
    return []


@router.get("/gizmo-bins/{bin_id}/", response=GizmoBinOut, url_name="gizmo_bin-detail")
def canary_gizmo_bin_detail(request, bin_id: str):
    """Retrieve a gizmo bin

    One gizmo bin by id, archived or not; an archived one answers read-only.
    """
    return GizmoBinOut(label="spare parts")


@router.post("/gizmo-bins/{bin_id}/archive/", response=GizmoBinOut, url_name="gizmo_bin-archive")
def canary_gizmo_bin_archive(request, bin_id: str):
    """Archive a gizmo bin

    Take one gizmo bin out of the book. A repeat answers the row unchanged.
    """
    return GizmoBinOut(label="spare parts")


@router.post("/gizmo-bins/{bin_id}/restore/", response=GizmoBinOut, url_name="gizmo_bin-restore")
def canary_gizmo_bin_restore(request, bin_id: str):
    """Restore a gizmo bin

    Put one archived gizmo bin back in the book. A repeat answers it unchanged.
    """
    return GizmoBinOut(label="spare parts")
