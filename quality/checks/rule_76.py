"""Rule 76: a versioned row's writes move `updated_at`."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, _parse, _py_files, _read
from quality.worlds import reaching

# --- rule 76: a versioned row's writes move `updated_at` ------------------------
#
# `core.models.Versioned` derives the optimistic-concurrency token from
# `updated_at` (`core.concurrency.version_of`): no column, so nothing a service
# could forget to bump — EXCEPT a write that leaves `updated_at` where it was.
# `auto_now` moves it on a plain `save()`, but a `save(update_fields=[...])`
# that does not list it writes the listed columns and leaves the stamp, and a
# queryset `.update(...)` never touches `auto_now` at all. Either is a change
# the next reader's version cannot see, so a stale edit made against the old
# version sails through. The population is rule 75's resolver shape: declared
# by class name to a fixed point, seeded by the mixin.

_VERSIONED_ATTR = "versioned"
_VERSIONED_MIXIN = "Versioned"
_STAMP = "updated_at"


def declared_marker_classes(root: Path, attr: str, mixin: str) -> set[str]:
    """Every class under `apps/` that declares `attr = True`, itself or through a base.

    The generic half of `declared_class_populations`: seeded by the mixin that
    declares the marker, resolved by class name to a fixed point. Only names
    with a definition site are returned.
    """
    bases_of: dict[str, set[str]] = {}
    marked: set[str] = {mixin}
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name == "Meta":
                continue
            bases_of.setdefault(node.name, set()).update(_base_names(node))
            if _class_attribute_is_true(node, attr):
                marked.add(node.name)
    return reaching(bases_of, marked) & bases_of.keys()


def _literal_strings(node: ast.expr | None) -> list[str] | None:
    """The strings of a literal list/tuple/set of string constants, else None."""
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return None
    out: list[str] = []
    for element in node.elts:
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            return None
        out.append(element.value)
    return out


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for keyword in call.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _row_names(tree: ast.Module, model: str) -> set[str]:
    """Names that hold a row of `model`: bound from an expression naming it, or a
    parameter annotated with it (`widget: Widget`) — the services' usual shape."""
    names = set(_names_bound_to(tree, model))
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names |= {a.arg for a in _all_args(fn) if model in _annotation_names(a.annotation)}
    return names


def versioned_writes_move_updated_at(root: Path, rule: dict) -> CheckResult:
    """Rule 76. A write to a `Versioned` row moves `updated_at`, the version's source.

    Three shapes fire, each only when the source makes the columns legible:
    `row.save(update_fields=[...])` with a LITERAL list lacking `"updated_at"`
    on a name holding a row of a versioned class; a queryset `.update(...)`
    rooted at a versioned class with no `updated_at=` keyword (a `**kwargs`
    spread is unreadable and is not accused); `.bulk_update(objs, [...])` whose
    literal field list lacks it. Tests and migrations are outside the scope.
    """
    out = CheckResult()
    versioned = declared_marker_classes(root, _VERSIONED_ATTR, _VERSIONED_MIXIN)
    out.count("versioned_classes", len(versioned))
    models_only = sorted(versioned - {_VERSIONED_MIXIN})
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        if _exempt(rule, rel):
            continue
        text = _read(path)
        for model in models_only:
            if not re.search(rf"\b{re.escape(model)}\b", text):
                continue
            rows = _row_names(tree, model)
            qs_names, helpers = _queryset_bindings(tree, model)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                method, receiver = node.func.attr, node.func.value
                if method == "save" and isinstance(receiver, ast.Name) and receiver.id in rows:
                    fields = _literal_strings(_keyword(node, "update_fields"))
                    if fields is not None and _STAMP not in fields:
                        out.hit(
                            rel,
                            node.lineno,
                            f"`{receiver.id}.save(update_fields={fields!r})` writes a "
                            f"`Versioned` {model} without moving `updated_at`, so its version "
                            "(`core.concurrency.version_of`) does not change and an edit made "
                            'against the old one is not refused — list `"updated_at"` too.',
                        )
                elif method in ("update", "bulk_update") and _queryset_rooted(
                    receiver, model, qs_names, helpers
                ):
                    if method == "update":
                        if any(k.arg is None for k in node.keywords):
                            continue
                        if _keyword(node, _STAMP) is not None or not node.keywords:
                            continue
                        out.hit(
                            rel,
                            node.lineno,
                            f"a queryset `.update(...)` on the `Versioned` {model} names no "
                            "`updated_at=` — `auto_now` does not run on a queryset update, so "
                            "every row it changes keeps its old version. Add "
                            "`updated_at=now()` (`apps.core.time.now`).",
                        )
                    else:
                        listed = _keyword(node, "fields")
                        if listed is None and len(node.args) > 1:
                            listed = node.args[1]
                        fields = _literal_strings(listed)
                        if fields is not None and _STAMP not in fields:
                            out.hit(
                                rel,
                                node.lineno,
                                f"`bulk_update(..., {fields!r})` on the `Versioned` {model} "
                                "leaves `updated_at` where it was — set it on each row and "
                                'list `"updated_at"`.',
                            )
    return out


from quality.checks.rule_16_the_rest_of_the_grammar import _base_names  # noqa: E402
from quality.checks.rule_20_enforceable_half import _class_attribute_is_true  # noqa: E402
from quality.checks.rule_26 import _all_args, _annotation_names  # noqa: E402
from quality.checks.rules_81_and_82 import (  # noqa: E402
    _names_bound_to,
    _queryset_bindings,
    _queryset_rooted,
)
