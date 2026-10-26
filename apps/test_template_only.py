# census: cross-app population=apps/**/test_*.py,scripts/tests/drive_preamble.sh marked tests
"""The template-only mark, as a census: a template test is DECLARED, never deleted.

Some tests assert a property only the TEMPLATE's own tree has, and on a product
that folded a release they are red by construction. `apps/conftest.py` honours
the mark — on a tree that declares `rule_id_namespace:` the test is skipped with
one sentence naming the declaration; on the template nothing is skipped — and
this module keeps the population honest in four closed questions:

  1. THE MARKED SET IS DERIVED, THE JUDGEMENT IS TYPED. Every `apps/**/test_*.py`
     is read by `ast`; a test function whose decorator is the mark with a
     string `reason=` is a member, and the derived set must EQUAL
     `TEMPLATE_ONLY_TESTS`. A new mark edits that set in the same commit, where
     a reviewer sees it — `apps/core/tests/test_plant_sites.py`'s shape. A mark
     with no reason, or spelled anywhere but on a test function, is a finding.
  2. EVERY PINNED TEST EXISTS. On a product that deleted one — the move the
     mark exists to make unnecessary — this is the red, and its message is the
     remedy.
  3. THE HONOUR, DRIVEN. `_withhold_template_only` over items this module
     builds, with a drawer handed in rather than the ambient one, so the drive
     is green on a product as on the template.
  4. ONE SENTENCE IN TWO MEDIA. The shell twin (`template_only` in
     `scripts/tests/drive_preamble.sh`) skips with the same prefix, byte for
     byte.

Why it sits at `apps/` root rather than under an app: its subject is the shared
conftest's mark, which belongs to no app.

WHAT IT DOES NOT SEE, declared: a test that is template-only in FACT but carries
no mark. It runs on a product and reds there, and that product's fold is the
census of that class — nothing on the template's own tree can tell it apart
from a test that is simply green.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from apps.conftest import (
    TEMPLATE_ONLY_SKIP_PREFIX,
    _withhold_template_only,
    template_only_skip_reason,
)
from apps.core.tests.tree_census import source_text, source_tree

ROOT = Path(__file__).resolve().parent.parent
PREAMBLE = ROOT / "scripts" / "tests" / "drive_preamble.sh"

#: THE JUDGEMENT: every test the template declares its own, by module and name.
#: A new mark joins here in the same commit, or the census below reds naming it.
TEMPLATE_ONLY_TESTS: frozenset[tuple[str, str]] = frozenset(
    {
        (
            "apps/accounts/tests/test_scopes.py",
            "test_a_key_that_moved_to_the_namespace_word_is_told_its_successor",
        ),
        (
            "apps/accounts/tests/test_scopes.py",
            "test_a_released_word_nobody_reclaimed_is_refused_naming_its_successor",
        ),
        (
            "apps/core/tests/test_fold_map.py",
            "test_this_template_tree_maps_onto_itself_with_nothing_to_do",
        ),
        (
            "apps/core/tests/test_template_shape.py",
            "test_the_platform_declares_nothing",
        ),
        (
            "apps/core/tests/test_template_version.py",
            "test_pyproject_states_the_same_version_as_the_file",
        ),
    }
)


def _is_the_mark(node: ast.AST) -> bool:
    """`pytest.mark.template_only`, spelled as an attribute chain."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "template_only"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _string_reason(decorator: ast.expr) -> str | None:
    """The literal `reason=` a decorator carries, or `None` when it carries none."""
    if not isinstance(decorator, ast.Call) or decorator.args:
        return None
    for keyword in decorator.keywords:
        if keyword.arg != "reason":
            continue
        value = keyword.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value.strip() or None
    return None


def _derive() -> tuple[set[tuple[str, str]], list[str]]:
    """(the marked set, the findings) over every test module under `apps/`."""
    marked: set[tuple[str, str]] = set()
    findings: list[str] = []
    for path in sorted((ROOT / "apps").rglob("test_*.py")):
        module = path.relative_to(ROOT).as_posix()
        tree = source_tree(path)
        on_a_test: set[int] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if not _is_the_mark(target):
                    continue
                on_a_test.add(id(target))
                if _string_reason(decorator) is None:
                    findings.append(
                        f"{module}::{node.name} carries the template-only mark with no "
                        "literal string reason= — a skip that cannot say why is a skip "
                        "nobody can audit"
                    )
                else:
                    marked.add((module, node.name))
        for node in ast.walk(tree):
            if _is_the_mark(node) and id(node) not in on_a_test:
                findings.append(
                    f"{module}:{getattr(node, 'lineno', '?')} spells the template-only "
                    "mark somewhere other than a test function's own decorator — a "
                    "module or class mark is invisible to this census; mark each test"
                )
    return marked, findings


def test_every_template_only_mark_carries_a_reason_and_sits_on_a_test() -> None:
    """A mark with no reason, or a mark this census cannot attribute, is a finding."""
    marked, findings = _derive()
    assert marked, "no template-only mark found anywhere — this census would pass vacuously"
    assert findings == [], "\n".join(findings)


def test_the_template_only_set_is_the_pinned_set() -> None:
    """The judgement, re-derived and compared.

    A new mark fails here until it is typed into `TEMPLATE_ONLY_TESTS` in the
    same commit. A PRODUCT never needs to: the mark says a property is the
    template's own, and a product's own test is never that.
    """
    marked, _findings = _derive()
    joined = sorted(marked - TEMPLATE_ONLY_TESTS)
    left = sorted(TEMPLATE_ONLY_TESTS - marked)
    assert marked == TEMPLATE_ONLY_TESTS, (
        f"marked but not pinned: {joined}; pinned but no longer marked: {left}"
    )


def _defines(module: str, name: str) -> bool:
    """Whether `module` (checkout-relative) exists and defines a test called `name`."""
    path = ROOT / module
    if not path.is_file():
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        for node in ast.walk(source_tree(path))
    )


def test_every_pinned_template_only_test_exists_in_the_tree() -> None:
    """On a product that DELETED a template-only test, this is the red — and the remedy."""
    missing = [
        f"restore `{module}::{name}`; it is marked `template_only` and is skipped on "
        "your tree by `apps/conftest.py` — a template test is declared, never deleted"
        for module, name in sorted(TEMPLATE_ONLY_TESTS)
        if not _defines(module, name)
    ]
    assert missing == [], "\n".join(missing)


def test_the_skip_sentence_is_the_shell_twins() -> None:
    """One sentence in two media: the shell twin's prefix is the conftest's, byte for byte."""
    spelled = re.findall(
        r'line="\$\{case_name\} — (template-only: [^$"]*)\$\{DRIVE__NAMESPACE\}; ',
        source_text(PREAMBLE),
    )
    assert len(spelled) == 1, (
        f"expected the shell twin's one skip sentence in {PREAMBLE}, found {spelled!r}"
    )
    assert spelled[0] == TEMPLATE_ONLY_SKIP_PREFIX


# --- the honour, driven over items this module builds --------------------------


class _Item:
    """The three things `_withhold_template_only` reads off a collected item."""

    def __init__(self, nodeid: str, mark: Any) -> None:
        self.nodeid = nodeid
        self._mark = mark
        self.added: list[Any] = []

    def get_closest_marker(self, name: str) -> Any:
        return self._mark if name == "template_only" else None

    def add_marker(self, marker: Any) -> None:
        self.added.append(marker)


def _mark(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(args=(), kwargs=kwargs)


WHY = "the platform's retired words are unclaimed only on the template's own tree"
PRODUCT = {"rule_id_namespace": "acme", "template_rule_ids_through": 60}
TEMPLATE: dict[str, object] = {}


def test_a_declared_namespace_skips_a_marked_test_naming_the_declaration() -> None:
    marked = _Item("apps/x/tests/test_a.py::test_marked", _mark(reason=WHY))
    plain = _Item("apps/x/tests/test_a.py::test_plain", None)
    _withhold_template_only([marked, plain], PRODUCT)
    assert plain.added == []
    assert len(marked.added) == 1, marked.added
    skip = marked.added[0].mark
    assert skip.name == "skip"
    assert skip.kwargs["reason"] == (
        "template-only: this tree declares rule_id_namespace acme; " + WHY
    )
    assert skip.kwargs["reason"] == template_only_skip_reason(WHY, PRODUCT)


def test_the_template_skips_nothing() -> None:
    marked = _Item("apps/x/tests/test_a.py::test_marked", _mark(reason=WHY))
    _withhold_template_only([marked], TEMPLATE)
    assert marked.added == []
    assert template_only_skip_reason(WHY, TEMPLATE) is None


def test_a_mark_with_no_reason_is_a_collection_error_naming_the_test_on_any_tree() -> None:
    for doc in (TEMPLATE, PRODUCT):
        for mark in (_mark(), _mark(reason="   "), SimpleNamespace(args=(WHY,), kwargs={})):
            bare = _Item("apps/x/tests/test_a.py::test_bare", mark)
            with pytest.raises(pytest.UsageError) as refused:
                _withhold_template_only([bare], doc)
            assert "apps/x/tests/test_a.py::test_bare" in str(refused.value)
            assert bare.added == []
