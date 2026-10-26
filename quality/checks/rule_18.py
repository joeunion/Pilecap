"""Rule 18: workflow ids are deterministic."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 18: workflow ids are deterministic ----------------------------------

_START_NAMES = {"start_workflow", "start_workflow_on_commit"}
_ID_SHAPE = re.compile(r"^[^:]+:[^:]+:[^:]+:.+$")
# The one module that DEFINES the starters. Everything under it is out of the
# live scan (it is the machinery); the pin below is what watches it instead.
_STARTER_HOME = "apps/workflows/services.py"


def _assigned_values(tree: ast.Module, name: str) -> list[ast.expr]:
    """Every value ever assigned to `name` at any depth in this module."""
    values: list[ast.expr] = []
    for node in ast.walk(tree):
        names, value = _assigned(node)
        if name in names and value is not None:
            values.append(value)
    return values


def _starter_id_pin(root: Path, out: CheckResult) -> None:
    """The pin on rule 18's own excluded zone.

    `workflow_ids` skips `apps/workflows/` because that module *defines* the
    starters — and an exclusion is a promise about what lives inside it. The
    promise here is exact and mechanical: **both starters declare `id` with no
    default**, so the `f"{type}-{uuid4()}"` default the starters once minted cannot quietly
    return inside the one zone the rule cannot see. A default on `id` turns
    every caller who forgot it into a caller with no idempotency at all, and
    the rule would stay green while it happened.

    Tier: this is exit **1**, a rule-18 violation, not exit 2. Exit 2 means the
    enforcement mechanism is broken; here the mechanism works perfectly and is
    reporting a real defect in production code. The self-test proves it fires
    by planting the defect (canary `default_id_starter.py`).
    """
    path = root / _STARTER_HOME
    tree = _parse(path)
    if tree is None:
        return
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in _START_NAMES:
            continue
        out.count("starter_defs")
        args = node.args
        pairs: list[tuple[ast.arg, ast.expr | None]] = list(
            zip(args.kwonlyargs, args.kw_defaults, strict=True)
        )
        positional = [*args.posonlyargs, *args.args]
        pairs += list(
            zip(
                positional,
                [None] * (len(positional) - len(args.defaults)) + list(args.defaults),
                strict=True,
            )
        )
        declared = [(a, d) for a, d in pairs if a.arg == "id"]
        if not declared:
            out.hit(
                _STARTER_HOME,
                node.lineno,
                f"{node.name}() does not declare `id` at all — rule 18 excludes this module "
                "because it DEFINES the starters, and the pin is what the exclusion is worth: "
                "the id must be asked for, by name, on every start",
            )
            continue
        for _arg, default in declared:
            if default is not None:
                out.hit(
                    _STARTER_HOME,
                    node.lineno,
                    f"{node.name}(id={ast.unparse(default)}) — `id` has a DEFAULT inside rule "
                    "18's excluded zone; a caller that forgets the id then gets one silently, "
                    "which is the idempotency hole a required id closes. `id: str`, required.",
                )


#: The id prefix rule 18's statement does not name: a schedule-started run's id
#: spelled `system:<app>:<noun>` beside the `platform:` the platform's own
#: schedules use — one population spelled two ways, and `check_workflow_id`
#: refuses the second. Counted as the class `system-prefix` and down-only.
_SYSTEM_PREFIX = "system:"
_PREFIX_SUFFIX = "PREFIX"


def _system_prefix_ids(root: Path, out: CheckResult) -> None:
    """Every module-level `*PREFIX = "system:…"` in an app's `activities.py`, one hit each."""
    for path in _py_files(root, "apps", named={"activities.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                continue
            if not value.value.startswith(_SYSTEM_PREFIX):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id.endswith(_PREFIX_SUFFIX):
                    out.hit(
                        rel,
                        node.lineno,
                        f"{target.id} = {value.value!r} spells a schedule-started run's id "
                        f"`{_SYSTEM_PREFIX}…` — the platform's own schedules spell it "
                        "`platform:…`, and `check_workflow_id` refuses the second spelling; "
                        "spell it `platform:`",
                        klass="system-prefix",
                    )


def workflow_ids(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    _starter_id_pin(root, out)
    _system_prefix_ids(root, out)
    for path in _py_files(root, "apps"):
        # The platform app DEFINES the starters (and its interceptors override
        # a method of the same name); every callsite outside it is the subject.
        if path.relative_to(root).as_posix().startswith("apps/workflows/"):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        # Names bound from bridge.get(bridge.WORKFLOW_ID) count as id builders.
        id_builders = {"workflow_id"}
        starter_names = set(_START_NAMES)
        # An IMPORT ALIAS binds a starter just as firmly as its own name, and
        # until that pin landed it was rule 18's cheapest evasion: three characters
        # (`as begin`) and the rule went quiet on the callsite. The alias is
        # read off the import, so `from ... import start_workflow_on_commit as
        # begin` puts `begin` in the starter set for this module only.
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _START_NAMES and alias.asname:
                        starter_names.add(alias.asname)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                value = node.value
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and value.func.attr == "get"
                ):
                    arg_src = ast.unparse(value.args[0]) if value.args else ""
                    if "WORKFLOW_ID" in arg_src:
                        id_builders.add(node.targets[0].id)
                    if "START_WORKFLOW" in arg_src:
                        starter_names.add(node.targets[0].id)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = _callee_name(func) or ""
            if name not in starter_names:
                continue
            out.count("start_callsites")
            id_kw = next((k.value for k in node.keywords if k.arg == "id"), None)
            if id_kw is None:
                out.hit(
                    rel,
                    node.lineno,
                    f"{name}(...) without id= — a workflow id is deterministic, built by "
                    "workflow_id(tenant, app, noun, key)",
                )
                continue
            ok = False
            if isinstance(id_kw, ast.Call):
                f = id_kw.func
                callee = _callee_name(f) or ""
                ok = callee in id_builders
            elif isinstance(id_kw, ast.Constant) and isinstance(id_kw.value, str):
                ok = bool(_ID_SHAPE.match(id_kw.value))
            elif isinstance(id_kw, ast.Name):
                # A NAME is legal on the same two grounds a literal is, because
                # a module constant is how a fixed platform id is written once
                # and used twice:
                # 1. a variable already built by workflow_id(...) here, or
                # 2. a constant string of the house shape —
                # PLATFORM_RELAY = "platform:events:outbox:relay".
                # (2) is not a loosening: the *string* is what rule 18 judges,
                # and binding it to a name changes nothing about it. Refusing
                # it would push authors back to inlining the literal at every
                # callsite, which is worse for exactly the reason a constant
                # exists. What stays out is a name bound to anything the check
                # cannot read as one of those two — uuid4(), a parameter, a
                # settings lookup.
                bound = _assigned_values(tree, id_kw.id)
                ok = any(
                    (
                        isinstance(v, ast.Call)
                        and getattr(v.func, "id", getattr(v.func, "attr", "")) in id_builders
                    )
                    or (
                        isinstance(v, ast.Constant)
                        and isinstance(v.value, str)
                        and bool(_ID_SHAPE.match(v.value))
                    )
                    for v in bound
                )
            if not ok:
                out.hit(
                    rel,
                    node.lineno,
                    f"{name}(id=...) is not workflow_id(...) or a <tenant>:<app>:<noun>:<key> "
                    "constant — "
                    "a random id makes a retried start a second run",
                )
    return out


from quality.checks.rule_13_clauses_i_iv import _assigned  # noqa: E402
from quality.checks.rule_36 import _callee_name  # noqa: E402
