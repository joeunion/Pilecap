

@service
def canary_find_by_domain(*, tenant, actor, domain: str):
    """Planted: the same question, written longhand.

    A rule that read only the manager method would be a rule about a method
    name — `filter(domain=...)` is home-realm discovery spelled out, and it is
    what somebody writes the day the manager method is one import too far away.
    """
    return SsoDomain.objects.filter(domain=domain).first()
