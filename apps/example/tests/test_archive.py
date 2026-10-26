"""Archive and restore on the worked example, over the wire and at the service."""

# golden: policy begin
from __future__ import annotations

import json
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.test import Client

from apps.example.models import WidgetPolicy
from apps.example.services import (
    archive_widget,
    archive_widget_policy,
    create_widget,
    create_widget_policy,
)
from pilecap import Actor
from pilecap.accounts import User
from pilecap.tenancy import Tenant

# golden: policy end
# isort: split
from apps.example.models import Widget
from apps.example.services import restore_widget
from pilecap import Forbidden, NotFound
from pilecap.accounts import create_user
from pilecap.tenancy import Membership, Organization, add_membership, create_organization
from pilecap.testing import actor_for, refusal_sentence, system_actor

# golden: policy begin
pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"
POLICIES_URL = "/api/v1/widgets/policies/"
JSON = "application/json"
# golden: policy end
PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret


# golden: policy begin
def _body(response: Any) -> Any:
    return json.loads(response.content)


def _ids(response: Any) -> list[str]:
    assert response.status_code == 200, response.content
    return [row["id"] for row in _body(response)["items"]]


def _events(tenant: Tenant, name: str) -> int:
    """How many outbox rows carry this event name — the spine's own count."""
    outbox = django_apps.get_model("events", "Outbox")
    return int(outbox.objects.filter(event__tenant=tenant, event__name=name).count())


# golden: policy end


# --- EXA.1 · the press, the repeat, the cuts ------------------------------------


def test_an_admin_archives_a_widget_and_the_list_cuts_follow(
    api: Client, tenant: Tenant, admin_member: User, owner_actor: Actor
) -> None:
    """The press, the repeat, and the three cuts of the list."""
    archived = create_widget(tenant=tenant, actor=owner_actor, name="Old bench")
    live = create_widget(tenant=tenant, actor=owner_actor, name="New bench")
    api.force_login(admin_member)

    first = api.post(f"{LIST_URL}{archived.pk}/archive/", content_type=JSON)
    assert first.status_code == 200, first.content
    body = _body(first)
    assert body["archived_at"] is not None
    assert body["archived_by"]["id"] == str(admin_member.pk)
    assert "name" in body["archived_by"]
    assert _events(tenant, "example.widget.archived") == 1

    again = api.post(f"{LIST_URL}{archived.pk}/archive/", content_type=JSON)
    assert again.status_code == 200, again.content
    assert _body(again)["archived_at"] == body["archived_at"]
    assert _events(tenant, "example.widget.archived") == 1

    assert _ids(api.get(LIST_URL)) == [str(live.pk)]
    assert _ids(api.get(f"{LIST_URL}?show=archived")) == [str(archived.pk)]
    assert set(_ids(api.get(f"{LIST_URL}?show=all"))) == {str(live.pk), str(archived.pk)}

    refused = api.get(f"{LIST_URL}?show=x")
    assert refused.status_code == 400, refused.content
    assert _body(refused)["code"] == "invalid"
    assert "show" in json.dumps(_body(refused))


# --- EXA.2 · the archived row reads, refuses writes, and comes back -------------


def test_an_archived_widget_reads_read_only_and_restores(
    api: Client, tenant: Tenant, admin_member: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Shelved")
    api.force_login(admin_member)
    assert api.post(f"{LIST_URL}{widget.pk}/archive/", content_type=JSON).status_code == 200

    detail = api.get(f"{LIST_URL}{widget.pk}/")
    assert detail.status_code == 200, detail.content
    assert _body(detail)["archived_at"] is not None
    assert _body(detail)["allowed_acts"] == ["restore"]

    patched = api.patch(
        f"{LIST_URL}{widget.pk}/",
        {"name": "Renamed", "version": _body(detail)["version"]},
        content_type=JSON,
    )
    assert patched.status_code == 409, patched.content
    assert _body(patched)["code"] == "archived"
    assert "route:widget-restore" in [r["destination"] for r in _body(patched)["remedies"]]
    widget.refresh_from_db()
    assert widget.name == "Shelved"

    for refused in (
        api.post(f"{LIST_URL}{widget.pk}/approve/", content_type=JSON),
        api.delete(f"{LIST_URL}{widget.pk}/"),
        api.post(
            f"{LIST_URL}entries/", {"widget_id": str(widget.pk), "note": "x"}, content_type=JSON
        ),
    ):
        assert refused.status_code == 409, refused.content
        assert _body(refused)["code"] == "archived"

    restored = api.post(f"{LIST_URL}{widget.pk}/restore/", content_type=JSON)
    assert restored.status_code == 200, restored.content
    assert _body(restored)["archived_at"] is None
    assert _body(restored)["archived_by"] is None
    assert _ids(api.get(LIST_URL)) == [str(widget.pk)]
    assert _events(tenant, "example.widget.restored") == 1

    repeat = api.post(f"{LIST_URL}{widget.pk}/restore/", content_type=JSON)
    assert repeat.status_code == 200, repeat.content
    assert _events(tenant, "example.widget.restored") == 1


# --- EXA.3 · who may press ------------------------------------------------------


def test_a_member_is_forbidden_with_the_keys_own_sentence(
    api: Client, tenant: Tenant, member: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Not theirs to shelve")
    api.force_login(member)

    refused = api.post(f"{LIST_URL}{widget.pk}/archive/", content_type=JSON)
    assert refused.status_code == 403, refused.content
    assert _body(refused)["code"] == "forbidden"
    assert _body(refused)["detail"] == refusal_sentence("widget.archive")
    assert "archive" not in _body(api.get(f"{LIST_URL}{widget.pk}/"))["allowed_acts"]
    widget.refresh_from_db()
    assert widget.archived_at is None


def test_a_sibling_branch_admin_is_not_found(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor, root_org: Organization
) -> None:
    """Not-there and not-yours are one answer: a sibling's widget is a 404."""
    branch_a = create_organization(
        tenant=tenant, parent=root_org, name="Branch A", slug="branch-a", actor=owner_actor
    )
    branch_b = create_organization(
        tenant=tenant, parent=root_org, name="Branch B", slug="branch-b", actor=owner_actor
    )
    at_a = create_widget(
        tenant=tenant, actor=actor_for(user=owner, tenant=tenant, org=branch_a), name="At A"
    )
    b_admin = create_user(email="b-admin@example.com", password=PASSWORD)
    add_membership(
        user=b_admin,
        tenant=tenant,
        organization=branch_b,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    api.force_login(b_admin)

    refused = api.post(f"{LIST_URL}{at_a.pk}/archive/", content_type=JSON)
    assert refused.status_code == 404, refused.content
    assert _body(refused)["code"] == "not_found"

    with pytest.raises(NotFound):
        archive_widget(
            tenant=tenant,
            actor=actor_for(user=b_admin, tenant=tenant, org=branch_b),
            widget=at_a,
        )
    at_a.refresh_from_db()
    assert at_a.archived_at is None


def test_the_system_actor_is_refused_on_a_real_noun(
    tenant: Tenant, root_org: Organization, owner_actor: Actor
) -> None:
    """A workflow does not take a person's row out of the book on its own say-so."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Kept")
    with pytest.raises(Forbidden):
        archive_widget(
            tenant=tenant, actor=system_actor(tenant=tenant, org=root_org), widget=widget
        )
    widget.refresh_from_db()
    assert widget.archived_at is None


def test_the_service_pair_is_idempotent_both_ways(
    tenant: Tenant, admin_actor: Actor, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Twice")
    first = archive_widget(tenant=tenant, actor=admin_actor, widget=widget)
    again = archive_widget(tenant=tenant, actor=admin_actor, widget=first)
    assert again.archived_at == first.archived_at
    assert not Widget.objects.for_tenant(tenant).filter(pk=widget.pk).exists()

    back = restore_widget(tenant=tenant, actor=admin_actor, widget=again)
    assert back.archived_at is None and back.archived_by is None
    assert restore_widget(tenant=tenant, actor=admin_actor, widget=back).archived_at is None
    assert Widget.objects.for_tenant(tenant).filter(pk=widget.pk).exists()


# --- EXA.4 · a live widget holds its policy in the book --------------------------


# golden: policy begin
def test_a_policy_a_live_widget_names_is_blocked_and_names_the_widgets(
    api: Client, tenant: Tenant, admin_member: User, owner_actor: Actor, admin_actor: Actor
) -> None:
    policy = create_widget_policy(tenant=tenant, actor=owner_actor, name="Heavy")
    holder = create_widget(tenant=tenant, actor=owner_actor, name="Governed", policy=policy)
    create_widget(tenant=tenant, actor=owner_actor, name="Ungoverned")
    api.force_login(admin_member)

    refused = api.post(f"{POLICIES_URL}{policy.pk}/archive/", content_type=JSON)
    assert refused.status_code == 409, refused.content
    body = _body(refused)
    assert body["code"] == "archive_blocked"
    assert body["blocking"][0]["noun"] == "widget"
    door = f"route:widget-list?policy={policy.pk}"
    assert body["blocking"][0]["door"] == door
    assert door in [remedy["destination"] for remedy in body["remedies"]]
    policy.refresh_from_db()
    assert policy.archived_at is None
    assert _events(tenant, "example.widget_policy.archived") == 0

    # The door is real: the list narrowed to this policy is exactly the holders.
    assert _ids(api.get(f"{LIST_URL}?policy={policy.pk}")) == [str(holder.pk)]

    # Take the holder out of the book and the policy is free to follow it.
    archive_widget(tenant=tenant, actor=admin_actor, widget=holder)
    archived = api.post(f"{POLICIES_URL}{policy.pk}/archive/", content_type=JSON)
    assert archived.status_code == 200, archived.content
    assert _body(archived)["archived_at"] is not None
    assert _ids(api.get(POLICIES_URL)) == []
    assert _ids(api.get(f"{POLICIES_URL}?show=archived")) == [str(policy.pk)]

    restored = api.post(f"{POLICIES_URL}{policy.pk}/restore/", content_type=JSON)
    assert restored.status_code == 200, restored.content
    assert _ids(api.get(POLICIES_URL)) == [str(policy.pk)]


def test_an_archived_policy_governs_nobody_and_cannot_be_named(
    tenant: Tenant, owner_actor: Actor, admin_actor: Actor, api: Client, owner: User
) -> None:
    policy = create_widget_policy(tenant=tenant, actor=owner_actor, name="Retired")
    archive_widget_policy(tenant=tenant, actor=admin_actor, policy=policy)
    assert not WidgetPolicy.objects.for_tenant(tenant).filter(pk=policy.pk).exists()
    api.force_login(owner)

    assert api.get(f"{POLICIES_URL}governing/").status_code == 404
    named = api.post(LIST_URL, {"name": "New", "policy_id": str(policy.pk)}, content_type=JSON)
    assert named.status_code == 404, named.content


# golden: policy end

# --- EXA.5 (the per-row half) · allowed_acts on every WidgetOut -------------------


def test_every_widget_out_carries_allowed_acts_and_a_member_is_offered_no_archive(
    api: Client, tenant: Tenant, admin_member: User, member: User, owner_actor: Actor
) -> None:
    create_widget(tenant=tenant, actor=owner_actor, name="One")
    create_widget(tenant=tenant, actor=owner_actor, name="Two")

    api.force_login(admin_member)
    for row in _body(api.get(LIST_URL))["items"]:
        assert "archive" in row["allowed_acts"], row
        assert "restore" not in row["allowed_acts"], row

    api.force_login(member)
    rows = _body(api.get(LIST_URL))["items"]
    assert rows
    for row in rows:
        assert isinstance(row["allowed_acts"], list), row
        assert "archive" not in row["allowed_acts"], row


# --- EXA.8 · approval is idempotent ----------------------------------------------


def test_approving_twice_writes_one_approved_ledger_line(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """Approval is idempotent as its contract says: the retry adds no second line."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Approved once")
    api.force_login(owner)

    first = api.post(f"{LIST_URL}{widget.pk}/approve/", content_type=JSON)
    second = api.post(f"{LIST_URL}{widget.pk}/approve/", content_type=JSON)
    assert (first.status_code, second.status_code) == (200, 200), second.content

    entries = api.get(f"{LIST_URL}entries/?widget_id={widget.pk}&include_count=true")
    assert entries.status_code == 200, entries.content
    assert _body(entries)["count"] == 1
    assert [row["kind"] for row in _body(entries)["items"]] == ["approved"]


def test_the_widget_row_is_archivable() -> None:
    """The model declared the mixin: two columns, and `for_tenant` hides the cut."""
    assert {field.name for field in Widget._meta.get_fields()} >= {"archived_at", "archived_by"}
