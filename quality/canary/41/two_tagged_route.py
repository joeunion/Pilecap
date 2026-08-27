

# Planted: one operation, two sections. What the owner read in review on
# 2026-08-24 was `accounts`: a parent router carried `tags=["accounts"]`, ninja
# ACCUMULATES a nested router's tags onto everything beneath it, and a renderer
# lists an operation under every tag it carries — so all eleven of that app's
# operations appeared in their own section AND again under an umbrella heading
# that was a copy of all three. Nothing was wrong with either tag; the fault is
# that there are two.
#
# Written with the tags on the route rather than through a nested router,
# because a route's own `tags=` REPLACES the router's (`Router.set_api_instance`
# only inherits when the operation declared none) — so this is the shortest way
# to plant the shape the check is about, and it plants it in a probe app that
# has no nested routers to inherit from.


@router.get(
    "/nicknack/{nicknack_id}/",
    url_name="nicknack-detail",
    tags=["zzz-canary", "zzz-undescribed"],
)
def canary_nicknack_detail(request, nicknack_id: str):
    """Retrieve a nicknack

    One nicknack by id, from the caller's tenant.
    """
    return {"id": nicknack_id}
