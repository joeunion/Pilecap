"""P7.5 — the `exports` sweep, **measured rather than argued**.

The sweep drops the role half out of this app's predicates and puts what a
`member` may do into `DEFAULT_ROLES`, where it is data with one owner. The
claim that has to survive that move is not "the code reads better": it is that
**every answer this app gave before it, it gives after it** — and the only
honest way to make that claim is to run one function on both trees and compare.

So this module carries three things:

* **`matrix(world)`** — `allows(actor, key, row)` over the app's keys × the
  three roles × the row classes below, as plain JSON-shaped data. One function,
  two trees.
* **`write_baseline(path)`** — the deriver. It is run on the sweep's BASELINE
  tree and its output is committed beside this file as `authz_baseline.json`,
  with the command that made it carried inside the document (a baseline nobody
  can re-derive is a baseline that stops being checked).
* **the tests** — the matrix re-run here equals that document; the app's
  `policies.py` reads no role; the alias still answers.

**The row classes, and why these.** A predicate that reads a row can only be
proven right by being asked about rows of every shape it distinguishes. This
app's one row-reading bar is `can_request`'s "a tenant-wide export takes an
administrator at the top", and the node bars come from `where_of`, so the
classes are: no row at all (the abstract question), the actor's own row at
their own hat, somebody else's row deeper inside the hat's subtree, a row in a
sibling branch where the actor holds nothing, a row in the branch an admin
administers, and the two export SCOPES at the root. A class this list does not
name is a class this census does not see, and `docs` says so in the blind spots.

**The keys are the BASELINE's names on purpose** (`export.request`, not
`export.create`). The rename is an alias under the immutable key — a caller
still saying the old word gets exactly the old answer — so asking the old names
is asking the question the sweep promised not to change. `export.create` is
asserted separately, against its alias, below.

**A stored row still carrying the old key goes inert until it is rewritten.**
The alias answers for CODE that says `export.request`; a `Grant` or a
`RolePermission` ROW holding that string is a key the collection no longer
matches, and `manage.py rename_permission` is what rewrites it. This tree has no
such rows; a deployment with them runs the command.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from django.conf import settings

from apps.core.actor import Actor, actor_for
from apps.core.authz import allows
from apps.core.tests.permissions_world import PASSWORD, World, build_world
from apps.exports.models import Export

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

#: The three keys this app answered for on the baseline tree. Asked by their
#: OLD names: `export.request` resolves through `RENAMED_PERMISSIONS` after the
#: sweep, and a cell that moved because the alias does not answer is a cell
#: this census is meant to catch.
KEYS: tuple[str, ...] = ("export.build", "export.read", "export.request")

#: The three people, by the name `permissions_world.build_world` gives them.
ACTORS: tuple[str, ...] = ("admin_at_a", "member", "owner")

#: The tree this document was derived on, and the command that derived it.
BASELINE_SHA = "11b1a765"
BASELINE_COMMAND = (
    "uv run python manage.py shell -c "
    '"from apps.exports.tests.test_authz_sweep import write_baseline as w; '
    "w('apps/exports/tests/authz_baseline.json')\"   # on 11b1a765, before the sweep"
)

BASELINE_PATH = "apps/exports/tests/authz_baseline.json"


def _rows(world: World) -> dict[str, dict[str, Export | None]]:
    """Row class → actor name → the object the question is asked about.

    Written with `objects.create` rather than through `create_export`, and
    deliberately: `create_export` asks the very permission this census is
    measuring, so building the world through it would make the census's own
    fixtures depend on the answer being measured. `permissions_world` makes the
    same call about its `Role` rows for the same reason.
    """
    from apps.accounts.services import create_user

    other = create_user(email=f"export-other-{world.tenant.slug}@example.com", password=PASSWORD)
    hats = {"admin_at_a": world.a, "member": world.root, "owner": world.root}
    people = {
        "admin_at_a": world.admin_at_a.user,
        "member": world.member.user,
        "owner": world.owner.user,
    }

    def make(org: Any, requester: Any, scope: str = Export.Scope.ORGANIZATION) -> Export:
        return Export.objects.create(
            tenant=world.tenant, organization=org, requested_by=requester, scope=scope
        )

    other_in_subtree = make(world.a1, other)
    sibling_branch = make(world.b, other)
    admin_branch = make(world.a, other)
    tenant_scope = make(world.root, other, Export.Scope.TENANT)
    org_scope = make(world.root, other, Export.Scope.ORGANIZATION)

    return {
        "no_row": dict.fromkeys(ACTORS, None),
        "own_at_hat": {name: make(hats[name], people[name]) for name in ACTORS},
        "other_in_subtree": dict.fromkeys(ACTORS, other_in_subtree),
        "sibling_branch": dict.fromkeys(ACTORS, sibling_branch),
        "admin_branch": dict.fromkeys(ACTORS, admin_branch),
        "tenant_scope_at_root": dict.fromkeys(ACTORS, tenant_scope),
        "org_scope_at_root": dict.fromkeys(ACTORS, org_scope),
    }


def matrix(world: World) -> dict[str, dict[str, dict[str, bool]]]:
    """`key → row class → actor → allows(...)`. The same function on both trees."""
    rows = _rows(world)
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
            "DERIVED, never typed. Every cell is `allows(actor, key, row)` over the `exports` "
            "keys, the three roles of `permissions_world.build_world`, and the row classes "
            "`test_authz_sweep._rows` names. The test re-runs the same function on this tree "
            "and asserts equality; a moved cell prints (key, row class, actor, before, after)."
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


# --- the tests ----------------------------------------------------------------


@pytest.fixture
def world(db: None) -> World:
    return build_world()


def _baseline() -> dict[str, Any]:
    document: dict[str, Any] = json.loads((Path(settings.BASE_DIR) / BASELINE_PATH).read_text())
    return document


def test_the_apps_authorization_matrix_equals_the_baseline(world: World) -> None:
    """**P7.5.2.** Every cell the sweep did not mean to move, unmoved.

    The document was derived on the baseline tree by `write_baseline`; this
    re-runs `matrix` here and compares cell by cell. `accepted_deltas` is the
    declared exception list — a cell in it is a cell the sweep MEANT to move,
    with the reason carried in the document rather than in a report.
    """
    document = _baseline()
    expected: Mapping[str, Any] = document["answers"]
    accepted: Mapping[str, str] = document["accepted_deltas"]

    assert sorted(expected) == sorted(KEYS), sorted(expected)
    cells = sum(len(actors) for rows in expected.values() for actors in rows.values())
    assert cells == len(KEYS) * 7 * len(ACTORS) == 63, cells

    actual = matrix(world)
    moved = [
        (key, row_class, name, expected[key][row_class][name], actual[key][row_class][name])
        for key in sorted(expected)
        for row_class in sorted(expected[key])
        for name in sorted(expected[key][row_class])
        if expected[key][row_class][name] != actual[key][row_class][name]
        and f"{key}/{row_class}/{name}" not in accepted
    ]
    assert moved == [], moved


def test_a_flipped_cell_is_red(world: World) -> None:
    """**The census, driven.** A planted flip in the document and the check reds.

    Without this the equality test above could be comparing a document against
    itself — the shape that reads green while proving nothing. The plant is a
    copy of the document in memory, never the committed file: a destructive
    demonstration builds its own victim.
    """
    document = _baseline()
    key, row_class, name = "export.build", "admin_branch", "member"
    flipped = dict(document["answers"])
    flipped[key] = {rows: dict(cells) for rows, cells in document["answers"][key].items()}
    flipped[key][row_class][name] = not flipped[key][row_class][name]

    actual = matrix(world)
    moved = [
        (k, r, n)
        for k in sorted(flipped)
        for r in sorted(flipped[k])
        for n in sorted(flipped[k][r])
        if flipped[k][r][n] != actual[k][r][n]
    ]
    assert moved == [(key, row_class, name)], moved


def test_the_apps_policies_read_no_role() -> None:
    """**P7.5.2, the code half.** `apps/exports/policies.py` asks no role by value.

    A predicate answers "may this person do this to THAT row"; "how much
    authority does this person have" is the DATA half's question and it has one
    owner. The grep is the same one rule 54 (c) runs, pointed at this one file,
    so a regression here reds in the rung before it reds in the gate.
    """
    import re

    source = (Path(settings.BASE_DIR) / "apps/exports/policies.py").read_text()
    pattern = re.compile(r"is_privileged|ADMIN_RANK|rank\(|effective_role|actor_role|ROLE_RANK")
    hits = [line for line in source.splitlines() if pattern.search(line)]
    assert hits == [], hits


def test_the_retired_key_still_answers_through_its_alias(world: World) -> None:
    """**P7.5.1.** `export.request` and `export.create` are one question.

    The rename is an alias under the immutable key (§D10): a product still
    calling the old word gets the new key's answer, resolved one line BEFORE the
    policy lookup, so it can never fall through to the role default.
    """
    from apps.core.authz import renamed_permissions, vocabulary

    assert renamed_permissions().get("export.request") == "export.create"
    assert vocabulary()["export.create"].renamed_from == ("export.request",)

    for name, actor in (
        ("owner", world.owner),
        ("admin_at_a", world.admin_at_a),
        ("member", world.member),
    ):
        for row in (None, Export(tenant=world.tenant, organization=world.root)):
            assert allows(actor, "export.request", row) == allows(actor, "export.create", row), (
                name,
                row,
            )


def test_every_key_this_app_declares_conforms() -> None:
    """**P7.5.1.** `<kind>.<verb>` over a kind the registry names, for all three."""
    from apps.core.authz import kind_registry, vocabulary

    words = vocabulary()
    assert "export" in kind_registry()
    for key in ("export.create", "export.read", "export.build"):
        assert words[key].kind == "export", key
        assert words[key].conforms, (key, words[key].non_conformance)


def test_what_a_member_may_do_is_still_the_transitional_residue(world: World) -> None:
    """**P7.5.2, deferred half — the PM's ruling of 2026-09-16, asserted.**

    The sweep's shape puts "a `member` may create an export" in `DEFAULT_ROLES`,
    as data. That entry moves `defaults_for("member")`, which is a pin of the
    flat product two core tests hold, and no per-app sweep may move it alone —
    so this app declares no `DEFAULT_ROLES` at all and `can_request` keeps its
    membership half as residue.

    This test is the RECORD of that, so the deferral is a thing the suite knows
    about rather than a sentence in a commit message: it fails the day somebody
    adds the entry without the core rung that makes room for it, and it fails
    the day the residue quietly stops holding.
    """
    from apps.core.authz import defaults_for, vocabulary
    from apps.exports import policies

    assert not hasattr(policies, "DEFAULT_ROLES"), "the deferred entry landed early"

    member = defaults_for("member")
    assert "export.read" in member  # by the `*.read` pattern `roles.py` declares
    assert "export.create" not in member  # the declaration's answer: not yet
    assert "export.build" not in member

    # ...and the transitional column is what carries it meanwhile: a key with a
    # predicate and no declaration is offered to every role and the predicate is
    # what narrows it (`core.authz._attach_default_roles` clause 5).
    assert "member" in vocabulary()["export.create"].default_roles
    assert "member" not in vocabulary()["export.build"].default_roles


def test_a_roleless_membership_may_not_export(world: World) -> None:
    """A negative, and **not** a change this sweep made — measured, not assumed.

    It reads like the sweep's one behavioural delta: `can_request` used to admit
    anybody carrying a membership row, a roleless one included, and now what a
    role holds is data. But the answer did not move, and the run on the baseline
    tree says so — this case is GREEN on `11b1a765` too. PR1 had already closed
    it one layer down: a roleless membership's collection is empty, so the DATA
    half refused before the predicate was ever consulted. The predicate's
    membership check was already dead code when the sweep reached it.

    It stays as a negative: it is the case that would go quietly True if a later
    change gave `export.create` to the roleless key.
    """
    from apps.core.authz import require
    from apps.core.exceptions import Forbidden

    roleless = actor_for(user=world.roleless_membership.user, tenant=world.tenant, org=world.b)
    with pytest.raises(Forbidden):
        require(roleless, "export.create", Export(tenant=world.tenant, organization=world.b))
