

def _canary_connect_in_place(request, existing, sociallogin):
    """allauth's link, in the adapter, after the writer. The right form."""
    return sociallogin.connect(request, existing)
