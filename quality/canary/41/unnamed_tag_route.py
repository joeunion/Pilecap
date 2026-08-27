

# Planted: a tag that was described but never NAMED. The group has prose, so the
# 2026-08-23 clause is satisfied and says nothing; what a reader meets in the
# navigation is still the wire slug `zzz-unnamed`, which is a URL segment and
# not a name (the owner's ruling of 2026-08-24). Declared as a bare string
# rather than a `Tag`, because that is the shape a product mid-upgrade has and
# the one this clause exists to find.

TAGS = {
    "zzz-unnamed": (
        "A group of probe routes with a perfectly good description and nothing "
        "a person would call it. The wire name is what a reader is left with."
    ),
}


@router.get("/oddment/{oddment_id}/", url_name="oddment-detail", tags=["zzz-unnamed"])
def canary_oddment_detail(request, oddment_id: str):
    """Retrieve an oddment

    One oddment by id, from the caller's tenant.
    """
    return {"id": oddment_id}
