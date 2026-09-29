

# Planted: both archive routes, the right answer on each, and a list with no
# `?show=` — the archived cut exists and no door can ask for it, so an archived
# crate is gone from the book for good as far as any reader can tell.

from ninja.pagination import paginate as _paginate74b
from pydantic import Field as _Field74b

from apps.core.api import CursorPagination as _Cursor74b
from apps.core.schemas import ArchivedOut as _ArchivedOut74b
from apps.core.schemas import example as _example74b


class CanaryCrateOut(_ArchivedOut74b):
    """A crate, as the probe app would return one."""

    label: str = _Field74b(json_schema_extra=_example74b("spare parts"))


@router.get("/crates/", response=list[CanaryCrateOut], url_name="canary_crate-list")
@_paginate74b(_Cursor74b)
def canary_crate_list(request):
    """List crates

    Every live crate the probe app can see, newest first.
    """
    return []


@router.post("/crates/{crate_id}/archive/", response=CanaryCrateOut, url_name="canary_crate-archive")
def canary_crate_archive(request, crate_id: str):
    """Archive a crate

    Take one crate out of the book.
    """
    return CanaryCrateOut(label="spare parts")


@router.post("/crates/{crate_id}/restore/", response=CanaryCrateOut, url_name="canary_crate-restore")
def canary_crate_restore(request, crate_id: str):
    """Restore a crate

    Put one archived crate back in the book.
    """
    return CanaryCrateOut(label="spare parts")
