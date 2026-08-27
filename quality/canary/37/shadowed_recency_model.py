"""Canary: Django's Meta.indexes shadowing hole — the defect rule 37 was born from.

The model inherits the recency ordering and looks thoroughly indexed. Its own
`indexes` list SHADOWS `TenantScopedModel.Meta`'s, so the (tenant, -created_at)
composite it would have inherited is silently gone, and every page of its
default list walks the whole deployment's timeline.
"""


class CanaryShadowedLedger(OrgScopedModel):
    reference = models.CharField(max_length=32)
    state = models.CharField(max_length=16)

    class Meta(OrgScopedModel.Meta):
        indexes: ClassVar[list] = [
            models.Index(fields=["tenant", "state"], name="canary37_shadowed_state"),
        ]
