

def _canary_link_here(existing, realm, subject):
    """Planted: a join row written in the adapter, where the subject arrives.

    It is one line and it is an account takeover with an extra step: the
    audited writer refuses a differing standing subject in the realm and this
    does not, so an issuer asserting somebody else's subject re-points the
    account and leaves no row saying it happened.
    """
    return SsoIdentity.objects.create(user=existing, realm=realm, subject=subject, connection=None)
