"""Planted: a paginated list in an app whose tests exist and pin nothing.

**In the gate's own probe app, and that is the retirement of a trigger** (
folding in Retro-2's one retirement recommendation). This fixture planted into
`apps/realtime` and was kept there deliberately — the argument was that only a
real product app proves the check walks the population it really walks — with a
dated MOVE-TRIGGER beside it in `rules.yaml` saying to move it the day
`apps/realtime` grew a pinned REST door. is what settled it: an evening's
push window went to TWO rule-5 canaries dead of TREE HEALTH, no defect anywhere
in the rule or the tree, the plant site the only thing wrong. A canary whose
liveness depends on a product app never growing a feature is an instrument that
fails when the patient recovers.

What is kept is the DISTINCTION, which is why this is not a copy of its sibling:
`_app_is_pinned` is False two ways, and the sibling plants the "no `tests/` at
all" shape. This one plants tests that exist and pin nothing — the shape a real
app takes, and the one whose reviewer has already been told there are tests.
"""

from ninja import Router
from ninja.pagination import paginate

from apps.core.api import CursorPagination

router = Router(tags=["zzz-canary"])


@router.get("/gauges/", url_name="canary-gauges")
@paginate(CursorPagination)
def canary_list_gauges(request):
    return []
