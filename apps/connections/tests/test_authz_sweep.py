"""The Phase-W sweep's own instrument: the matrix did not move, and no role is read.

Two claims, and they fail differently — which is why they are two tests.

* **The matrix.** `authz_baseline.json` is 24 cells derived on the tree before
  the sweep (`authz_matrix.py`, whose docstring carries the command and whose
  header carries the sha). This re-derives the same census here and asserts
  equality, cell for cell. A sweep that moved an answer prints
  `(key, actor, state, before, after)` and reds.
* **The code half reads no role.** The predicate this file had read
  `Membership.role` through a rank comparison. The census for that is a grep
  over the app's own file, because the property is about the SOURCE and not
  about any answer — a predicate could ask the right question and still compute
  it from the wrong layer.

The two together are what "roles are data, policies are code" means for one app:
the first says the answers are the same, the second says they now come from the
layer that owns them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

from apps.connections.models import Connection, InboundWebhook
from apps.connections.tests.authz_matrix import (
    MATRIX_ROLES,
    connections_action_keys,
    matrix,
    matrix_world,
)
from apps.core.actor import Actor

pytestmark = pytest.mark.django_db

BASELINE = Path(settings.BASE_DIR) / "apps/connections/tests/authz_baseline.json"

#: The shapes rule 54 (c) names, as one expression — the same one the criterion
#: pastes. `holds(...)` is deliberately absent: asking the data half what a
#: person holds IS the remedy, and a census that flagged it would forbid the fix.
ROLE_BY_VALUE = re.compile(r"is_privileged|ADMIN_RANK|rank\(|effective_role|actor_role|ROLE_RANK")


def test_the_apps_authorization_matrix_equals_the_baseline() -> None:
    """Every cell the app answered before the sweep, answered the same way now.

    The baseline is DERIVED — the same function, run on the sweep's baseline
    tree, committed beside its command — so this compares two runs of one census
    rather than a run against somebody's reading of the old code.

    **The population is compared before the cells.** A diff that only prints
    moved answers is silent about the failure it cannot express: a key that left
    the app's declarations. Its cells do not move, they stop existing.
    """
    document = json.loads(BASELINE.read_text())
    expected: dict[str, dict[str, dict[str, bool]]] = document["answers"]
    assert document["roles"] == list(MATRIX_ROLES)
    assert len(expected) == 4, sorted(expected)
    assert sum(len(states) for actors in expected.values() for states in actors.values()) == 24

    from apps.connections import policies

    renames = getattr(policies, "RENAMED_PERMISSIONS", {})
    here = set(connections_action_keys())
    vanished = sorted(key for key in expected if key not in here and key not in renames)
    assert vanished == [], vanished

    world, actors = matrix_world()
    actual = matrix(world, actors)

    moved = [
        (key, name, state, expected[key][name][state], actual[key][name][state])
        for key in sorted(expected)
        for name in sorted(expected[key])
        for state in sorted(expected[key][name])
        if key in actual and expected[key][name][state] != actual[key][name][state]
    ]
    assert moved == [], moved


def test_a_flipped_answer_is_caught() -> None:
    """The instrument can fail — the half a census is worthless without.

    A predicate is planted where the sweep left none (or replaced where it left
    one), answering the opposite, and the same comparison the test above makes
    must find the moved cells. Without this, a census whose `matrix()` silently
    returned the baseline it was comparing against would pass forever.

    **The plant is restored with a SECOND `reset_policies()`, and that is not
    belt-and-braces.** `vocabulary()` is derived from `policies()` and cached in
    the same module: a plant that is undone without dropping that cache leaves
    the vocabulary saying the planted predicate's key still HAS a predicate,
    which changes who holds it by default (the compat residue) for every later
    test in the worker. `monkeypatch` cannot do this — its undo runs after the
    test body, so a reset inside the body would run too early — which is why the
    restore is written out here.
    """
    from apps.connections import policies as app_policies
    from apps.core.authz import reset_policies

    def refuse(actor: Actor, obj: Any = None) -> bool:
        """The planted predicate: the opposite answer, for everybody."""
        return False

    document = json.loads(BASELINE.read_text())
    expected: dict[str, dict[str, dict[str, bool]]] = document["answers"]

    original = dict(app_policies.POLICIES)
    try:
        app_policies.POLICIES["connection.update"] = refuse
        reset_policies()
        world, actors = matrix_world()
        actual = matrix(world, actors)
    finally:
        app_policies.POLICIES.clear()
        app_policies.POLICIES.update(original)
        reset_policies()

    moved = [
        (key, name, state)
        for key in sorted(expected)
        for name in sorted(expected[key])
        for state in sorted(expected[key][name])
        if key in actual and expected[key][name][state] != actual[key][name][state]
    ]
    assert moved, "a planted predicate moved no cell — the census cannot fail"
    assert all(key == "connection.update" for key, _name, _state in moved), moved


def test_the_apps_policies_read_no_role() -> None:
    """Rule 54 (c) for this app, read off the file rather than off a count.

    The gate's own ratchet for `connections.role-value` reaches zero with this,
    and the two instruments are deliberately different: the gate reads the AST
    and counts, this reads the text and names the line.
    """
    source = (Path(settings.BASE_DIR) / "apps/connections/policies.py").read_text()
    offenders = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(source.splitlines(), start=1)
        if ROLE_BY_VALUE.search(line)
    ]
    assert offenders == [], offenders


def test_the_two_kinds_name_no_organization_so_the_matrix_is_two_states() -> None:
    """The claim `authz_matrix.py` makes about the models, asserted rather than assumed.

    Its object axis is two states instead of the five an org-scoped app owes,
    because `core.authz.where_of` resolves a question's node off the object's
    `organization` and neither model here has one. That is a fact about the
    models, and a model that grows an organization silently turns the shorter
    axis into a blind spot — so it is checked here, where the axis is decided.
    """
    for model in (Connection, InboundWebhook):
        fields = {field.name for field in model._meta.get_fields()}  # noqa: SLF001
        assert "organization" not in fields, model.__name__
