"""Rule 14: HTTP vocabulary never below the doors."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files
from quality.worlds import SERVICE_MODULE

# --- rule 14: HTTP vocabulary never below the doors ---------------------------

_HTTP_NAMES = {"HttpError", "Http404", "HttpResponse", "JsonResponse", "HttpResponseRedirect"}
_BELOW_DOOR_FILES = {SERVICE_MODULE, "selectors.py", "models.py", "policies.py"}


def http_below_doors(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", named=_BELOW_DOOR_FILES):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in ("ninja.errors", "django.http"):
                names = [a.name for a in node.names if a.name in _HTTP_NAMES]
                if names:
                    out.hit(
                        rel,
                        node.lineno,
                        f"imports {', '.join(names)} below the door layer — services raise "
                        "core.exceptions.*; config/api.py owns the one mapper",
                    )
            if isinstance(node, ast.Name) and node.id in _HTTP_NAMES:
                out.hit(
                    rel,
                    node.lineno,
                    f"uses {node.id} below the door layer — raise core.exceptions.* instead",
                )
    return out
