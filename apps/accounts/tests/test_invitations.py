"""Invitations, and the signup that honours them.

The last test is the one that matters: sign up through allauth's real form, at
allauth's real URL, and end up in the tenant that invited you. If that path
regresses, every invitation email in the product goes to a dead end — and it is
exactly the kind of thing a signal makes untestable, because a signal would
also fire for the fixtures.
"""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import actor_for, system_actor
from apps.core.exceptions import Conflict, Invalid
from apps.core.models import Invitation, Membership, Tenant
from apps.core.selectors import list_pending_invitations_for
from apps.core.services import (
    accept_invitation,
    hash_invitation_token,
    invite_member,
    revoke_invitation,
)
from apps.core.time import now

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret


# --- The invitation itself ---------------------------------------------------


def test_inviting_stores_only_the_hash(tenant: Tenant, owner: User) -> None:
    """What goes in the email is a bearer credential; a leaked database must not
    hand over every outstanding invitation."""
    invitation, token = invite_member(
        tenant=tenant,
        email="  New.Person@Example.COM ",
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )
    assert token
    assert invitation.email == "new.person@example.com"
    assert invitation.token_hash == hash_invitation_token(token)
    assert token not in invitation.token_hash
    assert invitation.role == Membership.Role.MEMBER
    assert invitation.is_pending
    assert invitation.invited_by_id == owner.pk


def test_inviting_again_supersedes_the_first(tenant: Tenant, owner: User) -> None:
    """ "Send it again" is what somebody clicks when the email went to spam."""
    first, _ = invite_member(
        tenant=tenant,
        email="again@example.com",
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )
    second, _ = invite_member(
        tenant=tenant,
        email="again@example.com",
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )

    first.refresh_from_db()
    assert first.status == Invitation.Status.REVOKED
    assert second.is_pending
    assert list_pending_invitations_for(email="again@example.com") == [second]


def test_pending_invitations_ignore_the_expired_and_the_revoked(
    tenant: Tenant, owner: User
) -> None:
    invitation, _ = invite_member(
        tenant=tenant,
        email="stale@example.com",
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )
    Invitation.objects.filter(pk=invitation.pk).update(expires_at=now())
    assert list_pending_invitations_for(email="stale@example.com") == []

    fresh, _ = invite_member(
        tenant=tenant,
        email="stale@example.com",
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )
    revoke_invitation(tenant=tenant, invitation=fresh, actor=system_actor(tenant=tenant))
    assert list_pending_invitations_for(email="stale@example.com") == []


def test_an_invitation_is_scoped_like_every_other_row(
    tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    # Each tenant's own owner does its own inviting: the escalation wall
    # (house rule 24) refuses a grant into a tenant the granter holds no role
    # in, so a single inviter for both would be proving the wall rather than
    # the scoping this test is about.
    mine, _ = invite_member(
        tenant=tenant,
        email="shared@example.com",
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )
    invite_member(
        tenant=other_tenant,
        email="shared@example.com",
        invited_by=stranger,
        actor=system_actor(tenant=other_tenant),
    )

    assert list(Invitation.objects.for_tenant(tenant)) == [mine]
    assert Invitation.objects.for_tenant(None).count() == 0
    # Two tenants may both have a live invitation for one address — they are
    # different offers, and signing up accepts both.
    assert len(list_pending_invitations_for(email="shared@example.com")) == 2


# --- Acceptance --------------------------------------------------------------


def test_accepting_creates_the_membership_the_invitation_named(tenant: Tenant, owner: User) -> None:
    invitation, _ = invite_member(
        tenant=tenant,
        email="admin-to-be@example.com",
        role=Membership.Role.ADMIN,
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )
    user = create_user(email="admin-to-be@example.com", password=PASSWORD)

    membership = accept_invitation(
        tenant=tenant,
        invitation=invitation,
        user=user,
        actor=actor_for(user=user, tenant=tenant, kind="human"),
    )

    assert membership.role == Membership.Role.ADMIN
    assert membership.is_default is True
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.ACCEPTED
    assert invitation.accepted_at is not None


def test_an_invitation_cannot_be_used_twice(tenant: Tenant, owner: User) -> None:
    invitation, _ = invite_member(
        tenant=tenant, email="once@example.com", invited_by=owner, actor=system_actor(tenant=tenant)
    )
    user = create_user(email="once@example.com", password=PASSWORD)
    accept_invitation(
        tenant=tenant,
        invitation=invitation,
        user=user,
        actor=actor_for(user=user, tenant=tenant, kind="human"),
    )

    with pytest.raises(Conflict):
        accept_invitation(
            tenant=tenant,
            invitation=invitation,
            user=user,
            actor=actor_for(user=user, tenant=tenant, kind="human"),
        )


def test_an_expired_invitation_is_refused(tenant: Tenant, owner: User) -> None:
    invitation, _ = invite_member(
        tenant=tenant, email="late@example.com", invited_by=owner, actor=system_actor(tenant=tenant)
    )
    Invitation.objects.filter(pk=invitation.pk).update(expires_at=now())
    invitation.refresh_from_db()
    user = create_user(email="late@example.com", password=PASSWORD)

    with pytest.raises(Invalid):
        accept_invitation(
            tenant=tenant,
            invitation=invitation,
            user=user,
            actor=actor_for(user=user, tenant=tenant, kind="human"),
        )
    assert not Membership.objects.filter(user=user).exists()


def test_the_second_membership_is_not_the_default(
    tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    first, _ = invite_member(
        tenant=tenant, email="both@example.com", invited_by=owner, actor=system_actor(tenant=tenant)
    )
    second, _ = invite_member(
        tenant=other_tenant,
        email="both@example.com",
        invited_by=stranger,
        actor=system_actor(tenant=other_tenant),
    )
    user = create_user(email="both@example.com", password=PASSWORD)

    accept_invitation(
        tenant=tenant,
        invitation=first,
        user=user,
        actor=actor_for(user=user, tenant=tenant, kind="human"),
    )
    accept_invitation(
        tenant=other_tenant,
        invitation=second,
        user=user,
        actor=actor_for(user=user, tenant=other_tenant, kind="human"),
    )

    assert Membership.objects.filter(user=user, is_default=True).count() == 1
    assert Membership.objects.get(user=user, is_default=True).tenant_id == tenant.pk


# --- Through the door somebody actually arrives at ---------------------------
#
# ADR ident-4 retired the local signup form: `SOCIALACCOUNT_ONLY` removes
# `account_signup` from the urlconf entirely, so the three tests that used to
# post to it could not be re-pointed — the URL they named does not resolve.
#
# The properties did not move, only the door. They are proved end to end in
# `test_rp_login.py`, through the identity provider that now hosts every
# interactive authentication:
#
#   * an invited address lands in the invited tenant at the invited role
#     -> test_an_invited_address_lands_in_the_invited_tenant_at_the_invited_role
#   * an uninvited first login gets an account and no tenant
#     -> test_an_uninvited_first_login_gets_an_account_and_no_tenant
#   * an invitation that lapsed in between is not a refusal
#     -> test_an_expired_invitation_still_lets_the_person_in
#
# They are named here rather than duplicated, because two copies of one property
# is how the two copies come to disagree. What stays in this module is
# everything above: the invitation rows, their scoping, and `accept_invitation`
# itself — none of which cares which door the person came through.
