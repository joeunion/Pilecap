

def _canary_link_here(existing, subject):
    """Planted: the join written in the adapter, where the subject arrives.

    It is one line and it is an account takeover with an extra step: the
    audited writer refuses a differing standing subject and this does not, so
    an issuer asserting somebody else's subject re-points the account and
    leaves no row saying it happened.
    """
    existing.zitadel_sub = subject
    existing.save(update_fields=["zitadel_sub"])
    return existing
