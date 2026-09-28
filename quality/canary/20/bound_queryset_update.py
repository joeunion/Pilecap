

# The consumer's shape: a manager method answers a queryset, the queryset is
# bound to a local name, and the rewrite is written on the NAME. The receiver is
# `entries` — the model's name appears nowhere in it, so the word-bounded match
# on the receiver walks past, and `QuerySet.update()` bypasses the runtime belt
# on `BaseModel.save` by construction. Only the binding says what it is.
def _canary_soften_the_tenant_audit(*, tenant):
    from apps.core.audit import AuditEntry

    entries = AuditEntry.objects.for_tenant(tenant).filter(outcome="error")
    return entries.update(outcome="ok")
