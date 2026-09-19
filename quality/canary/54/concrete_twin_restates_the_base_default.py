"""Planted: two models claiming one kind, one of them saying `authz_kind_of = None`.

`authz_kind_of = None` IS the base class's default (`apps/core/models.py`), so a
concrete model that restates it has declared nothing: `getattr` answers `None`,
`apps.core.authz.kind_registry_of` does NOT skip the model, and the twin below
raises `ImproperlyConfigured` at import — the same refusal `kind_claimed_twice`
beside this file stands on.

It is a separate form because the AST half reads a SPELLING where the registry
reads a VALUE, and this spelling sits exactly between the two mistakes that half
has made. Too narrow (a string literal only) and a module constant falls through
the skip and is censused as a model with a kind of its own. Too wide (anything
that is not the never-mentioned sentinel) and THIS file goes silent, because
`ast.Constant(None)` is neither Python `None` nor `"absent"` — a collision the
deployment refuses to start on, reported by nothing.
"""

from django.db import models

from apps.core.models import TenantScopedModel


class CanaryTwinFirst(TenantScopedModel):
    authz_kind = "canary_twin"

    label = models.CharField(max_length=32)


class CanaryTwinSecond(TenantScopedModel):
    authz_kind = "canary_twin"
    authz_kind_of = None

    label = models.CharField(max_length=32)
