"""`manage.py replay_events` — the recovery path, driven the way an operator does.

The properties: it re-enqueues rather than delivering, it starts a distinct
dispatch run for the replay, it refuses to replay the whole outbox by accident,
and `--dry-run` changes nothing.
"""

from __future__ import annotations

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.actor import system_actor
from apps.core.models import Tenant
from apps.events import services
from apps.events.models import Outbox
from apps.events.tests.bodies import in_the_root
from apps.example.events import WIDGET_CREATED
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db


def test_replaying_one_event_re_enqueues_it(tenant: Tenant) -> None:
    event = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant),
        actor=system_actor(tenant=tenant),
    )
    services.close_outbox(
        tenant=tenant, event_id=event.pk, status=Outbox.Status.FAILED, error="subscriber down"
    )

    out = StringIO()
    call_command("replay_events", "--id", str(event.pk), stdout=out)

    outbox = Outbox.objects.get(event=event)
    assert outbox.status == Outbox.Status.PENDING
    assert outbox.attempts == 2
    assert "re-enqueued 1 row" in out.getvalue()

    ids = set(
        WorkflowRun.objects.for_tenant(tenant)
        .filter(type=services.DISPATCH_WORKFLOW)
        .values_list("workflow_id", flat=True)
    )
    assert ids == {
        f"{tenant.slug}:events:event:{event.pk}",
        f"{tenant.slug}:events:event:{event.pk}.2",
    }


def test_a_dry_run_changes_nothing(tenant: Tenant) -> None:
    event = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant),
        actor=system_actor(tenant=tenant),
    )

    out = StringIO()
    call_command("replay_events", "--id", str(event.pk), "--dry-run", stdout=out)

    assert Outbox.objects.get(event=event).attempts == 1
    assert "would be re-enqueued" in out.getvalue()


def test_replaying_since_a_date_covers_every_tenant(tenant: Tenant, other_tenant: Tenant) -> None:
    """An outage is a deployment-level event, not one customer's."""
    services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant),
        actor=system_actor(tenant=tenant),
    )
    services.emit(
        name=WIDGET_CREATED,
        tenant=other_tenant,
        payload=in_the_root(other_tenant),
        actor=system_actor(tenant=other_tenant),
    )

    out = StringIO()
    call_command("replay_events", "--since", "2000-01-01", stdout=out)

    assert "re-enqueued 2 row" in out.getvalue()
    assert list(Outbox.objects.values_list("attempts", flat=True)) == [2, 2]


def test_failed_only_leaves_the_delivered_ones_alone(tenant: Tenant) -> None:
    done = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant, {"n": 1}),
        actor=system_actor(tenant=tenant),
    )
    stuck = services.emit(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload=in_the_root(tenant, {"n": 2}),
        actor=system_actor(tenant=tenant),
    )
    services.close_outbox(tenant=tenant, event_id=done.pk, status=Outbox.Status.DISPATCHED)

    call_command("replay_events", "--since", "2000-01-01", "--failed-only", stdout=StringIO())

    assert Outbox.objects.get(event=done).attempts == 1
    assert Outbox.objects.get(event=stuck).attempts == 2


def test_replaying_everything_is_not_a_default() -> None:
    with pytest.raises(CommandError):
        call_command("replay_events", stdout=StringIO())


def test_a_bad_date_is_refused_before_anything_is_touched(tenant: Tenant) -> None:
    with pytest.raises(CommandError):
        call_command("replay_events", "--since", "last tuesday", stdout=StringIO())
