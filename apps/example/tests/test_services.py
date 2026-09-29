"""Services own writes, so services are what the tests drive.

Every call passes `tenant` and `actor`, because that is the signature house
rule 13 requires: the tenant so a write can never be guessed from global state,
the actor so the service — not the door — decides whether it is allowed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.db.models import QuerySet

from apps.accounts.models import User
from apps.core import bridge
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.bridge import BridgeNotRegistered
from apps.core.exceptions import Forbidden, Invalid
from apps.core.models import Tenant
from apps.core.observability import configure
from apps.core.schemas import PER_VIEWER_FIELDS
from apps.core.services import add_membership, root_organization
from apps.example import services
from apps.example.events import (
    WIDGET_CREATED,
    WIDGET_DELETED,
    WIDGET_ONBOARDED,
    WIDGET_UPDATED,
)
from apps.example.models import Widget, WidgetEntry
from apps.example.schemas import WidgetOut
from apps.example.services import create_widget, delete_widget, update_widget

pytestmark = pytest.mark.django_db


def _events(tenant: Tenant) -> QuerySet[Any]:
    """This tenant's rows in the event spine, if the spine is installed.

    Through the app registry rather than `from apps.events.models import Event`:
    `events` is deliberately absent from this app's `depends_on` (house rule 7),
    because the app reaches the spine through `core.bridge` and never by import.
    A test that imported what the code refuses to import would be proving
    something the code cannot do.
    """
    return django_apps.get_model("events", "Event").objects.for_tenant(tenant)


def acting_in(user: User, tenant: Tenant) -> Actor:
    """The same person, genuinely joined to a second tenant.

    Set-up has to be legitimate now that services authorize: a test that wanted
    a row in another tenant used to write one, and would now be proving that
    authorization works rather than the thing it was about.
    """
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
    # The same person, acting in a tenant they also belong to: the uniqueness
    # constraint carries `tenant`, so the name is free again.
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


# --- Authorization: the service's half, not the door's ----------------------


def test_a_member_may_not_touch_somebody_elses_widget(
    tenant: Tenant, owner_actor: Actor, member_actor: Actor
) -> None:
    theirs = create_widget(tenant=tenant, actor=owner_actor, name="Not yours")
    with pytest.raises(Forbidden):
        update_widget(tenant=tenant, actor=member_actor, widget=theirs, name="Mine now")
    with pytest.raises(Forbidden):
        delete_widget(tenant=tenant, actor=member_actor, widget=theirs)
    assert Widget.objects.count() == 1


def test_a_member_may_touch_their_own(tenant: Tenant, member_actor: Actor) -> None:
    mine = create_widget(tenant=tenant, actor=member_actor, name="Mine")
    assert update_widget(tenant=tenant, actor=member_actor, widget=mine, name="Still mine")


def test_an_admin_may_touch_anybodys(
    tenant: Tenant, owner_actor: Actor, admin_actor: Actor
) -> None:
    theirs = create_widget(tenant=tenant, actor=owner_actor, name="Someone else's")
    assert update_widget(tenant=tenant, actor=admin_actor, widget=theirs, name="Moderated")
    delete_widget(tenant=tenant, actor=admin_actor, widget=theirs)
    assert Widget.objects.count() == 0


# --- Saying what happened ----------------------------------------------------
#
# `apps/events` is a later rung, so what is asserted here is the *service's*
# half of the contract: it publishes the declared name, with the read schema as
# the payload, inside the write's transaction — and it does not fail the
# customer's write when nothing is listening.


def test_a_write_publishes_its_declared_event(
    tenant: Tenant, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[tuple[str, dict[str, Any]]] = []

    def spy(name: str, *, tenant: Tenant, payload: dict[str, Any], actor: Any = None) -> None:
        published.append((name, payload))

    monkeypatch.setattr(services, "_event_bus", lambda: spy)

    widget = create_widget(tenant=tenant, actor=owner_actor, name="Announced")
    update_widget(tenant=tenant, actor=owner_actor, widget=widget, name="Renamed")
    delete_widget(tenant=tenant, actor=owner_actor, widget=widget)

    assert [name for name, _payload in published] == [
        WIDGET_CREATED,
        WIDGET_UPDATED,
        WIDGET_DELETED,
    ]
    # The payload is the schema a REST client gets, so a webhook subscriber and
    # an API client see one shape for one fact — minus the fields that answer
    # ONE viewer (`allowed_acts`), because a subscriber is somebody else.
    created = published[0][1]
    assert created["id"] == str(widget.pk)
    assert created["owner_email"] == owner_actor.user.email  # type: ignore[union-attr]
    assert set(created) == set(WidgetOut.model_fields) - PER_VIEWER_FIELDS
    assert "allowed_acts" not in created


def test_an_event_with_nowhere_to_go_does_not_fail_the_write(
    tenant: Tenant, owner_actor: Actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing registered under `events.emit` is the state of a tree without the spine.

    A template that refused to create a widget because a webhook had nowhere to
    go would be a template nobody could run. The registration is taken away
    rather than the app uninstalled, because that is the state a stripped
    template is actually in: `core.bridge` is there and its name is empty.
    """
    monkeypatch.delitem(bridge._registry, bridge.EMIT, raising=False)

    widget = create_widget(tenant=tenant, actor=owner_actor, name="Unheard")

    assert Widget.objects.for_tenant(tenant).get(pk=widget.pk).name == "Unheard"
    assert not _events(tenant).filter(name=WIDGET_CREATED).exists()


def test_the_event_reaches_the_spine_when_it_is_installed(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The other half: with `apps.events` registered, the row and the event land together.

    The name and the tenant are the assertion, and the payload is the schema a
    REST client gets — a webhook subscriber and an API client see one shape for
    one fact.
    """
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Heard")

    event = _events(tenant).get(name=WIDGET_CREATED)
    assert event.tenant_id == tenant.pk
    assert event.payload["id"] == str(widget.pk)
    assert event.actor_user_id == owner_actor.user_id
    assert event.actor_kind == "human"


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

    monkeypatch.setattr(services, "_event_bus", lambda: spy)

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
    """A plain member may not onboard somebody else's widget.

    The activity acts as the system, which `core.authz` lets through before it
    reads a policy at all — so the check that matters is this one: the day a
    person is given the button, the rule is already written and already tested.
    """
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Not theirs")
    with pytest.raises(Forbidden):
        services.mark_widget_onboarded(tenant=tenant, actor=member_actor, widget=widget)


def test_the_system_may_onboard(tenant: Tenant, owner_actor: Actor) -> None:
    """What the activity does, with the actor the activity uses."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="System's")
    marked = services.mark_widget_onboarded(
        tenant=tenant, actor=system_actor(tenant), widget=widget
    )
    assert marked.onboarded_at is not None


# --- When nobody is listening -------------------------------------------------
#
# `_publish` returns "did anybody hear this", and it used to lie.
# `bridge.get()` never returns `None` — with nothing registered it returns a
# logging no-op — so the `callable()` branch below it could not fail, the
# `example.event.unpublished` line was unreachable, and every caller was told
# `True` in a tree that had published nothing. These are the two answers that
# were missing: a template with no spine says so, and a deployment that has lost
# its spine refuses the write rather than dropping the event.


@pytest.fixture
def no_event_bus() -> Iterator[None]:
    """The state of a tree that has been stripped back: the name is empty.

    `bridge.clear()` rather than uninstalling `apps.events`, because that is the
    honest shape of the absence — `core.bridge` is there and nothing filled it.
    Everything is put back afterwards, registration by registration, so no other
    test inherits a spine-less tree.
    """
    saved = bridge.registered()
    bridge.clear()
    try:
        yield
    finally:
        bridge.clear()
        for name, registered in saved.items():
            bridge.register(name, registered)


def test_publish_says_nobody_heard_it_when_nobody_did(
    tenant: Tenant, owner_actor: Actor, no_event_bus: None
) -> None:
    """The return value is a fact, and this is the fact it was getting wrong."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Into the void")

    assert (
        services._publish(WIDGET_UPDATED, tenant=tenant, widget=widget, actor=owner_actor) is False
    )


def test_an_unheard_event_is_a_log_line_and_not_a_failed_write(
    tenant: Tenant,
    owner_actor: Actor,
    no_event_bus: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Create succeeds, the line names the event, and no Event row lands.

    A template that refused to create a widget because a webhook had nowhere to
    go would be a template nobody could run — but the log has to say so, or an
    operator whose spine quietly failed to register learns nothing until a
    subscriber complains.
    """
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


def test_a_deployment_that_lost_its_spine_refuses_the_write(
    tenant: Tenant,
    owner_actor: Actor,
    no_event_bus: None,
    settings: Any,
) -> None:
    """The production half. `BRIDGE_STRICT` is what a product sets to test it.

    Dropping an event on the floor in production is the failure mode
    `core.bridge` refuses by design: "the webhooks stopped going out in March"
    is worse than a write that would not complete. So `BridgeNotRegistered`
    propagates out of the service, the transaction rolls back, and there is no
    widget claiming to have been announced.
    """
    settings.BRIDGE_STRICT = True

    with pytest.raises(BridgeNotRegistered):
        create_widget(tenant=tenant, actor=owner_actor, name="Never happened")

    assert not Widget.objects.for_tenant(tenant).filter(name="Never happened").exists()
    # And the audit does not claim it worked. The row is written on the way out
    # of the failure, deliberately *outside* the transaction that rolled back —
    # a record of the failure that disappeared with the failure is no record.
    entries = AuditEntry.objects.for_tenant(tenant).filter(action="example.create_widget")
    assert [entry.outcome for entry in entries] == ["error"]


# --- The ledger is append-only, and the population is discovered --------------


def test_the_ledger_declares_itself_append_only_and_is_discovered() -> None:
    """`WidgetEntry` is in the append-only population without anybody listing it.

    This is the half of house rule 20 that a scan of `services.py` cannot see.
    The rule used to name `AuditEntry` in `rules.yaml`, which is the shape that
    does not survive a product — a witnessed fact, an accrual and a ledger line
    are all the same promise and none of them is called `AuditEntry`. The
    declaration is a class attribute (`append_only = True`, ADR core-6) and the
    population is read off the model registry, so declaring it here is what puts
    this model in scope, in this commit, with no edit to the rules file.

    The gate's own canary for rule 20 is the quality lane's and is not re-run
    here: what this asserts is that the model made itself a *member*.
    """
    from apps.core.models import append_only_models, is_append_only

    assert is_append_only(WidgetEntry)
    assert WidgetEntry in append_only_models()
    # And the negative, so the helper is not simply answering yes: a widget is
    # an ordinary row and gets edited all the time.
    assert not is_append_only(Widget)


def test_the_services_this_app_offers_are_these_and_no_others() -> None:
    """A pin on the public surface — which is how "no write-back door" stays true.

    The claim `WidgetEntry` makes is that nothing anywhere rewrites a line. The
    door half of that is asserted against the routes and the tools
    (`test_network.py`); this is the service half, and it is asserted as a
    *closed set* rather than by grepping for a name, because the way a
    write-back door actually arrives is as a helpfully-named new service that no
    negative assertion anticipated.

    A rung that adds a service changes this line, in the diff, where a reviewer
    sees it — which is the same mechanism the naming lexicon and the budgets
    use, for the same reason.
    """
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
        "create_widget_policy",
        "record_widget_entry",
        "archive_widget",
        "restore_widget",
        "move_widget",
        "duplicate_widget",
        "merge_widget",
        "archive_widget_policy",
        "restore_widget_policy",
    }, public


def test_the_landing_gate_refuses_a_row_that_disagrees_with_its_widget(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The gate at the model tier, where it actually lives.

    `record_widget_entry` derives the organization from the widget, so this
    drives the invariant directly: a row built by hand with the *wrong* branch,
    validated, and refused on the `organization` field. It is the same refusal
    the wire produces in `test_network.py`; asserting it here as well is what
    says the fence is the model's and not the route's — an activity, a
    management command or a future door gets the same answer.
    """
    from django.core.exceptions import ValidationError

    from apps.core.services import create_organization
    from apps.example.models import WidgetEntry as Entry

    root = root_organization(tenant=tenant)
    elsewhere = create_organization(
        tenant=tenant, parent=root, name="Elsewhere", slug="elsewhere", actor=owner_actor
    )
    widget = create_widget(tenant=tenant, actor=owner_actor, name="At the root")

    misfiled = Entry(tenant=tenant, organization=elsewhere, widget=widget, note="wrong desk")
    with pytest.raises(ValidationError) as raised:
        misfiled.full_clean()
    assert "organization" in raised.value.message_dict

    # And the same row filed correctly validates, so the refusal above is the
    # gate and not a broken model.
    Entry(tenant=tenant, organization=root, widget=widget, note="right desk").full_clean()
