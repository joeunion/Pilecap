"""Rule 1: auth.User is never imported."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 1: auth.User is never imported -------------------------------------


def auth_user_import(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "django.contrib.auth.models":
                for alias in node.names:
                    if alias.name == "User":
                        out.hit(
                            rel,
                            node.lineno,
                            "imports django.contrib.auth.models.User; use get_user_model() / "
                            "settings.AUTH_USER_MODEL",
                        )
            if isinstance(node, ast.Constant) and node.value == "auth.User":
                out.hit(
                    rel,
                    node.lineno,
                    'references "auth.User" by label; use settings.AUTH_USER_MODEL',
                )
    return out
