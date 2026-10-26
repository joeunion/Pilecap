"""Rule 86: a door composes no refusal body of its own."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, _parse

# --- rule 86: a door composes no refusal body of its own ----------------------
#
# Every refusal a door answers is a registered code composed ONCE
# (`core.exceptions.wire_refusal`, the MCP door's `tool_call`): the same three
# moves, the same keys, at both doors. A door that raises `HttpError(403, "No
# tenant …")` or hands a client `JsonResponse({...})` speaks a second refusal
# grammar the registry never sees — no code to branch on, no remedies, a
# sentence only one door says. Counted per app (`<app>.door-literal`), recorded
# at the measured count and down-only; the consolidation's per-app rungs bring
# each app's to zero.

#: The calls a REST door composes a body with, and the MCP door's one.
_DOOR_BODY_CALLS = frozenset({"HttpError", "JsonResponse"})
_MCP_REFUSAL_CALL = "ToolError"


def _called_name(node: ast.Call) -> str | None:
    """The last name of a call's target: `x.HttpError(...)` and `HttpError(...)` → `HttpError`."""
    target = node.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _composing_door(rel: str) -> str | None:
    """`rest` for a REST door module, `mcp` for the MCP door, else None (another door kind)."""
    parts = rel.split("/")
    if len(parts) == 3 and parts[2] == "api.py":
        return "rest"
    if len(parts) == 4 and parts[2] == "api":
        return "rest"
    if len(parts) == 3 and parts[2] == "mcp.py":
        return "mcp"
    return None


def doors_compose_no_body(root: Path, rule: dict) -> CheckResult:
    """Rule 86. A door module composes no refusal body: no `HttpError(`/`JsonResponse(` in a
    REST door, no `ToolError("…")` with a literal in an MCP door.

    The population is the door census's own (`DOOR_GLOBS`, read by
    `_door_modules`) narrowed to the two doors that answer a refusal body —
    every `apps/<x>/api.py`, every module of an `apps/<x>/api/` package and
    every `apps/<x>/mcp.py`; a hit is one call,
    counted under `<app>.door-literal`. The composers live outside it by
    construction (`apps/core/exceptions.py`, `config/api.py`), and a path the
    rule's `scope.exemptions` names is skipped with its reason.
    """
    out = CheckResult()
    for path in _door_modules(root):
        rel = path.relative_to(root).as_posix()
        door = _composing_door(rel)
        if door is None or _exempt(rule, rel):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        out.count("door_modules")
        app = rel.split("/")[1]
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if door == "rest" and name in _DOOR_BODY_CALLS:
                out.count("rest_calls_read")
                what = f"`{name}(…)`"
            elif (
                door == "mcp"
                and name == _MCP_REFUSAL_CALL
                and node.args
                and isinstance(node.args[0], (ast.Constant, ast.JoinedStr))
            ):
                out.count("mcp_calls_read")
                what = f'`{name}("…")` with a sentence of its own'
            else:
                continue
            out.hit(
                rel,
                node.lineno,
                f"{what} composes a refusal body in a door — a second refusal grammar no "
                "registry holds: raise the registered `core.exceptions` class instead, so "
                "`wire_refusal` composes the one body both doors send (`manage.py roads "
                "refuse`)",
                klass=f"{app}.door-literal",
            )
    return out


from quality.checks.rule_42 import _door_modules  # noqa: E402
