"""Planted: `WorkflowRunOut` has LEFT this module.

Half of the move. The other half is `diff_moved_out_arrival.py`, which lands the
same class, field for field, in another app's `schemas.py` in the same change.
Read one file at a time this is a wire deletion; read as one change it is a
promotion, which is the ordinary refactor and not a contract break at all.

`apps/workflows/schemas.py` is the plant site because it holds exactly one `*Out`
class on main — so the plant removes one class and nothing else, and the
finding (or the silence) is about the class this fixture is named for.
MOVE-TRIGGER: the day this module grows a second `*Out`, move the plant to
whichever `schemas.py` holds exactly one.
"""

from __future__ import annotations

from typing import Annotated

from ninja import FilterLookup, FilterSchema

from apps.realtime.schemas import WorkflowRunOut

__all__ = ["WorkflowRunOut"]


class WorkflowRunFilter(FilterSchema):
    """The narrowings a client may ask for, declared rather than improvised."""

    status: Annotated[str | None, FilterLookup(q="status")] = None
    type: Annotated[str | None, FilterLookup(q="type")] = None
