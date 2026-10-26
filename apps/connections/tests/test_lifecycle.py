"""How this app's data dies, and the machine that makes that true.

House rule 31 and ADR core-13: every concrete model declares what happens to
its rows over time, and a `purged` declaration is only worth the line it is
written on if something actually reaches its callable. The rule walks

    purged_by -> an activity that references it
              -> a workflow that executes that activity
              -> a `ScheduleDeclaration` in some app's `SCHEDULES`

and this module is the same chain asserted from inside the app that owns it —
plus the one thing a static walk cannot see: what the sweep actually deletes.

**The finding these tests are shaped around is the one that eats a promise, not
the one that leaves rows lying about.** A purge that keeps too much costs disk;
a purge that sweeps by `created_at` destroys an inbound delivery whose hand-off
had not happened yet, and the provider has already been told 202. So the
population assertions below are stated in both directions every time: what went,
and what is still there.
"""

from __future__ import annotations

import inspect
from typing import Any

from django.conf import settings as django_settings
from django.db import models

from apps.connections import activities, services
from apps.connections.models import Connection, InboundWebhook
from apps.connections.types import PURGE_WORKFLOW, PurgeInboundWebhooks
from apps.connections.workflows import PurgeInboundWebhooksWorkflow
from apps.core.audit import AuditEntry
from apps.core.lifecycle import LifecycleKind, lifecycle_of
from apps.core.models import Tenant
from apps.core.schedules import DAILY, platform_id
from apps.core.time import in_days, now
from apps.core.types import Swept

TASK_QUEUE = "djb-connections-tests"

# Comfortably outside the ninety-day window, and comfortably inside it. Written
# as offsets from the declared retention rather than as bare numbers, so the day
# somebody changes the window these tests still mean what they say.
WELL_PAST = -(activities.INBOUND_WEBHOOK_RETENTION_DAYS + 10)
WELL_INSIDE = -(activities.INBOUND_WEBHOOK_RETENTION_DAYS - 10)


def store(
    *,
    tenant: Tenant,
    connection: Connection,
    delivery_id: str,
    status: str,
    handed_off_days: int | None,
) -> InboundWebhook:
    """One stored delivery, with its hand-off clock put where the test needs it.

    Written straight onto the model rather than through `record_inbound_webhook`
    on purpose: the service hands off, which starts a workflow, and what is
    under test here is the clock and the status — not the receiving path, which
    `test_services.py` already owns.
    """
    row = InboundWebhook.objects.create(
        tenant=tenant,
        connection=connection,
        delivery_id=delivery_id,
        event_type="example.thing.happened",
        body="{}",
        status=status,
    )
    if handed_off_days is not None:
        # `update`, not `save`: this is a test backdating a clock that the
        # service writes in production, and `updated_at` must not move with it.
        InboundWebhook.objects.filter(pk=row.pk).update(
            handed_off_at=in_days(handed_off_days), handed_off_to="events.emit"
        )
        row.refresh_from_db()
    return row


# --- X1-1: what the sweep takes, and what it must not -------------------------


def test_the_purge_takes_processed_deliveries_and_leaves_the_open_promises(
    tenant: Tenant, connection: Connection
) -> None:
    """The whole rung, in one population: three rows in, one row out.

    * `old_processed` — handed off a hundred days ago. Nothing reads it; it is
      somebody else's customer data with no remaining purpose. **Goes.**
    * `recent_processed` — handed off eighty days ago, inside the support
      window in which a human still asks what the provider actually sent.
      **Stays.**
    * `old_unprocessed` — received a hundred days ago and never handed off. An
      OPEN PROMISE: the hand-off has not happened, so a replay still owes
      somebody this delivery. **Stays**, and this is the assertion the whole
      declaration is shaped around — a sweep by `created_at` would take it, and
      the provider was told 202 ninety days ago.
    """
    old_processed = store(
        tenant=tenant,
        connection=connection,
        delivery_id="old-processed",
        status=InboundWebhook.Status.HANDED_OFF,
        handed_off_days=WELL_PAST,
    )
    recent_processed = store(
        tenant=tenant,
        connection=connection,
        delivery_id="recent-processed",
        status=InboundWebhook.Status.HANDED_OFF,
        handed_off_days=WELL_INSIDE,
    )
    old_unprocessed = store(
        tenant=tenant,
        connection=connection,
        delivery_id="old-unprocessed",
        status=InboundWebhook.Status.RECEIVED,
        handed_off_days=None,
    )
    # The `received` row is genuinely old — the point is that its AGE is not
    # what the purge reads.
    InboundWebhook.objects.filter(pk=old_unprocessed.pk).update(created_at=in_days(WELL_PAST))

    removed = services.purge_inbound_webhooks(
        before=in_days(-activities.INBOUND_WEBHOOK_RETENTION_DAYS), tenant=None
    )

    assert removed.count == 1
    surviving = set(InboundWebhook.objects.for_tenant(tenant).values_list("pk", flat=True))
    assert surviving == {recent_processed.pk, old_unprocessed.pk}
    assert not InboundWebhook.objects.for_tenant(tenant).filter(pk=old_processed.pk).exists()
    # And the connection itself is untouched: it is `unbounded` config, not
    # traffic, and nothing in this sweep may reach it.
    assert Connection.objects.for_tenant(tenant).filter(pk=connection.pk).exists()


def test_the_purge_sweeps_a_handled_receipt_and_never_a_failed_one(
    tenant: Tenant, connection: Connection
) -> None:
    """Same age, past the window: `handled` goes, `handler_failed` stays for its replay."""
    handled = store(
        tenant=tenant,
        connection=connection,
        delivery_id="old-handled",
        status=InboundWebhook.Status.HANDLED,
        handed_off_days=WELL_PAST,
    )
    failed = store(
        tenant=tenant,
        connection=connection,
        delivery_id="old-handler-failed",
        status=InboundWebhook.Status.HANDLER_FAILED,
        handed_off_days=WELL_PAST,
    )

    removed = services.purge_inbound_webhooks(
        before=in_days(-activities.INBOUND_WEBHOOK_RETENTION_DAYS), tenant=None
    )

    assert removed.count == 1
    surviving = set(InboundWebhook.objects.for_tenant(tenant).values_list("pk", flat=True))
    assert surviving == {failed.pk}
    assert handled.pk not in surviving


def test_a_second_sweep_in_the_same_window_removes_nothing(
    tenant: Tenant, connection: Connection
) -> None:
    """Idempotence, which Temporal demands of every activity.

    It deletes by age, so the second run finds the same window empty. This is
    not a nicety: a schedule whose overlap policy is SKIP still re-runs after a
    worker restart, and an activity that is retried is an activity that runs
    twice.
    """
    store(
        tenant=tenant,
        connection=connection,
        delivery_id="old-processed",
        status=InboundWebhook.Status.HANDED_OFF,
        handed_off_days=WELL_PAST,
    )
    window = in_days(-activities.INBOUND_WEBHOOK_RETENTION_DAYS)

    assert services.purge_inbound_webhooks(before=window, tenant=None).count == 1
    assert services.purge_inbound_webhooks(before=window, tenant=None).count == 0


def test_a_handed_off_row_with_no_clock_is_never_swept(
    tenant: Tenant, connection: Connection
) -> None:
    """The belt on the null. Postgres excludes NULL from `<`, and that is right.

    `handed_off_at` is written in the same `save()` as the status, so this row
    should not exist — but a purge whose safety depends on that being true for
    ever is a purge with an invariant it does not own. The comparison is what
    makes an unclocked row survive, rather than a check somebody has to
    remember to write.
    """
    row = store(
        tenant=tenant,
        connection=connection,
        delivery_id="clockless",
        status=InboundWebhook.Status.HANDED_OFF,
        handed_off_days=None,
    )

    assert services.purge_inbound_webhooks(before=now(), tenant=None).count == 0
    assert InboundWebhook.objects.for_tenant(tenant).filter(pk=row.pk).exists()


# --- X1-2: the chain rule 31 walks, and the row the run leaves ----------------
#
# The end-to-end half — the declared action started against a real worker —
# lives in `test_workflows.py`, because it needs `transaction=True` and a
# module-wide truncating database would slow every test above it down for one
# test's benefit.


def test_the_purge_leaves_the_platform_audit_row(tenant: Tenant, connection: Connection) -> None:
    """A sweep that ran and said nothing is half of the poller that was never built.

    `@service` audits every service that DECLARES a `tenant` (ADR core-8), and
    `None` is that ADR's named population: the deployment's own actions. So the
    row lands in `for_platform()` and **not** in any tenant's trail — a customer
    reading their own audit page must not find the deployment's housekeeping in
    it, and `for_tenant` fails closed against the null population by design.
    """
    store(
        tenant=tenant,
        connection=connection,
        delivery_id="old-processed",
        status=InboundWebhook.Status.HANDED_OFF,
        handed_off_days=WELL_PAST,
    )
    action = "connections.purge_inbound_webhooks"

    services.purge_inbound_webhooks(
        before=in_days(-activities.INBOUND_WEBHOOK_RETENTION_DAYS), tenant=None
    )

    row = AuditEntry.objects.for_platform().filter(action=action).get()
    assert row.tenant_id is None
    assert row.outcome == AuditEntry.Outcome.OK
    assert row.actor_kind == AuditEntry.Kind.SYSTEM
    assert not AuditEntry.objects.for_tenant(tenant).filter(action=action).exists()


def test_the_schedule_this_app_declares() -> None:
    """Daily under one `platform:connections:purge:<queue>` id; the window rides the action."""
    declaration = activities.PURGE_INBOUND_WEBHOOKS
    schedule = declaration.schedule(TASK_QUEUE)

    action: Any = schedule.action
    expected = platform_id(app="connections", noun="purge", key=TASK_QUEUE)
    assert declaration.schedule_id(TASK_QUEUE) == expected
    assert action.id == expected
    assert action.workflow == PURGE_WORKFLOW
    assert action.task_queue == TASK_QUEUE
    assert action.args == [
        PurgeInboundWebhooks(retention_days=activities.INBOUND_WEBHOOK_RETENTION_DAYS)
    ]
    assert schedule.spec.intervals[0].every == DAILY


def test_two_queues_are_two_schedules_pointing_at_their_own_queue() -> None:
    """A schedule id is global to the namespace, so each queue has its own (ADR events-2)."""
    declaration = activities.PURGE_INBOUND_WEBHOOKS
    one = declaration.schedule_id("djb-alpha")
    two = declaration.schedule_id("djb-beta")

    assert one != two
    assert one.endswith(":djb-alpha")
    assert two.endswith(":djb-beta")


def test_the_purge_workflow_owns_no_run() -> None:
    """House rule 28's other half (ADR workflows-5).

    A schedule-started run has no `WorkflowRun` row to close: no service asked
    for it and nobody is waiting on a visibility row for the deployment's own
    housekeeping. The marker says "I own no row", never "I am exempt".
    """
    assert PurgeInboundWebhooksWorkflow.owns_no_run is True


def test_the_sweep_is_on_the_daily_factorys_one_signature() -> None:
    """ADR core-22 absence 1: `(*, before, tenant: None) -> Swept`, `daily_purge`'s shape."""
    signature = inspect.signature(services.purge_inbound_webhooks, eval_str=True)

    assert list(signature.parameters) == ["before", "tenant"]
    assert {p.kind for p in signature.parameters.values()} == {inspect.Parameter.KEYWORD_ONLY}
    assert signature.parameters["tenant"].annotation is None
    assert signature.return_annotation is Swept


# --- X1-3: the census --------------------------------------------------------


def test_every_table_this_app_owns_declares_how_its_data_dies() -> None:
    """The rung's own half of rule 31's backlog, asserted rather than assumed.

    Not a count: the models are named, so a table added on Thursday fails this
    the moment it is added rather than the day somebody reads the census. That
    is the whole reason the declaration lives on the model.
    """
    from django.apps import apps as django_apps

    declared = {
        model._meta.label: lifecycle_of(model)
        for model in django_apps.get_app_config("connections").get_models()
    }

    assert set(declared) == {"connections.Connection", "connections.InboundWebhook"}
    assert all(one is not None for one in declared.values())
    connection_lifecycle = declared["connections.Connection"]
    webhook_lifecycle = declared["connections.InboundWebhook"]
    assert connection_lifecycle is not None
    assert webhook_lifecycle is not None
    assert connection_lifecycle.kind is LifecycleKind.UNBOUNDED
    assert webhook_lifecycle.kind is LifecycleKind.PURGED


def test_the_unbounded_declaration_carries_a_reason_and_a_dated_trigger() -> None:
    """Unbounded-by-decision and unbounded-by-nobody-thinking look the same in a schema.

    The grammar is enforced at import by `apps.core.lifecycle`; this is the
    coherence half — that the sentence on `Connection` is about THIS table and
    not a paragraph copied off the neighbour. `bounded` would have been the easy
    answer and it would name a cascade that does not exist:
    `TenantScopedModel.tenant` is PROTECT, so nothing here dies with anything.
    The FK is asserted rather than described, because "dies with its tenant" is
    a premise a reader can hold about this whole tree and be wrong about.
    """
    declared = lifecycle_of(Connection)

    assert declared is not None
    assert declared.kind is LifecycleKind.UNBOUNDED
    assert "configuration" in declared.reason
    assert "2026-" in declared.trigger
    assert Connection._meta.get_field("tenant").remote_field.on_delete is models.PROTECT


def test_a_real_cascade_is_still_not_why_the_deliveries_die() -> None:
    """The other half of the same care, and the harder one to see.

    `InboundWebhook.connection` IS a genuine `CASCADE` — the one real cascade in
    this app — so `bounded` would pass every mechanical bar and would still be
    the wrong declaration: the parent it hangs off is `unbounded`, so a bounded
    child of an unbounded parent is a table that grows for ever with extra
    steps. `purged` is the truer kind, and it is the one that obliges somebody
    to write the sweeper.
    """
    field = InboundWebhook._meta.get_field("connection")

    assert field.remote_field.on_delete is models.CASCADE
    parent = lifecycle_of(Connection)
    child = lifecycle_of(InboundWebhook)
    assert parent is not None
    assert child is not None
    assert parent.kind is LifecycleKind.UNBOUNDED
    assert child.kind is LifecycleKind.PURGED


def test_the_task_queue_the_tests_use_is_not_this_checkouts_own() -> None:
    """A guard, not a property: these tests must never touch the real queue."""
    assert TASK_QUEUE != str(django_settings.TEMPORAL_TASK_QUEUE)
