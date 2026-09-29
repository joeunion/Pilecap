"""The widget's family verbs over the REST door: version, move, bulk, history.

Each test drives the door a client drives — `PATCH`, `POST …/move/`, `POST
…/bulk/`, `GET …/history/` — through the mounted API, so `TenantMiddleware`,
the strict body and the one error envelope all run. The machine door's answers
are compared against these on the wire in `test_doors_over_the_wire.py`; the
copy a product takes is `test_golden_<verb>.py`.

**"Nothing written" reads: no row change and no event.** A refused `@service`
always files its own refusal audit row, so the audit trail is not the measure;
the row's columns and the outbox are.

The world is one tenant's tree — root, A beneath it, A1 beneath A, B beside A —
with the owner at the root, an ADMIN at A (the branch administrator a move and a
bulk are pressed by) and the tenant's plain MEMBER at the root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization
from apps.example.models import Widget, WidgetEntry
from apps.example.services import create_widget, record_widget_entry

pytestmark = pytest.mark.django_db

WIDGETS = "/api/v1/widgets/"
ORGANIZATIONS = "/api/v1/organizations/"
JSON = "application/json"
PASSWORD = "a-long-enough-password"  # pragma: allowlist secret


@dataclass
class World:
    tenant: Tenant
    root: Organization
    a: Organization
    a1: Organization
    b: Organization
    owner: User
    manager: User  # ADMIN at A
    member: User  # MEMBER at the root


@pytest.fixture
def world(tenant: Tenant, owner: User, member: User) -> World:
    root = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=acting)
    b = create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=acting)
    a1 = create_organization(tenant=tenant, parent=a, name="A1", slug="a1", actor=acting)
    manager = create_user(email="manager@example.com", password=PASSWORD)
    add_membership(
        user=manager,
        tenant=tenant,
        organization=a,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return World(
        tenant=tenant, root=root, a=a, a1=a1, b=b, owner=owner, manager=manager, member=member
    )


def at(world: World, node: Organization, name: str) -> Widget:
    """A widget the owner created at `node`."""
    return create_widget(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=node),
        name=name,
    )


def body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def fresh(widget: Widget) -> Widget:
    return Widget.objects.for_tenant(widget.tenant).including_archived().get(pk=widget.pk)


def events(tenant: Tenant, name: str) -> list[dict[str, Any]]:
    """Every `Event.payload` this tenant recorded under `name`, oldest first."""
    from django.apps import apps as django_apps

    event = django_apps.get_model("events", "Event")
    return [
        dict(row.payload)
        for row in event.objects.filter(tenant=tenant, name=name).order_by("created_at")
    ]


# --- version -------------------------------------------------------------


def test_a_patch_without_a_version_is_refused_naming_it(api: Client, world: World) -> None:
    widget = at(world, world.root, "Unversioned")
    api.force_login(world.owner)

    response = api.patch(f"{WIDGETS}{widget.pk}/", {"name": "Renamed"}, content_type=JSON)

    assert response.status_code == 422, response.content
    assert "version" in body(response)["errors"], body(response)
    assert fresh(widget).name == "Unversioned"


def test_a_stale_version_is_refused_with_the_current_one_and_nothing_written(
    api: Client, world: World
) -> None:
    widget = at(world, world.root, "Raced")
    api.force_login(world.owner)
    read = body(api.get(f"{WIDGETS}{widget.pk}/"))
    first = api.patch(
        f"{WIDGETS}{widget.pk}/",
        {"name": "First save", "version": read["version"]},
        content_type=JSON,
    )
    assert first.status_code == 200, first.content
    before = fresh(widget)
    updated_events = len(events(world.tenant, "example.widget.updated"))

    late = api.patch(
        f"{WIDGETS}{widget.pk}/",
        {"name": "Late save", "version": read["version"]},
        content_type=JSON,
    )

    assert late.status_code == 409, late.content
    refusal = body(late)
    assert refusal["code"] == "stale_version"
    assert refusal["current_version"] == body(first)["version"]
    after = fresh(widget)
    assert (after.name, after.updated_at) == (before.name, before.updated_at)
    assert len(events(world.tenant, "example.widget.updated")) == updated_events


def test_the_current_version_saves_and_answers_a_new_one(api: Client, world: World) -> None:
    widget = at(world, world.root, "Current")
    api.force_login(world.owner)
    read = body(api.get(f"{WIDGETS}{widget.pk}/"))

    saved = api.patch(
        f"{WIDGETS}{widget.pk}/", {"name": "Saved", "version": read["version"]}, content_type=JSON
    )

    assert saved.status_code == 200, saved.content
    assert body(saved)["name"] == "Saved"
    assert body(saved)["version"] > read["version"]


# --- move -----------------------------------------------------------


def test_a_move_into_the_subtree_rehomes_the_widget_and_says_both_nodes(
    api: Client, world: World
) -> None:
    widget = at(world, world.a, "Mover")
    api.force_login(world.manager)
    read = body(api.get(f"{WIDGETS}{widget.pk}/", headers={"x-org": "a"}))

    moved = api.post(
        f"{WIDGETS}{widget.pk}/move/",
        {"organization_id": str(world.a1.pk), "version": read["version"]},
        content_type=JSON,
        headers={"x-org": "a"},
    )

    assert moved.status_code == 200, moved.content
    answered = body(moved)
    assert answered["organization_id"] == str(world.a1.pk)
    assert answered["organization_name"] == "A1"
    assert "owner_name" in answered
    assert fresh(widget).organization_id == world.a1.pk
    (said,) = events(world.tenant, "example.widget.moved")
    assert said["organization_id"] == str(world.a1.pk)
    assert said["from_organization_id"] == str(world.a.pk)


def test_a_widget_with_a_ledger_line_is_move_blocked_and_nothing_moves(
    api: Client, world: World
) -> None:
    widget = at(world, world.a, "Held by its ledger")
    record_widget_entry(
        tenant=world.tenant,
        actor=actor_for(user=world.owner, tenant=world.tenant, org=world.a),
        widget=widget,
        note="recorded here",
    )
    api.force_login(world.manager)
    before = fresh(widget)

    refused = api.post(
        f"{WIDGETS}{widget.pk}/move/",
        {"organization_id": str(world.a1.pk), "version": before.version},
        content_type=JSON,
        headers={"x-org": "a"},
    )

    assert refused.status_code == 409, refused.content
    answered = body(refused)
    assert answered["code"] == "move_blocked"
    assert answered["blocking"][0]["noun"] == "widget_entry"
    after = fresh(widget)
    assert (after.organization_id, after.updated_at) == (world.a.pk, before.updated_at)
    assert set(
        WidgetEntry.objects.for_tenant(world.tenant).values_list("organization", flat=True)
    ) == {world.a.pk}
    assert events(world.tenant, "example.widget.moved") == []


def test_a_destination_outside_the_admins_subtree_is_not_found(api: Client, world: World) -> None:
    widget = at(world, world.a, "Stays in A")
    api.force_login(world.manager)

    refused = api.post(
        f"{WIDGETS}{widget.pk}/move/",
        {"organization_id": str(world.b.pk), "version": fresh(widget).version},
        content_type=JSON,
        headers={"x-org": "a"},
    )

    assert refused.status_code == 404, refused.content
    assert fresh(widget).organization_id == world.a.pk


def test_a_member_may_not_move(api: Client, world: World) -> None:
    widget = at(world, world.a, "Not theirs to move")
    api.force_login(world.member)

    refused = api.post(
        f"{WIDGETS}{widget.pk}/move/",
        {"organization_id": str(world.a1.pk), "version": fresh(widget).version},
        content_type=JSON,
    )

    assert refused.status_code == 403, refused.content
    assert fresh(widget).organization_id == world.a.pk


def test_the_move_sheet_destinations_are_where_the_branch_admin_may_move_a_widget(
    api: Client, world: World
) -> None:
    """C2.4 with the real key: `?can=widget.move` lists A and A1 for an admin at A."""
    api.force_login(world.manager)

    listed = api.get(ORGANIZATIONS, {"can": "widget.move"}, headers={"x-org": "a"})

    assert listed.status_code == 200, listed.content
    assert {row["slug"] for row in body(listed)["items"]} == {"a", "a1"}
    nope = api.get(ORGANIZATIONS, {"can": "widget.nope"}, headers={"x-org": "a"})
    assert nope.status_code == 400, nope.content
    assert "can" in body(nope)["errors"]


# --- bulk -----------------------------------------------------------


def test_a_bulk_archive_answers_each_id_in_order_and_a_replay_answers_the_same(
    api: Client, world: World
) -> None:
    here = at(world, world.a, "First")
    sibling = at(world, world.b, "In B")
    below = at(world, world.a1, "Third")
    api.force_login(world.manager)
    ids = [str(here.pk), str(sibling.pk), str(below.pk)]

    first = api.post(
        f"{WIDGETS}bulk/",
        {"verb": "archive", "ids": ids},
        content_type=JSON,
        headers={"x-org": "a", "idempotency-key": "bulk-archive-1"},
    )

    assert first.status_code == 200, first.content
    answered = body(first)
    assert [r["outcome"] for r in answered["results"]] == ["done", "refused", "done"]
    assert [r["id"] for r in answered["results"]] == ids
    assert answered["results"][1]["refusal"]["code"] == "not_found"
    assert (answered["done"], answered["unchanged"], answered["refused"]) == (2, 0, 1)
    assert fresh(here).archived_at is not None and fresh(below).archived_at is not None
    assert fresh(sibling).archived_at is None

    replay = api.post(
        f"{WIDGETS}bulk/",
        {"verb": "archive", "ids": ids},
        content_type=JSON,
        headers={"x-org": "a", "idempotency-key": "bulk-archive-1"},
    )
    assert replay.status_code == 200, replay.content
    assert replay.content == first.content


def test_a_bulk_move_to_where_the_widget_already_is_is_unchanged(api: Client, world: World) -> None:
    there = at(world, world.a1, "Already there")
    goes = at(world, world.a, "Goes")
    api.force_login(world.manager)

    answered = api.post(
        f"{WIDGETS}bulk/",
        {"verb": "move", "ids": [str(there.pk), str(goes.pk)], "organization_id": str(world.a1.pk)},
        content_type=JSON,
        headers={"x-org": "a"},
    )

    assert answered.status_code == 200, answered.content
    assert [r["outcome"] for r in body(answered)["results"]] == ["unchanged", "done"]
    assert fresh(goes).organization_id == world.a1.pk


# --- history -----------------------------------------------------------------


def test_the_history_reads_create_update_archive_restore_newest_first(
    api: Client, world: World
) -> None:
    api.force_login(world.owner)
    created = api.post(WIDGETS, {"name": "Storied"}, content_type=JSON)
    assert created.status_code == 201, created.content
    widget_id = body(created)["id"]
    updated = api.patch(
        f"{WIDGETS}{widget_id}/",
        {"name": "Storied, renamed", "version": body(created)["version"]},
        content_type=JSON,
    )
    assert updated.status_code == 200, updated.content
    assert api.post(f"{WIDGETS}{widget_id}/archive/").status_code == 200
    assert api.post(f"{WIDGETS}{widget_id}/restore/").status_code == 200

    history = api.get(f"{WIDGETS}{widget_id}/history/")

    assert history.status_code == 200, history.content
    rows = body(history)["items"]
    assert [row["verb"] for row in rows] == ["restore", "archive", "update", "create"]
    assert rows[2]["changed_fields"] == ["name"]


def test_a_sibling_branch_widgets_history_is_not_found(api: Client, world: World) -> None:
    widget = at(world, world.b, "In B")
    api.force_login(world.manager)

    assert api.get(f"{WIDGETS}{widget.pk}/history/", headers={"x-org": "a"}).status_code == 404
