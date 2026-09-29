"""The duplicate adoption's own test — copied with the adoption, and green on the copy.

Every line is fenced `golden: duplicate`: a copy made at the presser's hat,
owned by them and named `Copy of <name>`, carrying what the declaration copies
and never the ledger; a repeated key answering the first copy. Rows and ledger
lines are made by hand — the noun's create and its ledger are the product's own
business, and so is a uniqueness the copied name could meet (the worked
example's name-per-owner clash is `test_duplicate_merge.py`'s).
"""

# golden: duplicate begin
import json
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.test import Client

from apps.accounts.models import User
from apps.core.models import Organization, Tenant
from apps.example.models import Widget, WidgetEntry

pytestmark = pytest.mark.django_db

WIDGETS_URL = "/api/v1/widgets/"


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def _payloads(tenant: Tenant, name: str) -> list[dict[str, Any]]:
    event = django_apps.get_model("events", "Event")
    rows = event.objects.filter(tenant=tenant, name=name).order_by("created_at")
    return [dict(row.payload) for row in rows]


def test_a_copy_is_the_pressers_at_their_hat_without_the_ledger(
    api: Client, tenant: Tenant, root_org: Organization, owner: User, admin_member: User
) -> None:
    widget = Widget.objects.create(
        tenant=tenant, organization=root_org, owner=owner, name="w", notes="kept"
    )
    WidgetEntry.objects.create(tenant=tenant, organization=root_org, widget=widget, note="own")
    api.force_login(admin_member)

    made = api.post(f"{WIDGETS_URL}{widget.pk}/duplicate/")

    assert made.status_code == 201, made.content
    copy = _body(made)
    assert copy["duplicated_from_id"] == str(widget.pk)
    assert (copy["name"], copy["notes"]) == ("Copy of w", "kept")
    assert copy["owner_id"] == str(admin_member.pk)
    assert copy["organization_id"] == str(root_org.pk)
    assert WidgetEntry.objects.filter(widget_id=copy["id"]).count() == 0
    said = _payloads(tenant, "example.widget.duplicated")
    assert [payload["id"] for payload in said] == [copy["id"]]
    assert "allowed_acts" not in said[0]


def test_a_repeated_key_answers_the_first_copy(
    api: Client, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")
    api.force_login(owner)

    first = api.post(f"{WIDGETS_URL}{widget.pk}/duplicate/", HTTP_IDEMPOTENCY_KEY="press-1")
    again = api.post(f"{WIDGETS_URL}{widget.pk}/duplicate/", HTTP_IDEMPOTENCY_KEY="press-1")

    assert first.status_code == 201, first.content
    assert _body(again)["id"] == _body(first)["id"]
    assert Widget.objects.filter(tenant=tenant).count() == 2


# golden: duplicate end
