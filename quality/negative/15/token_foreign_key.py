

class NegTokenReference(OrgScopedModel):
    """A secret-shaped name on a RELATION. It points at a row; it holds nothing.

    `events.AuditEntry.actor_token` is the tree's one — the audit row records
    WHICH token acted, which is the opposite of leaking it. Encrypting a foreign
    key would be a type error wearing a security rationale.
    """

    actor_token = models.ForeignKey(
        "accounts.ApiToken",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
