"""A contact answers each viewer the verbs THAT viewer may press on it.

`RecipientOut` inherits `core.schemas.ActsOut`: the list is paged by
`ActsPagination` (every item's `allowed_acts`, and the list's own) and the
detail sets its one row's through `core.verbs.with_allowed_acts`. The answer is
the server's, per row and per viewer — an administrator reads `archive` on a
live contact, a member does not, and an archived contact offers `restore` alone.

And one promise rides beside it: **an event payload never carries a
per-viewer field.** `allowed_acts` is what one caller may press;
`comms.recipient.archived` goes to every subscriber, so its payload is the row
and nothing about who is looking. The key set is written out below rather than
derived from the schema — a pin derived from the thing it pins cannot fail.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.comms.models import Recipient
from apps.comms.schemas import RecipientOut
from apps.comms.services import archive_recipient
from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.schemas import without_personal
from apps.events.models import Event

pytestmark = pytest.mark.django_db

JSON = "application/json"
RECIPIENTS_URL = "/api/v1/recipients/"
ARCHIVED = "comms.recipient.archived"

#: `comms.recipient.archived`'s payload keys, written out: the row as `RecipientOut`
#: describes it less its `personal` fields, the spine's version stamp, no per-viewer field.
ARCHIVED_PAYLOAD_KEYS = frozenset(
    {
        "v",
        "id",
        "user_id",
        "organization_id",
        "created_at",
        "archived_at",
        "archived_by",
    }
)


def _body(response: Any) -> dict[str, Any]:
    assert response.status_code == 200, response.content
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def _item(page: dict[str, Any], recipient: Recipient) -> dict[str, Any]:
    rows: list[dict[str, Any]] = [item for item in page["items"] if item["id"] == str(recipient.pk)]
    (row,) = rows
    return row


# --- the detail -----------------------------------------------------------------


def test_the_detail_answers_an_admin_archive_and_a_member_none(
    api: Client, admin_member: User, member: User, recipient: Recipient
) -> None:
    api.force_login(admin_member)
    admin_acts = _body(api.get(f"{RECIPIENTS_URL}{recipient.pk}/"))["allowed_acts"]
    assert "archive" in admin_acts, admin_acts
    assert "restore" not in admin_acts, admin_acts

    api.force_login(member)
    member_acts = _body(api.get(f"{RECIPIENTS_URL}{recipient.pk}/"))["allowed_acts"]
    assert "archive" not in member_acts, member_acts
    assert "restore" not in member_acts, member_acts


def test_an_archived_contact_offers_restore_alone(
    api: Client, admin_member: User, owner_actor: Actor, recipient: Recipient
) -> None:
    archive_recipient(tenant=recipient.tenant, actor=owner_actor, recipient=recipient)
    api.force_login(admin_member)
    assert _body(api.get(f"{RECIPIENTS_URL}{recipient.pk}/"))["allowed_acts"] == ["restore"]


# --- the list -------------------------------------------------------------------


def test_the_list_answers_an_admin_archive_and_a_member_none(
    api: Client, admin_member: User, member: User, recipient: Recipient
) -> None:
    api.force_login(admin_member)
    admin_page = _body(api.get(RECIPIENTS_URL))
    assert "archive" in _item(admin_page, recipient)["allowed_acts"], admin_page
    # The list's own acts ride the envelope — `create` when this hat may.
    assert "allowed_acts" in admin_page, sorted(admin_page)

    api.force_login(member)
    member_page = _body(api.get(RECIPIENTS_URL))
    assert "archive" not in _item(member_page, recipient)["allowed_acts"], member_page


def test_every_door_answering_a_contact_carries_the_pressers_acts(
    api: Client, admin_member: User, recipient: Recipient
) -> None:
    """Create, update, archive and restore answer the row WITH its acts as it now
    stands — never the schema's empty default, which would read as "you may do
    nothing" to a face drawing its buttons from it."""
    api.force_login(admin_member)
    created = api.post(
        RECIPIENTS_URL, data=json.dumps({"email": "new@example.com"}), content_type=JSON
    )
    assert created.status_code == 201, created.content
    assert "archive" in json.loads(created.content)["allowed_acts"]

    updated = api.patch(
        f"{RECIPIENTS_URL}{recipient.pk}/",
        data=json.dumps({"display_name": "Renamed"}),
        content_type=JSON,
    )
    assert "archive" in _body(updated)["allowed_acts"]
    archived = api.post(f"{RECIPIENTS_URL}{recipient.pk}/archive/")
    assert _body(archived)["allowed_acts"] == ["restore"]
    restored = api.post(f"{RECIPIENTS_URL}{recipient.pk}/restore/")
    assert "archive" in _body(restored)["allowed_acts"]


# --- the payload: the row, and nothing about who is looking ---------------------


def test_the_archived_payload_carries_no_per_viewer_field(
    api: Client, admin_member: User, tenant: Tenant, recipient: Recipient
) -> None:
    api.force_login(admin_member)
    answered = _body(api.post(f"{RECIPIENTS_URL}{recipient.pk}/archive/"))

    (event,) = Event.objects.for_tenant(tenant).filter(name=ARCHIVED)
    payload = dict(event.payload)
    assert set(payload) == ARCHIVED_PAYLOAD_KEYS, sorted(payload)
    assert "allowed_acts" not in payload
    # Everything else is the presser's own answer, value for value: the payload
    # IS the row, minus the one field that belongs to the viewer.
    assert payload.pop("v") == 1
    row = without_personal(
        RecipientOut, {key: value for key, value in answered.items() if key != "allowed_acts"}
    )
    assert payload == row, (payload, row)
