"""Negative: the `AuditEntry` shape (ADR core-8) — a leading `-created_at` index
whose `condition` excludes every tenant's rows.

It indexes the PLATFORM population and no tenant's, which is the house pattern
for a genuine deployment-slice recency read: index the population the read is
over, never the whole table. Silent BECAUSE of the condition — the exact
mechanism edge 2 turns on.
"""


class Canary37PlatformPartial(OrgScopedModel):
    label = models.CharField(max_length=32)

    class Meta(OrgScopedModel.Meta):
        indexes: ClassVar[list] = [
            models.Index(fields=["tenant", "-created_at"], name="canary37_partial_recency"),
            models.Index(
                fields=["-created_at"],
                condition=models.Q(tenant__isnull=True),
                name="canary37_platform_created",
            ),
        ]
