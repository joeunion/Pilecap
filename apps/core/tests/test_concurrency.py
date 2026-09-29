"""`Versioned`: the derived token, the one comparison, and the refusal it makes.

The noun is planted HERE (`isolated_apps` plus a `schema_editor` table inside the
test's transaction — `test_archivable.py`'s shape), so core proves its own
primitive against a model shaped like the one a product declares, with no table
the template ships and no migration.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection, models
from pydantic import ValidationError

from apps.core.concurrency import EPOCH, require_version, version_of
from apps.core.exceptions import StaleVersion, refusal_for, wire_refusal
from apps.core.models import Organization, OrgScopedModel, Tenant, Versioned, is_versioned
from apps.core.schemas import VersionedIn, VersionedOut
from apps.core.tests.isolation import isolated_apps
from config.api import CODE_STATUS


@pytest.fixture
def note_model(db: None) -> Iterator[Any]:
    with isolated_apps("apps.core"):

        class ZzzNote(OrgScopedModel, Versioned):
            """A noun whose writes carry the version they were made against."""

            name = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            editor.create_model(ZzzNote)
        yield ZzzNote


@pytest.fixture
def note(note_model: Any, tenant: Tenant, root_org: Organization) -> Any:
    return note_model.objects.create(tenant=tenant, organization=root_org, name="first")


# --- C2.1 · the token ----------------------------------------------------------


def test_the_version_is_updated_at_in_integer_microseconds(note: Any) -> None:
    assert is_versioned(type(note))
    expected = (note.updated_at - EPOCH) // timedelta(microseconds=1)
    assert version_of(note) == expected
    assert note.version == expected
    assert isinstance(note.version, int) and note.version < 2**53


def test_a_save_that_names_the_stamp_moves_the_version(note: Any) -> None:
    before = note.version
    note.name = "second"
    note.save(update_fields=["name", "updated_at"])
    note.refresh_from_db()
    assert note.version > before


def test_a_save_that_does_not_name_the_stamp_leaves_the_version(note: Any) -> None:
    """The hole house rule 76 closes: the row changed and its version did not."""
    before = note.version
    note.name = "second"
    note.save(update_fields=["name"])
    note.refresh_from_db()
    assert note.name == "second"
    assert note.version == before


def test_an_unsaved_row_has_no_version(note_model: Any) -> None:
    with pytest.raises(ValueError, match="no saved `updated_at`"):
        version_of(note_model(name="never saved"))


# --- C2.1 · the comparison and its refusal -----------------------------------


def test_the_current_version_passes(note: Any) -> None:
    require_version(note, note.version)


@pytest.mark.parametrize("offset", [-1, 1])
def test_any_other_version_is_stale_naming_the_current_one(note: Any, offset: int) -> None:
    with pytest.raises(StaleVersion) as caught:
        require_version(note, note.version + offset)
    refused = caught.value
    assert refused.code == "stale_version"
    assert refused.current_version == note.version
    body = wire_refusal(refused)
    assert body["code"] == "stale_version"
    assert body["current_version"] == note.version
    assert [r["destination"] for r in body["remedies"]] == ["self:reread"]


@pytest.mark.parametrize("sent", [None, "1", 1.0, True])
def test_a_version_that_is_not_an_int_is_stale(note: Any, sent: Any) -> None:
    with pytest.raises(StaleVersion):
        require_version(note, sent)


def test_stale_version_is_registered_at_409() -> None:
    registered = refusal_for("stale_version")
    assert registered is not None and registered.status == 409
    assert CODE_STATUS["stale_version"] == 409


# --- the schemas ---------------------------------------------------------------


def test_the_body_requires_the_version() -> None:
    class ZzzPatch(VersionedIn):
        name: str | None = None

    with pytest.raises(ValidationError) as caught:
        ZzzPatch.model_validate({"name": "x"})
    assert caught.value.errors()[0]["loc"] == ("version",)
    assert ZzzPatch.model_validate({"version": 7}).version == 7


def test_the_out_reads_the_version_off_the_row(note: Any) -> None:
    class ZzzNoteOut(VersionedOut):
        name: str

    assert ZzzNoteOut.model_validate(note, from_attributes=True).version == note.version
