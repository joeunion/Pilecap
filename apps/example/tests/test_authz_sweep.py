"""The app's authorization matrix against its derived baseline: a sweep moved no cell."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

from apps.example.tests.authz_matrix import (
    MATRIX_ROLES,
    example_action_keys,
    matrix,
    matrix_world,
)
from pilecap import Actor

pytestmark = pytest.mark.django_db

BASELINE = Path(settings.BASE_DIR) / "apps/example/tests/authz_baseline.json"


def test_the_apps_authorization_matrix_equals_the_baseline() -> None:
    """Every cell the app answered before the sweep, answered the same way now."""
    document = json.loads(BASELINE.read_text())
    expected: dict[str, dict[str, dict[str, bool]]] = document["answers"]
    assert document["roles"] == list(MATRIX_ROLES)
    assert len(expected) == 7, sorted(expected)
    assert sum(len(states) for actors in expected.values() for states in actors.values()) == 105

    from apps.example import policies

    renames = getattr(policies, "RENAMED_PERMISSIONS", {})
    here = set(example_action_keys())
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


def test_a_flipped_cell_is_caught() -> None:
    """The instrument can fail — the half a census is worthless without."""
    from apps.example import policies as app_policies
    from pilecap.testing import reset_policies

    def refuse(actor: Actor, obj: Any = None) -> bool:
        """The planted predicate: the opposite answer, for everybody."""
        return False

    document = json.loads(BASELINE.read_text())
    expected: dict[str, dict[str, dict[str, bool]]] = document["answers"]

    original = dict(app_policies.POLICIES)
    try:
        app_policies.POLICIES["widget.update"] = refuse
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
    assert all(key == "widget.update" for key, _name, _state in moved), moved


def test_every_declared_key_still_has_its_sentence() -> None:
    """A swept key that lost its prose would refuse with a derived sentence."""
    from apps.example import policies
    from pilecap.testing import refusal_sentence

    document = json.loads(BASELINE.read_text())
    for key in document["answers"]:
        resolved = getattr(policies, "RENAMED_PERMISSIONS", {}).get(key, key)
        assert resolved in policies.ACTION_PROSE, resolved
        assert refusal_sentence(resolved) == policies.ACTION_PROSE[resolved]
