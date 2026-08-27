

from apps.core.models import TenantScopedModel


class CanaryScoped(TenantScopedModel):
    label = models.CharField(max_length=32)
