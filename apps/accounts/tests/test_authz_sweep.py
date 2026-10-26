"""The `accounts` key sweep, measured: every answer the app gave before, it gives after.

The matrix asks the OLD key names, so `RENAMED_PERMISSIONS` is what answers them.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from django.conf import settings

from apps.accounts.tests.authz_matrix import (
    ACTORS,
    BASELINE_PATH,
    KEYS,
    matrix,
)
from apps.core.actor import actor_for, system_actor
from apps.core.authz import allows, refusal_sentence, renamed_permissions, vocabulary
from apps.core.models import Membership
from apps.core.services import add_membership
from apps.core.tests.permissions_world import PASSWORD, World, build_world

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Mapping

pytestmark = pytest.mark.django_db


#: The four renames the sweep declares, old word to new. Pinned here as well as
#: in `policies.py` because a rename is a promise about what a CALLER may still
#: say, and a promise with one copy is a promise nobody notices losing. It is
#: not a promise about stored rows: a `Grant` or `RolePermission` written under
#: an old key is INERT until `manage.py rename_permission` moves it.
RENAMES: dict[str, str] = {
    "accounts.user.deactivate": "user.deactivate",
    "accounts.user.erase": "user.erase",
    "identity_platform.configure": "deployment.configure",
    "sso_identity.provision": "sso_identity.create",
}

#: **The moved cells, named EXACTLY and every one of them strictly narrowing.**
#: Empty on this tree, and that is a measurement rather than an expectation: the
#: compat residue (`_attach_default_roles` clause 5) offers a key WITH a
#: predicate to every declared role, so the two `user.*` keys that gained a real
#: kind gained a data half that admits exactly the people their predicate then
#: narrows — which is the same population the kindless form reached. The list is
#: here as a list rather than as `moved == []` so that a sweep which DOES move a
#: cell has somewhere honest to say so, and so the narrowing check below has a
#: population to run over.
EXPECTED_MOVES: dict[str, str] = {}


def _baseline() -> Mapping[str, Any]:
    document: dict[str, Any] = json.loads((Path(settings.BASE_DIR) / BASELINE_PATH).read_text())
    return document


@pytest.fixture
def tree(db: None) -> World:
    return build_world()


# --- P8.2 · the matrix -------------------------------------------------------


def test_the_apps_authorization_matrix_equals_the_baseline(tree: World) -> None:
    """**P8.2.** Every cell the sweep did not mean to move, unmoved.

    The document was derived on the baseline tree by `authz_matrix.write_baseline`
    and committed beside it with the command in its own header; this re-runs the
    same function here and compares cell by cell. The keys asked are the OLD
    words, which is the strongest form of the claim: it is `RENAMED_PERMISSIONS`
    answering, not a test that quietly asked the new name.
    """
    document = _baseline()
    expected: Mapping[str, Any] = document["answers"]

    assert sorted(expected) == sorted(KEYS), sorted(expected)
    assert document["actors"] == list(ACTORS)
    cells = sum(len(actors) for rows in expected.values() for actors in rows.values())
    assert cells == len(KEYS) * 8 * len(ACTORS) == 216, cells

    actual = matrix(tree)
    moved = {
        f"{key}/{row_class}/{name}": (
            expected[key][row_class][name],
            actual[key][row_class][name],
        )
        for key in sorted(expected)
        for row_class in sorted(expected[key])
        for name in sorted(expected[key][row_class])
        if expected[key][row_class][name] != actual[key][row_class][name]
    }
    assert sorted(moved) == sorted(EXPECTED_MOVES), moved


def test_every_moved_cell_narrows(tree: World) -> None:
    """**P8.2, the direction.** A sweep may take a capability away; never add one.

    The equality test above pins WHICH cells moved. This pins which WAY: every
    named move is `True → False`. A sweep that widened one answer by accident
    would satisfy the list above the day somebody added the cell to it, and this
    is the assertion that refuses to let that be a one-line edit.
    """
    expected: Mapping[str, Any] = _baseline()["answers"]
    actual = matrix(tree)
    for cell in sorted(EXPECTED_MOVES):
        key, row_class, name = cell.split("/")
        before, after = expected[key][row_class][name], actual[key][row_class][name]
        assert (before, after) == (True, False), (cell, before, after, EXPECTED_MOVES[cell])


def test_a_flipped_cell_is_red(tree: World) -> None:
    """**The census, driven.** A planted flip in the document and the check reds.

    Without this the equality test above could be comparing a document against
    itself — the shape that reads green while proving nothing. The plant is a
    copy of the document in memory, never the committed file: a destructive
    demonstration builds its own victim.
    """
    document = _baseline()
    key, row_class, name = "accounts.user.erase", "own_user", "member"
    flipped = {
        k: {r: dict(cells) for r, cells in rows.items()} for k, rows in document["answers"].items()
    }
    flipped[key][row_class][name] = not flipped[key][row_class][name]

    actual = matrix(tree)
    moved = [
        (k, r, n)
        for k in sorted(flipped)
        for r in sorted(flipped[k])
        for n in sorted(flipped[k][r])
        if flipped[k][r][n] != actual[k][r][n]
    ]
    assert moved == [(key, row_class, name)], moved


# --- P8.1 · the words --------------------------------------------------------


def test_every_declared_key_of_this_app_conforms() -> None:
    """**P8.1.** Nothing this app declares is left on the non-conforming census.

    `accounts` held the last three names on it: two three-part keys and one on a
    kind no model derives. The first two got the kind `User` already yields; the
    third got the declared VIRTUAL kind, which is the honest answer for a
    permission about the installation rather than about anybody's rows.
    """
    from apps.accounts import policies

    words = vocabulary()
    for key in sorted(set(policies.ACTION_PROSE) | set(policies.POLICIES)):
        assert key in words, key
        assert words[key].conforms, (key, words[key].non_conformance)


def test_the_four_renames_answer_and_the_sentences_do_not_move() -> None:
    """**P8.1.** The old word still resolves, and reads the same sentence.

    This is the whole promise of a rename, and it is about the ASK: a caller
    still saying the old key is answered, and a refused one reads the words
    they read yesterday. A rename that stopped answering is a widening — the
    collection loses a key and the role default underneath it is what answers
    instead. **Stored rows are outside the promise**: a `Grant` or
    `RolePermission` under an old key is inert until `manage.py
    rename_permission` moves it, which is why the upgrade step is a step.
    """
    from apps.accounts import policies

    assert policies.RENAMED_PERMISSIONS == RENAMES
    table = renamed_permissions()
    words = vocabulary()
    for old, new in RENAMES.items():
        assert table[old] == new, old
        assert new in words, new
        assert old not in words, old
        assert refusal_sentence(old) == refusal_sentence(new), old
        assert old in words[new].renamed_from, (old, words[new].renamed_from)


def test_the_deployment_is_a_virtual_kind_with_one_declared_verb() -> None:
    """**P8.1, Overrule 8.** `deployment.configure` names a kind with no table.

    `VIRTUAL_KINDS` was declared by P1 with zero keys on it; this is the rung
    that gives it its one. The assertion is both halves: the kind is virtual
    (so `allows` skips the data half and the predicate is the entire rule) and
    the key is DECLARED rather than derived (there is no model to derive four
    verbs from).
    """
    from apps.core.authz import VIRTUAL_KINDS, kind_registry

    words = vocabulary()
    assert sorted(VIRTUAL_KINDS) == ["deployment"]
    assert "deployment" not in kind_registry()
    word = words["deployment.configure"]
    assert word.kind == "deployment"
    assert word.decided_by == "declared"
    assert word.conforms


# --- P8.4 · what must not move ------------------------------------------------


def test_a_branch_admin_still_cannot_erase_a_non_self_user(tree: World) -> None:
    """**ADR ident-6, preserved through the rename.** The ceiling is the ROOT's.

    The predicate used to compare a rank at the root; it now asks whether the
    actor HOLDS the key that means "administers this tenant's people" at the
    root. The node did not move and neither did the answer: an administrator of
    branch `A` administers `A`, and erasure anonymises a person everywhere.

    Driven at both the erase and the deactivate key, and against three objects —
    somebody else's row, the branch they do administer, and no row at all —
    because the rename gave these keys a data half that is asked at whatever
    node the object names, and a widening would show up at the branch first.
    """
    other = tree.member_membership.user
    for key in ("user.erase", "user.deactivate", "accounts.user.erase"):
        for obj in (other, tree.a, None):
            assert allows(tree.admin_at_a, key, obj) is False, (key, obj)
    # And the other half of the same sentence: themselves, always.
    admin_self = tree.admin_membership.user
    assert allows(tree.admin_at_a, "user.erase", admin_self) is True


def test_a_superuser_with_no_membership_still_configures_the_deployment(tree: World) -> None:
    """**Overrule 8's mechanism**, asserted rather than assumed.

    A platform operator has no membership anywhere — they administer the
    installation, not a customer inside it — so a key with a data half would
    refuse them at step 5 before their predicate ever ran. `deployment` is a
    virtual kind precisely so that does not happen, and this drives it from the
    outside: a superuser with no membership, and an owner of a tenant who is the
    most privileged person that tenant has, answering opposite ways.
    """
    from apps.accounts.services import create_user

    operator = create_user(email="operator-p8@example.com", password=PASSWORD)
    operator.is_superuser = True
    operator.save(update_fields=["is_superuser"])
    acting = actor_for(user=operator, tenant=tree.tenant)

    for key in ("deployment.configure", "identity_platform.configure"):
        assert allows(acting, key, tree.tenant) is True, key
        assert allows(tree.owner, key, tree.tenant) is False, key
    assert allows(system_actor(tenant=tree.tenant), "deployment.configure", tree.tenant) is True


def test_a_person_with_no_role_holds_none_of_the_account_keys(tree: World) -> None:
    """The roleless membership, which the matrix's three actors do not cover.

    `build_world`'s roleless person holds nothing beyond their own grants, and
    after the sweep the two `user.*` keys have a data half that says so — where
    the kindless form would have fallen straight through to the predicate and
    let them act on their own row. It is the one place this sweep could have
    narrowed something, so it is asserted rather than left to the matrix's
    three roles.
    """
    assert allows(tree.roleless, "user.erase", tree.roleless_membership.user) is False
    assert allows(tree.roleless, "user.erase", None) is False
    assert allows(tree.roleless, "sso_connection.create", tree.root) is False


def test_the_sso_ceiling_still_measures_the_configurer_at_the_root(tree: World) -> None:
    """R1-F1's wall, unmoved by the sweep: the four SSO keys are the ROOT's.

    They carry no predicate at all — `admin` holds them by `*` at the root and
    `owner` by the vocabulary — so the only thing that decides them is the node
    the service resolves. An administrator of one branch passes at their own hat
    and is refused at the root, which is exactly what the services ask.
    """
    for key in ("sso_connection.create", "sso_connection.update", "sso_domain.verify"):
        assert allows(tree.admin_at_a, key, tree.root) is False, key
        assert allows(tree.admin_at_a, key, tree.a) is True, key
        assert allows(tree.owner, key, tree.root) is True, key
        assert allows(tree.member, key, tree.root) is False, key


def test_a_second_person_at_the_root_is_what_the_matrix_calls_other_user(tree: World) -> None:
    """The census's `other_user` row class, built the way the census builds it.

    A guard on the fixture rather than on the product: if `add_membership` ever
    stopped putting a plain member on the root, the matrix's `other_user` class
    would quietly become a second copy of `own_user` and every cell in it would
    still agree with the baseline.
    """
    from apps.accounts.services import create_user

    other = create_user(email="matrix-guard-p8@example.com", password=PASSWORD)
    membership = add_membership(
        user=other,
        tenant=tree.tenant,
        organization=tree.root,
        role="member",
        actor=system_actor(tenant=tree.tenant),
    )
    assert membership.organization_id == tree.root.pk
    assert membership.role == "member"
    assert other.pk != tree.member_membership.user.pk
    assert Membership.objects.filter(user=other, tenant=tree.tenant).count() == 1
