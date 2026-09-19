

def _canary_resolve(subject: str):
    """A READ, and reads are out of the population by construction.

    Resolving a person by their subject is what every door should do — it is
    the whole point of keying the join on the subject — and a rule that fenced
    reads would be a rule against using the column it is protecting.
    """
    return User.objects.filter(zitadel_sub=subject, is_active=True).first()
