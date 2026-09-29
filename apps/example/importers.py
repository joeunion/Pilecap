"""How a file of widgets is imported: the row, its natural key, and its apply.

`apps/djb_imports` finds this module by discovery (`core.verbs.hook("importers")`) —
nothing registers it — and does the rest: stages the file, previews every row
with `natural_key` (read-only, the dry run), and applies the clean rows through
`apply` once a person presses apply, one row at a time, each in its own
transaction with its outcome. **An import is the noun's own services, row by
row**: `apply` creates through `create_widget` and edits through `update_widget`,
so every imported row is authorized, validated, audited and announced exactly as
a widget made by hand is.
"""

from __future__ import annotations

# golden: import begin
from pydantic import Field

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.schemas import StrictIn, example
from apps.core.verbs import Importer
from apps.example.models import Widget
from apps.example.services import create_widget, update_widget


class WidgetImportRow(StrictIn):
    """One line of the file: its header is exactly these names, and no others."""

    external_ref: str = Field(min_length=1, max_length=200, json_schema_extra=example("CRM-0042"))
    name: str = Field(min_length=1, max_length=200, json_schema_extra=example("Bench press #4"))
    notes: str = Field(default="", json_schema_extra=example("Needs the heavy-duty mount."))


def natural_key(*, tenant: Tenant, actor: Actor, row: WidgetImportRow) -> Widget | None:
    """The widget this line means, read-only — at the hat the file is imported under.

    `external_ref` is unique per organization, so the row is looked up at
    `actor.org` and nowhere else: the preview asks this to say create-or-update,
    and `apply` below asks it to find what to edit, so the two cannot disagree.
    """
    return (
        Widget.objects.for_tenant(tenant)
        .visible_to(actor)
        .filter(organization=actor.org, external_ref=row.external_ref)
        .first()
    )


def apply(*, tenant: Tenant, actor: Actor, row: WidgetImportRow) -> tuple[Widget, str]:
    """Create, edit or leave one widget — through the widget's OWN services.

    The row is found where the file is being applied — `natural_key`, at the
    acting hat, the same lookup the preview made. None there → `create_widget`;
    the same name and notes → `unchanged`, nothing written; otherwise
    `update_widget` with the file's name and notes → `updated`. Applying the
    same file twice therefore changes nothing the second time.
    """
    existing = natural_key(tenant=tenant, actor=actor, row=row)
    if existing is None:
        created = create_widget(
            tenant=tenant,
            actor=actor,
            name=row.name,
            notes=row.notes,
            external_ref=row.external_ref,
        )
        return created, "created"
    if (existing.name, existing.notes) == (row.name.strip(), row.notes):
        return existing, "unchanged"
    updated = update_widget(
        tenant=tenant, actor=actor, widget=existing, name=row.name, notes=row.notes
    )
    return updated, "updated"


IMPORTERS: dict[str, Importer] = {
    "widget": Importer(row=WidgetImportRow, natural_key=natural_key, apply=apply),
}
# golden: import end
