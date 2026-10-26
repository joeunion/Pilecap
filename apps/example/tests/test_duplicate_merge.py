"""The widget's duplicate and merge over the REST door, and what each carries."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.example.models import Widget, WidgetEntry
from apps.example.services import create_widget, record_widget_entry
from pilecap import Actor
from pilecap.tenancy import Organization, Tenant
from pilecap.testing import World, actor_for, build_world
from pilecap.testing import attach_file as file_one
from pilecap.testing import attach_note as note_one
from pilecap.testing import attach_tag as tag_one

pytestmark = pytest.mark.django_db

WIDGETS = "/api/v1/widgets/"
JSON = "application/json"


@pytest.fixture
def world() -> World:
    return build_world()


def acting(world: World, who: Actor, node: Organization) -> Actor:
    """`who` wearing the hat at `node`."""
    return actor_for(user=who.user, tenant=world.tenant, org=node)


def at(world: World, node: Organization, name: str, notes: str = "") -> Widget:
    """A widget the owner created at `node`."""
    return create_widget(
        tenant=world.tenant, actor=acting(world, world.owner, node), name=name, notes=notes
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


def test_a_duplicate_lands_at_the_hat_with_its_tags_and_without_the_ledger(world: World) -> None:
    """The copy is the presser's, at their hat; notes and tags carry, the ledger never does."""
    source = at(world, world.a1, "Bench press #4", notes="Needs the heavy-duty mount.")
    record_widget_entry(
        tenant=world.tenant, actor=acting(world, world.owner, world.a1), widget=source, note="own"
    )
    tag_one(tenant=world.tenant, actor=acting(world, world.owner, world.a1), subject=source)
    api = world.session(world.admin_at_a)  # an ADMIN whose hat is A, one level above the source

    made = api.post(f"{WIDGETS}{source.pk}/duplicate/")

    assert made.status_code == 201, made.content
    copy = body(made)
    assert copy["id"] != str(source.pk)
    assert copy["duplicated_from_id"] == str(source.pk)
    assert copy["organization_id"] == str(world.a.pk)  # the ACTOR's hat, not the source's
    assert copy["owner_id"] == str(world.user(world.admin_at_a).pk)
    assert (copy["name"], copy["notes"]) == ("Copy of Bench press #4", source.notes)
    assert copy["onboarded_at"] is None
    assert WidgetEntry.objects.filter(widget_id=copy["id"]).count() == 0
    assert WidgetEntry.objects.filter(widget_id=source.pk).count() == 1
    assert tag_names(api.get(f"{WIDGETS}{copy['id']}/")) == ["Specimen"]
    said = events(world.tenant, "example.widget.duplicated")
    assert [payload["id"] for payload in said] == [copy["id"]]
    assert "allowed_acts" not in said[0]


def test_a_repeated_key_answers_the_first_copy_and_a_second_copy_is_invalid_naming_name(
    world: World,
) -> None:
    source = at(world, world.root, "Rack")
    api = world.session(world.owner)

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


def test_an_archived_widget_is_not_copied(world: World) -> None:
    from apps.example.services import archive_widget

    source = at(world, world.root, "Retired")
    archive_widget(tenant=world.tenant, actor=world.owner, widget=source)
    api = world.session(world.owner)

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
    note_one(tenant=world.tenant, actor=world.owner, subject=loser)
    tag_one(tenant=world.tenant, actor=world.owner, subject=loser)
    file_one(tenant=world.tenant, actor=world.owner, subject=loser)
    record_widget_entry(
        tenant=world.tenant, actor=world.owner, widget=loser, note="kept on the loser"
    )
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
    world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api = world.session(world.owner)

    preview = api.get(f"{WIDGETS}{loser.pk}/merge/", {"into": str(survivor.pk)})

    assert preview.status_code == 200, preview.content
    assert body(preview)["loser_id"] == str(loser.pk)
    assert {row["title"]: row["left"] for row in body(preview)["repoints"]} == {
        "Notes": 1,
        "Tags": 1,
        "Files": 1,
        # The worked customer surface re-points the requests about a widget.
        "Portal requests": 0,
    }
    assert fresh(loser).merged_into_id is None
    assert events(world.tenant, "example.widget.merged") == []


def test_a_merge_repoints_the_attachments_and_leaves_a_read_only_tombstone(
    world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api = world.session(world.owner)

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
        # The worked customer surface re-points the requests about a widget.
        "Portal requests": 0,
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
    notes = api.get("/api/v1/djb_notes/", {"subject": f"widget:{survivor.pk}"})
    assert notes.status_code == 200, notes.content
    assert len(body(notes)["items"]) == 1
    assert tag_names(api.get(f"{WIDGETS}{survivor.pk}/")) == ["Specimen"]
    # The ledger stayed where it was written, and the survivor's ledger reads it.
    assert WidgetEntry.objects.filter(widget=loser).count() == 1
    ledger = api.get(f"{WIDGETS}entries/", {"widget_id": str(survivor.pk)})
    assert [row["note"] for row in body(ledger)["items"]] == ["kept on the loser"]


def test_a_write_on_the_loser_is_merged_naming_the_survivor_and_nothing_changes(
    world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api = world.session(world.owner)
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
    world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    last = at(world, world.root, "Bench press (final)")
    api = world.session(world.owner)
    assert _merge(api, loser, survivor).status_code == 200

    again = _merge(api, loser, survivor)
    assert again.status_code == 200, again.content
    assert len(events(world.tenant, "example.widget.merged")) == 1

    assert _merge(api, survivor, last).status_code == 200
    assert fresh(loser).merged_into_id == last.pk  # one hop, never two


def test_a_member_may_not_merge_and_a_widget_is_not_merged_into_itself(
    world: World, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api = world.session(world.member)
    refused = _merge(api, loser, survivor)
    assert refused.status_code == 403, refused.content
    assert fresh(loser).merged_into_id is None

    api = world.session(world.owner)
    itself = _merge(api, loser, loser)
    assert itself.status_code == 400, itself.content
    assert "into" in body(itself)["errors"], body(itself)
    assert events(world.tenant, "example.widget.merged") == []


def test_deleting_a_survivor_refuses_merge_survivor_and_changes_nothing(world: World) -> None:
    """The losers' tombstones name the survivor, so it cannot go: a typed refusal."""
    loser, survivor = at(world, world.root, "L"), at(world, world.root, "S")
    api = world.session(world.owner)
    assert _merge(api, loser, survivor).status_code == 200
    deleted_before = events(world.tenant, "example.widget.deleted")

    refused = api.delete(f"{WIDGETS}{survivor.pk}/")

    assert refused.status_code == 409, refused.content
    assert body(refused)["code"] == "merge_survivor", body(refused)
    assert fresh(survivor).archived_at is None
    assert fresh(loser).merged_into_id == survivor.pk
    assert events(world.tenant, "example.widget.deleted") == deleted_before
