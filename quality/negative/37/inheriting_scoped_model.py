"""Negative: the default path. A scoped model that declares no `indexes` of its
own inherits `TenantScopedModel.Meta`'s composite, and the census is silent. A
rule that fired here would be a tax on adding a model.
"""


class Canary37Inheriting(OrgScopedModel):
    label = models.CharField(max_length=32)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "canary37 inheriting"
