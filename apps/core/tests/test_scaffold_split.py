# census: cross-app population=apps/core/scaffold/arms/*.py walks every arm for its KEYS vs SHAPES
"""The scaffold command is a dispatcher over its arms: one module per arm, one arm per shape."""

import importlib
import pkgutil
from pathlib import Path

import pytest
from django.core.management.base import CommandError

from apps.core.lexicon import PLURAL_REMEDY
from apps.core.scaffold.shapes import SHAPES

ROOT = Path(__file__).resolve().parents[3]


def test_every_registered_shape_has_an_arm_module() -> None:
    arms = importlib.import_module("apps.core.scaffold.arms")
    claimed: dict[str, str] = {}
    for found in pkgutil.iter_modules(arms.__path__):
        if found.name.startswith("_"):
            continue
        module = importlib.import_module(f"{arms.__name__}.{found.name}")
        for key in module.KEYS:
            assert key not in claimed, f"{key} is claimed by {claimed[key]} and {found.name}"
            claimed[key] = found.name
    assert set(claimed) == {shape.key for shape in SHAPES}, sorted(claimed)


def test_the_plural_refusal_names_the_valve() -> None:
    from apps.core.management.commands.scaffold import Command

    with pytest.raises(CommandError) as refused:
        Command().refuse_names(ROOT, "ledger", "Entry", check=True)
    said = str(refused.value)
    assert "'ledger' is not plural — house rule 16" in said, said
    assert f"would be born red; {PLURAL_REMEDY}." in said, said
