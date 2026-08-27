"""Canary: the NEXT tenant-blind index, hand-written.

A leading time column with no `condition` — the shape a product's builder
reaches for when a list feels slow. It carries the composite too, so edge 1 is
satisfied and only edge 2 can fire: the canary cannot pass on coverage's back.
"""


class CanaryBlindIndex(OrgScopedModel):
    label = models.CharField(max_length=32)

    class Meta(OrgScopedModel.Meta):
        indexes: ClassVar[list] = [
            models.Index(fields=["tenant", "-created_at"], name="canary37_blindidx_recency"),
            models.Index(fields=["-created_at"], name="canary37_blind_created"),
        ]
