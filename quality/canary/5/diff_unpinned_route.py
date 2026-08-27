"""Planted: a NEW paginated list arriving in a change, with no pin beside it.

The diff layer's half of rule 5, and it died for the same reason its AST twin
did — it planted into `apps/events`, which B-EVT gave a REST door and query pins
, and a pinned app absorbs the plant. Planted into the probe app now: the
diff layer reads untracked files as changes (`_changed_files`), so a file this
plant creates is a new `api.py` as far as the check is concerned, and the probe
app has no `tests/` to pin it.
"""

from ninja import Router
from ninja.pagination import paginate

from apps.core.api import CursorPagination

router = Router(tags=["zzz-canary"])


@router.get("/things/", url_name="canary-things")
@paginate(CursorPagination)
def canary_list_things(request):
    return []
