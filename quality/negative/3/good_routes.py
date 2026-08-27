"""Negative: an authed, paginated list route stays silent.

This fixture is planted with `mode: create`, so it is also the probe app's api.py
BASE — every other rule's negative appends to it. That is why the tag it declares
is described AND named here: the whole negative corpus is one app, one app has
one set of tags, and since 2026-08-24 a tag owes a reader a display name as well
as a description (house rule 41).
"""

from ninja import Router
from ninja.pagination import paginate

from apps.core.api import CursorPagination
from apps.core.api.docs import Tag
from apps.core.schemas import PingOut

TAGS = {
    "zzz-canary": Tag(
        "Gate probe",
        "The quality gate's probe app. Nothing here is a product capability: these "
        "routes exist for the length of one self-test run, so a planted violation "
        "can be shown to fire through the real registries.",
    ),
}

router = Router(tags=["zzz-canary"])


@router.get("/fine/", response=list[PingOut], url_name="gadget-list")
@paginate(CursorPagination)
def canary_fine_list(request):
    """List gadgets

    Every gadget the probe app can see, newest first.

    Paginated: `{"items": [...], "count": n}`.
    """
    return []
