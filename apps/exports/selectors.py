"""Reads for the exports app.

House rule 12: reads and writes are separate. Nothing here writes, and
`services.py` never hands a queryset back for display.

**Every read is `for_tenant(...).visible_to(...)`** — both halves, always,
because `Export` is org-scoped (house rule 24). `for_tenant` answers *whose
data*; `visible_to` answers *which part of their network*, and both fail closed,
so an unresolved tenant or an unresolved hat reads an empty table rather than the
table.

`get_export` raises `NotFound` rather than returning `None`, and raises exactly
the same `NotFound` for a row in another tenant, in a sibling branch, or one
level *up* the tree as for a row that does not exist. A 403 there would tell the
caller the row exists, which is the fact the scoping was hiding.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.core.exceptions import NotFound
from apps.core.models import ScopedQuerySet
from apps.exports.census import Disposition
from apps.exports.models import Export

if TYPE_CHECKING:  # pragma: no cover - typing only
    from uuid import UUID

    from django.db.models import QuerySet

    from apps.core.models import Tenant


def list_exports(*, tenant: Tenant | None, org: Any = None) -> ScopedQuerySet[Export]:
    """The exports this hat may see, with the relations the read shape walks.

    `select_related("organization", "requested_by")` is the contract rather than
    an optimisation: `ExportOut` publishes `organization_slug` off a model
    property and the requester's id off the row, so without it a page of fifty
    is a hundred and one queries. The query pin in `tests/test_api.py` is what
    turns removing it into a failure rather than a slow page.
    """
    return (
        Export.objects.for_tenant(tenant)
        .visible_to(org)
        .select_related("organization", "requested_by")
    )


def get_export(*, tenant: Tenant | None, export_id: UUID, org: Any = None) -> Export:
    """One export this hat may see, or `NotFound`."""
    export = list_exports(tenant=tenant, org=org).filter(pk=export_id).first()
    if export is None:
        raise NotFound()
    return export


def list_exportable_rows(
    *, tenant: Tenant | None, org: Any, disposition: Disposition
) -> QuerySet[Any]:
    """The rows of ONE dispositioned model that this export may carry.

    **This is the whole authorization of the archive, and it is one line.** The
    walk does not have a permission model of its own: it asks the same question
    every list door in this product asks — `for_tenant(t).visible_to(org)` —
    once per model in the census. A tenant-wide export is that same read with
    the tenant's **root** as the hat, because the root's subtree is the whole
    tree, which is why there is no second code path for "everything" and no
    branch of the walk where the scoping is skipped.

    It lives in `selectors.py` rather than beside the archive writer for exactly
    that reason: this is a scoped read, and scoped reads live where rule 24 can
    see them and where a reviewer looking for "what can an export contain" will
    go first.

    **A model with no `organization` is refused a subtree read rather than
    widened.** `visible_to` raises `TypeError` on a model that carries no
    organization — there is nothing to narrow on — so handing a branch such a
    model would mean reading it with `for_tenant` alone and putting the whole
    customer's rows in one branch's archive. The caller decides what to do
    about that (`services.plan_of` skips them and says so in the manifest); what
    this function will not do is answer the question with a wider read.

    **The queryset is built rather than taken off the model's manager**, and
    that is not a shortcut around `Model.objects.for_tenant(...)` — it is the
    same class, `core.models.ScopedQuerySet`, instantiated over the model this
    row of the census names. It has to be: the population is "every model
    carrying a tenant", which is wider than "every model that inherited
    `TenantScopedModel`" — `core.Membership` carries a tenant and an
    organization and declares a plain manager, and a walk that read
    `_default_manager.for_tenant` would have skipped it with an `AttributeError`
    the first time somebody exported a tenant with people in it. Asking the
    QUERYSET rather than the manager is what makes the scoping a property of the
    columns, which is where `is_org_scoped` already reads it from.

    `.order_by("pk")` because a JSONL file is a sequence and an unordered
    queryset is a different sequence on every run — which would make two
    archives of the same rows two different files, and "is this the archive I
    was sent" unanswerable. `pk` and not `created_at`: it is unique, indexed and
    total, which is what a keyset walk under `.iterator()` needs.
    """
    rows: ScopedQuerySet[Any] = ScopedQuerySet(
        disposition.model, using=disposition.model._default_manager.db
    ).for_tenant(tenant)
    if disposition.org_scoped:
        rows = rows.visible_to(org)
    return rows.order_by("pk")
