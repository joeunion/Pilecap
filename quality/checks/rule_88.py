"""Rule 88: one discovery walk."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, _parse, _py_files

# --- rule 88: one discovery walk ----------------------------------------------
#
# Asking "which installed app ships a module called X" has one road —
# `apps.core.discovery.declared` (`manage.py roads discover`). A module that
# answers it with `importlib.util.find_spec(...)` or
# `import_module(f"apps.{label}…")` of its own is a second walk with its own
# idea of which apps are installed and what a missing module means. Rule 84's
# `discovery_loop` class counts the copies that also walk the registry; this
# rule counts every own walk, per app (`<app>.own-walk`).

_FIND_SPEC = "find_spec"
_IMPORT_MODULE = "import_module"
_APPS_PREFIX = "apps."


def _own_walk(node: ast.Call) -> str | None:
    """The walk this call is, or None: `find_spec(…)`, or `import_module(f"apps.…")`."""
    name = _called_name(node)
    if name == _FIND_SPEC:
        return "`find_spec(…)`"
    if name == _IMPORT_MODULE and node.args and isinstance(node.args[0], ast.JoinedStr):
        head = node.args[0].values[0] if node.args[0].values else None
        if isinstance(head, ast.Constant) and str(head.value).startswith(_APPS_PREFIX):
            return f'`import_module(f"{_APPS_PREFIX}…")`'
    return None


def one_discovery_walk(root: Path, rule: dict) -> CheckResult:
    """Rule 88. No module under `apps/` or `config/` walks the apps for a module of its own.

    The population is every production `.py` file under both roots (tests,
    migrations and fixtures skipped, as `SKIP_PARTS` says, and `apps/conftest.py`
    with them); a `find_spec(` call or an `import_module(f"apps.…")` is one
    site, counted under `<app>.own-walk` (`config.own-walk` under `config/`).
    The discovery road and its two declared readers are `scope.allow`, each
    with its reason.
    """
    out = CheckResult()
    allowed = {
        str(entry.get("path"))
        for entry in (rule.get("scope") or {}).get("allow") or []
        if entry.get("path")
    }
    for path in _py_files(root, "apps", "config"):
        rel = path.relative_to(root).as_posix()
        if _is_test_module(rel) or rel == _DRAWER_CONFTEST_PATH or rel.endswith("conftest.py"):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        if rel in allowed:
            out.count("roads_allowed")
            continue
        if _exempt(rule, rel):
            continue
        owner = rel.split("/")[1] if rel.startswith("apps/") else "config"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            walk = _own_walk(node)
            if walk is None:
                continue
            out.hit(
                rel,
                node.lineno,
                f"{walk} walks the installed apps for a module of its own — call "
                "`apps.core.discovery.declared` (`manage.py roads discover`), the one walk, "
                "so every reader agrees which apps are installed",
                klass=f"{owner}.own-walk",
            )
    return out


from quality.checks.rule_36 import _is_test_module  # noqa: E402
from quality.checks.rule_60_second_class import _DRAWER_CONFTEST_PATH  # noqa: E402
from quality.checks.rule_86 import _called_name  # noqa: E402
