"""The admin door and the escalation wall, and what happens when nothing wires them.

**A foundation-review finding.** `MembershipAdmin` inherited
`ServiceModelAdmin` and declared no `service_for`, so every membership written
from `/admin/core/membership/` fell through to `obj.save()`: the escalation wall
never ran and no `AuditEntry` was written. "Who made them an owner, and when" —
the question `set_role`'s docstring opens with — had no answer for the one door
a support agent actually uses.

Three properties, and they are one mechanism:

* **C2** — membership creates go through `core.services.add_membership` and role
  edits through `set_role`, with the request's user as the granting actor;
* **C3** — a `service_for` that returns `None` on a model the tenancy or the
  wall guards is a **refusal**, not a silent fallthrough. A model that is
  neither keeps the ordinary Django behaviour, which `UserAdmin` depends on;
* **C4** — an append-only model's admin offers no change and no delete, read off
  the declaration rather than remembered per subclass.

Driven through the real admin URLs with a real staff session wherever the claim
is about clicking Save, following `apps/example/tests/test_admin.py`.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib import admin
from django.contrib.messages import get_messages
from django.core.exceptions import ImproperlyConfigured
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, system_actor
from apps.core.admin import ServiceModelAdmin
from apps.core.audit import AuditEntry
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret
ADD_URL = "/admin/core/membership/add/"
LIST_URL = "/admin/core/membership/"


@pytest.fixture
def staff_owner(tenant: Tenant) -> User:
    """A staff member who owns the tenant they act in — the top of the ceiling."""
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
def staff_admin(tenant: Tenant, owner: User) -> User:
    """A staff member who is only an `admin` of the tenant.

    `owner` is asked for first so the tenant's *first* membership is its owner
    and this one really does come out an admin — the trap
    `apps/conftest.py`'s `owner` docstring names.
    """
    user = create_user(email="staff-admin@example.com", password=PASSWORD, is_staff=True)
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def newcomer(db: None) -> User:
    """Somebody with no membership anywhere, waiting to be given one."""
    return create_user(email="newcomer@example.com", password=PASSWORD)


def _refusals(response: Any) -> list[str]:
    """The refusal lines the door rendered for this request.

    **Re-pointed here.** These three tests asserted
    `pytest.raises(Forbidden)` through `api.post`, which pinned the *escape* of
    a refusal out of `changeform_view` — a 500 — as the wall's proof. The wall
    is unchanged and the property each test states is unchanged; what moved is
    where the refusal is read, from the traceback to the page a support agent
    is looking at. `ServiceModelAdmin` maps it through `wire_refusal`, so the
    `code` leads exactly as it does on REST and MCP.
    """
    return [str(message) for message in get_messages(response.wsgi_request)]


def _membership_form(
    *, user: User, tenant: Tenant, organization: Organization, role: str
) -> dict[str, Any]:
    return {
        "user": str(user.pk),
        "tenant": str(tenant.pk),
        "organization": str(organization.pk),
        "role": role,
    }


# --- C2: the admin door calls the services that hold the wall ----------------


def test_creating_a_membership_through_the_admin_is_audited_as_the_admin_door(
    api: Client, staff_owner: User, newcomer: User, tenant: Tenant
) -> None:
    """The write lands, through `add_membership`, with a row saying where from."""
    api.force_login(staff_owner)
    AuditEntry.objects.all().delete()

    response = api.post(
        ADD_URL,
        data=_membership_form(
            user=newcomer,
            tenant=tenant,
            organization=root_organization(tenant=tenant),
            role=Membership.Role.MEMBER,
        ),
    )
    assert response.status_code == 302, response.content

    membership = Membership.objects.get(user_id=newcomer.pk, tenant=tenant)
    assert membership.role == Membership.Role.MEMBER
    entry = AuditEntry.objects.for_tenant(tenant).get(action="core.add_membership")
    assert entry.door == "admin"
    assert entry.actor_user_id == staff_owner.pk
    assert entry.actor_kind == "human"
    assert entry.object_id == membership.pk


def test_an_admin_may_not_mint_an_owner_through_the_admin_door(
    api: Client, staff_admin: User, newcomer: User, tenant: Tenant
) -> None:
    """The reviewer's `save_model` scenario. The wall is the same wall.

    A staff member who is only an `admin` of this tenant may not grant `owner`
    here any more than they may through the API. It is refused as `forbidden` —
    said out loud on the page, and with no row written.
    """
    api.force_login(staff_admin)

    response = api.post(
        ADD_URL,
        data=_membership_form(
            user=newcomer,
            tenant=tenant,
            organization=root_organization(tenant=tenant),
            role=Membership.Role.OWNER,
        ),
        follow=True,
    )

    assert response.status_code == 200, response.content
    assert any("forbidden" in line for line in _refusals(response)), _refusals(response)
    assert not Membership.objects.filter(user_id=newcomer.pk, tenant=tenant).exists()


def test_a_role_edit_through_the_admin_goes_through_set_role(
    api: Client, staff_owner: User, member: User, tenant: Tenant
) -> None:
    """Changing a role on the change form is `set_role`, audited, door=admin."""
    membership = Membership.objects.get(user_id=member.pk, tenant=tenant)
    api.force_login(staff_owner)
    AuditEntry.objects.all().delete()

    response = api.post(
        f"{LIST_URL}{membership.pk}/change/",
        data={"role": Membership.Role.ADMIN},
    )
    assert response.status_code == 302, response.content

    membership.refresh_from_db()
    assert membership.role == Membership.Role.ADMIN
    entry = AuditEntry.objects.for_tenant(tenant).get(action="core.set_role")
    assert entry.door == "admin"
    assert entry.actor_user_id == staff_owner.pk


def test_a_role_edit_above_the_editors_ceiling_is_refused(
    api: Client, staff_admin: User, member: User, tenant: Tenant
) -> None:
    membership = Membership.objects.get(user_id=member.pk, tenant=tenant)
    api.force_login(staff_admin)

    response = api.post(
        f"{LIST_URL}{membership.pk}/change/",
        data={"role": Membership.Role.OWNER},
        follow=True,
    )

    assert response.status_code == 200, response.content
    assert any("forbidden" in line for line in _refusals(response)), _refusals(response)
    membership.refresh_from_db()
    assert membership.role == Membership.Role.MEMBER


def test_a_branch_admin_cannot_grant_into_a_branch_beside_their_own(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor, newcomer: User
) -> None:
    """The wall's *other* refusal, through the admin door: outside your subtree."""
    left = create_organization(
        tenant=tenant,
        parent=root_organization(tenant=tenant),
        name="Left",
        slug="left",
        actor=owner_actor,
    )
    right = create_organization(
        tenant=tenant,
        parent=root_organization(tenant=tenant),
        name="Right",
        slug="right",
        actor=owner_actor,
    )
    staff = create_user(email="left-admin@example.com", password=PASSWORD, is_staff=True)
    staff.is_superuser = True
    staff.save(update_fields=["is_superuser"])
    add_membership(
        user=staff,
        tenant=tenant,
        organization=left,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=owner_actor,
    )
    api.force_login(staff)

    response = api.post(
        ADD_URL,
        data=_membership_form(
            user=newcomer, tenant=tenant, organization=right, role=Membership.Role.MEMBER
        ),
        follow=True,
    )

    assert response.status_code == 200, response.content
    assert any("forbidden" in line for line in _refusals(response)), _refusals(response)
    assert not Membership.objects.filter(user_id=newcomer.pk, organization=right).exists()


# --- C3: an unwired service on a guarded model refuses, loudly ---------------


def _request(user: User | None = None) -> Any:
    request = RequestFactory().post("/admin/")
    request.user = user  # type: ignore[assignment]
    return request


def test_an_unwired_write_on_a_wall_guarded_model_refuses(
    tenant: Tenant, owner: User, newcomer: User
) -> None:
    """`service_for` returning `None` on `Membership` is a refusal, not a save.

    This is the shape the original gap actually was: nothing was wired, and Django's
    default quietly took over. A bare `ServiceModelAdmin` stands in for the next
    subclass somebody writes without reading the docstring.
    """
    unwired = ServiceModelAdmin(Membership, admin.site)
    row = Membership(
        user=newcomer,
        tenant=tenant,
        organization=root_organization(tenant=tenant),
        role=Membership.Role.OWNER,
    )

    with pytest.raises(ImproperlyConfigured) as refused:
        unwired.save_model(_request(owner), row, form=None, change=False)  # type: ignore[arg-type]

    assert "service_for" in str(refused.value)
    assert "Membership" in str(refused.value)
    assert not Membership.objects.filter(user_id=newcomer.pk).exists()


def test_an_unwired_delete_on_a_tenant_scoped_model_refuses(
    tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """The delete half, on a model the tenancy guards."""
    node = create_organization(
        tenant=tenant,
        parent=root_organization(tenant=tenant),
        name="Doomed",
        slug="doomed",
        actor=owner_actor,
    )
    unwired = ServiceModelAdmin(Organization, admin.site)

    with pytest.raises(ImproperlyConfigured):
        unwired.delete_model(_request(owner), node)

    assert Organization.objects.for_tenant(tenant).filter(pk=node.pk).exists()


def test_an_unguarded_model_keeps_the_ordinary_django_fallthrough(
    tenant: Tenant, owner: User
) -> None:
    """The other branch, and it is load-bearing.

    `UserAdmin` returns `None` from `service_for` on purpose — taking the add
    form over would mean taking password validation over too. `User` is neither
    tenant-scoped nor wall-guarded, so it keeps Django's behaviour and the
    admin still works.
    """
    unwired = ServiceModelAdmin(User, admin.site)
    row = User(email="fallthrough@example.com")

    unwired.save_model(_request(owner), row, form=None, change=False)  # type: ignore[arg-type]

    assert User.objects.filter(email="fallthrough@example.com").exists()


# --- C4: append-only is unchangeable from the admin, by construction ---------


def test_an_append_only_models_admin_offers_no_change_and_no_delete(root: User) -> None:
    """Read off `append_only = True`, not off which base class was chosen.

    `AuditEntryAdmin` is a `ReadOnlyModelAdmin` today and could stop being one
    tomorrow; the declaration is what the answer comes from.

    **A superuser asks**, which is what makes this able to fail: Django refuses
    everybody without the model permission, so a plain user would have proved
    nothing at all.
    """
    plain = ServiceModelAdmin(AuditEntry, admin.site)
    request = _request(root)

    assert plain.has_change_permission(request) is False
    assert plain.has_delete_permission(request) is False


def test_a_model_that_is_not_append_only_keeps_its_permissions(root: User) -> None:
    """The sibling that makes the assertion above able to fail, with the read granted."""
    plain = ServiceModelAdmin(Tenant, admin.site)
    plain.has_view_permission = lambda request, obj=None: True  # type: ignore[method-assign]
    request = _request(root)

    assert plain.has_change_permission(request) is True
    assert plain.has_delete_permission(request) is True


def test_a_subclass_may_still_override_the_append_only_refusal(root: User) -> None:
    """Overriding takes a conscious subclass, which is the whole ask."""

    class Deliberate(ServiceModelAdmin[AuditEntry]):
        def has_change_permission(self, request: Any, obj: Any = None) -> bool:
            return True

    assert Deliberate(AuditEntry, admin.site).has_change_permission(_request(root)) is True


def test_the_registered_audit_admin_still_refuses_everything(root: User) -> None:
    """C4 must not change the answer the existing admin already gives."""
    registered = admin.site._registry[AuditEntry]
    request = _request(root)

    assert registered.has_add_permission(request) is False
    assert registered.has_change_permission(request) is False
    assert registered.has_delete_permission(request) is False
