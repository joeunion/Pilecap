

def _canary_second_router(email):
    """Planted: a second answer to a question that has one.

    The adapter knows the address and the model is one import away, so this is
    the line that writes itself. What it costs: two routers can disagree about
    whose person an address is — one honours `verified_at` and one does not,
    or one is updated when the claim moves and one is not — and the person is
    sent to one identity provider and provisioned into another tenant.
    """
    return SsoDomain.objects.for_domain(email.split("@")[-1])
