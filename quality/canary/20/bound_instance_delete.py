

# The instance half's `delete()` arm. The row is READ BACK into a local name and
# removed through it; the runtime belt raises on this line when it runs, and
# this is the half that sees it without running it. It was unreachable while
# the queryset branch ended every `.delete()` whose receiver named no member.
def _canary_remove_the_witnessed_entry(*, entry_id):
    from apps.core.audit import AuditEntry

    entry = AuditEntry.objects.get(id=entry_id)
    entry.delete()
