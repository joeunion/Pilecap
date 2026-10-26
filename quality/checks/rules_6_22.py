"""Rules 6 + 22: migration discipline."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _app_dirs, _parse, _py_files, _read

# --- rules 6 + 22: migration discipline ---------------------------------------


def _migration_files(app: Path) -> list[Path]:
    mig = app / "migrations"
    if not mig.is_dir():
        return []
    return sorted(p for p in mig.glob("*.py") if p.name != "__init__.py")


def migration_parents(path: Path, app_label: str) -> list[str]:
    """The same-app parents this migration's `dependencies` names, by AST.

    Factored out of `migration_leaves` so the gate's plant resolver can derive a
    fixture's parent from the same reading the rule itself does (N-Q32b). A
    resolver with its own copy of this parse would be a second opinion about
    what a leaf is, and the two would drift.
    """
    tree = _parse(path)
    if tree is None:
        return []
    deps: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "dependencies" for t in node.targets
        ):
            # Element by element: one non-literal entry (a
            # swappable_dependency call, say) must not hide the rest.
            if isinstance(node.value, (ast.List, ast.Tuple)):
                for elt in node.value.elts:
                    try:
                        item = ast.literal_eval(elt)
                    except (ValueError, SyntaxError):
                        continue
                    if isinstance(item, tuple) and len(item) == 2 and item[0] == app_label:
                        deps.append(str(item[1]))
    return deps


def app_migration_leaf(root: Path, app_label: str) -> str | None:
    """The app's ONE graph leaf, or `None` when it does not have exactly one.

    Derived from the graph — the migrations' own `dependencies` — and NOT from
    `max_migration.txt`, deliberately: rule 6's `stale_max_migration.txt` canary
    overwrites that marker while it is planted, so a resolver reading the marker
    would be reading a file another canary exists to corrupt. `None` is the
    could-not-look answer and its caller turns it into exit 2, never a guess.
    """
    app = root / "apps" / app_label
    files = _migration_files(app)
    if not files:
        return None
    names = {p.stem for p in files}
    referenced = {
        parent for path in files for parent in migration_parents(path, app_label) if parent in names
    }
    leaves = sorted(names - referenced)
    return leaves[0] if len(leaves) == 1 else None


def migration_leaves(root: Path, rule: dict) -> CheckResult:
    """Rule 6: one leaf per app, no merge migrations, max_migration.txt agrees."""
    out = CheckResult()
    for app in _app_dirs(root):
        files = _migration_files(app)
        if not files:
            continue
        out.count("apps_with_migrations")
        names = {p.stem for p in files}
        parents: dict[str, list[str]] = {}
        for path in files:
            if _parse(path) is None:
                continue
            deps = migration_parents(path, app.name)
            parents[path.stem] = deps
            rel = str(path.relative_to(root))
            same_app_parents = [d for d in deps if d in names]
            if len(same_app_parents) > 1 or "merge" in path.stem:
                out.hit(
                    rel,
                    1,
                    "a merge migration — two agents touched one app; a PM ordering "
                    "failure to surface, never to patch (makemigrations --merge is forbidden)",
                )
        referenced = {d for deps in parents.values() for d in deps if d in names}
        leaves = sorted(names - referenced)
        if len(leaves) > 1:
            # One finding per leaf FILE, so the finding names the migration that
            # forked the graph rather than the directory it lives in.
            for leaf in leaves:
                out.hit(
                    str((app / "migrations" / f"{leaf}.py").relative_to(root)),
                    1,
                    f"{app.name} has {len(leaves)} migration leaves ({', '.join(leaves)}); "
                    "one leaf per app",
                )
        marker = app / "migrations" / "max_migration.txt"
        if not marker.exists():
            out.hit(
                str((app / "migrations").relative_to(root)),
                1,
                f"{app.name} has migrations but no max_migration.txt",
            )
        elif len(leaves) == 1 and marker.read_text().strip() != leaves[0]:
            out.hit(
                str(marker.relative_to(root)),
                1,
                f"max_migration.txt says {marker.read_text().strip()!r} but the leaf is "
                f"{leaves[0]!r}",
            )
    return out


def migration_expand_contract(root: Path, rule: dict) -> CheckResult:
    """Rule 22: AddField non-null needs a default; RunPython needs a reverse;
    a drop needs the tree to have stopped referencing the name first."""
    out = CheckResult()
    for app in _app_dirs(root):
        app_code = "\n".join(_read(p) for p in _py_files(root, f"apps/{app.name}"))
        for path in _migration_files(app):
            tree = _parse(path)
            if tree is None:
                continue
            out.count("migrations_scanned")
            rel = str(path.relative_to(root))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                op = _callee_name(func) or ""
                if op == "AddField":
                    kwargs = {k.arg: k.value for k in node.keywords if k.arg}
                    fld = kwargs.get("field")
                    if isinstance(fld, ast.Call):
                        fkw = {k.arg for k in fld.keywords if k.arg}
                        null = any(
                            k.arg == "null"
                            and isinstance(k.value, ast.Constant)
                            and k.value.value is True
                            for k in fld.keywords
                        )
                        if not null and "default" not in fkw:
                            out.hit(
                                rel,
                                node.lineno,
                                "AddField of a non-nullable column without a default in the same "
                                "migration — this fails on any table with rows (expand/contract)",
                            )
                elif op == "RunPython":
                    n_args = len(node.args) + len(
                        [k for k in node.keywords if k.arg in ("code", "reverse_code")]
                    )
                    has_reverse = len(node.args) >= 2 or any(
                        k.arg == "reverse_code" for k in node.keywords
                    )
                    if n_args >= 1 and not has_reverse:
                        out.hit(
                            rel,
                            node.lineno,
                            "RunPython without a reverse — an irreversible migration blocks every "
                            "rollback below it; pass migrations.RunPython.noop if there is "
                            "nothing to undo",
                        )
                elif op == "DeleteModel":
                    for k in node.keywords:
                        if k.arg == "name" and isinstance(k.value, ast.Constant):
                            model = str(k.value.value)
                            if re.search(rf"\b{re.escape(model)}\b", app_code):
                                out.hit(
                                    rel,
                                    node.lineno,
                                    f"DeleteModel({model!r}) while the app still references the "
                                    "name — "
                                    "the drop is a later rung than the code that stops using it",
                                )
    return out


from quality.checks.rule_36 import _callee_name  # noqa: E402
