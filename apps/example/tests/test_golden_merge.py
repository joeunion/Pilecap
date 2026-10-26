"""The merge adoption's own test — copied with the adoption, and green on the copy."""

# golden: merge begin
import json
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.test import Client

from apps.example.models import Widget, WidgetEntry
from pilecap.accounts import User
from pilecap.tenancy import Organization, Tenant

pytestmark = pytest.mark.django_db

WIDGETS_URL = "/api/v1/widgets/"
JSON = "application/json"


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def _merged(tenant: Tenant) -> list[dict[str, Any]]:
    event = django_apps.get_model("events", "Event")
    rows = event.objects.filter(tenant=tenant, name="example.widget.merged")
    return [dict(row.payload) for row in rows]


def _merge(api: Client, loser: Widget, survivor: Widget) -> Any:
    loser.refresh_from_db()
    survivor.refresh_from_db()
    return api.post(
        f"{WIDGETS_URL}{loser.pk}/merge/",
        {"into_id": str(survivor.pk), "version": loser.version, "into_version": survivor.version},
        content_type=JSON,
    )


@pytest.fixture
def pair(tenant: Tenant, root_org: Organization, owner: User) -> tuple[Widget, Widget]:
    loser = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="dup")
    survivor = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")
    WidgetEntry.objects.create(tenant=tenant, organization=root_org, widget=loser, note="kept")
    return loser, survivor


def test_a_merge_leaves_a_read_only_tombstone_and_keeps_the_ledger(
    api: Client, tenant: Tenant, owner: User, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api.force_login(owner)

    preview = api.get(f"{WIDGETS_URL}{loser.pk}/merge/", {"into": str(survivor.pk)})
    assert preview.status_code == 200, preview.content
    assert _merged(tenant) == []

    merged = _merge(api, loser, survivor)
    assert merged.status_code == 200, merged.content
    assert _body(merged)["id"] == str(survivor.pk)
    said = _merged(tenant)
    assert [payload["loser_id"] for payload in said] == [str(loser.pk)]
    assert "allowed_acts" not in said[0]

    tombstone = api.get(f"{WIDGETS_URL}{loser.pk}/")
    assert _body(tombstone)["merged_into_id"] == str(survivor.pk)
    loser.refresh_from_db()
    refused = api.patch(
        f"{WIDGETS_URL}{loser.pk}/", {"name": "back", "version": loser.version}, content_type=JSON
    )
    assert refused.status_code == 409, refused.content
    assert _body(refused)["code"] == "merged"
    assert WidgetEntry.objects.filter(widget=loser).count() == 1

    again = _merge(api, loser, survivor)
    assert again.status_code == 200, again.content
    assert len(_merged(tenant)) == 1


def test_a_member_may_not_merge(
    api: Client, tenant: Tenant, member: User, pair: tuple[Widget, Widget]
) -> None:
    loser, survivor = pair
    api.force_login(member)

    refused = _merge(api, loser, survivor)

    assert refused.status_code == 403, refused.content
    loser.refresh_from_db()
    assert loser.merged_into_id is None


# golden: merge end
