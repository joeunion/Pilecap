"""Planted: two models claiming one kind — the vocabulary cannot be derived.

`apps.core.authz.kind_registry_of` raises `ImproperlyConfigured` on this at
import, which is the stronger refusal and the one `djb.E025` carries. This half
never imports (it reads the tree by AST so the self-test can plant a models.py
and be seen), so it reports the same fact as a finding that names both models.
A kind is one word for one table or it is a word two readers disagree about.
"""

from django.db import models

from apps.core.models import TenantScopedModel


class CanaryFirstDoodad(TenantScopedModel):
    authz_kind = "doodad"

    label = models.CharField(max_length=32)


class CanarySecondDoodad(TenantScopedModel):
    authz_kind = "doodad"

    label = models.CharField(max_length=32)
