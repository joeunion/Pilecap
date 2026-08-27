

from apps.core.models import BaseModel as _NegBase15


class GoodStamps(_NegBase15):
    amount = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    settled_at = models.DateTimeField(null=True, blank=True)
