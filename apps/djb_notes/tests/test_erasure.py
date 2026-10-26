"""Erasing a person who wrote notes: the erasure completes and the notes stay.

`Note.author` is `PROTECT`, and a reader who knows only that expects erasing a
note's author to be refused. It is not, because the template's erasure never
deletes the person's row: `accounts.services.erase_user` anonymises the `User`
and keeps it, so the foreign key keeps pointing at a real row and the `PROTECT`
has nothing to refuse. This module pins that property from the note's side, so
the day erasure changes shape — a delete, a cascade, a column copied into the
note — this fails naming what moved.

Two states are driven: the author erased with one live note, and with one
ARCHIVED note that the author archived themselves (`archived_by` is `PROTECT`
too). Not driven here: a tenant-less erasure — the road is
`accounts/tests/test_erasure.py::test_the_deployment_itself_can_erase_a_user_with_no_tenant`,
and nothing about the note differs on it.

Read as the mechanism says, not as a first reading would guess:

* **the erased address** is whatever `erase_user` wrote — `erased+<uuid>@` the
  `ERASED_EMAIL_DOMAIN` constant — so it is asserted through the constant and
  the refreshed row, never a spelled literal;
* **the archived state's author is an administrator**, because archiving a
  note is an administrator's press (`policies.POLICIES["djb_note.archive"]`);
  the live note's author is the least privileged member;
* **the reader on the wire is the tenant's owner** — another member of the
  tenant, not the author;
* **the author's original address survives nowhere**: `DjbNoteOut` marks
  `author_email` personal, so the note's events never carried it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import ERASED_EMAIL_DOMAIN, create_user, erase_user, issue_token
from apps.accounts.tests.test_erasure_residue import (
    RETAINED,
    TARGET_EMAIL,
    TARGET_SUBJECT,
    residue,
)
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership
from apps.djb_notes.models import Note
from apps.djb_notes.services import archive_note, create_note
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = pytest.mark.django_db

NOTES_URL = "/api/v1/djb_notes/"

#: The note's words. They name nobody: the residue sweep looks for the
#: identifiers erasure knows about, and a body that carried the author's address
#: would be free text a product erases in its own service — the sweep's declared
#: blind spot (`test_erasure_residue.py`, "free-text PII a product writes into
#: its own columns"), not something this module could claim to cover.
BODY = "Called the site lead; the mount ships Tuesday."

#: The author's role per state. Archiving a note is an administrator's press
#: (`policies.POLICIES["djb_note.archive"]`), so the author who archives their own
#: note is an admin; the live note's author is the least privileged member.
AUTHOR_ROLE = {"live": Membership.Role.MEMBER, "archived": Membership.Role.ADMIN}


@pytest.fixture(autouse=True)
def declares_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The widget takes notes for this module, ADDED to whatever it declares."""
    monkeypatch.setattr(
        Widget, "attachments", (*getattr(Widget, "attachments", ()), "notes"), raising=False
    )


def _items(response: Any) -> list[dict[str, Any]]:
    body: dict[str, Any] = json.loads(response.content)
    items: list[dict[str, Any]] = body["items"]
    return items


@pytest.mark.parametrize("state", ["live", "archived"])
def test_erasing_a_notes_author_completes_and_the_note_survives_anonymised(
    owner_actor: Actor,
    owner: User,
    tenant: Tenant,
    root_org: Organization,
    api: Client,
    state: str,
) -> None:
    author = create_user(email=TARGET_EMAIL, password="x" * 20)
    add_membership(
        user=author, tenant=tenant, role=AUTHOR_ROLE[state], actor=system_actor(tenant=tenant)
    )
    author_actor = actor_for(user=author, tenant=tenant, org=root_org)
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Subject")
    subject = f"widget:{widget.pk}"
    note = create_note(tenant=tenant, actor=author_actor, subject=subject, body=BODY)
    if state == "archived":
        note = archive_note(tenant=tenant, actor=author_actor, note=note)
        assert note.archived_by_id == author.pk
    show = {"subject": subject, "show": state}
    _token, plaintext = issue_token(
        user=author, tenant=tenant, name="integration", actor=author_actor
    )
    bearer = Client(HTTP_AUTHORIZATION=f"Bearer {plaintext}")
    assert bearer.get(NOTES_URL, show).status_code == 200

    # The erasure RETURNS: no `ProtectedError`, no `Conflict`.
    erased = erase_user(user=author, actor=owner_actor, tenant=tenant)

    erased.refresh_from_db()
    assert erased.pk == author.pk
    assert erased.email.startswith("erased+")
    assert erased.email.endswith(f"@{ERASED_EMAIL_DOMAIN}")

    # The note row survives, still pointing at the same (now anonymised) row,
    # its words byte-identical.
    kept = Note.objects.for_tenant(tenant).including_archived().get(pk=note.pk)
    assert kept.author_id == author.pk
    assert kept.body == BODY
    if state == "archived":
        assert kept.archived_by_id == author.pk

    # Another member reads it on the wire, and the author is the erased address.
    api.force_login(owner)
    response = api.get(NOTES_URL, show)
    assert response.status_code == 200, response.content
    [item] = _items(response)
    assert item["id"] == str(note.pk)
    assert item["author_email"] == erased.email
    assert TARGET_EMAIL not in response.content.decode()

    # Nothing in the schema still holds the person, the note's events included.
    survivors = set(residue(TARGET_EMAIL, TARGET_SUBJECT))
    assert survivors - set(RETAINED) == set()
    assert survivors == set()

    # The machine that acted as the author stops at the door.
    assert bearer.get(NOTES_URL, show).status_code == 401
