# golden: policy begin
"""A widget whose policy is archived stays out of the book until the policy returns."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.example.models import Widget, WidgetPolicy
from apps.example.services import (
    archive_widget_policy,
    create_widget,
    create_widget_policy,
    restore_widget_policy,
)
from pilecap import Actor
from pilecap.accounts import User
from pilecap.tenancy import Organization, Tenant
from pilecap.testing import actor_for

pytestmark = pytest.mark.django_db

WIDGETS = "/api/v1/widgets/"


def body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def fresh(widget: Widget) -> Widget:
    return Widget.objects.for_tenant(widget.tenant).including_archived().get(pk=widget.pk)


def restored_events(tenant: Tenant) -> int:
    from django.apps import apps as django_apps

    event = django_apps.get_model("events", "Event")
    return int(event.objects.filter(tenant=tenant, name="example.widget.restored").count())


def test_a_widget_whose_policy_is_archived_is_restore_blocked(
    api: Client, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    owner_at_root: Actor = actor_for(user=owner, tenant=tenant, org=root_org)
    policy = create_widget_policy(tenant=tenant, actor=owner_at_root, name="Terms")
    widget = create_widget(tenant=tenant, actor=owner_at_root, name="Governed", policy=policy)
    api.force_login(owner)
    assert api.post(f"{WIDGETS}{widget.pk}/archive/").status_code == 200
    archive_widget_policy(tenant=tenant, actor=owner_at_root, policy=policy)
    before = fresh(widget)
    said = restored_events(tenant)

    refused = api.post(f"{WIDGETS}{widget.pk}/restore/")

    assert refused.status_code == 409, refused.content
    answered = body(refused)
    assert answered["code"] == "restore_blocked"
    assert answered["blocking"][0]["noun"] == "widget_policy"
    assert answered["blocking"][0]["door"] == f"route:widget_policy-restore?policy_id={policy.pk}"
    after = fresh(widget)
    assert (after.archived_at, after.updated_at) == (before.archived_at, before.updated_at)
    assert restored_events(tenant) == said

    restore_widget_policy(
        tenant=tenant,
        actor=owner_at_root,
        policy=WidgetPolicy.objects.for_tenant(tenant).including_archived().get(pk=policy.pk),
    )
    assert api.post(f"{WIDGETS}{widget.pk}/restore/").status_code == 200


# golden: policy end
