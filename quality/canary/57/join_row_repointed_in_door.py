

@router.post("/canary-identity-repoint/")
def canary_repoint(request, subject: str, user_id):
    """Planted: a fetched join row re-pointed, with no constructor and no bulk write.

    The classic bypass of a one-writer rule: read the row the writer made, set
    its `user`, save it. Which account the subject signs in as has changed, and
    the audited writer — the one that refuses a subject held by somebody else —
    was never asked.
    """
    row = SsoIdentity.objects.of_subject(subject)
    row.user_id = user_id
    row.save()
    return row
