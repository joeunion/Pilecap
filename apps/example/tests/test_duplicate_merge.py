"""The widget's duplicate and merge over the REST door, and what each carries.

Both are driven through the mounted API — `POST …/duplicate/`, `GET
…/merge/?into=`, `POST …/merge/` — so `TenantMiddleware`, the strict body and
the one error envelope all run. The machine door is held to the same answers on
the wire in `test_doors_over_the_wire.py`; the copy a product takes is
`test_golden_duplicate.py` and `test_golden_merge.py`.

**"Nothing written" reads: no row change and no event.** A refused `@service`
files its own refusal audit row, so the audit trail is not the measure; the
row's columns and the recorded events are.

The world is one tenant's tree — root, A beneath it, A1 beneath A — with the
owner at the root, an ADMIN at A and the tenant's plain MEMBER at the root.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization
from apps.example.models import Widget, WidgetEntry
from apps.example.services import create_widget, record_widget_entry
from apps.files.tests.attach_specimen import attach as file_one
from apps.notes.tests.attach_specimen import attach as note_one
from apps.tags.tests.attach_specimen import attach as tag_one

pytestmark = pytest.mark.django_db

WIDGETS = "/api/v1/widgets/"
JSON = "application/json"
PASSWORD = "a-long-enough-password"  # pragma: allowlist secret


@dataclass
class World:
    tenant: Tenant
    root: Organization
    a: Organization
    a1: Organization
    owner: User
    manager: User  # ADMIN at A
    member: User  # MEMBER at the root

    def acting(self, user: User, node: Organization) -> Actor:
        return actor_for(user=user, tenant=self.tenant, org=node)


@pytest.fixture
def world(tenant: Tenant, owner: User, member: User) -> World:
    root = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=acting)
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
    return World(tenant=tenant, root=root, a=a, a1=a1, owner=owner, manager=manager, member=member)


def at(world: World, node: Organization, name: str, notes: str = "") -> Widget:
    """A widget the owner created at `node`."""
    return create_widget(
        tenant=world.tenant, actor=world.acting(world.owner, node), name=name, notes=notes
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


def moved_events(tenant: Tenant) -> list[str]:
    """Every attachment owner's `<app>.<kind>.moved` this tenant recorded."""
    from django.apps import apps as django_apps

    event = django_apps.get_model("events", "Event")
    return sorted(
        event.objects.filter(tenant=tenant, name__endswith=".moved")
        .exclude(name__startswith="example.")
        .values_list("name", flat=True)
    )


def tag_names(response: Any) -> list[str]:
    return sorted(tag["name"] for tag in body(response)["tags"])


# --- duplicate ---------------------------------------------------------------------


def test_a_duplicate_lands_at_the_hat_with_its_tags_and_without_the_ledger(
    api: Client, world: World
) -> None:
    """The copy is the presser's, at their hat; notes and tags carry, the ledger never does."""
    source = at(world, world.a1, "Bench press #4", notes="Needs the heavy-duty mount.")
    record_widget_entry(
        tenant=world.tenant, actor=world.acting(world.owner, world.a1), widget=source, note="own"
    )
    tag_one(tenant=world.tenant, actor=world.acting(world.owner, world.a1), subject=source)
    api.force_login(world.manager)  # an ADMIN whose hat is A, one level above the source

    made = api.post(f"{WIDGETS}{source.pk}/duplicate/")

    assert made.status_code == 201, made.content
    copy = body(made)
    assert copy["id"] != str(source.pk)
    assert copy["duplicated_from_id"] == str(source.pk)
    assert copy["organization_id"] == str(world.a.pk)  # the ACTOR's hat, not the source's
    assert copy["owner_id"] == str(world.manager.pk)
    assert (copy["name"], copy["notes"]) == ("Copy of Bench press #4", source.notes)
    assert copy["onboarded_at"] is None
    assert WidgetEntry.objects.filter(widget_id=copy["id"]).count() == 0
    assert WidgetEntry.objects.filter(widget_id=source.pk).count() == 1
    assert tag_names(api.get(f"{WIDGETS}{copy['id']}/")) == ["Specimen"]
    said = events(world.tenant, "example.widget.duplicated")
    assert [payload["id"] for payload in said] == [copy["id"]]
    assert "allowed_acts" not in said[0]


def test_a_repeated_key_answers_the_first_copy_and_a_second_copy_is_invalid_naming_name(
    api: Client, world: World
) -> None:
    source = at(world, world.root, "Rack")
    api.force_login(world.owner)

    first = api.post(f"{WIDGETS}{source.pk}/duplicate/", HTTP_IDEMPOTENCY_KEY="press-1")
    again = api.post(f"{WIDGETS}{source.pk}/duplicate/", HTTP_IDEMPOTENCY_KEY="press-1")
    assert first.status_code == 201, first.content
    assert body(again)["id"] == body(first)["id"]
    before = Widget.objects.for_tenant(world.tenant).count()

    clash = api.post(f"{WIDGETS}{source.pk}/duplicate/")

    assert clash.status_code == 400, clash.content
    assert body(clash)["code"] == "invalid"
    assert "name" in body(clash)["errors"], body(clash)
    assert Widget.objects.for_tenant(world.tenant).count() == before
    assert len(events(world.tenant, "example.widget.duplicated")) == 1


def test_an_archived_widget_is_not_copied(api: Client, world: World) -> None:
    from apps.example.services import archive_widget

    source = at(world, world.root, "Retired")
    archive_widget(tenant=world.tenant, actor=world.acting(world.owner, world.root), widget=source)
    api.force_login(world.owner)

    refused = api.post(f"{WIDGETS}{source.pk}/duplicate/")

    assert refused.status_code == 409, refused.content
    assert body(refused)["code"] == "archived"
    assert events(world.tenant, "example.widget.duplicated") == []


# --- merge ---------------------------------------------------------------------


@pytest.fixture
def pair(world: World) -> tuple[Widget, Widget]:
    """A loser carrying a note, a tag, a file and a ledger line; a bare survivor."""
    loser = at(world, world.root, "Bench press (dup)")
    survivor = at(world, world.root, "Bench press")
    acting = world.acting(world.owner, world.root)
    note_one(tenant=world.tenant, actor=acting, subject=loser)
    tag_one(tenant=world.tenant, actor=acting, subject=loser)
    file_one(tenant=world.tenant, actor=acting, subject=loser)
    record_widget_entry(tenant=world.tenant, actor=acting, widget=loser, note="kept on the loser")
    return loser, survivor


def _merge(api: Client, loser: Widget, survivor: Widget) -> Any:
    return api.post(
        f"{WIDGETS}{loser.pk}/merge/",
        {
            "into_id": str(survivor.pk),
            "version": fresh(loser).version,
            "into_version": fresh(survivor).version,
        },
        content_type=JSON,
    )


def test_the_dry_run_names_what_would_leave_the_loser_and_writes_nothing(
    api: Client, world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api.force_login(world.owner)

    preview = api.get(f"{WIDGETS}{loser.pk}/merge/", {"into": str(survivor.pk)})

    assert preview.status_code == 200, preview.content
    assert body(preview)["loser_id"] == str(loser.pk)
    assert {row["title"]: row["left"] for row in body(preview)["repoints"]} == {
        "Notes": 1,
        "Tags": 1,
        "Files": 1,
    }
    assert fresh(loser).merged_into_id is None
    assert events(world.tenant, "example.widget.merged") == []


def test_a_merge_repoints_the_attachments_and_leaves_a_read_only_tombstone(
    api: Client, world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api.force_login(world.owner)

    merged = _merge(api, loser, survivor)

    assert merged.status_code == 200, merged.content
    assert body(merged)["id"] == str(survivor.pk)
    said = events(world.tenant, "example.widget.merged")
    assert len(said) == 1
    assert said[0]["id"] == str(survivor.pk)
    assert said[0]["loser_id"] == str(loser.pk)
    assert {row["title"]: row["left"] for row in said[0]["repoints"]} == {
        "Notes": 1,
        "Tags": 1,
        "Files": 1,
    }
    assert "allowed_acts" not in said[0]
    # One `<app>.<kind>.moved` per moved row — a note, a tag link, a file.
    assert len(moved_events(world.tenant)) == 3, moved_events(world.tenant)

    tombstone = api.get(f"{WIDGETS}{loser.pk}/")
    assert tombstone.status_code == 200, tombstone.content
    assert body(tombstone)["merged_into_id"] == str(survivor.pk)
    assert body(tombstone)["archived_at"] is not None
    assert body(tombstone)["allowed_acts"] == []

    # The attachments answer through the survivor now.
    notes = api.get("/api/v1/notes/", {"subject": f"widget:{survivor.pk}"})
    assert notes.status_code == 200, notes.content
    assert len(body(notes)["items"]) == 1
    assert tag_names(api.get(f"{WIDGETS}{survivor.pk}/")) == ["Specimen"]
    # The ledger stayed where it was written, and the survivor's ledger reads it.
    assert WidgetEntry.objects.filter(widget=loser).count() == 1
    ledger = api.get(f"{WIDGETS}entries/", {"widget_id": str(survivor.pk)})
    assert [row["note"] for row in body(ledger)["items"]] == ["kept on the loser"]


def test_a_write_on_the_loser_is_merged_naming_the_survivor_and_nothing_changes(
    api: Client, world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api.force_login(world.owner)
    assert _merge(api, loser, survivor).status_code == 200
    before = fresh(loser)
    updated = len(events(world.tenant, "example.widget.updated"))

    refused = api.patch(
        f"{WIDGETS}{loser.pk}/", {"name": "Revived", "version": before.version}, content_type=JSON
    )

    assert refused.status_code == 409, refused.content
    assert body(refused)["code"] == "merged"
    assert body(refused)["merged_into"] == str(survivor.pk)
    after = fresh(loser)
    assert (after.name, after.updated_at) == (before.name, before.updated_at)
    assert len(events(world.tenant, "example.widget.updated")) == updated


def test_the_same_pair_again_is_unchanged_and_a_chain_is_compressed(
    api: Client, world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    last = at(world, world.root, "Bench press (final)")
    api.force_login(world.owner)
    assert _merge(api, loser, survivor).status_code == 200

    again = _merge(api, loser, survivor)
    assert again.status_code == 200, again.content
    assert len(events(world.tenant, "example.widget.merged")) == 1

    assert _merge(api, survivor, last).status_code == 200
    assert fresh(loser).merged_into_id == last.pk  # one hop, never two


def test_a_member_may_not_merge_and_a_widget_is_not_merged_into_itself(
    api: Client, world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api.force_login(world.member)
    refused = _merge(api, loser, survivor)
    assert refused.status_code == 403, refused.content
    assert fresh(loser).merged_into_id is None

    api.force_login(world.owner)
    itself = _merge(api, loser, loser)
    assert itself.status_code == 400, itself.content
    assert "into" in body(itself)["errors"], body(itself)
    assert events(world.tenant, "example.widget.merged") == []


def test_deleting_a_survivor_refuses_merge_survivor_and_changes_nothing(
    api: Client, world: World
) -> None:
    """The losers' tombstones name the survivor, so it cannot go: a typed refusal, not a
    database PROTECT, with the survivor, the tombstone and the event log as they were."""
    loser, survivor = at(world, world.root, "L"), at(world, world.root, "S")
    api.force_login(world.owner)
    assert _merge(api, loser, survivor).status_code == 200
    deleted_before = events(world.tenant, "example.widget.deleted")

    refused = api.delete(f"{WIDGETS}{survivor.pk}/")

    assert refused.status_code == 409, refused.content
    assert body(refused)["code"] == "merge_survivor", body(refused)
    assert fresh(survivor).archived_at is None
    assert fresh(loser).merged_into_id == survivor.pk
    assert events(world.tenant, "example.widget.deleted") == deleted_before
