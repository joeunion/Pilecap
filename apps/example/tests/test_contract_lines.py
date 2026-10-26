# census: cross-app population=apps/example/**/*.py for a docstring longer than its contract line
"""Every symbol in the worked example that carries a docstring keeps its one contract line."""

from __future__ import annotations

import ast
from pathlib import Path

from pilecap.testing import source_tree

APP = Path(__file__).resolve().parents[1]
Documented = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef

#: Pinned from the printed population; it only falls by a human reading the count.
CONTRACT_LINES_FLOOR = 440


def _is_route(node: Documented) -> bool:
    """A `router.<verb>` route: its title and one description line (rule 41)."""
    return isinstance(node, ast.FunctionDef) and any(
        isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and isinstance(d.func.value, ast.Name)
        and d.func.value.id == "router"
        for d in node.decorator_list
    )


def contract_census(root: Path) -> tuple[list[str], list[str]]:
    """(symbols carrying a contract line, symbols whose docstring is longer than it)."""
    carrying: list[str] = []
    malformed: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if "migrations" in path.relative_to(root).parts:
            continue
        tree = source_tree(path)
        rel = path.relative_to(root).as_posix()
        nodes: list[tuple[str, Documented]] = [(f"{rel}::<module>", tree)]
        nodes += [
            (f"{rel}::{node.name}@{node.lineno}", node)
            for node in ast.walk(tree)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for name, node in nodes:
            doc = ast.get_docstring(node)
            if doc is None:
                continue
            lines = [line for line in doc.splitlines() if line.strip()]
            if len(lines) == (2 if _is_route(node) else 1):
                carrying.append(name)
            else:
                malformed.append(name)
    return carrying, malformed


def test_every_docstring_is_one_contract_line() -> None:
    """A docstring in `apps/example` is its contract line, a route's its title and one more."""
    _, malformed = contract_census(APP)
    assert not malformed, malformed


def test_no_symbol_lost_its_contract_line() -> None:
    """The population carrying a contract line never falls below its pinned floor."""
    carrying, _ = contract_census(APP)
    assert len(carrying) >= CONTRACT_LINES_FLOOR, (
        f"{len(carrying)} symbols carry a contract line; the floor is {CONTRACT_LINES_FLOOR}"
    )
