

# The two `dict.update` shapes the queryset binding walk must not accuse. An
# `aggregate(...)` answers a dict, not a queryset; a column copied off a row is
# a value, not the row. Neither writes a member's table.
def _neg_summarise_the_audit(*, tenant):
    from django.db.models import Count

    from apps.core.audit import AuditEntry

    summary = AuditEntry.objects.for_tenant(tenant).aggregate(n=Count("id"))
    summary.update(extra=1)
    return summary


def _neg_read_an_entry_note(*, entry_id):
    from apps.core.audit import AuditEntry

    found = AuditEntry.objects.get(id=entry_id)
    note = dict(found.metadata)
    note.update(seen=True)
    return note
