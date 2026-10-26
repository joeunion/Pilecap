"""A note about a row, over the REST door — the subject resolved at every write.

**Self-contained on purpose.** Nothing here imports `apps.djb_notes`: every claim is
made on the wire (the response body, the status, the refusal's `errors`), so the
same module runs against a tree with no notes app at all and answers `404` for
`POST /api/v1/djb_notes/` — which is this module's red.

The tree: a root and two sibling branches. A widget lives in branch B; a clerk
of branch A is the stranger next door, who must hear `404` — never `403` — for
anything about it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = pytest.mark.django_db

NOTES_URL = "/api/v1/djb_notes/"
NOTE_URL = "/api/v1/djb_notes/{}/"
JSON = "application/json"
PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret


@dataclass
class Branches:
    tenant: Tenant
    root: Organization
    branch_a: Organization
    branch_b: Organization
    clerk_a: User  # a member of branch A only
    widget_b: Widget  # lives in branch B


def _person(tenant: Tenant, email: str, org: Organization, role: str) -> User:
    user = create_user(email=email, password=PASSWORD)
    add_membership(
        user=user,
        tenant=tenant,
        organization=org,
        is_default=True,
        role=role,
        actor=system_actor(tenant=tenant),
    )
    return user


@pytest.fixture
def branches(tenant: Tenant, owner: User) -> Branches:
    root = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    branch_a = create_organization(
        tenant=tenant, parent=root, name="Branch A", slug="branch-a", actor=acting
    )
    branch_b = create_organization(
        tenant=tenant, parent=root, name="Branch B", slug="branch-b", actor=acting
    )
    clerk_a = _person(tenant, "clerk-a@example.com", branch_a, Membership.Role.MEMBER)
    widget_b = create_widget(
        tenant=tenant, actor=actor_for(user=owner, tenant=tenant, org=branch_b), name="At B"
    )
    return Branches(tenant, root, branch_a, branch_b, clerk_a, widget_b)


@pytest.fixture
def declares_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The widget declares notes for this module, ADDED to whatever it declares.

    Additive and undone by `monkeypatch`, never a replacement and never a hand
    `del`: the day the worked example declares its own attachments, this plant
    keeps them and leaves them exactly as it found them.
    """
    monkeypatch.setattr(
        Widget, "attachments", (*getattr(Widget, "attachments", ()), "notes"), raising=False
    )


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def _write(api: Client, subject: str, body: str = "Ships Tuesday.", **headers: str) -> Any:
    return api.post(
        NOTES_URL,
        data=json.dumps({"subject": subject, "body": body}),
        content_type=JSON,
        headers=headers,
    )


def test_a_note_about_a_widget_lives_where_the_widget_lives(
    api: Client, owner: User, branches: Branches, declares_notes: None
) -> None:
    """NT.1: 201, and the note's organization IS the widget's — not the hat's."""
    api.force_login(owner)
    subject = f"widget:{branches.widget_b.pk}"

    response = _write(api, subject)

    assert response.status_code == 201, response.content
    note = _body(response)
    # The owner acts at the ROOT (their default hat); the note lands in branch B.
    assert note["organization_id"] == str(branches.widget_b.organization_id)
    assert note["organization_id"] == str(branches.branch_b.pk)
    assert note["organization_id"] != str(branches.root.pk)
    assert note["subject"] == subject
    assert note["body"] == "Ships Tuesday."

    listed = api.get(NOTES_URL, {"subject": subject})
    assert listed.status_code == 200, listed.content
    assert [row["id"] for row in _body(listed)["items"]] == [note["id"]]


def test_a_sibling_branch_subject_is_not_found_never_forbidden(
    api: Client, owner: User, branches: Branches, declares_notes: None
) -> None:
    """NT.1: the clerk of branch A cannot name branch B's widget — 404 both ways."""
    subject = f"widget:{branches.widget_b.pk}"
    api.force_login(owner)
    assert _write(api, subject).status_code == 201

    api.force_login(branches.clerk_a)
    written = _write(api, subject)
    listed = api.get(NOTES_URL, {"subject": subject})

    for response in (written, listed):
        assert response.status_code == 404, response.content
        assert _body(response)["code"] == "not_found"


def test_a_kind_that_does_not_declare_notes_is_invalid_naming_subject(
    api: Client, owner: User, branches: Branches, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NT.1: a real, reachable widget — but the widget has not declared notes."""
    # The worked example declares notes; this plant takes `notes` OUT and keeps
    # the rest — subtractive, undone by `monkeypatch`.
    kept = tuple(kind for kind in getattr(Widget, "attachments", ()) if kind != "notes")
    monkeypatch.setattr(Widget, "attachments", kept, raising=False)
    api.force_login(owner)

    for subject in (f"widget:{branches.widget_b.pk}", f"organization:{branches.root.pk}"):
        response = _write(api, subject)
        assert response.status_code == 400, response.content
        body = _body(response)
        assert body["code"] == "invalid"
        assert "subject" in body["errors"], body


def test_only_the_author_may_change_a_note(
    api: Client, owner: User, admin_member: User, branches: Branches, declares_notes: None
) -> None:
    """NT.1: `update_note` by anyone but the author is 403 — an administrator too."""
    api.force_login(owner)
    note = _body(_write(api, f"widget:{branches.widget_b.pk}"))

    api.force_login(admin_member)
    refused = api.patch(
        NOTE_URL.format(note["id"]), data=json.dumps({"body": "Not mine"}), content_type=JSON
    )
    assert refused.status_code == 403, refused.content
    assert _body(refused)["code"] == "forbidden"

    api.force_login(owner)
    changed = api.patch(
        NOTE_URL.format(note["id"]), data=json.dumps({"body": "Mine"}), content_type=JSON
    )
    assert changed.status_code == 200, changed.content
    assert _body(changed)["body"] == "Mine"
