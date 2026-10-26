"""The org tree's one human door: the admin move action.

ADR core-10. Before this, `move_organization` had **no door at all** — not a
REST route, not an MCP tool, and not an admin path: `OrganizationAdmin.
service_for` answered `rename_organization` for an update and `None` for
everything else, and `parent` was read-only on the change form on purpose, so
there was no request a person could make that reached the service. Every move
was hand-driven through a shell, twice, and the three-move grammar this door
was built for had never once been driven by a user-initiated write.

That gap is therefore an **absence**, and it is pinned rather than
remembered: `test_no_form_field_moves_a_node` holds the fence that made the
absence deliberate (the change form still offers nothing that re-parents), and
the same fence is what makes the action the *only* path — which is the whole of
ADR core-10's "the action is the door; the field is not".

What each test answers, by the plan's criteria:

* The action exists, its target choices are `.for_tenant`-scoped,
  the write path is the service, the success line names the started run, and
  the class is still a `ServiceModelAdmin` (rules 10, 21).
* A hat covering one end only is refused *as a message*, in the
  200 family, with nothing written and an `AuditEntry` at `door=admin,
  outcome=error`; the read-only `parent` fence is intact.
* The four-quadrant grammar, driven through the door: a second
  destination while the first move is live is a `conflict`, and once the move
  has finished the same action re-parents the subtree for real.

Later, and here because it is the same fence on the same form —
`slug` and `tenant` were rendered as editable controls that
`call_service` then dropped on the floor. The test named for it holds those two
beside `parent`, using this file's fixtures and its one changelist URL.

DOES NOT COVER — declared: message *wording* (as `test_admin_door.py` declares
for the same composer — what is pinned is the `code` reaching the screen); the
tenant-admin self-service shape, which ADR core-10 leaves unbuilt with its
trigger named; and true concurrency between two staff members clicking Move on
one node at once, which is arbitrated by the run ledger's per-tenant unique
constraint and proved at that tier in `apps/workflows/tests/test_services.py`.
"""

from __future__ import annotations

from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.contrib.admin import helpers
from django.contrib.messages import get_messages
from django.db import connections, transaction
from django.test import Client
from temporalio.client import Client as TemporalClient
from temporalio.testing import WorkflowEnvironment

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, system_actor
from apps.core.admin import OrganizationAdmin, ServiceModelAdmin
from apps.core.audit import AuditEntry
from apps.core.models import PATH_SEPARATOR, Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization
from apps.workflows import client as client_module
from apps.workflows.client import attach_interceptors, build_worker, task_queue
from apps.workflows.models import WorkflowRun
from apps.workflows.services import workflow_id

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret
CHANGELIST = "/admin/core/organization/"
ACTION = "move_to_new_parent"


# --- The tree every test in this file moves things around in -----------------


@pytest.fixture
def branch_a(tenant: Tenant, owner_actor: Actor, root_org: Organization) -> Organization:
    return create_organization(
        tenant=tenant, parent=root_org, name="Branch A", slug="branch-a", actor=owner_actor
    )


@pytest.fixture
def branch_b(tenant: Tenant, owner_actor: Actor, root_org: Organization) -> Organization:
    return create_organization(
        tenant=tenant, parent=root_org, name="Branch B", slug="branch-b", actor=owner_actor
    )


@pytest.fixture
def node(tenant: Tenant, owner_actor: Actor, branch_a: Organization) -> Organization:
    """The subtree that moves: under Branch A, with a child of its own.

    A child, because the claim the criteria make is about a *subtree* landing
    somewhere — a leaf moving proves the row and not the rewrite.
    """
    return create_organization(
        tenant=tenant, parent=branch_a, name="The Node", slug="the-node", actor=owner_actor
    )


@pytest.fixture
def child(tenant: Tenant, owner_actor: Actor, node: Organization) -> Organization:
    return create_organization(
        tenant=tenant, parent=node, name="Below It", slug="below-it", actor=owner_actor
    )


@pytest.fixture
def staff_owner(tenant: Tenant, owner: User, root_org: Organization) -> User:
    """A support human whose hat covers the whole tenant — both ends of any move.

    `owner` is asked for first so this user is not the tenant's *first*
    membership; the role is named out loud for the reason `apps/conftest.py`
    gives about every role in it.
    """
    user = create_user(email="staff-owner@example.com", password=PASSWORD, is_staff=True)
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def staff_branch_admin(tenant: Tenant, owner: User, branch_a: Organization) -> User:
    """A support human who administers Branch A **and nothing else**.

    This is the actor for the one-ended-hat refusal: their hat covers the end
    the node is coming *from* and not the end it is going *to*, which is the
    half of `move_organization`'s authorization that a single-ended check would miss.
    """
    user = create_user(email="branch-admin@example.com", password=PASSWORD, is_staff=True)
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    add_membership(
        user=user,
        tenant=tenant,
        organization=branch_a,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return user


# --- Driving the door --------------------------------------------------------
#
# Two POSTs, because that is what a person does: the changelist's action
# dropdown (which carries `index`, and lands on Django's "action with
# confirmation" branch by way of the response this action returns), then the
# intermediate page's own form (which carries `_move` and the destination).


def open_move_page(api: Client, node: Organization) -> Any:
    return api.post(
        CHANGELIST,
        data={
            "action": ACTION,
            "index": "0",
            helpers.ACTION_CHECKBOX_NAME: [str(node.pk)],
        },
    )


def submit_move(
    api: Client, node: Organization, new_parent: Organization, follow: bool = True
) -> Any:
    return api.post(
        CHANGELIST,
        data={
            "action": ACTION,
            "_move": "1",
            "new_parent": str(new_parent.pk),
            helpers.ACTION_CHECKBOX_NAME: [str(node.pk)],
        },
        follow=follow,
    )


def messages_on(response: Any) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


# --- The action exists, and it rides the service -----------------------------


def test_the_action_is_offered_on_the_changelist(api: Client, staff_owner: User) -> None:
    """The green half of the earlier red: there is now a way to ask.

    Read off the rendered changelist rather than off `get_actions`, because the
    claim is that a support human can reach it — an action registered but
    filtered out by `has_change_permission` would pass the dictionary check and
    fail this one.
    """
    api.force_login(staff_owner)

    page = api.get(CHANGELIST).content.decode()

    assert ACTION in page
    assert "Move to a new parent" in page


def test_the_target_choices_hold_no_other_tenants_organizations(
    api: Client,
    staff_owner: User,
    node: Organization,
    branch_b: Organization,
    other_root_org: Organization,
) -> None:
    """The picker is `.for_tenant`-scoped, and the node is not in it.

    `other_root_org` is Globex's root, planted by the fixture through
    `create_tenant`. A destination list that offered it would be offering to
    move a subtree into another tenant — which `_refuse_impossible_move` calls
    an export and refuses, but a door that *asks* the question has already
    leaked the other tenant's tree onto the page.
    """
    api.force_login(staff_owner)

    response = open_move_page(api, node)

    assert response.status_code == 200
    choices = list(response.context["form"].fields["new_parent"].queryset)
    assert other_root_org not in choices
    assert branch_b in choices
    # The row being moved is not a candidate parent for itself.
    assert node not in choices
    assert {organization.tenant_id for organization in choices} == {node.tenant_id}


def test_a_hat_over_both_ends_moves_the_node_through_the_action(
    api: Client,
    staff_owner: User,
    tenant: Tenant,
    node: Organization,
    branch_b: Organization,
) -> None:
    """The move a support human actually makes, end to end at this tier.

    What is asserted is that the **service** ran: `move_organization` is the
    only thing in the product that writes `core.move_organization` to the audit
    trail, so a row at `door=admin` with `outcome=success` is the write path,
    read off the trail rather than off a mock. The durable run it started is on
    the ledger for the same reason — the action's own code has no `save()` in
    it and could not have produced either.
    """
    api.force_login(staff_owner)

    response = submit_move(api, node, branch_b)

    assert response.status_code == 200, response.content
    assert response.redirect_chain, "the action did not hand the request back to the changelist"

    entry = AuditEntry.objects.for_tenant(tenant).get(action="core.move_organization")
    assert entry.door == "admin"
    assert entry.outcome == AuditEntry.Outcome.OK
    assert entry.actor_user_id == staff_owner.pk

    run = WorkflowRun.objects.for_tenant(tenant).get(
        workflow_id=workflow_id(tenant=tenant, app="core", noun="organization", key=str(node.pk))
    )
    assert run.status == WorkflowRun.Status.RUNNING


def test_the_success_message_names_the_run_that_was_started(
    api: Client,
    staff_owner: User,
    tenant: Tenant,
    node: Organization,
    branch_b: Organization,
) -> None:
    """And the drift pin `OrganizationAdmin.move_run_id` asks for.

    `core` may not import `apps.workflows`, so the admin builds the id through
    the bridge from the same four parts the service builds it from — a second
    statement of one key. A test may cross that app line (rule 7 exempts tests
    by design), and crossing it here is what makes the repeat safe: the message
    is compared against `apps.workflows.services.workflow_id` itself, so an id
    that names no run fails rather than printing.
    """
    api.force_login(staff_owner)

    response = submit_move(api, node, branch_b)

    wanted = workflow_id(tenant=tenant, app="core", noun="organization", key=str(node.pk))
    rendered = messages_on(response)
    assert any(wanted in message for message in rendered), rendered
    # The id in the message is the id the ledger actually holds, not merely a
    # well-formed string.
    assert WorkflowRun.objects.for_tenant(tenant).filter(workflow_id=wanted).exists()


def test_the_organization_admin_is_still_a_service_model_admin() -> None:
    """Rule 21, said out loud where the rung that added a write path can see it.

    An action is the easiest place in Django to grow a second door with
    different rules — `queryset.update()` in a loop is four keystrokes — so the
    base class that maps refusals, binds the actor and scopes the read stays
    named here.
    """
    assert issubclass(OrganizationAdmin, ServiceModelAdmin)


def test_selecting_more_than_one_organization_is_refused(
    api: Client,
    staff_owner: User,
    node: Organization,
    branch_a: Organization,
    branch_b: Organization,
) -> None:
    """The door's own shape: one destination is one question.

    Not a domain rule and not restated from one — `move_organization` knows
    nothing about selections. The intermediate page asks for a single parent,
    and two nodes do not share one answer.
    """
    api.force_login(staff_owner)

    response = api.post(
        CHANGELIST,
        data={
            "action": ACTION,
            "index": "0",
            helpers.ACTION_CHECKBOX_NAME: [str(node.pk), str(branch_a.pk)],
        },
        follow=True,
    )

    assert response.status_code == 200
    rendered = messages_on(response)
    assert any("exactly one" in message for message in rendered), rendered
    node.refresh_from_db()
    assert node.parent_id == branch_a.pk


# --- The wall holds through the door ------------------------------------------


def test_a_hat_over_one_end_only_is_refused_as_a_message(
    api: Client,
    staff_branch_admin: User,
    tenant: Tenant,
    node: Organization,
    branch_a: Organization,
    branch_b: Organization,
) -> None:
    """Admin over where it comes from, nothing over where it is going.

    `move_organization` authorizes **both** ends because a move is a grant and
    a revocation at once, and this actor holds only one of them. The refusal
    arrives the way every other refusal on this door arrives — a
    message on a page in the 200 family — and nothing moved.
    """
    api.force_login(staff_branch_admin)

    response = submit_move(api, node, branch_b)

    assert response.status_code == 200, response.content
    rendered = messages_on(response)
    assert any("forbidden" in message for message in rendered), rendered
    # The sentence the app declared, not the action key. Since 2026-08-24 the
    # key stays in the audit row and in the log, where the reader is a
    # maintainer, and never reaches whoever was refused.
    assert any("You may not move that organization." in message for message in rendered), rendered
    assert not any("organization.move" in message for message in rendered), rendered

    node.refresh_from_db()
    assert node.parent_id == branch_a.pk
    assert not WorkflowRun.objects.for_tenant(tenant).exists()


def test_the_refused_move_is_audited_at_the_admin_door(
    api: Client,
    staff_branch_admin: User,
    tenant: Tenant,
    node: Organization,
    branch_b: Organization,
) -> None:
    """The refusal is in the trail, not only on the screen.

    The half the earlier refusal is actually about. Returning normally rather than letting the
    `Forbidden` climb out of the view is what lets the `AuditEntry` the
    `@service` decorator wrote survive the request's rollback.
    """
    api.force_login(staff_branch_admin)
    AuditEntry.objects.all().delete()

    submit_move(api, node, branch_b)

    entry = AuditEntry.objects.for_tenant(tenant).get(action="core.move_organization")
    assert entry.door == "admin"
    assert entry.outcome == AuditEntry.Outcome.ERROR
    assert entry.error_code == "forbidden"
    assert entry.actor_user_id == staff_branch_admin.pk


def test_no_form_field_moves_a_node(
    api: Client, staff_owner: User, node: Organization, branch_b: Organization
) -> None:
    """And the earlier fence held in place: the fence the action did not open.

    The original absence — `parent` read-only, so no form write can re-parent —
    is the reason the action had to exist, and it would be self-defeating for
    the action to have relaxed it. So both halves are pinned together: the
    change form offers no editable `parent`, **and** a POST that names one
    anyway changes nothing. A move is a decision with a durable run behind it,
    never a dropdown somebody nudged on the way past.
    """
    api.force_login(staff_owner)

    page = api.get(f"{CHANGELIST}{node.pk}/change/").content.decode()
    assert 'name="parent"' not in page

    api.post(
        f"{CHANGELIST}{node.pk}/change/",
        data={"name": node.name, "slug": node.slug, "parent": str(branch_b.pk)},
    )

    node.refresh_from_db()
    assert node.parent_id != branch_b.pk
    assert "parent" in OrganizationAdmin.readonly_fields


def test_the_change_form_offers_no_slug_or_tenant_it_would_then_drop(
    api: Client,
    staff_owner: User,
    node: Organization,
    other_tenant: Tenant,
) -> None:
    """The same fence, over the two fields the form used to offer anyway.

    `OrganizationAdmin.call_service` hands `rename_organization` exactly one
    field — `name` — so an editable `slug` or `tenant` control was a write the
    screen accepted and the service never made: Save, a green banner, and a row
    that did not change. Silent, and worse than a refusal, because the operator
    leaves believing it landed.

    Both halves, exactly as `test_no_form_field_moves_a_node` holds them for
    `parent`: **the rendered form offers neither as editable**, and **a POST
    naming both changes neither**. The `name` assertion is what stops this
    passing vacuously — the request really was accepted and the service really
    did run; it just did the one thing it is wired to do.
    """
    api.force_login(staff_owner)

    page = api.get(f"{CHANGELIST}{node.pk}/change/").content.decode()
    assert 'name="slug"' not in page
    assert 'name="tenant"' not in page

    was_slug, was_tenant = node.slug, node.tenant_id
    api.post(
        f"{CHANGELIST}{node.pk}/change/",
        data={
            "name": "Renamed Through The Door",
            "slug": "smuggled-slug",
            "tenant": str(other_tenant.pk),
        },
    )

    node.refresh_from_db()
    assert node.name == "Renamed Through The Door", "the rename the service DOES do"
    assert node.slug == was_slug
    assert node.tenant_id == was_tenant
    assert "slug" in OrganizationAdmin.readonly_fields
    assert "tenant" in OrganizationAdmin.readonly_fields


# --- The grammar, driven by a user-shaped hand ---------------------------------


def test_a_second_destination_while_the_move_is_live_is_a_conflict(
    api: Client,
    staff_owner: User,
    tenant: Tenant,
    node: Organization,
    branch_a: Organization,
    branch_b: Organization,
    root_org: Organization,
) -> None:
    """First quadrant through the door: two destinations, one subtree.

    This is the worst case, with a person's hand on it. The digest inside
    `record_run` refuses the second intent synchronously — no Temporal server
    is needed to be told the key is live — and what this grammar asks is what the
    *screen* then says. It used to answer with a 500 before the refusal was added;
    before that there was no screen at all.
    """
    api.force_login(staff_owner)
    submit_move(api, node, branch_b)

    response = submit_move(api, node, root_org)

    assert response.status_code == 200, response.content
    rendered = messages_on(response)
    assert any("conflict" in message for message in rendered), rendered

    # The first intent stands, alone, and nothing moved for the second.
    assert WorkflowRun.objects.for_tenant(tenant).count() == 1
    node.refresh_from_db()
    assert node.parent_id == branch_a.pk


def test_the_same_move_asked_twice_while_live_is_not_a_conflict(
    api: Client,
    staff_owner: User,
    tenant: Tenant,
    node: Organization,
    branch_b: Organization,
) -> None:
    """The retry quadrant: a person who clicked twice pays nothing.

    The counterpart to the test above, and the reason that one is not simply
    "a second click is refused": the grammar distinguishes a repeated *intent*
    from a competing one, and a door that could not tell them apart would make
    double-clicking a support tool an incident.
    """
    api.force_login(staff_owner)
    submit_move(api, node, branch_b)

    response = submit_move(api, node, branch_b)

    rendered = messages_on(response)
    assert not any("conflict" in message for message in rendered), rendered
    assert WorkflowRun.objects.for_tenant(tenant).count() == 1


# --- The grammar's second half: a finished move, and the action again ----------


def _point_the_client_at(env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch) -> None:
    """What the on-commit hook dials. The test's server, never a dev server."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> TemporalClient:
        return attach_interceptors(await TemporalClient.connect(target, namespace=namespace))

    monkeypatch.setattr(client_module, "get_client", connect)


def _drive(user_pk: Any, node_pk: Any, parent_pk: Any) -> list[str]:
    """One click of the action, from a worker thread, in its own transaction.

    Shaped like `test_move_matrix._order` and for the same two reasons: the run
    starts on `transaction.on_commit`, so a test that never commits never finds
    out what the next ask is answered with; and the connection this thread
    opened is nobody else's to reuse.
    """
    try:
        client = Client()
        with transaction.atomic():
            client.force_login(User.objects.get(pk=user_pk))
        node = Organization.objects.get(pk=node_pk)
        parent = Organization.objects.get(pk=parent_pk)
        response = submit_move(client, node, parent)
        return messages_on(response)
    finally:
        connections.close_all()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_the_action_after_a_completed_move_lands_the_subtree(
    staff_owner: User,
    tenant: Tenant,
    node: Organization,
    child: Organization,
    branch_a: Organization,
    branch_b: Organization,
    root_org: Organization,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The grammar's second half: the supersede quadrant, clicked rather than shelled.

    A worker runs here, so the first move really completes and really closes
    its row (ADR workflows-5) — which is the state that makes this interesting:
    a node whose deterministic id had fossilised on completion could never be
    moved a second time. The subtree's landing is read off the rows relationally
    (a child's path starts with its parent's), never against a guessed literal,
    because the segment encoding is the model's business.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        _point_the_client_at(env, monkeypatch)
        async with build_worker(attach_interceptors(env.client), queue=task_queue()):
            wanted = await sync_to_async(workflow_id, thread_sensitive=False)(
                tenant=tenant, app="core", noun="organization", key=str(node.pk)
            )

            first = await sync_to_async(_drive, thread_sensitive=False)(
                staff_owner.pk, node.pk, branch_b.pk
            )
            assert not any("conflict" in message for message in first), first
            await env.client.get_workflow_handle(wanted, result_type=str).result()

            # The click that used to be impossible: the key is spent, and a new
            # destination re-opens it.
            second = await sync_to_async(_drive, thread_sensitive=False)(
                staff_owner.pk, node.pk, root_org.pk
            )
            assert not any("conflict" in message for message in second), second
            await env.client.get_workflow_handle(wanted, result_type=str).result()

            moved, below, landed_under = await sync_to_async(_read_tree, thread_sensitive=False)(
                node.pk, child.pk, root_org.pk
            )

    assert moved.parent_id == root_org.pk
    assert moved.path.startswith(landed_under.path + PATH_SEPARATOR)
    assert below.parent_id == moved.pk
    assert below.path.startswith(moved.path + PATH_SEPARATOR)
    assert branch_a.pk not in (moved.parent_id, below.parent_id)


def _read_tree(
    node_pk: Any, child_pk: Any, parent_pk: Any
) -> tuple[Organization, Organization, Organization]:
    try:
        return (
            Organization.objects.get(pk=node_pk),
            Organization.objects.get(pk=child_pk),
            Organization.objects.get(pk=parent_pk),
        )
    finally:
        connections.close_all()
