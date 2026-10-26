"""The staff door onto a person opens, or it says why — never a traceback.

`/admin/accounts/user/add/` used to return a 500. The cause is the interaction
between Django 5.x's `UserAdmin.add_fieldsets` (which grew a `usable_password`
field) and this repository's own `fieldsets`/`add_fieldsets` pair — see
`apps/accounts/admin.py` for the fix and the reason.

The doctrinal position of this module, stated once: it asserts that the door
*answers*. A later ruling may narrow or remove the local add-person door in favour
of `invite_member`; this module is written so that a working door and a
deliberate refusal both pass, and only a traceback fails.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.admin import ServiceModelAdmin
from apps.core.models import Tenant

ADD_URL = "/admin/accounts/user/add/"


@pytest.fixture
def staff(tenant: Tenant) -> User:
    """A staff member who can reach every user page in the admin.

    Built through the manager rather than `create_user` because staff-ness and
    the admin permission set are exactly what this fixture is for, and the
    service deliberately does not take them.
    """
    person = User.objects.create_superuser(
        email="staff@example.com",
        password="a-long-enough-password",  # noqa: S106 — a throwaway password a test user is made with  # pragma: allowlist secret
    )
    from apps.core.actor import system_actor
    from apps.core.models import Membership
    from apps.core.services import add_membership

    add_membership(
        user=person,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=tenant),
    )
    return person


@pytest.fixture
def staff_client(api: Client, staff: User) -> Client:
    api.force_login(staff)
    return api


@pytest.mark.django_db
def test_the_add_person_form_renders(staff_client: Client) -> None:
    """A repro: this GET used to raise, not render.

    A 500 is the one answer excluded. A 200 (the door works) and a 403 (a
    later ruling closed it) are both accepted here on purpose — see the module
    docstring.
    """
    response = staff_client.get(ADD_URL)

    assert response.status_code != 500, "the add-person form raised"
    assert response.status_code in {200, 403}


@pytest.mark.django_db
def test_the_add_person_form_creates_a_person(staff_client: Client) -> None:
    """POST reaches the model, or refuses in a way that names the other door."""
    response = staff_client.post(
        ADD_URL,
        {
            "email": "newcomer@example.com",
            "usable_password": "true",  # a form flag, not a credential  # pragma: allowlist secret
            "password1": "a-long-enough-password",  # pragma: allowlist secret
            "password2": "a-long-enough-password",  # pragma: allowlist secret
        },
    )

    assert response.status_code != 500, "the add-person POST raised"
    if response.status_code == 403:
        # The door was deliberately closed; the refusal must name the way in.
        assert b"invite_member" in response.content
        return
    assert response.status_code == 302, response.content[:400]
    created = User.objects.get(email="newcomer@example.com")
    assert created.has_usable_password()
    assert created.check_password("a-long-enough-password")


@pytest.mark.django_db
def test_the_add_person_form_can_defer_the_password(staff_client: Client) -> None:
    """`usable_password` off is Django 5.1's flow, and it is the one that broke.

    The add form must reach the model with no password set — the person is then
    expected to arrive through the identity platform, which is exactly the case
    that ruling is about.
    """
    response = staff_client.post(
        ADD_URL,
        # the flag below is a form control, not a credential
        {"email": "deferred@example.com", "usable_password": "false"},  # pragma: allowlist secret
    )

    assert response.status_code != 500, "the deferred-password POST raised"
    if response.status_code == 403:
        assert b"invite_member" in response.content
        return
    assert response.status_code == 302, response.content[:400]
    created = User.objects.get(email="deferred@example.com")
    assert not created.has_usable_password()


@pytest.mark.django_db
def test_the_change_person_form_still_renders(staff_client: Client, owner: User) -> None:
    """The sibling the fix must not break: `fieldsets` are the change form's."""
    response = staff_client.get(f"/admin/accounts/user/{owner.pk}/change/")

    assert response.status_code == 200


def test_the_user_admin_is_service_based() -> None:
    """House rule 21, restated at the one admin this fix touched.

    `core/tests/test_admin.py` proves it over the whole registry; this asserts
    it here too, so a fix that "solved" the 500 by swapping the base class out
    fails in the module that changed it.
    """
    from django.contrib import admin

    assert isinstance(admin.site._registry[User], ServiceModelAdmin)
