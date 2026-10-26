"""The activities on their own: the parts a workflow test would pay wall clock for.

Two things live here rather than in `test_workflows.py`:

* the **retryable** half of delivery — a 503 has to be recorded *and* re-raised,
  so Temporal backs off and tries again. Proving that through six real retries
  would cost the suite a minute of real time for a property that is one call
  deep, so it is proved here, against the activity, in milliseconds.
* the **schedule** — the time-skipping test server has no schedules API, so what
  is proved is the schedule this app declares (a value, read directly) and the
  decisions the engine makes for `activities.PURGE` against a stand-in server,
  **in `deployment` mode**: the legacy un-suffixed id dropped, this queue's id
  created, and a restart updating rather than duplicating. The mode is declared
  by each test that needs it because the suite itself runs in `process` mode
  (ADR platform-lifecycle-1), where none of this happens at all — which is the
  point, and is proved next door in `test_machinery_lifetime.py`.
  That the ids are actually distinct on a real server, and
  that the run one starts completes, is the wire proof documented separately —
  a stand-in cannot prove two deployments do not collide.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.conf import settings as django_settings
from django.db import transaction
from django.test import override_settings
from temporalio.client import Schedule, ScheduleUpdate
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError, RPCStatusCode

from apps.core import bridge
from apps.core.actor import Actor, system_actor
from apps.core.models import Tenant
from apps.core.services import create_organization, root_organization
from apps.core.tests.fakes import FakeScheduleServer
from apps.core.time import now
from apps.events import activities, services
from apps.events.models import Delivery, Event, Outbox, WebhookEndpoint
from apps.events.tests.bodies import in_the_root
from apps.events.types import (
    DeliverWebhook,
    PurgeExpired,
    PushRealtime,
    ReconcileOutbox,
    ReconcileOutcome,
)
from apps.example.events import WIDGET_CREATED
from apps.workflows.client import delete_schedule, ensure_declaration, ensure_schedules
from apps.workflows.models import WorkflowRun
from apps.workflows.services import check_workflow_id, finish_run, record_run, workflow_id

# `transaction=True`: an activity calls `close_old_connections()` at both ends,
# because out in the worker there is no request cycle to do it. Inside the
# wrapping transaction a plain `django_db` test uses, that closes the connection
# the test itself is holding — so these run the way the worker does, against
# real commits.
pytestmark = pytest.mark.django_db(transaction=True)

SECRET = "a-shared-secret"  # noqa: S105 — a signing secret the test both signs and verifies with  # pragma: allowlist secret


@pytest.fixture
def acting(tenant: Tenant, monkeypatch: pytest.MonkeyPatch) -> Tenant:
    """Pretend the workflow interceptor restored this tenant.

    In production the tenant arrives on the workflow's Temporal headers and is
    read back through the bridge. Calling an activity directly, there is no
    workflow, so the one function that reads it is replaced — which is also the
    proof that the tenant is read in exactly one place.
    """
    monkeypatch.setattr(activities, "current_actor", lambda **_: system_actor(tenant))
    return tenant


def _endpoint(tenant: Tenant, url: str = "https://subscriber.example/hook") -> WebhookEndpoint:
    return WebhookEndpoint.objects.create(tenant=tenant, url=url, secret=SECRET)


def test_a_5xx_is_recorded_and_re_raised_so_temporal_retries(
    acting: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The attempt is in the table before the exception leaves the activity."""
    endpoint = _endpoint(acting)
    event = services.record_event(
        tenant=acting, name=WIDGET_CREATED, payload={"v": 1}, actor=system_actor(tenant=acting)
    )
    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))),
    )

    with pytest.raises(activities.DeliveryFailed):
        activities.deliver_webhook(
            DeliverWebhook(event_id=str(event.pk), endpoint_id=str(endpoint.pk))
        )

    delivery = Delivery.objects.get(event=event, endpoint=endpoint)
    assert delivery.status == Delivery.Status.FAILED
    assert delivery.last_code == 503
    assert delivery.attempts == 1
    assert delivery.dead_lettered_at is None


def test_a_network_failure_is_recorded_with_no_status_code(
    acting: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A connection that never opens is a failure with no answer to record."""
    endpoint = _endpoint(acting)
    event = services.record_event(
        tenant=acting, name=WIDGET_CREATED, payload={"v": 1}, actor=system_actor(tenant=acting)
    )

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(refuse)),
    )

    with pytest.raises(activities.DeliveryFailed):
        activities.deliver_webhook(
            DeliverWebhook(event_id=str(event.pk), endpoint_id=str(endpoint.pk))
        )

    delivery = Delivery.objects.get(event=event, endpoint=endpoint)
    assert delivery.last_code is None
    assert "ConnectError" in delivery.last_error


@pytest.mark.parametrize(
    ("code", "retry"),
    [(500, True), (503, True), (429, True), (408, True), (400, False), (404, False), (410, False)],
)
def test_which_answers_are_worth_retrying(code: int, retry: bool) -> None:
    """A 4xx means the request is wrong; sending it again does not fix it."""
    assert activities.is_worth_retrying(code) is retry
    assert activities.is_worth_retrying(None) is True


def test_the_signature_is_over_the_bytes_that_were_sent() -> None:
    """Sign what is sent, not a re-serialisation of what was meant."""
    body = b'{"a":1}'
    signature = activities.sign(secret="k", body=body)  # noqa: S106 — a signing secret the test both signs and verifies with
    assert signature.startswith("sha256=")
    assert activities.sign(secret="k", body=b'{"a": 1}') != signature  # noqa: S106 — a signing secret the test both signs and verifies with
    assert activities.sign(secret="other", body=body) != signature  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret


def test_the_schedule_this_app_declares() -> None:
    """Daily, on this deployment's queue, skipping a run it is late for."""
    schedule = activities.PURGE.schedule("djb-tests")

    action: Any = schedule.action
    assert action.workflow == services.PURGE_WORKFLOW
    assert action.id == "platform:events:purge:djb-tests"
    assert action.task_queue == "djb-tests"
    assert action.args == [
        PurgeExpired(
            outbox_retention_days=activities.outbox_retention_days(),
            delivery_retention_days=activities.delivery_retention_days(),
        )
    ]
    assert schedule.spec.intervals[0].every == timedelta(hours=24)


def test_two_queues_are_two_schedules_pointing_at_their_own_queue() -> None:
    """One dev server, several deployments, no fight: both ids are per queue (ADR events-2)."""
    one = activities.PURGE.schedule_id("djb-alpha")
    two = activities.PURGE.schedule_id("djb-beta")

    assert one == "platform:events:purge:djb-alpha"
    assert two == "platform:events:purge:djb-beta"

    alpha: Any = activities.PURGE.schedule("djb-alpha").action
    beta: Any = activities.PURGE.schedule("djb-beta").action
    assert (alpha.task_queue, beta.task_queue) == ("djb-alpha", "djb-beta")
    assert alpha.id != beta.id
    assert check_workflow_id(id=alpha.id, tenant=None) == alpha.id


def test_the_legacy_global_id_is_the_one_that_used_to_ship() -> None:
    """What is being cleaned up, named — and distinct from every new id."""
    assert activities.PURGE.legacy_ids == ("events-purge-expired",)
    assert activities.LEGACY_PURGE_SCHEDULE_ID != activities.PURGE.schedule_id(
        str(django_settings.TEMPORAL_TASK_QUEUE)
    )


def test_the_retention_window_comes_from_settings(settings: Any) -> None:
    """One reader, and it is `settings` — the variable is declared in
    `config/settings/base.py` with its default and its line in `.env.example`.
    """
    assert django_settings.EVENTS_OUTBOX_RETENTION_DAYS == 30, "the shipped default"
    settings.EVENTS_OUTBOX_RETENTION_DAYS = 7
    assert activities.outbox_retention_days() == 7


#: **The lifetime class these three tests are about** (ADR platform-lifecycle-1).
#:
#: The suite itself runs in `process` mode, where no Schedule object is created
#: at all — so a test about what a durable Schedule does has to say which class
#: it is proving, out loud, rather than inheriting one. The literal is the wire
#: value; `apps/workflows/tests/test_machinery_lifetime.py` pins it against
#: `settings.MACHINERY_DEPLOYMENT` so the two cannot drift.
deployment_machinery = override_settings(TEMPORAL_MACHINERY_LIFETIME="deployment")


@deployment_machinery
@pytest.mark.asyncio
async def test_ensuring_the_schedule_twice_updates_rather_than_duplicates() -> None:
    """A worker restart must converge on one schedule, not add a second."""
    server = FakeScheduleServer()
    client: Any = server
    queue = str(django_settings.TEMPORAL_TASK_QUEUE)

    await ensure_declaration(client, activities.PURGE)
    await ensure_declaration(client, activities.PURGE)

    assert [schedule_id for schedule_id, _ in server.created] == [
        activities.PURGE.schedule_id(queue)
    ]
    assert [schedule_id for schedule_id, _ in server.updated] == [
        activities.PURGE.schedule_id(queue)
    ]
    assert isinstance(server.updated[0][1], Schedule)
    assert isinstance(ScheduleUpdate(schedule=server.updated[0][1]).schedule, Schedule)
    assert server.present == {activities.PURGE.schedule_id(queue)}


@deployment_machinery
@pytest.mark.asyncio
async def test_a_planted_legacy_schedule_is_gone_after_startup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The upgrade path: the un-suffixed schedule an older worker left behind.

    It is deleted, the namespaced one is created in its place, and the deletion
    is logged — a schedule removed from a server nobody can see removed is the
    same problem the schedule-id collision was, one layer along.
    """
    server = FakeScheduleServer(present={activities.LEGACY_PURGE_SCHEDULE_ID})
    client: Any = server
    queue = str(django_settings.TEMPORAL_TASK_QUEUE)

    with caplog.at_level(logging.INFO):
        await ensure_declaration(client, activities.PURGE)

    assert server.deleted == [activities.LEGACY_PURGE_SCHEDULE_ID]
    assert activities.LEGACY_PURGE_SCHEDULE_ID not in server.present
    assert server.present == {activities.PURGE.schedule_id(queue)}
    assert "events.schedule.deleted" in caplog.text
    assert activities.LEGACY_PURGE_SCHEDULE_ID in caplog.text


@pytest.mark.asyncio
async def test_no_legacy_schedule_is_deleted_quietly_and_without_complaint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The common case: a server that never ran an older worker. Idempotent."""
    server = FakeScheduleServer()
    client: Any = server

    with caplog.at_level(logging.INFO):
        assert await delete_schedule(client, activities.LEGACY_PURGE_SCHEDULE_ID) is False
        assert await delete_schedule(client, activities.LEGACY_PURGE_SCHEDULE_ID) is False

    assert server.deleted == []
    assert "events.schedule.deleted" not in caplog.text


@pytest.mark.asyncio
async def test_a_delete_that_fails_for_any_other_reason_is_not_swallowed() -> None:
    """`NOT_FOUND` is the only answer that means "already clean"."""

    class RefusingServer(FakeScheduleServer):
        def _handle(self, schedule_id: str) -> Any:
            class Handle:
                async def delete(self) -> None:
                    raise RPCError("no", RPCStatusCode.PERMISSION_DENIED, b"")

            return Handle()

    client: Any = RefusingServer(present={activities.LEGACY_PURGE_SCHEDULE_ID})
    with pytest.raises(RPCError):
        await delete_schedule(client, activities.LEGACY_PURGE_SCHEDULE_ID)


# --- The relay (ADR events-3) ------------------------------------------------


def stranded(*, tenant: Tenant, age: timedelta) -> Event:
    """One event whose dispatch was enqueued and whose clock is `age` old.

    `record_event` + a hand-set clock rather than `emit`: what is under test is
    the sweep's arithmetic, and building the strand this way keeps the fixture
    honest about the one field it is about.
    """
    event = services.record_event(
        tenant=tenant, name=WIDGET_CREATED, payload={"v": 1}, actor=system_actor(tenant=tenant)
    )
    Outbox.objects.filter(event=event).update(
        status=Outbox.Status.PENDING, attempts=1, next_attempt_at=now() - age
    )
    return event


def sweep(*, batch_size: int = 0, already_seen: int = 0) -> ReconcileOutcome:
    """One relay **batch**, at the grace the schedule carries.

    `batch_size=0` is what a history with no number in it replays as, and it is
    the default here for the same reason it is the default in production: every
    test written before the ceiling existed is still asking the question it was
    asking, against `RECONCILE_BATCH`.
    """
    return activities.reconcile_outbox(
        ReconcileOutbox(
            grace_seconds=activities.outbox_grace_seconds(),
            batch_size=batch_size,
            already_seen=already_seen,
        )
    )


def test_a_row_still_inside_its_grace_is_not_touched(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """First half: a dispatch that is merely young is a dispatch in flight.

    The grace is what "alive" means here. Asking Temporal instead would put the
    product's answer about its own row inside somebody else's visibility API,
    which ADR workflows-5 rejected one table along for the same reason.
    """
    event = stranded(tenant=tenant, age=activities.OUTBOX_GRACE - timedelta(minutes=1))
    before = Outbox.objects.get(event=event)

    assert sweep() == ReconcileOutcome(reconciled=0, unresolved=0)

    after = Outbox.objects.get(event=event)
    assert (after.attempts, after.status) == (before.attempts, before.status)
    assert after.next_attempt_at == before.next_attempt_at


def test_a_swept_row_leaves_the_window_it_was_swept_out_of(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """The relay does not re-sweep what it has just resumed.

    A resume rewrites `next_attempt_at`, which is what makes the activity
    idempotent in the way Temporal demands: the second run of the same sweep
    finds nothing, because the first one moved the clock forward.
    """
    event = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=1))

    assert sweep() == ReconcileOutcome(reconciled=1, unresolved=0)
    assert sweep() == ReconcileOutcome(reconciled=0, unresolved=0)

    outbox = Outbox.objects.get(event=event)
    assert outbox.attempts == 1, "a resume is not an attempt — the id has to stay the id"
    assert outbox.status == Outbox.Status.PENDING


def test_the_relay_says_what_it_swept(
    tenant: Tenant, recorded_workflow_starts: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A count per sweep, structured (house rule 19).

    A relay whose only evidence is the absence of complaints is the finding it
    was built to close, one layer up: an operator has to be able to ask "is it
    running, and is it finding anything" without reading the outbox by hand.
    """
    stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=1))

    with caplog.at_level(logging.INFO):
        assert sweep() == ReconcileOutcome(reconciled=1, unresolved=0)

    assert "events.reconcile.resumed" in caplog.text
    assert "events.reconcile.done" in caplog.text


def test_a_rolled_back_emit_leaves_the_relay_nothing_to_find(tenant: Tenant) -> None:
    """The outbox pattern's promise, re-run against the new module.

    A relay is exactly the pressure that tempts somebody to move the write
    outside the transaction "so it can be recovered". It must not be, and this
    is the pin: a service that raises leaves no event, no outbox row, and
    nothing for a sweep to resume.
    """
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            services.emit(
                name=WIDGET_CREATED,
                tenant=tenant,
                payload=in_the_root(tenant, {"v": 1}),
                actor=system_actor(tenant=tenant),
            )
            raise RuntimeError("the caller failed after saying that something happened")

    assert Event.objects.count() == 0
    assert Outbox.objects.count() == 0
    assert sweep() == ReconcileOutcome(reconciled=0, unresolved=0)


def test_a_row_whose_run_already_finished_is_named_not_re_run(
    tenant: Tenant, recorded_workflow_starts: None, caplog: pytest.LogCaptureFixture
) -> None:
    """The honest half: a resume the ledger will not allow is counted, not faked.

    A `pending` row whose dispatch run has already **finished** cannot be healed
    under the id it claimed — `record_run` refuses to re-run a completed id, and
    it is right to: re-running finished work is a decision about a new key and
    belongs to a human. The relay says so and leaves the row exactly as it found
    it, which is what keeps `manage.py replay_events` the override rather than
    the only recovery.
    """
    event = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=1))
    dispatch_id = workflow_id(tenant=tenant, app="events", noun="event", key=str(event.pk))
    run = record_run(
        tenant=tenant,
        workflow_id=dispatch_id,
        workflow_type=services.DISPATCH_WORKFLOW,
        actor=system_actor(tenant),
    )
    finish_run(tenant=tenant, workflow_id=run.workflow_id, status=WorkflowRun.Status.COMPLETED)
    before = Outbox.objects.get(event=event)

    with caplog.at_level(logging.WARNING):
        assert sweep() == ReconcileOutcome(reconciled=0, unresolved=1)

    assert "events.reconcile.unresolved" in caplog.text
    after = Outbox.objects.get(event=event)
    assert (after.attempts, after.status) == (before.attempts, before.status)
    assert after.next_attempt_at == before.next_attempt_at, (
        "an unresolved row stays visible to the next sweep and to replay_events"
    )


def test_the_drain_stops_at_its_ceiling_and_says_more_remain(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """The drain has a ceiling, and the ceiling is reportable.

    Before this, `reconcile_outbox` walked the whole pending population at nine
    statements a row — 180,000 statements in one execution at the declared
    20,000 pending — so the sweep timed out, Temporal retried it from the head,
    and the oldest promises were the ones it never reached. The fix is a bound
    per execution plus an answer the workflow can loop on; this is both halves,
    with a batch of two so the arithmetic is visible.
    """
    for minutes in (30, 20, 10):
        stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=minutes))

    first = sweep(batch_size=2)
    assert first == ReconcileOutcome(reconciled=2, unresolved=0, more_remaining=True)

    second = sweep(batch_size=2)
    assert second == ReconcileOutcome(reconciled=1, unresolved=0, more_remaining=False)

    assert sweep(batch_size=2) == ReconcileOutcome()


def test_the_oldest_promise_is_in_the_first_batch(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """A ceiling is only safe because the order puts the oldest debt first.

    The `order_by("next_attempt_at")` predates this change; what is new is that it
    has become load-bearing. With no bound, order was a nicety — everything got
    swept eventually. With a bound, order decides *who waits*, and a relay that
    served the newest promises first would starve exactly the rows an outage
    stranded earliest.
    """
    oldest = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=30))
    newer = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=10))
    clocks = {
        event.pk: Outbox.objects.get(event=event).next_attempt_at for event in (oldest, newer)
    }

    assert sweep(batch_size=1) == ReconcileOutcome(reconciled=1, more_remaining=True)

    assert Outbox.objects.get(event=oldest).next_attempt_at != clocks[oldest.pk], (
        "the oldest promise is the one a single-row batch resumes"
    )
    assert Outbox.objects.get(event=newer).next_attempt_at == clocks[newer.pk]


def test_an_unresolved_head_does_not_block_the_batch_behind_it(
    tenant: Tenant, recorded_workflow_starts: None
) -> None:
    """The starvation a ceiling *introduces* if it is added on its own.

    A resumed row leaves the candidate set — its clock is rewritten forward — so
    a bounded drain would advance on its own if every row could be resumed. An
    `unresolved` row cannot be: `record_run` refuses a finished id, the service
    transaction rolls back, and the row stays exactly where it was, at the head
    of an oldest-first read. A batch of nothing but those would be re-read for
    ever, which is a worse failure than the unbounded walk it replaced.

    `already_seen` is what stops it, and the second half of this test is the
    proof that it is load-bearing rather than decorative: the same batch without
    the cursor reads the same refused row again.
    """
    blocked = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=30))
    behind = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=10))
    dispatch_id = workflow_id(tenant=tenant, app="events", noun="event", key=str(blocked.pk))
    run = record_run(
        tenant=tenant,
        workflow_id=dispatch_id,
        workflow_type=services.DISPATCH_WORKFLOW,
        actor=system_actor(tenant),
    )
    finish_run(tenant=tenant, workflow_id=run.workflow_id, status=WorkflowRun.Status.COMPLETED)

    head = sweep(batch_size=1)
    assert head == ReconcileOutcome(reconciled=0, unresolved=1, more_remaining=True)

    # Without the cursor the sweep is back on the row it cannot move.
    assert sweep(batch_size=1) == ReconcileOutcome(reconciled=0, unresolved=1, more_remaining=True)

    # With it, the batch starts past the row that stayed and the promise behind
    # it is kept.
    onward = sweep(batch_size=1, already_seen=head.unresolved)
    assert onward == ReconcileOutcome(reconciled=1, unresolved=0, more_remaining=False)
    assert Outbox.objects.get(event=behind).status == Outbox.Status.PENDING
    assert Outbox.objects.get(event=blocked).next_attempt_at is not None, (
        "the row the relay could not move is still visible to replay_events"
    )


def _poison(monkeypatch: pytest.MonkeyPatch, event_pk: Any) -> None:
    """Make `enqueue_dispatch` raise something the relay cannot classify, for one row.

    A `TimeoutError` stands in for the fault population: a lock timeout on
    `select_for_update`, a dropped connection, an error out of the on-commit
    Temporal start. What matters is only that it is not a `DomainError`.
    """
    real = services.enqueue_dispatch

    def fails_on_the_head(*, tenant: Tenant, event_id: Any, resume: bool = False) -> Any:
        if event_id == event_pk:
            raise TimeoutError("could not lock the outbox row")
        return real(tenant=tenant, event_id=event_id, resume=resume)

    monkeypatch.setattr(services, "enqueue_dispatch", fails_on_the_head)


def test_a_fault_on_one_row_does_not_abort_the_batch_behind_it(
    tenant: Tenant,
    recorded_workflow_starts: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Being "by construction, in both directions" used to cover only ONE class.

    The cursor stepped past `Conflict` and nothing else. Every other exception
    out of `enqueue_dispatch` — a `NotFound` from an event the purge took, a lock
    timeout on `select_for_update`, an error from the on-commit Temporal start —
    aborted the whole batch; Temporal retried it with the *same* `already_seen`,
    so one poison row pinned the sweep at a fixed offset and everything behind it
    starved. That is the exact failure the cursor exists to prevent, arriving
    through a door the docstring's claim did not cover.

    The head here raises something the relay cannot classify. The promise behind
    it is still kept, in the same batch, and the fault is visible: a silently
    skipped row nobody can see is the shape house rule 30 exists to catch.
    """
    poison = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=30))
    behind = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=10))
    clocks = {
        event.pk: Outbox.objects.get(event=event).next_attempt_at for event in (poison, behind)
    }
    _poison(monkeypatch, poison.pk)

    with caplog.at_level(logging.ERROR):
        outcome = sweep()

    assert outcome == ReconcileOutcome(reconciled=1, unresolved=0, faults=1)
    assert "events.reconcile.fault" in caplog.text
    assert "TimeoutError" in caplog.text
    assert Outbox.objects.get(event=behind).next_attempt_at != clocks[behind.pk], (
        "the promise behind the poison row is kept in the same batch"
    )
    assert Outbox.objects.get(event=poison).next_attempt_at == clocks[poison.pk], (
        "the row the relay could not move keeps its clock and is a candidate again"
    )


def test_a_fault_advances_the_cursor_like_a_refusal_does(
    tenant: Tenant, recorded_workflow_starts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cursor is "rows this batch could not move", not "rows the service refused".

    A cursor that counted only refusals would leave a faulting head at position
    zero for ever — the ceiling's own starvation bug, reintroduced through the
    other population. `already_seen` carries both, and the workflow adds them.
    """
    poison = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=30))
    behind = stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=10))
    behind_clock = Outbox.objects.get(event=behind).next_attempt_at
    _poison(monkeypatch, poison.pk)

    head = sweep(batch_size=1)
    assert head == ReconcileOutcome(reconciled=0, faults=1, more_remaining=True)

    # Without the cursor the sweep is back on the row it cannot move.
    assert sweep(batch_size=1) == ReconcileOutcome(reconciled=0, faults=1, more_remaining=True)

    onward = sweep(batch_size=1, already_seen=head.unresolved + head.faults)
    assert onward == ReconcileOutcome(reconciled=1, more_remaining=False)
    assert Outbox.objects.get(event=behind).next_attempt_at != behind_clock


def test_enough_faults_in_one_batch_is_the_platform_and_fails_the_activity(
    tenant: Tenant, recorded_workflow_starts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where per-row isolation stops and Temporal's retry starts.

    Isolating every fault for ever would make the relay quietly absorb a
    database outage: a batch of error lines and a `reconcile.done` reporting
    nothing wrong. A poison row arrives one at a time; a systemic fault arrives
    on every row in the batch. So at `RECONCILE_MAX_FAULTS` the exception is let
    out, the activity fails, and Temporal retries the batch in seconds rather
    than the next scheduled sweep discovering it in five minutes.
    """
    for minute in range(activities.RECONCILE_MAX_FAULTS + 1):
        stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=30 + minute))

    def always_fails(**kwargs: Any) -> Any:
        raise TimeoutError("the database is not there")

    monkeypatch.setattr(services, "enqueue_dispatch", always_fails)

    with pytest.raises(TimeoutError):
        sweep()


def test_a_domain_refusal_is_unresolved_and_never_a_fault(
    tenant: Tenant, recorded_workflow_starts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The split is by KIND, off `DomainError`, not by a list of classes.

    A `NotFound` — the event went out from under the sweep between the candidate
    read and the service call — is the service deciding, deterministically, and
    a retry asks the same question. It belongs with the `Conflict` population
    that `manage.py replay_events` owns, and it must stay away from the
    systemic-fault ceiling, where a handful of purged rows must not fail an
    otherwise healthy batch.
    """
    from apps.core.exceptions import NotFound

    stranded(tenant=tenant, age=activities.OUTBOX_GRACE + timedelta(minutes=30))

    def gone(**kwargs: Any) -> Any:
        raise NotFound("this event no longer exists")

    monkeypatch.setattr(services, "enqueue_dispatch", gone)

    assert sweep() == ReconcileOutcome(reconciled=0, unresolved=1, faults=0)


def test_the_relay_schedule_this_app_declares() -> None:
    """The value the worker hands Temporal, read directly."""
    schedule = activities.RECONCILE_OUTBOX.schedule("djb-tests")

    action: Any = schedule.action
    assert action.workflow == services.RECONCILE_WORKFLOW
    assert action.task_queue == "djb-tests"
    assert action.id == "platform:events:reconcile:djb-tests"
    assert action.args == [
        ReconcileOutbox(
            grace_seconds=activities.outbox_grace_seconds(),
            batch_size=activities.reconcile_batch_size(),
        )
    ]
    assert activities.reconcile_batch_size() == activities.RECONCILE_BATCH
    assert schedule.spec.intervals[0].every == activities.RECONCILE_EVERY


def test_two_queues_are_two_relays_pointing_at_their_own_queue() -> None:
    """Rule 18 on the second schedule: per queue, and never the purge's id."""
    one = activities.RECONCILE_OUTBOX.schedule_id("djb-alpha")
    assert one != activities.RECONCILE_OUTBOX.schedule_id("djb-beta")

    alpha: Any = activities.RECONCILE_OUTBOX.schedule("djb-alpha").action
    beta: Any = activities.RECONCILE_OUTBOX.schedule("djb-beta").action
    assert alpha.id != beta.id
    assert (alpha.task_queue, beta.task_queue) == ("djb-alpha", "djb-beta")
    assert one != activities.PURGE.schedule_id("djb-alpha")
    assert check_workflow_id(id=alpha.id, tenant=None) == alpha.id


@deployment_machinery
@pytest.mark.asyncio
async def test_the_worker_ensures_both_of_this_apps_schedules_at_startup() -> None:
    """The relay is deployed with the code, through discovery.

    `ensure_schedules` is what the worker runs at startup; it finds `SCHEDULES`
    in every installed app's `activities.py`. Nothing registered the relay by
    hand, and a recovery mechanism somebody has to remember to switch on is the
    finding closed here, one layer up.

    **Asserted as a subset, not as the whole set.** The
    assertions here used to be equalities, which read as "these are the only
    schedules in the deployment" — a claim about every *other* app, made from
    this one's test, and false the moment a second app declared a `SCHEDULES`
    entry. `apps.workflows` declaring its run sweep is what made it false. The
    property this test is named for is that **this app's two** are ensured
    through discovery and converge on a restart, and that is what it now says.
    """
    server = FakeScheduleServer()
    client: Any = server
    queue = str(django_settings.TEMPORAL_TASK_QUEUE)
    ours = [
        activities.PURGE.schedule_id(queue),
        activities.RECONCILE_OUTBOX.schedule_id(queue),
    ]

    await ensure_schedules(client)
    await ensure_schedules(client)

    assert server.present >= set(ours)
    assert [schedule_id for schedule_id, _ in server.created if schedule_id in ours] == ours
    # A restart converges rather than duplicating — for both of them.
    assert [schedule_id for schedule_id, _ in server.updated if schedule_id in ours] == ours


# --- The realtime seam this narrowing builds on -------------------------------


def test_the_push_hands_the_rows_organization_across_the_bridge(
    acting: Tenant, owner_actor: Actor
) -> None:
    """The org reaches `apps.realtime` on the body, without a new bridge keyword.

    `push_realtime` hands `schemas.envelope(event)` across `core.bridge`, so the
    branch travels on the **body** rather than on the signature — which is what
    lets the fan-out learn to narrow without either app importing the
    other and without `REALTIME_PUSH`'s declared shape moving. A push that
    dropped the field would leave the fan-out building against prose.
    """
    branch = create_organization(
        tenant=acting,
        parent=root_organization(tenant=acting),
        name="Branch",
        slug="branch",
        actor=owner_actor,
    )
    event = services.record_event(
        tenant=acting,
        name=WIDGET_CREATED,
        payload={"v": 1},
        organization=branch,
        actor=system_actor(tenant=acting),
    )

    pushed: list[dict[str, Any]] = []

    def fake_push(*, tenant_id: Any, event: Any) -> None:
        pushed.append(dict(event))

    saved = dict(bridge.registered())
    try:
        bridge.clear()
        for name, fn in saved.items():
            if name != bridge.REALTIME_PUSH:
                bridge.register(name, fn)
        bridge.register(bridge.REALTIME_PUSH, fake_push)
        assert activities.push_realtime(PushRealtime(event_id=str(event.pk))) is True
    finally:
        # The registry is filled once per process, at startup; put back exactly
        # what was there rather than leaving the next test a planted push.
        bridge.clear()
        for name, fn in saved.items():
            bridge.register(name, fn)

    assert pushed[0]["organization_id"] == str(branch.pk)


# --- The delivery's half of the target check, before the POST ------------------


def _recording(seen: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    """A handler answering 200 that keeps every request it was sent."""

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    return handle


def _deliver_to(tenant: Tenant, url: str) -> tuple[WebhookEndpoint, Event]:
    endpoint = _endpoint(tenant, url=url)
    event = services.record_event(
        tenant=tenant, name=WIDGET_CREATED, payload={"v": 1}, actor=system_actor(tenant=tenant)
    )
    return endpoint, event


@pytest.mark.parametrize(
    ("url", "answers", "refused"),
    [
        ("https://169.254.169.254/latest/meta-data/", [], "link_local"),
        ("https://rebound.example.com/hook", ["10.0.0.5"], "private"),
    ],
)
def test_a_row_holding_a_refused_target_fails_closed_with_no_request(
    acting: Tenant,
    monkeypatch: pytest.MonkeyPatch,
    resolved_hosts: dict[str, list[str]],
    url: str,
    answers: list[str],
    refused: str,
) -> None:
    """A row planted past the doors, or a name that now resolves privately: no POST is made."""
    if answers:
        resolved_hosts["rebound.example.com"] = answers
    endpoint, event = _deliver_to(acting, url)
    seen: list[httpx.Request] = []
    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(_recording(seen))),
    )

    with pytest.raises(ApplicationError) as caught:
        activities.deliver_webhook(
            DeliverWebhook(event_id=str(event.pk), endpoint_id=str(endpoint.pk))
        )

    assert caught.value.non_retryable is True
    assert seen == []
    delivery = Delivery.objects.get(event=event, endpoint=endpoint)
    assert delivery.status == Delivery.Status.FAILED
    assert delivery.last_error == f"private_target: {refused}"
    assert delivery.last_code is None


def test_a_redirect_into_private_space_is_not_followed(
    acting: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 302 from a public host to the metadata address is one request and a failed attempt."""
    endpoint, event = _deliver_to(acting, "https://subscriber.example/hook")
    seen: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/latest/"})

    shipped = activities.http_client
    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: shipped(transport=httpx.MockTransport(redirect)),
    )

    with pytest.raises(activities.DeliveryFailed):
        activities.deliver_webhook(
            DeliverWebhook(event_id=str(event.pk), endpoint_id=str(endpoint.pk))
        )

    assert [str(r.url) for r in seen] == ["https://subscriber.example/hook"]
    assert shipped().follow_redirects is False
    delivery = Delivery.objects.get(event=event, endpoint=endpoint)
    assert (delivery.status, delivery.last_code) == (Delivery.Status.FAILED, 302)


def test_the_laptop_valve_delivers_to_localhost(
    acting: Tenant, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    settings.WEBHOOK_PRIVATE_TARGETS_ALLOWED = True
    endpoint, event = _deliver_to(acting, "http://localhost:9000/hook")
    seen: list[httpx.Request] = []
    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(_recording(seen))),
    )

    activities.deliver_webhook(DeliverWebhook(event_id=str(event.pk), endpoint_id=str(endpoint.pk)))

    assert len(seen) == 1
    assert Delivery.objects.get(event=event).status == Delivery.Status.DELIVERED
