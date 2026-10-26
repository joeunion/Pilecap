"""Rule 19: structured logging only."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, _parse, _py_files

# --- rule 19: structured logging only -----------------------------------------

_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
_LOG_CONFIG_FILES = {"apps/core/observability.py", "apps/core/log.py"}


def structured_logging(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                out.hit(
                    rel,
                    node.lineno,
                    "print() — every line goes through core.log or a command's self.stdout",
                )
            if rel not in _LOG_CONFIG_FILES:
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "getLogger"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "logging"
                ):
                    out.hit(
                        rel,
                        node.lineno,
                        "logging.getLogger() — core.log.get_logger is the one logger; only "
                        "core/observability.py configures logging",
                    )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LOG_METHODS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in ("log", "logger")
                and node.args
                and not _exempt(rule, rel)
            ):
                first = node.args[0]
                if isinstance(first, ast.JoinedStr) or (
                    isinstance(first, ast.BinOp) and isinstance(first.op, ast.Mod)
                ):
                    out.hit(
                        rel,
                        node.lineno,
                        "an f-string/% in a log call — the event is a constant name; the "
                        "variables are keyword context",
                    )
    return out
