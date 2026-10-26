"""The absent-app planner resolves a relative import as the import system does.

`apps/testing/absent_world.py::_imported_modules` used to keep a `from … import` only when
it was absolute, so `from .helper import thing` named nothing and a test that
reached an absent app through a sibling helper was collected — and errored at
import. These pin the resolution, level by level. Why this module sits at the
root of `apps/`: `apps/test_absent_world.py` says (it imports `apps.conftest`).
"""

from __future__ import annotations

import ast

import pytest

from apps.conftest import _imported_modules


def _node(source: str) -> ast.AST:
    return ast.parse(source).body[0]


@pytest.mark.parametrize(
    ("source", "package", "expected"),
    [
        (
            "from .helper import thing",
            "apps.zzz_reach.tests",
            {"apps.zzz_reach.tests.helper", "apps.zzz_reach.tests.helper.thing"},
        ),
        (
            "from ..services import act",
            "apps.zzz_reach.tests",
            {"apps.zzz_reach.services", "apps.zzz_reach.services.act"},
        ),
        (
            "from . import helper",
            "apps.zzz_reach.tests",
            {"apps.zzz_reach.tests", "apps.zzz_reach.tests.helper"},
        ),
        ("from apps.example import services", "", {"apps.example", "apps.example.services"}),
        ("from .....beyond import x", "apps.zzz_reach.tests", set()),
    ],
)
def test_a_relative_import_names_the_module_it_reaches(
    source: str, package: str, expected: set[str]
) -> None:
    assert set(_imported_modules(_node(source), package)) == expected
