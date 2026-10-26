"""Services own writes, so services are what the tests drive."""

# golden: noun begin
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.db.models import QuerySet

from apps.example import services
from apps.example.events import (
    WIDGET_CREATED,
    WIDGET_DELETED,
    WIDGET_ONBOARDED,
    WIDGET_UPDATED,
)
from apps.example.models import Widget
from apps.example.schemas import WidgetOut
from apps.example.services import create_widget, delete_widget, update_widget
from pilecap import Actor, AuditEntry, Forbidden, Invalid, NotFound, StaleVersion
from pilecap.accounts import User
from pilecap.events import EMIT
from pilecap.tenancy import Tenant, add_membership, create_organization, root_organization
from pilecap.testing import (
    PER_VIEWER_FIELDS,
    BridgeNotRegistered,
    actor_for,
    bridge_registry,
    clear_bridge,
    configure,
    register_listener,
    registered_listeners,
    system_actor,
)

# golden: noun end
# isort: split
# golden: child entry begin
from apps.example.models import WidgetEntry

# golden: child entry end
# isort: split
# golden: verb touch begin
from apps.example.events import WIDGET_TOUCHED
from apps.example.services import archive_widget, touch_widget
from pilecap import Archived

# golden: verb touch end
# isort: split
# golden: enum status begin
from apps.example.services import transition_widget
from pilecap import Conflict

# golden: enum status end
# golden: noun begin
pytestmark = pytest.mark.django_db


def _events(tenant: Tenant) -> QuerySet[Any]:
    """This tenant's rows in the event spine, if the spine is installed."""
    return django_apps.get_model("events", "Event").objects.for_tenant(tenant)


def acting_in(user: User, tenant: Tenant) -> Actor:
    """The same person, genuinely joined to a second tenant."""
    add_membership(user=user, tenant=tenant, actor=system_actor(tenant=tenant))
    return actor_for(user=user, tenant=tenant, org=root_organization(tenant=tenant))


def test_create_widget_writes_the_row(tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="  Spaced  ", notes="a note")
    assert widget.pk is not None
    assert widget.name == "Spaced"
    assert widget.notes == "a note"
    assert widget.owner_id == owner_actor.user_id
    assert widget.tenant_id == tenant.pk
    assert widget.created_at is not None
    assert Widget.objects.count() == 1


def test_update_widget_changes_only_what_it_was_given(tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Before", notes="kept")
    renamed = update_widget(tenant=tenant, actor=owner_actor, widget=widget, name="After")
    renamed.refresh_from_db()
    assert renamed.name == "After"
    assert renamed.notes == "kept"


def test_update_widget_with_nothing_to_do_is_a_no_op(tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Same")
    before = widget.updated_at
    assert update_widget(tenant=tenant, actor=owner_actor, widget=widget).updated_at == before


def test_a_widget_name_is_unique_per_owner_within_a_tenant(
    tenant: Tenant, owner_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Only one")
    with pytest.raises(Invalid):
        create_widget(tenant=tenant, actor=owner_actor, name="Only one")


def test_the_same_owner_may_reuse_a_name_in_another_tenant(
    tenant: Tenant, other_tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Shared name")
    # The same person, acting in a tenant they also belong to: the name is free again.
    create_widget(tenant=other_tenant, actor=acting_in(owner, other_tenant), name="Shared name")
    assert Widget.objects.count() == 2


def test_for_tenant_returns_only_that_tenants_rows(
    tenant: Tenant, other_tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    mine = create_widget(tenant=tenant, actor=owner_actor, name="Mine")
    theirs = create_widget(tenant=other_tenant, actor=acting_in(owner, other_tenant), name="Theirs")
    assert list(Widget.objects.for_tenant(tenant)) == [mine]
    assert list(Widget.objects.for_tenant(other_tenant)) == [theirs]


def test_for_tenant_with_no_tenant_returns_nothing(tenant: Tenant, owner_actor: Actor) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Present")
    assert Widget.objects.for_tenant(None).count() == 0
    assert Widget.objects.count() == 1


def test_delete_widget_removes_the_row(tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Doomed")
    delete_widget(tenant=tenant, actor=owner_actor, widget=widget)
    assert Widget.objects.count() == 0


# golden: noun end


# --- Authorization: the service's half, not the door's ----------------------


# golden: noun begin
def test_a_member_may_touch_their_own(tenant: Tenant, member_actor: Actor) -> None:
    mine = create_widget(tenant=tenant, actor=member_actor, name="Mine")
    assert update_widget(tenant=tenant, actor=member_actor, widget=mine, name="Still mine")


def test_a_member_may_not_update_somebody_elses_widget(
    tenant: Tenant, owner_actor: Actor, member_actor: Actor
) -> None:
    theirs = create_widget(tenant=tenant, actor=owner_actor, name="Not yours")
    with pytest.raises(Forbidden):
        update_widget(tenant=tenant, actor=member_actor, widget=theirs, name="Mine now")
    theirs.refresh_from_db()
    assert theirs.name == "Not yours"


def test_a_member_may_not_delete_somebody_elses_widget(
    tenant: Tenant, owner_actor: Actor, member_actor: Actor
) -> None:
    theirs = create_widget(tenant=tenant, actor=owner_actor, name="Not yours")
    with pytest.raises(Forbidden):
        delete_widget(tenant=tenant, actor=member_actor, widget=theirs)
    assert Widget.objects.count() == 1


def test_an_admin_may_touch_anybodys(
    tenant: Tenant, owner_actor: Actor, admin_actor: Actor
) -> None:
    theirs = create_widget(tenant=tenant, actor=owner_actor, name="Someone else's")
    assert update_widget(tenant=tenant, actor=admin_actor, widget=theirs, name="Moderated")
    delete_widget(tenant=tenant, actor=admin_actor, widget=theirs)
    assert Widget.objects.count() == 0


# golden: noun end


@pytest.mark.parametrize("write", ["update", "delete", "onboard"])
def test_a_widget_outside_the_hat_is_not_found_and_untouched(
    tenant: Tenant, owner_actor: Actor, write: str
) -> None:
    """A row the hat could not have reached is `not_found` at the service (rule 26)."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Above the hat")
    branch = create_organization(
        tenant=tenant, parent=widget.organization, name="Branch", slug="branch", actor=owner_actor
    )
    below = actor_for(user=owner_actor.user, tenant=tenant, org=branch)
    calls = {
        "update": lambda: update_widget(tenant=tenant, actor=below, widget=widget, name="Renamed"),
        "delete": lambda: delete_widget(tenant=tenant, actor=below, widget=widget),
        "onboard": lambda: services.mark_widget_onboarded(
            tenant=tenant, actor=below, widget=widget
        ),
    }
    with pytest.raises(NotFound):
        calls[write]()
    widget.refresh_from_db()
    assert (widget.name, widget.onboarded_at) == ("Above the hat", None)


# --- Saying what happened ----------------------------------------------------


def test_a_write_publishes_its_declared_event(
    tenant: Tenant, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[tuple[str, dict[str, Any]]] = []

    def spy(name: str, *, tenant: Tenant, payload: dict[str, Any], actor: Any = None) -> None:
        published.append((name, payload))

    monkeypatch.setitem(bridge_registry, EMIT, spy)

    widget = create_widget(tenant=tenant, actor=owner_actor, name="Announced")
    update_widget(tenant=tenant, actor=owner_actor, widget=widget, name="Renamed")
    delete_widget(tenant=tenant, actor=owner_actor, widget=widget)

    assert [name for name, _payload in published] == [
        WIDGET_CREATED,
        WIDGET_UPDATED,
        WIDGET_DELETED,
    ]
    # The payload is the schema a REST client gets, minus the per-viewer fields.
    created = published[0][1]
    assert created["id"] == str(widget.pk)
    # A person's fields are the doors' alone; an event names the owner by `owner_id`.
    assert not {"owner_email", "owner_name"} & set(created)
    assert set(created) == set(WidgetOut.model_fields) - PER_VIEWER_FIELDS - {
        "owner_email",
        "owner_name",
    }
    assert "allowed_acts" not in created


# golden: noun begin
def test_an_event_with_nowhere_to_go_does_not_fail_the_write(
    tenant: Tenant, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    """Nothing registered under `events.emit` is the state of a tree without the spine."""
    settings.BRIDGE_STRICT = False  # opt-out: a stripped tree's no-op is the subject
    monkeypatch.delitem(bridge_registry, EMIT, raising=False)

    widget = create_widget(tenant=tenant, actor=owner_actor, name="Unheard")

    assert Widget.objects.for_tenant(tenant).get(pk=widget.pk).name == "Unheard"
    assert not _events(tenant).filter(name=WIDGET_CREATED).exists()


def test_the_event_reaches_the_spine_when_it_is_installed(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The other half: with `apps.events` registered, the row and the event land together."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Heard")

    event = _events(tenant).get(name=WIDGET_CREATED)
    assert event.tenant_id == tenant.pk
    assert event.payload["id"] == str(widget.pk)
    assert event.actor_user_id == owner_actor.user_id
    assert event.actor_kind == "human"


# golden: noun end


def test_the_names_published_are_the_ones_the_app_declares() -> None:
    """An event name is a published contract, so it is a constant, never a literal."""
    source = Path(services.__file__).read_text()
    for name in (WIDGET_CREATED, WIDGET_UPDATED, WIDGET_DELETED, WIDGET_ONBOARDED):
        assert f'"{name}"' not in source, f"{name} is a literal in services.py"


# --- The onboarding writes ---------------------------------------------------


def test_marking_a_widget_onboarded_is_idempotent(tenant: Tenant, owner_actor: Actor) -> None:
    """Temporal runs an activity at least once; a retry must not move the mark."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Twice")

    first = services.mark_widget_onboarded(tenant=tenant, actor=owner_actor, widget=widget)
    again = services.mark_widget_onboarded(tenant=tenant, actor=owner_actor, widget=first)

    assert first.onboarded_at is not None
    assert again.onboarded_at == first.onboarded_at


def test_announcing_carries_the_outcome_of_the_wait(
    tenant: Tenant, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[tuple[str, dict[str, Any]]] = []

    def spy(name: str, *, tenant: Tenant, payload: dict[str, Any], actor: Any = None) -> None:
        published.append((name, payload))

    monkeypatch.setitem(bridge_registry, EMIT, spy)

    widget = create_widget(tenant=tenant, actor=owner_actor, name="Waited for")
    services.mark_widget_onboarded(tenant=tenant, actor=owner_actor, widget=widget)
    services.announce_widget_onboarded(
        tenant=tenant, actor=owner_actor, widget=widget, approved=False
    )

    name, payload = published[-1]
    assert name == WIDGET_ONBOARDED
    # Nobody approved, and the event says so rather than hiding it.
    assert payload["approved"] is False
    assert payload["onboarded_at"] is not None


def test_onboarding_is_authorized_like_every_other_write(
    tenant: Tenant, owner_actor: Actor, member_actor: Actor
) -> None:
    """A plain member may not onboard somebody else's widget."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Not theirs")
    with pytest.raises(Forbidden):
        services.mark_widget_onboarded(tenant=tenant, actor=member_actor, widget=widget)


def test_the_system_may_onboard(tenant: Tenant, owner_actor: Actor) -> None:
    """What the activity does, with the actor the activity uses: the system, at the run's hat."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="System's")
    marked = services.mark_widget_onboarded(
        tenant=tenant, actor=system_actor(tenant, org=widget.organization), widget=widget
    )
    assert marked.onboarded_at is not None


# --- When nobody is listening -------------------------------------------------


# golden: noun begin
@pytest.fixture
def no_event_bus(settings: Any) -> Iterator[None]:
    """The state of a tree that has been stripped back: the name is empty."""
    settings.BRIDGE_STRICT = False  # opt-out: a stripped tree's no-op is the subject
    saved = registered_listeners()
    clear_bridge()
    try:
        yield
    finally:
        clear_bridge()
        for name, registered in saved.items():
            register_listener(name, registered)


def test_publish_says_nobody_heard_it_when_nobody_did(
    tenant: Tenant, owner_actor: Actor, no_event_bus: None
) -> None:
    """The return value is a fact, and this is the fact it was getting wrong."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Into the void")

    assert (
        services._publish_widget(WIDGET_UPDATED, tenant=tenant, widget=widget, actor=owner_actor)
        is False
    )


def test_an_unheard_event_is_a_log_line_and_not_a_failed_write(
    tenant: Tenant,
    owner_actor: Actor,
    no_event_bus: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Create succeeds, the line names the event, and no Event row lands."""
    configure()
    with caplog.at_level(logging.INFO):
        widget = create_widget(tenant=tenant, actor=owner_actor, name="Unheard of")

    assert Widget.objects.for_tenant(tenant).get(pk=widget.pk).name == "Unheard of"
    assert not _events(tenant).exists()

    lines = [
        json.loads(record.getMessage())
        for record in caplog.records
        if "example.event.unpublished" in record.getMessage()
    ]
    assert lines, "the service said nothing about an event nobody heard"
    assert lines[0]["event_name"] == WIDGET_CREATED
    assert lines[0]["widget_id"] == str(widget.pk)


# golden: noun end


def test_a_deployment_that_lost_its_spine_refuses_the_write(
    tenant: Tenant,
    owner_actor: Actor,
    no_event_bus: None,
    settings: Any,
) -> None:
    """The production half. `BRIDGE_STRICT` is what a product sets to test it."""
    settings.BRIDGE_STRICT = True

    with pytest.raises(BridgeNotRegistered):
        create_widget(tenant=tenant, actor=owner_actor, name="Never happened")

    assert not Widget.objects.for_tenant(tenant).filter(name="Never happened").exists()
    # And the audit does not claim it worked: its row is outside the rolled-back transaction.
    entries = AuditEntry.objects.for_tenant(tenant).filter(action="example.create_widget")
    assert [entry.outcome for entry in entries] == ["error"]


# golden: child entry begin
# --- The ledger is append-only, and the population is discovered --------------


def test_the_ledger_declares_itself_append_only_and_is_discovered() -> None:
    """`WidgetEntry` is in the append-only population without anybody listing it."""
    from pilecap.testing import append_only_models, is_append_only

    assert is_append_only(WidgetEntry)
    assert WidgetEntry in append_only_models()
    # And the negative, so the helper is not simply answering yes.
    assert not is_append_only(Widget)


# golden: child entry end
def test_the_services_this_app_offers_are_these_and_no_others() -> None:
    """A pin on the public surface — which is how "no write-back door" stays true."""
    import inspect

    from apps.example import services as module

    public = {
        name
        for name, value in vars(module).items()
        if not name.startswith("_")
        and inspect.isfunction(value)
        and value.__module__ == module.__name__
    }
    assert public == {
        "create_widget",
        "update_widget",
        "delete_widget",
        "approve_widget",
        "mark_widget_onboarded",
        "announce_widget_onboarded",
        "mark_widget_reminded",
        "confirm_widget_onboarding",
        "create_widget_policy",
        "record_widget_entry",
        "archive_widget",
        "restore_widget",
        "move_widget",
        "duplicate_widget",
        "merge_widget",
        "touch_widget",
        "transition_widget",
        "archive_widget_policy",
        "restore_widget_policy",
    }, public


# golden: child entry begin
def test_the_landing_gate_refuses_a_row_that_disagrees_with_its_widget(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The gate at the model tier, where it actually lives."""
    from django.core.exceptions import ValidationError

    from apps.example.models import WidgetEntry as Entry
    from pilecap.tenancy import create_organization

    root = root_organization(tenant=tenant)
    elsewhere = create_organization(
        tenant=tenant, parent=root, name="Elsewhere", slug="elsewhere", actor=owner_actor
    )
    widget = create_widget(tenant=tenant, actor=owner_actor, name="At the root")

    misfiled = Entry(tenant=tenant, organization=elsewhere, widget=widget, note="wrong desk")
    with pytest.raises(ValidationError) as raised:
        misfiled.full_clean()
    assert "organization" in raised.value.message_dict

    # And the same row filed correctly validates.
    Entry(tenant=tenant, organization=root, widget=widget, note="right desk").full_clean()


# golden: child entry end
# golden: verb touch begin
def test_a_touch_moves_updated_at_and_says_so_on_every_press(
    tenant: Tenant, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[str] = []

    def spy(name: str, *, tenant: Tenant, payload: dict[str, Any], actor: Any = None) -> None:
        published.append(name)

    monkeypatch.setitem(bridge_registry, EMIT, spy)
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Seen")
    first = touch_widget(tenant=tenant, actor=owner_actor, widget=widget)
    again = touch_widget(tenant=tenant, actor=owner_actor, widget=first)
    assert widget.updated_at < first.updated_at < again.updated_at
    assert again.name == "Seen"
    assert published.count(WIDGET_TOUCHED) == 2


def test_an_archived_widget_refuses_a_touch(tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Gone")
    archive_widget(tenant=tenant, actor=owner_actor, widget=widget)
    with pytest.raises(Archived):
        touch_widget(tenant=tenant, actor=owner_actor, widget=widget)


# golden: verb touch end
# golden: enum status begin
def test_a_status_starts_first_and_moves_one_step_at_a_time(
    tenant: Tenant, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Staged")
    assert widget.status == Widget.Status.DRAFT
    for status in (Widget.Status.ACTIVE, Widget.Status.RETIRED):
        widget = transition_widget(tenant=tenant, actor=owner_actor, widget=widget, status=status)
        assert widget.status == status
    widget.refresh_from_db()
    assert widget.status == Widget.Status.RETIRED


@pytest.mark.parametrize(
    ("before", "to"),
    [
        ((), Widget.Status.RETIRED),
        ((), Widget.Status.DRAFT),
        ((Widget.Status.ACTIVE,), Widget.Status.DRAFT),
    ],
)
def test_a_status_move_off_the_one_step_is_refused_and_changes_nothing(
    tenant: Tenant, owner_actor: Actor, before: tuple[str, ...], to: str
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Staged")
    for status in before:
        widget = transition_widget(tenant=tenant, actor=owner_actor, widget=widget, status=status)
    with pytest.raises(Conflict):
        transition_widget(tenant=tenant, actor=owner_actor, widget=widget, status=to)
    stayed = widget.status
    widget.refresh_from_db()
    assert widget.status == stayed


def test_a_status_the_noun_does_not_have_is_invalid(tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Staged")
    with pytest.raises(Invalid) as refused:
        transition_widget(tenant=tenant, actor=owner_actor, widget=widget, status="nowhere")
    assert "status" in refused.value.errors


# golden: enum status end


# --- The due date: set at create, changed, cleared, and carried on the event ----

# golden: noun begin
# golden: field due_at begin
DUE_AT = datetime(2026, 11, 2, 17, 0, tzinfo=UTC)
LATER_DUE_AT = datetime(2026, 12, 1, 9, 30, tzinfo=UTC)
DUE_AT_WIRE = "2026-11-02T17:00:00Z"


def test_a_widget_is_created_with_its_due_at(tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Due", due_at=DUE_AT)
    widget.refresh_from_db()
    assert widget.due_at == DUE_AT


def test_due_at_is_changed_and_an_omitted_one_is_left_alone(
    tenant: Tenant, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Due", due_at=DUE_AT)
    update_widget(tenant=tenant, actor=owner_actor, widget=widget, due_at=LATER_DUE_AT)
    widget.refresh_from_db()
    assert widget.due_at == LATER_DUE_AT

    update_widget(tenant=tenant, actor=owner_actor, widget=widget, name="Renamed")
    widget.refresh_from_db()
    assert widget.due_at == LATER_DUE_AT


def test_due_at_is_cleared_only_when_clearing_is_asked_for(
    tenant: Tenant, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Due", due_at=DUE_AT)
    update_widget(tenant=tenant, actor=owner_actor, widget=widget, due_at=None)
    widget.refresh_from_db()
    assert widget.due_at == DUE_AT

    update_widget(tenant=tenant, actor=owner_actor, widget=widget, clear_due_at=True)
    widget.refresh_from_db()
    assert widget.due_at is None


def test_setting_and_clearing_due_at_at_once_is_refused(tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Due", due_at=DUE_AT)
    with pytest.raises(Invalid) as refused:
        update_widget(
            tenant=tenant, actor=owner_actor, widget=widget, due_at=LATER_DUE_AT, clear_due_at=True
        )
    assert "due_at" in refused.value.errors
    widget.refresh_from_db()
    assert widget.due_at == DUE_AT


def test_the_updated_event_carries_due_at(
    tenant: Tenant, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[tuple[str, dict[str, Any]]] = []

    def spy(name: str, *, tenant: Tenant, payload: dict[str, Any], actor: Any = None) -> None:
        published.append((name, payload))

    monkeypatch.setitem(bridge_registry, EMIT, spy)
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Due")
    update_widget(tenant=tenant, actor=owner_actor, widget=widget, due_at=DUE_AT)

    name, payload = published[-1]
    assert name == WIDGET_UPDATED
    assert payload["due_at"] == DUE_AT_WIRE


# golden: field due_at end
# golden: noun end


def test_a_stale_due_date_edit_is_refused_and_writes_nothing(
    tenant: Tenant, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Due", due_at=DUE_AT)
    stale = widget.version
    update_widget(tenant=tenant, actor=owner_actor, widget=widget, version=stale, notes="moved")
    with pytest.raises(StaleVersion):
        update_widget(
            tenant=tenant, actor=owner_actor, widget=widget, version=stale, due_at=LATER_DUE_AT
        )
    widget.refresh_from_db()
    assert widget.due_at == DUE_AT
