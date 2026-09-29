"""The history adoption's own test — copied with the adoption, and green on the copy.

Every line is fenced `golden: history`: four things done to one widget read
back as four entries, newest first, the edit naming the one field it sent.
"""

# golden: history begin
import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.actor import actor_for
from apps.core.models import Organization, Tenant
from apps.core.services import create_organization
from apps.example.models import Widget

pytestmark = pytest.mark.django_db

WIDGETS_URL = "/api/v1/widgets/"
JSON = "application/json"


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def test_the_history_reads_what_was_done_newest_first(
    api: Client, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    branch = create_organization(
        tenant=tenant, parent=root_org, name="Branch", slug="branch", actor=acting
    )
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")
    url = f"{WIDGETS_URL}{widget.pk}/"
    api.force_login(owner)

    edited = api.patch(url, {"name": "w2", "version": widget.version}, content_type=JSON)
    assert edited.status_code == 200, edited.content
    moved = api.post(
        f"{url}move/",
        {"organization_id": str(branch.pk), "version": _body(edited)["version"]},
        content_type=JSON,
    )
    assert moved.status_code == 200, moved.content
    assert api.post(f"{url}archive/").status_code == 200
    assert api.post(f"{url}restore/").status_code == 200

    history = api.get(f"{url}history/")
    assert history.status_code == 200, history.content
    entries = _body(history)["items"]
    assert [e["verb"] for e in entries] == ["restore", "archive", "move", "update"]
    assert entries[3]["changed_fields"] == ["name"]
    assert entries[3]["door"] == "rest"


# golden: history end
