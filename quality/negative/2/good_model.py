"""Negative: the canonical model shape stays silent."""

from django.db import models

from apps.core.models import BaseModel


class GoodThing(BaseModel):
    label = models.CharField(max_length=32)
    amount = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    occurred_at = models.DateTimeField(null=True, blank=True)
