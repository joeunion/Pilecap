"""A facade module's lazy re-exports: each name its `if TYPE_CHECKING:` block imports."""

from __future__ import annotations

import ast
import importlib
import sys
from collections.abc import Callable
from typing import Any

#: The guard whose imports are the module's exports, read off its own text.
GUARD = "TYPE_CHECKING"

__all__: list[str] = []


def guarded(path: str) -> dict[str, tuple[str, str]]:
    """Each `from M import a as b` under a top-level `if TYPE_CHECKING:`: `b` → (M, a)."""
    with open(path, encoding="utf-8") as source:
        tree = ast.parse(source.read(), filename=path)
    out: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == GUARD:
            for inner in node.body:
                if isinstance(inner, ast.ImportFrom) and inner.module and not inner.level:
                    out.update({a.asname or a.name: (inner.module, a.name) for a in inner.names})
    return out


def lazy(module: str) -> Callable[[str], Any]:
    """The module `__getattr__` that imports a guarded name when it is first read, then binds it."""
    table: dict[str, tuple[str, str]] = {}

    def __getattr__(name: str) -> Any:
        home = sys.modules[module]
        if not table:
            table.update(guarded(str(home.__file__)))
        if name not in table:
            raise AttributeError(f"module {module!r} has no attribute {name!r}")
        source, original = table[name]
        value = getattr(importlib.import_module(source), original)
        setattr(home, name, value)
        return value

    return __getattr__
