"""The admin changelist over the run ledger, and the platform population.

ADR workflows-3 claims the null-tenant population is invisible to every tenant
door **by construction** — because `ServiceModelAdmin.get_queryset` narrows
through `for_tenant`, and `for_tenant` can never match a null. A claim about
construction still has to be driven once through the real door, because the
next person to write a `get_queryset` on this model is the person the claim is
about.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import system_actor
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership
from apps.workflows.services import record_run, workflow_id

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret
LIST_URL = "/admin/workflows/workflowrun/"
PLATFORM_RUN_ID = "platform:accounts:identity:workforce"


@pytest.fixture
def staff_owner(tenant: Tenant) -> User:
    """A staff superuser who owns the tenant they act in — the widest hat there is."""
    user = create_user(email="staff-runs@example.com", password=PASSWORD, is_staff=True)
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


def test_the_changelist_shows_the_tenants_runs_and_never_the_platforms(
    tenant: Tenant, staff_owner: User, api: Client
) -> None:
    """One GET, the widest hat in the product, and the platform row is not there."""
    mine = record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="workflows", noun="echo", key="visible"),
        workflow_type="EchoWorkflow",
        actor=system_actor(tenant),
    )
    record_run(
        tenant=None,
        workflow_id=PLATFORM_RUN_ID,
        workflow_type="EchoWorkflow",
        actor=system_actor(None),
    )

    api.force_login(staff_owner)
    response = api.get(LIST_URL)

    assert response.status_code == 200
    body = response.content.decode()
    assert mine.workflow_id in body
    assert PLATFORM_RUN_ID not in body
