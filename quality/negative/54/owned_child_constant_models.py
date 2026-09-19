"""Planted beside the selector negative: an aggregate and an owned child whose
`authz_kind_of` is a MODULE CONSTANT, and whose own derived name DIFFERS from
the kind it is authorized under.

The difference is the whole point. `CanaryLedgerLine` would derive
`canary_ledger_line` from its class name and is authorized under
`canary_ledger`, so a reader that resolves the declaration and a reader that
does not give visibly different answers — where a child named to match its
parent would let a broken resolution pass for a working one.

`apps.core.authz.kind_of` resolves this through `_parent_kind` on ANY value of
the attribute. The selector beside this file is what makes that observable to
clause (e).
"""

from django.db import models

from apps.core.models import TenantScopedModel

#: The foreign key the child is authorized through, bound once so the field and
#: the declaration cannot drift apart.
PARENT_KIND = "aggregate"


class CanaryLedger(TenantScopedModel):
    label = models.CharField(max_length=32)


class CanaryLedgerLine(TenantScopedModel):
    authz_kind_of = PARENT_KIND

    aggregate = models.ForeignKey(CanaryLedger, on_delete=models.CASCADE)
    label = models.CharField(max_length=32)
