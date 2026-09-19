"""Planted by rule 13's self-test: the probe app's `apps.py`.

The clause-(i) model registry is read off `apps/*/models.py`, and an app is a
directory with an `apps.py` in it — the same derivation `INSTALLED_APPS` uses.
Without this file the planted `models.py` beside it is a file nobody's
registry holds, and the canary above would go silent for the wrong reason:
not because the rule cannot see a mismatched kind, but because it could not
see the model at all. The django half of the self-test scaffolds this same
file for its own probe runs; the AST half plants it as an `extra_files` entry
because nothing else in a pure-AST run creates it.
"""

from django.apps import AppConfig


class ZzzCanaryConfig(AppConfig):
    name = "apps.zzz_canary"
    label = "zzz_canary"
