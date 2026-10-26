"""Rule 7: depends_on is honest."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _app_dirs, _parse, _py_files

# --- rule 7: depends_on is honest ---------------------------------------------


def _declared_depends(app: Path) -> set[str] | None:
    tree = _parse(app / "apps.py")
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                names, value = _assigned(stmt)
                target = names[0] if len(names) == 1 else None
                if target == "depends_on" and value is not None:
                    try:
                        return {str(x) for x in ast.literal_eval(value)}
                    except (ValueError, SyntaxError):
                        return None
    return None


def depends_on_imports(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    labels = {app.name for app in _app_dirs(root)}
    for app in _app_dirs(root):
        declared = _declared_depends(app)
        if declared is None:
            out.hit(
                str((app / "apps.py").relative_to(root)),
                1,
                f"{app.name} declares no depends_on on its AppConfig",
            )
            continue
        out.count("apps_scanned")
        allowed = declared | {app.name}
        for path in _py_files(root, f"apps/{app.name}"):
            tree = _parse(path)
            if tree is None:
                continue
            out.count("files_scanned")
            rel = str(path.relative_to(root))
            for node in ast.walk(tree):
                modules: list[tuple[str, int]] = []
                if isinstance(node, ast.Import):
                    modules = [(a.name, node.lineno) for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    modules = [(node.module, node.lineno)]
                for mod, lineno in modules:
                    parts = mod.split(".")
                    if len(parts) >= 2 and parts[0] == "apps" and parts[1] in labels:
                        if parts[1] not in allowed:
                            out.hit(
                                rel,
                                lineno,
                                f"imports apps.{parts[1]} but {app.name}'s AppConfig.depends_on "
                                f"declares only {sorted(declared)} — declare it or invert "
                                "through core.bridge",
                            )
    return out


from quality.checks.rule_13_clauses_i_iv import _assigned  # noqa: E402
