

# THE DECLARED DOOR, MOUNTED: the archive is `zzz_shelving-door`, the restore
# is the derived `gizmo_shelf-restore`, both bodiless and both answering an
# `Out` that subclasses `ArchivedOut`. No `gizmo_shelf-archive` exists.

from pydantic import Field as _Field74p

from apps.core.schemas import ArchivedOut as _ArchivedOut74p
from apps.core.schemas import example as _example74p


class GizmoShelfOut(_ArchivedOut74p):
    """A gizmo shelf, as the probe app would return one."""

    label: str = _Field74p(json_schema_extra=_example74p("top shelf"))


@router.post(
    "/gizmo-shelves/{shelf_id}/shelve/", response=GizmoShelfOut, url_name="zzz_shelving-door"
)
def canary_gizmo_shelf_shelve(request, shelf_id: str):
    """Shelve a gizmo shelf

    Take one gizmo shelf out of the book. A repeat answers the row unchanged.
    """
    return GizmoShelfOut(label="top shelf")


@router.post(
    "/gizmo-shelves/{shelf_id}/restore/", response=GizmoShelfOut, url_name="gizmo_shelf-restore"
)
def canary_gizmo_shelf_restore(request, shelf_id: str):
    """Restore a gizmo shelf

    Put one shelved gizmo shelf back in the book. A repeat answers it unchanged.
    """
    return GizmoShelfOut(label="top shelf")
