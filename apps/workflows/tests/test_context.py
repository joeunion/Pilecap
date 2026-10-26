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

import asyncio
import contextlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.db import close_old_connections
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from apps.accounts.models import User
from apps.core import bridge
from apps.core import context as observability
from apps.core.audit import AuditEntry
from apps.core.headers import ORG_HEADER, TENANT_HEADER
from apps.core.models import Membership, Organization, Tenant
from apps.core.tests import hats
from apps.workflows.client import (
    MAX_CONCURRENT_ACTIVITIES,
    attach_interceptors,
    discovered_activities,
    discovered_workflows,
)
from apps.workflows.context import (
    RUN_CHAIN_NAMESPACE,
    platform_context,
    reset_principal,
    set_principal,
    workflow_context,
)
from apps.workflows.models import WorkflowRun
from apps.workflows.services import start_workflow
from apps.workflows.tests.childwork import (
    ChildContextWorkflow,
    ParentContextWorkflow,
    SeenContext,
    TwoChains,
    TwoStepChainWorkflow,
)
from apps.workflows.tests.hatwork import RevokedHatWorkflow

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


#: What `act_under_the_hat` did, in order: one entry per call that got PAST the
#: accessor. A module-level list because the activity runs on a worker thread in
#: this process, and the test reads it back between the two halves of the run.
HAT_CALLS: list[str] = []


@activity.defn(name="act_under_the_hat")
def act_under_the_hat(note: str) -> str:
    """The shape every tenant activity has: restore the principal, then act.

    It records its note only once `workflow_context()` has answered, so an entry
    in `HAT_CALLS` is an activity that acted, and a refused call leaves nothing.
    """
    close_old_connections()
    try:
        _tenant, _user_id, org = workflow_context()
        HAT_CALLS.append(note)
        return org.slug if org is not None else ""
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
        workflows=[
            *discovered_workflows(),
            ParentContextWorkflow,
            ChildContextWorkflow,
            RevokedHatWorkflow,
            TwoStepChainWorkflow,
        ],
        activities=[*discovered_activities(), report_workflow_context, act_under_the_hat],
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


# --- The hat is revalidated at every activity boundary ------------------------
#
# The hat rides on the run's headers from the moment the run starts, and a
# person can lose it while the run waits. Every other door asks
# `core.middleware.resolve_org` on every request; the activity boundary is a
# door for this purpose, so it asks the same question.

#: The hat fixtures' home is `apps.core.tests.hats`; bound here by name so pytest finds them.
branch = hats.branch
branch_membership = hats.branch_membership
_revoke = hats.revoke
HAT_REVOKED = hats.HAT_REVOKED


async def _until_acted(expected: list[str]) -> None:
    """Wait, bounded, for the first activity to have acted."""
    for _ in range(600):
        if expected == HAT_CALLS:
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"the first activity never acted; saw {HAT_CALLS!r}")


@pytest.mark.asyncio
async def test_a_revoked_hat_is_refused_at_the_next_activity(
    tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    branch_membership: Membership,
) -> None:
    """A run started before a revocation does not act after it."""
    HAT_CALLS.clear()
    member = await sync_to_async(lambda: branch_membership.user)()
    workflow_id = f"{tenant.slug}:workflows:hat:revoked"
    acted: str | None = None
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with worker_with_the_pair(client):
            await start_workflow(
                workflow="RevokedHatWorkflow",
                arg="hat",
                tenant=tenant,
                user=member,
                org=branch,
                client=client,
                task_queue=TASK_QUEUE,
                id=workflow_id,
            )
            handle = client.get_workflow_handle(workflow_id, result_type=str)
            await _until_acted(["hat:first"])

            await sync_to_async(_revoke)(tenant, owner, root_org, branch_membership)
            await handle.signal("proceed")

            with contextlib.suppress(WorkflowFailureError):
                acted = await asyncio.wait_for(handle.result(), timeout=120)

    assert HAT_CALLS == ["hat:first"], (
        f"the run acted under a revoked hat: calls {HAT_CALLS!r}, answered {acted!r}"
    )
    assert acted is None, f"the run completed under a revoked hat, answering {acted!r}"
    run = await WorkflowRun.objects.aget(workflow_id=workflow_id)
    assert run.status == WorkflowRun.Status.FAILED
    assert ORG_HEADER in run.error
    assert branch.slug in run.error
    assert HAT_REVOKED in run.error


def test_the_refusal_is_final_and_says_whose_hat(
    tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    branch_membership: Membership,
) -> None:
    """Non-retryable: a hat the person no longer holds is not coming back."""
    _revoke(tenant, owner, root_org, branch_membership)
    tokens = set_principal(
        tenant_id=str(tenant.pk),
        user_id=str(branch_membership.user_id),
        org_id=str(branch.pk),
    )
    try:
        with pytest.raises(ApplicationError) as refused:
            workflow_context()
    finally:
        reset_principal(tokens)

    assert refused.value.type == HAT_REVOKED
    assert refused.value.non_retryable is True
    said = str(refused.value)
    assert ORG_HEADER in said
    assert tenant.slug in said
    assert branch.slug in said
    assert "no longer holds a role over it" in said


def test_a_hat_the_person_holds_is_answered(
    tenant: Tenant, branch: Organization, branch_membership: Membership
) -> None:
    """The live half: the same person, the same hat, not yet revoked."""
    tokens = set_principal(
        tenant_id=str(tenant.pk),
        user_id=str(branch_membership.user_id),
        org_id=str(branch.pk),
    )
    try:
        restored, user_id, org = workflow_context()
    finally:
        reset_principal(tokens)

    assert restored == tenant
    assert user_id == str(branch_membership.user_id)
    assert org == branch


def test_a_hat_in_another_tenant_is_refused(
    tenant: Tenant, other_root_org: Organization, branch_membership: Membership
) -> None:
    """The belt: a hat id from somebody else's tree is no hat here."""
    tokens = set_principal(
        tenant_id=str(tenant.pk),
        user_id=str(branch_membership.user_id),
        org_id=str(other_root_org.pk),
    )
    try:
        with pytest.raises(ApplicationError) as refused:
            workflow_context()
    finally:
        reset_principal(tokens)

    assert refused.value.type == HAT_REVOKED
    assert refused.value.non_retryable is True


def test_a_system_run_under_a_hat_proceeds(tenant: Tenant, branch: Organization) -> None:
    """No user, so no membership to revoke: the hat only has to exist in the tenant."""
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=None, org_id=str(branch.pk))
    try:
        restored, user_id, org = workflow_context()
    finally:
        reset_principal(tokens)

    assert restored == tenant
    assert user_id is None
    assert org == branch


# The revalidation's price, measured: the tenant and the hat in one read, the
# person, and `resolve_org`'s two (the memberships, the hat by slug).
REVALIDATION_QUERIES = 4


def test_the_revalidation_costs_four_queries_under_a_branch_hat(
    tenant: Tenant,
    branch: Organization,
    branch_membership: Membership,
    django_assert_num_queries: Any,
) -> None:
    tokens = set_principal(
        tenant_id=str(tenant.pk),
        user_id=str(branch_membership.user_id),
        org_id=str(branch.pk),
    )
    try:
        with django_assert_num_queries(REVALIDATION_QUERIES):
            workflow_context()
    finally:
        reset_principal(tokens)


def test_a_flat_product_at_the_root_pays_the_same(
    tenant: Tenant, owner: User, root_org: Organization, django_assert_num_queries: Any
) -> None:
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=str(owner.pk), org_id=str(root_org.pk))
    try:
        with django_assert_num_queries(REVALIDATION_QUERIES):
            _tenant, _user_id, org = workflow_context()
    finally:
        reset_principal(tokens)

    assert org == root_org


# --- A run with a person and no hat is revalidated too ------------------------
#
# No hat means no `resolve_org` question, but the person still has to be
# somebody who can act in this tenant: active, and holding at least one
# membership in it. A person whose last role here was revoked is refused the
# same way a revoked hat is.

HATLESS_QUERIES = 2


def test_a_hatless_run_whose_person_left_the_tenant_is_refused(
    tenant: Tenant, owner: User, root_org: Organization, branch_membership: Membership
) -> None:
    _revoke(tenant, owner, root_org, branch_membership)
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=str(branch_membership.user_id))
    try:
        with pytest.raises(ApplicationError) as refused:
            workflow_context()
    finally:
        reset_principal(tokens)

    assert refused.value.type == HAT_REVOKED
    assert refused.value.non_retryable is True
    assert tenant.slug in str(refused.value)


def test_a_hatless_run_whose_person_was_deactivated_is_refused(
    tenant: Tenant, branch_membership: Membership
) -> None:
    User.objects.filter(pk=branch_membership.user_id).update(is_active=False)
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=str(branch_membership.user_id))
    try:
        with pytest.raises(ApplicationError) as refused:
            workflow_context()
    finally:
        reset_principal(tokens)

    assert refused.value.type == HAT_REVOKED


def test_a_hatless_run_whose_person_still_belongs_is_answered(
    tenant: Tenant, branch_membership: Membership, django_assert_num_queries: Any
) -> None:
    """The live half, and its price: the tenant, then one membership read."""
    tokens = set_principal(tenant_id=str(tenant.pk), user_id=str(branch_membership.user_id))
    try:
        with django_assert_num_queries(HATLESS_QUERIES):
            restored, user_id, org = workflow_context()
    finally:
        reset_principal(tokens)

    assert restored == tenant
    assert user_id == str(branch_membership.user_id)
    assert org is None


# --- the chain: one per run, minted at the workflow door when nobody handed one ---


@pytest.mark.asyncio
async def test_a_headerless_run_is_one_chain_across_its_activities(tenant: Tenant) -> None:
    """A Schedule's run carries no correlation header: the door mints ONE, for the run.

    Minted per activity instead, two activities of one run would be two
    unrelated chains, and nothing could join the work a scheduled run did.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with worker_with_the_pair(client):
            # Started straight through the client with no principal bound: the
            # headers carry no tenant and no chain, exactly as a Schedule's do.
            handle = await client.start_workflow(
                "TwoStepChainWorkflow",
                "scheduled",
                id=f"{tenant.slug}:workflows:chain:headerless",
                task_queue=TASK_QUEUE,
                result_type=TwoChains,
            )
            seen: TwoChains = await handle.result()
            run_id = (await handle.describe()).run_id

    assert seen.first.correlation_id != ""
    assert seen.first.correlation_id == seen.second.correlation_id
    # Deterministic: a function of the run's identity alone, so a replay of the
    # same run mints the same chain (house rule 9).
    expected = uuid.uuid5(RUN_CHAIN_NAMESPACE, f"{handle.id}/{run_id}").hex
    assert seen.first.correlation_id == expected


@pytest.mark.asyncio
async def test_a_run_started_in_a_chain_carries_that_chain_to_its_service_writes(
    tenant: Tenant, owner: User, root_org: Organization
) -> None:
    """The header's chain, not a fresh one, is what a service inside an activity records.

    `mark_run_finished` calls `finish_run`, a `@service`, so its audit row is a
    service write made inside an activity — read back off that row.
    """
    chain = observability.new_correlation_id()
    observability.bind(correlation_id=chain)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with worker_with_the_pair(client):
            run = await start_workflow(
                workflow="EchoWorkflow",
                arg="hello",
                tenant=tenant,
                user=owner,
                org=root_org,
                client=client,
                task_queue=TASK_QUEUE,
                id=f"{tenant.slug}:workflows:echo:chained",
            )
            await client.get_workflow_handle(run.workflow_id).result()

    written = await AuditEntry.objects.for_tenant(tenant).aget(action="workflows.finish_run")
    assert written.correlation_id == chain
