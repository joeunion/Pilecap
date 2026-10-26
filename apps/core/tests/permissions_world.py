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
  about is a world the product can actually reach. **It is the one world**: a
  test that needs a tree with people in it imports it (the accounts sweep and
  matrix do) rather than declaring a `class World` of its own — the per-app
  worlds retire in their own apps' rungs.
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

import importlib
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.test import Client

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import OWNER_ROLE, allows, role_declarations
from apps.core.discovery import declared
from apps.core.models import Membership, Organization, Tenant
from apps.core.roads import road
from apps.core.scaffold.baseline import BASELINE_COMMAND as BASELINE_COMMAND
from apps.core.scaffold.baseline import (
    BASELINE_MISSING,
    BASELINE_WRITE,
    BASELINE_WRITTEN,
    NOUN_SWEEP,
)
from apps.core.services import (
    add_membership,
    create_organization,
    create_tenant,
    root_organization,
)


def platform_labels() -> frozenset[str]:
    """The census's population: `quality/partition.yaml`'s platform apps, never a product's."""
    from quality.partition import platform_apps

    return frozenset(platform_apps())


def _product_kinds() -> frozenset[str]:
    """The kinds whose model a product app owns."""
    from apps.core import authz

    platform = platform_labels()
    return frozenset(
        kind
        for kind, model in authz.kind_registry().items()
        if model._meta.app_label not in platform
    )


def _product_declared() -> frozenset[str]:
    """The action keys a product app's `policies.py` declares."""
    platform = platform_labels()
    return frozenset(
        str(key)
        for attribute in ("POLICIES", "ACTION_PROSE")
        for config, found in declared("policies", attribute)
        if config.label not in platform
        for key in found
    )


def platform_keys(actions: Iterable[str]) -> list[str]:
    """Those of `actions` neither declared by a product app nor about a kind one owns, sorted."""
    declared_there, kinds_there = _product_declared(), _product_kinds()
    return sorted(
        action
        for action in actions
        if action not in declared_there and action.split(".", 1)[0] not in kinds_there
    )


#: The roles the flat-product census asks about: `owner`, the platform role, and
#: every role a platform app declares — `admin` and `member` in `core`, and
#: whatever an app beside it declares (the worked customer surface declares
#: `customer`). Derived from the registry, so a declared role widens the census by
#: itself and the baseline is re-derived with its header's command.
def flat_roles() -> tuple[str, ...]:
    """`owner`, then every platform-declared role key, in registry order."""
    from apps.core.authz import role_declarers

    platform = platform_labels()
    by = role_declarers()
    return (OWNER_ROLE, *(role for role in role_declarations() if by[role] in platform))


PASSWORD = "census-pass-1234"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret

#: The tree `flat_product_baseline.json` was derived on, and the command that
#: derived it — carried INTO the document so the file says how to re-make
#: itself. A baseline whose provenance lives only in a report is a baseline
#: nobody re-derives. Re-derived IN PLACE: the document records this tree's
#: answers, and `test_flat_baseline_document.py` holds it to them.
BASELINE_SHA = "68b1b8c0"


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

    return platform_keys(set(authz.policies()) | set(authz.action_prose()))


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

    product = _product_kinds()
    return sorted(f"{kind}.read" for kind in authz.kind_registry() if kind not in product)


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


#: Where an app declares its object axis: `apps/<label>/tests/authz_objects.py::OBJECTS`.
OBJECTS_MODULE = "tests.authz_objects"


def object_providers() -> dict[str, Callable[[Tenant], Mapping[str, Any]]]:
    """`{kind: provider}` from every installed app's `OBJECTS`; a provider answers `{state: row}`.

    A provider writes its rows raw in the flat tenant: a service would ask the keys measured.
    """
    from django.apps import apps as django_apps

    found: dict[str, Callable[[Tenant], Mapping[str, Any]]] = {}
    platform = platform_labels()
    for config in django_apps.get_app_configs():
        if config.label not in platform:
            continue
        try:
            module = importlib.import_module(f"{config.name}.{OBJECTS_MODULE}")
        except ModuleNotFoundError:
            continue
        found.update(getattr(module, "OBJECTS", {}))
    return found


def object_census(
    tenant: Tenant, keys: Sequence[str], actors: Mapping[str, Actor]
) -> dict[str, dict[str, dict[str, bool]]]:
    """`key → role → state → allows(actor, key, row)` for every key whose kind has a provider."""
    providers = object_providers()
    rows = {kind: dict(provide(tenant)) for kind, provide in sorted(providers.items())}
    return {
        str(key): {
            name: {
                state: bool(allows(actor, str(key), row))
                for state, row in sorted(rows[str(key).split(".", 1)[0]].items())
            }
            for name, actor in sorted(actors.items())
        }
        for key in sorted(keys)
        if str(key).split(".", 1)[0] in rows
    }


def residue() -> dict[str, list[str]]:
    """Per declared role, the keys its `default_roles` column lists beyond its declaration.

    A key is residue for a role when the vocabulary's `default_roles` column
    lists the role and the role's own declaration (`defaults_for`: its patterns
    and the `DEFAULT_ROLES` entries naming it) does not. Clause (5) of
    `authz._attach_default_roles` was what put keys there and is retired,
    so every list is `[]`, and the committed document is where that is read: a
    list that GREW is a diff a reviewer sees.
    """
    from apps.core.authz import defaults_for, grantable_permissions, vocabulary

    words = vocabulary()
    grantable = platform_keys(grantable_permissions())
    found: dict[str, list[str]] = {}
    for role in flat_roles()[1:]:
        declared = defaults_for(role)
        found[role] = sorted(
            action
            for action in grantable
            if role in words[action].default_roles and action not in declared
        )
    return found


def flat_product_census(*, keys: Sequence[str] | None = None) -> dict[str, Any]:
    """The whole baseline document: the keys, the roles, every answer, and the residue.

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
            "person per role; `objects` asks the same keys of the rows an app's "
            "`tests/authz_objects.py` provides. The test re-runs the same census on this "
            "tree and asserts equality; a moved answer prints (key, role, before, after)."
        ),
        "_baseline": BASELINE_SHA,
        "_command": BASELINE_COMMAND,
        "roles": list(flat_roles()),
        "answers": census(chosen, actors),
        "objects": object_census(tenant, chosen, actors),
        "residue": residue(),
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


def flat_world(roles: Sequence[str] | None = None) -> tuple[Tenant, dict[str, Actor]]:
    """One tenant, one node, one person per role (default `flat_roles()`); no permission rows."""
    suffix = uuid.uuid4().hex[:8]
    tenant = create_tenant(name=f"Census {suffix}", slug=f"census-{suffix}", actor=system_actor())
    root = root_organization(tenant=tenant)
    actors: dict[str, Actor] = {}
    for role in flat_roles() if roles is None else roles:
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


def drift(committed: dict[str, Any], derived: dict[str, Any]) -> list[str]:
    """One line per difference between two census documents: added, removed, moved, roles."""
    before: dict[str, dict[str, bool]] = committed["answers"]
    after: dict[str, dict[str, bool]] = derived["answers"]
    lines = [f"added    {key}" for key in sorted(set(after) - set(before))]
    lines += [f"removed  {key}" for key in sorted(set(before) - set(after))]
    lines += [
        f"moved    {key} · {role}: {before[key].get(role)} -> {after[key].get(role)}"
        for key in sorted(set(before) & set(after))
        for role in sorted(set(before[key]) | set(after[key]))
        if before[key].get(role) != after[key].get(role)
    ]
    held_rows: dict[str, Any] = committed.get("objects", {})
    rows: dict[str, Any] = derived.get("objects", {})
    lines += [f"object   {key}" for key in sorted(set(held_rows) ^ set(rows))]
    lines += [
        f"object   {key} moved"
        for key in sorted(set(held_rows) & set(rows))
        if held_rows[key] != rows[key]
    ]
    if committed.get("roles") != derived["roles"]:
        lines.append(f"roles    {committed.get('roles')} -> {derived['roles']}")
    held: dict[str, list[str]] = committed.get("residue", {})
    left: dict[str, list[str]] = derived.get("residue", {})
    for role in sorted(set(held) | set(left)):
        lines += [
            f"residue  {role} grew: {key}"
            for key in sorted(set(left.get(role, [])) - set(held.get(role, [])))
        ]
        lines += [
            f"residue  {role} swept: {key}"
            for key in sorted(set(held.get(role, [])) - set(left.get(role, [])))
        ]
    return lines


# --- a noun's own matrix: the product's roles x the noun's keys, against its own file ------------


def noun_roles() -> tuple[str, ...]:
    """`owner`, then every declared role key — the platform's and the product's alike."""
    return (OWNER_ROLE, *role_declarations())


def noun_keys(model: type[Any]) -> list[str]:
    """The keys `model`'s kind declares in any `POLICIES`, and its derived `<kind>.read`."""
    from apps.core import authz

    kind = next(k for k, m in authz.kind_registry().items() if m is model)
    return sorted({k for k in authz.policies() if k.split(".", 1)[0] == kind} | {f"{kind}.read"})


def noun_census(model: type[Any], row: Callable[[Tenant, Any], Any]) -> dict[str, Any]:
    """`key -> role -> allows` on a flat product: no row, `<role> · own` and `<role> · other`."""
    roles = noun_roles()
    tenant, actors = flat_world(roles)
    stranger = create_user(email=f"stranger-{uuid.uuid4().hex[:8]}@example.com", password=PASSWORD)
    other = row(tenant, stranger)
    own = {name: row(tenant, actor.user) for name, actor in actors.items() if actor.user}
    answers: dict[str, dict[str, bool]] = {}
    for key in noun_keys(model):
        cells: dict[str, bool] = {}
        for name, actor in sorted(actors.items()):
            cells[name] = bool(allows(actor, key, None))
            cells[f"{name} · own"] = bool(allows(actor, key, own[name]))
            cells[f"{name} · other"] = bool(allows(actor, key, other))
        answers[key] = cells
    return {
        "_": (
            "DERIVED, never typed. Every cell is `allows(actor, key, obj)` on a flat product: "
            "every declared role x the noun's keys x {no row, own row, another's row}. Remake "
            "it by running its sweep with DJB_BASELINE_WRITE=1; read the diff before committing."
        ),
        "roles": list(roles),
        "answers": answers,
    }


def settle_baseline(path: Path, derived: dict[str, Any]) -> list[str]:
    """The drift from the committed file; asked to write (`DJB_BASELINE_WRITE`), written and []."""
    import json
    import os

    import pytest
    from django.conf import settings

    base = Path(settings.BASE_DIR)
    shown = path.relative_to(base) if path.is_relative_to(base) else path
    if os.environ.get(BASELINE_WRITE):
        path.write_text(json.dumps(derived, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(BASELINE_WRITTEN.format(path=shown))
        return []
    if not path.is_file():
        sweep = shown.parent.parent / NOUN_SWEEP
        pytest.fail(BASELINE_MISSING.format(path=shown, sweep=sweep), pytrace=False)
    return drift(json.loads(path.read_text(encoding="utf-8")), derived)


# --- the tree the resolution tests drive ---------------------------------------


@dataclass(frozen=True)
class World:
    """`root → A → A1 → A1X`, sibling `B`, a person per state at their hat; `clerk` at A only."""

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
    clerk: Actor

    owner_membership: Membership
    admin_membership: Membership
    member_membership: Membership
    approver_root_membership: Membership
    approver_a_membership: Membership
    roleless_membership: Membership
    clerk_membership: Membership

    def user(self, who: Actor) -> User:
        """The `User` behind one of this world's people."""
        assert isinstance(who.user, User)
        return who.user

    def session(self, who: Actor) -> Client:
        """A REST client signed in as `who` by the session the browser door holds."""
        client = Client()
        client.force_login(self.user(who))
        return client


@road("permission_world", example="apps/accounts/tests/test_authz_sweep.py::tree")
def build_world(*, approver_key: str = "approver") -> World:
    """Build the whole world through services; each person's hat is their default membership.

    `approver_key` is a custom `Role` row made by a raw write — no service hands roles out yet.
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
        user=owner_user,
        tenant=tenant,
        organization=root,
        role="owner",
        is_default=True,
        actor=system,
    )
    admin_user = person("admin")
    admin_membership = add_membership(
        user=admin_user, tenant=tenant, organization=a, role="admin", is_default=True, actor=system
    )
    member_user = person("member")
    member_membership = add_membership(
        user=member_user,
        tenant=tenant,
        organization=root,
        role="member",
        is_default=True,
        actor=system,
    )

    # Two roles on one path: `member` at the root, the custom role at A (the default).
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
        user=approver_user,
        tenant=tenant,
        organization=a,
        role=approver_key,
        is_default=True,
        actor=system,
    )

    roleless_user = person("roleless")
    roleless_membership = add_membership(
        user=roleless_user, tenant=tenant, organization=b, role="", is_default=True, actor=system
    )
    clerk_user = person("clerk")
    clerk_membership = add_membership(
        user=clerk_user, tenant=tenant, organization=a, role="member", is_default=True, actor=system
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
        clerk=actor_for(user=clerk_user, tenant=tenant, org=a),
        owner_membership=owner_membership,
        admin_membership=admin_membership,
        member_membership=member_membership,
        approver_root_membership=approver_root_membership,
        approver_a_membership=approver_a_membership,
        roleless_membership=roleless_membership,
        clerk_membership=clerk_membership,
    )


#: The names the clerk had before it joined `World`; kept one release for `djb_tags`' `TagWorld`.
BranchWorld = World
build_branch_world = build_world
