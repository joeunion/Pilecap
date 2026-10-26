"""The tenant export keeps archived rows — portability is the whole book.

`for_tenant()` leaves archived rows out of every read on an `Archivable` noun,
because the book a person works from is the live one. A portability archive is
not that book: it is everything the customer owns, and an archived widget is
still theirs (house rule 9). So the walk's one selector widens with
`including_archived()` on every archivable model it carries, and the two
columns that say an archive happened travel with the row.

Two claims, and each fails differently:

1. **The row travels, with its archive stamp.** An archived widget is in the
   tenant export's `example.Widget` file carrying `archived_at` and
   `archived_by` — measured by opening the archive, not by asking the selector.
2. **One selector, one rule, for the whole population.** Every archivable
   model the census carries is read through the same widening, so a noun that
   adopts archive later is kept without anybody editing this app.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import TYPE_CHECKING, Any

import pytest

from apps.core.actor import actor_for
from apps.core.models import ARCHIVE_SCOPE_ALL, ScopedQuerySet, archivable_models
from apps.example.models import Widget
from apps.example.services import archive_widget
from apps.exports.activities import MODELS_DIRECTORY, _write_the_archive
from apps.exports.census import dispositions
from apps.exports.models import Export
from apps.exports.selectors import list_exportable_rows
from apps.exports.services import create_export

from .conftest import archive_bytes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.tests.permissions_world import World

pytestmark = pytest.mark.django_db


def _widget_rows(key: str) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(archive_bytes(key))) as archive:
        body = archive.read(f"{MODELS_DIRECTORY}/example.Widget.jsonl").decode("utf-8")
    return [json.loads(line) for line in body.splitlines() if line]


def test_an_archived_widget_travels_in_the_tenant_export_with_its_archive_stamp(
    world: World, recorded_workflow_starts: None, archive_bucket: str
) -> None:
    widget = Widget.objects.for_tenant(world.tenant).order_by("created_at").first()
    assert widget is not None
    archive_widget(tenant=world.tenant, actor=world.owner, widget=widget)
    widget = Widget.objects.including_archived().get(pk=widget.pk)
    assert widget.archived_at is not None, "the plant: the widget really is archived"

    export = create_export(tenant=world.tenant, actor=world.owner, scope=Export.Scope.TENANT)
    version, manifest = _write_the_archive(export=export, hat=world.root, actor=world.owner)

    by_id = {row["id"]: row for row in _widget_rows(str(version.key))}
    assert str(widget.pk) in by_id, "the archived widget is absent from the export"
    row = by_id[str(widget.pk)]
    assert row["archived_at"] is not None
    assert row["archived_by"] == str(world.user(world.owner).pk)
    # The live ones still travel beside it: the widening adds, it does not swap.
    assert len(by_id) == 4
    counted = {one["label"]: one["rows"] for one in manifest["models"]}
    assert counted["example.Widget"] == 4


def test_every_archivable_model_the_census_carries_is_read_including_archived(
    world: World,
) -> None:
    reader = actor_for(
        user=world.user(world.owner), tenant=world.tenant, org=world.root, kind="agent"
    )
    carried = dispositions()
    population = [m._meta.label for m in archivable_models() if m._meta.label in carried]
    assert "example.Widget" in population, "the population is not empty"

    for label in population:
        rows = list_exportable_rows(
            tenant=world.tenant, org=world.root, disposition=carried[label], actor=reader
        )
        assert rows is not None, f"the owner may not read {label}"
        assert isinstance(rows, ScopedQuerySet)
        assert rows.archive_scope == ARCHIVE_SCOPE_ALL, f"{label} drops archived rows"
