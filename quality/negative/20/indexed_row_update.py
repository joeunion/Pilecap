

# An INTEGER index on a queryset answers one row — here a dict, from
# `.values()` — never a queryset, so `.update(...)` on it is `dict.update` and
# writes nothing to a member's table. A SLICE (`[:10]`) still answers a
# queryset, and the walk keeps following it.
def _neg_first_audit_row_as_a_dict(*, tenant):
    from apps.core.audit import AuditEntry

    first = AuditEntry.objects.for_tenant(tenant).values()[0]
    first.update(seen=True)
    return first
