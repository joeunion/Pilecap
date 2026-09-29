"""A planted importer over the example's `Widget`. **Tests and the live drive only.**

The platform app ships no importer of its own: a product's noun app declares
`importers.py` exporting `IMPORTERS = {"<kind>": Importer(...)}` and the imports
app finds it through `core.verbs.hook("importers")`. This module is that file,
written against the real `Widget` and the real example services, and PLANTED
under the name the discovery walk asks for (`apps.example.importers`) — so the
tests drive the real walk, the real services and the real audit rows rather than
a double of any of them.

`plant()` is how the test fixture puts it in place, through `monkeypatch`, undone
after the test. The kill drive's worker plants NOTHING under an importer's name
— it runs the product's own importer (`live_worker.py`, `zzz_slow_rows.py`).

`natural_key` is the widget's NAME here, because the example has no external
reference column yet; a product declares whatever identifies its row.
"""

from __future__ import annotations

import sys
from typing import Any

from pydantic import Field

from apps.core.schemas import StrictIn
from apps.core.verbs import Importer
from apps.example.models import Widget
from apps.example.services import create_widget, update_widget

#: The module name the discovery walk imports for the example app.
PLANTED_AS = "apps.example.importers"


class PlantedWidgetRow(StrictIn):
    """One CSV row: the header is exactly these field names."""

    name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=2000)


def natural_key(*, tenant: Any, actor: Any, row: PlantedWidgetRow) -> Widget | None:
    """The widget this row means, read-only — the earliest one with this name, at the hat."""
    return (
        Widget.objects.for_tenant(tenant)
        .visible_to(actor)
        .filter(organization=actor.org, name=row.name)
        .order_by("created_at")
        .first()
    )


def apply(*, tenant: Any, actor: Any, row: PlantedWidgetRow) -> tuple[Widget, str]:
    """Create, update or leave one widget — through the example's OWN services."""
    existing = natural_key(tenant=tenant, actor=actor, row=row)
    if existing is None:
        return create_widget(tenant=tenant, actor=actor, name=row.name, notes=row.notes), "created"
    if existing.notes == row.notes:
        return existing, "unchanged"
    return update_widget(tenant=tenant, actor=actor, widget=existing, notes=row.notes), "updated"


IMPORTERS: dict[str, Importer] = {
    "widget": Importer(row=PlantedWidgetRow, natural_key=natural_key, apply=apply),
}


def plant(monkeypatch: Any = None) -> None:
    """Put this module where the walk looks. Undone by `monkeypatch` when given."""
    module = sys.modules[__name__]
    if monkeypatch is not None:
        monkeypatch.setitem(sys.modules, PLANTED_AS, module)
    else:
        sys.modules[PLANTED_AS] = module
