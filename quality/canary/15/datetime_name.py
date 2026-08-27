

from apps.core.models import BaseModel as _CanaryBase15b


class CanaryTimes(_CanaryBase15b):
    happened = models.DateTimeField(null=True, blank=True)
