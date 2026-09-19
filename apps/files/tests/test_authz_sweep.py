"""P7.6 — the `files` sweep, **measured rather than argued**.

The sweep gives this app's two models the authorization kind its keys have
always used — `StoredFile.authz_kind = "file"`, and `FileVersion.authz_kind_of`
naming the document it belongs to — and takes the role read out of its
predicates. Four keys that were non-conforming become four derived keys of a
real kind, and two derived keys of the OLD kind names stop existing.

The claim that has to survive all of that is that **every answer this app gave
before it, it gives after it**, including for a caller still saying the old
words. So this module carries the same three things the exports sweep carries:

* **`matrix(world)`** — `allows(actor, key, row)` over the app's keys × the
  three roles × the row classes below. One function, two trees.
* **`write_baseline(path)`** — the deriver, run on the sweep's baseline tree,
  its output committed beside this file with the command inside the document.
* **the tests** — the matrix re-run here equals that document; the app's
  `policies.py` reads no role; the four old derived keys still answer.

**The row classes, and why these.** After the sweep a `file.*` key is a key of a
registry kind, which means `core.authz.where_of` starts asking it at the ROW's
node — where before it was a kindless key whose predicate was the whole rule and
the node never entered into it. That is the biggest thing this sweep moves, so
the classes are the node ones: no row at all, the actor's own document at their
own hat, somebody else's deeper inside the hat's subtree, one in a sibling
branch where the actor holds nothing, one in the branch an admin administers,
and a VERSION inside the subtree — which is the class that proves
`authz_kind_of` resolves a child to its parent's kind rather than to a kind of
its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from django.conf import settings

from apps.core.actor import Actor
from apps.core.authz import allows
from apps.core.tests.permissions_world import PASSWORD, World, build_world
from apps.files.models import FileVersion, StoredFile

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

#: The six keys this app answered for on the baseline tree.
#:
#: The first four are its DECLARED ones, asked by the names they have always
#: had — the sweep gives them a kind, it does not rename them. The last two are
#: the DERIVED reads of the kinds the two models used to yield
#: (`snake_case(StoredFile)`, `snake_case(FileVersion)`); the sweep deletes both
#: kinds, so those two keys stop existing and `RENAMED_PERMISSIONS` is what
#: keeps them answering. A cell that moved because an alias does not answer is
#: exactly what this census is here to catch.
KEYS: tuple[str, ...] = (
    "file.archive",
    "file.create",
    "file.read",
    "file.replace",
    "file_version.read",
    "stored_file.read",
)

#: The three people, by the name `permissions_world.build_world` gives them.
ACTORS: tuple[str, ...] = ("admin_at_a", "member", "owner")

#: The tree this document was derived on, and the command that derived it.
#: `92a89c22`'s successor on this branch: `exports` and `search` are swept on it
#: and `files` is untouched, which is the tree the sweep starts from.
BASELINE_SHA = "e34f7bac"
BASELINE_COMMAND = (
    "uv run python manage.py shell -c "
    '"from apps.files.tests.test_authz_sweep import write_baseline as w; '
    "w('apps/files/tests/authz_baseline.json')\"   # on e34f7bac, before the sweep"
)

BASELINE_PATH = "apps/files/tests/authz_baseline.json"


def _rows(world: World) -> dict[str, dict[str, Any]]:
    """Row class → actor name → the object the question is asked about.

    Written with `objects.create` rather than through `create_file`, and
    deliberately: `create_file` asks the very permission this census is
    measuring, so building the world through it would make the census's own
    fixtures depend on the answer being measured. `permissions_world` makes the
    same call about its `Role` rows for the same reason.
    """
    from apps.accounts.services import create_user

    other = create_user(email=f"file-other-{world.tenant.slug}@example.com", password=PASSWORD)
    hats = {"admin_at_a": world.a, "member": world.root, "owner": world.root}
    people = {
        "admin_at_a": world.admin_at_a.user,
        "member": world.member.user,
        "owner": world.owner.user,
    }
    counter = {"n": 0}

    def make(org: Any, uploader: Any) -> StoredFile:
        counter["n"] += 1
        return StoredFile.objects.create(
            tenant=world.tenant,
            organization=org,
            uploaded_by=uploader,
            filename=f"census-{counter['n']}.pdf",
            purpose=StoredFile.Purpose.UPLOAD,
        )

    other_in_subtree = make(world.a1, other)
    sibling_branch = make(world.b, other)
    admin_branch = make(world.a, other)
    version = FileVersion.objects.create(
        tenant=world.tenant,
        file=other_in_subtree,
        organization=other_in_subtree.organization,
        version=1,
        key=f"census/{other_in_subtree.pk}/1",
        content_type="application/pdf",
        uploaded_by=other,
    )

    return {
        "no_row": dict.fromkeys(ACTORS, None),
        "own_at_hat": {name: make(hats[name], people[name]) for name in ACTORS},
        "other_in_subtree": dict.fromkeys(ACTORS, other_in_subtree),
        "sibling_branch": dict.fromkeys(ACTORS, sibling_branch),
        "admin_branch": dict.fromkeys(ACTORS, admin_branch),
        "version_in_subtree": dict.fromkeys(ACTORS, version),
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
            "DERIVED, never typed. Every cell is `allows(actor, key, row)` over the `files` "
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
def tree(db: None) -> World:
    return build_world()


def _baseline() -> dict[str, Any]:
    document: dict[str, Any] = json.loads((Path(settings.BASE_DIR) / BASELINE_PATH).read_text())
    return document


def test_the_apps_authorization_matrix_equals_the_baseline(tree: World) -> None:
    """**P7.6.2.** Every cell the sweep did not mean to move, unmoved.

    The document was derived on the baseline tree by `write_baseline`; this
    re-runs `matrix` here and compares cell by cell. `accepted_deltas` is the
    declared exception list — a cell in it is a cell the sweep MEANT to move,
    with the reason carried in the document rather than in a report.
    """
    document = _baseline()
    expected: Mapping[str, Any] = document["answers"]
    accepted: Mapping[str, str] = document["accepted_deltas"]

    assert sorted(expected) == sorted(KEYS), sorted(expected)
    # The exception list is READ, never inferred, and it is small and one shape:
    # four keys, one row class, one actor. A delta list that had started
    # absorbing whatever moved would show up here as a count nobody chose.
    assert len(accepted) == 4, sorted(accepted)
    assert {name.split("/", 1)[1] for name in accepted} == {"sibling_branch/admin_at_a"}
    cells = sum(len(actors) for rows in expected.values() for actors in rows.values())
    assert cells == len(KEYS) * 6 * len(ACTORS) == 108, cells

    actual = matrix(tree)
    moved = [
        (key, row_class, name, expected[key][row_class][name], actual[key][row_class][name])
        for key in sorted(expected)
        for row_class in sorted(expected[key])
        for name in sorted(expected[key][row_class])
        if expected[key][row_class][name] != actual[key][row_class][name]
        and f"{key}/{row_class}/{name}" not in accepted
    ]
    assert moved == [], moved


def test_a_flipped_cell_is_red(tree: World) -> None:
    """**The census, driven.** A planted flip in the document and the check reds.

    Without this the equality test above could be comparing a document against
    itself — the shape that reads green while proving nothing. The plant is a
    copy of the document in memory, never the committed file: a destructive
    demonstration builds its own victim.

    The accepted deltas are subtracted here exactly as they are above, so this
    proves the check still catches a flip the exception list does NOT cover —
    which is the half that would otherwise go quiet as the list grows.
    """
    document = _baseline()
    accepted = document["accepted_deltas"]
    key, row_class, name = "file.archive", "admin_branch", "member"
    flipped = dict(document["answers"])
    flipped[key] = {rows: dict(cells) for rows, cells in document["answers"][key].items()}
    flipped[key][row_class][name] = not flipped[key][row_class][name]

    actual = matrix(tree)
    moved = [
        (k, r, n)
        for k in sorted(flipped)
        for r in sorted(flipped[k])
        for n in sorted(flipped[k][r])
        if flipped[k][r][n] != actual[k][r][n] and f"{k}/{r}/{n}" not in accepted
    ]
    assert moved == [(key, row_class, name)], moved


def test_the_apps_policies_read_no_role() -> None:
    """**P7.6.2, the code half.** `apps/files/policies.py` asks no role by value.

    A predicate answers "may this person do this to THAT row"; "how much
    authority does this person have" is the DATA half's question and it has one
    owner. The grep is the same one rule 54 (c) runs, pointed at this one file,
    so a regression here reds in the rung before it reds in the gate.
    """
    import re

    source = (Path(settings.BASE_DIR) / "apps/files/policies.py").read_text()
    pattern = re.compile(r"is_privileged|ADMIN_RANK|rank\(|effective_role|actor_role|ROLE_RANK")
    hits = [line for line in source.splitlines() if pattern.search(line)]
    assert hits == [], hits


def test_the_two_models_yield_one_kind_and_it_is_the_one_the_keys_use() -> None:
    """**P7.6.1.** `file` is a kind, and both models answer to it.

    `StoredFile` declares it because the key vocabulary predates the class name;
    `FileVersion` declares `authz_kind_of`, which is a claim about the SHAPE of
    the relationship — a version dies with its document (CASCADE) and writing a
    version is writing the document — and `core.authz` refuses the declaration
    if that is not true of the foreign key it names.
    """
    from apps.core.authz import kind_of, kind_registry, vocabulary

    kinds = kind_registry()
    assert kind_of(StoredFile) == "file"
    assert kind_of(FileVersion) == "file"
    assert kinds["file"] is StoredFile
    assert "stored_file" not in kinds
    assert "file_version" not in kinds

    words = vocabulary()
    for key in ("file.create", "file.read", "file.replace", "file.archive"):
        assert words[key].kind == "file", key
        assert words[key].conforms, (key, words[key].non_conformance)


def test_the_retired_kind_names_still_answer_through_their_aliases(tree: World) -> None:
    """**P7.6.1.** Two kinds vanish; nobody who said their words is refused.

    `stored_file.*` and `file_version.*` were DERIVED keys — nobody typed them,
    the registry produced them from the class names — and the sweep deletes the
    kinds that produced them. A deployment whose code or rows say one of those
    words would otherwise fall to the role default with nothing saying so, which
    is the exact silent widening `RENAMED_PERMISSIONS` exists to prevent.
    """
    from apps.core.authz import renamed_permissions, vocabulary

    table = renamed_permissions()
    for verb in ("create", "read", "update", "delete"):
        assert table[f"stored_file.{verb}"] == f"file.{verb}", verb
        assert table[f"file_version.{verb}"] == f"file.{verb}", verb

    words = vocabulary()
    assert "stored_file.read" not in words
    assert "file_version.read" not in words
    assert set(words["file.read"].renamed_from) == {"file_version.read", "stored_file.read"}

    for actor in (tree.owner, tree.admin_at_a, tree.member):
        for old in ("stored_file.read", "file_version.read"):
            assert allows(actor, old, None) == allows(actor, "file.read", None), (actor, old)


def test_what_a_member_may_do_is_still_the_transitional_residue(tree: World) -> None:
    """**P7.6.2, deferred half — the PM's ruling of 2026-09-16, asserted.**

    The sweep's shape puts "a `member` may file and may replace" in
    `DEFAULT_ROLES`, as data. Those entries move `defaults_for("member")`, which
    is a pin of the flat product two core tests hold, and no per-app sweep may
    move it alone — so this app declares no `DEFAULT_ROLES` at all and
    `can_file` and `can_replace` keep their membership halves as residue.

    This test is the RECORD of that: it fails the day somebody adds the entries
    without the core rung that makes room for them, and the day the residue
    quietly stops holding.
    """
    from apps.core.authz import defaults_for, vocabulary
    from apps.files import policies

    assert not hasattr(policies, "DEFAULT_ROLES"), "the deferred entries landed early"

    member = defaults_for("member")
    assert "file.read" in member  # by the `*.read` pattern `roles.py` declares
    assert "file.create" not in member  # the declaration's answer: not yet
    assert "file.replace" not in member
    assert "file.archive" not in member

    words = vocabulary()
    assert "member" in words["file.create"].default_roles
    assert "member" in words["file.replace"].default_roles
    assert "member" not in words["file.archive"].default_roles
