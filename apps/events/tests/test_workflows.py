"""The dispatch, end to end, with no dev server and no real subscriber.

`WorkflowEnvironment.start_time_skipping()` gives a real Temporal server with a
skippable clock, so these drive the actual worker assembly the worker process
would build — the discovered workflows and activities, the tenant interceptor —
rather than a stand-in. The one thing that is faked is the subscriber, through
`httpx.MockTransport`: this repository does not make network calls in a test,
and the point under test is what *we* send, not what somebody else's server
does with it.

What is proved here is the wiring nobody can see from a diff: the endpoint that
asked for the event is the one that gets it, the body is signed with that
endpoint's secret, the headers carry the event and the correlation chain, a
subscriber that has gone away ends as a dead-lettered row and a failed outbox
row rather than as silence, and the housekeeping schedule's workflow really does
empty the two tables it is for.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from django.db import transaction
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import ApplicationError
from temporalio.service import RPCError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from apps.core import bridge
from apps.core.actor import system_actor
from apps.core.asyncdb import run_async, run_db
from apps.core.idempotency import IdempotencyRecord
from apps.core.models import Tenant
from apps.core.time import in_days, now
from apps.events import activities, services
from apps.events.models import Delivery, Event, Outbox, WebhookEndpoint
from apps.events.types import (
    DispatchEvent,
    DispatchOutcome,
    PurgeExpired,
    PurgeOutcome,
    ReconcileOutbox,
    ReconcileOutcome,
)
from apps.events.workflows import RECONCILE_MAX_BATCHES, ReconcileOutboxWorkflow, _reason
from apps.example.events import WIDGET_CREATED
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun
from apps.workflows.services import start_workflow, workflow_id

# `transaction=True`: the activities run on worker threads, on their own
# connections, so the rows have to be really committed for them to be seen.
pytestmark = pytest.mark.django_db(transaction=True)

TASK_QUEUE = "djb-events-tests"
SECRET = "a-shared-secret"  # pragma: allowlist secret


def seed(*, tenant: Tenant, url: str = "https://subscriber.example/hook") -> tuple[Event, Any]:
    """One endpoint and one undispatched event, without starting a dispatch.

    Built with `record_event` rather than `emit` on purpose: `emit` registers the
    dispatch on `transaction.on_commit`, and in a `transaction=True` test that
    commit is real — it would reach for the deployment's Temporal client instead
    of the test environment's. The workflow is started explicitly below, which is
    exactly what the on-commit hook would have done.

    **Still needed, and no longer the only thing standing between this module and
    the development server** (queue V3): `apps/conftest.py`'s autouse
    `_no_dialling_temporal` now makes that reach a `RuntimeError` rather than a
    leaked execution, and `config/settings/test.py` points `TEMPORAL_ADDRESS` at a
    dead port behind it. This stays because it is the better shape regardless —
    the run under test is started *here*, on the environment's own client and
    queue, where the test can hold its handle.
    """
    endpoint = WebhookEndpoint.objects.create(tenant=tenant, url=url, secret=SECRET)
    event = services.record_event(
        tenant=tenant,
        name=WIDGET_CREATED,
        payload={"v": 1, "id": "widget-1"},
        correlation_id="chain-1",
        actor=system_actor(tenant=tenant),
    )
    return event, endpoint


async def dispatch(*, tenant: Tenant, event: Event) -> DispatchOutcome:
    """Run one `DispatchEventWorkflow` to completion and return what it did."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow=services.DISPATCH_WORKFLOW,
                arg=DispatchEvent(event_id=str(event.pk)),
                tenant=tenant,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:events:event:{event.pk}",
            )
            handle = client.get_workflow_handle(run.workflow_id, result_type=DispatchOutcome)
            result: DispatchOutcome = await handle.result()
    return result


def test_the_worker_discovers_the_spine() -> None:
    """Discovery, not registration: the app dropped the files and that is all."""
    from apps.workflows.client import discovered_activities, discovered_workflows

    names = {getattr(one, "__temporal_workflow_definition").name for one in discovered_workflows()}
    assert {"DispatchEventWorkflow", "PurgeExpiredWorkflow"} <= names

    activity_names = {
        getattr(one, "__temporal_activity_definition").name for one in discovered_activities()
    }
    assert {"deliver_webhook", "load_delivery_targets", "purge_expired_records"} <= activity_names


def test_the_reason_walks_the_cause_chain_and_stops() -> None:
    """N193b: three links, joined, and never a fourth (conventions §7).

    Bounded because a cause chain is somebody else's data structure — a chain
    that referred to itself, or that was a hundred links of framework
    bookkeeping, would otherwise decide how long a `TextField` gets to be.
    Three is wrapper, activity error, the activity's own complaint, which is all
    of it.
    """
    deepest = ValueError("HTTP 500")
    middle = RuntimeError("Activity task failed")
    middle.__cause__ = deepest
    outer = RuntimeError("Workflow execution failed")
    outer.__cause__ = middle

    assert _reason(deepest) == "ValueError: HTTP 500"
    assert _reason(middle) == "RuntimeError: Activity task failed <- ValueError: HTTP 500"

    fourth = RuntimeError("one link too far")
    fourth.__cause__ = outer
    walked = _reason(fourth)
    assert walked.count(" <- ") == 2, walked
    assert "HTTP 500" not in walked, "the bound is the point; it is not best-effort"


@pytest.mark.asyncio
async def test_an_event_reaches_its_subscriber_signed(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The delivery a subscriber actually receives, byte for byte."""
    event, endpoint = await run_db(seed, tenant=tenant)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    outcome = await dispatch(tenant=tenant, event=event)

    # `pushed` is the socket app's and is asserted where it belongs
    # (`test_the_realtime_push_is_optional_and_reached_only_by_name`): a
    # template that strips `apps.realtime` changes it, and must not change what
    # a webhook subscriber receives.
    assert (outcome.delivered, outcome.dead_lettered) == (1, 0)
    assert len(seen) == 1
    request = seen[0]
    assert str(request.url) == endpoint.url

    # The signature is over the bytes that were sent, with that endpoint's
    # secret — which is what a subscriber can verify and an attacker cannot
    # forge.
    expected = hmac.new(SECRET.encode(), request.content, hashlib.sha256).hexdigest()
    assert request.headers["X-Signature"] == f"sha256={expected}"
    assert request.headers["X-Event-Name"] == WIDGET_CREATED
    assert request.headers["X-Event-Id"] == str(event.pk)
    assert request.headers["X-Correlation-Id"] == "chain-1"
    assert request.headers["traceparent"].startswith("00-")

    body = json.loads(request.content)
    assert body["name"] == WIDGET_CREATED
    assert body["payload"] == {"v": 1, "id": "widget-1"}

    delivery = await run_db(lambda: Delivery.objects.get(event=event, endpoint=endpoint))
    assert delivery.status == Delivery.Status.DELIVERED
    assert delivery.attempts == 1
    assert delivery.last_code == 200
    assert delivery.correlation_id == "chain-1"

    outbox = await run_db(lambda: Outbox.objects.get(event=event))
    assert outbox.status == Outbox.Status.DISPATCHED
    assert outbox.dispatched_at is not None


@pytest.mark.asyncio
async def test_a_subscriber_that_has_gone_away_is_dead_lettered(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row somebody can find, never silence — and no retry storm to get there.

    410 Gone is the subscriber saying the request is wrong, not that it is
    having a moment, so the delivery is non-retryable and dead-letters on the
    first answer (`activities.is_worth_retrying`). The retryable half — a 503,
    recorded and raised so Temporal backs off — is proved in
    `test_activities.py`, at the activity, where it costs no wall clock.
    """
    event, endpoint = await run_db(seed, tenant=tenant)
    attempts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        return httpx.Response(410, text="gone")

    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    outcome = await dispatch(tenant=tenant, event=event)

    assert outcome.delivered == 0
    assert outcome.dead_lettered == 1
    assert len(attempts) == 1

    delivery = await run_db(lambda: Delivery.objects.get(event=event, endpoint=endpoint))
    assert delivery.status == Delivery.Status.DEAD
    assert delivery.dead_lettered_at is not None
    assert delivery.last_code == 410
    assert delivery.attempts == 1
    # End to end through the real dead-letter transition: the pair the
    # dead-letter list publishes is what the subscriber's server answered.
    # Previously the transition wrote Temporal's own wrapper here, so the
    # row read `last_code 410` beside `last_error "Activity task failed"` — two
    # fields about one attempt, disagreeing.
    assert delivery.last_error == "HTTP 410", delivery.last_error
    assert "Activity task failed" not in delivery.last_error

    outbox = await run_db(lambda: Outbox.objects.get(event=event))
    assert outbox.status == Outbox.Status.FAILED
    assert "dead-lettered" in outbox.last_error


@pytest.mark.asyncio
async def test_a_dispatch_closes_its_visibility_row(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`WorkflowRun` stops saying `running` when the dispatch stops (queue V6).

    The row is written by the service that starts the run and is the product's
    own answer to "what durable work is this tenant waiting on". A dispatch that
    never closed it made every finished run look like a stuck one — which is
    what the table exists to make visible.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    event, _endpoint = await run_db(seed, tenant=tenant)
    await dispatch(tenant=tenant, event=event)

    run = await run_db(
        lambda: (
            WorkflowRun.objects.for_tenant(tenant)
            .filter(workflow_id=f"{tenant.slug}:events:event:{event.pk}")
            .get()
        )
    )
    assert run.status == WorkflowRun.Status.COMPLETED
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_a_dispatch_that_fails_says_so_on_its_visibility_row(tenant: Tenant) -> None:
    """The failure half of the same property: `failed`, with the reason on it."""
    from temporalio.client import WorkflowFailureError

    workflow_id = f"{tenant.slug}:events:event:orphan-row"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow=services.DISPATCH_WORKFLOW,
                arg=DispatchEvent(event_id="01a01d28-0000-7000-8000-0000deadbee0"),
                tenant=tenant,
                client=client,
                task_queue=TASK_QUEUE,
                id=workflow_id,
            )
            handle = client.get_workflow_handle(run.workflow_id, result_type=DispatchOutcome)
            with pytest.raises(WorkflowFailureError):
                await handle.result()

    row = await run_db(
        lambda: WorkflowRun.objects.for_tenant(tenant).filter(workflow_id=workflow_id).get()
    )
    assert row.status == WorkflowRun.Status.FAILED
    assert row.finished_at is not None
    # And the reason is the CAUSE, not the wrapper (N193b, conventions §7).
    # `str(ActivityError)` is "Activity task failed" — true, and useless to
    # whoever reads this row six weeks later. The walk puts the activity's own
    # complaint on it: this dispatch names an event nothing wrote.
    assert "Not Found" in row.error, row.error
    assert row.error != "Activity task failed"


@pytest.mark.asyncio
async def test_an_orphaned_event_fails_the_dispatch_terminally(tenant: Tenant) -> None:
    """The row is gone, so the run stops. It used to be read forever (queue V5).

    A dispatch is started on the commit that wrote its event, so the row is
    normally there — unless the transaction was rolled back after the hook was
    registered, or somebody deleted it. `load_delivery_targets` had no retry
    policy, and Temporal's default is to retry an activity until the end of
    time: one orphaned event was a worker asking for a missing row, at
    increasing intervals, until a human found it months later.

    Two things are asserted, and they are different: that the run **fails**
    rather than hanging, and that it fails on the **first** attempt rather than
    after the bounded five, because a row that is gone is not a transient
    failure. The attempt count is what says the `non_retryable` flag is doing
    the work and not just the policy.
    """
    from temporalio.client import WorkflowFailureError

    missing_event_id = "01a01d28-0000-7000-8000-0000deadbeef"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow=services.DISPATCH_WORKFLOW,
                arg=DispatchEvent(event_id=missing_event_id),
                tenant=tenant,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:events:event:orphan",
            )
            handle = client.get_workflow_handle(run.workflow_id, result_type=DispatchOutcome)
            with pytest.raises(WorkflowFailureError) as failure:
                await handle.result()

            # Which activity each start belongs to: the started event names
            # only the id of the event that scheduled it.
            scheduled: dict[int, str] = {}
            attempts: list[int] = []
            async for history in handle.fetch_history_events():
                if history.HasField("activity_task_scheduled_event_attributes"):
                    schedule = history.activity_task_scheduled_event_attributes
                    scheduled[history.event_id] = schedule.activity_type.name
                elif history.HasField("activity_task_started_event_attributes"):
                    started = history.activity_task_started_event_attributes
                    if scheduled.get(started.scheduled_event_id) == "load_delivery_targets":
                        attempts.append(started.attempt)

    # Temporal wraps the activity's failure twice; the message is at the bottom.
    causes = []
    error: BaseException | None = failure.value
    while error is not None:
        causes.append(str(error))
        error = error.__cause__
    assert any("Not Found" in cause for cause in causes), causes
    assert attempts == [1], attempts


@pytest.mark.asyncio
async def test_an_endpoint_that_did_not_ask_for_this_event_is_not_called(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allow-list is honoured, and a fan-out to nobody still closes the row."""
    event, endpoint = await run_db(seed, tenant=tenant)
    await run_db(
        lambda: WebhookEndpoint.objects.filter(pk=endpoint.pk).update(
            event_names=["example.widget.deleted"]
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("an endpoint that did not subscribe was called")

    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    outcome = await dispatch(tenant=tenant, event=event)

    assert (outcome.delivered, outcome.dead_lettered) == (0, 0)  # `pushed`: see above
    assert await run_db(lambda: Delivery.objects.count()) == 0
    outbox = await run_db(lambda: Outbox.objects.get(event=event))
    assert outbox.status == Outbox.Status.DISPATCHED


@pytest.mark.asyncio
async def test_another_tenants_endpoint_is_never_delivered_to(
    tenant: Tenant, other_tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The sibling test that cannot pass vacuously."""
    event, _endpoint = await run_db(seed, tenant=tenant)
    await run_db(
        lambda: WebhookEndpoint.objects.create(
            tenant=other_tenant, url="https://not-theirs.example/hook", secret=SECRET
        )
    )
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )

    await dispatch(tenant=tenant, event=event)

    assert seen == ["https://subscriber.example/hook"]


@pytest.mark.asyncio
async def test_the_realtime_push_is_optional_and_reached_only_by_name(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The spine must ship and work whether or not `apps.realtime` is installed.

    Absent, the dispatch says `pushed=False` and delivers anyway. Present, the
    registered callable is handed the event — and it is reached by name through
    the bridge, never by an import, because the two apps are siblings.

    Both halves are driven from an empty registry rather than from whatever this
    process happens to have registered, so the test says the same thing in a
    tree with the socket app and in one without.
    """
    event, _endpoint = await run_db(seed, tenant=tenant)
    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
    )

    pushed: list[dict[str, Any]] = []

    def fake_push(*, tenant_id: Any, event: dict[str, Any]) -> None:
        pushed.append(event)

    saved = bridge.registered()
    try:
        # Nothing registered: the one state a template without the socket app is
        # in, and the dispatch has to survive it.
        bridge.clear()
        for name, fn in saved.items():
            if name != bridge.REALTIME_PUSH:
                bridge.register(name, fn)
        assert bridge.find(bridge.REALTIME_PUSH) is None
        absent = await dispatch(tenant=tenant, event=event)
        assert absent.pushed is False

        bridge.register(bridge.REALTIME_PUSH, fake_push)
        second = await run_db(
            services.record_event,
            tenant=tenant,
            name=WIDGET_CREATED,
            payload={"v": 1},
            actor=system_actor(tenant=tenant),
        )
        present = await dispatch(tenant=tenant, event=second)
    finally:
        # The registry is filled once per process, at startup; put back exactly
        # what was there rather than leaving the next test a planted push.
        bridge.clear()
        for name, fn in saved.items():
            bridge.register(name, fn)

    assert present.pushed is True
    # The envelope, which is the body a webhook subscriber is signed and sent —
    # one serialisation for both doors.
    assert pushed[0]["name"] == WIDGET_CREATED
    assert pushed[0]["id"] == str(second.pk)


@pytest.mark.asyncio
async def test_the_search_index_leg_is_optional_and_reached_only_by_name(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `push_realtime` posture, verbatim, for the third fan-out leg.

    ADR search-2 asks for exactly this and the reason is the template's own:
    a product that does not want search still has to deliver its webhooks. So
    an unregistered `search.index_event` is `indexed=False` and a delivered
    event, not a failed dispatch — **and the events suite proves it from an
    EMPTY registry**, so this module says the same thing in a checkout with
    `apps.search` and in one without.

    The present half proves the other property the bridge exists for: what
    crosses is the ENVELOPE — the same JSON body a webhook subscriber is signed
    and sent — reached by name, never by importing the app that fills it.
    """
    event, _endpoint = await run_db(seed, tenant=tenant)
    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
    )

    indexed: list[dict[str, Any]] = []

    def fake_index(*, tenant_id: Any, event: dict[str, Any]) -> bool:
        indexed.append(event)
        return True

    saved = bridge.registered()
    try:
        bridge.clear()
        for name, fn in saved.items():
            if name != activities.SEARCH_INDEX_EVENT:
                bridge.register(name, fn)
        assert bridge.find(activities.SEARCH_INDEX_EVENT) is None
        absent = await dispatch(tenant=tenant, event=event)
        assert absent.indexed is False
        # The half that matters: the subscriber was still served.
        assert (absent.delivered, absent.dead_lettered) == (1, 0)

        bridge.register(activities.SEARCH_INDEX_EVENT, fake_index)
        second = await run_db(
            services.record_event,
            tenant=tenant,
            name=WIDGET_CREATED,
            payload={"v": 1},
            actor=system_actor(tenant=tenant),
        )
        present = await dispatch(tenant=tenant, event=second)
    finally:
        # The registry is filled once per process, at startup; put back exactly
        # what was there rather than leaving the next test a planted indexer.
        bridge.clear()
        for name, fn in saved.items():
            bridge.register(name, fn)

    assert present.indexed is True
    assert indexed[0]["name"] == WIDGET_CREATED
    assert indexed[0]["id"] == str(second.pk)


@pytest.mark.asyncio
async def test_an_index_the_retries_cannot_fix_does_not_re_deliver_every_webhook(
    tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The isolation, and the cost comparison behind it (`workflows._index`).

    Temporal's retries are the catch-up queue and `INDEX_DEADLINE` is how long
    that queue runs for. When the leg fails ANYWAY — the budget spent, or a
    failure Temporal will not retry at all — the document is stale, which is the
    honest answer with `manage.py search_reindex` named at the call site as the
    backstop. What must not happen is the dispatch failing: that leaves the
    outbox row `pending`, `ReconcileOutboxWorkflow` re-dispatches it, and every
    webhook for this event is delivered a second time to fix a document — the
    subscribers paying the index's bill.

    **A non-retryable failure rather than an exhausted budget**, and it proves
    the same line: both arrive at `_index`'s `except` as an `ActivityError`, and
    this one costs one attempt instead of an hour of skipped clock. The budget's
    own convergence half is proved where it belongs, against the real container
    — `apps/search/tests/test_indexer.py`, the flaky-engine test.
    """
    event, endpoint = await run_db(seed, tenant=tenant)
    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
    )

    def never_works(*, tenant_id: Any, event: dict[str, Any]) -> bool:
        raise ApplicationError("the index refused this document", non_retryable=True)

    saved = bridge.registered()
    try:
        bridge.clear()
        for name, fn in saved.items():
            bridge.register(name, fn)
        bridge.register(activities.SEARCH_INDEX_EVENT, never_works)
        outcome = await dispatch(tenant=tenant, event=event)
    finally:
        bridge.clear()
        for name, fn in saved.items():
            bridge.register(name, fn)

    assert outcome.indexed is False
    assert (outcome.delivered, outcome.dead_lettered) == (1, 0)

    outbox = await run_db(lambda: Outbox.objects.get(event=event))
    assert outbox.status == Outbox.Status.DISPATCHED, (
        "a stale document left the outbox row pending, which the relay would "
        "re-dispatch — re-delivering every webhook to fix an index"
    )
    delivery = await run_db(lambda: Delivery.objects.get(event=event, endpoint=endpoint))
    assert delivery.status == Delivery.Status.DELIVERED


@pytest.mark.asyncio
async def test_housekeeping_purges_expired_keys_and_old_outbox_rows(tenant: Tenant) -> None:
    """`IdempotencyRecord.purge_expired` had nothing calling it until this closed the gap.

    Three populations now: expired idempotency keys, dispatched
    outbox rows past retention, and deliveries ninety days past the moment they
    reached a final state. This is the END-TO-END half of criterion E1-2 — one
    run of the declared machine, through a real Temporal server, taking one row
    from each and leaving each population's ineligible rows alone.
    """

    def seed_rows() -> tuple[Event, Delivery, Delivery]:
        IdempotencyRecord.objects.create(
            scope="s",
            key="expired",
            fingerprint="f",
            method="POST",
            path="/api/x/",
            expires_at=in_days(-1),
        )
        IdempotencyRecord.objects.create(
            scope="s",
            key="live",
            fingerprint="f",
            method="POST",
            path="/api/x/",
            expires_at=in_days(1),
        )
        old = services.record_event(
            tenant=tenant, name=WIDGET_CREATED, payload={"v": 1}, actor=system_actor(tenant=tenant)
        )
        Outbox.objects.filter(event=old).update(
            status=Outbox.Status.DISPATCHED, dispatched_at=in_days(-40)
        )

        # One finished delivery past the window and one still being retried.
        # The second is the assertion that matters: a purge that swept by row
        # age rather than by final state would take it, and it is a promise the
        # relay still owes.
        endpoint = WebhookEndpoint.objects.create(
            tenant=tenant, url="https://subscriber.example/purge", secret=SECRET
        )
        finished = Delivery.objects.create(
            endpoint=endpoint,
            event=services.record_event(
                tenant=tenant,
                name=WIDGET_CREATED,
                payload={"v": 2},
                actor=system_actor(tenant=tenant),
            ),
            status=Delivery.Status.DELIVERED,
        )
        Delivery.objects.filter(pk=finished.pk).update(delivered_at=in_days(-100))
        retrying = Delivery.objects.create(
            endpoint=endpoint,
            event=services.record_event(
                tenant=tenant,
                name=WIDGET_CREATED,
                payload={"v": 3},
                actor=system_actor(tenant=tenant),
            ),
            status=Delivery.Status.FAILED,
        )
        Delivery.objects.filter(pk=retrying.pk).update(created_at=in_days(-100))
        return old, finished, retrying

    old, finished, retrying = await run_db(seed_rows)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow=services.PURGE_WORKFLOW,
                arg=PurgeExpired(
                    outbox_retention_days=30,
                    delivery_retention_days=activities.DELIVERY_RETENTION_DAYS,
                ),
                tenant=tenant,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:events:purge:{now().date().isoformat()}",
            )
            handle = client.get_workflow_handle(run.workflow_id, result_type=PurgeOutcome)
            result: PurgeOutcome = await handle.result()

    assert result == PurgeOutcome(idempotency_records=1, outbox_rows=1, deliveries=1)
    assert await run_db(lambda: IdempotencyRecord.objects.count()) == 1
    assert await run_db(lambda: Outbox.objects.filter(event=old).exists()) is False
    assert await run_db(lambda: Delivery.objects.filter(pk=finished.pk).exists()) is False
    assert await run_db(lambda: Delivery.objects.filter(pk=retrying.pk).exists()) is True


# --- The relay (ADR events-3) ------------------------------------------------
#
# `emit()` writes `Outbox(PENDING, next_attempt_at)` and registers the dispatch
# on `transaction.on_commit`. A process that dies **between the commit and that
# hook's client call** leaves a committed event, a committed outbox row holding
# a retry clock, a `WorkflowRun` row saying `running` — and nothing whatsoever
# in Temporal. Until the relay there was no production reader of
# `next_attempt_at` at all, so the event was stranded silently and forever, with
# `manage.py replay_events` as the only recovery and a human who already knew as
# its only trigger.
#
# The tests below are that finding, over the wire: the strand is built the way
# the crash builds it, and then the relay is the thing that ends it.


def dead_hook(monkeypatch: pytest.MonkeyPatch) -> Callable[[bool], None]:
    """Cut the wire between a real commit and the client call the hook makes.

    `run_async` is the one thing `start_workflow_on_commit`'s hook does that a
    crash takes away: everything above it — the id check, the `WorkflowRun` row,
    the hook registered on the right transaction, the commit itself — still
    happens, and the dial does not. That is the failure exactly, rather than an
    approximation of it (`apps/conftest.py`'s `recorded_workflow_starts` is the
    same seam, named for the other use).

    Returns a switch, so one test can commit under the crash and then let the
    later dials through without undoing the rest of its patches.
    """
    dialling = {"live": False}

    def maybe(coroutine_factory: Any) -> Any:
        return run_async(coroutine_factory) if dialling["live"] else None

    monkeypatch.setattr("apps.workflows.services.run_async", maybe)

    def switch(live: bool) -> None:
        dialling["live"] = live

    return switch


def strand(*, event: Event) -> None:
    """Age the row's retry clock past the grace, as a real strand ages itself."""
    Outbox.objects.filter(event=event).update(
        next_attempt_at=now() - activities.OUTBOX_GRACE - timedelta(minutes=1)
    )


@pytest.mark.asyncio
async def test_the_relay_delivers_an_event_whose_dispatch_never_started(
    tenant: Tenant, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The forward direction: a stranded event leaves the building.

    The crash is built, not described — the emit commits with the hook's dial
    cut, so what is on disk afterwards is exactly what a killed process leaves.
    Then one relay sweep, and the subscriber gets its webhook.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    settings.TEMPORAL_TASK_QUEUE = TASK_QUEUE
    switch = dead_hook(monkeypatch)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        target = env.client.service_client.config.target_host
        namespace = env.client.namespace

        async def connect() -> Client:
            return attach_interceptors(await Client.connect(target, namespace=namespace))

        # What the on-commit hook reaches for once the wire is live again: the
        # relay re-enqueues from a worker thread, on its own event loop, exactly
        # as production's hook dials the real server.
        monkeypatch.setattr(client_module, "get_client", connect)

        def crash() -> Event:
            WebhookEndpoint.objects.create(
                tenant=tenant, url="https://subscriber.example/hook", secret=SECRET
            )
            with transaction.atomic():
                return services.emit(
                    name=WIDGET_CREATED,
                    tenant=tenant,
                    payload={"v": 1, "id": "widget-1"},
                    actor=system_actor(tenant=tenant),
                )

        event = await run_db(crash)
        dispatch_id = workflow_id(tenant=tenant, app="events", noun="event", key=str(event.pk))
        await run_db(strand, event=event)
        switch(True)

        # The strand, stated: a promise made, a clock written, a ledger row
        # saying `running` — and no execution anywhere that could keep it.
        outbox = await run_db(lambda: Outbox.objects.get(event=event))
        assert (outbox.status, outbox.attempts) == (Outbox.Status.PENDING, 1)
        assert outbox.next_attempt_at is not None
        assert await run_db(lambda: Delivery.objects.filter(event=event).count()) == 0
        assert seen == []
        run_row = await run_db(lambda: WorkflowRun.objects.get(workflow_id=dispatch_id))
        assert run_row.status == WorkflowRun.Status.RUNNING
        with pytest.raises(RPCError):
            await env.client.get_workflow_handle(dispatch_id).describe()

        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow=services.RECONCILE_WORKFLOW,
                arg=ReconcileOutbox(grace_seconds=activities.outbox_grace_seconds()),
                tenant=tenant,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:events:reconcile:{now().date().isoformat()}",
            )
            handle = client.get_workflow_handle(run.workflow_id, result_type=ReconcileOutcome)
            swept: ReconcileOutcome = await handle.result()
            assert swept == ReconcileOutcome(reconciled=1, unresolved=0)

            dispatched: DispatchOutcome = await client.get_workflow_handle(
                dispatch_id, result_type=DispatchOutcome
            ).result()

    # The event left the building: one webhook, to the endpoint that asked.
    assert dispatched.delivered == 1
    assert [str(request.url) for request in seen] == ["https://subscriber.example/hook"]
    delivery = await run_db(lambda: Delivery.objects.get(event=event))
    assert (delivery.status, delivery.attempts) == (Delivery.Status.DELIVERED, 1)

    # And it left it **once**, under the id the crashed start had already
    # claimed: a resume is the same run healed, never a second attempt.
    final = await run_db(lambda: Outbox.objects.get(event=event))
    assert (final.status, final.attempts) == (Outbox.Status.DISPATCHED, 1)
    assert final.next_attempt_at is None
    assert await run_db(lambda: WorkflowRun.objects.filter(workflow_id=dispatch_id).count()) == 1


def test_the_worker_discovers_the_relay_and_it_owns_no_run() -> None:
    """Discovery, and rule 28's other half.

    Nothing was registered — the app declared a class, an activity and a
    `SCHEDULES` entry, and the worker found all three. `owns_no_run` is the
    declaration a schedule-started workflow owes rule 28 (ADR workflows-5): no
    service asked for this run, so there is no `WorkflowRun` row waiting to be
    closed and nobody is reading one that lies.
    """
    from apps.workflows.client import (
        discovered_activities,
        discovered_schedules,
        discovered_workflows,
    )

    names = {getattr(one, "__temporal_workflow_definition").name for one in discovered_workflows()}
    assert "ReconcileOutboxWorkflow" in names

    activity_names = {
        getattr(one, "__temporal_activity_definition").name for one in discovered_activities()
    }
    assert "reconcile_outbox" in activity_names

    assert activities.RECONCILE_OUTBOX in discovered_schedules()
    assert ReconcileOutboxWorkflow.owns_no_run is True


# --- The relay's loop over bounded batches ------------------------------------

#: Every `ReconcileOutbox` the workflow handed the activity, in order. The
#: cursor's progress is the property under test and it is only visible here.
RELAY_CALLS: list[ReconcileOutbox] = []

#: A queue with no database behind it: `stuck` rows sit at the head and can
#: never be resumed (a finished dispatch run — `record_run` refuses the id),
#: `resumable` rows sit behind them and leave the candidate set when they are.
RELAY_QUEUE = {"stuck": 0, "resumable": 0}


@activity.defn(name="reconcile_outbox")
async def fake_reconcile_outbox(window: ReconcileOutbox) -> ReconcileOutcome:
    """One relay batch, modelled rather than run.

    A stand-in and not the real activity, because what is under test is the
    **loop** — that the workflow keeps asking while it is told there is more,
    that it carries the cursor forward by the rows a batch could not move, and
    that it stops at its own ceiling. Proving those against real rows would mean
    seeding thousands of them and a live dispatch per resume, which is the
    activity's own subject (`test_activities.py`) and not this one's.

    The contract it honours is the real one, stated in `types.ReconcileOutbox`:
    at most `batch_size` rows from `already_seen` onward, oldest first;
    `more_remaining` is whether a candidate exists past the batch; a resumed row
    leaves the set and an unresolved one does not.
    """
    RELAY_CALLS.append(window)
    visible = (RELAY_QUEUE["stuck"] - window.already_seen) + RELAY_QUEUE["resumable"]
    taken = min(window.batch_size, visible)
    unresolved = max(0, min(taken, RELAY_QUEUE["stuck"] - window.already_seen))
    reconciled = taken - unresolved
    RELAY_QUEUE["resumable"] -= reconciled
    return ReconcileOutcome(
        reconciled=reconciled, unresolved=unresolved, more_remaining=visible > window.batch_size
    )


@pytest.fixture
def relay_queue() -> dict[str, int]:
    """A fresh modelled queue per test; the worker shares this process."""
    RELAY_CALLS.clear()
    RELAY_QUEUE.update(stuck=0, resumable=0)
    return RELAY_QUEUE


async def sweep_the_modelled_queue(*, batch_size: int) -> ReconcileOutcome:
    """Run one whole `ReconcileOutboxWorkflow` against the stand-in activity."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=TASK_QUEUE,
            workflows=[ReconcileOutboxWorkflow],
            activities=[fake_reconcile_outbox],
        ):
            handle = await env.client.start_workflow(
                "ReconcileOutboxWorkflow",
                ReconcileOutbox(grace_seconds=300, batch_size=batch_size),
                id=f"{TASK_QUEUE}:reconcile-loop",
                task_queue=TASK_QUEUE,
                result_type=ReconcileOutcome,
            )
            swept: ReconcileOutcome = await handle.result()
    return swept


@pytest.mark.asyncio
async def test_the_relay_loops_until_the_queue_is_clear(relay_queue: dict[str, int]) -> None:
    """Bounding the batch must not bound the drain.

    Five stranded rows and a batch of two is three activity executions, not one
    truncated sweep. The loop is workflow code and the `LIMIT` is activity code
    (house rule 9), and this is what says the two halves add up.
    """
    relay_queue.update(stuck=0, resumable=5)

    swept = await sweep_the_modelled_queue(batch_size=2)

    assert swept == ReconcileOutcome(reconciled=5, unresolved=0, more_remaining=False)
    assert len(RELAY_CALLS) == 3
    assert [call.already_seen for call in RELAY_CALLS] == [0, 0, 0], (
        "a resumed row leaves the candidate set, so the cursor has nothing to skip"
    )
    assert {call.batch_size for call in RELAY_CALLS} == {2}


@pytest.mark.asyncio
async def test_the_cursor_carries_past_the_rows_the_relay_cannot_move(
    relay_queue: dict[str, int],
) -> None:
    """No starvation, by construction: an unresolved head is stepped over.

    Three rows the relay can never resume sit at the head of an oldest-first
    read, two keepable promises behind them. Without a cursor a batch of two
    would read the same refused pair for ever and the two promises would never
    be kept — the bug a ceiling introduces on its own. The workflow carries the
    unresolved count forward, so each batch starts strictly past the last.
    """
    relay_queue.update(stuck=3, resumable=2)

    swept = await sweep_the_modelled_queue(batch_size=2)

    assert swept == ReconcileOutcome(reconciled=2, unresolved=3, more_remaining=False)
    assert [call.already_seen for call in RELAY_CALLS] == [0, 2, 3]


@pytest.mark.asyncio
async def test_a_sweep_that_spends_every_batch_says_so_rather_than_lying(
    relay_queue: dict[str, int],
) -> None:
    """The ceiling on the *sweep*, and the honest word for having hit it.

    The per-batch bound stops one activity execution from timing out; this stops
    one execution's history from growing with the size of an outage. What an
    operator needs is to be able to tell "nothing left" from "I ran out of
    batches", so the two are different values of the same field and the next
    scheduled sweep picks the rest up — oldest first, as always.
    """
    relay_queue.update(stuck=0, resumable=RECONCILE_MAX_BATCHES + 5)

    swept = await sweep_the_modelled_queue(batch_size=1)

    assert swept == ReconcileOutcome(
        reconciled=RECONCILE_MAX_BATCHES, unresolved=0, more_remaining=True
    )
    assert len(RELAY_CALLS) == RECONCILE_MAX_BATCHES


@pytest.mark.asyncio
async def test_a_resume_beside_a_live_dispatch_delivers_once(
    tenant: Tenant, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Second half: the relay cannot turn at-most-once into at-least-twice.

    The dangerous case is the one the grace cannot see: the hook *did* reach
    Temporal, the execution is alive, and the row is still `pending` because the
    dispatch has not got to it yet. A relay that started a second run here would
    post the same webhook twice.

    It does not, and the instrument is the deterministic id rather than a guess
    about liveness: a resume asks again under the id the first start claimed,
    Temporal answers `WorkflowAlreadyStartedError`, and `_start_recorded` treats
    that as the success it is. One execution, one run row, one webhook.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(
        activities,
        "http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    settings.TEMPORAL_TASK_QUEUE = TASK_QUEUE

    async with await WorkflowEnvironment.start_time_skipping() as env:
        target = env.client.service_client.config.target_host
        namespace = env.client.namespace

        async def connect() -> Client:
            return attach_interceptors(await Client.connect(target, namespace=namespace))

        monkeypatch.setattr(client_module, "get_client", connect)

        def emit_live() -> Event:
            WebhookEndpoint.objects.create(
                tenant=tenant, url="https://subscriber.example/hook", secret=SECRET
            )
            return services.emit(
                name=WIDGET_CREATED,
                tenant=tenant,
                payload={"v": 1, "id": "widget-1"},
                actor=system_actor(tenant=tenant),
            )

        # No worker yet: the dispatch really exists and really has not run.
        event = await run_db(emit_live)
        dispatch_id = workflow_id(tenant=tenant, app="events", noun="event", key=str(event.pk))
        started = await env.client.get_workflow_handle(dispatch_id).describe()
        assert (await run_db(lambda: Outbox.objects.get(event=event))).status == (
            Outbox.Status.PENDING
        )

        # The relay sweeps it anyway — the grace is a clock, not an oracle.
        await run_db(strand, event=event)
        swept = await run_db(
            activities.reconcile_outbox,
            ReconcileOutbox(grace_seconds=activities.outbox_grace_seconds()),
        )
        assert swept == ReconcileOutcome(reconciled=1, unresolved=0)

        # And it asked for the run that was already there, not a second one.
        after = await env.client.get_workflow_handle(dispatch_id).describe()
        assert after.run_id == started.run_id
        assert (await run_db(lambda: Outbox.objects.get(event=event))).attempts == 1

        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            dispatched: DispatchOutcome = await client.get_workflow_handle(
                dispatch_id, result_type=DispatchOutcome
            ).result()

    assert dispatched.delivered == 1
    assert len(seen) == 1, "the relay must not post the same webhook twice"
    delivery = await run_db(lambda: Delivery.objects.get(event=event))
    assert delivery.attempts == 1
    assert await run_db(lambda: WorkflowRun.objects.filter(workflow_id=dispatch_id).count()) == 1
