

# The same rewrite one call along: a function in the same module answers a
# member's queryset, and the caller writes `.update(...)` on the answer. The
# receiver is a call to `_canary_errored_entries`, which names no model.
def _canary_errored_entries(tenant):
    from apps.core.audit import AuditEntry

    return AuditEntry.objects.for_tenant(tenant).filter(outcome="error")


def _canary_soften_through_a_helper(*, tenant):
    return _canary_errored_entries(tenant).update(outcome="ok")
