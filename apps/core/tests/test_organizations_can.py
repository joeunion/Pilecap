"""`GET /organizations/?can=<key>`: the nodes where the actor may do that, and no others.

The move sheet's destinations are this list — no per-noun destinations read.
Two worlds: the criterion's own (root, A, A1; an admin at A) and a sharper one
in which the filter must actually narrow — a person who is a MEMBER at the root
and an ADMIN at A, acting at the root, sees the whole tree and may administer
only A and A1.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import actor_for
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization

pytestmark = pytest.mark.django_db

ORGANIZATIONS = "/api/v1/organizations/"

#: Held by `admin` (`*`) and never by `member` (`*.read`) — the administer key.
KEY = "organization.update"


@pytest.fixture
def tree(tenant: Tenant, owner: User) -> dict[str, Organization]:
    root = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=root)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=acting)
    a1 = create_organization(tenant=tenant, parent=a, name="A1", slug="a1", actor=acting)
    return {"root": root, "a": a, "a1": a1}


def _person(
    tenant: Tenant, owner: User, tree: dict[str, Organization], email: str, grants: list[Any]
) -> User:
    user = create_user(email=email, password="pw-for-tests-only")  # noqa: S106 — a throwaway password a test user is made with
    acting = actor_for(user=owner, tenant=tenant, org=tree["root"])
    for i, (node, role) in enumerate(grants):
        add_membership(
            user=user,
            tenant=tenant,
            organization=tree[node],
            role=role,
            is_default=i == 0,
            actor=acting,
        )
    return user


def _slugs(response: Any) -> set[str]:
    assert response.status_code == 200, response.content
    return {row["slug"] for row in response.json()["items"]}


def test_a_branch_admin_can_at_their_subtree(
    api: Client, tenant: Tenant, owner: User, tree: dict[str, Organization]
) -> None:
    admin = _person(tenant, owner, tree, "a-admin@example.com", [("a", Membership.Role.ADMIN)])
    api.force_login(admin)
    assert _slugs(api.get(ORGANIZATIONS, {"can": KEY})) == {"a", "a1"}


def test_the_filter_narrows_what_the_hat_sees_to_where_the_actor_may_act(
    api: Client, tenant: Tenant, owner: User, tree: dict[str, Organization]
) -> None:
    person = _person(
        tenant,
        owner,
        tree,
        "mixed@example.com",
        [("root", Membership.Role.MEMBER), ("a", Membership.Role.ADMIN)],
    )
    api.force_login(person)
    root_slug = tree["root"].slug

    assert _slugs(api.get(ORGANIZATIONS)) == {root_slug, "a", "a1"}
    assert _slugs(api.get(ORGANIZATIONS, {"can": KEY})) == {"a", "a1"}
    # A read the member holds everywhere narrows nothing.
    assert _slugs(api.get(ORGANIZATIONS, {"can": "organization.read"})) == {root_slug, "a", "a1"}


def test_an_unknown_key_is_invalid_naming_can(
    api: Client, tenant: Tenant, owner: User, tree: dict[str, Organization]
) -> None:
    api.force_login(owner)
    response = api.get(ORGANIZATIONS, {"can": "gadget.teleport"})
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid"
    assert "can" in body["errors"]
