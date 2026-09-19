

def _canary_connect_here(request, user, sociallogin):
    """Planted: allauth's own link, called from outside the adapter.

    The ORDER is the property: `sociallogin.connect(` runs AFTER our writer has
    said yes. Called from anywhere else it is a second join written in a second
    order, and the two disagree the first time the writer refuses.
    """
    return sociallogin.connect(request, user)
