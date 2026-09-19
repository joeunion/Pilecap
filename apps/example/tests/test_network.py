"""The network truths — what a hierarchy is actually for.

One tenant, four nodes, four people. Everything here is a claim about *which
rows somebody can see*, because that is the only thing a hierarchy is: a rule
about visibility that a product must not be able to get wrong by forgetting.

    root  (hq)                 owner, and an admin
     |
     +-- seller-a              a manager, admin of A
     |    |
     |    +-- sub-a1           a clerk, member of A1
     |
     +-- seller-b              nobody here holds anything

The claims, one test each:

* a sub-seller sees its own rows and no others;
* a seller sees its own **and** its sub-seller's — downward inheritance;
* sideways is blocked: A cannot see B, and B cannot see A;
* upward is blocked: A1 cannot see A's rows, even though A is its parent;
* the **hat switches** the answer: one person, two memberships, two `X-Org`
  headers, two different sets of rows;
* **re-parenting moves visibility**: A1 under B, and its rows move with it;
* a grant above the granter's own effective role is refused, and a grant
  outside their subtree is refused;
* the root's admin sees everything;
* **REST and MCP agree** on the same rows for the same hat;
* a **workflow activity acting for A1** reads and writes as A1, and the audit
  row says so;
* a superuser with no membership still sees nothing.

The tree is built here rather than in the shared `conftest`, because a tree in
the shared conftest would make every unrelated test in the repository pay for
one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from django.test import Client
from django.urls import reverse
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.authz import effective_role
from apps.core.exceptions import Forbidden, NotFound
from apps.core.mcp import SCOPE_KEY, Principal
from apps.core.middleware import resolve_org
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import (
    add_membership,
    apply_organization_move,
    create_organization,
    move_organization,
    root_organization,
    set_role,
)
from apps.example.mcp import register
from apps.example.models import Widget, WidgetEntry, WidgetPolicy
from apps.example.selectors import (
    get_governing_widget_policy,
    list_widget_entries,
    list_widgets,
)
from apps.example.services import create_widget, create_widget_policy, record_widget_entry

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"
PASSWORD = "a-long-enough-password"  # pragma: allowlist secret


def reading(tenant: Tenant | None, org: Any) -> Actor:
    """The actor these scoping tests read as, now that reads are permissions.

    `system`, on purpose (ADR core-27; `allows` passes it at step 1). Every
    selector assertion in this file is about WHICH rows a hat sees —
    `visible_to`, `governing`, `for_tenant`, which is rule 24's question — and a
    person-shaped actor would make each of them depend on `widget.read` as well.
    Whether a kind may be read at all is `test_reads_ask.py`'s subject; holding
    the capability half constant is what keeps this file measuring the scoping
    half, which is the only half it was ever written about.

    The `org` argument is whatever the call site passed — a node, an `Actor`, or
    `None` — because these selectors take any of the three; only a real node
    means anything to `system_actor`.
    """
    return system_actor(tenant, org if isinstance(org, Organization) else None)


# --- The tree ----------------------------------------------------------------


@dataclass
class Network:
    """One tenant's tree and the people in it, as one fixture value.

    A dataclass rather than nine fixtures: every test here needs most of the
    tree, and nine fixtures would make each signature a paragraph and each
    test's meaning harder to find than its set-up.
    """

    tenant: Tenant
    hq: Organization
    seller_a: Organization
    sub_a1: Organization
    seller_b: Organization
    owner: User
    manager: User  # admin of seller_a
    clerk: User  # member of sub_a1
    both: User  # member of seller_a AND of sub_a1


@pytest.fixture
def network(tenant: Tenant, owner: User) -> Network:
    hq = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=hq)
    seller_a = create_organization(
        tenant=tenant, parent=hq, name="Seller A", slug="seller-a", actor=acting
    )
    seller_b = create_organization(
        tenant=tenant, parent=hq, name="Seller B", slug="seller-b", actor=acting
    )
    sub_a1 = create_organization(
        tenant=tenant, parent=seller_a, name="Sub A1", slug="sub-a1", actor=acting
    )

    manager = create_user(email="manager@example.com", password=PASSWORD)
    add_membership(
        user=manager,
        tenant=tenant,
        organization=seller_a,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    clerk = create_user(email="clerk@example.com", password=PASSWORD)
    add_membership(
        user=clerk,
        tenant=tenant,
        organization=sub_a1,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    both = create_user(email="both@example.com", password=PASSWORD)
    add_membership(
        user=both,
        tenant=tenant,
        organization=seller_a,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    add_membership(
        user=both,
        tenant=tenant,
        organization=sub_a1,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    return Network(
        tenant=tenant,
        hq=hq,
        seller_a=seller_a,
        sub_a1=sub_a1,
        seller_b=seller_b,
        owner=owner,
        manager=manager,
        clerk=clerk,
        both=both,
    )


def hat(net: Network, user: User, org: Organization) -> Actor:
    return actor_for(user=user, tenant=net.tenant, org=org)


def seed(net: Network) -> dict[str, Widget]:
    """One widget at each node, each named after where it lives."""
    return {
        "hq": create_widget(tenant=net.tenant, actor=hat(net, net.owner, net.hq), name="At HQ"),
        "a": create_widget(
            tenant=net.tenant, actor=hat(net, net.manager, net.seller_a), name="At A"
        ),
        "a1": create_widget(tenant=net.tenant, actor=hat(net, net.clerk, net.sub_a1), name="At A1"),
        "b": create_widget(tenant=net.tenant, actor=hat(net, net.owner, net.seller_b), name="At B"),
    }


def names(rows: Any) -> set[str]:
    return {row.name for row in rows}


# --- The shape of the tree itself --------------------------------------------


def test_the_tree_is_a_materialized_path_with_fixed_width_segments(network: Network) -> None:
    assert network.hq.path == "0000"
    assert network.seller_a.path == "0000.0000"
    assert network.seller_b.path == "0000.0001"
    assert network.sub_a1.path == "0000.0000.0000"
    assert (network.hq.depth, network.seller_a.depth, network.sub_a1.depth) == (0, 1, 2)
    # The whole read path in one property: containment is a prefix test.
    assert network.seller_a.contains(network.sub_a1)
    assert not network.sub_a1.contains(network.seller_a)
    assert not network.seller_a.contains(network.seller_b)


def test_every_tenant_gets_a_root_named_after_it(tenant: Tenant) -> None:
    root = root_organization(tenant=tenant)
    assert root.parent_id is None
    assert root.slug == tenant.slug
    assert Organization.objects.for_tenant(tenant).filter(parent__isnull=True).count() == 1


# --- Visibility: down only, never up, never sideways -------------------------


def test_a_sub_seller_sees_only_its_own(network: Network) -> None:
    seed(network)
    assert names(
        list_widgets(
            tenant=network.tenant, org=network.sub_a1, actor=reading(network.tenant, network.sub_a1)
        )
    ) == {"At A1"}


def test_a_seller_sees_its_own_and_its_sub_sellers(network: Network) -> None:
    seed(network)
    assert names(
        list_widgets(
            tenant=network.tenant,
            org=network.seller_a,
            actor=reading(network.tenant, network.seller_a),
        )
    ) == {"At A", "At A1"}


def test_sideways_is_blocked(network: Network) -> None:
    """A and B are siblings. Neither is any of the other's business."""
    seed(network)
    assert "At B" not in names(
        list_widgets(
            tenant=network.tenant,
            org=network.seller_a,
            actor=reading(network.tenant, network.seller_a),
        )
    )
    assert "At A" not in names(
        list_widgets(
            tenant=network.tenant,
            org=network.seller_b,
            actor=reading(network.tenant, network.seller_b),
        )
    )
    assert "At A1" not in names(
        list_widgets(
            tenant=network.tenant,
            org=network.seller_b,
            actor=reading(network.tenant, network.seller_b),
        )
    )


def test_upward_is_blocked(network: Network) -> None:
    """A1 is under A. That gives A sight of A1, and gives A1 nothing."""
    seed(network)
    assert names(
        list_widgets(
            tenant=network.tenant, org=network.sub_a1, actor=reading(network.tenant, network.sub_a1)
        )
    ) == {"At A1"}


def test_the_root_sees_all_of_it(network: Network) -> None:
    seed(network)
    assert names(
        list_widgets(
            tenant=network.tenant, org=network.hq, actor=reading(network.tenant, network.hq)
        )
    ) == {
        "At HQ",
        "At A",
        "At A1",
        "At B",
    }


def test_no_hat_reads_nothing(network: Network) -> None:
    """`visible_to(None)` fails closed, exactly as `for_tenant(None)` does."""
    seed(network)
    assert (
        list_widgets(tenant=network.tenant, org=None, actor=reading(network.tenant, None)).count()
        == 0
    )
    assert list_widgets(tenant=None, org=network.hq, actor=reading(None, network.hq)).count() == 0


def test_a_superuser_with_no_membership_still_sees_nothing(network: Network, root: User) -> None:
    """There is no exemption one level down either.

    `root` is a superuser belonging to no tenant. The tenancy already gave them
    nothing; the hierarchy is asked the same question and gives the same answer,
    because an exemption is a leak with a nicer name.
    """
    seed(network)
    assert resolve_org(user=root, tenant=network.tenant, requested_slug=None) is None
    assert (
        list_widgets(
            tenant=network.tenant,
            org=actor_for(user=root, tenant=network.tenant),
            actor=reading(network.tenant, None),
        ).count()
        == 0
    )


# --- Roles inherit down, and only down ---------------------------------------


def test_effective_role_is_the_best_role_on_an_ancestor(network: Network) -> None:
    # The owner holds `owner` at HQ and therefore everywhere beneath it.
    assert effective_role(network.owner, network.tenant, network.sub_a1) == Membership.Role.OWNER
    # The manager holds `admin` at A: over A and A1, and nothing at B.
    assert effective_role(network.manager, network.tenant, network.seller_a) == (
        Membership.Role.ADMIN
    )
    assert effective_role(network.manager, network.tenant, network.sub_a1) == (
        Membership.Role.ADMIN
    )
    assert effective_role(network.manager, network.tenant, network.seller_b) is None
    # The clerk holds `member` at A1 — and nothing at A, one level up.
    assert effective_role(network.clerk, network.tenant, network.sub_a1) == Membership.Role.MEMBER
    assert effective_role(network.clerk, network.tenant, network.seller_a) is None
    assert effective_role(network.clerk, network.tenant, network.hq) is None


# --- The escalation wall -----------------------------------------------------


def test_a_grant_above_your_own_effective_role_is_refused(network: Network) -> None:
    """An admin of A may make admins and members of A. Not owners."""
    newcomer = create_user(email="newcomer@example.com", password=PASSWORD)
    granting = hat(network, network.manager, network.seller_a)

    with pytest.raises(Forbidden):
        add_membership(
            user=newcomer,
            tenant=network.tenant,
            organization=network.seller_a,
            role=Membership.Role.OWNER,
            actor=granting,
        )
    assert not Membership.objects.filter(user=newcomer).exists()


def test_a_grant_at_or_below_your_own_effective_role_is_allowed(network: Network) -> None:
    """The other direction, so the refusal above is not just a broken service."""
    newcomer = create_user(email="allowed@example.com", password=PASSWORD)
    granted = add_membership(
        user=newcomer,
        tenant=network.tenant,
        organization=network.sub_a1,
        role=Membership.Role.ADMIN,
        actor=hat(network, network.manager, network.seller_a),
    )
    assert granted.role == Membership.Role.ADMIN
    assert granted.organization_id == network.sub_a1.pk


def test_a_grant_outside_your_subtree_is_refused(network: Network) -> None:
    """The manager runs A. B is not theirs to staff, at any role."""
    newcomer = create_user(email="elsewhere@example.com", password=PASSWORD)
    with pytest.raises(Forbidden):
        add_membership(
            user=newcomer,
            tenant=network.tenant,
            organization=network.seller_b,
            role=Membership.Role.MEMBER,
            actor=hat(network, network.manager, network.seller_a),
        )


def test_promoting_past_your_own_ceiling_is_refused_too(network: Network) -> None:
    """A promotion is a grant with an extra step, and the wall is the same."""
    existing = Membership.objects.get(user=network.clerk, organization=network.sub_a1)
    with pytest.raises(Forbidden):
        set_role(
            tenant=network.tenant,
            membership=existing,
            role=Membership.Role.OWNER,
            actor=hat(network, network.manager, network.seller_a),
        )
    existing.refresh_from_db()
    assert existing.role == Membership.Role.MEMBER

    promoted = set_role(
        tenant=network.tenant,
        membership=existing,
        role=Membership.Role.ADMIN,
        actor=hat(network, network.manager, network.seller_a),
    )
    assert promoted.role == Membership.Role.ADMIN


def test_opening_a_node_needs_admin_over_its_parent(network: Network) -> None:
    """Ancestor-admin, said from the create side: underneath yourself only."""
    with pytest.raises(Forbidden):
        create_organization(
            tenant=network.tenant,
            parent=network.seller_b,
            name="Sub B1",
            slug="sub-b1",
            actor=hat(network, network.manager, network.seller_a),
        )
    under_mine = create_organization(
        tenant=network.tenant,
        parent=network.sub_a1,
        name="Sub A1a",
        slug="sub-a1a",
        actor=hat(network, network.manager, network.seller_a),
    )
    assert under_mine.path.startswith(network.sub_a1.path + ".")


def test_a_member_may_not_open_a_node_at_all(network: Network) -> None:
    with pytest.raises(Forbidden):
        create_organization(
            tenant=network.tenant,
            parent=network.sub_a1,
            name="Sub A1b",
            slug="sub-a1b",
            actor=hat(network, network.clerk, network.sub_a1),
        )


# --- The acting hat, over HTTP -----------------------------------------------


def _list(api: Client, headers: dict[str, str] | None = None) -> dict[str, Any]:
    response = api.get(LIST_URL, headers=headers or {})
    assert response.status_code == 200, response.content
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def test_the_hat_switches_the_visible_set(api: Client, network: Network) -> None:
    """One person, two memberships, two headers, two answers.

    `both` is a member of A and of A1. Acting as A they see A's row and A1's;
    acting as A1 they see only A1's. Nothing about the person changed — the
    header did, and it is revalidated from their memberships every request.
    """
    seed(network)
    api.force_login(network.both)

    as_a = _list(api, {"x-org": "seller-a"})
    assert {item["name"] for item in as_a["items"]} == {"At A", "At A1"}

    as_a1 = _list(api, {"x-org": "sub-a1"})
    assert {item["name"] for item in as_a1["items"]} == {"At A1"}


def test_a_hat_you_hold_no_role_over_is_refused_identically(api: Client, network: Network) -> None:
    """Naming a sibling — or the group above you, or nothing at all — is refused.

    **Refused, and byte-identically** (ADR core-21). It used to read an
    empty table, on the argument that a 403 would tell the caller seller B
    exists. The anti-oracle is kept and the lie is not: the three answers below
    are the same bytes, so the refusal still says nothing about what exists —
    it fires because the slug is not one this credential can wear, and it names
    the header rather than the slug. What it stops is a fat-fingered `X-Org`
    reading as a zero bill, which is this table's whole point.
    """
    seed(network)
    api.force_login(network.clerk)

    sibling = api.get(LIST_URL, headers={"x-org": "seller-b"})
    above = api.get(LIST_URL, headers={"x-org": "seller-a"})
    absent = api.get(LIST_URL, headers={"x-org": "nope"})
    for refused in (sibling, above, absent):
        assert refused.status_code == 403, refused.content
        assert json.loads(refused.content)["code"] == "addressing_header_not_honoured"
    assert sibling.content == above.content == absent.content

    # Their own hat still works, so the refusals above are the rule and not a bug.
    assert len(_list(api, {"x-org": "sub-a1"})["items"]) == 1


def test_the_default_hat_is_the_default_memberships_own_node(api: Client, network: Network) -> None:
    seed(network)
    api.force_login(network.clerk)
    body = _list(api)
    assert {item["name"] for item in body["items"]} == {"At A1"}
    assert {item["organization_slug"] for item in body["items"]} == {"sub-a1"}


def test_a_row_outside_the_hat_is_not_found_rather_than_forbidden(
    api: Client, network: Network
) -> None:
    widgets = seed(network)
    api.force_login(network.clerk)
    assert api.get(f"{LIST_URL}{widgets['a'].pk}/").status_code == 404
    assert api.get(f"{LIST_URL}{widgets['a1'].pk}/").status_code == 200


def test_a_write_lands_in_the_hat_it_was_made_under(api: Client, network: Network) -> None:
    api.force_login(network.both)
    response = api.post(
        LIST_URL,
        data=json.dumps({"name": "Made as A1", "notes": ""}),
        content_type="application/json",
        headers={"x-org": "sub-a1"},
    )
    assert response.status_code == 201, response.content
    assert json.loads(response.content)["organization_slug"] == "sub-a1"
    # And it is invisible from the sibling, immediately.
    assert (
        list_widgets(
            tenant=network.tenant,
            org=network.seller_b,
            actor=reading(network.tenant, network.seller_b),
        )
        .filter(name="Made as A1")
        .count()
        == 0
    )


# --- The machine door agrees with the human one ------------------------------


@dataclass
class _FakeRequest:
    scope: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def mcp_context(user: User, tenant: Tenant, org: Organization | None) -> Context[Any]:
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=org)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def tool(name: str) -> Any:
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    return server._tool_manager._tools[name].fn


def test_both_doors_answer_with_the_same_rows_for_the_same_hat(
    api: Client, network: Network
) -> None:
    """The disagreement between doors that `architecture.md` calls a finding.

    Same person, same `X-Org`, both doors — and the assertion is on the *set of
    rows*, not on the count, because two doors can agree on how many and differ
    on which.
    """
    seed(network)
    api.force_login(network.both)

    for slug, org in (("seller-a", network.seller_a), ("sub-a1", network.sub_a1)):
        over_http = {item["name"] for item in _list(api, {"x-org": slug})["items"]}
        page = tool("list_widgets")(ctx=mcp_context(network.both, network.tenant, org))
        over_mcp = {item.name for item in page.items}
        assert over_http == over_mcp, slug


def test_the_machine_door_fails_closed_on_a_hat_it_does_not_hold(network: Network) -> None:
    """The token names a hat; `resolve_org` is what decides whether it gets one.

    The hat is resolved here the way `config.mcp`'s token middleware resolves
    it — from the header, against the principal's own memberships — rather than
    handed to the `Principal` directly, because "a caller cannot name a branch
    it holds no membership over" is the claim, and a test that constructed the
    principal by hand would be asserting about a shortcut nothing takes.
    """
    seed(network)
    refused = resolve_org(user=network.clerk, tenant=network.tenant, requested_slug="seller-b")
    assert refused is None
    page = tool("list_widgets")(ctx=mcp_context(network.clerk, network.tenant, refused))
    assert len(page.items) == 0


# --- Re-parenting ------------------------------------------------------------


def move(net: Network, node: Organization, new_parent: Organization, actor: Actor) -> Organization:
    """Order the move, then run the activity's write.

    `move_organization` authorizes and starts `MoveOrganizationWorkflow`; the
    rewrite itself is `apply_organization_move`, reached through
    `rewrite_organization_paths`. Under pytest nothing commits, so the
    on-commit hook never fires and the activity is called directly here — as
    the system, which is exactly who calls it in production. The workflow half
    is proved against a real Temporal server in
    `apps/workflows/tests/test_workflows.py`.
    """
    move_organization(tenant=net.tenant, organization=node, new_parent=new_parent, actor=actor)
    return apply_organization_move(
        tenant=net.tenant,
        organization=node,
        new_parent=new_parent,
        actor=system_actor(net.tenant, actor.org),
    )


def test_re_parenting_moves_the_subtrees_rows_with_it(network: Network) -> None:
    """A1 goes from under A to under B, and every row underneath goes with it.

    This is the whole reason a re-parent is a workflow rather than an UPDATE:
    the visibility of every row in the subtree changes at once, and it has to
    change completely or not at all.
    """
    seed(network)
    deep = create_widget(
        tenant=network.tenant, actor=hat(network, network.clerk, network.sub_a1), name="Deep in A1"
    )

    # A sees its own row plus everything at A1, which is now two rows.
    assert names(
        list_widgets(
            tenant=network.tenant,
            org=network.seller_a,
            actor=reading(network.tenant, network.seller_a),
        )
    ) == {
        "At A",
        "At A1",
        "Deep in A1",
    }
    assert names(
        list_widgets(
            tenant=network.tenant,
            org=network.seller_b,
            actor=reading(network.tenant, network.seller_b),
        )
    ) == {"At B"}

    moved = move(network, network.sub_a1, network.seller_b, hat(network, network.owner, network.hq))

    assert moved.parent_id == network.seller_b.pk
    assert moved.path.startswith(network.seller_b.path + ".")
    assert moved.depth == network.seller_b.depth + 1
    # A has lost sight of A1's rows; B has gained them.
    assert names(
        list_widgets(
            tenant=network.tenant,
            org=network.seller_a,
            actor=reading(network.tenant, network.seller_a),
        )
    ) == {"At A"}
    assert names(
        list_widgets(
            tenant=network.tenant,
            org=network.seller_b,
            actor=reading(network.tenant, network.seller_b),
        )
    ) == {
        "At B",
        "At A1",
        "Deep in A1",
    }
    # The rows themselves never moved: their organization is the same row it was.
    deep.refresh_from_db()
    assert deep.organization_id == network.sub_a1.pk
    # And the root still sees everything, as it did before.
    assert (
        len(
            names(
                list_widgets(
                    tenant=network.tenant, org=network.hq, actor=reading(network.tenant, network.hq)
                )
            )
        )
        == 5
    )


def test_a_deeper_subtree_keeps_its_shape_through_a_move(network: Network) -> None:
    acting = hat(network, network.owner, network.hq)
    grandchild = create_organization(
        tenant=network.tenant,
        parent=network.sub_a1,
        name="Sub A1a",
        slug="sub-a1a",
        actor=acting,
    )
    moved = move(network, network.sub_a1, network.seller_b, acting)
    grandchild.refresh_from_db()
    assert grandchild.path == moved.path + "." + grandchild.path.rsplit(".", 1)[-1]
    assert grandchild.depth == moved.depth + 1
    assert grandchild.parent_id == moved.pk


def test_a_move_needs_admin_over_both_ends(network: Network) -> None:
    """Admin of where it comes from AND of where it goes. A move is both at once."""
    # The manager runs A (so A1's current parent) but holds nothing over B.
    with pytest.raises(Forbidden):
        move_organization(
            tenant=network.tenant,
            organization=network.sub_a1,
            new_parent=network.seller_b,
            actor=hat(network, network.manager, network.seller_a),
        )
    # And the other way round: somebody who runs B but not A.
    runs_b = create_user(email="runs-b@example.com", password=PASSWORD)
    add_membership(
        user=runs_b,
        tenant=network.tenant,
        organization=network.seller_b,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=network.tenant),
    )
    with pytest.raises(Forbidden):
        move_organization(
            tenant=network.tenant,
            organization=network.sub_a1,
            new_parent=network.seller_b,
            actor=hat(network, runs_b, network.seller_b),
        )


def test_the_shapes_that_are_not_a_move_are_refused(network: Network) -> None:
    from apps.core.exceptions import Invalid

    acting = hat(network, network.owner, network.hq)
    with pytest.raises(Invalid):
        move_organization(
            tenant=network.tenant,
            organization=network.hq,
            new_parent=network.seller_a,
            actor=acting,
        )
    with pytest.raises(Invalid):
        move_organization(
            tenant=network.tenant,
            organization=network.seller_a,
            new_parent=network.sub_a1,
            actor=acting,
        )


def test_applying_a_move_twice_changes_nothing_the_second_time(network: Network) -> None:
    """Temporal runs an activity at least once, so the write has to be idempotent."""
    acting = hat(network, network.owner, network.hq)
    first = move(network, network.sub_a1, network.seller_b, acting)
    again = apply_organization_move(
        tenant=network.tenant,
        organization=first,
        new_parent=network.seller_b,
        actor=system_actor(network.tenant, network.hq),
    )
    assert again.path == first.path
    assert again.parent_id == network.seller_b.pk


# --- The workflow's activity acts as the hat it was started under -------------


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("recorded_workflow_starts")
def test_an_activity_acting_for_a_sub_seller_reads_and_writes_as_it(
    network: Network,
) -> None:
    """The workflow door, wearing the same hat the request that started it wore.

    This drives `apps.example.activities.mark_widget_onboarded` directly — the
    real activity body, with the principal set the way the interceptor sets it
    from the workflow's headers. What is proved is the part that would otherwise
    be invisible: the activity reads through `visible_to(org)`, so a run started
    for A1 cannot touch a row at A, and the audit row it leaves says which hat
    it acted under.

    `transaction=True` because a real activity calls `close_old_connections()`
    at both ends — it has no request cycle to do it for it — and that is exactly
    what an open test transaction cannot survive. Running against real commits
    is the honest way to drive one.

    Real commits are also why `recorded_workflow_starts` is here: `seed` creates
    widgets, `create_widget` registers an onboarding run on `transaction.on_commit`,
    and in this test that commit is real. The run is recorded and not dialled —
    the onboarding workflow is proved in `test_workflows.py`, against a server
    this test has no business starting (queue V3).
    """
    from apps.example.activities import mark_widget_onboarded
    from apps.example.types import WidgetOnboarding
    from apps.workflows.context import reset_principal, set_principal

    widgets = seed(network)

    tokens = set_principal(
        tenant_id=str(network.tenant.pk),
        user_id=str(network.clerk.pk),
        org_id=str(network.sub_a1.pk),
    )
    try:
        marked_at = mark_widget_onboarded(WidgetOnboarding(widget_id=str(widgets["a1"].pk)))
        assert marked_at
        # The same activity, the same hat, a row one level UP: not found.
        with pytest.raises(NotFound):
            mark_widget_onboarded(WidgetOnboarding(widget_id=str(widgets["a"].pk)))
    finally:
        reset_principal(tokens)

    widgets["a1"].refresh_from_db()
    assert widgets["a1"].onboarded_at is not None

    entry = (
        AuditEntry.objects.for_tenant(network.tenant)
        .filter(action="example.mark_widget_onboarded")
        .first()
    )
    assert entry is not None
    assert entry.acting_org_id == network.sub_a1.pk
    assert entry.actor_kind == AuditEntry.Kind.SYSTEM


def test_the_audit_row_of_a_human_write_carries_the_hat(api: Client, network: Network) -> None:
    api.force_login(network.both)
    response = api.post(
        LIST_URL,
        data=json.dumps({"name": "Audited as A1", "notes": ""}),
        content_type="application/json",
        headers={"x-org": "sub-a1"},
    )
    assert response.status_code == 201, response.content
    entry = (
        AuditEntry.objects.for_tenant(network.tenant).filter(action="example.create_widget").first()
    )
    assert entry is not None
    assert entry.acting_org_id == network.sub_a1.pk
    assert entry.door == "rest"


# --- Approval follows the tree, both ways ------------------------------------


def approve_url(widget: Widget) -> str:
    return f"{LIST_URL}{widget.pk}/approve/"


def test_a_sub_seller_cannot_approve_a_siblings_widget(api: Client, network: Network) -> None:
    """404, not 403: sideways is not "you may not", it is "there is no such row".

    The clerk at Sub A1 asking about Seller B's widget must not learn that it
    exists — the same answer they get for an id nobody ever minted.
    """
    widgets = seed(network)
    api.force_login(network.clerk)
    response = api.post(approve_url(widgets["b"]), content_type="application/json")
    assert response.status_code == 404, response.content


def test_a_sub_seller_cannot_approve_its_parents_widget(api: Client, network: Network) -> None:
    """Upward is blocked too, and for the same reason it is blocked on reads."""
    widgets = seed(network)
    api.force_login(network.clerk)
    response = api.post(approve_url(widgets["a"]), content_type="application/json")
    assert response.status_code == 404, response.content


def test_a_seller_admin_may_approve_at_its_sub_seller(api: Client, network: Network) -> None:
    """Roles inherit downwards, so approval does — the manager of A covers A1.

    This is the half that makes `can_approve` read the role over the *widget's*
    node rather than over the actor's hat: the manager is acting as Seller A,
    and the row lives one level below.
    """
    widgets = seed(network)
    api.force_login(network.manager)
    response = api.post(approve_url(widgets["a1"]), content_type="application/json")
    assert response.status_code == 200, response.content


def test_a_sub_seller_member_may_not_approve_even_at_home(api: Client, network: Network) -> None:
    """Nothing inherits up, and a member is a member wherever they stand."""
    widgets = seed(network)
    api.force_login(network.clerk)
    response = api.post(approve_url(widgets["a1"]), content_type="application/json")
    assert response.status_code == 403, response.content


# --- Config goes DOWN; visibility does not ------------------------------------
#
# Everything below is one claim in two halves, and the halves point in opposite
# directions on purpose. A branch **resolves** the policy its parent set — it is
# governed by that policy whether it can see it or not — and a branch **lists**
# only its own. If those two ever agree, the hierarchy has grown an upward leak
# with a friendly name (ADR core-3, `architecture.md` A5a).

POLICIES_URL = f"{LIST_URL}policies/"
GOVERNING_URL = f"{POLICIES_URL}governing/"
ENTRIES_URL = f"{LIST_URL}entries/"
STATS_URL = f"{LIST_URL}stats/"


def seed_policies(net: Network) -> dict[str, WidgetPolicy]:
    """One policy at the root and one at Seller A. **Nothing at A1, on purpose.**

    A1 is the interesting node precisely because it has no policy of its own:
    what governs it has to come from somewhere above, and which "somewhere" is
    the whole question `governing()` answers. B has nothing of its own either,
    so it falls all the way through to the root's — which is what makes the two
    answers different and the test able to fail.
    """
    return {
        "hq": create_widget_policy(
            tenant=net.tenant, actor=hat(net, net.owner, net.hq), name="House rules"
        ),
        "a": create_widget_policy(
            tenant=net.tenant, actor=hat(net, net.manager, net.seller_a), name="Seller A rules"
        ),
    }


def test_the_nearest_policy_on_the_chain_is_the_one_that_governs(network: Network) -> None:
    """Root -> A -> A1, and root -> B. A1 gets A's; B falls through to the root's.

    This is the whole of `governing()` in four assertions: nearest wins, "nearest"
    is measured in tree depth and not in insertion order, and a node with nothing
    above it but the root resolves the root's.
    """
    policies = seed_policies(network)

    at_a1 = get_governing_widget_policy(
        tenant=network.tenant, org=network.sub_a1, actor=reading(network.tenant, network.sub_a1)
    )
    assert at_a1.pk == policies["a"].pk, "A1 must resolve A's, not the root's — nearest wins"

    at_b = get_governing_widget_policy(
        tenant=network.tenant, org=network.seller_b, actor=reading(network.tenant, network.seller_b)
    )
    assert at_b.pk == policies["hq"].pk, "B has nothing of its own and nothing between it and HQ"

    # And the two ends of the chain resolve themselves, which is what makes
    # "the chain includes me" true rather than assumed.
    assert get_governing_widget_policy(
        tenant=network.tenant, org=network.seller_a, actor=reading(network.tenant, network.seller_a)
    ).pk == (policies["a"].pk)
    assert get_governing_widget_policy(
        tenant=network.tenant, org=network.hq, actor=reading(network.tenant, network.hq)
    ).pk == (policies["hq"].pk)


def test_resolution_fails_closed_with_no_hat_and_when_nothing_governs(network: Network) -> None:
    """The two ways there is no answer, and both of them are `NotFound`."""
    with pytest.raises(NotFound):
        # A tree with no policies in it at all.
        get_governing_widget_policy(
            tenant=network.tenant, org=network.sub_a1, actor=reading(network.tenant, network.sub_a1)
        )
    seed_policies(network)
    with pytest.raises(NotFound):
        # An unresolved hat resolves no configuration rather than the root's —
        # the same fail-closed shape `for_tenant(None)` and `visible_to(None)` have.
        get_governing_widget_policy(
            tenant=network.tenant, org=None, actor=reading(network.tenant, None)
        )


def test_a_branch_never_lists_the_policy_that_governs_it(api: Client, network: Network) -> None:
    """**The split, over the wire.** A1 resolves A's policy and cannot list it.

    Both halves in one test because neither is worth much alone: a list that
    shows nothing proves nothing if the resolution also shows nothing, and a
    resolution that reaches up is only safe if the list does not. Read together
    they say the sentence the whole design rests on — upward *config
    resolution*, never upward *visibility*.
    """
    policies = seed_policies(network)
    api.force_login(network.clerk)  # a member of Sub A1 and of nowhere else

    governing = api.get(GOVERNING_URL, headers={"x-org": "sub-a1"})
    assert governing.status_code == 200, governing.content
    resolved = json.loads(governing.content)
    assert resolved["id"] == str(policies["a"].pk)
    # And it says whose it is, which is how a client can tell it was inherited.
    assert resolved["organization_slug"] == "seller-a"

    listed = api.get(POLICIES_URL, headers={"x-org": "sub-a1"})
    assert listed.status_code == 200, listed.content
    body = json.loads(listed.content)
    assert len(body["items"]) == 0, "A1 owns no policy; the one governing it is not A1's to list"
    assert body["items"] == []


def test_a_seller_lists_its_own_and_its_sub_sellers_policies(api: Client, network: Network) -> None:
    """The list half, in the direction it *does* travel: down, like every list."""
    seed_policies(network)
    at_a1 = create_widget_policy(
        tenant=network.tenant, actor=hat(network, network.manager, network.sub_a1), name="A1 rules"
    )
    api.force_login(network.manager)

    body = json.loads(api.get(POLICIES_URL, headers={"x-org": "seller-a"}).content)
    assert {item["name"] for item in body["items"]} == {"Seller A rules", "A1 rules"}
    assert str(at_a1.pk) in {item["id"] for item in body["items"]}

    # The root's policy is one level UP from A, and it is not in the list.
    assert "House rules" not in {item["name"] for item in body["items"]}


def test_setting_a_policy_needs_a_role_and_lands_on_the_acting_hat(
    api: Client, network: Network
) -> None:
    """Config travels down, so a member may not write it — and it lands on the hat.

    `create_widget_policy` reads `actor.org` and takes no `organization=`, so
    the second assertion is about the same hole the widget create closes: a
    caller cannot name a branch, only wear one.
    """
    api.force_login(network.clerk)  # a MEMBER of A1
    refused = api.post(
        POLICIES_URL,
        data=json.dumps({"name": "Member's rules", "body": ""}),
        content_type="application/json",
        headers={"x-org": "sub-a1"},
    )
    assert refused.status_code == 403, refused.content
    assert WidgetPolicy.objects.for_tenant(network.tenant).count() == 0

    api.force_login(network.manager)  # an ADMIN of A, and therefore of A1
    made = api.post(
        POLICIES_URL,
        data=json.dumps({"name": "Manager's rules", "body": ""}),
        content_type="application/json",
        headers={"x-org": "sub-a1"},
    )
    assert made.status_code == 201, made.content
    assert json.loads(made.content)["organization_slug"] == "sub-a1"


# --- Naming a policy: the link gate, and the rival's champion ------------------


def test_a_branch_may_name_the_policy_its_parent_set(api: Client, network: Network) -> None:
    """201. **The link gate, live**: A1 names A's policy, a row it cannot list.

    This is the widening `InheritedDownward` buys and the only one it buys.
    `may_be_named` says yes because the policy's organization is on the hat's
    ancestor chain; nothing about `visible_to` moved, and the previous test is
    what proves that.
    """
    policies = seed_policies(network)
    api.force_login(network.clerk)

    response = api.post(
        LIST_URL,
        data=json.dumps(
            {"name": "Under A's policy", "notes": "", "policy_id": str(policies["a"].pk)}
        ),
        content_type="application/json",
        headers={"x-org": "sub-a1"},
    )

    assert response.status_code == 201, response.content
    body = json.loads(response.content)
    assert body["policy_id"] == str(policies["a"].pk)
    assert body["organization_slug"] == "sub-a1"


def test_naming_a_siblings_policy_is_a_404_with_remedies_and_writes_nothing(
    api: Client, network: Network
) -> None:
    """**The rival's champion**, refused: B's policy, named from A1, is `not_found`.

    404 and not 403, because 403 would confirm that a policy with that id exists
    somewhere in this tenant — the fact the scoping was hiding. The body is
    checked as a *superset* of `{detail, code}` rather than as an exact key set:
    the refusal envelope is additive by contract (G2's `remedies` joined it
    mid-cycle without renaming anything), so a test that pinned the key set
    exactly would break on every honest addition.

    The write leaves nothing behind and the refusal is on the audit trail, which
    is the half a status-code assertion cannot see: a refusal nobody recorded is
    a refusal nobody can count.
    """
    seed_policies(network)
    at_b = create_widget_policy(
        tenant=network.tenant, actor=hat(network, network.owner, network.seller_b), name="B rules"
    )
    api.force_login(network.clerk)

    response = api.post(
        LIST_URL,
        data=json.dumps({"name": "Stolen", "notes": "", "policy_id": str(at_b.pk)}),
        content_type="application/json",
        headers={"x-org": "sub-a1"},
    )

    assert response.status_code == 404, response.content
    body = json.loads(response.content)
    assert {"detail", "code"} <= set(body), body
    assert body["code"] == "not_found"
    # G2's addition, present because `not_found` registered remedies: what the
    # caller can DO, not prose about what went wrong.
    assert body["remedies"], body

    assert not Widget.objects.for_tenant(network.tenant).filter(name="Stolen").exists()


def test_the_refused_naming_is_audited_as_an_error(network: Network) -> None:
    """The **audited** fence, driven where audit rows come from: inside the service.

    There are two fences on this and they refuse in different places, which is
    why they are tested in different places. Over the wire the door refuses
    first — `resolve_named_policy` cannot find a sibling's policy on the hat's
    ancestor chain at all — and a refusal raised at a door leaves no audit row,
    because the audit trail records *services*.

    So the second fence is driven directly: `create_widget`, handed a policy row
    from Seller B by an actor wearing Sub A1's hat. That is the shape a future
    door, an activity or a hand-written script would arrive in, and it is
    refused with `not_found` and recorded with `outcome=error` — which is the
    half of "no row was written" that a status code cannot say.
    """
    at_b = create_widget_policy(
        tenant=network.tenant, actor=hat(network, network.owner, network.seller_b), name="B rules"
    )

    with pytest.raises(NotFound):
        create_widget(
            tenant=network.tenant,
            actor=hat(network, network.clerk, network.sub_a1),
            name="Stolen",
            policy=at_b,
        )

    assert not Widget.objects.for_tenant(network.tenant).filter(name="Stolen").exists()
    entry = (
        AuditEntry.objects.for_tenant(network.tenant)
        .filter(action="example.create_widget", outcome=AuditEntry.Outcome.ERROR)
        .first()
    )
    assert entry is not None, "a refusal nobody recorded is a refusal nobody can count"
    assert entry.error_code == "not_found"
    assert entry.acting_org_id == network.sub_a1.pk


# --- The ledger: it lands where the widget is, and nothing rewrites it ---------


def test_an_entry_lands_in_the_widgets_branch_not_the_actors_hat(
    api: Client, network: Network
) -> None:
    """The manager acts as Seller A and records against a widget at Sub A1.

    The entry lands at **A1**, because `derive_org_from = "widget"` says the row
    belongs where its subject belongs. Had it been stamped with the actor's hat
    it would have landed at A — visible to A, invisible to A1, and wrong in a way
    no later read could report.
    """
    widgets = seed(network)
    api.force_login(network.manager)

    response = api.post(
        ENTRIES_URL,
        data=json.dumps({"widget_id": str(widgets["a1"].pk), "kind": "note", "note": "Seen"}),
        content_type="application/json",
        headers={"x-org": "seller-a"},
    )

    assert response.status_code == 201, response.content
    assert json.loads(response.content)["organization_slug"] == "sub-a1"


def test_a_body_naming_a_mismatched_organization_is_a_400_on_that_field(
    api: Client, network: Network
) -> None:
    """**The landing gate, live on the wire.** 400, and it names `organization`.

    The manager may legitimately wear Seller A's hat and may legitimately see
    A1's widget — nothing about tenancy or visibility refuses this request. What
    refuses it is the model's own `clean()`, because the branch the body names
    disagrees with the branch the widget lives in, and a row like that lands
    where its own parent cannot see it.
    """
    widgets = seed(network)
    api.force_login(network.manager)

    response = api.post(
        ENTRIES_URL,
        data=json.dumps(
            {
                "widget_id": str(widgets["a1"].pk),
                "kind": "note",
                "note": "Filed at the wrong desk",
                "organization_slug": "seller-a",
            }
        ),
        content_type="application/json",
        headers={"x-org": "seller-a"},
    )

    assert response.status_code == 400, response.content
    body = json.loads(response.content)
    assert {"detail", "code"} <= set(body), body
    assert "organization" in body["errors"], body
    assert WidgetEntry.objects.for_tenant(network.tenant).count() == 0


def test_naming_the_widgets_own_branch_is_accepted_and_changes_nothing(
    api: Client, network: Network
) -> None:
    """The other side of the gate: the only value it accepts is the derived one."""
    widgets = seed(network)
    api.force_login(network.manager)

    response = api.post(
        ENTRIES_URL,
        data=json.dumps(
            {
                "widget_id": str(widgets["a1"].pk),
                "note": "Filed correctly",
                "organization_slug": "sub-a1",
            }
        ),
        content_type="application/json",
        headers={"x-org": "seller-a"},
    )

    assert response.status_code == 201, response.content
    assert json.loads(response.content)["organization_slug"] == "sub-a1"


def test_the_ledger_is_scoped_like_everything_else(api: Client, network: Network) -> None:
    """A sees A's and A1's lines; A1 sees only its own; B sees neither."""
    widgets = seed(network)
    for key in ("a", "a1", "b"):
        record_widget_entry(
            tenant=network.tenant,
            actor=hat(network, network.owner, network.hq),
            widget=widgets[key],
            note=f"line for {key}",
        )

    def lines(org: Organization) -> set[str]:
        return {
            entry.note
            for entry in list_widget_entries(
                tenant=network.tenant, org=org, actor=reading(network.tenant, org)
            )
        }

    assert lines(network.seller_a) == {"line for a", "line for a1"}
    assert lines(network.sub_a1) == {"line for a1"}
    assert lines(network.seller_b) == {"line for b"}
    assert (
        list_widget_entries(
            tenant=network.tenant, org=None, actor=reading(network.tenant, None)
        ).count()
        == 0
    )


def test_the_ledger_has_no_write_back_door(api: Client, network: Network) -> None:
    """There is no route and no tool that edits or removes a line. **By design.**

    The claim is about the *doors*, so it is asserted against the doors: every
    HTTP route the app mounts and every MCP tool it registers, checked for any
    that would write to an entry other than by appending. House rule 20 covers
    the population (`WidgetEntry.append_only` is discovered, not listed) and its
    canary is the quality lane's; this is the door-shaped half of the same
    promise, which no AST scan of `services.py` would see.
    """
    from apps.example.api import router

    offered = {
        (path, method)
        for path, path_view in router.path_operations.items()
        for operation in path_view.operations
        for method in operation.methods
        if path.startswith("/entries")
    }
    assert offered == {("/entries/", "GET"), ("/entries/", "POST")}, offered

    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    entry_tools = {name for name in server._tool_manager._tools if "widget_entr" in name}
    assert entry_tools == {"list_widget_entries", "record_widget_entry"}, entry_tools


def test_approving_appends_a_line_where_the_widget_lives(api: Client, network: Network) -> None:
    """The ledger the done-line drives: approval writes its own row, at A1.

    The manager approves as Seller A (roles inherit down, so they may), and the
    line lands at Sub A1 with the widget — the same derivation, reached from a
    service rather than from a body.
    """
    widgets = seed(network)
    api.force_login(network.manager)

    response = api.post(approve_url(widgets["a1"]), content_type="application/json")
    assert response.status_code == 200, response.content

    entries = list(
        list_widget_entries(
            tenant=network.tenant, org=network.sub_a1, actor=reading(network.tenant, network.sub_a1)
        )
    )
    assert [entry.kind for entry in entries] == [WidgetEntry.Kind.APPROVED]
    assert entries[0].organization_id == network.sub_a1.pk


def test_the_new_routes_are_mounted_where_they_say(network: Network) -> None:
    """The paths, pinned by name — so a rename shows up here and not in a client.

    Every `url_name` these routes added, reversed. It is also what house rule 3
    reads: a route that no test names is an unproven door, and the rule looks
    for the name.
    """
    assert reverse("api:widget_stats-detail") == STATS_URL
    assert reverse("api:widget_policies-list") == POLICIES_URL
    assert reverse("api:widget_policy-create") == POLICIES_URL
    assert reverse("api:governing_widget_policy-detail") == GOVERNING_URL
    assert reverse("api:widget_entries-list") == ENTRIES_URL
    assert reverse("api:widget_entry-record") == ENTRIES_URL


def test_the_hat_switches_the_policy_and_ledger_sets_too(api: Client, network: Network) -> None:
    """One person, two memberships, two headers — and it is not only widgets.

    `both` belongs to Seller A and to Sub A1. The claim the widget list already
    makes is made again here for the two shapes these routes added, because "the
    hat decides the answer" is a property of the *reads*, not of one model, and
    a new model that quietly ignored the hat would pass every existing test.
    """
    widgets = seed(network)
    create_widget_policy(
        tenant=network.tenant, actor=hat(network, network.manager, network.seller_a), name="A rules"
    )
    create_widget_policy(
        tenant=network.tenant, actor=hat(network, network.manager, network.sub_a1), name="A1 rules"
    )
    for key in ("a", "a1"):
        record_widget_entry(
            tenant=network.tenant,
            actor=hat(network, network.owner, network.hq),
            widget=widgets[key],
            note=f"line for {key}",
        )
    api.force_login(network.both)

    as_a = json.loads(api.get(POLICIES_URL, headers={"x-org": "seller-a"}).content)
    assert {item["name"] for item in as_a["items"]} == {"A rules", "A1 rules"}
    as_a1 = json.loads(api.get(POLICIES_URL, headers={"x-org": "sub-a1"}).content)
    assert {item["name"] for item in as_a1["items"]} == {"A1 rules"}

    ledger_a = json.loads(api.get(ENTRIES_URL, headers={"x-org": "seller-a"}).content)
    assert {item["note"] for item in ledger_a["items"]} == {"line for a", "line for a1"}
    ledger_a1 = json.loads(api.get(ENTRIES_URL, headers={"x-org": "sub-a1"}).content)
    assert {item["note"] for item in ledger_a1["items"]} == {"line for a1"}

    # And the measured number moves with the hat as well, which is the one place
    # a scoping mistake would show up as a *number* rather than as a missing row.
    stats_a = json.loads(api.get(STATS_URL, headers={"x-org": "seller-a"}).content)
    stats_a1 = json.loads(api.get(STATS_URL, headers={"x-org": "sub-a1"}).content)
    assert stats_a["count"]["value"] == "2"
    assert stats_a1["count"]["value"] == "1"


def test_a_second_tenants_policies_and_entries_are_absent(
    api: Client, network: Network, other_tenant: Tenant, stranger: User, stranger_actor: Actor
) -> None:
    """The tenancy, one level above the hierarchy, for the two new shapes.

    The sibling tests above are all *inside* one tenant, which is the harder
    property and the newer one — and it is exactly why this one still has to be
    written. A read that got `visible_to` perfectly right and dropped
    `for_tenant` would pass every test in this file up to here.
    """
    other_widget = create_widget(
        tenant=other_tenant, actor=stranger_actor, name="Not yours", notes=""
    )
    create_widget_policy(tenant=other_tenant, actor=stranger_actor, name="Their rules")
    record_widget_entry(
        tenant=other_tenant, actor=stranger_actor, widget=other_widget, note="their line"
    )
    seed(network)
    api.force_login(network.owner)

    policies = json.loads(api.get(POLICIES_URL, headers={"x-org": "acme"}).content)
    assert len(policies["items"]) == 0
    entries = json.loads(api.get(ENTRIES_URL, headers={"x-org": "acme"}).content)
    assert len(entries["items"]) == 0
    stats = json.loads(api.get(STATS_URL, headers={"x-org": "acme"}).content)
    assert stats["count"]["value"] == "4", "the four widgets of THIS tenant, and not a fifth"

    # And from the selectors, so the claim is about the reads rather than about
    # one route's query string.
    assert (
        list_widget_entries(
            tenant=network.tenant, org=network.hq, actor=reading(network.tenant, network.hq)
        ).count()
        == 0
    )

    # The sharp edge, said out loud: **both tenants' roots have path "0000"**,
    # because a materialized path is only unique inside its own tree. A
    # `governing()` that resolved on the path alone would hand Acme's root
    # Globex's policy — same path, same name, different company. The `for_tenant`
    # half is what stops that, and this is the assertion that would notice.
    ours = create_widget_policy(
        tenant=network.tenant, actor=hat(network, network.owner, network.hq), name="Their rules"
    )
    resolved = get_governing_widget_policy(
        tenant=network.tenant, org=network.hq, actor=reading(network.tenant, network.hq)
    )
    assert resolved.pk == ours.pk
    assert resolved.tenant_id == network.tenant.pk
