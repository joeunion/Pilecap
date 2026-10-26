"""This app's four keys were re-keyed onto `workflow_run.*` and no answer moved.

The baseline is core's derived `flat_product_baseline.json` (obj=None); the row-bound half
(`started_by`) is the services', driven by `test_api.py` and `test_cancel.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings

from apps.core.authz import renamed_permissions, vocabulary
from apps.core.tests.permissions_world import census, flat_roles, flat_world

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
    """Every cell — these keys × every role the flat census asks — before and after, flat.

    A moved cell prints `(key, role, before, after)` rather than `assert False`,
    because the interesting failure is *which person stopped being able to do
    what* and a boolean comparison cannot say it.

    The key count is asserted first: a census that silently found none would
    compare an empty dict with an empty dict and pass.
    """
    baseline = _baseline()
    old_for = {new: old for old, new in renamed_permissions().items()}

    # The document is re-derived in place, so it names the NEW key; a document
    # derived before the rename named only the old one.
    pinned = {key: baseline.get(key) or baseline[old_for[key]] for key in APP_KEYS}
    assert len(pinned) == len(APP_KEYS) == 4, pinned
    assert sum(len(cells) for cells in pinned.values()) == len(APP_KEYS) * len(flat_roles()), pinned
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
