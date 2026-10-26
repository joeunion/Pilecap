# golden: noun begin
"""Every role's answer to every widget key, against this app's own baseline file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

from apps.example import policies
from apps.example.models import Widget
from pilecap import Actor
from pilecap.accounts import User
from pilecap.tenancy import Tenant, root_organization
from pilecap.testing import drift, noun_census, reset_policies, settle_baseline

pytestmark = pytest.mark.django_db

BASELINE = (
    Path(settings.BASE_DIR)
    / "apps"
    / Widget._meta.app_label
    / "tests"
    / f"{Widget._meta.model_name}_authz_baseline.json"
)


def _row(tenant: Tenant, owner: User) -> Widget:
    """One row at the root, written raw: a service would ask the very keys measured."""
    return Widget.objects.create(
        tenant=tenant,
        organization=root_organization(tenant=tenant),
        owner_id=owner.pk,
        name=f"census-{owner.pk}",
    )


def test_every_role_answers_every_widget_key_as_the_baseline_says() -> None:
    moved = settle_baseline(BASELINE, noun_census(Widget, row=_row))
    assert moved == [], (
        f"{BASELINE.relative_to(settings.BASE_DIR)} moved ({len(moved)} lines):\n    "
        + "\n    ".join(moved)
        + "\n  A change you meant: re-run this test with DJB_BASELINE_WRITE=1, read the diff, "
        "commit it."
    )


def test_a_planted_predicate_moves_a_cell() -> None:
    """The census can fail: a key refused to everybody moves the cells that said yes."""

    def refuse(actor: Actor, obj: Any = None) -> bool:
        """The planted predicate: no, for everybody."""
        return False

    key = f"{Widget._meta.model_name}.update"
    before = noun_census(Widget, row=_row)
    original = dict(policies.POLICIES)
    try:
        policies.POLICIES[key] = refuse
        reset_policies()
        after = noun_census(Widget, row=_row)
    finally:
        policies.POLICIES.clear()
        policies.POLICIES.update(original)
        reset_policies()
    moved = drift(before, after)
    assert moved and all(line.split()[1] == key for line in moved), moved


# golden: noun end
