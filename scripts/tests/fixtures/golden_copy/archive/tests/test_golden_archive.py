"""The self-case's test block: the copied test that proves the road on the copy."""

# golden: archive begin
import json

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.exceptions import Forbidden
from apps.core.models import Organization, Tenant
from apps.example.models import Widget
from apps.example.services import archive_widget, restore_widget

pytestmark = pytest.mark.django_db


def test_an_admin_archives_and_restores_a_widget(
    tenant: Tenant, root_org: Organization, admin_actor: Actor
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, name="w")

    archived = archive_widget(tenant=tenant, actor=admin_actor, widget=widget)
    assert archived.archived_at is not None
    assert not Widget.objects.for_tenant(tenant).filter(pk=widget.pk).exists()
    assert Widget.objects.for_tenant(tenant).archived_only().filter(pk=widget.pk).exists()
    again = archive_widget(tenant=tenant, actor=admin_actor, widget=archived)
    assert again.archived_at == archived.archived_at

    restored = restore_widget(tenant=tenant, actor=admin_actor, widget=archived)
    assert restored.archived_at is None
    assert Widget.objects.for_tenant(tenant).filter(pk=widget.pk).exists()


def test_a_member_may_not_archive(
    tenant: Tenant, root_org: Organization, member_actor: Actor
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, name="w")
    with pytest.raises(Forbidden):
        archive_widget(tenant=tenant, actor=member_actor, widget=widget)


def test_the_rest_door_archives_and_the_list_shows_the_cut(
    api: Client, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, name="w")
    api.force_login(owner)

    archived = api.post(f"/api/v1/widgets/{widget.pk}/archive/")
    assert archived.status_code == 200, archived.content
    assert json.loads(archived.content)["archived_at"] is not None
    live = json.loads(api.get("/api/v1/widgets/").content)["items"]
    assert [row["id"] for row in live] == []
    cut = json.loads(api.get("/api/v1/widgets/?show=archived").content)["items"]
    assert [row["id"] for row in cut] == [str(widget.pk)]
    detail = api.get(f"/api/v1/widgets/{widget.pk}/")
    assert detail.status_code == 200


# golden: archive end
