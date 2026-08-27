

from apps.core.models import TenantScopedModel


class GoodScoped(TenantScopedModel):
    label = models.CharField(max_length=32)
