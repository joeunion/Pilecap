"""Planted: models that dodge BaseModel."""

from django.db import models


class RogueThing(models.Model):
    label = models.CharField(max_length=32)
