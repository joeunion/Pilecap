"""Rule 9: workflow code is deterministic."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _app_dirs, _parse

# --- rule 9: workflow code is deterministic -----------------------------------

_WF_ALLOWED_ROOTS = {
    "__future__",
    "dataclasses",
    "typing",
    "collections",
    "enum",
    "asyncio",
    "temporalio",
}
_WF_BANNED_CALLS = {
    "now",
    "utcnow",
    "today",
    "time",
    "uuid4",
    "uuid7",
    "uuid1",
    "random",
    "randint",
    "open",
    "urandom",
    # PYTHONHASHSEED is randomised per PROCESS, so `hash(x)` on a str/bytes/tuple
    # answers differently in the worker that replays than in the one that first
    # ran — a hash-keyed branch or a hash-derived partition replays down the
    # other leg and Temporal calls it a non-determinism error. Banned outright
    # rather than argued about per type.
    "hash",
}

# temporalio's own deterministic replacements live on the `workflow` module —
# `workflow.now()`, `workflow.uuid4()`, `workflow.random()`, `workflow.time()`.
# They are the SANCTIONED way to do the banned thing, recorded in history and
# replayed identically, so a call whose receiver is that module is never this
# rule's subject. (Rule 9's declared blind spot keeps their *misuse*.)
#
# The whole CHAIN is read, not just the immediate receiver: `workflow.now().time()`
# and `workflow.random().randint(1, 6)` are the correct forms of two banned names
# and would otherwise be findings against code that did exactly the right thing —
# an over-fire whose only exit is an override, which is the shape this rule
# exists to stop shipping.
_WF_SANCTIONED_RECEIVER = "workflow"


def _wf_sanctioned(callee: ast.expr) -> bool:
    """True when this call hangs off temporalio's `workflow` module, at any depth."""
    if not isinstance(callee, ast.Attribute):
        return False
    root = _chain_root(callee)
    return isinstance(root, ast.Name) and root.id == _WF_SANCTIONED_RECEIVER


def _admitted_modules(rule: dict, key: str) -> set[str]:
    """The dotted module names a scope allow-list's file paths declare."""
    return {path.removesuffix(".py").replace("/", ".") for path in _allowed_paths(rule, key)}


def workflow_determinism(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    # A platform module a workflow may import is DECLARED in the rule's scope,
    # with its reason, never added to `_WF_ALLOWED_ROOTS`: the admission is one
    # module, read off the yaml, and the consistency pass holds its path to
    # existence.
    admitted = _admitted_modules(rule, "allow_import")
    for app in _app_dirs(root):
        wf = app / "workflows.py"
        tree = _parse(wf) if wf.exists() else None
        if tree is None:
            continue
        out.count("workflow_modules")
        rel = str(wf.relative_to(root))
        for node in ast.walk(tree):
            modules: list[tuple[str, int, list[str]]] = []
            if isinstance(node, ast.Import):
                modules = [(a.name, node.lineno, []) for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [a.name for a in node.names]
                # `from apps.core import determinism` names the admitted module as `module.name`.
                if all(f"{node.module}.{n}" in admitted for n in names):
                    continue
                modules = [(node.module, node.lineno, names)]
            for mod, lineno, names in modules:
                head = mod.split(".")[0]
                if mod == "datetime":
                    bad = [n for n in names if n not in ("timedelta",)]
                    if bad or not names:
                        out.hit(
                            rel,
                            lineno,
                            f"workflows.py imports {bad or ['datetime']} — a workflow may "
                            "import timedelta and nothing else from datetime; "
                            "a clock cannot replay",
                        )
                    continue
                if mod == f"apps.{app.name}.types" or mod == f"apps.{app.name}":
                    continue
                if mod in admitted:
                    continue
                if head in _WF_ALLOWED_ROOTS:
                    continue
                out.hit(
                    rel,
                    lineno,
                    f"workflows.py imports {mod} — workflow code is deterministic: "
                    "a workflow module imports pilecap.determinism (and its app's types.py), "
                    "stdlib dataclasses/timedelta and temporalio; the ORM, pilecap's root "
                    "and the apps are the activities'",
                )
            if isinstance(node, ast.Call):
                callee = node.func
                sanctioned = _wf_sanctioned(callee)
                name = _callee_name(callee) or ""
                if name in _WF_BANNED_CALLS and not sanctioned:
                    why = (
                        "hash() is seeded per PROCESS (PYTHONHASHSEED), so a replay in another "
                        "worker takes the other branch"
                        if name == "hash"
                        else "no clock, no randomness, no I/O in a workflow"
                    )
                    out.hit(
                        rel,
                        node.lineno,
                        f"workflows.py calls {name}() — {why}; use an activity or "
                        f"workflow.now()/workflow.uuid4(), which replay identically",
                    )
    return out


from quality.checks.rule_36 import _callee_name  # noqa: E402
from quality.checks.rules_10_12 import _chain_root  # noqa: E402
from quality.checks.rules_56_and_57 import _allowed_paths  # noqa: E402
