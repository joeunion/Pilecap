"""Rule 55: a tenant-wide kind is asked at a node the caller resolved."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import _RULE8_FILES, CheckResult, _app_dirs, _parse, _py_files, _read
from quality.worlds import comment_reason

# --- rule 55: a tenant-wide kind is asked at a node the caller resolved --------
#
# ADR core-4's sibling. `allows` resolves the node it judges at: handed a row it
# uses the row's `organization`, and handed NOTHING it falls back to the acting
# hat — which is right for every kind that HAS a node, and wrong for every kind
# that does not. A `sso_connection` is the tenant's, not a branch's; so is a
# `role`, a `tenant`, an `api_token`. Asked with no node, or with the row
# itself, one of those resolves at the caller's hat, where a branch admin holds
# `*` — and that is how an administrator of one branch came to administer the
# whole tenant's identity provider while every test in the tree stayed green.
#
# THE POPULATION IS DERIVED, from the same two facts rule 13's clause (i) and
# rule 24 already derive and by the same functions — `model_kinds` for the
# kind→model map, and `org_scoped_model_names` plus the class body's own
# `organization = models.ForeignKey(` for "does this row name a node". One
# derivation, three rules, so a model that gains a node leaves this population
# on the same run it enters rule 24's.
#
# WHAT IS OUT, BY CONSTRUCTION AND DECLARED:
#
# * a key whose kind is `organization` — an organization IS its own node, so
#   `require(actor, "organization.update", org)` is already at the node;
# * a key whose kind is virtual (`deployment`) or in no registry at all — the
#   first has no row by declaration, the second is rule 54 (a)'s finding and
#   its non-conforming ratchet is the belt;
# * a key that is neither a literal nor a module-level string constant — rule
#   13's clause (iv) owns it and `# authz-key:` is its valve;
# * `holds(actor, key, at=...)`, whose node is explicit in the signature.

#: `# hat-scoped: <reason>` — the one valve, on the line or the contiguous
#: comment block above it. A bare one is its own finding, which is rule 26's
#: device and the gate's own rule about its overrides: an escape hatch nobody
#: has to justify is an off switch.
_HAT_SCOPED_RE = re.compile(r"#\s*hat-scoped:\s*(.*)$")

#: The modules a capability is asked in. Rule 13's set, plus the shell doors —
#: a management command is a door (rule 42 counts it as one), and an operator
#: act on a tenant-wide kind is exactly the shape that must name its node.
_RULE55_FILES = frozenset(_RULE8_FILES | {"policies.py", "adapter.py", "views.py"})

#: The name whose call resolves a tenant's root. Named rather than derived
#: because it IS the answer this rule is pushing callers towards, and a product
#: that renames it has renamed the primitive.
_ROOT_CALL = "root_organization"


def _command_files(root: Path) -> list[Path]:
    """Every `apps/*/management/commands/*.py` — the shell doors."""
    out: list[Path] = []
    for app in _app_dirs(root):
        commands = app / "management" / "commands"
        if commands.is_dir():
            out += [p for p in sorted(commands.glob("*.py")) if p.name != "__init__.py"]
    return out


def tenant_wide_kind_names(root: Path) -> set[str]:
    """Every kind whose model names no organization. The rule's whole subject.

    `organization` is removed last and deliberately: it derives a kind like any
    other model and it is the one kind that IS a node, so leaving it in would
    make every `require(actor, "organization.create", parent)` a finding about
    the node it was already asked at.
    """
    facts = _model_facts(root)
    kinds = model_kinds(root)
    org_scoped = org_scoped_model_names(root)
    out: set[str] = set()
    for name, kind in kinds.items():
        if kind is None or facts[name]["abstract"]:
            continue
        if "organization" in facts[name]["foreign_keys"] or name in org_scoped:
            continue
        out.add(kind)
    out.discard("organization")
    return out


def _organization_names(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[set[str], set[str]]:
    """(names holding an Organization, names bound to a resolved root).

    Two sets and not one, because the messages differ and a reader holding the
    red needs to know which half they have: a parameter typed `Organization` is
    a node the CALLER resolved, and a local bound to `root_organization(...)` is
    a node THIS function resolved. Both satisfy the rule; neither is guessed at.
    """
    typed = {
        arg.arg for arg in _all_args(fn) if "Organization" in _annotation_names(arg.annotation)
    }
    rooted: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if "Organization" in _annotation_names(node.annotation):
                typed.add(node.target.id)
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        called = _callee_name(func) or ""
        if called != _ROOT_CALL:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                rooted.add(target.id)
    return typed, rooted


def _node_verdict(arg: ast.expr | None, typed: set[str], rooted: set[str]) -> tuple[bool, str]:
    """(is it a node the caller resolved, how it is spelled)."""
    if arg is None:
        return False, "with no third argument at all"
    if isinstance(arg, ast.Constant) and arg.value is None:
        return False, "with an explicit `None`"
    if isinstance(arg, ast.Call):
        func = arg.func
        called = _callee_name(func) or ""
        if called == _ROOT_CALL:
            return True, f"{_ROOT_CALL}(...)"
        return False, f"with the result of `{called}(...)`"
    if isinstance(arg, ast.Name):
        if arg.id in rooted:
            return True, f"`{arg.id}`, bound to {_ROOT_CALL}(...)"
        if arg.id in typed:
            return True, f"`{arg.id}`, a parameter annotated Organization"
        return False, f"with `{arg.id}`, which is the ROW rather than a node"
    if isinstance(arg, ast.Attribute):
        if arg.attr == "organization":
            return True, "an expression ending in `.organization`"
        return False, f"with `.{arg.attr}`, which names no node"
    return False, f"with `{ast.unparse(arg)[:48]}`, which names no node"


def tenant_wide_kinds_ask_at_the_root(root: Path, rule: dict) -> CheckResult:
    """Rule 55. Findings are classed by APP, so one app's backlog cannot pay for
    another's growth and each sweep drives its own app to zero."""
    out = CheckResult()
    kinds = tenant_wide_kind_names(root)
    out.targets_matched["tenant_wide_kinds"] = len(kinds)
    # Seeded at zero and PRINTED whatever it is: a valve nobody counts is an off
    # switch, and a count that only appears when it is non-zero is one nobody
    # sees fall to zero either.
    out.targets_matched["hat_scoped_valves"] = 0
    out.targets_matched["sites_seen"] = 0
    files = _py_files(root, "apps", named=set(_RULE55_FILES))
    files += _command_files(root)
    for path in sorted(set(files)):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = path.relative_to(root).as_posix()
        app = rel.split("/")[1]
        lines = _read(path).splitlines()
        constants = string_constants(root, path, tree)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            typed, rooted = _organization_names(fn)
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else (func.attr if isinstance(func, ast.Attribute) else "")
                )
                if name not in ("require", "allows") or len(node.args) < 2:
                    continue
                keyarg = node.args[1]
                key = None
                if isinstance(keyarg, ast.Constant) and isinstance(keyarg.value, str):
                    key = keyarg.value
                elif isinstance(keyarg, ast.Name) and keyarg.id in constants:
                    key = constants[keyarg.id]
                if key is None or "." not in key:
                    continue
                kind = key.rsplit(".", 1)[0]
                if kind not in kinds:
                    continue
                out.count("sites_seen")
                third = node.args[2] if len(node.args) > 2 else None
                resolved, how = _node_verdict(third, typed, rooted)
                if resolved:
                    continue
                reason = comment_reason(lines, node.lineno, _HAT_SCOPED_RE)
                if reason is not None and reason.holds:
                    out.count("hat_scoped_valves")
                    continue
                if reason is not None:
                    out.hit(
                        rel,
                        node.lineno,
                        f"`# hat-scoped:` with no reason on {fn.name} — an escape hatch nobody "
                        "has to justify is an off switch; write the sentence a reviewer can "
                        "disagree with",
                        klass=app,
                    )
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"{fn.name} asks for {key!r} {how}. The kind {kind!r} names no "
                    "organization, so there is no node in the question and `allows` falls "
                    "back to the ACTING HAT — where a branch administrator holds `*`. Pass "
                    f"the node the caller resolved ({_ROOT_CALL}(tenant=tenant), an "
                    "Organization parameter, or a row's `.organization`), or record "
                    "`# hat-scoped: <reason>` saying why the hat is the right node here",
                    klass=app,
                )
    return out


from quality.checks.rule_13_clauses_i_iv import (  # noqa: E402
    _model_facts,
    model_kinds,
    string_constants,
)
from quality.checks.rule_24 import org_scoped_model_names  # noqa: E402
from quality.checks.rule_26 import _all_args, _annotation_names  # noqa: E402
from quality.checks.rule_36 import _callee_name  # noqa: E402
