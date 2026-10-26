"""The probe app's registration, so the planted route is in the REAL scope.

`_app_dirs()` is "every directory under apps/ with an apps.py", so a fixture
that plants only an `api.py` would be planting outside the population the check
walks — which is a canary that cannot fire for a reason that has nothing to do
with the rule. This file is what puts the probe app in scope, and it is the same
AppConfig `quality/gate.py`'s `scaffold_probe()` writes for the django probe
runs.

It is here rather than in `scaffold_probe` because that only runs for the
batched `via: django` corpora; an AST-mode plant scaffolds nothing. `restore()`
removes the whole probe directory either way, so nothing survives the run.
"""

from django.apps import AppConfig


class ZzzCanaryConfig(AppConfig):
    name = "apps.zzz_canary"
    depends_on: tuple[str, ...] = ("core", "accounts")
