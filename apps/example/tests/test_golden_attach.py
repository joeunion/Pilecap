"""The attach adoption's own test — copied with the adoption, and green on the copy."""

# golden: attach begin
import json
from typing import Any

import pytest
from django.test import Client

from apps.example.models import Widget
from pilecap import Actor
from pilecap.accounts import User
from pilecap.attach import create_note, create_tag, create_tag_link
from pilecap.tenancy import Organization, Tenant

pytestmark = pytest.mark.django_db

WIDGETS_URL = "/api/v1/widgets/"


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def test_a_widget_takes_a_note_and_a_tag_and_answers_them(
    api: Client, tenant: Tenant, root_org: Organization, owner: User, owner_actor: Actor
) -> None:
    widget = Widget.objects.create(tenant=tenant, organization=root_org, owner=owner, name="w")
    subject = f"widget:{widget.pk}"
    word = create_tag(tenant=tenant, actor=owner_actor, name="Urgent")
    create_tag_link(tenant=tenant, actor=owner_actor, tag=word, subject=subject)
    create_note(tenant=tenant, actor=owner_actor, subject=subject, body="Checked the mount.")
    api.force_login(owner)

    detail = api.get(f"{WIDGETS_URL}{widget.pk}/")
    notes = api.get("/api/v1/djb_notes/", {"subject": subject})

    assert detail.status_code == 200, detail.content
    assert [tag["name"] for tag in _body(detail)["tags"]] == ["Urgent"]
    assert notes.status_code == 200, notes.content
    assert [note["body"] for note in _body(notes)["items"]] == ["Checked the mount."]


# golden: attach end
