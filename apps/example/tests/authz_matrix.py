"""The example app's authorization matrix, and the census that derives it.

**Why this module and not `apps/core/tests/permissions_world.py::census`.** The
core census asks one cell per key — `allows(actor, key, None)`, the abstract
question — because that is the only cell that can be asked of every key in the
deployment without inventing a row per kind. A sweep over ONE app can do better,
and P7.x.2 asks it to: the interesting answers here are about *rows* — the
actor's own, somebody else's in the same branch, somebody else's under an admin's
branch, and somebody else's in a sibling branch — and none of them exist in a
census whose object is always `None`.

So this is the core census's shape (`key → actor → answer`, plain JSON data, the
same function on both trees) with one axis added: the object. It lives in
`apps/example/tests/` because it is about this app's keys and this app's rows,
and because `permissions_world.py` is `core`'s file and a sweep does not edit
another app's territory.

**Deriving `authz_baseline.json`** — the command the document's own header
carries, so the file says how to re-make itself:

```bash
git worktree add <scratch> <baseline sha> --detach
cp apps/example/tests/authz_matrix.py <scratch>/apps/example/tests/authz_matrix.py
cd <scratch> && ./scripts/rung_start.sh && uv run python manage.py shell -c \
  "from apps.example.tests.authz_matrix import write_baseline as w; w('<out>')"
```

The writer writes the FILE rather than printing it, for the reason
`permissions_world.py` gives: `manage.py shell` prints a banner of its own on
stdout and a redirect would bake it into the document.

**The rows are raw writes, deliberately.** `create_widget` asks
`widget.create` — the very key half this matrix censuses — so building the
world through it would make the census depend on the answers it is measuring,
and a sweep that moved `widget.create` would change the *world* rather than the
*answers*. Raw creates are what `permissions_world.build_world` already does for
the same reason (its `Role` rows), and a test module is where a raw write is
legal.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from apps.accounts.services import create_user
from apps.core.actor import Actor
from apps.core.authz import allows
from apps.core.models import Organization, Tenant
from apps.core.tests.permissions_world import PASSWORD, World, build_world
from apps.example.models import Widget

#: The three roles the matrix asks about — the template's declarations plus the
#: platform role, exactly the population `permissions_world.FLAT_ROLES` names.
#: A product that declared others would widen this and re-derive its baseline.
MATRIX_ROLES: tuple[str, ...] = ("owner", "admin", "member")

#: The tree `authz_baseline.json` was derived on, and the command that derived
#: it. Carried INTO the document so a baseline nobody can re-make is impossible.
BASELINE_SHA = "5bf51daa"
BASELINE_COMMAND = (
    "git worktree add <scratch> 5bf51daa --detach && "
    "cp apps/example/tests/authz_matrix.py <scratch>/apps/example/tests/ && "
    "cd <scratch> && ./scripts/rung_start.sh && uv run python manage.py shell -c "
    '"from apps.example.tests.authz_matrix import write_baseline as w; '
    "w('<repo>/apps/example/tests/authz_baseline.json')\""
)


def example_action_keys() -> list[str]:
    """Every key this app declares, read off the app's own declarations.

    `POLICIES` and `ACTION_PROSE` are the two halves an app declares, and both
    exist on every tree this census runs on — which is what lets one function
    derive the key list on the baseline tree and on the swept one. Deliberately
    NOT `vocabulary()`: a sweep RENAMES keys, so asking the vocabulary would ask
    the two trees two different questions, and the renamed key is exactly the
    cell the matrix has to keep answering.

    The old name and the new one are both here by construction — the sweep's
    `RENAMED_PERMISSIONS` keeps the old word answering (`allows` resolves the
    alias before the lookup), so the baseline's `widget_entry.record` row is
    re-asked on the swept tree and must give the same answers.
    """
    from apps.example import policies

    declared = set(policies.POLICIES) | set(policies.ACTION_PROSE)
    declared |= set(getattr(policies, "RENAMED_PERMISSIONS", {}))
    return sorted(declared)


def _widget(*, tenant: Tenant, organization: Organization, owner_id: Any, name: str) -> Widget:
    """One row, written raw. See the module docstring for why it is raw."""
    return Widget.objects.create(
        tenant=tenant, organization=organization, owner_id=owner_id, name=name
    )


def matrix(world: World, actors: Mapping[str, Actor]) -> dict[str, dict[str, dict[str, bool]]]:
    """`key → actor → state → allows(...)`, over the five states P7.x.2 names.

    The states, and what each is for:

    * **`none`** — `obj=None`, the capability in the abstract. The cell a
      row-bound predicate has no row for, and the one the core census already
      asks.
    * **`own`** — a row this actor owns, at this actor's own hat. "A member may
      act on their own records" is the app's first sentence, and this is it.
    * **`other_at_hat`** — somebody else's row at the same node. The second half
      of that sentence: an owner or an admin may act on anyone's.
    * **`other_under_a1`** — somebody else's row at A1, which is *under* the
      admin's branch and under the root. Roles inherit downwards, so this cell
      and the next are how "downwards only" is read.
    * **`other_in_b`** — somebody else's row in the sibling branch B, which the
      admin at A holds nothing over.

    Every cell is `allows`, never `require`: this is the algebra, and the
    refusal grammar the doors speak is `test_reads_ask.py`'s.
    """
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
    """`root → A → A1 → A1X` and a sibling `B`, with one actor per matrix role.

    The tree is `permissions_world.build_world`'s, unchanged — one world, built
    by services, shared by every rung in this lane. The hats are the ones that
    world names: `owner` and `member` at the root, `admin` at A.
    """
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
