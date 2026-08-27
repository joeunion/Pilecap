"""The admin is a door, and a door calls services.

Driven through the real admin URLs with a real staff session, because the whole
claim is about what happens when a support agent clicks Save — not about what
`WidgetAdmin.save_model` does when called directly.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership, root_organization
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = pytest.mark.django_db

ADD_URL = "/admin/example/widget/add/"
LIST_URL = "/admin/example/widget/"
PASSWORD = "a-long-enough-password"  # pragma: allowlist secret


@pytest.fixture
def staff(tenant: Tenant) -> User:
    """A staff member who is also an owner of the tenant they act in.

    Both halves are needed and that is the point: `is_staff` opens the admin,
    and the membership is what authorizes the write. Staff status alone is not
    a way past the tenancy.
    """
    user = create_user(email="staff@example.com", password=PASSWORD, is_staff=True)
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


def staff_actor(user: User, tenant: Tenant) -> Actor:
    """The staff member acting under the tenant's root hat, as the admin door
    would resolve it from their default membership."""
    return actor_for(user=user, tenant=tenant, org=root_organization(tenant=tenant))


def test_saving_through_the_admin_writes_an_audit_row_saying_admin(
    api: Client, staff: User, tenant: Tenant
) -> None:
    api.force_login(staff)
    AuditEntry.objects.all().delete()

    response = api.post(ADD_URL, data={"name": "From the admin", "notes": "typed by a human"})
    assert response.status_code == 302, response.content

    widget = Widget.objects.for_tenant(tenant).get(name="From the admin")
    entry = AuditEntry.objects.for_tenant(tenant).get(action="example.create_widget")
    assert entry.door == "admin"
    assert entry.actor_user_id == staff.pk
    assert entry.actor_kind == "human"
    assert entry.object_id == widget.pk
    assert entry.outcome == AuditEntry.Outcome.OK


def test_the_admin_sets_the_tenant_from_who_is_acting_not_from_the_form(
    api: Client, staff: User, tenant: Tenant, other_tenant: Tenant
) -> None:
    """The one door that could write into a tenant it is not acting in — closed."""
    api.force_login(staff)
    api.post(ADD_URL, data={"name": "Placed", "notes": ""})

    widget = Widget.objects.get(name="Placed")
    assert widget.tenant_id == tenant.pk
    assert widget.owner_id == staff.pk


def test_the_admin_list_is_scoped_to_the_acting_tenant(
    api: Client, staff: User, tenant: Tenant, other_tenant: Tenant, stranger_actor: Actor
) -> None:
    mine = create_widget(tenant=tenant, actor=staff_actor(staff, tenant), name="Mine")
    theirs = create_widget(tenant=other_tenant, actor=stranger_actor, name="Theirs")

    api.force_login(staff)
    page = api.get(LIST_URL).content.decode()
    assert "Mine" in page
    assert "Theirs" not in page
    assert str(mine.pk) in page or "Mine" in page
    assert str(theirs.pk) not in page


def test_editing_through_the_admin_goes_through_the_service(
    api: Client, staff: User, tenant: Tenant
) -> None:
    widget = create_widget(tenant=tenant, actor=staff_actor(staff, tenant), name="Before")
    AuditEntry.objects.all().delete()
    api.force_login(staff)

    response = api.post(
        f"{LIST_URL}{widget.pk}/change/",
        data={"name": "After", "notes": ""},
    )
    assert response.status_code == 302, response.content

    widget.refresh_from_db()
    assert widget.name == "After"
    entry = AuditEntry.objects.for_tenant(tenant).get(action="example.update_widget")
    assert entry.door == "admin"


def test_the_audit_admin_offers_no_way_to_change_anything(
    api: Client, staff: User, tenant: Tenant
) -> None:
    create_widget(tenant=tenant, actor=staff_actor(staff, tenant), name="Audited")
    entry = AuditEntry.objects.for_tenant(tenant).first()
    assert entry is not None

    api.force_login(staff)
    assert api.get("/admin/core/auditentry/").status_code == 200
    assert api.get("/admin/core/auditentry/add/").status_code in (403, 302)

    change: Any = api.get(f"/admin/core/auditentry/{entry.pk}/change/")
    # Django serves a read-only "view" page rather than a form.
    assert change.status_code == 200
    assert "_save" not in change.content.decode()
