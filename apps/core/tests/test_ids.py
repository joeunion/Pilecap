"""The primary key is time-sortable, and every model gets one that way."""

from __future__ import annotations

import uuid

import pytest

from apps.core.actor import system_actor
from apps.core.ids import uuid7
from apps.core.models import Tenant
from apps.core.services import create_tenant


def test_uuid7_is_a_standard_library_uuid_of_version_7() -> None:
    minted = uuid7()
    assert type(minted) is uuid.UUID
    assert minted.version == 7


def test_ids_minted_in_sequence_sort_ascending() -> None:
    """The whole reason for v7: `ORDER BY id` is `ORDER BY created_at`."""
    minted = [uuid7() for _ in range(50)]
    assert minted == sorted(minted)
    assert [str(one) for one in minted] == sorted(str(one) for one in minted)


@pytest.mark.django_db
def test_rows_get_a_v7_key_and_sort_by_creation() -> None:
    first = create_tenant(name="First", slug="first", actor=system_actor())
    second = create_tenant(name="Second", slug="second", actor=system_actor())

    assert first.pk.version == 7
    assert first.pk < second.pk
    ordered = list(Tenant.objects.order_by("id").values_list("slug", flat=True))
    assert ordered == ["first", "second"]
