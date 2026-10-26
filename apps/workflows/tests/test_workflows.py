"""Durable work, end to end, with no dev server.

`WorkflowEnvironment.start_time_skipping()` gives a real Temporal server with a
skippable clock, so these tests exercise the actual worker assembly — the one
`apps.workflows.client.build_worker` discovers — rather than a stand-in.

What is proved here is the wiring nobody can see from a diff: the worker finds
the workflow and the activity, the worker closes the activity pool it was
handed when it shuts down, the acting tenant survives the trip from the client
into the activity, and the `WorkflowRun` row transitions from running to
completed.
"""

from __future__ import annotations

import ast
import inspect
from typing import Any

import pytest
from django.core import mail as django_mail
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment

from apps.accounts.models import User
from apps.core.asyncdb import run_db
from apps.core.determinism import run_to_finish
from apps.core.models import Tenant
from apps.workflows import workflows as workflow_definitions
from apps.workflows.client import (
    attach_interceptors,
    build_worker,
    discovered_activities,
    discovered_workflows,
)
from apps.workflows.models import WorkflowRun
from apps.workflows.services import start_workflow
from apps.workflows.types import EchoOutput, MoveOrganization, SendEmail

# `transaction=True`: the activity writes from another thread, on another
# connection, so the rows have to be really committed for it to see them.
pytestmark = pytest.mark.django_db(transaction=True)

TASK_QUEUE = "djb-tests"

#: What a planted activity says when it refuses, so the row's `error` can be
#: matched on something a human wrote rather than on a framework's wording.
PLANTED = "planted to fail by the test"


def plant_a_failing_activity(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap one **discovered** activity for one that always refuses.

    Through `ACTIVITIES` rather than by hand-building a worker, so the worker
    under test is still the real assembly: everything else — `mark_run_finished`
    above all — is the production function.
    """
    from apps.workflows import activities as workflow_activities

    @activity.defn(name=name)
    def refuse(_payload: Any) -> Any:
        raise ApplicationError(f"{name} was {PLANTED}", non_retryable=True)

    monkeypatch.setattr(
        workflow_activities,
        "ACTIVITIES",
        [
            refuse if getattr(one, "__temporal_activity_definition").name == name else one
            for one in workflow_activities.ACTIVITIES
        ],
    )


def test_the_worker_discovers_what_the_apps_declared() -> None:
    assert "EchoWorkflow" in {workflow.__name__ for workflow in discovered_workflows()}
    names = {
        getattr(activity, "__temporal_activity_definition").name
        for activity in discovered_activities()
    }
    assert "mark_run_finished" in names


def test_the_worker_and_introspect_read_one_population() -> None:
    """The worker's assembly and the schema dump are two callers of one discovery walk.

    `introspect` reports what the worker would register; if the two walked
    differently (a tuple one accepts and the other skips), the dump would
    describe a worker that does not exist.
    """
    from apps.core.management.commands import introspect

    worker = sorted(
        getattr(workflow, "__temporal_workflow_definition").name
        for workflow in discovered_workflows()
    )
    dumped = sorted(str(entry["name"]) for entry in introspect._workflows_payload())
    assert worker, "an empty population would agree with anything"
    assert worker == dumped
    activities = sorted(
        getattr(activity, "__temporal_activity_definition").name
        for activity in discovered_activities()
    )
    assert activities == sorted(str(entry["name"]) for entry in introspect._activities_payload())


def test_shutting_the_worker_down_shuts_its_activity_pool_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**The granted line, proven rather than hoped.**

    `Worker.__aexit__` shuts the worker down and leaves an externally supplied
    `activity_executor` running — reasonably, since Temporal never owned it. Each
    of that pool's threads holds a Django database connection, and under
    `pytest-xdist` the garbage collector reaping them races the test-database
    teardown of the worker's own process. `build_worker` therefore hands back a
    worker that closes what it was given.

    Driven at `shutdown()` rather than through a live `async with`, because the
    property is about the pool and not about Temporal: dialling a real server to
    assert a local `Executor` had gone quiet would make an isolation test into an
    integration one. The fixture is the same object the real path uses.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    from temporalio.worker import Worker

    from apps.workflows.client import _PoolClosingWorker

    async def already_down(self: Any) -> None:
        """Temporal's half, stubbed: this test is about the pool, not the server."""

    monkeypatch.setattr(Worker, "shutdown", already_down)

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pool-lifetime-test-")
    worker = object.__new__(_PoolClosingWorker)
    worker._activity_pool = pool

    assert pool.submit(lambda: "alive").result() == "alive"

    asyncio.run(worker.shutdown())

    with pytest.raises(RuntimeError, match="shutdown"):
        pool.submit(lambda: "still here")


@pytest.mark.asyncio
async def test_echo_runs_end_to_end_and_carries_its_tenant(tenant: Tenant, owner: User) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        # The test environment builds a bare client; the interceptor that carries
        # the tenant has to be attached to it, exactly as `get_client` does.
        client = attach_interceptors(env.client)
        worker = build_worker(client, queue=TASK_QUEUE)
        async with worker:
            run = await start_workflow(
                workflow="EchoWorkflow",
                arg="hello",
                tenant=tenant,
                user=owner,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:workflows:echo:end-to-end",
            )
            assert run.status == WorkflowRun.Status.RUNNING
            assert run.finished_at is None

            handle = client.get_workflow_handle(run.workflow_id, result_type=EchoOutput)
            result: EchoOutput = await handle.result()

    assert result.message == "hello"
    # The activity read the tenant off a contextvar the interceptor filled from
    # the workflow's headers. Nothing passed it as an argument.
    assert result.tenant_slug == tenant.slug

    finished = await run_db(lambda: WorkflowRun.objects.for_tenant(tenant).get(pk=run.pk))
    assert finished.status == WorkflowRun.Status.COMPLETED
    assert finished.finished_at is not None
    assert finished.error == ""
    assert finished.run_id != ""


@pytest.mark.asyncio
async def test_another_tenant_cannot_see_the_run(tenant: Tenant, other_tenant: Tenant) -> None:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        worker = build_worker(client, queue=TASK_QUEUE)
        async with worker:
            run = await start_workflow(
                workflow="EchoWorkflow",
                arg="mine",
                tenant=tenant,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:workflows:echo:mine",
            )
            handle = client.get_workflow_handle(run.workflow_id, result_type=EchoOutput)
            await handle.result()

    visible = await run_db(lambda: WorkflowRun.objects.for_tenant(other_tenant).count())
    assert visible == 0
    mine = await run_db(lambda: WorkflowRun.objects.for_tenant(tenant).count())
    assert mine == 1


@pytest.mark.asyncio
async def test_an_email_is_sent_by_the_activity_not_by_the_caller(
    tenant: Tenant, owner: User
) -> None:
    """The whole email path, end to end: workflow → activity → backend.

    This is the shape `architecture.md` rules — the Django email backend called
    from a workflow activity — and it is the only test that proves the parts
    join up. The message lands in `django.core.mail.outbox` because the test
    settings use the locmem backend; in a worktree it would be Mailpit, and in
    production a provider.
    """
    outbox_before = len(django_mail.outbox)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        worker = build_worker(client, queue=TASK_QUEUE)
        async with worker:
            run = await start_workflow(
                workflow="SendEmailWorkflow",
                arg=SendEmail(
                    to=["newcomer@example.com"],
                    subject="You have been invited to Acme",
                    template="invitation",
                    context={
                        "tenant_name": tenant.name,
                        "email": "newcomer@example.com",
                        "role": "Member",
                        "signup_url": "http://127.0.0.1:8000/accounts/signup/",
                        "expires_on": "2026-09-02",
                    },
                ),
                tenant=tenant,
                user=owner,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:workflows:email:invitation",
            )
            handle = client.get_workflow_handle(run.workflow_id, result_type=int)
            accepted: int = await handle.result()

    assert accepted == 1
    assert len(django_mail.outbox) == outbox_before + 1
    message = django_mail.outbox[-1]
    assert message.subject == "You have been invited to Acme"
    assert message.to == ["newcomer@example.com"]
    assert "Acme invited you to join them." in message.body


@pytest.mark.asyncio
async def test_a_re_parent_runs_as_a_workflow_and_rewrites_the_subtree(
    tenant: Tenant, owner: User
) -> None:
    """The move's durable half, against a real server.

    `core.services.move_organization` authorizes and starts this run; what is
    proved here is the part a unit test cannot see — that the worker finds
    `MoveOrganizationWorkflow` and `rewrite_organization_paths`, that the
    acting tenant AND the acting org survive the trip on the workflow's
    headers, and that the activity's write lands: the node is re-parented and
    every descendant's path moves with it.
    """
    from apps.core.actor import actor_for
    from apps.core.models import Organization
    from apps.core.services import create_organization, root_organization

    def build() -> tuple[Organization, Organization, Organization]:
        hq = root_organization(tenant=tenant)
        acting = actor_for(user=owner, tenant=tenant, org=hq)
        a = create_organization(
            tenant=tenant, parent=hq, name="Seller A", slug="seller-a", actor=acting
        )
        b = create_organization(
            tenant=tenant, parent=hq, name="Seller B", slug="seller-b", actor=acting
        )
        a1 = create_organization(
            tenant=tenant, parent=a, name="Sub A1", slug="sub-a1", actor=acting
        )
        return (
            b,
            a1,
            create_organization(
                tenant=tenant, parent=a1, name="Sub A1a", slug="sub-a1a", actor=acting
            ),
        )

    seller_b, sub_a1, grandchild = await run_db(build)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow="MoveOrganizationWorkflow",
                arg=MoveOrganization(
                    organization_id=str(sub_a1.pk),
                    new_parent_id=str(seller_b.pk),
                ),
                tenant=tenant,
                user=owner,
                org=seller_b,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:core:organization:{sub_a1.pk}",
            )
            handle = client.get_workflow_handle(run.workflow_id, result_type=str)
            new_path: str = await handle.result()

    moved = await run_db(lambda: Organization.objects.for_tenant(tenant).get(pk=sub_a1.pk))
    assert moved.path == new_path
    assert moved.parent_id == seller_b.pk
    assert moved.path.startswith(seller_b.path + ".")

    below = await run_db(lambda: Organization.objects.for_tenant(tenant).get(pk=grandchild.pk))
    assert below.path.startswith(moved.path + ".")
    assert below.depth == moved.depth + 1

    # The move's success half: the move closes its own row now (ADR workflows-5).
    closed = await run_db(lambda: WorkflowRun.objects.for_tenant(tenant).get(pk=run.pk))
    assert closed.status == WorkflowRun.Status.COMPLETED
    assert closed.finished_at is not None
    assert closed.error == ""


@pytest.mark.asyncio
async def test_the_email_run_closes_its_own_visibility_row(tenant: Tenant, owner: User) -> None:
    """The platform app's own workflows close their rows too.

    `SendEmailWorkflow` had no `mark_run_finished` anywhere in it, so every
    email run this product has ever started still says RUNNING — for as long as
    the row is kept. A reconciler sweeping dead runs would read those rows as
    live work, which is why these two had to land together.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow="SendEmailWorkflow",
                arg=SendEmail(
                    to=["closes@example.com"],
                    subject="You have been invited to Acme",
                    template="invitation",
                    context={
                        "tenant_name": tenant.name,
                        "email": "closes@example.com",
                        "role": "Member",
                        "signup_url": "https://example.test/accounts/signup/",
                        "expires_on": "2026-09-02",
                    },
                ),
                tenant=tenant,
                user=owner,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:workflows:email:closes",
            )
            await client.get_workflow_handle(run.workflow_id, result_type=int).result()

    closed = await run_db(lambda: WorkflowRun.objects.for_tenant(tenant).get(pk=run.pk))
    assert closed.status == WorkflowRun.Status.COMPLETED
    assert closed.finished_at is not None
    assert closed.error == ""


# --- The closing seam, both halves, for all three -------------------------------
#
# ADR workflows-5. The interesting half is the failure: a workflow that marked
# its row *before* doing the work would say `completed` for a run that failed,
# and nothing downstream — a reconciler, an operator, a support query — could
# tell. So each of the three is driven once through a planted failure, and the
# row has to end `failed` with the activity's own complaint on it.


@pytest.mark.parametrize(
    ("name", "run_method"),
    [
        ("EchoWorkflow", workflow_definitions.EchoWorkflow.run),
        ("SendEmailWorkflow", workflow_definitions.SendEmailWorkflow.run),
        ("MoveOrganizationWorkflow", workflow_definitions.MoveOrganizationWorkflow.run),
    ],
)
def test_every_platform_workflow_marks_its_run_last(name: str, run_method: Any) -> None:
    """The mark is the LAST thing before return, never the first.

    Read off the source in source order, because that is the property — a
    workflow whose `run_to_finish` were merely *present* somewhere could still be
    `EchoWorkflow` as it was, marking itself complete and then doing the work.
    """
    body = ast.parse(inspect.cleandoc(inspect.getsource(run_method)))
    awaits = sorted(
        (node for node in ast.walk(body) if isinstance(node, ast.Await)),
        key=lambda node: (node.lineno, node.col_offset),
    )
    assert awaits, f"{name}.run awaits nothing at all"
    last = awaits[-1].value
    assert isinstance(last, ast.Call) and getattr(last.func, "id", "") == run_to_finish.__name__, (
        f"{name}.run's last await is {ast.unparse(last)}, not the finish seam"
    )


@pytest.mark.asyncio
async def test_an_echo_that_fails_before_the_mark_leaves_a_failed_row(tenant: Tenant) -> None:
    """The behavioural half: the anti-pattern would have said `completed`."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow="EchoWorkflow",
                arg="",
                tenant=tenant,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:workflows:echo:empty",
            )
            with pytest.raises(WorkflowFailureError):
                await client.get_workflow_handle(run.workflow_id, result_type=EchoOutput).result()

    row = await run_db(lambda: WorkflowRun.objects.for_tenant(tenant).get(pk=run.pk))
    assert row.status == WorkflowRun.Status.FAILED
    assert row.finished_at is not None
    assert "empty message" in row.error


@pytest.mark.asyncio
async def test_an_email_that_never_lands_leaves_a_failed_row(
    tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure half: the error string is on the row, not only in history."""
    plant_a_failing_activity("send_email", monkeypatch)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow="SendEmailWorkflow",
                arg=SendEmail(
                    to=["nowhere@example.com"],
                    subject="You have been invited to Acme",
                    template="invitation",
                    context={
                        "tenant_name": tenant.name,
                        "email": "nowhere@example.com",
                        "role": "Member",
                        "signup_url": "https://example.test/accounts/signup/",
                        "expires_on": "2026-09-02",
                    },
                ),
                tenant=tenant,
                user=owner,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:workflows:email:refused",
            )
            with pytest.raises(WorkflowFailureError):
                await client.get_workflow_handle(run.workflow_id, result_type=int).result()

    row = await run_db(lambda: WorkflowRun.objects.for_tenant(tenant).get(pk=run.pk))
    assert row.status == WorkflowRun.Status.FAILED
    assert row.finished_at is not None
    assert PLANTED in row.error


@pytest.mark.asyncio
async def test_a_move_closes_its_row_and_says_so_when_it_fails(
    tenant: Tenant, owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure half. The success half is the re-parent test above."""
    from apps.core.actor import actor_for
    from apps.core.models import Organization
    from apps.core.services import create_organization, root_organization

    def build() -> tuple[Organization, Organization]:
        hq = root_organization(tenant=tenant)
        acting = actor_for(user=owner, tenant=tenant, org=hq)
        return (
            create_organization(
                tenant=tenant, parent=hq, name="Seller C", slug="seller-c", actor=acting
            ),
            create_organization(
                tenant=tenant, parent=hq, name="Seller D", slug="seller-d", actor=acting
            ),
        )

    moving, destination = await run_db(build)
    plant_a_failing_activity("rewrite_organization_paths", monkeypatch)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with build_worker(client, queue=TASK_QUEUE):
            run = await start_workflow(
                workflow="MoveOrganizationWorkflow",
                arg=MoveOrganization(
                    organization_id=str(moving.pk),
                    new_parent_id=str(destination.pk),
                ),
                tenant=tenant,
                user=owner,
                org=destination,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:core:organization:{moving.pk}",
            )
            with pytest.raises(WorkflowFailureError):
                await client.get_workflow_handle(run.workflow_id, result_type=str).result()

    row = await run_db(lambda: WorkflowRun.objects.for_tenant(tenant).get(pk=run.pk))
    assert row.status == WorkflowRun.Status.FAILED
    assert row.finished_at is not None
    assert PLANTED in row.error
    # And the tree did not half-move: the node is where it was.
    unmoved = await run_db(lambda: Organization.objects.for_tenant(tenant).get(pk=moving.pk))
    assert unmoved.parent_id == moving.parent_id
