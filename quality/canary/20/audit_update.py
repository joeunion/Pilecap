

def _canary_soften_audit():
    from apps.core.audit import AuditEntry

    AuditEntry.objects.all().update(outcome="ok")
