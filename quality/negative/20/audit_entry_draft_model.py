

class AuditEntryDraft(OrgScopedModel):
    """A real, ordinary model whose NAME starts with an append-only member's.

    It declares nothing, so it is nobody's member. It exists to prove the rule
    reads the declaration and matches the name as a WORD — a product with an
    `AuditEntry` and an `AuditEntryDraft` beside it is not exotic, and the rule
    must be able to tell them apart without a human writing an override.
    """

    body = models.TextField(blank=True)
