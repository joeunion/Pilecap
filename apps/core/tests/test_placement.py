"""A grant comes from where you sent it — ADR core-20, the placement law.

*"Agree — comes from where you sent it. Don't elevate out of context."*

**What was wrong.** An invitation carried
no organization at all. `invite_member` asked its two authority questions at
`root_organization(tenant)`, wrote a row with no placement, and
`accept_invitation` landed the membership at the root — *whatever hat the
inviter was wearing when they sent it*. Two consequences, and they point in
opposite directions:

* **Elevation.** An owner acting under `X-Org: a-branch` issued an invitation
  that became a membership at the tenant ROOT — a grant that reached further
  than the context it was sent from, silently, with nothing in the request
  saying so.
* **A dead end.** A branch admin — somebody who administers `a-branch` and
  nothing above it — was refused outright: `require(actor,
  "invitation.create", root)` measures at the root, where they hold nothing.
  They could not invite anybody into their own branch. `add_membership` with
  `organization_id` omitted has the identical shape one door over: it defaulted
  to the root, so the same person's grant was refused by the escalation wall for
  a node they never named.

Both are one bug: the landing node was a constant instead of the context.

**What is true now.** The acting hat at grant time IS the landing node, recorded
on the row. Every authority question — issue, supersede, revoke, the escalation
wall, the removal ceiling — is asked AT that node. The accepted membership lands
exactly there. An omitted placement is the acting hat and never the root, on
both doors. **A caller can only ever be surprised narrower.**

**A flat product pays nothing**, and that is asserted rather than assumed: with
the hat at the root, every path here behaves exactly as it did.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import Forbidden, NotFound
from apps.core.models import Invitation, Membership, Organization, Tenant
from apps.core.selectors import list_invitations
from apps.core.services import (
    accept_invitation,
    add_membership,
    create_organization,
    invite_member,
    revoke_invitation,
)

pytestmark = pytest.mark.django_db

JSON = "application/json"
INVITATIONS = "/api/v1/invitations/"
MEMBERSHIPS = "/api/v1/memberships/"


# --- the tree, and the people standing in it ----------------------------------


@pytest.fixture
def branch(tenant: Tenant, owner: User, root_org: Organization) -> Organization:
    """One branch under the root. The context a grant is sent *from*."""
    return create_organization(
        tenant=tenant,
        parent=root_org,
        name="Branch",
        slug="branch",
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )


@pytest.fixture
def sibling(tenant: Tenant, owner: User, root_org: Organization) -> Organization:
    """A branch beside it, so "not mine" is a real place and not a hypothetical."""
    return create_organization(
        tenant=tenant,
        parent=root_org,
        name="Sibling",
        slug="sibling",
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )


@pytest.fixture
def branch_admin(tenant: Tenant, owner: User, branch: Organization) -> User:
    """Somebody who administers ONE branch and holds nothing above it.

    The whole rung is about this person: before the placement law they could
    neither invite into their own branch nor add a member to it without naming
    it, because both roads measured at a node they hold nothing on.
    """
    # The password is written out rather than taken from `apps.conftest`: this
    # module may reach up into `apps.accounts` (import-linter says so by name)
    # and may not reach sideways into the shared conftest, which drags
    # `apps.workflows` in behind it.
    user = create_user(
        email="branch-admin@example.com",
        password="a-long-enough-password",  # pragma: allowlist secret
    )
    add_membership(
        user=user,
        tenant=tenant,
        organization=branch,
        role=Membership.Role.ADMIN,
        is_default=True,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def branch_actor(branch_admin: User, tenant: Tenant, branch: Organization) -> Actor:
    return actor_for(user=branch_admin, tenant=tenant, org=branch)


@pytest.fixture
def owner_in_branch(owner: User, tenant: Tenant, branch: Organization) -> Actor:
    """The tenant's owner, acting under the branch's hat.

    This is the elevation shape: somebody who *could* grant at the root, sending
    a grant from somewhere narrower. Previously the grant landed at the root
    anyway.
    """
    return actor_for(user=owner, tenant=tenant, org=branch)


def _invited(tenant: Tenant, email: str) -> Invitation:
    return Invitation.objects.for_tenant(tenant).get(email=email)


# --- 1 · the row records where it was sent from -------------------------------


def test_an_invitation_records_the_hat_it_was_sent_from(
    tenant: Tenant, owner_in_branch: Actor, branch: Organization
) -> None:
    """The landing node is the context, not a constant.

    Previously `Invitation` had no organization column at all and this grant
    became a root membership.
    """
    invitation, _token = invite_member(
        tenant=tenant,
        email="new@example.com",
        invited_by=owner_in_branch.user,
        actor=owner_in_branch,
    )
    assert invitation.organization_id == branch.pk


def test_an_omitted_placement_is_the_acting_hat_and_never_the_root(
    tenant: Tenant, owner_in_branch: Actor, root_org: Organization, branch: Organization
) -> None:
    """The ruling's exact words, as the one assertion that separates the two."""
    invitation, _token = invite_member(
        tenant=tenant,
        email="omitted@example.com",
        invited_by=owner_in_branch.user,
        actor=owner_in_branch,
    )
    assert invitation.organization_id != root_org.pk
    assert invitation.organization_id == branch.pk


def test_a_named_placement_inside_the_hat_is_honoured(
    tenant: Tenant, owner: User, root_org: Organization, branch: Organization
) -> None:
    """Naming a node is still allowed — the default is what changed, not the door."""
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    invitation, _token = invite_member(
        tenant=tenant,
        email="named@example.com",
        organization=branch,
        invited_by=owner,
        actor=acting,
    )
    assert invitation.organization_id == branch.pk


def test_a_caller_is_only_ever_surprised_narrower(
    tenant: Tenant, owner_in_branch: Actor, branch: Organization
) -> None:
    """The ruling's safety property, stated as a property rather than a case.

    Whatever the door decides, the landing node is at or below the hat the
    request was made under. There is no input that makes it wider.
    """
    invitation, _token = invite_member(
        tenant=tenant,
        email="narrower@example.com",
        invited_by=owner_in_branch.user,
        actor=owner_in_branch,
    )
    landing = Organization.objects.get(pk=invitation.organization_id)
    assert landing.path.startswith(branch.path)


# --- 2 · every authority question is asked at that node -----------------------


def test_a_branch_admin_may_invite_into_their_own_branch(
    tenant: Tenant, branch_actor: Actor, branch: Organization
) -> None:
    """The dead end, closed. Previously they were refused at the root."""
    invitation, _token = invite_member(
        tenant=tenant,
        email="theirs@example.com",
        invited_by=branch_actor.user,
        actor=branch_actor,
    )
    assert invitation.organization_id == branch.pk


def test_a_branch_admin_may_not_invite_into_a_branch_they_do_not_hold(
    tenant: Tenant, branch_actor: Actor, sibling: Organization
) -> None:
    """Asked AT the node means refused at the node too — the wall did not move."""
    with pytest.raises(Forbidden):
        invite_member(
            tenant=tenant,
            email="elsewhere@example.com",
            organization=sibling,
            invited_by=branch_actor.user,
            actor=branch_actor,
        )


def test_the_escalation_wall_is_measured_at_the_landing_node(
    tenant: Tenant, branch_actor: Actor
) -> None:
    """Nobody invites above themselves, and "themselves" is measured where it lands."""
    with pytest.raises(Forbidden):
        invite_member(
            tenant=tenant,
            email="too-senior@example.com",
            role=Membership.Role.OWNER,
            invited_by=branch_actor.user,
            actor=branch_actor,
        )


def test_a_member_still_may_not_invite_anywhere(
    tenant: Tenant, member: User, root_org: Organization
) -> None:
    """The placement law widened nobody: `invitation.create` is still admin-or-owner."""
    acting = actor_for(user=member, tenant=tenant, org=root_org)
    with pytest.raises(Forbidden):
        invite_member(tenant=tenant, email="nope@example.com", invited_by=member, actor=acting)


# --- 3 · supersede is asked at the node too -----------------------------------


def test_issuing_again_supersedes_only_at_the_same_node(
    tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    sibling: Organization,
) -> None:
    """ "Invite them again" withdraws the one standing HERE, not somebody else's.

    Two branches may each have a live offer out to the same address, because
    they are offers of two different places. Superseding tenant-wide would let
    one branch silently withdraw another's.
    """
    at_branch, _ = invite_member(
        tenant=tenant,
        email="both@example.com",
        organization=branch,
        invited_by=owner,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )
    at_sibling, _ = invite_member(
        tenant=tenant,
        email="both@example.com",
        organization=sibling,
        invited_by=owner,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )
    at_branch.refresh_from_db()
    assert at_branch.status == Invitation.Status.PENDING
    assert at_sibling.status == Invitation.Status.PENDING

    again, _ = invite_member(
        tenant=tenant,
        email="both@example.com",
        organization=branch,
        invited_by=owner,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )
    at_branch.refresh_from_db()
    at_sibling.refresh_from_db()
    assert at_branch.status == Invitation.Status.REVOKED
    assert at_sibling.status == Invitation.Status.PENDING
    assert again.organization_id == branch.pk


# --- 4 · revoke is asked at the node ------------------------------------------


def test_a_branch_admin_may_revoke_their_own_branchs_invitation(
    tenant: Tenant, branch_actor: Actor
) -> None:
    invitation, _ = invite_member(
        tenant=tenant,
        email="withdrawn@example.com",
        invited_by=branch_actor.user,
        actor=branch_actor,
    )
    revoked = revoke_invitation(tenant=tenant, invitation=invitation, actor=branch_actor)
    assert revoked.status == Invitation.Status.REVOKED


def test_another_branchs_invitation_is_not_visible_to_revoke(
    tenant: Tenant,
    owner: User,
    root_org: Organization,
    sibling: Organization,
    branch_actor: Actor,
) -> None:
    """Out of the hat's subtree is `not_found`, which is how the tree answers."""
    invite_member(
        tenant=tenant,
        email="theirs@example.com",
        organization=sibling,
        invited_by=owner,
        actor=actor_for(user=owner, tenant=tenant, org=root_org),
    )
    with pytest.raises(NotFound):
        from apps.core.selectors import get_invitation

        get_invitation(
            tenant=tenant,
            org=branch_actor.org,
            invitation_id=_invited(tenant, "theirs@example.com").pk,
            actor=branch_actor,
        )


def test_the_list_is_narrowed_to_the_acting_hats_subtree(
    tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    sibling: Organization,
    branch_actor: Actor,
) -> None:
    """A read that showed every branch's offers would leak who is being hired where."""
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    invite_member(
        tenant=tenant,
        email="mine@example.com",
        organization=branch,
        invited_by=owner,
        actor=acting,
    )
    invite_member(
        tenant=tenant,
        email="yours@example.com",
        organization=sibling,
        invited_by=owner,
        actor=acting,
    )
    seen = {
        row.email
        for row in list_invitations(tenant=tenant, org=branch_actor.org, actor=branch_actor)
    }
    assert seen == {"mine@example.com"}
    whole = {row.email for row in list_invitations(tenant=tenant, org=root_org, actor=acting)}
    assert whole == {"mine@example.com", "yours@example.com"}


# --- 5 · the accepted membership lands exactly at the recorded node -----------


def test_the_accepted_membership_lands_at_the_recorded_node(
    tenant: Tenant, owner_in_branch: Actor, branch: Organization, nomad: User
) -> None:
    """The half that makes the record mean something."""
    invitation, _ = invite_member(
        tenant=tenant,
        email=nomad.email,
        invited_by=owner_in_branch.user,
        actor=owner_in_branch,
    )
    membership = accept_invitation(
        tenant=tenant,
        invitation=invitation,
        user=nomad,
        actor=actor_for(user=nomad, tenant=tenant, kind="human"),
    )
    assert membership.organization_id == branch.pk


def test_accepting_twice_in_two_branches_makes_two_memberships(
    tenant: Tenant,
    owner: User,
    root_org: Organization,
    branch: Organization,
    sibling: Organization,
    nomad: User,
) -> None:
    """Two offers of two different places really are two different offers."""
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    first, _ = invite_member(
        tenant=tenant,
        email=nomad.email,
        organization=branch,
        invited_by=owner,
        actor=acting,
    )
    second, _ = invite_member(
        tenant=tenant,
        email=nomad.email,
        organization=sibling,
        invited_by=owner,
        actor=acting,
    )
    one = accept_invitation(
        tenant=tenant,
        invitation=first,
        user=nomad,
        actor=actor_for(user=nomad, tenant=tenant, kind="human"),
    )
    two = accept_invitation(
        tenant=tenant,
        invitation=second,
        user=nomad,
        actor=actor_for(user=nomad, tenant=tenant, kind="human"),
    )
    assert {one.organization_id, two.organization_id} == {branch.pk, sibling.pk}


# --- 6 · the identical rule one door over: `add_membership` -------------------


def test_an_omitted_organization_on_add_membership_is_the_acting_hat(
    tenant: Tenant,
    owner_in_branch: Actor,
    branch: Organization,
    root_org: Organization,
    nomad: User,
) -> None:
    """The same class, the same answer. It used to default to the root."""
    membership = add_membership(
        user=nomad, tenant=tenant, role=Membership.Role.MEMBER, actor=owner_in_branch
    )
    assert membership.organization_id == branch.pk
    assert membership.organization_id != root_org.pk


def test_a_branch_admin_adds_a_member_to_their_branch_without_naming_it(
    tenant: Tenant, branch_actor: Actor, branch: Organization, nomad: User
) -> None:
    """Previously the wall refused them for a node they never named."""
    membership = add_membership(
        user=nomad, tenant=tenant, role=Membership.Role.MEMBER, actor=branch_actor
    )
    assert membership.organization_id == branch.pk


def test_add_membership_with_no_actor_still_lands_at_the_root(
    tenant: Tenant, root_org: Organization, nomad: User
) -> None:
    """Nobody acting means no hat to inherit — the bootstrap keeps its root.

    `create_tenant`, the seed command and `accept_invitation`'s own call all
    reach this with no actor. Defaulting those to anything but the root would
    change what a tenant's first membership means.
    """
    membership = add_membership(
        user=nomad, tenant=tenant, role=Membership.Role.MEMBER, actor=system_actor(tenant=tenant)
    )
    assert membership.organization_id == root_org.pk


# --- 7 · a flat product pays nothing ------------------------------------------


def test_a_flat_product_behaves_exactly_as_it_did(
    tenant: Tenant, owner: User, root_org: Organization, nomad: User
) -> None:
    """Hat == root, which is every flat product: nothing about this moved.

    Asserted rather than argued, because "unaffected" is the claim a hierarchy
    feature is least likely to be able to keep and most likely to be believed
    about.
    """
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    invitation, _ = invite_member(tenant=tenant, email=nomad.email, invited_by=owner, actor=acting)
    assert invitation.organization_id == root_org.pk

    membership = accept_invitation(
        tenant=tenant,
        invitation=invitation,
        user=nomad,
        actor=actor_for(user=nomad, tenant=tenant, kind="human"),
    )
    assert membership.organization_id == root_org.pk

    assert {
        row.email
        for row in list_invitations(tenant=tenant, org=root_org, actor=system_actor(tenant=tenant))
    } == {nomad.email}


# --- 8 · the wire says so -----------------------------------------------------


def _post(api: Client, url: str, body: dict[str, Any], **headers: str) -> Any:
    return api.post(url, data=json.dumps(body), content_type=JSON, headers=headers)


def test_the_http_door_places_an_invitation_at_the_acting_hat(
    api: Client, tenant: Tenant, owner: User, branch: Organization
) -> None:
    """`X-Org` is the context, and the row records it."""
    api.force_login(owner)
    response = _post(
        api,
        INVITATIONS,
        {"email": "wire@example.com"},
        **{"x-tenant": tenant.slug, "x-org": branch.slug},
    )
    assert response.status_code == 201, response.content
    assert _invited(tenant, "wire@example.com").organization_id == branch.pk


def test_the_http_door_places_a_membership_at_the_acting_hat(
    api: Client, tenant: Tenant, owner: User, branch: Organization, nomad: User
) -> None:
    api.force_login(owner)
    response = _post(
        api,
        MEMBERSHIPS,
        {"user_id": str(nomad.pk), "role": Membership.Role.MEMBER},
        **{"x-tenant": tenant.slug, "x-org": branch.slug},
    )
    assert response.status_code == 201, response.content
    assert json.loads(response.content)["organization_id"] == str(branch.pk)


def test_the_removal_ceiling_is_measured_at_the_membership_s_own_node(
    tenant: Tenant, branch_actor: Actor, owner: User, root_org: Organization
) -> None:
    """The ceiling half of the placement law, which did not have to move.

    `_refuse_acting_above_yourself` has always measured the actor's effective
    role at `membership.organization` rather than at the root. That is the same
    rule the rest of this file applies to the other four questions — so it is
    pinned here rather than left as a coincidence: a
    branch admin cannot remove the tenant's owner, because at the owner's node
    the branch admin holds nothing.
    """
    from apps.core.services import revoke_membership

    at_root = Membership.objects.get(user=owner, tenant=tenant, organization=root_org)
    with pytest.raises((Forbidden, NotFound)):
        revoke_membership(tenant=tenant, membership=at_root, actor=branch_actor)
    assert Membership.objects.filter(pk=at_root.pk).exists()


def test_the_refusal_sentence_moved_with_the_behaviour(
    tenant: Tenant, member: User, root_org: Organization
) -> None:
    """A 403 that still said "into this tenant" would be describing the old rule.

    The brief's own clause: the placement never silently changes an existing
    refusal without the prose moving with it. `invitation.create` is authorized
    against an ORGANIZATION now, so the sentence a refused caller reads says
    organization — and the route's contract half says the same thing, which is
    what rule 41 requires.
    """
    from apps.core.api.docs import contract_of
    from apps.core.api.routes import invite_member_route
    from apps.core.authz import require

    acting = actor_for(user=member, tenant=tenant, org=root_org)
    with pytest.raises(Forbidden) as refused:
        require(acting, "invitation.create", root_org)
    assert refused.value.detail == "You may not invite people into that organization."
    assert "tenant" not in refused.value.detail

    # Flattened before matching: the contract half is wrapped prose, so an
    # assertion that carried its line breaks would go red on a reflow rather
    # than on a change of meaning.
    contract = " ".join(contract_of(invite_member_route).split())
    assert "administrator of the organization this invitation is placed in" in contract


def test_both_invitation_contracts_state_the_placement() -> None:
    """Rule 41's half: the document moves with the behaviour, on both doors.

    The MCP twin renders the REST route's own docstring, so asserting the route
    contract asserts both — which is exactly why the twin renders it.
    """
    from apps.core.api.docs import contract_of
    from apps.core.api.routes import (
        accept_invitation_route,
        invite_member_route,
        list_invitations_route,
    )

    issue = contract_of(invite_member_route)
    assert "organization_id" in issue
    assert "X-Org" in issue

    accept = contract_of(accept_invitation_route)
    assert "organization" in accept.lower()

    listing = contract_of(list_invitations_route)
    assert "X-Org" in listing
