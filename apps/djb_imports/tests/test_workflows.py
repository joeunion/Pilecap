"""The two runs on a real worker: the check, and the apply — and the apply's resume.

`WorkflowEnvironment.start_time_skipping()` gives a real Temporal server, the
real worker assembly (every discovered workflow and activity), the real
interceptors carrying the tenant, the person and the hat, and the real
activities writing to the real database. The object store is the one double
(`conftest.memory_store`, in this process, where the worker's threads run).

What is proved here and nowhere cheaper:

* staging **starts** `ValidateImportWorkflow` on the commit, under the id the row
  implies, and it previews and closes its `WorkflowRun` row;
* the apply writes the four clean rows through the importer's own service — four
  `example.create_widget` audit rows under ONE correlation — and closes as
  `imported` with the refused row still listed;
* **idempotent per row**: an apply attempt that dies part-way (a planted crash
  after two rows) is retried by Temporal, resumes at the first unsettled row,
  and the file still makes four widgets, not five or six. The box's kill drive
  is the same property with a real worker process killed instead of an
  exception raised; this is the in-process half;
* **a cancel is its own exit**: cancelled mid-apply, the writer stops at a row
  boundary before the run closes, and the run and the import both say
  `cancelled`; cancelled mid-check, the same two rows say the same.

`transaction=True` throughout: the activities run on worker threads with their
own connections, and an `on_commit` hook only fires on a real commit.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowFailureError
from temporalio.testing import WorkflowEnvironment

from apps.core.actor import actor_for, system_actor
from apps.core.asyncdb import run_db
from apps.core.audit import AuditEntry
from apps.core.services import create_tenant, root_organization
from apps.core.verbs import Importer
from apps.djb_imports.models import Import, ImportRow
from apps.djb_imports.services import apply_import, create_import
from apps.djb_imports.tests import planted
from apps.djb_imports.tests.conftest import FIVE_ROWS_ONE_BAD
from apps.djb_imports.tests.store import stored_csv
from apps.djb_imports.types import ImportSettled
from apps.example.models import Widget
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun
from apps.workflows.services import workflow_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import Tenant

pytestmark = pytest.mark.django_db(transaction=True)


def run_id(tenant: Tenant, run: Import, phase: str) -> str:
    """The id the service used — DERIVED, never remembered (house rule 18)."""
    return workflow_id(tenant=tenant, app="djb_imports", noun="import", key=f"{run.pk}-{phase}")


async def _local_client(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> Client:
    """Point everything at the test server, including the on-commit hook."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)
    return attach_interceptors(env.client)


@pytest.fixture
def small_world(db: None, memory_store: dict[str, bytes], planted_importer: None) -> Any:
    """A tenant, its root, an owner acting there — written on the synchronous side."""
    from apps.accounts.services import create_user
    from apps.core.models import Membership
    from apps.core.services import add_membership

    tenant = create_tenant(name="Acme", slug="acme", actor=system_actor())
    root = root_organization(tenant=tenant)
    owner = create_user(email="imports-owner@acme.com", password="a" * 24)
    add_membership(
        user=owner,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=tenant),
    )
    return tenant, actor_for(user=owner, tenant=tenant, org=root)


async def _staged_and_checked(client: Client, tenant: Tenant, actor: Any) -> Import:
    version = await run_db(stored_csv, actor, FIVE_ROWS_ONE_BAD)
    run, created = await run_db(
        create_import, tenant=tenant, actor=actor, kind="widget", file_version=version
    )
    assert created
    handle = client.get_workflow_handle(run_id(tenant, run, "check"), result_type=ImportSettled)
    settled: ImportSettled = await handle.result()
    assert settled.status == "previewed", settled
    return run


@pytest.mark.asyncio
async def test_staging_starts_the_check_which_previews_and_closes_its_row(
    small_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IM.1 / IM.2 on a worker: started on commit, previewed, nothing written, row closed."""
    tenant, actor = small_world

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            run = await _staged_and_checked(client, tenant, actor)
            described = await client.get_workflow_handle(run_id(tenant, run, "check")).describe()

    assert described.status == WorkflowExecutionStatus.COMPLETED
    checked = await run_db(lambda: Import.objects.get(pk=run.pk))
    assert checked.counts == {"create": 4, "update": 0, "unchanged": 0, "refused": 1}
    assert await run_db(lambda: Widget.objects.filter(tenant=tenant).count()) == 0
    row = await run_db(lambda: WorkflowRun.objects.get(workflow_id=run_id(tenant, run, "check")))
    assert row.status == WorkflowRun.Status.COMPLETED


@pytest.mark.asyncio
async def test_apply_writes_the_four_clean_rows_through_the_importer(
    small_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IM.3: `imported`, four widgets, four `create_widget` audit rows, one correlation."""
    tenant, actor = small_world

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            run = await _staged_and_checked(client, tenant, actor)
            await run_db(apply_import, tenant=tenant, actor=actor, import_=run)
            applied: ImportSettled = await client.get_workflow_handle(
                run_id(tenant, run, "apply"), result_type=ImportSettled
            ).result()

    assert applied.status == "imported"
    assert applied.counts == {"create": 4, "update": 0, "unchanged": 0, "refused": 1}
    widgets = await run_db(
        lambda: sorted(Widget.objects.filter(tenant=tenant).values_list("name", flat=True))
    )
    assert widgets == ["Alpha", "Bravo", "Delta", "Echo"]
    audits = await run_db(
        lambda: list(
            AuditEntry.objects.filter(tenant=tenant, action="example.create_widget").values_list(
                "correlation_id", "actor_user_id", "actor_kind"
            )
        )
    )
    assert len(audits) == 4
    assert len({correlation for correlation, _, _ in audits}) == 1, audits
    assert {user for _, user, _ in audits} == {actor.user_id}, "written as the person who applied"
    refused = await run_db(lambda: list(ImportRow.objects.filter(run=run, outcome="refused")))
    assert [row.row_no for row in refused] == [3]
    finished = await run_db(
        lambda: WorkflowRun.objects.get(workflow_id=run_id(tenant, run, "apply"))
    )
    assert finished.status == WorkflowRun.Status.COMPLETED


@pytest.mark.asyncio
async def test_an_apply_that_dies_part_way_resumes_and_writes_each_row_once(
    small_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IM.3's property in process: a crash after two rows, a retry, four widgets — not 5+."""
    tenant, actor = small_world
    real_apply = planted.apply
    calls = {"n": 0}

    def dies_on_the_third_row_once(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 3:
            # Not a domain refusal: a crash, which escapes the row's service and
            # fails the whole activity attempt — the in-process stand-in for a
            # worker killed mid-apply.
            raise RuntimeError("worker died mid-apply")
        return real_apply(**kwargs)

    monkeypatch.setitem(
        planted.IMPORTERS,
        "widget",
        Importer(
            row=planted.PlantedWidgetRow,
            natural_key=planted.natural_key,
            apply=dies_on_the_third_row_once,
        ),
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            run = await _staged_and_checked(client, tenant, actor)
            await run_db(apply_import, tenant=tenant, actor=actor, import_=run)
            handle = client.get_workflow_handle(
                run_id(tenant, run, "apply"), result_type=ImportSettled
            )
            applied: ImportSettled = await handle.result()
            history = await handle.fetch_history()

    assert applied.status == "imported"
    assert calls["n"] == 5, "four clean rows plus the one call that died — no row applied twice"
    assert await run_db(lambda: Widget.objects.filter(tenant=tenant).count()) == 4
    attempts = [
        event.activity_task_started_event_attributes.attempt
        for event in history.events
        if event.HasField("activity_task_started_event_attributes")
    ]
    assert max(attempts) >= 2, "the apply activity was retried"


#: How long the held row waits on the test, and then on the cancel reaching it.
#: Bounded, so a broken arm fails this test instead of hanging the suite.
HOLD_SECONDS = 60


@pytest.mark.asyncio
async def test_a_cancel_mid_apply_closes_the_run_and_leaves_no_row_half_applied(
    small_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel mid-apply: the run closes `cancelled`, the import says so, every row whole.

    The third clean row is held on an `Event` until the test has asked Temporal
    to cancel, and then until the cancel has reached the activity (a synchronous
    activity learns of it only through a heartbeat's answer, so the held row
    heartbeats while it waits — a slow row doing what a slow row should). The
    count asserted is the number of `apply` calls that RETURNED: the activity
    stops at a row boundary, so a row is either written whole or not at all.
    """
    tenant, actor = small_world
    real_apply = planted.apply
    calls = {"entered": 0, "returned": 0}
    released = threading.Event()

    def holds_the_third_row(**kwargs: Any) -> Any:
        calls["entered"] += 1
        if calls["entered"] == 3:
            released.wait(HOLD_SECONDS)
            deadline = time.monotonic() + HOLD_SECONDS
            while not activity.is_cancelled() and time.monotonic() < deadline:
                activity.heartbeat("held")
                time.sleep(0.1)
        applied = real_apply(**kwargs)
        calls["returned"] += 1
        return applied

    monkeypatch.setitem(
        planted.IMPORTERS,
        "widget",
        Importer(
            row=planted.PlantedWidgetRow,
            natural_key=planted.natural_key,
            apply=holds_the_third_row,
        ),
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            run = await _staged_and_checked(client, tenant, actor)
            await run_db(apply_import, tenant=tenant, actor=actor, import_=run)
            handle = client.get_workflow_handle(
                run_id(tenant, run, "apply"), result_type=ImportSettled
            )
            deadline = time.monotonic() + HOLD_SECONDS
            while await run_db(lambda: Widget.objects.filter(tenant=tenant).count()) < 2:
                assert time.monotonic() < deadline, "the first two rows never landed"
                await asyncio.sleep(0.05)
            await handle.cancel()
            released.set()
            with pytest.raises(WorkflowFailureError) as ended:
                await handle.result()
            # Read BEFORE the worker shuts down: its graceful shutdown would let
            # an abandoned activity finish, and hide that the run closed first.
            calls_when_the_run_ended = dict(calls)
            described = await handle.describe()

    row = await run_db(lambda: WorkflowRun.objects.get(workflow_id=run_id(tenant, run, "apply")))
    settled = await run_db(lambda: Import.objects.get(pk=run.pk))
    outcomes = await run_db(
        lambda: sorted(
            ImportRow.objects.filter(run=run).exclude(outcome="").values_list("row_no", "outcome")
        )
    )
    observed = {
        "temporal": described.status and described.status.name,
        "cause": type(ended.value.cause).__name__,
        "run": (str(row.status), row.error),
        "import": (str(settled.status), settled.failure, settled.cancelled_at is not None),
        "apply_calls_when_the_run_ended": calls_when_the_run_ended,
        "apply_calls": dict(calls),
        "widgets": await run_db(lambda: Widget.objects.filter(tenant=tenant).count()),
        "settled_rows": outcomes,
    }
    assert observed == {
        "temporal": "CANCELED",
        "cause": "CancelledError",
        "run": ("cancelled", "cancelled"),
        "import": ("failed", {}, True),
        # The held row finished whole, the cancel was seen at its boundary, and
        # no row after it was begun: one widget per `apply` call that returned.
        # The run closed only after that — the workflow WAITED for the writer.
        "apply_calls_when_the_run_ended": {"entered": 3, "returned": 3},
        "apply_calls": {"entered": 3, "returned": 3},
        "widgets": 3,
        "settled_rows": [(1, "created"), (2, "created"), (3, "refused"), (4, "created")],
    }


@pytest.mark.asyncio
async def test_a_cancel_mid_check_closes_the_run_and_the_import_as_cancelled(
    small_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cancel during the dry run: the run closes `cancelled` and the import says so.

    The check does not heartbeat, so its workflow does not wait for it (the
    default cancellation type): the cancel arm closes the import while the
    check is held on its first lookup. The lookup runs under the preview's lock
    on the import row, so the arm's write waits for the check and lands after
    it — whichever order, the import ends `failed` with `cancelled`, the run
    ends `cancelled`, and no widget is written.
    """
    tenant, actor = small_world
    entered = threading.Event()
    released = threading.Event()

    def holds_the_first_lookup(**kwargs: Any) -> Any:
        entered.set()
        released.wait(HOLD_SECONDS)
        return planted.natural_key(**kwargs)

    monkeypatch.setitem(
        planted.IMPORTERS,
        "widget",
        Importer(
            row=planted.PlantedWidgetRow,
            natural_key=holds_the_first_lookup,
            apply=planted.apply,
        ),
    )

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            version = await run_db(stored_csv, actor, FIVE_ROWS_ONE_BAD)
            run, _ = await run_db(
                create_import, tenant=tenant, actor=actor, kind="widget", file_version=version
            )
            handle = client.get_workflow_handle(
                run_id(tenant, run, "check"), result_type=ImportSettled
            )
            assert await asyncio.to_thread(entered.wait, HOLD_SECONDS), "the check never looked"
            await handle.cancel()
            released.set()
            with pytest.raises(WorkflowFailureError) as ended:
                await handle.result()
            described = await handle.describe()

    row = await run_db(lambda: WorkflowRun.objects.get(workflow_id=run_id(tenant, run, "check")))
    settled = await run_db(lambda: Import.objects.get(pk=run.pk))
    observed = {
        "temporal": described.status and described.status.name,
        "cause": type(ended.value.cause).__name__,
        "run": (str(row.status), row.error),
        "import": (str(settled.status), settled.failure, settled.cancelled_at is not None),
        "widgets": await run_db(lambda: Widget.objects.filter(tenant=tenant).count()),
    }
    assert observed == {
        "temporal": "CANCELED",
        "cause": "CancelledError",
        "run": ("cancelled", "cancelled"),
        "import": ("failed", {}, True),
        "widgets": 0,
    }
