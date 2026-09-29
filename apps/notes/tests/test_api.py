"""The note list over REST: its query pin, and the archive cuts on the wire."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.example.models import Widget
from apps.example.services import create_widget
from apps.notes.services import archive_note, create_note

pytestmark = pytest.mark.django_db

NOTES_URL = "/api/v1/notes/"
NOTE_URL = "/api/v1/notes/{}/"
JSON = "application/json"

#: The note list's query count at any number of rows, measured on the box and
#: pinned (rule 5): the session and the tenant middleware, the subject's
#: resolution (the kind registry's read of the subject row, and the hat's
#: reach), the `note.read` resolution at the hat (paid once per actor), the
#: page itself with the author and the archiver joined in.
LIST_QUERY_BUDGET = 12


@pytest.fixture(autouse=True)
def declares_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The widget declares notes for this module, ADDED to whatever it declares.

    Additive and undone by `monkeypatch`, never a replacement and never a hand
    `del`: the day the worked example declares its own attachments, this plant
    keeps them and leaves them exactly as it found them.
    """
    monkeypatch.setattr(
        Widget, "attachments", (*getattr(Widget, "attachments", ()), "notes"), raising=False
    )


@pytest.fixture
def widget(tenant: Tenant, owner_actor: Actor) -> Widget:
    return create_widget(tenant=tenant, actor=owner_actor, name="Subject")


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


@pytest.mark.parametrize("rows", [5, 25])
def test_list_query_count_does_not_grow_with_rows(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    widget: Widget,
    django_assert_num_queries: Any,
    rows: int,
) -> None:
    for index in range(rows):
        create_note(
            tenant=tenant, actor=owner_actor, subject=f"widget:{widget.pk}", body=f"n{index}"
        )
    api.force_login(owner)

    with django_assert_num_queries(LIST_QUERY_BUDGET):
        response = api.get(NOTES_URL, {"subject": f"widget:{widget.pk}"})

    assert response.status_code == 200, response.content
    assert len(_body(response)["items"]) == rows


def test_the_archive_cuts_and_the_archived_detail_answer_read_only(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    admin_actor: Actor,
    widget: Widget,
) -> None:
    subject = f"widget:{widget.pk}"
    live = create_note(tenant=tenant, actor=owner_actor, subject=subject, body="live")
    gone = archive_note(
        tenant=tenant,
        actor=admin_actor,
        note=create_note(tenant=tenant, actor=owner_actor, subject=subject, body="gone"),
    )
    api.force_login(owner)

    def listed(**query: str) -> list[str]:
        response = api.get(NOTES_URL, {"subject": subject, **query})
        assert response.status_code == 200, response.content
        return [row["id"] for row in _body(response)["items"]]

    assert listed() == [str(live.pk)]
    assert listed(show="archived") == [str(gone.pk)]
    assert set(listed(show="all")) == {str(live.pk), str(gone.pk)}

    detail = api.get(NOTE_URL.format(gone.pk))
    assert detail.status_code == 200
    assert _body(detail)["archived_at"] is not None
    assert _body(detail)["archived_by"]["id"] == str(admin_actor.user.pk)  # type: ignore[union-attr]

    refused = api.patch(
        NOTE_URL.format(gone.pk), data=json.dumps({"body": "edit"}), content_type=JSON
    )
    assert refused.status_code == 409, refused.content
    assert _body(refused)["code"] == "archived"


def test_the_list_needs_a_subject_and_an_unknown_field_is_refused(
    api: Client, owner: User, widget: Widget
) -> None:
    api.force_login(owner)
    assert api.get(NOTES_URL).status_code in (400, 422)

    response = api.post(
        NOTES_URL,
        data=json.dumps({"subject": f"widget:{widget.pk}", "body": "x", "organization": "root"}),
        content_type=JSON,
    )
    assert response.status_code == 422, response.content
    assert _body(response)["code"] == "invalid_body"


def test_the_whole_road_by_route_name(
    api: Client, owner: User, owner_actor: Actor, widget: Widget
) -> None:
    """Every route of the door, reached by its `url_name`: write, read, list,
    correct, archive and restore one note."""
    from django.urls import reverse

    subject = f"widget:{widget.pk}"
    api.force_login(owner)

    created = api.post(
        reverse("api:note-create"),
        data=json.dumps({"subject": subject, "body": "first"}),
        content_type=JSON,
    )
    assert created.status_code == 201, created.content
    note_id = _body(created)["id"]

    detail = api.get(reverse("api:note-detail", kwargs={"note_id": note_id}))
    assert detail.status_code == 200 and _body(detail)["body"] == "first"

    listed = api.get(reverse("api:note-list"), {"subject": subject})
    assert [row["id"] for row in _body(listed)["items"]] == [note_id]

    updated = api.patch(
        reverse("api:note-update", kwargs={"note_id": note_id}),
        data=json.dumps({"body": "second"}),
        content_type=JSON,
    )
    assert updated.status_code == 200 and _body(updated)["body"] == "second"

    archived = api.post(
        reverse("api:note-archive", kwargs={"note_id": note_id}), data="{}", content_type=JSON
    )
    assert archived.status_code == 200 and _body(archived)["archived_at"] is not None
    again = api.post(
        reverse("api:note-archive", kwargs={"note_id": note_id}), data="{}", content_type=JSON
    )
    assert _body(again)["archived_at"] == _body(archived)["archived_at"]

    restored = api.post(
        reverse("api:note-restore", kwargs={"note_id": note_id}), data="{}", content_type=JSON
    )
    assert restored.status_code == 200 and _body(restored)["archived_at"] is None
