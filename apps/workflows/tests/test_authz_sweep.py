"""P7.8's instrument: this app's four keys changed name and nothing changed answer.

The sweep re-keyed the whole of this app's vocabulary onto the kind its one
model derives — `workflow.signal`, `workflowrun.read`, `workflowrun.replay`,
`workflowrun.cancel` became `workflow_run.*` — and retired the one predicate
that had no row half. Every one of those is a change to HOW the question is
asked. None of them may change the ANSWER, and this module is what makes that a
measurement instead of a claim.

**The baseline is derived, and it was derived before the sweep.**
`apps/core/tests/flat_product_baseline.json` is the committed census —
`allows(actor, key, obj=None)` for every key × {owner, admin, member} on a flat
product, written by `permissions_world.write_flat_product_baseline` on a tree
that predates this sweep, with the sha and the command in its own header. This
module re-runs the SAME function over this app's keys on this tree and compares.

*Rejected, and the reason is the lead's own* (P7's rejected-alternatives note,
one layer over): a per-app `authz_baseline.json` derived here. Eight files that
agree with one census is the second-copy class, and the copy this app would
write could only be derived on the swept tree — a pin taken from the thing it
pins. The document that already exists was derived by somebody else, before the
sweep, and is therefore the only honest baseline on the tree.

**The row-bound half is not here and says where it is.** These cells are all
`obj=None`: the abstract question, which is the only one that can be asked of
every key without inventing a row per kind. What replay and cancel narrow to the
actor's OWN run is `started_by` in `services.py`, not a predicate, and
`test_api.py` and `test_cancel.py` own it — unchanged by the sweep, which is the
claim `test_the_row_bound_refusals_are_still_the_services_own` makes here.
"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest
from django.conf import settings

from apps.core.authz import renamed_permissions, vocabulary
from apps.core.tests.permissions_world import census, flat_world

pytestmark = pytest.mark.django_db

#: This app's whole vocabulary after the sweep. One kind — `workflow_run`, which
#: `WorkflowRun` derives — and four verbs on it: the derived read plus the three
#: the ledger's own doors declare.
APP_KEYS = (
    "workflow_run.cancel",
    "workflow_run.read",
    "workflow_run.replay",
    "workflow_run.signal",
)


def _baseline() -> dict[str, dict[str, bool]]:
    document = json.loads(
        (Path(settings.BASE_DIR) / "apps/core/tests/flat_product_baseline.json").read_text()
    )
    answers: dict[str, dict[str, bool]] = document["answers"]
    return answers


def test_the_apps_authorization_matrix_equals_the_baseline() -> None:
    """Twelve cells — four keys × three roles — before and after, on a flat product.

    A moved cell prints `(key, role, before, after)` rather than `assert False`,
    because the interesting failure is *which person stopped being able to do
    what* and a boolean comparison cannot say it.

    The key count is asserted first: a census that silently found none would
    compare an empty dict with an empty dict and pass.
    """
    baseline = _baseline()
    old_for = {new: old for old, new in renamed_permissions().items()}

    pinned = {key: baseline[old_for.get(key, key)] for key in APP_KEYS}
    assert len(pinned) == len(APP_KEYS) == 4, pinned
    assert sum(len(cells) for cells in pinned.values()) == 12, pinned
    assert sorted(old_for[key] for key in APP_KEYS) == [
        "workflow.signal",
        "workflowrun.cancel",
        "workflowrun.read",
        "workflowrun.replay",
    ], old_for

    _tenant, actors = flat_world()
    actual = census(sorted(APP_KEYS), actors)

    moved = [
        (key, role, pinned[key][role], actual[key][role])
        for key in sorted(APP_KEYS)
        for role in sorted(pinned[key])
        if pinned[key][role] != actual[key][role]
    ]
    assert moved == [], moved


def test_every_old_key_and_its_successor_are_one_cell() -> None:
    """The four aliases, driven rather than asserted about the table.

    Asserted separately from the matrix because they fail differently: the
    matrix goes red when an ANSWER moved, and this goes red when the two names
    came apart — a product's stored `Grant` row naming the old word, or a caller
    that never read the release note, quietly falling to a different key.
    """
    _tenant, actors = flat_world()
    old_for = {new: old for old, new in renamed_permissions().items()}

    for key in APP_KEYS:
        old = old_for[key]
        assert census([old], actors)[old] == census([key], actors)[key], key
        assert vocabulary()[key].renamed_from == (old,), key


def test_the_four_keys_conform_and_name_the_one_kind() -> None:
    """The census's own verdict on this app, read off the vocabulary.

    `read` is the DERIVED key and the other three are declared verbs on a
    registry kind, which is why `decided_by` differs and `conforms` does not:
    the sentence a refused caller reads is this app's in all four cases, because
    an `ACTION_PROSE` entry for a derived key is a sentence override.
    """
    words = vocabulary()

    for key in APP_KEYS:
        assert words[key].kind == "workflow_run", key
        assert words[key].conforms, key
        assert "background job" in words[key].sentence, key
    assert words["workflow_run.read"].decided_by == "derived"
    assert {words[key].decided_by for key in APP_KEYS if key != "workflow_run.read"} == {"declared"}


def test_the_apps_policies_read_no_role() -> None:
    """Rule 54 (c) for this app: zero, before the sweep and after it.

    **Through the gate's own derivation and not through a grep**, which is the
    difference between the two: prose spelling a name gets counted by a grep
    exactly like code, and this module's own docstring spells several.

    It is asserted here — where it was already zero — so that the file cannot
    quietly acquire one later: the four predicates this app had were membership
    questions, never rank questions, and the sweep retired the one of them that
    had nothing else to say.
    """
    role_value_sites = importlib.import_module("quality.checks")._role_value_sites  # noqa: SLF001

    source = (Path(settings.BASE_DIR) / "apps/workflows/policies.py").read_text()

    assert role_value_sites(ast.parse(source)) == {}

    # ...and the check really is looking: the same walk over the same file with
    # a rank comparison planted into it finds it.
    planted = source.replace(
        "def belongs_to_the_tenant(actor: Actor, obj: Any = None) -> bool:",
        "def belongs_to_the_tenant(actor: Actor, obj: Any = None) -> bool:\n"
        "    if actor_role(actor) == 'admin':\n        return True",
    )
    assert role_value_sites(ast.parse(planted)) != {}
