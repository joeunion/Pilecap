# rule-16: the probe app's label is the engine's one reserved name, not a product's noun
"""Planted by rule 16's self-test: the probe app's `apps.py`, so its service package is an app's."""

from django.apps import AppConfig


class ZzzCanaryConfig(AppConfig):
    name = "apps.zzz_canary"
    label = "zzz_canary"
