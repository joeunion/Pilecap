"""The connections app's authorization matrix, and the census that derives it.

The same shape `apps/example/tests/authz_matrix.py` carries, with one axis
smaller, and the difference is the app rather than the author: **`Connection`
and `InboundWebhook` are tenant-scoped, not org-scoped.** `core.authz.where_of`
resolves the node a question is about from the object's `organization`, and
these rows have none — so every cell here is asked at the acting hat whatever
object is passed, and a five-state object axis would be five spellings of one
answer. The states below are the two that differ: no row at all, and a row of
this tenant.

That is a claim about the models rather than a convenience, so the test beside
this file asserts it: if `Connection` ever grows an organization, the extra
states stop being redundant and the matrix has to grow with them.

**Deriving `authz_baseline.json`** — the command the document's own header
carries:

```bash
git worktree add <scratch> <baseline sha> --detach
cp apps/connections/tests/authz_matrix.py <scratch>/apps/connections/tests/
cd <scratch> && ./scripts/rung_start.sh && uv run python manage.py shell -c \
  "from apps.connections.tests.authz_matrix import write_baseline as w; w('<out>')"
```

The rows are raw writes: `create_connection` asks `connection.create`, which is
one of the keys this matrix censuses, so building the world through it would
make the census depend on the answers it is measuring.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from apps.connections.models import Connection
from apps.core.actor import Actor
from apps.core.authz import allows
from apps.core.tests.permissions_world import World, build_world

#: The three roles the matrix asks about — the template's two declarations plus
#: the platform role, exactly the population `permissions_world.FLAT_ROLES` names.
MATRIX_ROLES: tuple[str, ...] = ("owner", "admin", "member")

#: The tree `authz_baseline.json` was derived on, and the command that derived it.
BASELINE_SHA = "2e2b96ad"
BASELINE_COMMAND = (
    "git worktree add <scratch> 2e2b96ad --detach && "
    "cp apps/connections/tests/authz_matrix.py <scratch>/apps/connections/tests/ && "
    "cd <scratch> && ./scripts/rung_start.sh && uv run python manage.py shell -c "
    '"from apps.connections.tests.authz_matrix import write_baseline as w; '
    "w('<repo>/apps/connections/tests/authz_baseline.json')\""
)


def connections_action_keys() -> list[str]:
    """Every key this app declares, read off the app's own declarations.

    `POLICIES` and `ACTION_PROSE` are the two halves an app declares, and both
    exist on every tree this census runs on — which is what lets one function
    derive the key list on the baseline tree and on the swept one. Deliberately
    NOT `vocabulary()`: that mapping is the whole deployment's, and this census
    is about one app.
    """
    from apps.connections import policies

    declared = set(policies.POLICIES) | set(policies.ACTION_PROSE)
    declared |= set(getattr(policies, "RENAMED_PERMISSIONS", {}))
    return sorted(declared)


def matrix(world: World, actors: Mapping[str, Actor]) -> dict[str, dict[str, dict[str, bool]]]:
    """`key → actor → state → allows(...)`, over the two states that differ here.

    * **`none`** — `obj=None`, the capability in the abstract.
    * **`row`** — a `Connection` of this tenant. It names no organization, so
      the question is asked at the acting hat exactly as `none` is; the cell is
      here so that the day the model grows one, the two stop agreeing and the
      test beside this file says so.
    """
    row = Connection.objects.create(
        tenant=world.tenant,
        provider="census",
        name=f"census-{uuid.uuid4().hex[:8]}",
        status=Connection.Status.CONNECTED,
    )
    return {
        key: {
            name: {
                "none": bool(allows(actor, key, None)),
                "row": bool(allows(actor, key, row)),
            }
            for name, actor in sorted(actors.items())
        }
        for key in connections_action_keys()
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
            "DERIVED, never typed. Every cell is `allows(actor, key, obj)` over the "
            "connections app's declared keys x {owner, admin, member} x two object states. "
            "The sweep re-runs the same census on its own tree and asserts equality; a "
            "moved answer prints (key, actor, state, before, after)."
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
