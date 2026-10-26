"""Rule 92: every on-commit registration is a declared seam."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 92: every on-commit registration is a declared seam -----------------


def _on_commit_names(tree: ast.Module) -> set[str]:
    """The bare names this module binds to `django.db.transaction.on_commit`."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "django.db.transaction":
            names.update(a.asname or a.name for a in node.names if a.name == "on_commit")
    return names


def _is_on_commit_call(node: ast.AST, bare: set[str]) -> bool:
    """`transaction.on_commit(...)`, or a bare name imported from `django.db.transaction`."""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return (
            func.attr == "on_commit"
            and isinstance(func.value, ast.Name)
            and func.value.id == "transaction"
        )
    return isinstance(func, ast.Name) and func.id in bare


def _is_road_decorated(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A definition carrying rule 84's python marker, `@road("<job>", …)`."""
    for dec in node.decorator_list:
        call = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(call, ast.Name) and call.id == "road":
            return True
        if isinstance(call, ast.Attribute) and call.attr == "road":
            return True
    return False


def on_commit_seams(root: Path, rule: dict) -> CheckResult:
    """Rule 92. Every on-commit site under `apps/` sits in a function marked `@road` (rule 84)."""
    out = CheckResult()
    for path in _py_files(root, "apps"):
        rel = path.relative_to(root).as_posix()
        if _is_test_module(rel) or rel.endswith("conftest.py"):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_read")
        bare = _on_commit_names(tree)
        holders: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        for top in tree.body:
            if isinstance(top, (ast.FunctionDef, ast.AsyncFunctionDef)):
                holders.append(top)
            elif isinstance(top, ast.ClassDef):
                holders.extend(
                    n for n in top.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
        seen: set[int] = set()
        for holder in holders:
            declared = _is_road_decorated(holder)
            for node in ast.walk(holder):
                if not _is_on_commit_call(node, bare) or id(node) in seen:
                    continue
                seen.add(id(node))
                out.count("sites_read")
                if declared:
                    out.count("declared_sites")
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"`{holder.name}` registers `transaction.on_commit(` and is not a declared "
                    "seam — register through a function marked `@road(...)` (rule 84) and call "
                    "it, or carry `# rule-92: <reason>`",
                    klass="undeclared_seam",
                )
        for node in ast.walk(tree):
            if _is_on_commit_call(node, bare) and id(node) not in seen:
                seen.add(id(node))
                out.count("sites_read")
                out.hit(
                    rel,
                    node.lineno,
                    "`transaction.on_commit(` registered at module level is not a declared seam "
                    "— register through a function marked `@road(...)` (rule 84)",
                    klass="undeclared_seam",
                )
    return out


from quality.checks.rule_36 import _is_test_module  # noqa: E402
