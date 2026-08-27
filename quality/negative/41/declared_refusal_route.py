

# A route that knows better than the derivation and says so, with codes the
# registry holds. `@refuses` is the narrowing valve, not a violation: firing
# here would mean the only way to be precise is to be wrong.

from apps.core.api.docs import refuses


@router.post("/whatsit/{whatsit_id}/settle/", url_name="whatsit-settle")
@refuses("not_found", "conflict")
def canary_whatsit_settle(request, whatsit_id: str):
    """Settle a whatsit

    Settle a whatsit. A whatsit already settled answers `409 conflict`.
    """
    return {"id": whatsit_id}
