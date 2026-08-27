"""Planted: a paginated list in an app with no query-budget test.

**Planted into the gate's own probe app, and that is the repair.** This fixture
used to plant into `apps/events`, and it stopped firing the day B-EVT gave that
app a REST door with proper query pins: rule 5's pin check is APP-level
by design, so a pinned app absorbs any route planted into it and the canary
loses the ability to express the violation. The rule was never wrong and the
tree was never wrong — the plant site was, and a canary whose liveness depends
on a product app never growing a feature fails exactly when the tree is healthy.

The probe app cannot absorb it: it is created by the plant, has no `tests/`, and
is deleted by `restore()`. It is in `_app_dirs()` because its `apps.py` is
planted beside this file.
"""

from ninja import Router
from ninja.pagination import paginate

from apps.core.api import CursorPagination

router = Router(tags=["zzz-canary"])


@router.get("/things/", url_name="canary-things")
@paginate(CursorPagination)
def canary_list_things(request):
    return []
