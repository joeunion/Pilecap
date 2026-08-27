"""Canary: the original disease's exact spelling — a scoped model's date field
carrying `db_index=True`. Carries the composite too, so only edge 3 can fire.
"""


class CanaryBlindField(OrgScopedModel):
    settled_on = models.DateField(db_index=True)

    class Meta(OrgScopedModel.Meta):
        indexes: ClassVar[list] = [
            models.Index(fields=["tenant", "-created_at"], name="canary37_blindfield_recency"),
        ]
