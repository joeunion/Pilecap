"""The usage key's rename: the old word and the new one are one cell of the census."""

from __future__ import annotations

import pytest

from apps.core.authz import vocabulary
from apps.core.tests.permissions_world import census, flat_world

pytestmark = pytest.mark.django_db


def test_the_old_key_and_the_new_one_are_one_cell() -> None:
    """`usage.read_report` answers as `usage_entry.read` for every role: an alias, one key."""
    _tenant, actors = flat_world()

    assert (
        census(["usage.read_report"], actors)["usage.read_report"]
        == (census(["usage_entry.read"], actors)["usage_entry.read"])
    )
    assert vocabulary()["usage_entry.read"].renamed_from == ("usage.read_report",)
