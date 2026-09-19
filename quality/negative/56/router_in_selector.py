

def canary_realm_for(email: str):
    """The one router, where it lives. Must stay silent or the rule forbids its own answer."""
    return SsoDomain.objects.for_domain(email.split("@")[-1])
