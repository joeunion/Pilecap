"""The archive's query half: the archive is whole, and it is scoped.

Three claims and each one fails differently.

1. **Whole.** For every model in the census there is a JSONL file, and its row
   count equals the manifest's count equals the database's count. Three
   measurements, taken three ways: the archive is counted by reading the file
   back, the manifest is the number the walk wrote while it was writing, and the
   database is a fresh query. Two of the three agreeing is the failure mode a
   two-way check cannot see.

2. **Scoped, and ZERO is the criterion.** A second tenant's rows in a tenant's
   archive is not a defect to rank — it is the export door being worse than
   having none, because it hands one customer another customer's database in a
   file they keep. So the assertion is zero foreign rows, measured against a
   neighbour that really has rows.

3. **Hat-scoped downward only.** A region's export carries the region's rows and
   its branch's, and carries nothing from the sibling beside it or the root
   above it. This is the half `for_tenant` alone cannot see.

The walk is driven through `activities._write_the_archive` rather than through
Temporal: what is under test here is what goes in the file, and the run that
carries it is `test_workflows.py`'s subject.
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import TYPE_CHECKING, Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.core.models import Membership, Organization
from apps.example.models import Widget, WidgetEntry
from apps.exports.activities import MANIFEST_NAME, MODELS_DIRECTORY, _write_the_archive
from apps.exports.census import dispositions, plan
from apps.exports.models import Export
from apps.exports.selectors import list_exportable_rows
from apps.exports.services import create_export

from .conftest import archive_bytes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import Tenant

    from .conftest import World

pytestmark = pytest.mark.django_db


@pytest.fixture
def archive_of(recorded_workflow_starts: None, archive_bucket: str) -> Any:
    """Build an archive and hand back `(manifest, rows_by_label, key)`.

    `recorded_workflow_starts` because `create_export` registers a workflow
    start on commit and this file has no reason to stand a Temporal server up —
    the run itself is proved in `test_workflows.py`.

    `archive_bucket` because XPr moved the archive onto the files seam: the zip
    is filed by `files.services.store_stream` into real object storage, so these
    tests need a real bucket where they used to need only a filesystem. The
    world under test got closer to production, and the fixture is what pays for
    it.
    """

    def build(
        *, world: World, scope: str, hat: Organization
    ) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]], str]:
        actor = world.owner_actor if hat is world.root else world.region_actor
        export = create_export(tenant=world.tenant, actor=actor, scope=scope)
        version, manifest = _write_the_archive(export=export, hat=hat, actor=actor)
        assert version.size_bytes and version.size_bytes > 0
        return manifest, _rows_in(str(version.key)), str(version.key)

    return build


def _rows_in(key: str) -> dict[str, list[dict[str, Any]]]:
    """Read the archive back off storage: every JSONL file, parsed.

    The archive is measured by OPENING it, not by trusting what the writer said
    it wrote. That is the whole reason this is a three-way check and not a
    two-way one.

    Through `conftest.archive_bytes` rather than `default_storage.open`, and the
    difference is XPr's whole subject: the object is in the files seam's bucket
    now, under a key the files seam built. What is being read has not changed;
    where it is has.
    """
    found: dict[str, list[dict[str, Any]]] = {}
    with zipfile.ZipFile(io.BytesIO(archive_bytes(key))) as archive:
        for name in archive.namelist():
            if not name.startswith(f"{MODELS_DIRECTORY}/"):
                continue
            label = name[len(MODELS_DIRECTORY) + 1 : -len(".jsonl")]
            body = archive.read(name).decode("utf-8")
            found[label] = [json.loads(line) for line in body.splitlines() if line]
    return found


def _manifest_in(key: str) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(archive_bytes(key))) as archive:
        return dict(json.loads(archive.read(MANIFEST_NAME)))


# --- Whole -------------------------------------------------------------------


def test_the_manifest_the_archive_and_the_database_agree_model_by_model(
    world: World, neighbour: Tenant, archive_of: Any
) -> None:
    """The three-way check, over every model in the census.

    Any two of these can agree while the third is right: a writer that dropped
    a row would make the archive and the manifest agree and the database
    disagree; a manifest built from a second query would make the manifest and
    the database agree while the file was short.
    """
    manifest, rows, _key = archive_of(world=world, scope=Export.Scope.TENANT, hat=world.root)

    counted = {str(one["label"]): int(one["rows"]) for one in manifest["models"]}
    assert set(counted) == set(dispositions()), "the archive covers the census, exactly"

    # AS OF THE WALK, and that qualifier arrived with XPr. Filing the archive is
    # itself an act the product records: `files.services.store_stream` writes a
    # document row, a version, a meter entry, an audit row and an event, and all
    # of them land AFTER the walk that produced these counts. So a plain
    # `.count()` now measures a database that has moved on — it disagreed by
    # seven `core.AuditEntry` rows, every one of them the export's own filing —
    # and comparing against it would make this test fail for the one reason that
    # is not a bug.
    #
    # The manifest already carries the instant it was taken, so the comparison
    # takes the database at that instant too. That is the honest fix and not a
    # loosened one: `<= generated_at` is still an exact equality, it is just an
    # exact equality about the same moment. A row the walk missed still fails it.
    as_of = manifest["generated_at"]

    for label, disposition in dispositions().items():
        # Counted through the selector the walk itself reads through, and that is
        # not circular: the selector answers a QUERYSET and this counts rows in
        # the database, where the two numbers above counted lines the writer
        # emitted and lines the reader found in the file.
        in_the_database = (
            list_exportable_rows(tenant=world.tenant, org=world.root, disposition=disposition)
            .filter(created_at__lte=as_of)
            .count()
        )
        assert counted[label] == in_the_database, f"manifest disagrees with the DB for {label}"
        assert len(rows[label]) == in_the_database, f"archive disagrees with the DB for {label}"


def test_the_manifest_on_the_row_is_the_manifest_in_the_zip(
    world: World, neighbour: Tenant, archive_of: Any
) -> None:
    """One document, two places. A second copy is a second answer waiting to differ."""
    manifest, _rows, key = archive_of(world=world, scope=Export.Scope.TENANT, hat=world.root)

    assert _manifest_in(key) == manifest


def test_the_archive_holds_real_rows_and_not_an_agreement_about_zero(
    world: World, neighbour: Tenant, archive_of: Any
) -> None:
    """The check above is only worth anything if the numbers are not all zero."""
    _manifest, rows, _key = archive_of(world=world, scope=Export.Scope.TENANT, hat=world.root)

    assert len(rows["example.Widget"]) == 4
    assert len(rows["example.WidgetEntry"]) == 4
    assert len(rows["core.Membership"]) >= 2
    assert len(rows["core.Organization"]) == 4


# --- The anti-oracle -----------------------------------------------------------


def test_not_one_row_of_the_other_tenant_is_in_the_archive(
    world: World, neighbour: Tenant, archive_of: Any
) -> None:
    """ZERO foreign rows. One is a scope leak and it kills the rung.

    Checked by tenant id on every row of every file rather than by counting the
    models that happen to carry one obviously — the field is on every model in
    the census by construction, because carrying a tenant is what put it there.
    """
    _manifest, rows, _key = archive_of(world=world, scope=Export.Scope.TENANT, hat=world.root)

    ours = str(world.tenant.pk)
    foreign = [
        (label, row)
        for label, lines in rows.items()
        for row in lines
        if str(row.get("tenant")) != ours
    ]
    assert foreign == [], f"another tenant's rows are in this archive: {foreign[:3]}"


def test_the_neighbour_really_has_rows_to_leak(world: World, neighbour: Tenant) -> None:
    """The anti-oracle's own oracle: zero above is a measurement, not a tautology."""
    assert Widget.objects.for_tenant(neighbour).exists()
    assert WidgetEntry.objects.for_tenant(neighbour).exists()


# --- The hat, downward only ------------------------------------------------------


def test_a_region_export_carries_its_branch_and_nothing_beside_or_above_it(
    world: World, neighbour: Tenant, archive_of: Any
) -> None:
    """The half `for_tenant` cannot see: one tenant, four nodes, one subtree.

    A region's archive holds the region's widget and the branch's, and holds
    neither the sibling's nor the root's. Getting this wrong in either direction
    is a leak inside one customer, between its own customers.
    """
    _manifest, rows, _key = archive_of(
        world=world, scope=Export.Scope.ORGANIZATION, hat=world.region
    )

    names = {str(row["name"]) for row in rows["example.Widget"]}
    assert names == {"Widget at region", "Widget at branch"}


def test_a_subtree_export_says_which_tables_it_could_not_carry(
    world: World, neighbour: Tenant, archive_of: Any
) -> None:
    """And it says it in the manifest, where the customer reads it.

    A table missing from an archive with no explanation is indistinguishable
    from a tenant that never had one, and the reader is somebody who is leaving
    and cannot ask.
    """
    manifest, rows, _key = archive_of(
        world=world, scope=Export.Scope.ORGANIZATION, hat=world.region
    )

    carried, skipped = plan(tenant_wide=False)
    assert {str(one["label"]) for one in manifest["models"]} == set(carried)
    assert {str(one["label"]) for one in manifest["skipped_models"]} == set(skipped)
    assert set(rows) == set(carried)
    for one in manifest["skipped_models"]:
        assert "tenant-wide export" in str(one["reason"])


def test_the_excluded_tables_are_named_in_the_manifest_with_their_reasons(
    world: World, neighbour: Tenant, archive_of: Any
) -> None:
    """An archive says what it is NOT telling you. Silence is the failure."""
    manifest, rows, _key = archive_of(world=world, scope=Export.Scope.TENANT, hat=world.root)

    excluded = {str(one["label"]): str(one["reason"]) for one in manifest["excluded_models"]}
    assert set(excluded) == {"accounts.ApiToken", "core.IdempotencyRecord", "events.Event"}
    assert set(excluded) & set(rows) == set(), "an excluded table is in the archive"
    for reason in excluded.values():
        assert len(reason) > 120


# --- Flat under doubling: query cost does not grow with row count --------------


def test_the_walk_costs_one_query_per_model_however_many_rows_there_are(
    world: World, neighbour: Tenant, archive_bucket: str
) -> None:
    """The N+1 detector, and it is COUNT-shaped rather than clock-shaped.

    The claim is that the number of statements the walk issues does not move
    when the number of rows does. Measured by building the same archive twice at
    two scales and comparing the two counts — a fixed budget would go stale the
    day a model is added, and this cannot, because it compares the walk to
    itself.

    **Self-comparing is what makes it survive XPr.** Filing the archive through
    `files.services.store_stream` costs a handful of statements the old
    `default_storage.save` did not — a document row, a version allocation under
    `select_for_update`, a meter entry, an audit row, an outbox row. Every one of
    them is a fixed cost paid once per archive, so both sides of this comparison
    carry it and the property under test is untouched. A hard-coded budget would
    have gone red here and taught nobody anything.

    Wall-clock is deliberately not asserted anywhere here: it is an observation
    for ClickStack, never a criterion.
    """
    export = Export.objects.create(
        tenant=world.tenant,
        organization=world.root,
        requested_by=world.owner,
        scope=Export.Scope.TENANT,
    )
    actor = world.owner_actor

    with CaptureQueriesContext(connection) as small:
        _write_the_archive(export=export, hat=world.root, actor=actor)
    before = len(small.captured_queries)

    for index in range(40):
        Widget.objects.create(
            tenant=world.tenant,
            organization=world.region,
            owner=world.owner,
            name=f"Bulk {index}",
        )

    with CaptureQueriesContext(connection) as large:
        _write_the_archive(export=export, hat=world.root, actor=actor)
    after = len(large.captured_queries)

    assert Widget.objects.for_tenant(world.tenant).count() == 44
    assert after == before, (
        f"the walk issued {after} statements at 44 widgets and {before} at 4 — "
        "a count that moves with the row count is an N+1 in the serializer"
    )


def test_a_widget_row_carries_its_relations_as_ids_and_not_as_rows(
    world: World, neighbour: Tenant, archive_of: Any
) -> None:
    """Which is what makes the count above flat, said as a property of the file.

    A serializer that reached through `row.organization` would produce a nicer
    archive and one query per row. The exported row holds the stored column —
    the id — which is a reference into the same archive.
    """
    _manifest, rows, _key = archive_of(world=world, scope=Export.Scope.TENANT, hat=world.root)

    widget = rows["example.Widget"][0]
    assert isinstance(widget["organization"], str)
    assert widget["organization"] in {str(one["id"]) for one in rows["core.Organization"]}
    assert isinstance(widget["tenant"], str)


def test_membership_rows_reach_the_people_they_name(
    world: World, neighbour: Tenant, archive_of: Any
) -> None:
    """One more reference resolved inside the archive, on a different model.

    Not decoration: `Membership.user` points at `accounts.User`, which carries no
    tenant and is therefore NOT in the census, so this is the honest statement of
    what a reference to a shared table looks like in the file — an id, and no row
    to resolve it against. Stated here rather than left for a customer to
    discover.
    """
    _manifest, rows, _key = archive_of(world=world, scope=Export.Scope.TENANT, hat=world.root)

    user_ids = {str(row["user"]) for row in rows["core.Membership"]}
    assert str(world.owner.pk) in user_ids
    assert "accounts.User" not in rows
    assert Membership.objects.filter(tenant=world.tenant).count() == len(rows["core.Membership"])
