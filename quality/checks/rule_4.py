"""Rule 4: no business logic in signals."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 4: no business logic in signals ------------------------------------

_SIGNAL_MODULES = ("django.dispatch", "django.db.models.signals")


def signal_logic(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        imports_signals = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith(_SIGNAL_MODULES)
            ):
                imports_signals = True
            if isinstance(node, ast.Import) and any(
                a.name.startswith(_SIGNAL_MODULES) for a in node.names
            ):
                imports_signals = True
        if path.name == "signals.py":
            has_defs = any(
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)
            )
            if has_defs:
                out.hit(
                    rel,
                    1,
                    "a signals.py with function bodies — services own writes; signals are where "
                    "logic hides",
                )
        if not imports_signals:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    name = dec.func if isinstance(dec, ast.Call) else dec
                    if isinstance(name, ast.Name) and name.id == "receiver":
                        out.hit(
                            rel,
                            node.lineno,
                            f"@receiver on {node.name}; move the logic into a service",
                        )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
            ):
                out.hit(rel, node.lineno, "signal .connect(); services own writes, not receivers")
    return out
