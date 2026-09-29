"""The note services and selectors, called directly — the rules every door inherits."""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for
from apps.core.audit import AuditEntry
from apps.core.exceptions import Archived, Forbidden, Invalid, NotFound
from apps.core.models import Organization, Tenant
from apps.djb_notes.events import NOTE_ARCHIVED, NOTE_CREATED, NOTE_RESTORED, NOTE_UPDATED
from apps.djb_notes.models import Note
from apps.djb_notes.selectors import get_note, list_notes
from apps.djb_notes.services import archive_note, create_note, restore_note, update_note
from apps.events.models import Event, Outbox
from apps.example.models import Widget
from apps.example.services import create_widget, delete_widget

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def declares_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The widget declares notes for this module, ADDED to whatever it declares.

    Additive and undone by `monkeypatch`, never a replacement and never a hand
    `del`: the day the worked example declares its own attachments, this plant
    keeps them and leaves them exactly as it found them.
    """
    monkeypatch.setattr(
        Widget, "attachments", (*getattr(Widget, "attachments", ()), "notes"), raising=False
    )


@pytest.fixture
def widget(tenant: Tenant, owner_actor: Actor) -> Widget:
    return create_widget(tenant=tenant, actor=owner_actor, name="Subject")


def _subject(widget: Widget) -> str:
    return f"widget:{widget.pk}"


def _write(tenant: Tenant, actor: Actor, widget: Widget, body: str = "Ships Tuesday.") -> Note:
    return create_note(tenant=tenant, actor=actor, subject=_subject(widget), body=body)


def test_a_note_emits_created_with_the_door_shape(
    tenant: Tenant, owner_actor: Actor, widget: Widget
) -> None:
    note = _write(tenant, owner_actor, widget)

    event = Event.objects.for_tenant(tenant).get(name=NOTE_CREATED)
    assert event.payload["id"] == str(note.pk)
    assert event.payload["subject"] == _subject(widget)
    assert event.payload["organization_id"] == str(widget.organization_id)
    assert note.author_id == owner_actor.user.pk  # type: ignore[union-attr]


def test_the_derived_names_carry_the_app_label(
    tenant: Tenant, owner_actor: Actor, widget: Widget
) -> None:
    """The event's first segment and the audit action's are the LABEL, not the kind.

    Both are derived by mechanism — the event grammar joins segment 0 to the
    declaring app, and `@service` composes `<label>.<function>` — so they are
    spelled here as literals: a constant would move with the rename and prove
    nothing about it.
    """
    _write(tenant, owner_actor, widget)

    event = Event.objects.for_tenant(tenant).get(name=NOTE_CREATED)
    assert event.name == "djb_notes.note.created"
    assert Outbox.objects.get(event=event).event.name == "djb_notes.note.created"
    actions = set(AuditEntry.objects.for_tenant(tenant).values_list("action", flat=True))
    assert "djb_notes.create_note" in actions
    assert "notes.create_note" not in actions


@pytest.mark.parametrize(
    "subject",
    ["widget", "widget:", ":abc", "widget:not-an-id", "nothing-like-it"],
)
def test_a_malformed_pointer_is_invalid_naming_subject(
    tenant: Tenant, owner_actor: Actor, subject: str
) -> None:
    with pytest.raises(Invalid) as refused:
        create_note(tenant=tenant, actor=owner_actor, subject=subject, body="x")
    assert "subject" in refused.value.errors


def test_an_unknown_kind_is_invalid_not_not_found(tenant: Tenant, owner_actor: Actor) -> None:
    with pytest.raises(Invalid) as refused:
        create_note(
            tenant=tenant,
            actor=owner_actor,
            subject="spaceship:3f0c2a8e-54b1-4c5e-9d7a-1b2c3d4e5f60",
            body="x",
        )
    assert "subject" in refused.value.errors


def test_a_row_that_does_not_exist_is_not_found(tenant: Tenant, owner_actor: Actor) -> None:
    with pytest.raises(NotFound):
        create_note(
            tenant=tenant,
            actor=owner_actor,
            subject="widget:3f0c2a8e-54b1-4c5e-9d7a-1b2c3d4e5f60",
            body="x",
        )


def test_another_tenants_subject_is_not_found(
    tenant: Tenant, stranger_actor: Actor, other_tenant: Tenant, widget: Widget
) -> None:
    with pytest.raises(NotFound):
        create_note(tenant=other_tenant, actor=stranger_actor, subject=_subject(widget), body="x")


def test_only_the_author_updates_and_an_archived_note_is_read_only(
    tenant: Tenant, owner_actor: Actor, admin_actor: Actor, member_actor: Actor, widget: Widget
) -> None:
    note = _write(tenant, member_actor, widget)

    for stranger in (owner_actor, admin_actor):
        with pytest.raises(Forbidden):
            update_note(tenant=tenant, actor=stranger, note=note, body="Not mine")

    changed = update_note(tenant=tenant, actor=member_actor, note=note, body="Mine")
    assert changed.body == "Mine"
    assert Event.objects.for_tenant(tenant).filter(name=NOTE_UPDATED).count() == 1

    archive_note(tenant=tenant, actor=admin_actor, note=changed)
    with pytest.raises(Archived):
        update_note(
            tenant=tenant,
            actor=member_actor,
            note=Note.objects.for_tenant(tenant).including_archived().get(pk=note.pk),
            body="Too late",
        )


def test_archive_and_restore_are_idempotent_and_an_admins_press(
    tenant: Tenant, owner_actor: Actor, admin_actor: Actor, member_actor: Actor, widget: Widget
) -> None:
    note = _write(tenant, member_actor, widget)

    with pytest.raises(Forbidden):
        archive_note(tenant=tenant, actor=member_actor, note=note)

    first = archive_note(tenant=tenant, actor=admin_actor, note=note)
    again = archive_note(tenant=tenant, actor=admin_actor, note=first)
    assert first.archived_at is not None
    assert again.archived_at == first.archived_at
    assert Event.objects.for_tenant(tenant).filter(name=NOTE_ARCHIVED).count() == 1

    restored = restore_note(tenant=tenant, actor=admin_actor, note=again)
    restore_note(tenant=tenant, actor=admin_actor, note=restored)
    assert restored.archived_at is None
    assert Event.objects.for_tenant(tenant).filter(name=NOTE_RESTORED).count() == 1


def test_the_list_cuts(
    tenant: Tenant, owner_actor: Actor, admin_actor: Actor, widget: Widget
) -> None:
    live = _write(tenant, owner_actor, widget, "live")
    gone = archive_note(
        tenant=tenant, actor=admin_actor, note=_write(tenant, owner_actor, widget, "gone")
    )

    def ids(show: str) -> set[object]:
        return {
            n.pk
            for n in list_notes(
                tenant=tenant, actor=owner_actor, subject=_subject(widget), show=show
            )
        }

    assert ids("live") == {live.pk}
    assert ids("archived") == {gone.pk}
    assert ids("all") == {live.pk, gone.pk}
    with pytest.raises(Invalid):
        ids("everything")


def test_the_list_is_only_this_subjects_and_this_tenants(
    tenant: Tenant,
    owner_actor: Actor,
    widget: Widget,
    other_tenant: Tenant,
    stranger_actor: Actor,
) -> None:
    other_widget = create_widget(tenant=tenant, actor=owner_actor, name="Another")
    mine = _write(tenant, owner_actor, widget)
    _write(tenant, owner_actor, other_widget)
    theirs_widget = create_widget(tenant=other_tenant, actor=stranger_actor, name="Theirs")
    _write(other_tenant, stranger_actor, theirs_widget)

    listed = list_notes(tenant=tenant, actor=owner_actor, subject=_subject(widget))
    assert [n.pk for n in listed] == [mine.pk]


def test_a_note_whose_subject_is_gone_is_unreachable_never_wrong(
    tenant: Tenant, owner_actor: Actor, widget: Widget
) -> None:
    """The declared price of a polymorphic pointer, and why it is never WRONG."""
    note = _write(tenant, owner_actor, widget)
    assert get_note(tenant=tenant, actor=owner_actor, note_id=note.pk).pk == note.pk

    delete_widget(tenant=tenant, actor=owner_actor, widget=widget)

    assert Note.objects.filter(pk=note.pk).exists()  # the orphan the database allows
    with pytest.raises(NotFound):
        get_note(tenant=tenant, actor=owner_actor, note_id=note.pk)
    with pytest.raises(NotFound):
        list_notes(tenant=tenant, actor=owner_actor, subject=_subject(widget))


def test_a_note_on_an_organization_lives_at_that_organization(
    tenant: Tenant,
    owner_actor: Actor,
    root_org: Organization,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subject that IS a node: the note lives at it (the `_landing` case for nodes)."""
    monkeypatch.setattr(
        Organization,
        "attachments",
        (*getattr(Organization, "attachments", ()), "notes"),
        raising=False,
    )
    note = create_note(
        tenant=tenant,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
        subject=f"organization:{root_org.pk}",
        body="The root's own note.",
    )
    assert note.organization_id == root_org.pk
