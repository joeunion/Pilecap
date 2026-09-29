"""The move adoption's own test — copied with the adoption, and green on the copy.

Every line is fenced `golden: move`: a move into a branch, the same node
answering unchanged, a ledger line holding the widget where it is, and a member
refused. Rows and ledger lines are made by hand — the noun's create and its
ledger's recording are the product's own business.
"""

# golden: move begin
import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.actor import actor_for
from apps.core.models import Organization, Tenant
from apps.core.services import create_organization
from apps.example.models import Widget, WidgetEntry

pytestmark = pytest.mark.django_db

WIDGETS_URL = "/api/v1/widgets/"
JSON = "application/json"


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


@pytest.fixture
def branch(tenant: Tenant, root_org: Organization, owner: User) -> Organization:
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    return create_organization(
        tenant=tenant, parent=root_org, name="Branch", slug="branch", actor=acting
    )


def _move(api: Client, widget: Widget, to: Organization) -> Any:
    widget.refresh_from_db()
    return api.post(
        f"{WIDGETS_URL}{widget.pk}/move/",
        {"organization_id": str(to.pk), "version": widget.version},
        content_type=JSON,
    )


def test_a_widget_moves_into_a_branch_and_the_same_node_is_unchanged(
    api: Client, tenant: Tenant, root_org: Organization, branch: Organization, owner: User
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")
    api.force_login(owner)

    moved = _move(api, widget, branch)
    assert moved.status_code == 200, moved.content
    assert _body(moved)["organization_id"] == str(branch.pk)
    assert _body(moved)["organization_name"] == "Branch"

    again = _move(api, widget, branch)
    assert again.status_code == 200, again.content
    assert _body(again)["version"] == _body(moved)["version"]


def test_a_ledger_line_holds_the_widget_where_it_is(
    api: Client, tenant: Tenant, root_org: Organization, branch: Organization, owner: User
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")
    WidgetEntry.objects.create(tenant=tenant, organization=root_org, widget=widget, note="here")
    api.force_login(owner)

    refused = _move(api, widget, branch)
    assert refused.status_code == 409, refused.content
    assert _body(refused)["code"] == "move_blocked"
    widget.refresh_from_db()
    assert widget.organization_id == root_org.pk


def test_a_member_may_not_move(
    api: Client,
    tenant: Tenant,
    root_org: Organization,
    branch: Organization,
    owner: User,
    member: User,
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")
    api.force_login(member)

    refused = _move(api, widget, branch)
    assert refused.status_code == 403, refused.content
    widget.refresh_from_db()
    assert widget.organization_id == root_org.pk


# golden: move end
