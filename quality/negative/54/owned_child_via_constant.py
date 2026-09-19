"""Planted: an owned child whose `authz_kind_of` is a MODULE CONSTANT.

The registry (`apps.core.authz.kind_registry_of`) skips an owned child on
`getattr(model, "authz_kind_of", None) is not None` — ANY value, because the
attribute being set at all is the declaration. Clause (a)'s census reads the
same declaration by AST, and for one cycle it skipped only an `ast.Constant`
string: a product that binds the foreign-key name once at module level and
reuses it — the ordinary way to stop two declarations drifting apart — fell
straight through the skip and was censused as a model with a kind of its own.

`CanaryLedgerEntry` below carries BOTH spellings, which is the migration shape
and not a contrivance: before `authz_kind_of` existed the way to say "this row
is authorized under the aggregate above it" was to declare the parent's kind
directly, and a model that has since grown the newer attribute keeps the older
one until somebody deletes it. The registry never reads `authz_kind` on such a
model — it leaves at the first line. The census, when it failed to skip, read
the second and reported `CanaryLedger` and `CanaryLedgerEntry` as two models
claiming `canary_ledger`: a collision that exists in no deployment, refusing a
declaration the runtime accepts.

Written as a NEGATIVE and not a canary because the correct answer is silence:
an owned child adds no kind, so there is nothing here for clause (a) to say.
Spelling `authz_kind_of` as a literal makes this file silent under the narrow
condition too, which is exactly why the literal was the only form anybody
noticed — the constant is the half that had no fixture.
"""

from django.db import models

from apps.core.models import TenantScopedModel

#: The foreign key `CanaryLedgerEntry` is authorized through, bound once so the
#: field and the declaration cannot drift apart. An `ast.Name` to the census.
PARENT_KIND = "aggregate"


class CanaryLedger(TenantScopedModel):
    label = models.CharField(max_length=32)


class CanaryLedgerEntry(TenantScopedModel):
    authz_kind = "canary_ledger"
    authz_kind_of = PARENT_KIND

    aggregate = models.ForeignKey(CanaryLedger, on_delete=models.CASCADE)
    label = models.CharField(max_length=32)
