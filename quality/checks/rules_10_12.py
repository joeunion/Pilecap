"""Rules 10 + 12: doors and selectors never write; services return objects."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import (
    _WRITE_MANAGER_CALLS,
    CheckResult,
    _enclosing_functions,
    _exempt,
    _function_at,
    _parse,
    _py_files,
)
from quality.worlds import service_modules

# --- rules 10 + 12: doors and selectors never write; services return objects ---

_DOOR_FILES = {"api.py", "mcp.py", "consumers.py", "receivers.py", "admin.py", "activities.py"}
# Receivers whose .save()/.delete() is not an ORM write. `cache.delete(key)` was
# found in the wild (connections/api.py) and is the negative fixture.
_NON_MODEL_RECEIVERS = {"cache", "caches", "session", "storage", "self"}


def _chain_root(node: ast.expr) -> ast.expr:
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript, ast.Await)):
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Subscript):
            node = node.value
        else:
            node = node.value
    return node


def _write_calls(tree: ast.Module) -> list[tuple[int, str]]:
    """(line, description) for every direct ORM write this file makes."""
    hits: list[tuple[int, str]] = []
    # A decorator is a call too — `@router.delete("/{id}/")` is a route, not a
    # write — so decorator expressions are excluded from the walk wholesale.
    decorator_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                for sub in ast.walk(dec):
                    decorator_nodes.add(id(sub))
    for node in ast.walk(tree):
        if id(node) in decorator_nodes:
            continue
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        recv = node.func.value
        # Manager writes: X.objects.create(...) and friends.
        if (
            attr in _WRITE_MANAGER_CALLS
            and isinstance(recv, ast.Attribute)
            and recv.attr == "objects"
        ):
            hits.append((node.lineno, f".objects.{attr}()"))
            continue
        # Queryset writes: ....filter(...).update(...) / .delete().
        if attr in ("update", "delete") and isinstance(recv, ast.Call):
            inner = recv.func
            if isinstance(inner, ast.Attribute) and inner.attr in (
                "filter",
                "exclude",
                "all",
                "for_tenant",
            ):
                hits.append((node.lineno, f".{inner.attr}(...).{attr}()"))
                continue
        # Instance writes: obj.save() / obj.delete() on a plain name.
        if attr in ("save", "delete") and isinstance(recv, ast.Name):
            if recv.id in _NON_MODEL_RECEIVERS:
                continue
            hits.append((node.lineno, f"{recv.id}.{attr}()"))
    return hits


def door_writes(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", named=_DOOR_FILES):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("door_files")
        rel = str(path.relative_to(root))
        spans = _enclosing_functions(tree)
        for lineno, what in _write_calls(tree):
            fn = _function_at(spans, lineno)
            if _exempt(rule, rel, fn):
                continue
            out.hit(
                rel,
                lineno,
                f"a door writes ({what}) — every door calls services; services own writes",
            )
    return out


_QS_TAIL = {
    "filter",
    "exclude",
    "all",
    "order_by",
    "values",
    "values_list",
    "annotate",
    "select_related",
    "prefetch_related",
    "for_tenant",
    "only",
    "defer",
}


def selector_service_split(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", named={"selectors.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("selector_files")
        rel = str(path.relative_to(root))
        for lineno, what in _write_calls(tree):
            out.hit(
                rel,
                lineno,
                f"a selector writes ({what}) — selectors.py never writes (reads/writes separate)",
            )
    for path in service_modules(root):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("service_files")
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            returns = node.returns
            if returns is not None and "QuerySet" in ast.unparse(returns):
                out.hit(
                    rel,
                    node.lineno,
                    f"{node.name} returns a QuerySet from services.py — a display read is a "
                    "selector's",
                )
                continue
            for ret in ast.walk(node):
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Call):
                    f = ret.value.func
                    if isinstance(f, ast.Attribute) and f.attr in _QS_TAIL:
                        out.hit(
                            rel,
                            ret.lineno,
                            f"{node.name} returns a queryset chain (.{f.attr}(...)) — services "
                            "return objects; selectors return querysets",
                        )
                        break
    return out
