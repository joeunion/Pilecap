"""The example app's authorization matrix, and the census that derives it."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from apps.example.models import Widget
from pilecap import Actor
from pilecap.accounts import create_user
from pilecap.tenancy import Organization, Tenant
from pilecap.testing import PASSWORD, World, allows, build_world

#: The roles the matrix asks about: `permissions_world.FLAT_ROLES`.
MATRIX_ROLES: tuple[str, ...] = ("owner", "admin", "member")

#: The tree `authz_baseline.json` was derived on, and the command that derived it.
BASELINE_SHA = "5bf51daa"
BASELINE_COMMAND = (
    "git worktree add <scratch> 5bf51daa --detach && "
    "cp apps/example/tests/authz_matrix.py <scratch>/apps/example/tests/ && "
    "cd <scratch> && ./scripts/rung_start.sh && uv run python manage.py shell -c "
    '"from apps.example.tests.authz_matrix import write_baseline as w; '
    "w('<repo>/apps/example/tests/authz_baseline.json')\""
)


def example_action_keys() -> list[str]:
    """Every key this app declares, read off the app's own declarations."""
    from apps.example import policies

    declared = set(policies.POLICIES) | set(policies.ACTION_PROSE)
    declared |= set(getattr(policies, "RENAMED_PERMISSIONS", {}))
    return sorted(declared)


def _widget(*, tenant: Tenant, organization: Organization, owner_id: Any, name: str) -> Widget:
    """One row, written raw. See the module docstring for why it is raw."""
    return Widget.objects.create(
        tenant=tenant, organization=organization, owner_id=owner_id, name=name
    )


# does-not-cover: per-actor `own` and the A1/B rows need a tree; trigger: core's object axis on one.
def matrix(world: World, actors: Mapping[str, Actor]) -> dict[str, dict[str, dict[str, bool]]]:
    """`key → actor → state → allows(...)`, over the five states P7.x.2 names."""
    stranger = create_user(email=f"stranger-{uuid.uuid4().hex[:8]}@example.com", password=PASSWORD)
    at_hat = {
        name: _widget(
            tenant=world.tenant,
            organization=actor.org or world.root,
            owner_id=stranger.pk,
            name=f"other-at-{name}",
        )
        for name, actor in actors.items()
    }
    under_a1 = _widget(
        tenant=world.tenant, organization=world.a1, owner_id=stranger.pk, name="other-under-a1"
    )
    in_b = _widget(tenant=world.tenant, organization=world.b, owner_id=stranger.pk, name="other-b")

    answers: dict[str, dict[str, dict[str, bool]]] = {}
    for key in example_action_keys():
        per_actor: dict[str, dict[str, bool]] = {}
        for name, actor in sorted(actors.items()):
            own = _widget(
                tenant=world.tenant,
                organization=actor.org or world.root,
                owner_id=actor.user.pk if actor.user is not None else None,
                name=f"own-{name}-{key}",
            )
            per_actor[name] = {
                "none": bool(allows(actor, key, None)),
                "own": bool(allows(actor, key, own)),
                "other_at_hat": bool(allows(actor, key, at_hat[name])),
                "other_under_a1": bool(allows(actor, key, under_a1)),
                "other_in_b": bool(allows(actor, key, in_b)),
            }
        answers[key] = per_actor
    return answers


def matrix_world() -> tuple[World, dict[str, Actor]]:
    """`root → A → A1 → A1X` and a sibling `B`, with one actor per matrix role."""
    world = build_world()
    return world, {"owner": world.owner, "admin": world.admin_at_a, "member": world.member}


def census_document() -> dict[str, Any]:
    """The whole baseline document: the provenance, the roles, and every answer."""
    world, actors = matrix_world()
    return {
        "_": (
            "DERIVED, never typed. Every cell is `allows(actor, key, obj)` over the example "
            "app's declared keys x {owner, admin, member} x five object states. The sweep "
            "re-runs the same census on its own tree and asserts equality; a moved answer "
            "prints (key, actor, state, before, after)."
        ),
        "_baseline": BASELINE_SHA,
        "_command": BASELINE_COMMAND,
        "roles": list(MATRIX_ROLES),
        "answers": matrix(world, actors),
    }


def write_baseline(path: str) -> str:
    """Derive the census and write it as the JSON document, sorted and stable."""
    import json
    from pathlib import Path

    target = Path(path)
    target.write_text(
        json.dumps(census_document(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return str(target)
