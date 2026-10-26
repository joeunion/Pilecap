"""`move_organization` asked twice: same or different parent, against a live or a completed run.

Once completed, a different parent supersedes (ADR workflows-5); the same one is `conflict` (-4).
`create_tenant` refuses the slug `platform`, reserved by ADR workflows-3.
Paths are asserted relationally; the segment encoding is the model's.
# does-not-cover: true concurrency — the race is `apps/workflows/tests/test_services.py`'s.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.db import connections, transaction
from django.test import RequestFactory
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment

from apps.core.actor import Actor, system_actor
from apps.core.asyncdb import run_db
from apps.core.exceptions import Conflict, Invalid
from apps.core.models import PATH_SEPARATOR, Organization, Tenant
from apps.core.services import (
    RESERVED_TENANT_SLUGS,
    create_organization,
    create_tenant,
    move_organization,
)
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker, task_queue
from apps.workflows.models import WorkflowRun
from apps.workflows.services import PLATFORM_SEGMENT, workflow_id

# `transaction=True`: `move_organization` starts its run on `transaction.
# on_commit`, and a test that never commits never finds out what the second ask
# is answered with.
pytestmark = pytest.mark.django_db(transaction=True)


@dataclass(frozen=True)
class Tree:
    """One tenant, two possible destinations, and a subtree to move."""

    tenant: Tenant
    actor: Actor
    hq: Organization
    p1: Organization
    p2: Organization
    node: Organization
    child: Organization

    @property
    def run_id_wanted(self) -> str:
        """The id `move_organization` builds — keyed on the moving node.

        Stated here rather than read off the row, because *that* is the
        property the whole matrix rests on: every ask about this node lands on
        one key, which is what makes a second ask answerable at all.
        """
        return workflow_id(
            tenant=self.tenant, app="core", noun="organization", key=str(self.node.pk)
        )


@pytest.fixture
def tree(tenant: Tenant, owner_actor: Actor, root_org: Organization) -> Tree:
    p1 = create_organization(
        tenant=tenant, parent=root_org, name="Parent One", slug="parent-one", actor=owner_actor
    )
    p2 = create_organization(
        tenant=tenant, parent=root_org, name="Parent Two", slug="parent-two", actor=owner_actor
    )
    node = create_organization(
        tenant=tenant, parent=root_org, name="The Node", slug="the-node", actor=owner_actor
    )
    child = create_organization(
        tenant=tenant, parent=node, name="Below It", slug="below-it", actor=owner_actor
    )
    return Tree(tenant=tenant, actor=owner_actor, hq=root_org, p1=p1, p2=p2, node=node, child=child)


def _order(tree: Tree, new_parent_pk: Any) -> None:
    """Ask for the move, and commit — which is what starts the run.

    Both rows are **re-read** first, because that is what a door does: it
    resolves the node and the destination from the request, then calls the
    service. Handing the service a row that has already moved would be a test
    holding state no caller holds.

    `connections.close_all()` because this runs in a worker thread off the
    event loop, and the connection it opened is nobody else's to reuse.
    """
    try:
        with transaction.atomic():
            rows = Organization.objects.for_tenant(tree.tenant)
            move_organization(
                tenant=tree.tenant,
                organization=rows.get(pk=tree.node.pk),
                new_parent=rows.get(pk=new_parent_pk),
                actor=tree.actor,
            )
    finally:
        connections.close_all()


async def ask(tree: Tree, new_parent: Organization) -> None:
    """One caller-shaped ask, from an async test."""
    await sync_to_async(_order, thread_sensitive=False)(tree, new_parent.pk)


def _point_the_client_at(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> None:
    """What the on-commit hook dials. The test's server, never a dev server."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> Client:
        return attach_interceptors(await Client.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)


async def _reread(tree: Tree, organization: Organization) -> Organization:
    fresh: Organization = await run_db(
        Organization.objects.for_tenant(tree.tenant).get, pk=organization.pk
    )
    return fresh


async def _rows_for(tree: Tree) -> int:
    count: int = await run_db(
        WorkflowRun.objects.for_tenant(tree.tenant).filter(workflow_id=tree.run_id_wanted).count
    )
    return count


async def _ledger_row(tree: Tree) -> WorkflowRun:
    row: WorkflowRun = await run_db(
        WorkflowRun.objects.for_tenant(tree.tenant).get, workflow_id=tree.run_id_wanted
    )
    return row


# --- the same move while live: the retry is still free ----------------------


@pytest.mark.asyncio
async def test_asking_for_the_same_move_twice_while_it_runs_is_one_run(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repeat of a live move answers the run already there: one row, one start event.

    No worker, so the execution stays live — the state the second ask must be answered in.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        _point_the_client_at(env, monkeypatch)

        await ask(tree, tree.p1)
        first = await env.client.get_workflow_handle(tree.run_id_wanted).describe()
        await ask(tree, tree.p1)

        handle = env.client.get_workflow_handle(tree.run_id_wanted)
        again = await handle.describe()
        assert again.status is WorkflowExecutionStatus.RUNNING
        assert again.run_id == first.run_id
        starts = [
            event
            async for event in handle.fetch_history_events()
            if event.HasField("workflow_execution_started_event_attributes")
        ]
        assert len(starts) == 1

        assert await _rows_for(tree) == 1
        row = await _ledger_row(tree)
        assert row.status == WorkflowRun.Status.RUNNING
        assert row.run_id == again.run_id


# --- a different move while live: a second destination is a second job ------


@pytest.mark.asyncio
async def test_a_different_parent_while_the_move_is_live_is_an_honest_conflict(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second destination while the first move runs is `conflict`, with nothing started or moved.

    The wire half goes through `config.api`'s own exception mapper: the body a caller receives.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        _point_the_client_at(env, monkeypatch)

        await ask(tree, tree.p1)
        with pytest.raises(Conflict) as refused:
            await ask(tree, tree.p2)

        # The refusal says which half disagreed: same run, different work.
        assert "different input" in str(refused.value)

        # Nothing was started for the second intent, and nothing moved.
        assert await _rows_for(tree) == 1
        node = await _reread(tree, tree.node)
        assert node.parent_id == tree.hq.pk
        starts = [
            event
            async for event in env.client.get_workflow_handle(
                tree.run_id_wanted
            ).fetch_history_events()
            if event.HasField("workflow_execution_started_event_attributes")
        ]
        assert len(starts) == 1

        def on_the_wire() -> tuple[int, dict[str, Any]]:
            request = RequestFactory().post("/api/v1/organizations/")
            from config.api import api

            response = api.on_exception(request, refused.value)
            body: dict[str, Any] = json.loads(response.content)
            return response.status_code, body

        status, body = await sync_to_async(on_the_wire, thread_sensitive=False)()

    assert status == 409
    assert body["code"] == "conflict"
    assert body["remedies"]
    assert all({"label", "destination"} <= set(remedy) for remedy in body["remedies"])


# --- a completed move: what a finished move allows --------------------------


@pytest.mark.asyncio
async def test_a_completed_move_supersedes_but_the_same_move_does_not(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The quadrant that needs verifying rather than assuming.

    A worker runs here, so the first move really completes and really closes
    its row (ADR workflows-5) — which is the state that matters here:
    a finished row under a node-keyed id is a node that can never
    move again unless something supersedes.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        _point_the_client_at(env, monkeypatch)
        async with build_worker(attach_interceptors(env.client), queue=task_queue()):
            await ask(tree, tree.p1)
            await env.client.get_workflow_handle(tree.run_id_wanted, result_type=str).result()

            landed = await _ledger_row(tree)
            assert landed.status == WorkflowRun.Status.COMPLETED
            assert landed.finished_at is not None
            first_run_id = landed.run_id

            node = await _reread(tree, tree.node)
            parent_one = await _reread(tree, tree.p1)
            child = await _reread(tree, tree.child)
            assert node.parent_id == tree.p1.pk
            assert node.path.startswith(parent_one.path + PATH_SEPARATOR)
            assert child.path.startswith(node.path + PATH_SEPARATOR)

            # The fourth quadrant: the same move, now that it is done.
            with pytest.raises(Conflict) as spent:
                await ask(tree, tree.p1)
            assert "a new job, not a repeat of that one" in str(spent.value)
            unchanged = await _ledger_row(tree)
            assert unchanged.status == WorkflowRun.Status.COMPLETED
            assert unchanged.run_id == first_run_id

            # A different destination re-opens the key and runs again.
            await ask(tree, tree.p2)
            second_path: str = await env.client.get_workflow_handle(
                tree.run_id_wanted, result_type=str
            ).result()

            reopened = await _ledger_row(tree)
            assert reopened.status == WorkflowRun.Status.COMPLETED
            assert reopened.run_id != first_run_id

            moved = await _reread(tree, tree.node)
            parent_two = await _reread(tree, tree.p2)
            below = await _reread(tree, tree.child)

    # One row throughout — superseded, never duplicated — and the subtree is
    # under the second parent, read off the rows rather than guessed.
    assert await _rows_for(tree) == 1
    assert moved.parent_id == tree.p2.pk
    assert moved.path == second_path
    assert moved.path.startswith(parent_two.path + PATH_SEPARATOR)
    assert below.path.startswith(moved.path + PATH_SEPARATOR)
    assert below.parent_id == moved.pk


def test_the_docstring_states_the_matrix_it_now_has() -> None:
    """`move_organization`'s contract says one intent at a time, not "cannot be in flight"."""
    # Collapsed, because the sentence is wrapped and asterisked in the source
    # and what is being pinned is the claim, not the line breaks.
    doc = " ".join((inspect.getdoc(move_organization) or "").split())
    assert "cannot be in flight at once" not in doc
    assert "one intent at a time" in doc.replace("*", "").lower()
    assert "supersedes" in doc
    assert "Conflict" in doc


# --- the reserved slug ------------------------------------------------------


def test_creating_a_tenant_called_platform_is_refused() -> None:
    """The segment ADR workflows-3 reserved cannot be minted."""
    with pytest.raises(Invalid) as refused:
        create_tenant(name="Platform", slug=PLATFORM_SEGMENT, actor=system_actor())
    assert "slug" in refused.value.errors
    assert PLATFORM_SEGMENT in refused.value.errors["slug"][0]
    assert not Tenant.objects.filter(slug=PLATFORM_SEGMENT).exists()


def test_the_refusal_survives_the_shapes_a_slug_arrives_in() -> None:
    """Whitespace and case are normalised *before* the fence, not after it."""
    for typed in ("  platform  ", "PLATFORM", "Platform"):
        with pytest.raises(Invalid):
            create_tenant(name="Platform", slug=typed, actor=system_actor())
    assert not Tenant.objects.filter(slug=PLATFORM_SEGMENT).exists()


def test_a_slug_that_merely_contains_the_word_is_still_a_tenant() -> None:
    """The fence is the exact segment, not a substring — `platform-co` is fine."""
    made = create_tenant(name="Platform Co", slug="platform-co", actor=system_actor())
    assert made.slug == "platform-co"


def test_no_tenant_holds_a_reserved_slug(tenant: Tenant) -> None:
    """The existing-population half of the reserved-slug fence: nothing already minted one.

    A fence at creation only closes the question if the population it protects
    is empty, and the fixtures are the only tenants this suite ever makes.
    """
    assert not Tenant.objects.filter(slug__in=RESERVED_TENANT_SLUGS).exists()


def test_the_reserved_slug_is_the_one_the_run_ledger_reserved() -> None:
    """The two halves of a value `core` may not import are pinned together.

    `core` cannot import `apps.workflows` — the dependency runs the other way —
    so the word is written twice. A test may cross that line (rule 7 exempts
    tests by design), and crossing it here is what makes the repeat safe.
    """
    assert PLATFORM_SEGMENT in RESERVED_TENANT_SLUGS
