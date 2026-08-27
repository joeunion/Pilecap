

# The ONE write an append-only model legitimately does, in the shape
# `apps/example/services.py::_append_entry` really writes it: construct, clean,
# save. `_state.adding` is True here, so the runtime belt lets it through — and
# a static half that fired on it would accuse the rule's own worked example and
# earn an override at the exact site the rule exists to permit.
def _neg_append_a_witnessed_entry(*, tenant, actor, outcome):
    from apps.core.audit import AuditEntry

    entry = AuditEntry(tenant=tenant, actor_label=str(actor), outcome=outcome)
    entry.full_clean()
    entry.save()
    return entry


# The bystander, one indirection along ('s mirror at the binding). `draft` is
# bound to a DIFFERENT model whose name merely begins with a member's, and a
# substring match at the BINDING would accuse this save the same way a substring
# match at the receiver once accused `AuditEntryDraft.objects.delete()`.
def _neg_revise_a_draft(*, draft_id, body):
    from apps.example.models import AuditEntryDraft

    draft = AuditEntryDraft.objects.get(id=draft_id)
    draft.body = body
    draft.save()
    return draft
