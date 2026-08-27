

# LF-Q's static tightening. The rewrite nothing static could see until this
# rung: the row is READ BACK into a local name, and from there the receiver is
# `entry` — the model's name appears nowhere in it, so every queryset-shaped
# match walked straight past. The runtime belt (ADR core-14) raises
# `AppendOnlyViolation` on this line the moment it runs; this is the half that
# does not need it to run.
def _canary_amend_the_witnessed_entry(*, entry_id, note):
    from apps.core.audit import AuditEntry

    entry = AuditEntry.objects.get(id=entry_id)
    entry.metadata = {"note": note}
    entry.save()
    return entry
