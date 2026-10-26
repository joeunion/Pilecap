"""Rule 20 (enforceable half): declared-append-only models are never rewritten."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files, _read

# --- rule 20 (enforceable half): declared-append-only models are never rewritten --
#
# ADR core-6. This rule used to hard-code the name `AuditEntry`, which is the
# shape that does not survive a product: a witnessed fact, an accrual and a
# stage-transition log make the same promise and none of them is called
# AuditEntry. The population is now DISCOVERED — every model that declared
# `append_only = True` (`core.models.APPEND_ONLY_ATTR`, and
# `core.models.append_only_models()` is the same question asked of the live
# registry). A product adds a member by declaring it, and this rule covers it
# in the same commit with no edit to rules.yaml.

_APPEND_ONLY_ATTR = "append_only"


def _class_attribute_is_true(node: ast.ClassDef, attr: str) -> bool:
    """Whether this class body assigns `attr = True` (annotated or not)."""
    for stmt in node.body:
        names, value = _assigned(stmt)
        target = names[0] if len(names) == 1 else None
        if target != attr:
            continue
        if isinstance(value, ast.Constant) and value.value is True:
            return True
    return False


def append_only_model_names(root: Path) -> dict[str, str]:
    """{model name: the module that declares it} for every declared append-only model.

    Derived from the tree on every run. The declaring module is remembered
    because that is the one place a member's own rows are reviewed — `AuditEntry`
    lives in `apps/core/audit.py`, and the archival job a product one day writes
    belongs there too, where this rule can see it was read.
    """
    found: dict[str, str] = {}
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _class_attribute_is_true(node, _APPEND_ONLY_ATTR):
                found[node.name] = path.relative_to(root).as_posix()
    return found


from quality.checks.rule_13_clauses_i_iv import _assigned  # noqa: E402

# : The queryset-level rewrites. A manager or queryset expression is the
# : receiver, so the model's name is IN the receiver and the word-bounded match
# : below finds it.
_QUERYSET_REWRITES = ("delete", "update", "bulk_update")


# : The INSTANCE-level rewrites, and the whole of LF-Q's static tightening.
# : `entry.save()` on a row that was READ back and `entry.delete()` on any row of
# : an append-only model are the same forbidden act as
# : `AuditEntry.objects.update(...)`, and until this clause they were
# : invisible: the receiver is a local name and the model's name is nowhere in it. The
# : runtime belt (`BaseModel.save`/`.delete`, ADR core-14, LF1-2) raises
# : `AppendOnlyViolation` on exactly this path — this half is its PAIR, not its
# : replacement, and the two catch different things: the belt sees every instance
# : whatever its name, at the cost of needing the line to run; this sees the line
# : without running it, at the cost of needing the binding to be legible.
# :
# : THE ASYMMETRY IS THE BELT'S, COPIED EXACTLY. `save()` refuses only when
# : `_state.adding` is False, because the ONE legitimate write an append-only
# : model ever does is its create — `entry = WidgetEntry(...)` then
# : `entry.save()`, which is `apps/example/services.py::_entry` and is the
# : worked example of a correct ledger append. `delete()` refuses always. A
# : static half that fired on both would accuse the one shape the rule exists to
# : permit, which is how a rule earns an override at its own worked example.
_INSTANCE_REWRITE_ALWAYS = ("delete",)


_INSTANCE_REWRITE_IF_READ_BACK = ("save",)


def append_only_writes(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    declared = append_only_model_names(root)
    out.targets_matched["append_only_models"] = len(declared)
    for path in _py_files(root, "apps", "config"):
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        subjects = {name for name, home in declared.items() if home != rel and name in text}
        if not subjects:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        # : local name -> (the member it was bound to, how). Built once per module.
        bound: dict[str, tuple[str, str]] = {}
        for name in sorted(subjects):
            for local, how in _names_bound_to(tree, name).items():
                if bound.get(local, ("", ""))[1] != _BOUND_READ_BACK:
                    bound[local] = (name, how)
        out.count("bound_names", len(bound))
        # : member -> (queryset-bound names, queryset-returning helpers).
        querysets = {name: _queryset_bindings(tree, name) for name in sorted(subjects)}
        out.count("queryset_bindings", sum(len(n) + len(h) for n, h in querysets.values()))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            receiver = ast.unparse(node.func.value)
            if node.func.attr in _QUERYSET_REWRITES:
                queryset_hit = False
                for name in sorted(subjects):
                    # WORD-BOUNDED, not substring . `AuditEntryDraft` is a
                    # different model that merely starts with a member's name, and
                    # a substring match made every write to it a finding with an
                    # override as the only exit — the rule accusing a bystander.
                    if re.search(rf"\b{re.escape(name)}\b", receiver):
                        out.hit(
                            rel,
                            node.lineno,
                            f"{name}.{node.func.attr}(...) — {name} declared itself "
                            "append-only (core.models.append_only); a service may create a "
                            "row and no code path anywhere may update or delete one",
                        )
                        queryset_hit = True
                        break
                else:
                    # The receiver does not NAME a member, but it may still BE
                    # one's queryset: a bound name, or a helper's answer. The
                    # same rewrite one indirection along, and the shape a
                    # manager method returning a queryset is written in.
                    for name in sorted(subjects):
                        names, helpers = querysets[name]
                        if (names or helpers) and _queryset_rooted(
                            node.func.value, name, names, helpers
                        ):
                            out.hit(
                                rel,
                                node.lineno,
                                f"{name} queryset `{receiver}`: `.{node.func.attr}(...)` "
                                f"rewrites its rows — {name} declared itself append-only "
                                "(core.models.append_only); the receiver is bound to (or "
                                f"returned as) a {name} queryset, so this is "
                                f"`{name}.objects....{node.func.attr}(...)` one indirection "
                                "along. A service may create a row and no code path anywhere "
                                "may update or delete one",
                            )
                            queryset_hit = True
                            break
                # A `.delete()` that no queryset reading claimed FALLS THROUGH to
                # the instance half below. It used to `continue` here, which
                # left `entry.delete()` on a read-back row — the instance half's
                # own `_INSTANCE_REWRITE_ALWAYS` — unreachable: the statement
                # promised it, and the arm that kept the promise never ran.
                if queryset_hit:
                    continue
            if receiver not in bound:
                continue
            model, how = bound[receiver]
            if node.func.attr in _INSTANCE_REWRITE_ALWAYS or (
                node.func.attr in _INSTANCE_REWRITE_IF_READ_BACK and how == _BOUND_READ_BACK
            ):
                out.hit(
                    rel,
                    node.lineno,
                    f"{model} row `{receiver}` ({how}): `{receiver}.{node.func.attr}()` "
                    f"rewrites it — {model} declared itself append-only "
                    "(core.models.append_only), so a row may be created and never updated "
                    "or removed. The runtime belt (`BaseModel.save`/`.delete`, ADR core-14) "
                    "raises `AppendOnlyViolation` here the moment this line runs; this is "
                    "the static half of the same wall and it fires without running it. "
                    "Create a new row that supersedes this one, or take the model out of "
                    "the append-only population — the declaration IS the promise",
                )
    return out


from quality.checks.rules_81_and_82 import (  # noqa: E402
    _BOUND_READ_BACK,
    _names_bound_to,
    _queryset_bindings,
    _queryset_rooted,
)
