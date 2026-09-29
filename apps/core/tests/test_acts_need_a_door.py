"""An act is offered only where a door exists (`core.verbs.allowed_acts`).

The vocabulary holds keys no person presses — the worked example's
`widget.onboard` is its onboarding workflow's own key, with a predicate and no
route — and a face that drew every key drew a dead act. `allowed_acts` now
offers a verb only when `<kind>-<verb>` is a mounted `url_name`, read off the
live URL configuration (`core.verbs.mounted_url_names`).
"""

from __future__ import annotations

from typing import Any

import pytest
from django.db import transaction

from apps.core import verbs
from apps.core.actor import Actor
from apps.core.authz import vocabulary
from apps.core.models import Tenant
from apps.example.models import Widget
from apps.example.services import archive_widget, create_widget

pytestmark = pytest.mark.django_db


@pytest.fixture
def widget(tenant: Tenant, owner_actor: Actor) -> Widget:
    return create_widget(tenant=tenant, actor=owner_actor, name="Spares")


def test_a_key_with_a_predicate_and_no_route_is_not_an_act(
    widget: Widget, owner_actor: Actor
) -> None:
    assert "widget.onboard" in vocabulary()
    assert "widget-onboard" not in verbs.mounted_url_names()
    acts = verbs.allowed_acts(owner_actor, widget)
    assert "onboard" not in acts, acts


def test_the_acts_with_doors_are_still_offered(widget: Widget, owner_actor: Actor) -> None:
    acts = verbs.allowed_acts(owner_actor, widget)
    assert {"update", "delete", "archive"} <= set(acts), acts
    assert "restore" not in acts
    for verb in acts:
        assert f"widget-{verb}" in verbs.mounted_url_names(), verb


def test_an_archived_row_offers_restore_alone(
    widget: Widget, tenant: Tenant, owner_actor: Actor
) -> None:
    with transaction.atomic():
        archived = archive_widget(tenant=tenant, actor=owner_actor, widget=widget)
    assert verbs.allowed_acts(owner_actor, archived) == ("restore",)


def test_the_mount_decides(
    widget: Widget, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Take one door off the mount and its act goes with it — the gate reads the mount."""
    mounted = verbs.mounted_url_names()
    monkeypatch.setattr(verbs, "mounted_url_names", lambda: mounted - {"widget-archive"})
    acts: Any = verbs.allowed_acts(owner_actor, widget)
    assert "archive" not in acts
    assert "update" in acts


def test_a_declared_door_under_another_name_offers_the_act(
    widget: Widget, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The door is LOOKED UP: a noun declaring `act_doors` is offered the act where
    that url_name is mounted, not where `<kind>-<verb>` would be."""
    mounted = verbs.mounted_url_names() - {"widget-archive"}
    monkeypatch.setattr(verbs, "mounted_url_names", lambda: mounted | {"zzz-shelving-door"})
    monkeypatch.setattr(Widget, "act_doors", {"archive": "zzz-shelving-door"}, raising=False)
    assert "archive" in verbs.allowed_acts(owner_actor, widget)


def test_an_act_with_no_door_anywhere_stays_dead(
    widget: Widget, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Widget, "act_doors", {"onboard": "zzz-no-such-door"}, raising=False)
    assert "onboard" not in verbs.allowed_acts(owner_actor, widget)
