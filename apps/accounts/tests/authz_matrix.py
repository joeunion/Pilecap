"""The accounts app's authorization matrix, and the census that derives it.

The same shape `apps/files/tests/test_authz_sweep.py` carries, split into its
own module the way `apps/example/tests/authz_matrix.py` is — because this file
has to be COPIED onto the baseline tree to derive the document, and a module
that carries no tests copies without dragging a test suite with it.

**Why the row axis is eight states here and two in `events`.** Every model this
app's keys are about is tenant-scoped or not scoped at all — a `User` belongs to
several tenants and to none, an `SsoConnection` names no organization — so
`core.authz.where_of` falls back to the acting hat for all of them. But three of
this app's keys are asked with an `Organization` as the object (the SSO services
pass `root_organization(tenant=tenant)`), and an `Organization` IS its own node.
So the node axis is real here even though no row carries an FK to one, and the
classes below are the ones that separate the answers: the root, the branch an
admin administers, and a sibling branch where nobody holds anything.

The `User` classes are the other half: `themselves` reads the row, so the
actor's OWN user and somebody else's are two different questions and always
were.

**Deriving `authz_baseline.json`** — the command the document's own header
carries:

```bash
git worktree add <scratch> <baseline sha> --detach
cp apps/accounts/tests/authz_matrix.py <scratch>/apps/accounts/tests/
cd <scratch> && ./scripts/rung_start.sh && uv run python manage.py shell -c \
  "from apps.accounts.tests.authz_matrix import write_baseline as w; w('<out>')"
```

The rows are raw writes on purpose: `create_sso_connection` asks
`sso_connection.create`, which is one of the keys this matrix censuses, so
building the world through it would make the census depend on the answers it is
measuring. `permissions_world` makes the same call about its `Role` rows.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from apps.accounts.models import SsoConnection
from apps.accounts.services import create_user
from apps.core.actor import Actor, system_actor
from apps.core.authz import allows
from apps.core.services import add_membership
from apps.core.tests.permissions_world import PASSWORD, World, build_world

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

#: The nine keys this app answered for on the baseline tree, by the names it had
#: there. The sweep renames four of them and `RENAMED_PERMISSIONS` is what keeps
#: the old words answering — so the census asks the OLD names on both trees, and
#: a cell that moved because an alias does not answer is exactly what this is
#: here to catch.
KEYS: tuple[str, ...] = (
    "accounts.user.deactivate",
    "accounts.user.erase",
    "identity_platform.configure",
    "sso_connection.create",
    "sso_connection.disable",
    "sso_connection.update",
    "sso_domain.verify",
    "sso_identity.provision",
    "user.unlink",
)

#: The three people, by the name `permissions_world.build_world` gives them.
ACTORS: tuple[str, ...] = ("admin_at_a", "member", "owner")

#: The tree this document was derived on, and the command that derived it.
BASELINE_SHA = "9ba0c429"
BASELINE_COMMAND = (
    "git worktree add <scratch> 9ba0c429 --detach && "
    "cp apps/accounts/tests/authz_matrix.py <scratch>/apps/accounts/tests/ && "
    "cd <scratch> && ./scripts/rung_start.sh && uv run python manage.py shell -c "
    '"from apps.accounts.tests.authz_matrix import write_baseline as w; '
    "w('<repo>/apps/accounts/tests/authz_baseline.json')\"   # before the sweep"
)

BASELINE_PATH = "apps/accounts/tests/authz_baseline.json"


# does-not-cover: per-actor `own_user`, A/B, cross-kind rows; trigger: core's object axis on a tree.
def accounts_rows(world: World) -> dict[str, dict[str, Any]]:
    """Row class → actor name → the object the question is asked about.

    * **`no_row`** — `obj=None`, the capability in the abstract.
    * **`own_user`** — the actor's own `User`, which is the row the `themselves`
      half of the account wall reads.
    * **`other_user`** — somebody else who belongs to this tenant at the root.
    * **`root_org`** — the tenant's root `Organization`, the node the four SSO
      services resolve and hand to `require`.
    * **`admin_branch`** — `A`, the branch the admin of this world administers.
    * **`sibling_branch`** — `B`, where none of the three holds anything.
    * **`connection`** — an `SsoConnection` of this tenant: tenant-scoped, names
      no organization, so it resolves to the acting hat. The cell is here so the
      day the model grows a node the two stop agreeing.
    * **`tenant`** — the `Tenant` row itself, which is what
      `sync_workforce_identity_config` hands the deployment key.
    """
    suffix = uuid.uuid4().hex[:8]
    other = create_user(email=f"census-other-{suffix}@example.com", password=PASSWORD)
    add_membership(
        user=other,
        tenant=world.tenant,
        organization=world.root,
        role="member",
        actor=system_actor(tenant=world.tenant),
    )
    connection = SsoConnection.objects.create(
        tenant=world.tenant,
        name=f"Census {suffix}",
        metadata={},
    )
    people = {
        "admin_at_a": world.admin_at_a.user,
        "member": world.member.user,
        "owner": world.owner.user,
    }
    return {
        "no_row": dict.fromkeys(ACTORS, None),
        "own_user": {name: people[name] for name in ACTORS},
        "other_user": dict.fromkeys(ACTORS, other),
        "root_org": dict.fromkeys(ACTORS, world.root),
        "admin_branch": dict.fromkeys(ACTORS, world.a),
        "sibling_branch": dict.fromkeys(ACTORS, world.b),
        "connection": dict.fromkeys(ACTORS, connection),
        "tenant": dict.fromkeys(ACTORS, world.tenant),
    }


def matrix(world: World) -> dict[str, dict[str, dict[str, bool]]]:
    """`key → row class → actor → allows(...)`. The same function on both trees."""
    rows = accounts_rows(world)
    actors: dict[str, Actor] = {
        "admin_at_a": world.admin_at_a,
        "member": world.member,
        "owner": world.owner,
    }
    return {
        key: {
            row_class: {
                name: bool(allows(actors[name], key, rows[row_class][name])) for name in ACTORS
            }
            for row_class in sorted(rows)
        }
        for key in KEYS
    }


def census_document() -> dict[str, Any]:
    """The whole baseline document: the provenance, the shape and every answer."""
    world = build_world()
    return {
        "_": (
            "DERIVED, never typed. Every cell is `allows(actor, key, row)` over the `accounts` "
            "keys as the baseline tree spelled them, the three roles of "
            "`permissions_world.build_world`, and the row classes `authz_matrix.accounts_rows` "
            "names. The sweep re-runs the same function on its own tree and asserts equality; "
            "a moved cell prints (key, row class, actor, before, after)."
        ),
        "_baseline": BASELINE_SHA,
        "_command": BASELINE_COMMAND,
        "accepted_deltas": {},
        "actors": list(ACTORS),
        "keys": list(KEYS),
        "answers": matrix(world),
    }


def write_baseline(path: str) -> str:
    """Derive the census and write it, sorted and stable. **Writes rows.**

    Run inside a rolled-back transaction by the deriving command, so a
    checkout's own database is not left carrying a census world. The FILE is
    written rather than printed because `manage.py shell` puts a banner on
    stdout and a redirect would bake it into the document.
    """
    target = Path(path)
    target.write_text(json.dumps(census_document(), indent=2, sort_keys=True) + "\n", "utf-8")
    return str(target)


def read_baseline(base_dir: str) -> Mapping[str, Any]:
    """The committed document, read off disk. One reader, two tests."""
    document: dict[str, Any] = json.loads((Path(base_dir) / BASELINE_PATH).read_text())
    return document
