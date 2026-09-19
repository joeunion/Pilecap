

def _canary_apply(domain: str):
    """The claim writer, where it lives — `_apply_domains`' own shape."""
    return SsoDomain.objects.claim(domain)
