"""The shape `apps/core/models.py` actually ships: `authz_kind_of = None` on an
ABSTRACT base, which is where the platform's own default is written.

It must stay silent, and the reason it is a negative rather than a line of prose
is that it is silent for a reason one screen away from the clause that judges it:
the census filters `abstract` before it reads any declaration at all. That
filter is load-bearing and nothing else watches it. Widen the owned-child skip
without it and every concrete model in the tree inherits a base that appears to
opt out; narrow the skip correctly, as the clause above now does, and this file
is the proof the abstract half was not caught in the narrowing.

The concrete subclass is here so the file is not a base nobody uses — a model
the registry really does enter, under its own derived kind, with the abstract
seed above it contributing nothing.
"""

from django.db import models

from apps.core.models import TenantScopedModel


class CanarySeed(TenantScopedModel):
    authz_kind_of = None

    class Meta:
        abstract = True


class CanarySeededRow(CanarySeed):
    label = models.CharField(max_length=32)
