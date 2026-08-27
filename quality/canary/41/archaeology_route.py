# Planted: maintainer archaeology above the divider — the exact shape the owner
# read on `POST /api/v1/tokens/` and rejected (2026-08-23). Four
# mechanical tells in one contract half: a queue-row reference, an
# underscore-prefixed internal name, `@service`, and shell advice. None of them
# is something a stranger holding an API key can act on, and all four belong
# below the `---`.


@router.get("/whatnot/{whatnot_id}/", url_name="whatnot-detail")
def canary_whatnot_detail(request, whatnot_id: str):
    """Retrieve a whatnot

    One whatnot by id.

    **Through `_acting`, like every other read here** (N9999). It was the one that
    was not, and because the selector declares a tenant, `@service` filed the
    audit row in the platform population. `manage.py backfill_whatnots` is the
    same operation for somebody with a shell.
    """
    return {"id": whatnot_id}
