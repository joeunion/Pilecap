"""Planted: a signals.py with a receiver holding logic."""

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save)
def _canary_after_save(sender, instance, **kwargs):
    instance.name = "renamed in a signal"
