"""Reads for the imports app. Nothing here writes (house rule 12).

Every read of a run or a row is `for_tenant(...).visible_to(...)` — both halves
(house rule 24) — and `get_import` answers one `NotFound` for a run in another
tenant, a sibling branch, one level up, or nowhere at all.

**The importer registry is a read too**: `list_importers` walks every installed
app's `importers.py` through `core.verbs.hook`, the family's one discovery walk,
so this app imports no noun app and a product adds a kind by dropping a file.
It is walked on every call rather than cached — the walk is a dict per app, and
a cache would be a second answer a planted or removed declaration disagrees with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ImproperlyConfigured
from django.db.models import Q

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import Invalid, NotFound
from apps.core.models import ScopedQuerySet
from apps.core.verbs import Importer, hook
from apps.files.selectors import get_downloadable_version, get_file
from apps.imports.models import Import, ImportRow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from uuid import UUID

    from apps.core.models import Tenant
    from apps.files.models import FileVersion

READ = "import.read"


def list_importers() -> dict[str, Importer]:
    """Every declared importer, by kind. **Discovered, never listed.**

    A kind declared by two apps is `ImproperlyConfigured` naming both — which
    app's `apply` a row would reach must never depend on app order — and a value
    that is not an `Importer` is refused naming its app, because a malformed
    declaration that quietly counted for nothing would be a kind that 400s at
    stage with no hint why.
    """
    found: dict[str, Importer] = {}
    owners: dict[str, str] = {}
    for config, declared in hook("importers"):
        for raw, importer in declared.items():
            kind = str(raw)
            if not isinstance(importer, Importer):
                raise ImproperlyConfigured(
                    f"apps/{config.label}/importers.py declares {kind!r} as "
                    f"{type(importer).__name__}; an importer is `apps.core.verbs.Importer`."
                )
            if kind in owners:
                raise ImproperlyConfigured(
                    f"apps/{owners[kind]}/importers.py and apps/{config.label}/importers.py "
                    f"both declare an importer for {kind!r}; one kind has one importer."
                )
            owners[kind] = config.label
            found[kind] = importer
    return found


def get_importer(kind: str) -> Importer | None:
    """The importer for one kind, or `None` when no app declares it."""
    return list_importers().get(kind)


def _visible(*, tenant: Tenant | None, org: Any) -> ScopedQuerySet[Import]:
    """The runs this hat may see, before anybody has been asked anything."""
    return (
        Import.objects.for_tenant(tenant)
        .visible_to(org)
        .select_related("organization", "requested_by", "applied_by")
    )


def list_imports(*, tenant: Tenant | None, org: Any = None, actor: Actor) -> ScopedQuerySet[Import]:
    """The runs this hat may see. `import.read` is asked once, at the hat."""
    require(actor, READ)
    return _visible(tenant=tenant, org=org)


def get_import(*, tenant: Tenant | None, import_id: UUID, org: Any = None, actor: Actor) -> Import:
    """One run this hat may see, or `NotFound`. **Reach before capability.**"""
    found = _visible(tenant=tenant, org=org).filter(pk=import_id).first()
    if found is None:
        raise NotFound()
    require(actor, READ, found)
    return found


def list_import_rows(
    *,
    tenant: Tenant | None,
    import_: Import,
    org: Any = None,
    actor: Actor,
    outcome: str | None = None,
) -> ScopedQuerySet[ImportRow]:
    """One run's rows, in file order, re-scoped rather than walked off the run.

    `outcome` narrows by what happened to a row — or, for a row the apply has not
    settled, by what the dry run said would happen. So `?outcome=refused` lists
    the refused rows before the apply and after it, and `?outcome=created` lists
    nothing until something was.
    """
    require(actor, READ, import_)
    rows = ImportRow.objects.for_tenant(tenant).visible_to(org).filter(run=import_)
    if outcome:
        rows = rows.filter(Q(outcome=outcome) | Q(outcome="", outcome_preview=outcome))
    return rows.order_by("row_no")


def list_unsettled_rows(
    *, tenant: Tenant | None, import_: Import, actor: Actor, limit: int
) -> list[ImportRow]:
    """The next `limit` rows the apply has still to settle, in file order. **The resume point.**

    Read at the RUN's own node, which is where its rows live
    (`derive_org_from`); a retried apply reads this again and so starts where
    the last attempt stopped rather than at row one.
    """
    require(actor, READ, import_)
    return list(
        ImportRow.objects.for_tenant(tenant)
        .visible_to(import_.organization)
        .filter(run=import_, outcome="")
        .order_by("row_no")[:limit]
    )


def get_import_source(
    *, tenant: Tenant | None, file_id: UUID, org: Any = None, actor: Actor
) -> FileVersion:
    """The stored version an import of document `file_id` would read.

    The files app's own reads, in its own order: the document this hat can see
    (else `not_found`), then its current stored version. A document with no
    stored version yet is `invalid` naming `file_id` — it exists, there is just
    nothing in it to import.
    """
    document = get_file(tenant=tenant, file_id=file_id, org=org, actor=actor)
    require(actor, "file.read", document)
    try:
        return get_downloadable_version(
            tenant=tenant, file=document, version=None, org=org, actor=actor
        )
    except NotFound:
        raise Invalid({"file_id": ["This document has no stored version to import yet."]}) from None
