"""What `emit` promises, and what it refuses.

The properties, not the mechanism: an event row exists after the write, with its
outbox row and its dispatch run; nothing exists after a rollback; another
tenant's events are not visible; an undeclared name is refused before anything
is written; and the payload that lands is the one the REST door would have put
on the wire for the same row.
"""

# names, never reads: docs/product/build-contract.md — a basename `services.__doc__` must name
# as its pointer; the test reads the docstring, never the file

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.test import Client
from ninja import Schema
from ninja.renderers import JSONRenderer
from pydantic import Field

from apps.accounts.models import User
from apps.core.actor import Actor, system_actor
from apps.core.exceptions import Forbidden, Invalid
from apps.core.models import Tenant
from apps.core.schemas import (
    PER_VIEWER_FIELDS,
    event_payload,
    example,
    personal,
    without_personal,
)
from apps.core.service import service
from apps.events import selectors, services
from apps.events.events import ENDPOINT_REGISTERED, declared_names
from apps.events.models import Delivery, Event, Outbox, WebhookEndpoint
from apps.events.schemas import WebhookEndpointOut
from apps.events.tests.bodies import in_the_root
from apps.example.events import WIDGET_CREATED
from apps.example.schemas import WidgetOut
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db


# --- Emitting ----------------------------------------------------------------


def test_emit_writes_the_event_its_outbox_row_and_a_dispatch_run(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """One call, three rows, all in the caller's transaction."""
    event = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant, {"id": "x", "name": "A widget"}),
        actor=owner_actor,
    )

    assert event.name == WIDGET_CREATED
    # House rule: `v` on every payload, so a subscriber can tell v1 from v2
    # without guessing from the keys it finds.
    assert event.payload["v"] == 1
    assert event.actor_kind == "human"

    outbox = Outbox.objects.get(event=event)
    assert outbox.status == Outbox.Status.PENDING
    assert outbox.attempts == 1

    run = WorkflowRun.objects.for_tenant(tenant).get(type=services.DISPATCH_WORKFLOW)
    # House rule 18: deterministic, keyed on the event, so a retried service
    # starts one run and not two.
    assert run.workflow_id == f"{tenant.slug}:events:event:{event.pk}"


def test_an_emit_that_rolls_back_promises_nobody_anything(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The outbox pattern's whole point: no event, no outbox row, no run.

    A service that wrote its row, emitted, and then failed must not leave a
    promise to tell the world about a row that does not exist.
    """

    class Deliberate(Exception):
        pass

    with pytest.raises(Deliberate), transaction.atomic():
        services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload=in_the_root(tenant, {"id": "x"}),
            actor=system_actor(tenant=tenant),
        )
        raise Deliberate

    assert not Event.objects.for_tenant(tenant).exists()
    assert not Outbox.objects.exists()
    assert not WorkflowRun.objects.for_tenant(tenant).exists()


def test_a_payload_carrying_a_per_viewer_field_is_refused_and_writes_nothing(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """`allowed_acts` is what ONE caller may press; an event is broadcast to every
    subscriber. The spine refuses the key before anything is written — no event,
    no outbox row — naming it and the helper that leaves it out."""
    with pytest.raises(ImproperlyConfigured) as raised:
        services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload=in_the_root(tenant, {"id": "x", "allowed_acts": ["restore"]}),
            actor=owner_actor,
        )
    assert "'allowed_acts'" in str(raised.value)
    assert "ActsOut" in str(raised.value)
    assert "event_payload" in str(raised.value)
    assert not Event.objects.for_tenant(tenant).exists()
    assert not Outbox.objects.exists()

    # At any depth: a nested `Out` (a row's children, each with its own acts).
    nested = {"id": "x", "entries": [{"id": "e1", "allowed_acts": ["delete"]}]}
    with pytest.raises(ImproperlyConfigured) as deeper:
        services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload=in_the_root(tenant, nested),
            actor=owner_actor,
        )
    assert "'entries[0].allowed_acts'" in str(deeper.value)
    assert not Event.objects.for_tenant(tenant).exists()


class _PersonOut(Schema):
    """A row naming a person, emitted under a declared name."""

    id: str
    organization_id: str
    email: str = Field(json_schema_extra=personal(example("dana@example.com")))


def test_a_payload_carrying_a_personal_field_is_refused_and_writes_nothing(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """A `personal` field put back after the strip is refused by name."""
    root = in_the_root(tenant)["organization_id"]
    payload = event_payload(_PersonOut(id="x", organization_id=root, email="dana@example.com"))
    assert "email" not in payload
    payload["email"] = "dana@example.com"
    with pytest.raises(ImproperlyConfigured) as raised:
        services.emit(name=WIDGET_CREATED, tenant=tenant, payload=payload, actor=owner_actor)
    assert "'email'" in str(raised.value)
    assert "personal" in str(raised.value)
    assert not Event.objects.for_tenant(tenant).exists()
    assert not Outbox.objects.exists()


def test_an_undeclared_name_is_refused_and_writes_nothing(tenant: Tenant) -> None:
    """A typo reaches no subscriber and would otherwise raise nothing at all."""
    with pytest.raises(Invalid) as raised:
        services.emit(
            name="example.widget.creted",
            tenant=tenant,
            payload=in_the_root(tenant),
            actor=system_actor(tenant=tenant),
        )
    assert "events.py" in raised.value.errors["name"][0]
    assert not Event.objects.for_tenant(tenant).exists()


def test_a_name_from_an_app_that_declares_nothing_is_refused(tenant: Tenant) -> None:
    with pytest.raises(Invalid):
        services.emit(
            name="nosuchapp.thing.happened",
            tenant=tenant,
            payload={},
            actor=system_actor(tenant=tenant),
        )


def test_a_name_that_is_not_three_segments_is_refused(tenant: Tenant) -> None:
    with pytest.raises(Invalid):
        services.emit(
            name="WidgetCreated", tenant=tenant, payload={}, actor=system_actor(tenant=tenant)
        )


def test_the_registry_is_read_from_the_real_apps() -> None:
    """`declared_names` is what `introspect` prints, not a list somebody keeps."""
    declared = declared_names()
    assert WIDGET_CREATED in declared["example"]
    assert ENDPOINT_REGISTERED in declared["events"]


def test_another_tenant_cannot_see_the_event(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor
) -> None:
    mine = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant, {"id": "mine"}),
        actor=system_actor(tenant=tenant),
    )
    services.emit(
        name=WIDGET_CREATED,
        tenant=other_tenant,
        payload=in_the_root(other_tenant, {"id": "theirs"}),
        actor=system_actor(tenant=other_tenant),
    )

    # The system actor, because this test is about WHICH rows each tenant sees —
    # rule 24's question — and `list_events` also asks `event.read` since Phase R
    # (`test_reads_ask.py` is that half's subject). `allows` passes `system` at
    # step 1, so the capability is constant here and the scoping is what moves.
    assert [
        event.pk
        for event in selectors.list_events(tenant=tenant, actor=system_actor(tenant=tenant))
    ] == [mine.pk]
    assert (
        selectors.list_events(tenant=other_tenant, actor=system_actor(tenant=other_tenant)).count()
        == 1
    )
    # Fails closed: no tenant reads an empty table, not the table.
    assert selectors.list_events(tenant=None, actor=system_actor()).count() == 0


def test_the_correlation_chain_is_carried_onto_the_event(tenant: Tenant) -> None:
    """The join key that survives restarts and days (`architecture.md`)."""
    from apps.core import context

    with context.bound(correlation_id="chain-1", door="rest"):
        event = services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload=in_the_root(tenant),
            actor=system_actor(tenant=tenant),
        )

    assert event.correlation_id == "chain-1"
    assert event.causation_id == "chain-1"


def test_the_event_carries_the_trace_core_stamps_on_its_audit_rows(tenant: Tenant) -> None:
    """`emit` stamps `core.service.trace_id()`: the 32 hex digits of the trace it runs in."""
    from opentelemetry import trace

    from apps.core.service import trace_id

    span = trace.NonRecordingSpan(trace.SpanContext(trace_id=0xABC, span_id=0xDEF, is_remote=False))
    with trace.use_span(span):
        inside = services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload=in_the_root(tenant),
            actor=system_actor(tenant=tenant),
        )
        assert inside.trace_id == trace_id() == format(0xABC, "032x")


# --- Subscribers -------------------------------------------------------------


def test_registering_an_endpoint_needs_a_privileged_role(
    tenant: Tenant, member_actor: Actor, admin_actor: Actor
) -> None:
    """An endpoint decides where a copy of everything in the tenant is sent.

    The pair is the point: same tenant, same call, two answers.
    """
    with pytest.raises(Forbidden):
        services.register_endpoint(
            tenant=tenant,
            actor=member_actor,
            url="https://example.com/hook",
            secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
        )

    endpoint = services.register_endpoint(
        tenant=tenant,
        actor=admin_actor,
        url="https://example.com/hook",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    assert endpoint.is_active
    assert Event.objects.for_tenant(tenant).filter(name=ENDPOINT_REGISTERED).count() == 1


def test_the_registered_event_carries_the_endpoint_as_every_door_reads_it(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The payload is the endpoint's `Out`, so the signing key has no field to ride in."""
    endpoint = services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/hook",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    event = Event.objects.for_tenant(tenant).get(name=ENDPOINT_REGISTERED)
    expected = event_payload(WebhookEndpointOut.from_orm(endpoint))
    assert set(event.payload) - {"v"} == set(expected)
    assert event.payload["id"] == expected["id"] == str(endpoint.pk)
    assert "secret" not in json.dumps(event.payload)


def test_the_registered_event_says_its_payload_is_v1(tenant: Tenant, owner_actor: Actor) -> None:
    """The `Out`-shaped payload is the event's first published shape, so it says `v: 1`."""
    services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/hook",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    event = Event.objects.for_tenant(tenant).get(name=ENDPOINT_REGISTERED)
    assert (event.v, event.payload["v"]) == (1, 1)


def test_an_endpoint_with_no_names_wants_everything(tenant: Tenant, owner_actor: Actor) -> None:
    everything = services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/all",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    narrow = services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/one",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
        event_names=[WIDGET_CREATED],
    )

    wanted = selectors.list_endpoints_for(tenant=tenant, name=WIDGET_CREATED)
    assert {endpoint.pk for endpoint in wanted} == {everything.pk, narrow.pk}

    wanted = selectors.list_endpoints_for(tenant=tenant, name=ENDPOINT_REGISTERED)
    assert [endpoint.pk for endpoint in wanted] == [everything.pk]


def test_a_deactivated_endpoint_is_not_delivered_to(tenant: Tenant, owner_actor: Actor) -> None:
    endpoint = services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/hook",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    services.deactivate_endpoint(tenant=tenant, actor=owner_actor, endpoint=endpoint)

    assert selectors.list_endpoints_for(tenant=tenant, name=WIDGET_CREATED) == []


def test_an_endpoint_in_another_tenant_is_invisible(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor, stranger_actor: Actor
) -> None:
    services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/mine",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    services.register_endpoint(
        tenant=other_tenant,
        actor=stranger_actor,
        url="https://example.com/theirs",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )

    assert [
        e.url for e in selectors.list_endpoints(tenant=tenant, actor=system_actor(tenant=tenant))
    ] == ["https://example.com/mine"]


# --- Deliveries and replay ---------------------------------------------------


def test_recording_the_same_attempt_twice_keeps_one_row(tenant: Tenant, owner_actor: Actor) -> None:
    """Temporal runs an activity at least once; the row has to absorb that."""
    endpoint = services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/hook",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    event = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant),
        actor=system_actor(tenant=tenant),
    )

    first = services.record_delivery_attempt(
        tenant=tenant,
        endpoint_id=endpoint.pk,
        event_id=event.pk,
        status=Delivery.Status.FAILED,
        code=500,
    )
    second = services.record_delivery_attempt(
        tenant=tenant,
        endpoint_id=endpoint.pk,
        event_id=event.pk,
        status=Delivery.Status.DELIVERED,
        code=200,
    )

    assert first.pk == second.pk
    assert Delivery.objects.count() == 1
    assert second.attempts == 2
    assert second.delivered_at is not None


def test_giving_up_does_not_rewrite_what_the_server_said(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """N193a: the dead-letter transition records that we stopped, and nothing else.

    `last_code` and `last_error` are one pair about one attempt — the final one
    — which is what `GET /dead-letters/` promises them to be. Writing the
    give-up reason over `last_error` left the row saying `last_code 500` beside
    `last_error "Activity task failed"`: two fields about the same attempt,
    disagreeing, and only one of them true. Six attempts because that is the
    dispatch policy's ceiling and the shape the stranger-run met.
    """
    endpoint = services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/hook",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    event = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant),
        actor=system_actor(tenant=tenant),
    )
    for _ in range(6):
        services.record_delivery_attempt(
            tenant=tenant,
            endpoint_id=endpoint.pk,
            event_id=event.pk,
            status=Delivery.Status.FAILED,
            code=500,
            error="HTTP 500",
        )

    parked = services.dead_letter_delivery(
        tenant=tenant,
        endpoint_id=endpoint.pk,
        event_id=event.pk,
        error="ActivityError: Activity task failed <- DeliveryFailed: HTTP 500",
    )

    parked.refresh_from_db()
    assert parked.status == Delivery.Status.DEAD
    assert parked.dead_lettered_at is not None
    assert parked.attempts == 6
    assert parked.last_code == 500, "the code the server gave is not ours to erase"
    assert parked.last_error == "HTTP 500", "and neither is what it said beside it"


def test_a_delivery_parked_before_any_attempt_was_recorded_still_says_why(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The other half of N193a: not clobbering must not become saying nothing.

    A dispatch can give up on a delivery no attempt was ever recorded for — the
    activity died before it reached `record_delivery_attempt`. The row has no
    answer of its own, so the reason the workflow walked out of the failure is
    the only thing there is to write, and it is written.
    """
    endpoint = services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/hook",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    event = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant),
        actor=system_actor(tenant=tenant),
    )

    parked = services.dead_letter_delivery(
        tenant=tenant,
        endpoint_id=endpoint.pk,
        event_id=event.pk,
        error="ActivityError: Activity task failed <- TimeoutError: StartToClose",
    )

    parked.refresh_from_db()
    assert parked.attempts == 0
    assert parked.last_code is None
    assert "TimeoutError" in parked.last_error


def test_a_replay_re_enqueues_and_starts_a_distinct_run(tenant: Tenant) -> None:
    """Deterministic enough to be idempotent, distinct enough to be a replay."""
    event = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant),
        actor=system_actor(tenant=tenant),
    )
    services.close_outbox(
        tenant=tenant, event_id=event.pk, status=Outbox.Status.FAILED, error="nope"
    )

    services.enqueue_dispatch(tenant=tenant, event_id=event.pk)

    outbox = Outbox.objects.get(event=event)
    assert outbox.attempts == 2
    assert outbox.status == Outbox.Status.PENDING
    ids = set(
        WorkflowRun.objects.for_tenant(tenant)
        .filter(type=services.DISPATCH_WORKFLOW)
        .values_list("workflow_id", flat=True)
    )
    assert ids == {
        f"{tenant.slug}:events:event:{event.pk}",
        f"{tenant.slug}:events:event:{event.pk}.2",
    }


def test_purging_leaves_the_failures_alone(tenant: Tenant) -> None:
    """A failed outbox row is the record of a promise nobody kept."""
    from datetime import timedelta

    from apps.core.time import now

    dispatched = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant, {"n": 1}),
        actor=system_actor(tenant=tenant),
    )
    failed = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant, {"n": 2}),
        actor=system_actor(tenant=tenant),
    )
    services.close_outbox(tenant=tenant, event_id=dispatched.pk, status=Outbox.Status.DISPATCHED)
    services.close_outbox(tenant=tenant, event_id=failed.pk, status=Outbox.Status.FAILED)
    Outbox.objects.filter(event=dispatched).update(dispatched_at=now() - timedelta(days=40))

    swept = services.purge_dispatched_outbox(before=now() - timedelta(days=30), tenant=None)

    assert (swept.label, swept.count) == ("events.Outbox", 1)
    assert list(Outbox.objects.values_list("event_id", flat=True)) == [failed.pk]


def test_the_dispatch_is_handed_the_deployments_retry_floor(
    tenant: Tenant, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The floor rides the run's argument; the dispatch workflow reads no settings (rule 9)."""
    from apps.core import bridge

    started: list[Any] = []
    real_get = bridge.get

    def get(name: str) -> Any:
        if name == bridge.START_WORKFLOW_ON_COMMIT:
            return lambda **kwargs: started.append(kwargs["arg"])
        return real_get(name)

    monkeypatch.setattr(bridge, "get", get)
    settings.TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS = 0.25
    services.emit(
        name=WIDGET_CREATED, tenant=tenant, payload=in_the_root(tenant), actor=system_actor(tenant)
    )
    assert [arg.retry_floor for arg in started] == [0.25]


def test_a_system_actor_may_emit(tenant: Tenant) -> None:
    """A workflow, a schedule and a command act for the product itself."""
    event = services.emit(
        name=WIDGET_CREATED, tenant=tenant, payload=in_the_root(tenant), actor=system_actor(tenant)
    )
    assert event.actor_kind == "system"
    assert event.actor_user_id is None


def test_the_surveyor_can_see_what_never_dispatched(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor
) -> None:
    """Two of the six standing lenses: the outbox, and the dead letters.

    Both cross tenants on purpose — "did anything fail last night" is a question
    about the deployment — and both are the reason the failure states are
    columns rather than log lines.
    """
    delivered = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant, {"n": 1}),
        actor=system_actor(tenant=tenant),
    )
    stuck = services.emit(
        name=WIDGET_CREATED,
        tenant=other_tenant,
        payload=in_the_root(other_tenant, {"n": 2}),
        actor=system_actor(tenant=other_tenant),
    )
    services.close_outbox(tenant=tenant, event_id=delivered.pk, status=Outbox.Status.DISPATCHED)

    assert [row.event_id for row in selectors.list_undispatched_outbox()] == [stuck.pk]

    endpoint = services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/hook",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    services.dead_letter_delivery(
        tenant=tenant, endpoint_id=endpoint.pk, event_id=delivered.pk, error="gone"
    )

    assert [
        d.event_id
        for d in selectors.list_dead_letters(tenant=tenant, actor=system_actor(tenant=tenant))
    ] == [delivered.pk]
    # A tenant sees its own dead letters and nobody else's.
    assert (
        selectors.list_dead_letters(
            tenant=other_tenant, actor=system_actor(tenant=other_tenant)
        ).count()
        == 0
    )


def test_an_endpoint_is_unique_per_tenant_and_url(tenant: Tenant, owner_actor: Actor) -> None:
    services.register_endpoint(
        tenant=tenant,
        actor=owner_actor,
        url="https://example.com/hook",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
    )
    with pytest.raises(Invalid):
        services.register_endpoint(
            tenant=tenant,
            actor=owner_actor,
            url="https://example.com/hook",
            secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
        )
    assert WebhookEndpoint.objects.for_tenant(tenant).count() == 1


# --- What the module says about itself ---------------------------------------
#
# This docstring carried a copy of what `build-contract.md` and the
# conventions skill said about `emit` — that both wrote the name positionally —
# and the copy stayed after both were corrected, so the module's own
# documentation was the last place in the repository still claiming the wrong
# thing. The paragraph is gone. These two hold the replacement to the two
# properties that matter: that it does not re-state the stale claim, and that
# what it does claim is true of the function.


def test_the_module_docstring_makes_no_claim_about_a_positional_emit() -> None:
    """The stale-claim grep, as a test — an assertion is checked, a grep is run.

    Anything that reads like `emit("orders.order.created", ...)` is the shape
    that was wrong; so is a sentence about the name being positional. Neither
    may come back, in this docstring or in `emit`'s own.
    """
    docstrings = [services.__doc__ or "", services.emit.__doc__ or ""]
    for text in docstrings:
        assert 'emit("' not in text
        assert "emit('" not in text
        assert "name positional" not in text
        assert "positionally" not in text

    # And the replacement points at the two files rather than reproducing them.
    assert "build-contract.md" in (services.__doc__ or "")
    assert "django-conventions" in (services.__doc__ or "")


def test_emit_is_keyword_only_including_the_name(tenant: Tenant) -> None:
    """The claim the docstring does make, exercised rather than read.

    Two halves, because `@service` refuses positionals twice: the signature it
    checked at import time, and the wrapper that refuses `args` at call time.
    """
    parameters = inspect.signature(services.emit).parameters.values()
    assert parameters, "a signature with no parameters would pass this vacuously"
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in parameters)
    assert "name" in inspect.signature(services.emit).parameters

    with pytest.raises(TypeError):
        # The ignore below is deliberate: the wrong call is the thing under
        # test, and mypy refusing it first is half the property.
        services.emit(WIDGET_CREATED, tenant=tenant, payload={}, actor=system_actor(tenant=tenant))  # type: ignore[call-arg]

    assert Event.objects.for_tenant(tenant).count() == 0, "refused before anything was written"


def test_a_service_with_a_positional_parameter_is_refused_at_import_time() -> None:
    """Why the name cannot quietly become positional again: `@service` refuses.

    The decorator is what makes the docstring's claim structural rather than a
    convention somebody has to remember — so it is worth one test that the
    refusal is real and not a comment.
    """
    with pytest.raises(TypeError, match="positional"):

        @service
        def emit_the_wrong_way(name: str, *, tenant: Tenant) -> None: ...


# --- One instant, one string (ADR core-8) -------------------------------------
#
# `emit` renders its payload through the exact encoder class the REST door
# renders with, so `Event.payload` and a REST body for the same row are one
# rendering rather than two spellings of it. What follows is the property from
# both sides: the literal string a known instant becomes, and same-bytes
# equality across two doors for a real row. The decision is ADR core-8 in
# `docs/product/architecture.md`, the ADR home.


MICROSECONDS = datetime(2026, 8, 20, 12, 34, 56, 123456, tzinfo=UTC)

# What the REST door writes for `MICROSECONDS`: milliseconds, **truncated** and
# not rounded, with the UTC offset spelled `Z`. Written out as a literal rather
# than computed, so this disagrees with the encoder if either of them moves.
AS_THE_DOOR_WRITES_IT = "2026-08-20T12:34:56.123Z"

# Shapes with nothing for the normalisation to do: two timestamps already at or
# under the precision the door keeps, a plain date, strings, numbers, a bool, a
# null, nesting, and a non-ASCII string. Byte-identical in and out, or the
# chokepoint is reshaping payloads it was never asked to touch.
UNTOUCHED: dict[str, Any] = {
    "id": "0f8f8f8f",
    "name": "A widget",
    "listed_on": "2026-08-20",
    "at_the_second": "2026-08-20T12:34:56Z",
    "at_the_millisecond": "2026-08-20T12:34:56.123Z",
    "count": 3,
    "ratio": 1.5,
    "is_active": True,
    "notes": None,
    "tags": ["a", "b"],
    "nested": {"deep": {"still": "here"}, "rows": [{"k": 1}]},
    "unicode": "café — ✓",
}


def stored(tenant: Tenant, event: Event) -> dict[str, Any]:
    """The payload as the database holds it, not as the instance remembers it."""
    return dict(Event.objects.for_tenant(tenant).get(pk=event.pk).payload)


def test_a_microsecond_timestamp_is_stored_the_way_the_rest_door_writes_it(
    tenant: Tenant,
) -> None:
    """W1R4-1, the near half: one instant, one string, whichever way it arrived.

    Both forms are in the payload on purpose. A `datetime` is what a caller
    building a payload by hand hands over; the **string** is what the house form
    hands over, because `model_dump(mode="json")` has already serialised it to
    microseconds — and it is the string that made this a template-wide finding.
    """
    event = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(
            tenant,
            {
                "id": "x",
                "from_pydantic": "2026-08-20T12:34:56.123456Z",
                "from_python": MICROSECONDS,
            },
        ),
        actor=system_actor(tenant=tenant),
    )

    payload = stored(tenant, event)
    assert payload["from_pydantic"] == AS_THE_DOOR_WRITES_IT
    assert payload["from_python"] == AS_THE_DOOR_WRITES_IT
    assert "123456" not in json.dumps(payload), "no microseconds survive the chokepoint"


def test_the_event_and_the_rest_body_for_one_row_are_the_same_bytes(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """W1R4-1, the far half: the claim E3 makes, asserted as a raw `==`.

    A widget is created and read **through its REST door**, so the body on the
    right-hand side is bytes off the wire and not a second `model_dump` written
    here; the service behind that door emits
    `WidgetOut.from_orm(widget).model_dump(mode="json")`, the house form, which
    is the left-hand side. A webhook subscriber holding the payload and a client
    holding the body are looking at one rendering, `created_at` included.

    The door is the example app's, called over HTTP rather than imported: this
    module may not reach into `apps.example.services`, whose own downward call
    into `apps.workflows` would drag the layer contract through an events test.

    **Minus the per-viewer fields** (the lead's R1: an event payload never
    carries one). `allowed_acts` answers what ONE caller may press, and a
    subscriber is somebody else, so the payload is the body with those fields
    taken out — and everything that remains is still one rendering, byte for
    byte.
    """
    api.force_login(owner)
    created = api.post(
        "/api/v1/widgets/",
        data=json.dumps({"name": "Twin", "notes": "hello"}),
        content_type="application/json",
    )
    assert created.status_code == 201, created.content
    widget_id = json.loads(created.content)["id"]

    read = api.get(f"/api/v1/widgets/{widget_id}/")
    assert read.status_code == 200
    body = json.loads(read.content)

    published = list(Event.objects.for_tenant(tenant).filter(name=WIDGET_CREATED))
    assert len(published) == 1
    payload = dict(published[0].payload)
    assert payload.pop("v") == 1

    # The per-viewer fields, derived from `ActsOut` — what a viewer door answers
    # and a broadcast never carries.
    per_viewer = set(PER_VIEWER_FIELDS)
    assert per_viewer <= set(body), "the door answers this viewer's acts"
    assert not per_viewer & set(payload), "an event never carries a per-viewer field"
    body = without_personal(
        WidgetOut, {key: value for key, value in body.items() if key not in per_viewer}
    )
    # The DETAIL also answers the words on the widget (`tags`, read through the
    # tags app): the record's, not the row's, and an event is the row.
    assert body.pop("tags") == []

    assert sorted(payload) == sorted(body), "one row, one key set, both doors"
    assert payload == body, "one row, one rendering, both doors"
    assert payload["created_at"] == body["created_at"], "the half that used to differ"


def test_a_payload_with_nothing_over_precise_in_it_is_stored_byte_identical(
    tenant: Tenant,
) -> None:
    """W1R4-2, the second half: the chokepoint reshapes nothing else.

    Including two timestamp strings the door would have written exactly as they
    arrived — a normalisation that rewrote those would be widening its own
    licence, and a date-shaped string that is not an instant would be next.
    """
    # The branch is part of the body being compared, not something wrapped
    # around it: `emit` refuses a widget event that names none (house rule 59),
    # and what this test is about is that the chokepoint reshapes nothing —
    # so the key has to be inside the dictionary on both sides of the equality.
    untouched = in_the_root(tenant, dict(UNTOUCHED))
    event = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=untouched,
        actor=system_actor(tenant=tenant),
    )

    payload = stored(tenant, event)
    assert payload.pop("v") == 1
    assert payload == untouched
    assert json.dumps(payload, sort_keys=True) == json.dumps(untouched, sort_keys=True)


def test_an_emit_that_rolls_back_still_promises_nobody_anything(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """W1R4-2, the first half: normalising did not move the write out of the transaction.

    The same property as `test_an_emit_that_rolls_back_promises_nobody_anything`,
    re-run with a payload that goes through the encoder on the way in. The
    chokepoint sits inside `emit`, before `record_event`, so it is inside the
    caller's `atomic()` — and a test is what says so.
    """

    class Deliberate(Exception):
        pass

    with pytest.raises(Deliberate), transaction.atomic():
        services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload=in_the_root(tenant, {"id": "x", "at": "2026-08-20T12:34:56.123456Z"}),
            actor=owner_actor,
        )
        raise Deliberate

    assert not Event.objects.for_tenant(tenant).exists()
    assert not Outbox.objects.exists()
    assert not WorkflowRun.objects.for_tenant(tenant).exists()


def test_an_inbound_events_payload_is_stored_exactly_as_it_arrived(tenant: Tenant) -> None:
    """The declared edge of the chokepoint: `record_event` renders nothing.

    An inbound webhook is an event too, and its body is the sender's bytes. If
    `stripe.invoice.paid` said microseconds, the row says microseconds —
    re-rendering somebody else's payload would make the stored copy disagree
    with the signature that was checked over it.
    """
    arrived = {"id": "evt_1", "created": "2026-08-20T12:34:56.123456Z"}

    event = services.record_event(
        tenant=tenant,
        name="stripe.invoice.paid",
        payload=dict(arrived),
        actor=system_actor(tenant=tenant),
    )

    assert stored(tenant, event) == arrived


def test_the_encoder_renders_exactly_as_the_mounted_api_does() -> None:
    """The seam ADR core-8 leaves behind, held shut by an assertion.

    `emit` names `DjangoJSONEncoder` rather than ninja's `NinjaJSONEncoder`,
    because `apps/core/tests/test_exceptions.py` refuses any `ninja` import
    under a `services.py` and that refusal is right: a service that imported the
    REST door's package would be callable from one door of five. The subclass
    only adds `default()` cases for objects a ninja *response* can hold and a
    JSON payload cannot, so the two agree — and "so they agree" is a claim, which
    is why it is asserted here rather than reasoned about in a comment.

    This module may import the door's stack; a `services.py` may not. That is
    the whole trade, and this test is the half that makes it safe: it fails on
    the day the two encoders diverge, which is the day the equality two tests
    above would quietly stop being true.
    """
    from config.api import api as mounted_api

    renderer = mounted_api.renderer
    assert isinstance(renderer, JSONRenderer), "the door renders through ninja's JSONRenderer"
    door_encoder = type(renderer).encoder_class

    assert issubclass(door_encoder, services.DOOR_ENCODER), "one lineage, not two encoders"
    for value in (
        MICROSECONDS,
        MICROSECONDS.date(),
        Decimal("19.9500"),
        uuid4(),
        UNTOUCHED,
        {"v": 1, "at": MICROSECONDS, "rows": [{"at": MICROSECONDS}]},
    ):
        assert json.dumps(value, cls=services.DOOR_ENCODER) == json.dumps(
            value, cls=door_encoder
        ), value


# --- R4-F2 · the narrowing key is a contract, both ways ------------------------


def test_an_org_scoped_kind_without_its_branch_is_refused(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """**R4's F4, as the belt.** A widget belongs to a branch; say which.

    `_subject_organization` reads only the payload's top-level
    `organization_id`, and an absent key becomes NULL — which
    `bridge.group_for` reads as TENANT-WIDE. So an org-scoped row announced
    without its branch is broadcast to every socket in the tenant, while the
    REST list under a sibling hat never shows the row. House rule 59 is the
    static half over emit SITES; this is the half that also catches a body
    assembled somewhere the scan cannot follow.

    The refusal names both halves — the key and the kind — because a caller
    reading `organization_id is required` with no kind beside it cannot tell
    which of the three payloads in the function is wrong.
    """
    with pytest.raises(Invalid) as raised:
        services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload={"id": "x", "name": "A widget"},
            actor=owner_actor,
        )

    message = raised.value.errors["organization_id"][0]
    assert "widget" in message, message
    assert "organization_id" in message, message
    assert not Event.objects.for_tenant(tenant).exists()


def test_an_org_less_kind_with_a_branch_is_refused(tenant: Tenant, owner_actor: Actor) -> None:
    """**R4's F5, as the belt.** The engine being down is nobody's branch.

    The other direction, and it is not symmetry for its own sake:
    `consumers._may_read` answers True for a `None` kind whatever branch the
    frame carries, so a `None`-kind event that names a branch would be the
    widest delivery this product has — every connection in the tenant, and the
    read set skipped. `search.engine.degraded` is the declared `None` on this
    tree and the only honest body for it is one with no branch in it at all.
    """
    from apps.core.services import root_organization
    from apps.search.events import SEARCH_ENGINE_DEGRADED

    where = root_organization(tenant=tenant)

    with pytest.raises(Invalid) as raised:
        services.emit(
            name=SEARCH_ENGINE_DEGRADED,
            tenant=tenant,
            payload={"organization_id": str(where.pk), "engine": "meilisearch"},
            actor=owner_actor,
        )

    message = raised.value.errors["organization_id"][0]
    assert "an org-less event cannot name a branch" in message, message
    assert not Event.objects.for_tenant(tenant).exists()


# --- The service's half of the target check: no I/O inside its transaction -----


def test_a_private_literal_is_refused_by_the_service_without_resolving(
    tenant: Tenant, owner_actor: Actor, no_dns: list[str]
) -> None:
    with pytest.raises(Invalid) as caught:
        services.register_endpoint(tenant=tenant, actor=owner_actor, url="http://10.0.0.1/")
    assert caught.value.errors["url"] == ["The address must use https."]
    with pytest.raises(Invalid) as caught:
        services.register_endpoint(tenant=tenant, actor=owner_actor, url="https://10.0.0.1/")
    assert caught.value.errors["url"] == ["The host is or resolves to a private address."]

    endpoint = services.register_endpoint(
        tenant=tenant, actor=owner_actor, url="https://subscriber.example/hook"
    )
    with pytest.raises(Invalid):
        services.update_endpoint(
            tenant=tenant, actor=owner_actor, endpoint=endpoint, url="https://[::1]/hook"
        )
    assert no_dns == [], "the service resolved a host inside its transaction"
    assert not WebhookEndpoint.objects.for_tenant(tenant).filter(url__contains="10.0.0.1").exists()


def test_the_laptop_valve_lets_the_service_take_localhost(
    tenant: Tenant, owner_actor: Actor, settings: Any
) -> None:
    settings.WEBHOOK_PRIVATE_TARGETS_ALLOWED = True
    endpoint = services.register_endpoint(
        tenant=tenant, actor=owner_actor, url="http://localhost:9000/hook"
    )
    assert endpoint.url == "http://localhost:9000/hook"
