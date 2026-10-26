"""A suspended tenant's invitation lands no membership, and one token lands one."""

from __future__ import annotations

import threading

import pytest
from django.db import connection

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import Conflict, DomainError
from apps.core.models import Invitation, Membership, Tenant
from apps.core.selectors import list_pending_invitations_for
from apps.core.services import accept_invitation, invite_member, resume_tenant, suspend_tenant

EMAIL = "invited@example.com"
PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret


def _invite(tenant: Tenant, owner_actor: Actor) -> Invitation:
    invitation, _token = invite_member(
        tenant=tenant, email=EMAIL, invited_by=owner_actor.user, actor=owner_actor
    )
    return invitation


@pytest.mark.django_db
def test_a_suspended_tenants_invitation_is_absent_from_the_sign_in_read(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """Sign-in's list names no invitation of a suspended tenant, and names it again on resume."""
    invitation = _invite(tenant, owner_actor)
    assert [row.pk for row in list_pending_invitations_for(email=EMAIL)] == [invitation.pk]

    suspend_tenant(tenant=tenant, actor=owner_actor)
    assert list_pending_invitations_for(email=EMAIL) == []

    resume_tenant(tenant=tenant, actor=owner_actor)
    assert [row.pk for row in list_pending_invitations_for(email=EMAIL)] == [invitation.pk]


@pytest.mark.django_db
def test_accepting_a_suspended_tenants_invitation_is_refused_and_writes_nothing(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The service refuses in words before `add_membership`; the tree is as it was."""
    invitation = _invite(tenant, owner_actor)
    suspend_tenant(tenant=tenant, actor=owner_actor)
    person = create_user(email=EMAIL, password=PASSWORD)
    memberships_before = Membership.objects.count()

    with pytest.raises(Conflict) as refused:
        accept_invitation(
            tenant=tenant,
            invitation=invitation,
            user=person,
            actor=actor_for(user=person, tenant=tenant, kind="human"),
        )

    assert "suspended" in str(refused.value.detail)
    assert Membership.objects.count() == memberships_before
    assert not Membership.objects.filter(user=person).exists()
    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.PENDING


@pytest.mark.django_db(transaction=True)
def test_two_concurrent_acceptances_of_one_invitation_land_one_membership(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """Under real concurrency: `select_for_update` on the invitation row.

    The shape is `apps/files/tests/test_services.py::
    test_two_concurrent_replaces_get_two_ordinals_and_never_one_twice` — real
    threads behind a barrier, each on its own connection. Two different people
    hold the one token, so the membership unique constraint cannot stand in for
    the lock: without it both pass `is_pending` and both land.
    """
    invitation = _invite(tenant, owner_actor)
    racers_people: list[User] = [
        create_user(email=f"racer-{n}@example.com", password=PASSWORD) for n in range(2)
    ]
    both_at_the_door = threading.Barrier(2, timeout=30)
    landed: list[Membership] = []
    refused: list[DomainError] = []
    broke: list[BaseException] = []

    def accept(person: User) -> None:
        try:
            own = Invitation.objects.select_related("tenant").get(pk=invitation.pk)
            both_at_the_door.wait()
            landed.append(
                accept_invitation(
                    tenant=own.tenant,
                    invitation=own,
                    user=person,
                    actor=actor_for(user=person, tenant=own.tenant, kind="human"),
                )
            )
        except DomainError as refusal:
            refused.append(refusal)
        except BaseException as failure:  # noqa: BLE001 - reported, not swallowed
            broke.append(failure)
        finally:
            connection.close()

    racers = [threading.Thread(target=accept, args=(person,)) for person in racers_people]
    for racer in racers:
        racer.start()
    for racer in racers:
        racer.join(timeout=30)

    assert broke == []
    assert len(landed) == 1, landed
    assert [type(refusal) for refusal in refused] == [Conflict]
    assert Membership.objects.filter(user__in=racers_people).count() == 1
