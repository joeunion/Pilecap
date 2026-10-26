"""Rule 8: scoped models are read through for_tenant."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import (
    _RULE8_FILES,
    CheckResult,
    _enclosing_functions,
    _exempt,
    _function_at,
    _parse,
    _py_files,
    scoped_model_names,
)

#: The read a fail-closed manager names for a person rather than a tenant
#: (`MembershipQuerySet.of`) — as scoped as `for_tenant`, by the same failure.
_SCOPED_READ_METHODS = ("for_tenant", "of")


def fail_closed_manager_models(root: Path) -> set[str]:
    """Models whose own manager reads fail closed though they are not `TenantScopedModel`s.

    DERIVED, never declared: a class under `apps/` defining `def for_tenant`
    is a fail-closed queryset, and a model whose class body binds `objects` to
    that queryset (`Q.as_manager()` or `Q()`) reads through it — `Membership`
    today, whose `MembershipQuerySet` says so in its docstring.
    """
    querysets: set[str] = set()
    bindings: dict[str, str] = {}
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if stmt.name == "for_tenant":
                        querysets.add(node.name)
                elif isinstance(stmt, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == "objects" for t in stmt.targets
                ):
                    call = stmt.value
                    if isinstance(call, ast.Call):
                        target = call.func
                        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                            bindings[node.name] = target.value.id
                        elif isinstance(target, ast.Name):
                            bindings[node.name] = target.id
    return {model for model, queryset in bindings.items() if queryset in querysets}


def scoped_reads(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    scoped = scoped_model_names(root)
    out.targets_matched["scoped_models"] = len(scoped)
    managed = fail_closed_manager_models(root) - scoped
    out.targets_matched["fail_closed_managers"] = len(managed)
    scoped = scoped | managed
    files = _py_files(root, "apps", named=_RULE8_FILES) + _py_files(root, "config")
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        spans = _enclosing_functions(tree)
        # X.objects reached through for_tenant is the right form; anything else
        # on a scoped model is the leak-shaped read this rule refuses.
        ok_parents: set[int] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr in _SCOPED_READ_METHODS
                and isinstance(node.value, ast.Attribute)
                and (
                    node.attr == "for_tenant"
                    or (isinstance(node.value.value, ast.Name) and node.value.value.id in managed)
                )
            ):
                ok_parents.add(id(node.value))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Attribute)
                and node.attr == "objects"
                and isinstance(node.value, ast.Name)
                and node.value.id in scoped
            ):
                continue
            if id(node) in ok_parents:
                continue
            fn = _function_at(spans, node.lineno)
            if _exempt(rule, rel, fn):
                continue
            if node.value.id in managed:
                out.hit(
                    rel,
                    node.lineno,
                    f"bare {node.value.id}.objects — its manager fails closed only through its "
                    f"named reads: {node.value.id}.objects.for_tenant(tenant) or "
                    f".of(user), or carry # rule-8: <reason>",
                    klass="fail-closed-manager",
                )
                continue
            out.hit(
                rel,
                node.lineno,
                f"bare {node.value.id}.objects on a scoped model — read through "
                f"{node.value.id}.objects.for_tenant(tenant), or carry # rule-8: <reason>",
            )
    return out
