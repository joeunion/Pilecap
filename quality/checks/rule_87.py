"""Rule 87: an event's payload is the helper's."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, _parse, _read
from quality.reason_floor import MIN_REASON
from quality.worlds import comment_reason, service_modules

# --- rule 87: an event's payload is the helper's ------------------------------
#
# Rule 59's sibling. An event a webhook subscriber reads is the REST `Out` the
# route returns, through `core.schemas.event_payload` — which drops the
# per-viewer fields (`allowed_acts`) at any depth and is the one place that
# knows to. A hand `model_dump(...)`, an `exclude=` of its own or a dict literal
# is a payload nobody keeps equal to the wire. Counted per app
# (`<app>.hand-payload`), recorded at the measured count and down-only.

_EVENT_HELPER = "event_payload"
_EMIT_CALL = "emit"
#: `# payload: <reason>` — the valve for a payload that has no `Out` to carry
#: (an engine event about the platform itself), on the emit line or the
#: contiguous comment block above it.
_PAYLOAD_RE = re.compile(r"#\s*payload:\s*(.*)$")


def _is_helper_call(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Call) and _called_name(node) == _EVENT_HELPER


def _helper_returns(tree: ast.Module) -> set[str]:
    """Module-level functions whose every `return` hands back `event_payload(...)`."""
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
        if returns and all(_is_helper_call(r.value) for r in returns):
            names.add(node.name)
    return names


def _bound_only_to_helper(fn: ast.AST, name: str, helpers: set[str]) -> bool:
    """Whether every binding of `name` inside `fn` is an `event_payload(...)` (or helper) call."""
    values: list[ast.expr] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
                values.append(node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            if isinstance(node.target, ast.Name) and node.target.id == name:
                values.append(node.value)
    return bool(values) and all(_payload_through_helper(v, fn, helpers) for v in values)


def _payload_through_helper(value: ast.expr, fn: ast.AST, helpers: set[str]) -> bool:
    """`event_payload(...)`, a same-module helper returning it, or a name bound only to those."""
    if _is_helper_call(value):
        return True
    if isinstance(value, ast.Call) and _called_name(value) in helpers:
        return True
    if isinstance(value, ast.Name):
        return _bound_only_to_helper(fn, value.id, helpers)
    return False


def event_payloads_through_the_helper(root: Path, rule: dict) -> CheckResult:
    """Rule 87. Every `emit(..., payload=...)` in `apps/*/services.py` passes `event_payload(...)`.

    Accepted, one hop and no further: the call itself; a module-level function
    in the same module whose every `return` is that call; a name the enclosing
    function binds only to one of those. Anything else — a `model_dump(...)`, a
    dict literal, a helper that dumps by hand — is a hand payload, counted
    under `<app>.hand-payload`, unless the line carries `# payload: <reason>`.
    """
    out = CheckResult()
    for path in service_modules(root):
        rel = path.relative_to(root).as_posix()
        if _is_test_module(rel) or _exempt(rule, rel):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        out.count("services_modules")
        lines = _read(path).splitlines()
        helpers = _helper_returns(tree)
        app = rel.split("/")[1]
        functions = [
            n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        for fn in functions:
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call) or _called_name(node) != _EMIT_CALL:
                    continue
                payload = next((k.value for k in node.keywords if k.arg == "payload"), None)
                if payload is None:
                    continue
                out.count("emits_read")
                if _payload_through_helper(payload, fn, helpers):
                    continue
                valve = comment_reason(lines, node.lineno, _PAYLOAD_RE)
                if valve is not None and valve.holds:
                    out.count("payload_valves")
                    continue
                if valve is not None:
                    out.hit(
                        rel,
                        node.lineno,
                        f"`# payload:` on {fn.name}'s emit carries no reason (under "
                        f"{MIN_REASON} characters) — write the sentence a reviewer can "
                        "disagree with",
                        klass=f"{app}.hand-payload",
                    )
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"{fn.name} emits `payload={ast.unparse(payload)[:60]}` — a payload built by "
                    "hand, which nothing keeps equal to the wire: pass "
                    "`event_payload(<the route's Out>)` (`manage.py roads event_payload`), or "
                    "record `# payload: <reason>` when the event has no `Out` to carry",
                    klass=f"{app}.hand-payload",
                )
    return out


from quality.checks.rule_36 import _is_test_module  # noqa: E402
from quality.checks.rule_86 import _called_name  # noqa: E402
