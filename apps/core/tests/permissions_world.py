"""The one permission world, and the census both trees answer.

**Why a module and not a `conftest.py`.** Every later rung in this lane needs
the same tree, the same people and the same census, and a `conftest.py` is a
file several rungs would append to at once — the append-collision class. This
is an ordinary module: a rung imports what it needs and adds a function beside
the ones already here.

Two things live here and they are deliberately different shapes:

* **`build_world(...)`** — the tree the resolution tests drive: `root → A →
  A1 → A1X` and a sibling `B`, with one person per state the blueprint names.
  It is built by services, never by raw writes, so the world a test reasons
  about is a world the product can actually reach.
* **`census(keys, actors)`** — `allows(actor, key, None)` for every key × every
  named actor, as plain JSON-shaped data. It is the same function on both
  trees, which is the whole point: a baseline is DERIVED by running it on a
  scratch clone of the older tree rather than typed from a reading of it, and
  the test re-runs it here and compares.

**Deriving `flat_product_baseline.json`** (the command its own header names),
in place, on the tree whose answers it records:

```bash
uv run python manage.py shell -c \
  "from apps.core.tests.permissions_world import write_flat_product_baseline as w; \
   w('apps/core/tests/flat_product_baseline.json')"
```

`apps/core/tests/test_flat_baseline_document.py` runs the same writer in-process
and diffs its answer against the committed file, so a document its writer would
no longer produce is a red naming the keys, and the remedy is this command.

The writer writes the FILE rather than printing it, because `manage.py shell`
prints a banner of its own on stdout and a redirect would bake it into the
document — a baseline nobody can re-derive byte for byte is a baseline that
stops being checked.

`flat_product_census` writes rows, so it is run against a SCRATCH checkout's
own derived database (`scripts/db.sh`) and never against a shared one. Under
pytest the same function runs inside the test transaction and is rolled back.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import allows
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import (
    add_membership,
    create_organization,
    create_tenant,
    root_organization,
)

#: The three roles the flat-product census asks about. `owner` is the platform
#: role; `admin` and `member` are the template's declarations. A product that
#: declared others would widen this list and re-derive its own baseline.
FLAT_ROLES: tuple[str, ...] = ("owner", "admin", "member")

PASSWORD = "census-pass-1234"  # pragma: allowlist secret

#: The tree `flat_product_baseline.json` was derived on, and the command that
#: derived it — carried INTO the document so the file says how to re-make
#: itself. A baseline whose provenance lives only in a report is a baseline
#: nobody re-derives. Re-derived IN PLACE: the document records this tree's
#: answers, and `test_flat_baseline_document.py` holds it to them.
BASELINE_SHA = "e85a5057"
BASELINE_COMMAND = (
    "uv run python manage.py shell -c "
    '"from apps.core.tests.permissions_world import write_flat_product_baseline as w; '
    "w('apps/core/tests/flat_product_baseline.json')\""
)


# --- the census ---------------------------------------------------------------


def declared_action_keys() -> list[str]:
    """Every action name THIS tree declares, read off the apps' own declarations.

    `policies()` and `action_prose()` are the two halves an app declares, and
    both exist on every tree this census runs on — which is what lets one
    function derive the key list on the old tree and on the new one. It is
    deliberately NOT `vocabulary()`: that mapping is younger than the baseline,
    so asking for it there would be asking the older tree a question it has no
    word for.
    """
    from apps.core import authz

    return sorted(set(authz.policies()) | set(authz.action_prose()))


def read_action_keys() -> list[str]:
    """`<kind>.read` for every kind the registry names. **The Phase R half.**

    Reads are DERIVED keys — nobody types them, the model registry produces
    them — so `declared_action_keys()` above has never seen one, and the census
    was blind to exactly the population Phase R moves. These 36 keys × 3 roles
    are the 108 cells that say "a product that customised nothing observes no
    change": all True before the flip (the free branch) and all True after it
    (`owner` is the vocabulary, `admin` is `*`, `member` is `*.read`).

    This is why the baseline moved from `eb88c9db` to `ae19beab`: the older
    tree had no `kind_registry()` to ask, so the read half could not be derived
    there at all. The WRITE cells are byte-identical across the re-derivation,
    which is the check that says the move added rows rather than changing any.
    """
    from apps.core import authz

    return sorted(f"{kind}.read" for kind in authz.kind_registry())


def census(keys: Sequence[str], actors: Mapping[str, Actor]) -> dict[str, dict[str, bool]]:
    """`allows(actor, key, None)` for every key × every named actor.

    `obj=None` on purpose: this is the ABSTRACT cell — "may this person do this
    kind of thing here at all" — which is the only cell that can be asked of
    every key without inventing a row per kind. The per-row cells belong to
    each app's own sweep, and the criteria say so.
    """
    return {
        str(key): {
            name: bool(allows(actor, str(key), None)) for name, actor in sorted(actors.items())
        }
        for key in sorted(keys)
    }


def flat_product_census(*, keys: Sequence[str] | None = None) -> dict[str, Any]:
    """The whole baseline document: the keys, the roles, and every answer.

    A **flat product** is the state the criteria pin: one tenant, one node, no
    `Role`, no `RolePermission` and no `Grant` row anywhere — the deployment a
    product that customised nothing is running. Three people, one per role.
    """
    tenant, actors = flat_world()
    chosen = (
        list(keys)
        if keys is not None
        else sorted(set(declared_action_keys()) | set(read_action_keys()))
    )
    return {
        "_": (
            "DERIVED, never typed. Every cell is `allows(actor, key, obj=None)` on a FLAT "
            "product: one tenant, one node, no Role, RolePermission or Grant row, one "
            "person per role. The test re-runs the same census on this tree and asserts "
            "equality; a moved answer prints (key, role, before, after)."
        ),
        "_baseline": BASELINE_SHA,
        "_command": BASELINE_COMMAND,
        "roles": list(FLAT_ROLES),
        "answers": census(chosen, actors),
    }


def write_flat_product_baseline(path: str) -> str:
    """Derive the census and write it as the JSON document, sorted and stable."""
    import json
    from pathlib import Path

    target = Path(path)
    target.write_text(
        json.dumps(flat_product_census(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return str(target)


def flat_world() -> tuple[Tenant, dict[str, Actor]]:
    """One tenant, one node, one person per role. No permission rows at all."""
    suffix = uuid.uuid4().hex[:8]
    tenant = create_tenant(name=f"Census {suffix}", slug=f"census-{suffix}", actor=system_actor())
    root = root_organization(tenant=tenant)
    actors: dict[str, Actor] = {}
    for role in FLAT_ROLES:
        user = create_user(email=f"{role}-{suffix}@example.com", password=PASSWORD)
        add_membership(
            user=user,
            tenant=tenant,
            organization=root,
            role=role,
            actor=system_actor(tenant=tenant),
        )
        actors[role] = actor_for(user=user, tenant=tenant, org=root)
    return tenant, actors


# --- the tree the resolution tests drive ---------------------------------------


@dataclass(frozen=True)
class World:
    """`root → A → A1 → A1X`, a sibling `B`, and one person per named state.

    Every field is a row a service made. The names are the blueprint's, so a
    criterion that says "an admin at A asked at A1X" reads as one line of test.
    """

    tenant: Tenant
    root: Organization
    a: Organization
    a1: Organization
    a1x: Organization
    b: Organization

    owner: Actor
    admin_at_a: Actor
    member: Actor
    approver: Actor
    roleless: Actor

    owner_membership: Membership
    admin_membership: Membership
    member_membership: Membership
    approver_root_membership: Membership
    approver_a_membership: Membership
    roleless_membership: Membership


def build_world(*, approver_key: str = "approver") -> World:
    """Build the whole world through services. Every hat is the node named.

    `approver_key` is a CUSTOM role — a `Role` row of this tenant, with its
    collection assembled out of `RolePermission` include rows. It is created by
    a raw write on purpose: the services that hand roles out are P4's, and the
    criteria say a raw create is legal until they land.
    """
    from apps.core.models import Role, RolePermission

    suffix = uuid.uuid4().hex[:8]
    tenant = create_tenant(name=f"World {suffix}", slug=f"world-{suffix}", actor=system_actor())
    system = system_actor(tenant=tenant)
    root = root_organization(tenant=tenant)
    a = create_organization(tenant=tenant, parent=root, name="A", slug="a", actor=system)
    a1 = create_organization(tenant=tenant, parent=a, name="A1", slug="a1", actor=system)
    a1x = create_organization(tenant=tenant, parent=a1, name="A1X", slug="a1x", actor=system)
    b = create_organization(tenant=tenant, parent=root, name="B", slug="b", actor=system)

    def person(label: str) -> Any:
        return create_user(email=f"{label}-{suffix}@example.com", password=PASSWORD)

    owner_user = person("owner")
    owner_membership = add_membership(
        user=owner_user, tenant=tenant, organization=root, role="owner", actor=system
    )
    admin_user = person("admin")
    admin_membership = add_membership(
        user=admin_user, tenant=tenant, organization=a, role="admin", actor=system
    )
    member_user = person("member")
    member_membership = add_membership(
        user=member_user, tenant=tenant, organization=root, role="member", actor=system
    )

    # The custom role, and the person who holds it AT A while holding `member`
    # at the root — the two-roles-on-the-path case the blueprint names.
    Role.objects.create(tenant=tenant, key=approver_key, name="Approver")
    RolePermission.objects.create(
        tenant=tenant,
        role_key=approver_key,
        permission="widget.approve",
        effect=RolePermission.Effect.INCLUDE,
    )
    approver_user = person("approver")
    approver_root_membership = add_membership(
        user=approver_user, tenant=tenant, organization=root, role="member", actor=system
    )
    approver_a_membership = add_membership(
        user=approver_user, tenant=tenant, organization=a, role=approver_key, actor=system
    )

    roleless_user = person("roleless")
    roleless_membership = add_membership(
        user=roleless_user, tenant=tenant, organization=b, role="", actor=system
    )

    return World(
        tenant=tenant,
        root=root,
        a=a,
        a1=a1,
        a1x=a1x,
        b=b,
        owner=actor_for(user=owner_user, tenant=tenant, org=root),
        admin_at_a=actor_for(user=admin_user, tenant=tenant, org=a),
        member=actor_for(user=member_user, tenant=tenant, org=root),
        approver=actor_for(user=approver_user, tenant=tenant, org=a),
        roleless=actor_for(user=roleless_user, tenant=tenant, org=b),
        owner_membership=owner_membership,
        admin_membership=admin_membership,
        member_membership=member_membership,
        approver_root_membership=approver_root_membership,
        approver_a_membership=approver_a_membership,
        roleless_membership=roleless_membership,
    )
