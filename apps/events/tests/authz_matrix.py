"""The events app's authorization matrix, and the census that derives it.

The same shape `apps/example/tests/authz_matrix.py` carries, with one axis
smaller, and for the same reason `apps/connections`' is: **every model this
app's keys are about is tenant-scoped, not org-scoped.** `core.authz.where_of`
resolves the node a question is about from the object's `organization`, and a
`WebhookEndpoint` has none (a `Delivery` is not even tenant-scoped — it is
dispatch machinery, read through the event it belongs to). So every cell is
asked at the acting hat whatever object is passed, and a five-state object axis
would be five spellings of one answer.

That is a claim about the models rather than a convenience, so the test beside
this file asserts it.

**Deriving `authz_baseline.json`** — the command the document's own header
carries:

```bash
git worktree add <scratch> <baseline sha> --detach
cp apps/events/tests/authz_matrix.py <scratch>/apps/events/tests/
cd <scratch> && ./scripts/rung_start.sh && uv run python manage.py shell -c \
  "from apps.events.tests.authz_matrix import write_baseline as w; w('<out>')"
```

The rows are raw writes: `register_endpoint` asks `endpoint.create`, which is
one of the keys this matrix censuses, so building the world through it would
make the census depend on the answers it is measuring.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from apps.core.actor import Actor
from apps.core.authz import allows
from apps.core.tests.permissions_world import World, build_world
from apps.events.models import WebhookEndpoint

#: The three roles the matrix asks about — the template's two declarations plus
#: the platform role, exactly the population `permissions_world.FLAT_ROLES` names.
MATRIX_ROLES: tuple[str, ...] = ("owner", "admin", "member")

#: The tree `authz_baseline.json` was derived on, and the command that derived it.
BASELINE_SHA = "2e2b96ad"
BASELINE_COMMAND = (
    "git worktree add <scratch> 2e2b96ad --detach && "
    "cp apps/events/tests/authz_matrix.py <scratch>/apps/events/tests/ && "
    "cd <scratch> && ./scripts/rung_start.sh && uv run python manage.py shell -c "
    '"from apps.events.tests.authz_matrix import write_baseline as w; '
    "w('<repo>/apps/events/tests/authz_baseline.json')\""
)


def events_action_keys() -> list[str]:
    """Every key this app declares, read off the app's own declarations.

    `POLICIES` and `ACTION_PROSE` are the two halves an app declares, and both
    exist on every tree this census runs on — which is what lets one function
    derive the key list on the baseline tree and on the swept one. The RENAMED
    keys are included by construction, because a rename's whole promise is that
    the old word goes on answering, and the baseline's rows are written under
    the old word.
    """
    from apps.events import policies

    declared = set(policies.POLICIES) | set(policies.ACTION_PROSE)
    declared |= set(getattr(policies, "RENAMED_PERMISSIONS", {}))
    return sorted(declared)


def matrix(world: World, actors: Mapping[str, Actor]) -> dict[str, dict[str, dict[str, bool]]]:
    """`key → actor → state → allows(...)`, over the two states that differ here.

    * **`none`** — `obj=None`, the capability in the abstract.
    * **`row`** — a `WebhookEndpoint` of this tenant. It names no organization,
      so the question is asked at the acting hat exactly as `none` is; the cell
      is here so that the day the model grows one, the two stop agreeing and the
      test beside this file says so.
    """
    row = WebhookEndpoint.objects.create(
        tenant=world.tenant,
        url=f"https://census.example.com/{uuid.uuid4().hex[:8]}",
        secret="census-secret-value",  # pragma: allowlist secret
    )
    return {
        key: {
            name: {
                "none": bool(allows(actor, key, None)),
                "row": bool(allows(actor, key, row)),
            }
            for name, actor in sorted(actors.items())
        }
        for key in events_action_keys()
    }


def matrix_world() -> tuple[World, dict[str, Actor]]:
    """`root → A → A1 → A1X` and a sibling `B`, with one actor per matrix role."""
    world = build_world()
    return world, {"owner": world.owner, "admin": world.admin_at_a, "member": world.member}


def census_document() -> dict[str, Any]:
    """The whole baseline document: the provenance, the roles, and every answer."""
    world, actors = matrix_world()
    return {
        "_": (
            "DERIVED, never typed. Every cell is `allows(actor, key, obj)` over the events "
            "app's declared keys x {owner, admin, member} x two object states. The sweep "
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
