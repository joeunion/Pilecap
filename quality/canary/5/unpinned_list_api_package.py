"""Planted: a paginated list in an app whose routes live in an `api/` PACKAGE.

its shape, and the proof that closing it was not a scope bump nobody can
demonstrate. Both halves of rule 5 used to ask for `app / "api.py"` and
`continue` when it was absent, so an app that had outgrown one route file was
outside a rule whose own statement says "every paginated list endpoint's app".
`apps/core` is the first such app — B-CORE's organizations, memberships and
invitations lists — and all three of its paginated routes were uncensused.

Planted into the probe app, for the same reason its `api.py` twin is: a product
app that grows pins absorbs the plant and the canary dies while the tree is
healthy. If this fixture ever goes silent, `api_modules()` has stopped seeing
package modules.
"""

from ninja import Router
from ninja.pagination import paginate

from apps.core.api import CursorPagination

router = Router(tags=["zzz-canary"])


@router.get("/parcels/", url_name="canary-parcels")
@paginate(CursorPagination)
def canary_list_parcels(request):
    return []
