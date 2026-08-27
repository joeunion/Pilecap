"""What `@service` guarantees, and what the audit trail is worth.

Five properties, each with a test that can fail:

* a positional-argument service does not import;
* a service may name a parameter `event` — the word structlog reserves for its
  own first argument — and still log;
* one call writes exactly one audit row, carrying the door's bound context;
* a written row cannot be changed or removed by any path;
* the `input` is redacted to the app's `LOG_KEYS` allow-list.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest

from apps.core import context
from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry, AuditImmutable
from apps.core.exceptions import Invalid
from apps.core.log import REDACTED
from apps.core.models import Tenant
from apps.core.observability import configure
from apps.core.service import DEFAULT_LOG_KEYS, INPUT_KEY, redact, service
from apps.core.services import add_membership
from apps.example.models import Widget
from apps.example.services import create_widget, delete_widget

pytestmark = pytest.mark.django_db


# --- Keyword-only, at import time -------------------------------------------


def test_a_positional_service_is_refused_when_it_is_defined() -> None:
    """The failure lands at import, not at the call site that got it wrong.

    Two arguments of the same type in the wrong order is a bug that type
    checking does not catch and a test only catches by luck.
    """
    with pytest.raises(TypeError) as raised:

        @service
        def create_thing(tenant: Tenant, name: str) -> None: ...

    assert "keyword-only" in str(raised.value)
    assert "tenant" in str(raised.value)


def test_a_keyword_only_service_is_accepted() -> None:
    @service
    def create_thing(*, tenant: Tenant, name: str) -> str:
        return name

    assert create_thing(tenant=None, name="fine") == "fine"  # type: ignore[arg-type]


# --- The log line the wrapper writes ----------------------------------------


@service
def _takes_an_event(*, event: str) -> str:
    """A service whose parameter is named the word structlog reserves."""
    return event


@service
def _takes_a_level_and_a_timestamp(*, level: str, timestamp: str) -> str:
    """The other two names structlog's processors own."""
    return f"{level}@{timestamp}"


def test_a_service_may_name_a_parameter_structlog_reserves(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`event` is a perfectly ordinary domain word, and it used to be a `TypeError`.

    `BoundLogger.info(event, **kw)` names its own first parameter `event`, and
    the wrapper used to spread the service's redacted arguments flat into it —
    so any service taking `event=` (or `level`, or `timestamp`) blew up on its
    first call, inside the logging line, before the body ever ran. The arguments
    now ride under one key, so this is structurally impossible.
    """
    configure()
    with caplog.at_level(logging.INFO):
        assert _takes_an_event(event="a-value") == "a-value"

    line: dict[str, Any] = json.loads(caplog.records[-1].getMessage())
    assert line["event"].endswith(".called"), "the event name is still structlog's own"
    assert line[INPUT_KEY] == {"event": REDACTED}


def test_the_other_reserved_names_are_safe_too(caplog: pytest.LogCaptureFixture) -> None:
    configure()
    with caplog.at_level(logging.INFO):
        assert _takes_a_level_and_a_timestamp(level="gold", timestamp="now") == "gold@now"

    line: dict[str, Any] = json.loads(caplog.records[-1].getMessage())
    assert line["level"] == "info", "structlog's own level survived"
    assert line[INPUT_KEY] == {"level": REDACTED, "timestamp": REDACTED}


def test_the_redacted_arguments_are_one_object_a_query_can_name(
    tenant: Tenant, owner_actor: Actor, caplog: pytest.LogCaptureFixture
) -> None:
    """Nesting must not cost the line what it was worth: the values are still there."""
    configure()
    with caplog.at_level(logging.INFO):
        create_widget(tenant=tenant, actor=owner_actor, name="Nested", notes="private")

    called = [
        json.loads(record.getMessage())
        for record in caplog.records
        if '"example.create_widget.called"' in record.getMessage()
    ]
    assert called, "the service logged"
    assert called[-1][INPUT_KEY]["name"] == "Nested"
    assert called[-1][INPUT_KEY]["notes"] == REDACTED


# --- Redaction ---------------------------------------------------------------


def test_redaction_is_an_allow_list_not_a_block_list() -> None:
    redacted = redact(
        {"name": "Widget", "notes": "the customer's private prose", "owner_id": "u-1"},
        frozenset({"name"}),
    )
    assert redacted == {
        "name": "Widget",
        "notes": "[redacted]",
        "owner_id": "u-1",
    }


def test_the_default_allow_list_is_almost_nothing() -> None:
    """A new app gets safety before convenience."""
    assert DEFAULT_LOG_KEYS == frozenset({"name"})
    assert redact({"email": "a@b.c"}, DEFAULT_LOG_KEYS) == {"email": "[redacted]"}


def test_a_model_becomes_its_label_and_key_rather_than_a_copy_of_the_row(
    tenant: Tenant,
) -> None:
    assert redact({"tenant": tenant}, frozenset({"tenant"})) == {
        "tenant": f"core.Tenant:{tenant.pk}"
    }


# --- One row, with the context on it ----------------------------------------


def test_a_service_call_writes_exactly_one_audit_row(tenant: Tenant, owner_actor: Actor) -> None:
    AuditEntry.objects.all().delete()  # the fixtures' own memberships were audited too
    context.bind(
        request_id="r-1",
        session_id="s-1",
        correlation_id="c-1",
        causation_id="c-0",
        door="rest",
    )

    widget = create_widget(tenant=tenant, actor=owner_actor, name="Audited", notes="secret")

    entries = list(AuditEntry.objects.for_tenant(tenant))
    # One row per service *call*, and the call graph is named rather than
    # counted: creating a widget also says what happened (`events.emit`, which
    # writes the event, its outbox row and the run that will dispatch it) and
    # starts its onboarding workflow — and `workflows.record_run` is a service
    # too, once per run. An action appearing here that is not on this list is a
    # write nobody declared, which is exactly what this assertion is for.
    assert sorted(entry.action for entry in entries) == [
        "events.emit",
        "events.enqueue_dispatch",
        "events.record_event",
        "example.create_widget",
        "workflows.record_run",  # the dispatch run
        "workflows.record_run",  # the onboarding run
    ]
    entry = AuditEntry.objects.for_tenant(tenant).get(action="example.create_widget")
    assert entry.action == "example.create_widget"
    assert entry.outcome == AuditEntry.Outcome.OK
    assert entry.error_code == ""
    assert entry.object_type == "example.Widget"
    assert entry.object_id == widget.pk
    assert entry.actor_user_id == owner_actor.user_id
    assert entry.actor_kind == "human"
    # The door's context, which no caller passed to the service.
    assert entry.door == "rest"
    assert entry.request_id == "r-1"
    assert entry.session_id == "s-1"
    assert entry.correlation_id == "c-1"
    assert entry.causation_id == "c-0"
    # Redacted per the app's LOG_KEYS: the name survives, the notes do not.
    assert entry.input["name"] == "Audited"
    assert entry.input["notes"] == "[redacted]"


def test_a_deletion_names_what_went(tenant: Tenant, owner_actor: Actor) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Doomed")
    AuditEntry.objects.all().delete()
    delete_widget(tenant=tenant, actor=owner_actor, widget=widget)

    entry = AuditEntry.objects.for_tenant(tenant).get(action="example.delete_widget")
    assert entry.object_type == "example.Widget"
    assert entry.object_id == widget.pk


def test_a_failed_service_is_recorded_with_the_reason(tenant: Tenant, owner_actor: Actor) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Only one")
    AuditEntry.objects.all().delete()

    with pytest.raises(Invalid):
        create_widget(tenant=tenant, actor=owner_actor, name="Only one")

    entry = AuditEntry.objects.for_tenant(tenant).get()
    assert entry.outcome == AuditEntry.Outcome.ERROR
    assert entry.error_code == "invalid"
    assert entry.object_id is None


def test_a_service_with_no_tenant_writes_no_row(tenant: Tenant) -> None:
    """A write nobody's tenant owns has nothing to scope an audit row to."""
    AuditEntry.objects.all().delete()

    @service
    def housekeeping(*, note: str) -> str:
        return note

    housekeeping(note="tidying")
    assert AuditEntry.objects.count() == 0


def test_a_system_actor_is_recorded_as_the_system(tenant: Tenant) -> None:
    """Work nobody asked for directly is attributed to nobody, on purpose.

    Naming whichever person last touched the process would make the trail read
    plausibly and be false, which is the worst of the three options.
    """
    AuditEntry.objects.all().delete()

    @service
    def reconcile(*, tenant: Tenant, actor: Actor) -> Tenant:
        return tenant

    reconcile(tenant=tenant, actor=system_actor(tenant))

    entry = AuditEntry.objects.for_tenant(tenant).get()
    assert entry.actor_kind == "system"
    assert entry.actor_user_id is None
    assert entry.object_type == "core.Tenant"


# --- Append-only -------------------------------------------------------------


def test_an_audit_row_cannot_be_changed(tenant: Tenant, owner_actor: Actor) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Audited")
    entry = AuditEntry.objects.for_tenant(tenant).filter(action="example.create_widget").get()

    entry.action = "something.else"
    with pytest.raises(AuditImmutable):
        entry.save()

    entry.refresh_from_db()
    assert entry.action == "example.create_widget"


def test_an_audit_row_cannot_be_deleted(tenant: Tenant, owner_actor: Actor) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Audited")
    entry = AuditEntry.objects.for_tenant(tenant).filter(action="example.create_widget").get()

    with pytest.raises(AuditImmutable):
        entry.delete()

    assert AuditEntry.objects.filter(pk=entry.pk).exists()


def test_audit_rows_are_scoped_like_every_other_row(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor, stranger_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="Mine")
    create_widget(tenant=other_tenant, actor=stranger_actor, name="Theirs")

    mine = AuditEntry.objects.for_tenant(tenant).filter(action="example.create_widget")
    assert mine.count() == 1
    assert AuditEntry.objects.for_tenant(None).count() == 0


# --- The writes core itself makes -------------------------------------------


def test_joining_a_tenant_is_audited(tenant: Tenant, nomad: object) -> None:
    AuditEntry.objects.all().delete()
    add_membership(user=nomad, tenant=tenant, actor=system_actor(tenant=tenant))  # type: ignore[arg-type]

    entry = AuditEntry.objects.for_tenant(tenant).get()
    assert entry.action == "core.add_membership"
    assert entry.object_type == "core.Membership"


def test_the_widget_row_and_its_audit_row_land_together(tenant: Tenant, owner_actor: Actor) -> None:
    """One transaction: a widget without its audit row cannot exist."""
    AuditEntry.objects.all().delete()
    create_widget(tenant=tenant, actor=owner_actor, name="Atomic")
    assert Widget.objects.for_tenant(tenant).count() == 1
    audited = AuditEntry.objects.for_tenant(tenant).filter(action="example.create_widget")
    assert audited.count() == 1
