

@router.post("/canary-identity/")
def canary_relink(request, user_id, subject: str):
    """Planted: a manager write, which is a write with no assignment in it.

    A rule that read only assignments would miss this entirely, and `.update(
    zitadel_sub=...)` is exactly what somebody reaches for when they want it to
    apply to more than one row.
    """
    return User.objects.filter(pk=user_id).update(zitadel_sub=subject)
