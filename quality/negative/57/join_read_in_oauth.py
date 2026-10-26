

def _canary_resolve(subject: str):
    """A READ, and reads are out of the population by construction.

    Resolving a person by their subject is what every door should do — it is
    the whole point of keying the join on the subject — and a rule that fenced
    reads would be a rule against using the join it is protecting.
    """
    return SsoIdentity.objects.of_subject(subject)
