"""The permission world's people sign in over the REST door; its clerk reaches one branch only."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.core.actor import Actor
from apps.core.models import Membership
from apps.core.tests.permissions_world import World, build_world

pytestmark = pytest.mark.django_db

ORGANIZATIONS = "/api/v1/organizations/"


@pytest.fixture
def world() -> World:
    return build_world()


def people(world: World) -> dict[str, Actor]:
    """Every person the world names, by field — derived, so a new person joins every case."""
    return {name: value for name, value in vars(world).items() if isinstance(value, Actor)}


def slugs(response: Any) -> list[str]:
    assert response.status_code == 200, response.content
    return sorted(item["slug"] for item in json.loads(response.content)["items"])


def code(response: Any) -> str:
    return str(json.loads(response.content)["code"])


def test_every_person_signs_in_to_the_world_tenant_at_their_own_hat(world: World) -> None:
    for name, who in people(world).items():
        client = world.session(who)
        assert isinstance(client, Client)
        listed = client.get(ORGANIZATIONS, {"limit": 50})
        if who is world.roleless:
            # Resolved and then refused by the role it lacks, not by the resolution.
            assert code(listed) == "forbidden", listed.content
            continue
        assert who.org is not None
        assert who.org.slug in slugs(listed), name


def test_a_session_honours_the_org_header_inside_the_hat(world: World) -> None:
    owner = world.session(world.owner)
    assert slugs(owner.get(ORGANIZATIONS)) == sorted(["a", "a1", "a1x", "b", world.root.slug])
    assert slugs(owner.get(ORGANIZATIONS, headers={"x-org": "b"})) == ["b"]
    assert slugs(owner.get(ORGANIZATIONS, headers={"x-org": "a1"})) == ["a1", "a1x"]


def test_the_clerk_belongs_to_branch_a_and_nowhere_else(world: World) -> None:
    held = list(Membership.objects.for_tenant(world.tenant).of(world.clerk.user))
    assert [(m.organization_id, m.role) for m in held] == [(world.a.pk, Membership.Role.MEMBER)]
    assert held[0] == world.clerk_membership
    assert world.clerk.org == world.a


def test_the_clerk_reaches_a_and_beneath_and_nothing_above_or_beside(world: World) -> None:
    clerk = world.session(world.clerk)
    assert slugs(clerk.get(ORGANIZATIONS)) == ["a", "a1", "a1x"]
    for elsewhere in (world.b.slug, world.root.slug):
        refused = clerk.get(ORGANIZATIONS, headers={"x-org": elsewhere})
        assert refused.status_code == 403, refused.content
        assert code(refused) == "addressing_header_not_honoured"
