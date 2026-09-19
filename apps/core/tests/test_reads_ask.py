"""Reads are permissions: the six selectors, both doors, the admin, and the kick.

**What this module is for, and what it deliberately is not.**
`test_resolution.py` drives the ALGEBRA — what a person holds at a node. This
drives the SEAM: that every scoped read in `core` actually asks, that the answer
a refused caller gets is the same on every door, and that the socket hears about
a narrowing. The two are separate because they fail separately: a resolution bug
tells the wrong person yes, a seam bug never asks at all.

**The grammar under test, in one line** (§C8, reach before capability): a row
outside the hat's subtree is `not_found`, a row inside it without
`<kind>.read` is `forbidden`, and a list without the key is `forbidden` because
a list has no row to hide. The ORDER is asserted by the two exception types
rather than described — a `get_` that asked the capability before the scoped
fetch would answer `forbidden` where this expects `not_found`, and that is the
oracle §C8 exists to close.

Raw `Grant` rows, because the services that hand permissions out are P4's and
the criteria say a raw create is legal until they land.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

import pytest
from django.contrib.auth.models import Permission as DjangoPermission
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core import bridge
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import refusal_sentence
from apps.core.exceptions import Conflict, Forbidden, NotFound, refusal_message
from apps.core.mcp import SCOPE_KEY, Principal, register
from apps.core.models import Grant, Invitation, Membership, Organization, Tenant
from apps.core.selectors import (
    get_invitation,
    get_membership,
    get_organization,
    list_invitations,
    list_memberships,
    list_organizations,
)
from apps.core.services import (
    KICK_PERMISSIONS_NARROWED,
    add_membership,
    create_organization,
    invite_member,
    root_organization,
    set_role,
)

pytestmark = pytest.mark.django_db

JSON = "application/json"
PASSWORD = "reads-ask-pass-1234"  # pragma: allowlist secret


# --- the world ----------------------------------------------------------------


@dataclass(frozen=True)
class Reads:
    """One tenant, `root -> a -> a1` and a sibling `b`, with rows in each branch.

    The reader is a `member` at **A**, so their hat covers `a` and `a1` and
    never `b`. Every case below is one of three cells: a row in `b` (outside),
    a row in `a1` (inside), and the list at the hat.
    """

    tenant: Tenant
    root: Organization
    a: Organization
    a1: Organization
    b: Organization
    reader: User
    reader_membership: Membership
    inside_membership: Membership
    outside_membership: Membership
    inside_invitation: Invitation
    outside_invitation: Invitation

    def actor(self) -> Actor:
        """A fresh actor at A — fresh because the memo's TTL is the instance."""
        return actor_for(user=self.reader, tenant=self.tenant, org=self.a)


@pytest.fixture
def reads(tenant: Tenant, owner: User) -> Reads:
    root = root_organization(tenant=tenant)
    system = system_actor(tenant=tenant)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=system)
    a1 = create_organization(tenant=tenant, parent=a, name="A1", slug="a1", actor=system)
    b = create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=system)

    reader = create_user(email="reader@example.com", password=PASSWORD)
    reader_membership = add_membership(
        user=reader,
        tenant=tenant,
        organization=a,
        role=Membership.Role.MEMBER,
        is_default=True,
        actor=system,
    )
    inside = create_user(email="inside@example.com", password=PASSWORD)
    inside_membership = add_membership(
        user=inside, tenant=tenant, organization=a1, role=Membership.Role.MEMBER, actor=system
    )
    outside = create_user(email="outside@example.com", password=PASSWORD)
    outside_membership = add_membership(
        user=outside, tenant=tenant, organization=b, role=Membership.Role.MEMBER, actor=system
    )
    inside_invitation, _ = invite_member(
        tenant=tenant,
        email="offered-inside@example.com",
        role=Membership.Role.MEMBER,
        organization=a1,
        invited_by=owner,
        actor=system,
    )
    outside_invitation, _ = invite_member(
        tenant=tenant,
        email="offered-outside@example.com",
        role=Membership.Role.MEMBER,
        organization=b,
        invited_by=owner,
        actor=system,
    )
    return Reads(
        tenant=tenant,
        root=root,
        a=a,
        a1=a1,
        b=b,
        reader=reader,
        reader_membership=reader_membership,
        inside_membership=inside_membership,
        outside_membership=outside_membership,
        inside_invitation=inside_invitation,
        outside_invitation=outside_invitation,
    )


def withhold(membership: Membership, permission: str) -> Grant:
    """A raw `withhold` row. Legal until P4 lands the hand-out services."""
    return Grant.objects.create(
        tenant=membership.tenant,
        membership=membership,
        permission=permission,
        effect=Grant.Effect.WITHHOLD,
    )


#: kind → (the id of a row INSIDE the hat's subtree, the id of one OUTSIDE it),
#: read off the world. One entry per core kind that has a `get_`.
def _cells(reads: Reads) -> dict[str, tuple[UUID, UUID]]:
    return {
        "organization": (reads.a1.pk, reads.b.pk),
        "membership": (reads.inside_membership.pk, reads.outside_membership.pk),
        "invitation": (reads.inside_invitation.pk, reads.outside_invitation.pk),
    }


def _get(kind: str) -> Callable[..., Any]:
    return {
        "organization": lambda **kw: get_organization(organization_id=kw.pop("row"), **kw),
        "membership": lambda **kw: get_membership(membership_id=kw.pop("row"), **kw),
        "invitation": lambda **kw: get_invitation(invitation_id=kw.pop("row"), **kw),
    }[kind]


def _list(kind: str) -> Callable[..., Any]:
    return {
        "organization": list_organizations,
        "membership": list_memberships,
        "invitation": list_invitations,
    }[kind]


# --- PR1.2 · the selectors ask, and the order is the criterion -----------------


@pytest.mark.parametrize("kind", ["organization", "membership", "invitation"])
def test_a_read_outside_the_subtree_is_not_found_and_inside_without_the_key_is_forbidden(
    reads: Reads, kind: str
) -> None:
    """Three cells per kind, and the third is the one Phase R adds.

    *Outside* is `not_found` and always was — the scoped fetch answers before a
    capability is ever consulted, so a caller cannot map a branch they hold
    nothing on by reading which ids refuse differently. *Inside without the
    key* is `forbidden`, which is what every capability has answered on every
    door since day one and what makes the read gate VISIBLE to
    `test_contract_docs.py` (a 404 there reads as inconclusive). A *list*
    without the key is `forbidden` because there is no row to hide.

    Then the withhold is lifted and all three answer, which is what stops this
    from being a test that would pass with the selectors refusing everybody.
    """
    inside, outside = _cells(reads)[kind]
    key = f"{kind}.read"
    withhold(reads.reader_membership, key)

    with pytest.raises(NotFound):
        _get(kind)(tenant=reads.tenant, org=reads.a, row=outside, actor=reads.actor())

    with pytest.raises(Forbidden) as refused:
        _get(kind)(tenant=reads.tenant, org=reads.a, row=inside, actor=reads.actor())
    assert str(refused.value.args[0]) == refusal_sentence(key)

    with pytest.raises(Forbidden) as refused_list:
        _list(kind)(tenant=reads.tenant, org=reads.a, actor=reads.actor())
    assert str(refused_list.value.args[0]) == refusal_sentence(key)

    # ...and with the withhold gone, the same three calls answer.
    Grant.objects.filter(membership=reads.reader_membership, permission=key).delete()
    assert _get(kind)(tenant=reads.tenant, org=reads.a, row=inside, actor=reads.actor()) is not None
    assert _list(kind)(tenant=reads.tenant, org=reads.a, actor=reads.actor()).exists()
    with pytest.raises(NotFound):
        _get(kind)(tenant=reads.tenant, org=reads.a, row=outside, actor=reads.actor())


def test_the_system_actor_reads_everything_the_scope_shows(reads: Reads) -> None:
    """`system` passes at step 1, so activities, commands and the seed are untouched.

    Asserted with a withhold on the reader in place, so the pass is the actor
    kind and not an accident of there being nothing to refuse.
    """
    for kind in ("organization", "membership", "invitation"):
        withhold(reads.reader_membership, f"{kind}.read")
    system = system_actor(tenant=reads.tenant, org=reads.root)
    for kind, (inside, _outside) in _cells(reads).items():
        assert _list(kind)(tenant=reads.tenant, org=reads.root, actor=system).exists()
        assert _get(kind)(tenant=reads.tenant, org=reads.root, row=inside, actor=system) is not None


# --- PR1.3 · both doors, the same words ---------------------------------------


@dataclass
class _FakeRequest:
    scope: dict[str, Any]


@dataclass
class _FakeRequestContext:
    request: _FakeRequest


def context_for(user: User, tenant: Tenant, org: Organization) -> Context[Any]:
    """The context a tool sees, with the principal the middleware would have left."""
    scope = {SCOPE_KEY: Principal(user=user, tenant=tenant, org=org)}
    return Context(
        request_context=cast(Any, _FakeRequestContext(request=_FakeRequest(scope=scope)))
    )


def tool(name: str) -> Callable[..., Any]:
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    register(server)
    found: Callable[..., Any] = cast(Any, server._tool_manager._tools[name]).fn  # noqa: SLF001
    return found


def test_a_withheld_read_is_forbidden_on_the_wire_and_the_twin_says_the_same(
    api: Client, reads: Reads
) -> None:
    """E9: the MCP message IS the REST body, rendered — string-compared.

    **Disproved while building PR1.3:** the criterion names
    `GET /api/v1/memberships/{id}/` and there is no such route — `core` publishes
    exactly one scoped detail read on the wire (`organization-detail`), and
    `get_membership`/`get_invitation` are reached from the write routes only —
    there is no `get_membership` MCP tool either, because the tool set mirrors
    the route set. So the get half is driven where a get half exists on BOTH
    doors: `organization-detail` and its `get_organization` twin, string-compared
    through `wire_refusal`.

    A row in a sibling branch stays 404 on both doors — the §C8 half Phase R
    does not touch.
    """
    withhold(reads.reader_membership, "membership.read")
    withhold(reads.reader_membership, "organization.read")
    api.force_login(reads.reader)

    listed = api.get("/api/v1/memberships/")
    assert listed.status_code == 403, listed.content
    body = listed.json()
    assert body["code"] == "forbidden"
    assert body["detail"] == refusal_sentence("membership.read")

    # The one scoped detail read `core` publishes, inside the hat's subtree.
    fetched = api.get(f"/api/v1/organizations/{reads.a1.pk}/")
    assert fetched.status_code == 403, fetched.content
    assert fetched.json()["detail"] == refusal_sentence("organization.read")

    with pytest.raises(ToolError) as listed_tool:
        tool("list_memberships")(context_for(reads.reader, reads.tenant, reads.a))
    assert str(listed_tool.value) == refusal_message(body)

    with pytest.raises(ToolError) as fetched_tool:
        tool("get_organization")(
            context_for(reads.reader, reads.tenant, reads.a),
            organization_id=reads.a1.pk,
        )
    assert str(fetched_tool.value) == refusal_message(fetched.json())

    # The sibling branch is still NOT FOUND on both doors — unchanged.
    outside = api.get(f"/api/v1/organizations/{reads.b.pk}/")
    assert outside.status_code == 404
    with pytest.raises(ToolError) as outside_tool:
        tool("get_organization")(
            context_for(reads.reader, reads.tenant, reads.a),
            organization_id=reads.b.pk,
        )
    assert str(outside_tool.value) == refusal_message(outside.json())


# --- PR1.4 · the admin door asks the same question ----------------------------


def test_the_admin_changelist_of_a_withheld_kind_is_refused_not_emptied(
    api: Client, reads: Reads
) -> None:
    """An empty page and a refusal are different facts, and the admin used to lie.

    `get_queryset` scopes the rows and has never answered "whether this kind at
    all", so before `has_view_permission` a hat without `organization.read` got
    a changelist rendering zero rows — indistinguishable from a tenant with no
    branches.
    """
    # A staff member holding Django's own `view_organization` and nothing else
    # — NOT a superuser, and that is load-bearing. Django gates a changelist on
    # `has_view_or_change_permission`, so a superuser renders it through the
    # CHANGE half whatever the read gate says; PR1 moves the read gate and not
    # the write one, so the person this criterion is about is the one whose only
    # permission is to view.
    reads.reader.is_staff = True
    reads.reader.save(update_fields=["is_staff"])
    reads.reader.user_permissions.add(
        DjangoPermission.objects.get(
            codename="view_organization",
            content_type=ContentType.objects.get_for_model(Organization),
        )
    )
    api.force_login(reads.reader)

    allowed = api.get("/admin/core/organization/")
    assert allowed.status_code == 200

    withhold(reads.reader_membership, "organization.read")
    refused = api.get("/admin/core/organization/")
    assert refused.status_code == 403


# --- PR1.8 · the narrowing kick -----------------------------------------------


@pytest.fixture
def kicks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Every `close_sockets` ask, recorded, with the real seam otherwise intact.

    Only the `KICK` name is diverted — `bridge.find` still answers for every
    other registered name. The same fixture `apps/accounts/tests/test_user_doors.py`
    uses, for its reason: what is under test here is that the write reached the
    seam with the right person and the right reason on it; that the seam then
    closes a REAL socket is driven over a real connection in
    `apps/realtime/tests/test_authorization_kick.py`.
    """
    recorded: list[dict[str, Any]] = []
    real_find = bridge.find

    def record(*, user_id: UUID, reason: str) -> None:
        recorded.append({"user_id": user_id, "reason": reason})

    def find(name: str) -> Any:
        return record if name == bridge.KICK else real_find(name)

    monkeypatch.setattr(bridge, "find", find)
    return recorded


def _approver(tenant: Tenant) -> str:
    """A custom role whose collection holds one WRITE key and no reads at all."""
    from apps.core.models import Role, RolePermission

    Role.objects.create(tenant=tenant, key="approver", name="Approver")
    RolePermission.objects.create(
        tenant=tenant,
        role_key="approver",
        permission="widget.approve",
        effect=RolePermission.Effect.INCLUDE,
    )
    return "approver"


def test_a_demotion_that_narrows_a_read_kicks_that_person_and_nobody_else(
    reads: Reads, owner: User, kicks: list[dict[str, Any]], django_capture_on_commit_callbacks: Any
) -> None:
    """BVB-3: a socket resolved at the handshake goes on delivering what it may no longer read.

    `member` → the custom `approver`, whose collection is one include row and
    no reads: every kind this person could hear about is gone. The kick is for
    exactly that person; the reader's colleague in the sibling branch, whose
    permissions nobody touched, is not hung up on.
    """
    role = _approver(reads.tenant)
    system = system_actor(tenant=reads.tenant, org=reads.root)

    with django_capture_on_commit_callbacks(execute=True):
        set_role(tenant=reads.tenant, membership=reads.reader_membership, role=role, actor=system)

    assert kicks == [{"user_id": reads.reader.pk, "reason": KICK_PERMISSIONS_NARROWED}]
    assert all(kick["user_id"] != owner.pk for kick in kicks)


def test_a_promotion_kicks_nobody(
    reads: Reads, kicks: list[dict[str, Any]], django_capture_on_commit_callbacks: Any
) -> None:
    """A widening takes nothing away, so hanging up would be a reconnect for nothing."""
    system = system_actor(tenant=reads.tenant, org=reads.root)
    with django_capture_on_commit_callbacks(execute=True):
        set_role(
            tenant=reads.tenant,
            membership=reads.reader_membership,
            role=Membership.Role.ADMIN,
            actor=system,
        )
    assert kicks == []


def test_a_rolled_back_demotion_kicks_nobody(
    reads: Reads, kicks: list[dict[str, Any]], django_capture_on_commit_callbacks: Any
) -> None:
    """`on_commit`: a write that never landed must not disconnect anybody.

    The rollback is forced by the ownerless floor — a real refusal on a real
    road, rather than a raised exception the test invented.
    """
    role = _approver(reads.tenant)
    system = system_actor(tenant=reads.tenant, org=reads.root)
    owner_membership = Membership.objects.get(tenant=reads.tenant, role=Membership.Role.OWNER)
    with django_capture_on_commit_callbacks(execute=True), pytest.raises(Conflict):
        set_role(tenant=reads.tenant, membership=owner_membership, role=role, actor=system)
    assert kicks == []


# --- PR1.9 · the write door pays the read once --------------------------------


def test_a_write_door_pays_the_read_once(reads: Reads, django_assert_num_queries: Any) -> None:
    """The memo's whole point, asserted where Phase R makes it matter.

    A write request now asks twice — the `get_` selector asks `<kind>.read`, the
    service asks its own verb — and without PR0's memo that would be **six**
    authorization statements rather than three.

    `n = 5`, decomposed so the number is not a magic one: **2** scoped fetches
    (one per `get_membership`, unchanged by Phase R) **+ 3** authorization
    statements, paid ONCE for the actor. The claim is the 3, and what would
    break it is 6.
    """
    actor = reads.actor()
    with django_assert_num_queries(5):
        assert get_membership(
            tenant=reads.tenant,
            org=reads.a,
            membership_id=reads.inside_membership.pk,
            actor=actor,
        )
        assert get_membership(
            tenant=reads.tenant,
            org=reads.a,
            membership_id=reads.inside_membership.pk,
            actor=actor,
        )
