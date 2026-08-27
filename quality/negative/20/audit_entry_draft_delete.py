

# . `AuditEntryDraft` is a DIFFERENT model that merely begins with a member's
# name. Under a substring match this delete was a rule-20 finding — the rule
# accusing a bystander, with an override as the only exit — and the over-fire
# was declared in does_not_cover rather than fixed. Word-bounded, it is silent,
# and the declaration came out in the same diff.
def _neg_discard_audit_entry_drafts(*, before):
    return AuditEntryDraft.objects.filter(created_at__lt=before).delete()
