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
  exception raised; this is the in-process half.

`transaction=True` throughout: the activities run on worker threads with their
own connections, and an `on_commit` hook only fires on a real commit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment

from apps.core.actor import actor_for, system_actor
from apps.core.asyncdb import run_db
from apps.core.audit import AuditEntry
from apps.core.services import create_tenant, root_organization
from apps.core.verbs import Importer
from apps.example.models import Widget
from apps.imports.models import Import, ImportRow
from apps.imports.services import apply_import, create_import
from apps.imports.tests import planted
from apps.imports.tests.conftest import FIVE_ROWS_ONE_BAD, stored_csv
from apps.imports.types import ImportSettled
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker
from apps.workflows.models import WorkflowRun
from apps.workflows.services import workflow_id

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import Tenant

pytestmark = pytest.mark.django_db(transaction=True)


def run_id(tenant: Tenant, run: Import, phase: str) -> str:
    """The id the service used — DERIVED, never remembered (house rule 18)."""
    return workflow_id(tenant=tenant, app="imports", noun="import", key=f"{run.pk}-{phase}")


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
