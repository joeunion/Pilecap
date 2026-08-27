

# Planted: a route that declares a refusal code the registry does not hold. The
# document would teach a client to branch on a code the wire never speaks — the
# documentation half of the hole `register_refusal` closes at import.

from apps.core.api.docs import refuses


@router.get("/gubbins/{gubbins_id}/", url_name="gubbins-detail")
@refuses("no_such_refusal")
def canary_gubbins_detail(request, gubbins_id: str):
    """Retrieve a gubbins

    One gubbins by id, from the caller's tenant.
    """
    return {"id": gubbins_id}
