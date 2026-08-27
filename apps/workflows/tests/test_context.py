"""Who a workflow is running for, and what happens when nobody said.

Three properties. The first two are the two halves of one earlier finding; the third is
the contract the accessors themselves have, stated where a caller will look.

**The stamping half.** `_WorkflowOutbound` put the tenant, the acting hat and
the correlation chain onto an outbound *activity* and onto nothing else, so a
child workflow and a cross-workflow signal shed all three. The parent/child
pair in `childwork.py` is the smallest thing that can see that.

**The loud half.** An activity that lost its principal did not fail — it read
`for_tenant(None)`, found nothing, and carried on. Empty reads instead of a
refusal is the worst shape a tenancy bug can take, because every assertion
downstream of it passes. `workflow_context()` now raises; `platform_context()`
is the declared opt-out for the one population that legitimately has no tenant.

**What the opt-out actually promises.** `platform_context()` answers three
things and may answer None — and it does **not** assert that the tenant is
absent: a platform run whose headers carry a tenant gets that tenant back.
Refusing that mismatch is the caller's job, not the accessor's. Where the name
is *registered* on the core bridge is a different surface, pinned next door in
`test_platform_context_bridge.py`.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from django.db import close_old_connections
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from apps.accounts.models import User
from apps.core import bridge
from apps.core import context as observability
from apps.core.models import Organization, Tenant
from apps.workflows.client import (
    MAX_CONCURRENT_ACTIVITIES,
    attach_interceptors,
    discovered_activities,
    discovered_workflows,
)
from apps.workflows.context import (
    TENANT_HEADER,
    platform_context,
    reset_principal,
    set_principal,
    workflow_context,
)
from apps.workflows.services import start_workflow
from apps.workflows.tests.childwork import (
    ChildContextWorkflow,
    ParentContextWorkflow,
    SeenContext,
)

pytestmark = pytest.mark.django_db(transaction=True)

TASK_QUEUE = "djb-tests-context"


@activity.defn(name="report_workflow_context")
def report_workflow_context(_note: str) -> SeenContext:
    """Say what the principal looks like from inside whatever invoked this.

    A test activity rather than a production one: nothing in the product needs
    to report its own context, and an activity that existed only to be asserted
    on would be a canonical file growing a second job (house rule 11).

    It reads through `platform_context()` and not `workflow_context()` for a
    reason that is the point of the test: a reporter has to be able to report
    **absence**. Reading through the loud accessor would turn "the child saw
    nothing" into an activity failure, and the property under test would be
    proved by an exception type instead of by the empty string it is about.
    """
    close_old_connections()
    try:
        tenant, _user_id, org = platform_context()
        return SeenContext(
            tenant_slug=tenant.slug if tenant is not None else "",
            org_slug=org.slug if org is not None else "",
            correlation_id=str(observability.value("correlation_id") or ""),
        )
    finally:
        close_old_connections()


def worker_with_the_pair(client: Any) -> Worker:
    """The real assembly, plus the test-only parent, child and reporter.

    Built here rather than through `build_worker` because these three are
    deliberately not discovered: a parent/child pair that shipped in
    `WORKFLOWS` would be a fixture in production's discovery.
    """
    return Worker(
        attach_interceptors(client),
        task_queue=TASK_QUEUE,
        workflows=[*discovered_workflows(), ParentContextWorkflow, ChildContextWorkflow],
        activities=[*discovered_activities(), report_workflow_context],
        activity_executor=ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_ACTIVITIES,
            thread_name_prefix="temporal-activity-",
        ),
        max_concurrent_activities=MAX_CONCURRENT_ACTIVITIES,
    )


@pytest.mark.asyncio
async def test_a_child_workflow_carries_the_parents_tenant_and_hat(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    """The child is where the principal used to be dropped."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with worker_with_the_pair(client):
            run = await start_workflow(
                workflow="ParentContextWorkflow",
                arg=f"{tenant.slug}:workflows:child:seen",
                tenant=tenant,
                user=owner,
                org=root_org,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:workflows:parent:seen",
            )
            seen: SeenContext = await client.get_workflow_handle(
                run.workflow_id, result_type=SeenContext
            ).result()

    assert seen.tenant_slug == tenant.slug
    assert seen.org_slug == root_org.slug
    assert seen.correlation_id != ""


def test_workflow_context_refuses_a_run_that_stamped_no_tenant() -> None:
    """At the accessor: loud, and it names the header that is missing."""
    with pytest.raises(RuntimeError, match=TENANT_HEADER):
        workflow_context()


def test_platform_context_is_the_declared_opt_out() -> None:
    """The valve: platform scope, no tenant, and it says so rather than raising."""
    assert platform_context() == (None, None, None)


def test_a_production_activity_refuses_a_run_that_stamped_no_tenant() -> None:
    """Through an activity, not only the accessor.

    `send_email` is the shape every tenant activity has — restore the
    principal, then act. Invoked with nothing stamped it used to hand the
    message to the mail host and log `tenant=None`; it now refuses before the
    host is touched, which is why the payload below never has to be renderable.
    """
    from apps.workflows.activities import send_email
    from apps.workflows.types import SendEmail

    with pytest.raises(RuntimeError, match=TENANT_HEADER):
        send_email(SendEmail(to=["nobody@example.com"], subject="Hello", template="invitation"))


def test_the_run_closer_proceeds_with_no_tenant_because_it_serves_both_populations() -> None:
    """The other side of the same criterion: the valve, in the one activity that needs it.

    `mark_run_finished` closes rows for a tenant's runs **and** for the
    platform's (ADR workflows-3), so it is the one activity in this app that
    cannot demand a tenant. It reports the empty slug rather than raising, and
    `finish_run` routes the read on exactly that.
    """
    from apps.workflows.activities import mark_run_finished
    from apps.workflows.types import MarkRunFinished

    seen = mark_run_finished(
        MarkRunFinished(workflow_id="platform:accounts:identity:absent", status="completed")
    )
    assert seen == ""


# --- The accessors' own contract, as the code has it --------------------------


def test_it_answers_three_things_and_may_answer_none() -> None:
    """The declared opt-out, through the bridge rather than through the import."""
    read = bridge.get(bridge.PLATFORM_CONTEXT)

    answer = read()

    assert isinstance(answer, tuple)
    assert len(answer) == 3
    assert answer == (None, None, None)


def test_the_tenanted_accessor_raises_where_this_one_answers() -> None:
    """The two are not synonyms, and that is the whole reason there are two."""
    with pytest.raises(RuntimeError):
        bridge.get(bridge.WORKFLOW_CONTEXT)()

    assert bridge.get(bridge.PLATFORM_CONTEXT)() == (None, None, None)


def test_it_hands_back_a_stamped_tenant_rather_than_refusing_it(tenant: Tenant) -> None:
    """**The accessor's real contract, pinned as found — not as hoped.**

    ADR core-9 says a platform kind invoked under tenant-stamped headers must
    fail loudly rather than proceed cross-scoped. This test records *where* that
    refusal cannot come from: `platform_context()` is a plain read of the
    contextvars the interceptor set, and a tenant that is stamped comes straight
    back out. It has no way to know whether its caller is a platform run.

    So the refusal is the caller's, and it lands at the activity that knows —
    `apps/accounts/tests/test_federation.py` drives it there. Hardening this
    accessor would be a rung of its own; leaving the mismatch un-recorded is
    what would let the next platform activity skip the assertion silently,
    exactly as today's two do.
    """
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=None)
    try:
        restored, _user_id, _org = bridge.get(bridge.PLATFORM_CONTEXT)()
    finally:
        reset_principal(tokens)

    assert restored == tenant, "platform_context does not refuse a stamped tenant"
