"""The archive adoption's own test — copied with the adoption, and green on the copy."""

# golden: archive begin
import json
from typing import Any

import pytest
from django.test import Client

from apps.example.models import Widget
from apps.example.services import archive_widget, restore_widget
from pilecap import Actor, Forbidden
from pilecap.accounts import User
from pilecap.tenancy import Organization, Tenant
from pilecap.testing import system_actor

pytestmark = pytest.mark.django_db

WIDGETS_URL = "/api/v1/widgets/"


def _items(response: Any) -> list[str]:
    assert response.status_code == 200, response.content
    return [row["id"] for row in json.loads(response.content)["items"]]


def test_an_admin_archives_and_restores_a_widget(
    tenant: Tenant, root_org: Organization, admin_actor: Actor, owner: User
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")

    archived = archive_widget(tenant=tenant, actor=admin_actor, widget=widget)
    assert archived.archived_at is not None
    assert not Widget.objects.for_tenant(tenant).filter(pk=widget.pk).exists()
    assert Widget.objects.for_tenant(tenant).archived_only().filter(pk=widget.pk).exists()
    again = archive_widget(tenant=tenant, actor=admin_actor, widget=archived)
    assert again.archived_at == archived.archived_at

    restored = restore_widget(tenant=tenant, actor=admin_actor, widget=again)
    assert restored.archived_at is None
    assert Widget.objects.for_tenant(tenant).filter(pk=widget.pk).exists()


def test_a_member_and_the_system_may_not_archive(
    tenant: Tenant, root_org: Organization, member_actor: Actor, owner: User
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")
    with pytest.raises(Forbidden):
        archive_widget(tenant=tenant, actor=member_actor, widget=widget)
    with pytest.raises(Forbidden):
        archive_widget(
            tenant=tenant, actor=system_actor(tenant=tenant, org=root_org), widget=widget
        )


def test_the_rest_door_archives_and_the_list_shows_the_cut(
    api: Client, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")
    api.force_login(owner)

    archived = api.post(f"{WIDGETS_URL}{widget.pk}/archive/")
    assert archived.status_code == 200, archived.content
    assert json.loads(archived.content)["archived_at"] is not None
    assert _items(api.get(WIDGETS_URL)) == []
    assert _items(api.get(f"{WIDGETS_URL}?show=archived")) == [str(widget.pk)]
    assert _items(api.get(f"{WIDGETS_URL}?show=all")) == [str(widget.pk)]
    assert api.get(f"{WIDGETS_URL}{widget.pk}/").status_code == 200

    restored = api.post(f"{WIDGETS_URL}{widget.pk}/restore/")
    assert restored.status_code == 200, restored.content
    assert _items(api.get(WIDGETS_URL)) == [str(widget.pk)]


def test_the_row_says_what_this_viewer_may_press(
    api: Client,
    tenant: Tenant,
    root_org: Organization,
    owner: User,
    admin_member: User,
    member: User,
) -> None:
    """`allowed_acts` is per viewer: an administrator is offered archive, a member is not."""
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")

    api.force_login(admin_member)
    as_admin = api.get(f"{WIDGETS_URL}{widget.pk}/")
    assert as_admin.status_code == 200, as_admin.content
    assert "archive" in json.loads(as_admin.content)["allowed_acts"]

    api.force_login(member)
    as_member = api.get(f"{WIDGETS_URL}{widget.pk}/")
    assert as_member.status_code == 200, as_member.content
    assert "archive" not in json.loads(as_member.content)["allowed_acts"]


# golden: archive end
