"""The operator trio's door: `TenantAdmin`'s suspend, resume and close actions, over the admin."""

from __future__ import annotations

from typing import Any

import pytest
from django.contrib.admin import helpers
from django.contrib.messages import get_messages
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import system_actor
from apps.core.audit import AuditEntry
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret
CHANGELIST = "/admin/core/tenant/"


@pytest.fixture
def operator(tenant: Tenant, owner: User) -> User:
    """A staff superuser with a membership, so the admin resolves a person to act as."""
    user = create_user(email="operator@example.com", password=PASSWORD, is_staff=True)
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


def press(api: Client, action: str, tenant: Tenant) -> Any:
    return api.post(
        CHANGELIST,
        data={"action": action, "index": "0", helpers.ACTION_CHECKBOX_NAME: [str(tenant.pk)]},
        follow=True,
    )


def said(response: Any) -> list[str]:
    return [str(message) for message in get_messages(response.wsgi_request)]


def test_the_three_actions_walk_a_tenant_through_its_lifecycle(
    api: Client, tenant: Tenant, operator: User
) -> None:
    """Suspend, resume, then close: each through its service, each an audited admin write."""
    api.force_login(operator)

    assert said(press(api, "suspend_selected", tenant)) == ["1 tenant(s) suspended."]
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.SUSPENDED
    assert tenant.suspended_at is not None

    assert said(press(api, "resume_selected", tenant)) == ["1 tenant(s) resumed."]
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.ACTIVE

    assert said(press(api, "close_selected", tenant)) == ["1 tenant(s) closed."]
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.CLOSED

    rows = AuditEntry.objects.for_tenant(tenant).filter(
        action__in=["core.suspend_tenant", "core.resume_tenant", "core.close_tenant"]
    )
    assert sorted(rows.values_list("action", "door", "actor_user_id")) == sorted(
        (f"core.{verb}_tenant", "admin", operator.pk) for verb in ("suspend", "resume", "close")
    )


def test_a_closed_tenant_is_refused_resumption_on_the_screen(
    api: Client, tenant: Tenant, operator: User
) -> None:
    """The service's `conflict` reaches the operator as a message, with nothing changed."""
    api.force_login(operator)
    press(api, "close_selected", tenant)

    response = press(api, "resume_selected", tenant)

    assert response.status_code == 200
    assert any("closed tenant is not resumed" in line for line in said(response))
    tenant.refresh_from_db()
    assert tenant.status == Tenant.Status.CLOSED
