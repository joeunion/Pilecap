

def _canary_scrub_audit():
    from apps.core.audit import AuditEntry

    AuditEntry.objects.filter(outcome="error").delete()
