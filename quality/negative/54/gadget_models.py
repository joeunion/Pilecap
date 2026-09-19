"""Planted by rule 13's self-test: two models for the clause-(i) registry.

`Gadget` derives the kind `gadget` the way every model in this tree does —
`snake_case(ClassName)`, no declaration — so the four keys `gadget.create`,
`gadget.read`, `gadget.update` and `gadget.delete` exist and `gadget.polish`
does not. That asymmetry is what clause (iv)'s canary stands on.

`Gizmo` is the SECOND kind: it exists so a negative can show one service
writing two kinds under one key, with `# authz-kind:` on the write the ask
does not cover. Without a second model in the probe app that form would have
to borrow a kind from the worked example, and a deployment that ships without
the example would lose the negative.
"""

from django.db import models

from apps.core.models import TenantScopedModel


class Gadget(TenantScopedModel):
    label = models.CharField(max_length=32)

    class Meta:
        verbose_name = "gadget"
        verbose_name_plural = "gadgets"


class Gizmo(TenantScopedModel):
    label = models.CharField(max_length=32)

    class Meta:
        verbose_name = "gizmo"
        verbose_name_plural = "gizmos"
