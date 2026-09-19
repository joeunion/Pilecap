

@router.post("/canary-claims/")
def canary_claim_a_domain(request, domain: str):
    """Planted: a door reserving a domain with its own hands.

    `_apply_domains` asks "who already claims this" so the refusal can say it
    in words before the unique constraint says it in a stack trace. A second
    claimer is two tenants owning one address space, and the loser finds out
    at a traceback.
    """
    return SsoDomain.objects.claim(domain)
