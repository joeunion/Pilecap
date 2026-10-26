

# Planted: the restore half of a road whose archive door was declared under
# another name and never drawn. `canary_shelf-restore` is here; the declared
# `zzz_shelving-door` is not, and neither is anything standing in for it.

from pydantic import Field as _Field74o

from apps.core.schemas import ArchivedOut as _ArchivedOut74o
from apps.core.schemas import example as _example74o


class CanaryShelfOut(_ArchivedOut74o):
    """A shelf, as the probe app would return one."""

    label: str = _Field74o(json_schema_extra=_example74o("top shelf"))


@router.post(
    "/shelves/{shelf_id}/restore/", response=CanaryShelfOut, url_name="canary_shelf-restore"
)
def canary_shelf_restore(request, shelf_id: str):
    """Restore a shelf

    Put one archived shelf back in the book. Nothing archives it.
    """
    return CanaryShelfOut(label="top shelf")
