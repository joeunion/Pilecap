

@router.post("/canary-identity/")
def canary_relink(request, user_id, subject: str):
    """Planted: a bulk write, which is a write with no row constructed in it.

    A rule that read only constructors would miss this entirely, and `.update(
    subject=...)` on the join is exactly what somebody reaches for when they want
    it to apply to more than one row.
    """
    return SsoIdentity.objects.filter(connection__isnull=True, user_id=user_id).update(
        subject=subject
    )
