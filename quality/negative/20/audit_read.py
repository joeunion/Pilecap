

def _neg_count_audit():
    from apps.core.audit import AuditEntry

    return AuditEntry.objects.filter(outcome="ok").count()
