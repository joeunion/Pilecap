"""House-rule checks — pure AST/file scans over a tree, no Django required.

Every check returns a CheckResult carrying findings (path, line, message) AND
targets_matched, so the gate can distinguish pass / fail / UNBOUND (the scope
resolved to too little — green-because-empty is not a pass).

The Django system checks (rules 2, 3, 11, 13-half, 15, 17, 21) live in
`apps/core/checks.py` and run through `manage.py check --tag djb`; the gate
runs that as its own leg. Everything here is what AST can see without a
running registry.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Directory parts never scanned. Tests are proof, not product; migrations are
# rule 22's own subject and get their own walker; fixtures are planted wrongness.
SKIP_PARTS = {"__pycache__", "migrations", "tests", "canary", "negative"}


@dataclass
class Finding:
    path: str  # relative to the scanned root
    line: int
    msg: str
    # : Which CLASS of the rule this finding belongs to, when the rule has more
    # : than one (rule 16's naming grammar has seven). It is what the gate's
    # : ratchets are counted against, so a backlog in one class cannot pay for
    # : growth in another. Empty for a rule with a single subject.
    klass: str = ""

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.msg}"


@dataclass
class CheckResult:
    findings: list[Finding] = field(default_factory=list)
    targets_matched: dict = field(default_factory=dict)

    def hit(
        self,
        path: Path | str,
        line: int,
        msg: str,
        root: Path | None = None,
        klass: str = "",
    ) -> None:
        rel = str(path)
        if root is not None and isinstance(path, Path):
            try:
                rel = str(path.relative_to(root))
            except ValueError:
                rel = str(path)
        self.findings.append(Finding(rel, line, msg, klass))

    def count(self, key: str, n: int = 1) -> None:
        self.targets_matched[key] = self.targets_matched.get(key, 0) + n


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return ""


_AST_CACHE: dict[tuple[str, float], ast.Module | None] = {}


def _parse(path: Path) -> ast.Module | None:
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return None
    if key in _AST_CACHE:
        return _AST_CACHE[key]
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        tree = None
    _AST_CACHE[key] = tree
    return tree


def _py_files(root: Path, *subtrees: str, named: set[str] | None = None) -> list[Path]:
    """Every .py file under the subtrees, minus SKIP_PARTS; optionally only
    files with the given basenames. DERIVED from the tree, never typed."""
    out: list[Path] = []
    for sub in subtrees:
        base = root / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if SKIP_PARTS & set(path.relative_to(base).parts):
                continue
            if named is not None and path.name not in named:
                continue
            out.append(path)
    return out


def _app_dirs(root: Path) -> list[Path]:
    """Every app package under apps/ — a directory with an apps.py."""
    base = root / "apps"
    if not base.exists():
        return []
    return sorted(d for d in base.iterdir() if d.is_dir() and (d / "apps.py").exists())


def _exempt(rule: dict, path_rel: str, function: str | None = None) -> bool:
    """Whether rules.yaml exempts this site, by path (and function when given).

    Exemptions live in the rule's scope, each with a reason — a judgement a
    person wrote down, visible in one file, not an edit to somebody's app.
    """
    for entry in (rule.get("scope") or {}).get("exemptions") or []:
        if entry.get("path") and entry["path"] != path_rel:
            continue
        wanted = entry.get("function")
        if wanted and wanted != function:
            continue
        if entry.get("path") or wanted:
            return True
    return False


def _enclosing_functions(tree: ast.Module) -> list[tuple[int, int, str]]:
    """(start, end, name) for every function, for attributing a line to one."""
    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            spans.append((node.lineno, node.end_lineno or node.lineno, node.name))
    return spans


def _function_at(spans: list[tuple[int, int, str]], line: int) -> str | None:
    best: tuple[int, str] | None = None
    for start, end, name in spans:
        if start <= line <= end and (best is None or start > best[0]):
            best = (start, name)
    return best[1] if best else None


# --- scoped-model discovery (rules 8, 12, 13) --------------------------------

_SCOPED_BASE = "TenantScopedModel"


def scoped_model_names(root: Path) -> set[str]:
    """Every class name that inherits TenantScopedModel, transitively, by AST.

    Derived from the tree on every run: a new scoped model is in scope the
    moment it exists, without anybody editing a list.
    """
    class_bases: dict[str, set[str]] = {}
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = set()
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.add(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.add(b.attr)
            class_bases.setdefault(node.name, set()).update(bases)
    scoped = {_SCOPED_BASE}
    changed = True
    while changed:
        changed = False
        for name, bases in class_bases.items():
            if name not in scoped and bases & scoped:
                scoped.add(name)
                changed = True
    scoped.discard(_SCOPED_BASE)
    return scoped


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


# --- rule 4: no business logic in signals ------------------------------------

_SIGNAL_MODULES = ("django.dispatch", "django.db.models.signals")


def signal_logic(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        imports_signals = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith(_SIGNAL_MODULES)
            ):
                imports_signals = True
            if isinstance(node, ast.Import) and any(
                a.name.startswith(_SIGNAL_MODULES) for a in node.names
            ):
                imports_signals = True
        if path.name == "signals.py":
            has_defs = any(
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree)
            )
            if has_defs:
                out.hit(
                    rel,
                    1,
                    "a signals.py with function bodies — services own writes; signals are where "
                    "logic hides",
                )
        if not imports_signals:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    name = dec.func if isinstance(dec, ast.Call) else dec
                    if isinstance(name, ast.Name) and name.id == "receiver":
                        out.hit(
                            rel,
                            node.lineno,
                            f"@receiver on {node.name}; move the logic into a service",
                        )
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "connect"
            ):
                out.hit(rel, node.lineno, "signal .connect(); services own writes, not receivers")
    return out


# --- rule 5: list endpoints carry a query budget ------------------------------


def _has_paginate(tree: ast.Module) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Name) and target.id == "paginate":
                lines.append(node.lineno)
    return lines


# --- the hot-path registry (rules 5 + 35, ADR gate-2) --------------------------
#
# The registry is rule 35's `registry:` list in quality/rules.yaml (dotted
# selector paths — the plan's ratified location); quality/budgets.yaml
# `hot_path_query_counts` holds each entry's gate-scale statement count under
# the rising-floor grammar. Rule 5's check holds the seam (every entry counted,
# every count registered, every entry citing the measurement-doc line that
# earned it — measured before enforced, the shape); rule 35's check runs
# the probe that EXPLAINs the probed entries' real reads.


def hot_path_registry(root: Path) -> list[dict]:
    rules = yaml.safe_load((root / "quality" / "rules.yaml").read_text())["rules"]
    for rule in rules:
        if str(rule["id"]) == "35":
            return list(rule.get("registry") or [])
    return []


def hot_path_counts(root: Path) -> dict[str, Any]:
    budgets_path = root / "quality" / "budgets.yaml"
    if not budgets_path.is_file():
        return {}
    budgets = yaml.safe_load(budgets_path.read_text()) or {}
    return dict(budgets.get("hot_path_query_counts") or {})


def _dotted_to_file(root: Path, dotted: str) -> str:
    """The longest module-file prefix of a dotted path, as a repo-relative path."""
    parts = dotted.split("#")[0].split(".")
    for length in range(len(parts), 0, -1):
        candidate = Path(*parts[:length]).with_suffix(".py")
        if (root / candidate).is_file():
            return str(candidate)
    return "quality/rules.yaml"


def _module_constant(root: Path, path_rel: str, name: str) -> Any:
    tree = _parse(root / path_rel)
    if tree is None:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    try:
                        return ast.literal_eval(node.value)
                    except ValueError:
                        return None
    return None


def _hierarchy_proposal_paths(root: Path) -> set[str]:
    """The keys of perf/measure_hierarchy.py::HOT_PATH_PROPOSALS — M1's
    machine-readable seam ("read them from the module, not retype them")."""
    tree = _parse(root / "perf" / "measure_hierarchy.py")
    if tree is None:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "HOT_PATH_PROPOSALS":
                    if isinstance(node.value, ast.Dict):
                        return {
                            k.value
                            for k in node.value.keys
                            if isinstance(k, ast.Constant) and isinstance(k.value, str)
                        }
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "HOT_PATH_PROPOSALS" and isinstance(node.value, ast.Dict):
                return {
                    k.value
                    for k in node.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
    return set()


# : A spec hash is twelve hex characters (`perf/seed.py::spec_hash`). Used only
# : to say WHICH hash a doc is carrying when it carries the wrong one — the
# : verdict itself is membership of the computed hash, never this pattern.
SPEC_STAMP_RE = re.compile(r"\b[0-9a-f]{12}\b")

# : The envelope is not a measurement doc and cites nothing, so no registry entry
# : names it — and it is the file that states the spec for the whole product.
# : Named here rather than derived, with the reason.
SCALE_ENVELOPE = "docs/product/scale-envelope.md"


def _scale_spec_stamp(root: Path) -> str | None:
    """The hash `perf/seed.py::ScaleSpec` has right now, or None if unreadable.

    **`quality/` may import `perf/`; the reverse is the boundary.** The gate is
    allowed to read the harness's own contract — that is the whole mechanism
    here, a doc's claim compared against the artifact rather than against a
    number somebody retyped — and `perf/seed.py` is written to be importable
    before `django.setup()` precisely so that callers outside the harness can do
    it. Nothing in `perf/` imports `quality/`, and nothing should: the harness
    must not learn to satisfy the gate.

    `ScaleSpec()` is constructed here rather than reading `DEFAULT_SPEC`,
    because a spec whose FIELDS changed is the case this exists to catch and
    `DEFAULT_SPEC` is bound at the seeder's import.

    **Reloaded, not imported.** The gate runs every rule in one process and the
    self-test plants into the real tree between rules, so a cached `perf.seed`
    would make this check answer from the seeder as it was before the plant —
    a canary that cannot fire because the module it moves was already read.
    """
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        importlib.invalidate_caches()
        module = importlib.reload(importlib.import_module("perf.seed"))
    except Exception:  # noqa: BLE001 # any import failure is the same answer
        return None
    return str(module.spec_hash(module.ScaleSpec()))


def _stamp_findings(root: Path, registry: list[dict], out: CheckResult) -> None:
    """Every cited measurement doc, and the envelope, carries the current spec hash.

    A measurement doc's numbers describe ONE world. Until P3 F2 the docs said
    which — four of them carried `9959d8a1c073` — and nothing compared it to
    anything, so when `ScaleSpec` moved to `df07df482a95` every number in every
    doc went on citing a world that no longer existed, in silence, and the fifth
    doc carried no hash at all (done-line item 1). The stamp the
    seeder puts in the DATABASE is checked on every `perf.sh` run; the stamp in
    the PROSE was checked by nobody.

    Counts `stamp_candidates` (docs examined — the rule's floor, so a check
    that found nothing to stamp reads as UNBOUND rather than as a pass) and
    `stamped_docs` (docs that carry the current hash — the verdict, printed).
    """
    stamp = _scale_spec_stamp(root)
    if stamp is None:
        out.hit(
            "perf/seed.py",
            0,
            "perf/seed.py::ScaleSpec could not be imported, so no measurement doc's "
            "spec stamp can be compared with the spec — the seam is unenforced, not clean",
        )
        return
    docs = sorted(
        {
            str((entry.get("citation") or {}).get("doc", ""))
            for entry in registry
            if (entry.get("citation") or {}).get("doc")
        }
        | {SCALE_ENVELOPE}
    )
    for doc_rel in docs:
        doc_path = root / doc_rel
        if not doc_path.is_file():
            continue  # the citation half above already fires on a missing doc
        # The FLOOR rides on how many docs were examined, never on how many
        # passed: a stale stamp is a violation (exit 1) and an empty doc set is
        # broken enforcement (exit 2), and conflating the two would report a
        # `ScaleSpec` move as the gate being broken.
        out.count("stamp_candidates", 1)
        carried = sorted(set(SPEC_STAMP_RE.findall(doc_path.read_text())))
        if stamp in carried:
            out.count("stamped_docs", 1)
            continue
        out.hit(
            doc_rel,
            0,
            f"this doc's spec stamp is {', '.join(carried) if carried else 'MISSING'} and "
            f"perf/seed.py::ScaleSpec hashes to {stamp} — every number in it was measured "
            "against a world the fixture contract no longer declares, or against one it "
            "never named. Re-run the census and re-stamp, or say which spec the numbers "
            "are for",
        )


def api_modules(app: Path) -> list[Path]:
    """Where an app's routes live — `api.py`, or every module of an `api/` package.

    Both halves of rule 5 used to ask `app / "api.py"` and `continue` when
    it was absent, so an app whose routes had outgrown one file was not covered
    by a rule whose own statement says "every paginated list endpoint's app".
    The statement was the contract and the implementation was narrower than it;
    this is that discrepancy closed, not the contract widened. `apps/core` is the
    first such app (B-CORE's organizations, memberships and invitations lists),
    and every one of its three paginated routes was outside the census.

    `config/api.py` mounts an app by the `router` its `api` module exposes and
    does not care which of the two shapes holds it, so the population here is
    the one the mount already accepts.
    """
    flat = app / "api.py"
    if flat.is_file():
        return [flat]
    package = app / "api"
    if package.is_dir():
        return sorted(p for p in package.glob("*.py"))
    return []


def _app_is_pinned(app: Path) -> bool:
    """Whether anything in this app's tests pins a query count.

    App-level on purpose — route accuracy is review's, and rule 5's
    `does_not_cover` says so. It is also why the canaries plant into the gate's
    own probe app: a pinned app absorbs any route planted into it.
    """
    tests = app / "tests"
    if not tests.exists():
        return False
    return any(
        "assert_num_queries" in _read(p) or "assertNumQueries" in _read(p)
        for p in sorted(tests.rglob("*.py"))
    )


def query_budget_tests(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    # -- the app half: every paginated list route's app carries a pin ----------
    for app in _app_dirs(root):
        paginated: list[int] = []
        first_home: Path | None = None
        for api in api_modules(app):
            tree = _parse(api)
            if tree is None:
                continue
            found = _has_paginate(tree)
            if found and first_home is None:
                first_home = api
            paginated += found
        out.count("paginated_routes", len(paginated))
        if not paginated or first_home is None:
            continue
        if not _app_is_pinned(app):
            rel = str(first_home.relative_to(root))
            out.hit(
                rel,
                paginated[0],
                f"{app.name} has a paginated list route but no test pins its query count "
                "(assert_num_queries) — an N+1 here is a slow page, not a failure",
            )

    # -- the registry half (ADR gate-2): the declared hot paths ----------------
    registry = hot_path_registry(root)
    counts = hot_path_counts(root)
    out.count("hot_paths", len(registry))
    registered_paths = {str(entry.get("path", "")) for entry in registry}
    for entry in registry:
        dotted = str(entry.get("path", ""))
        where = _dotted_to_file(root, dotted)
        if dotted not in counts:
            out.hit(
                "quality/budgets.yaml",
                0,
                f"hot path {dotted} has no recorded count under hot_path_query_counts — "
                "a registered path with no measured number is vibes with teeth",
            )
        for spec, wanted in (entry.get("constants") or {}).items():
            const_file, _, const_name = str(spec).partition("::")
            measured = _module_constant(root, const_file, const_name)
            if measured != wanted:
                out.hit(
                    const_file,
                    0,
                    f"hot path {dotted}: {const_name} is {measured!r}, not the registered "
                    f"{wanted!r} — the ceiling the measurement doc pinned has moved without "
                    "the registry moving with it",
                )
        pin_test = entry.get("pin_test")
        if pin_test:
            pin_path = root / str(pin_test)
            if not pin_path.is_file() or "assert_num_queries" not in _read(pin_path):
                out.hit(
                    where,
                    0,
                    f"hot path {dotted} points at pin {pin_test}, which is missing or "
                    "carries no assert_num_queries — the gate-scale pin is gone",
                )
    # -- the stamp seam: a cited doc names the world it measured -----------------
    _stamp_findings(root, registry, out)

    for dotted in counts:
        if str(dotted) not in registered_paths:
            out.hit(
                "quality/budgets.yaml",
                0,
                f"hot_path_query_counts records {dotted}, which no registry entry declares — "
                "a count with no cited measurement behind it; register it "
                "with its citation in quality/rules.yaml, or remove the number",
            )
    for dotted in sorted(_hierarchy_proposal_paths(root)):
        if dotted not in registered_paths:
            out.hit(
                "perf/measure_hierarchy.py",
                0,
                f"HOT_PATH_PROPOSALS proposes {dotted} and the registry does not carry it — "
                "M1-2's seam: the module is the machine-readable proposal and the registry "
                "must consume it or record why not",
            )
    return out


# --- rule 7: depends_on is honest ---------------------------------------------


def _declared_depends(app: Path) -> set[str] | None:
    tree = _parse(app / "apps.py")
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                target = None
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    target, value = stmt.target.id, stmt.value
                elif (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    target, value = stmt.targets[0].id, stmt.value
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


# --- rule 8: scoped models are read through for_tenant ------------------------

_RULE8_FILES = {
    "api.py",
    "mcp.py",
    "services.py",
    "selectors.py",
    "activities.py",
    "consumers.py",
    "admin.py",
    "receivers.py",
}


def scoped_reads(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    scoped = scoped_model_names(root)
    out.targets_matched["scoped_models"] = len(scoped)
    files = _py_files(root, "apps", named=_RULE8_FILES) + _py_files(root, "config")
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        spans = _enclosing_functions(tree)
        # X.objects reached through for_tenant is the right form; anything else
        # on a scoped model is the leak-shaped read this rule refuses.
        ok_parents: set[int] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "for_tenant"
                and isinstance(node.value, ast.Attribute)
            ):
                ok_parents.add(id(node.value))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Attribute)
                and node.attr == "objects"
                and isinstance(node.value, ast.Name)
                and node.value.id in scoped
            ):
                continue
            if id(node) in ok_parents:
                continue
            fn = _function_at(spans, node.lineno)
            if _exempt(rule, rel, fn):
                continue
            out.hit(
                rel,
                node.lineno,
                f"bare {node.value.id}.objects on a scoped model — read through "
                f"{node.value.id}.objects.for_tenant(tenant), or carry # rule-8: <reason>",
            )
    return out


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
                op = (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else (func.id if isinstance(func, ast.Name) else "")
                )
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
    # rather than argued about per type (P1-R0 F4).
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
# an over-fire whose only exit is an override, which is the shape was booked
# to stop shipping.
_WF_SANCTIONED_RECEIVER = "workflow"


def _wf_sanctioned(callee: ast.expr) -> bool:
    """True when this call hangs off temporalio's `workflow` module, at any depth."""
    if not isinstance(callee, ast.Attribute):
        return False
    root = _chain_root(callee)
    return isinstance(root, ast.Name) and root.id == _WF_SANCTIONED_RECEIVER


def workflow_determinism(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
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
                modules = [(node.module, node.lineno, [a.name for a in node.names])]
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
                if head in _WF_ALLOWED_ROOTS:
                    continue
                out.hit(
                    rel,
                    lineno,
                    f"workflows.py imports {mod} — workflow code is deterministic: stdlib "
                    "dataclasses/"
                    f"timedelta, temporalio and the app's types.py only; I/O lives in activities",
                )
            if isinstance(node, ast.Call):
                callee = node.func
                sanctioned = _wf_sanctioned(callee)
                name = (
                    callee.attr
                    if isinstance(callee, ast.Attribute)
                    else (callee.id if isinstance(callee, ast.Name) else "")
                )
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


# --- rules 10 + 12: doors and selectors never write; services return objects ---

_DOOR_FILES = {"api.py", "mcp.py", "consumers.py", "receivers.py", "admin.py", "activities.py"}
_WRITE_MANAGER_CALLS = {"create", "get_or_create", "update_or_create", "bulk_create", "bulk_update"}
# Receivers whose .save()/.delete() is not an ORM write. `cache.delete(key)` was
# found in the wild (connections/api.py) and is the negative fixture.
_NON_MODEL_RECEIVERS = {"cache", "caches", "session", "storage", "self"}


def _chain_root(node: ast.expr) -> ast.expr:
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript, ast.Await)):
        if isinstance(node, ast.Attribute):
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        elif isinstance(node, ast.Subscript):
            node = node.value
        else:
            node = node.value
    return node


def _write_calls(tree: ast.Module) -> list[tuple[int, str]]:
    """(line, description) for every direct ORM write this file makes."""
    hits: list[tuple[int, str]] = []
    # A decorator is a call too — `@router.delete("/{id}/")` is a route, not a
    # write — so decorator expressions are excluded from the walk wholesale.
    decorator_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for dec in node.decorator_list:
                for sub in ast.walk(dec):
                    decorator_nodes.add(id(sub))
    for node in ast.walk(tree):
        if id(node) in decorator_nodes:
            continue
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        recv = node.func.value
        # Manager writes: X.objects.create(...) and friends.
        if (
            attr in _WRITE_MANAGER_CALLS
            and isinstance(recv, ast.Attribute)
            and recv.attr == "objects"
        ):
            hits.append((node.lineno, f".objects.{attr}()"))
            continue
        # Queryset writes: ....filter(...).update(...) / .delete().
        if attr in ("update", "delete") and isinstance(recv, ast.Call):
            inner = recv.func
            if isinstance(inner, ast.Attribute) and inner.attr in (
                "filter",
                "exclude",
                "all",
                "for_tenant",
            ):
                hits.append((node.lineno, f".{inner.attr}(...).{attr}()"))
                continue
        # Instance writes: obj.save() / obj.delete() on a plain name.
        if attr in ("save", "delete") and isinstance(recv, ast.Name):
            if recv.id in _NON_MODEL_RECEIVERS:
                continue
            hits.append((node.lineno, f"{recv.id}.{attr}()"))
    return hits


def door_writes(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", named=_DOOR_FILES):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("door_files")
        rel = str(path.relative_to(root))
        spans = _enclosing_functions(tree)
        for lineno, what in _write_calls(tree):
            fn = _function_at(spans, lineno)
            if _exempt(rule, rel, fn):
                continue
            out.hit(
                rel,
                lineno,
                f"a door writes ({what}) — every door calls services; services own writes",
            )
    return out


_QS_TAIL = {
    "filter",
    "exclude",
    "all",
    "order_by",
    "values",
    "values_list",
    "annotate",
    "select_related",
    "prefetch_related",
    "for_tenant",
    "only",
    "defer",
}


def selector_service_split(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", named={"selectors.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("selector_files")
        rel = str(path.relative_to(root))
        for lineno, what in _write_calls(tree):
            out.hit(
                rel,
                lineno,
                f"a selector writes ({what}) — selectors.py never writes (reads/writes separate)",
            )
    for path in _py_files(root, "apps", named={"services.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("service_files")
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            returns = node.returns
            if returns is not None and "QuerySet" in ast.unparse(returns):
                out.hit(
                    rel,
                    node.lineno,
                    f"{node.name} returns a QuerySet from services.py — a display read is a "
                    "selector's",
                )
                continue
            for ret in ast.walk(node):
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Call):
                    f = ret.value.func
                    if isinstance(f, ast.Attribute) and f.attr in _QS_TAIL:
                        out.hit(
                            rel,
                            ret.lineno,
                            f"{node.name} returns a queryset chain (.{f.attr}(...)) — services "
                            "return objects; selectors return querysets",
                        )
                        break
    return out


# --- rule 13 (AST half): services are @service, keyword-only, authorized ------


def _decorator_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names = set()
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name):
            names.add(target.id)
        elif isinstance(target, ast.Attribute):
            names.add(target.attr)
    return names


def service_shape(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", named={"services.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        src = _read(path)
        out.count("service_files")
        rel = str(path.relative_to(root))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            out.count("functions_scanned")
            decorated = "service" in _decorator_names(node)
            segment = ast.get_source_segment(src, node) or ""
            writes = _write_calls(ast.parse(segment)) if segment else []
            public = not node.name.startswith("_")
            if public and writes and not decorated and not _exempt(rule, rel, node.name):
                out.hit(
                    rel,
                    node.lineno,
                    f"{node.name} writes ({writes[0][1]}) but is not @service — undecorated writes "
                    "skip the transaction, the span, the log lines and the audit row",
                )
            if decorated:
                positional = [a.arg for a in node.args.args + node.args.posonlyargs]
                if positional or node.args.vararg:
                    out.hit(
                        rel,
                        node.lineno,
                        f"{node.name} is @service with positional parameters "
                        f"({', '.join(positional) or '*args'}) — a service is "
                        "keyword-only: put a bare * before the first parameter",
                    )
                takes_actor = any(a.arg == "actor" for a in node.args.kwonlyargs)
                guarded = "require(" in segment or "# authz:" in segment
                if takes_actor and not guarded and not _exempt(rule, rel, node.name):
                    out.hit(
                        rel,
                        node.lineno,
                        f"{node.name} takes an actor but never calls authz.require and carries no "
                        "# authz: <reason> — resolving who is asking without asking whether "
                        "they may",
                    )
    return out


# --- rule 14: HTTP vocabulary never below the doors ---------------------------

_HTTP_NAMES = {"HttpError", "Http404", "HttpResponse", "JsonResponse", "HttpResponseRedirect"}
_BELOW_DOOR_FILES = {"services.py", "selectors.py", "models.py", "policies.py"}


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


# --- rule 16: naming grammar (event names) ------------------------------------

_EVENT_SHAPE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+$")
_IRREGULAR_PAST = {
    "sent",
    "won",
    "lost",
    "sold",
    "held",
    "kept",
    "left",
    "met",
    "paid",
    "made",
    "seen",
    "shown",
    "taken",
    "given",
    "done",
    "gone",
    "begun",
    "set",
    "put",
    "read",
    "run",
    "sprung",
    "spun",
    "torn",
    "worn",
    "written",
    "risen",
    "sunk",
    "found",
    "bound",
    "built",
    "spent",
    "brought",
    "bought",
    "caught",
    "taught",
    "thought",
    "understood",
    "withdrawn",
    "split",
}


def event_grammar(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for app in _app_dirs(root):
        events = app / "events.py"
        tree = _parse(events) if events.exists() else None
        if tree is None:
            continue
        rel = str(events.relative_to(root))
        for node in tree.body:
            value = None
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
            ):
                name, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name, value = node.target.id, node.value
            else:
                continue
            if not (
                name.isupper() and isinstance(value, ast.Constant) and isinstance(value.value, str)
            ):
                continue
            out.count("event_names")
            text = value.value
            if not _EVENT_SHAPE.match(text) or text.split(".")[0] != app.name:
                out.hit(
                    rel,
                    node.lineno,
                    f"event {text!r} does not follow <app>.<noun>.<past-verb> for app {app.name!r}",
                )
                continue
            verb = text.split(".")[-1]
            last = verb.split("_")[-1]
            if not (last.endswith("ed") or last in _IRREGULAR_PAST):
                out.hit(
                    rel,
                    node.lineno,
                    f"event {text!r} — the verb is not past tense; an event states that "
                    "something HAS happened",
                )
    return out


# --- rule 16, the rest of the grammar -----------------------------------
#
# One rule, seven classes. The events half above is where rule 16 started; the
# six below extend it to the grammar the skills already taught and nothing
# checked. Each class is a CLOSED question with its own population, its own
# floor, its own canary and its own ratchet — measured before it was enforced
# (`quality/naming-grammar-measurement.md` is that measurement, committed
# first). A class with a backlog records the count in `rules.yaml`; the number
# may shrink, never grow, and it never tightens by itself.
#
# What is deliberately NOT here: whether a compliant name is a *good* name. A
# service called `create_thing_and_email_someone` starts with a verb in the
# lexicon and passes. That is review's, and it is in `does_not_cover`.

# A singular noun that happens to end in `s`. Not a stemmer: an English
# pluraliser would be a dependency and a source of arguments, and the real
# population is small enough that the exceptions are nameable. `Analysis`,
# `Address`, `Status` — kept as negatives so the shape stays proven.
#
# `-os` is deliberately NOT here, and the negative corpus is why: `gizmos`,
# `photos` and `memos` are plurals, and `chaos` is the kind of noun no model is
# named after. A singular `-os` that ever does turn up earns an exemption with
# its reason, which is visible, rather than a silent hole in the ending list.
_SINGULAR_S_ENDINGS = ("ss", "us", "is")


def _looks_plural(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith("s") and not lowered.endswith(_SINGULAR_S_ENDINGS)


def _base_names(node: ast.ClassDef) -> list[str]:
    """The last segment of each base's dotted name — `models.Model` -> `Model`.

    A subscripted base (`ScopedManager["Connection"]`) resolves to the
    generic's own name, which is what tells a manager from a model.
    """
    out: list[str] = []
    for base in node.bases:
        cur: ast.expr = base
        while isinstance(cur, ast.Subscript):
            cur = cur.value
        parts: list[str] = []
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        if parts:
            out.append(parts[0])
    return out


def _scope_list(rule: dict, key: str) -> list[Any]:
    return list((rule.get("scope") or {}).get(key) or [])


def _model_files(root: Path) -> list[Path]:
    """Every module that defines models — the app `models.py` files, plus the
    two `core` modules that hold a model beside the machinery that uses it."""
    files = [app / "models.py" for app in _app_dirs(root)]
    files += [root / "apps/core/audit.py", root / "apps/core/idempotency.py"]
    return [f for f in files if f.exists()]


def _model_classes(root: Path) -> list[tuple[Path, ast.ClassDef]]:
    """Module-level classes that reach a Django model base transitively.

    Derived, never typed: a manager, a queryset, a custom field, a plain
    exception and a nested `Meta`/`TextChoices` are all excluded, because none
    of them reaches a base whose name ends in `Model`.
    """
    candidates: list[tuple[Path, ast.ClassDef]] = []
    for path in _model_files(root):
        tree = _parse(path)
        if tree is None:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.bases:
                candidates.append((path, node))
    resolved: set[str] = set()
    found: list[tuple[Path, ast.ClassDef]] = []
    changed = True
    while changed:
        changed = False
        for path, node in candidates:
            if node.name in resolved:
                continue
            bases = _base_names(node)
            if any(b.endswith("Model") for b in bases) or any(b in resolved for b in bases):
                resolved.add(node.name)
                found.append((path, node))
                changed = True
    return found


def _module_functions(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = _parse(path)
    if tree is None:
        return []
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _starts_with_verb(name: str, verbs: list[str]) -> bool:
    """Longest-prefix match, so a declared two-word verb (`dead_letter`) reads
    as the verb phrase it is rather than as the adjective it starts with."""
    for verb in verbs:
        if name == verb or name.startswith(verb + "_"):
            return True
    return False


def _field_assignments(
    node: ast.ClassDef,
) -> list[tuple[int, str, ast.expr]]:
    """(line, name, value) for every `x = ...` / `x: T = ...` in a class body."""
    out: list[tuple[int, str, ast.expr]] = []
    for stmt in node.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
            and stmt.value is not None
        ):
            out.append((stmt.lineno, stmt.targets[0].id, stmt.value))
        elif (
            isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
            and stmt.value is not None
        ):
            out.append((stmt.lineno, stmt.target.id, stmt.value))
    return out


def _call_name(value: ast.expr) -> str:
    """`models.BooleanField(...)` -> `BooleanField`; anything else -> ``."""
    if not isinstance(value, ast.Call):
        return ""
    called: ast.expr = value.func
    parts: list[str] = []
    while isinstance(called, ast.Attribute):
        parts.append(called.attr)
        called = called.value
    if isinstance(called, ast.Name):
        parts.append(called.id)
    return parts[0] if parts else ""


_SCHEMA_SUFFIXES = ("In", "Out", "Patch", "Filter", "Page")


def naming_grammar(root: Path, rule: dict) -> CheckResult:
    """Rule 16, whole: events, apps, models, services, selectors, schemas, booleans."""
    out = event_grammar(root, rule)
    for finding in out.findings:
        finding.klass = "events"

    # --- apps are plural ------------------------------------------------------
    app_exempt = {
        str(entry.get("app"))
        for entry in _scope_list(rule, "app_name_exemptions")
        if entry.get("app")
    }
    for app in _app_dirs(root):
        out.count("apps_named")
        if app.name in app_exempt:
            continue
        if not _looks_plural(app.name):
            out.hit(
                str((app / "apps.py").relative_to(root)),
                1,
                f"app {app.name!r} is not plural — an app is a collection of things "
                "(`orders`, not `order`); a singular name that is deliberate is an "
                "exemption with a reason in rules.yaml",
                klass="apps",
            )

    # --- models are singular, and their booleans are is_/has_ -----------------
    models = _model_classes(root)
    for path, node in models:
        rel = str(path.relative_to(root))
        out.count("model_names")
        if _looks_plural(node.name):
            out.hit(
                rel,
                node.lineno,
                f"model {node.name!r} is plural — a model names ONE row "
                "(`Order`, not `Orders`); the table is already the plural",
                klass="models",
            )
        for line, field_name, value in _field_assignments(node):
            if not _call_name(value).endswith("BooleanField"):
                continue
            out.count("boolean_fields")
            if not field_name.startswith(("is_", "has_")):
                out.hit(
                    rel,
                    line,
                    f"boolean {node.name}.{field_name} does not start with `is_` or "
                    "`has_` — a bare adjective reads as a noun at the call site "
                    f"(`{field_name}` -> `is_{field_name}`)",
                    klass="booleans",
                )

    # --- services are verbs ---------------------------------------------------
    verbs = sorted((str(v) for v in _scope_list(rule, "service_verbs")), key=len, reverse=True)
    for app in _app_dirs(root):
        path = app / "services.py"
        if not path.exists():
            continue
        for node in _module_functions(path):
            if node.name.startswith("_"):
                continue  # a private helper is the inside of a service, not a capability
            out.count("service_names")
            if not _starts_with_verb(node.name, verbs):
                out.hit(
                    str(path.relative_to(root)),
                    node.lineno,
                    f"service {node.name!r} does not begin with a declared verb — a service "
                    "is something somebody DOES; add the verb to `service_verbs` in "
                    "rules.yaml if the lexicon is what is wrong",
                    klass="services",
                )

    # --- selectors are get_ / list_ -------------------------------------------
    for app in _app_dirs(root):
        path = app / "selectors.py"
        if not path.exists():
            continue
        for node in _module_functions(path):
            if node.name.startswith("_"):
                continue
            out.count("selector_names")
            if not node.name.startswith(("get_", "list_")):
                out.hit(
                    str(path.relative_to(root)),
                    node.lineno,
                    f"selector {node.name!r} is neither `get_` nor `list_` — the whole value "
                    "of the pair is that a caller can guess the name without opening "
                    "the module",
                    klass="selectors",
                )

    # --- schemas end In/Out/Patch/Filter/Page ---------------------------------
    for app in _app_dirs(root):
        path = app / "schemas.py"
        if not path.exists():
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            out.count("schema_names")
            if not node.name.endswith(_SCHEMA_SUFFIXES):
                out.hit(
                    str(path.relative_to(root)),
                    node.lineno,
                    f"schema {node.name!r} does not end in one of "
                    f"{'/'.join(_SCHEMA_SUFFIXES)} — the suffix is what says which "
                    "direction a shape travels",
                    klass="schemas",
                )
    return out


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
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
            and node.value is not None
        ):
            values.append(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == name
            and node.value is not None
        ):
            values.append(node.value)
    return values


def _starter_id_pin(root: Path, out: CheckResult) -> None:
    """The pin on rule 18's own excluded zone (P1-R0 F4).

    `workflow_ids` skips `apps/workflows/` because that module *defines* the
    starters — and an exclusion is a promise about what lives inside it. The
    promise here is exact and mechanical: **both starters declare `id` with no
    default**, so the `f"{type}-{uuid4()}"` default W1 deleted cannot quietly
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
                    "which is the idempotency hole W1 closed. `id: str`, required.",
                )


def workflow_ids(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    _starter_id_pin(root, out)
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
        # until P1-R0 F4 it was rule 18's cheapest evasion: three characters
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
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else (func.id if isinstance(func, ast.Name) else "")
            )
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
                callee = (
                    f.attr
                    if isinstance(f, ast.Attribute)
                    else (f.id if isinstance(f, ast.Name) else "")
                )
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


# --- rule 28: every workflow closes its run row (or declares it owns none) -----
#
# ADR workflows-5. The defect this holds closed was not a subtle one: the
# platform app's own SendEmailWorkflow and MoveOrganizationWorkflow never
# marked their `WorkflowRun` finished, so every row they wrote said RUNNING
# for ever, and EchoWorkflow marked itself *completed before doing anything*.
# W1 fixed all three. A rule is what stops the 15th builder's first workflow
# from reopening it, because the wrong shape costs nothing at write time and
# only lies later, to a reader who has no way to know.
#
# THE CLOSED QUESTION, and it has to cover two seams that are both correct:
#
# apps/workflows/workflows.py result, slug = await _finish(work)
# the four domain apps await self._finish(status=..., error=...)
#
# One is a module-level wrapper taking the work as a callable; the other is a
# method on the class. Asking "does it call `mark_run_finished`" would miss
# both (they invoke the activity BY NAME, one level down, which house rule 9
# requires). Asking for one exact call shape would force four apps to rewrite
# a seam that is already right. So the question is: **does the `@workflow.run`
# method reference a name ending `_finish`, or name the finish activity, or
# does the class declare `owns_no_run = True`.**
#
# The declaration half is not a loophole, it is the other real population: a
# workflow started by a Temporal SCHEDULE has no `WorkflowRun` row, because no
# service asked for it and nobody is waiting on a visibility row for the
# deployment's own housekeeping. `owns_no_run = True` says that out loud, on
# the class, where a reviewer meets it.
_FINISH_SUFFIX = "_finish"
_FINISH_ACTIVITY = "mark_run_finished"
_OWNS_NO_RUN_ATTR = "owns_no_run"
_WORKFLOWS_LIST = "WORKFLOWS"
_RUN_DECORATOR = "run"


def _declared_workflow_names(tree: ast.Module) -> set[str]:
    """The class names in this module's `WORKFLOWS` list(s) — the population.

    Read off the list `config.temporal` actually discovers, not off "every
    class with @workflow.defn": the list is what gets registered on the worker,
    so it is what can run, so it is what must close its rows.
    """
    names: set[str] = set()
    for value in _assigned_values(tree, _WORKFLOWS_LIST):
        if isinstance(value, (ast.List, ast.Tuple)):
            names |= {e.id for e in value.elts if isinstance(e, ast.Name)}
    return names


def _run_method(node: ast.ClassDef) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for stmt in node.body:
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in stmt.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute) and target.attr == _RUN_DECORATOR:
                return stmt
    return None


def _references_finish_seam(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id.endswith(_FINISH_SUFFIX):
            return True
        if isinstance(node, ast.Attribute) and node.attr.endswith(_FINISH_SUFFIX):
            return True
        if isinstance(node, ast.Constant) and node.value == _FINISH_ACTIVITY:
            return True
    return False


def workflows_close_runs(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for app in _app_dirs(root):
        wf = app / "workflows.py"
        tree = _parse(wf) if wf.exists() else None
        if tree is None:
            continue
        rel = wf.relative_to(root).as_posix()
        population = _declared_workflow_names(tree)
        if not population:
            continue
        out.count("workflow_modules")
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name not in population:
                continue
            out.count("workflow_classes")
            if _class_attribute_is_true(node, _OWNS_NO_RUN_ATTR):
                out.count("declared_no_run")
                continue
            run = _run_method(node)
            if run is None:
                out.hit(
                    rel,
                    node.lineno,
                    f"{node.name} is registered in WORKFLOWS with no @workflow.run method — "
                    "a class the worker will register and can never execute",
                    klass="workflows",
                )
                continue
            if _references_finish_seam(run):
                continue
            out.hit(
                rel,
                node.lineno,
                f"{node.name}.run() never reaches the finish seam — a WorkflowRun row was "
                "written when this was started and nothing here closes it, so it says RUNNING "
                f"for ever. Call the app's `_finish` seam LAST, or declare "
                f"`{_OWNS_NO_RUN_ATTR} = True` on the class if it is schedule-started and owns "
                "no row (ADR workflows-5).",
                klass="workflows",
            )
    return out


# --- rule 29: a role is never granted above the granter -----------------------
#
# , the class-closure. fixed the two concrete paths
# (`create_sso_connection`, `update_sso_connection`); this is what stops the
# next one being written. The defect it holds closed is the worst kind of quiet:
# a service takes `role=` from a door, writes it onto a `Membership`, and an
# admin who could pass `"owner"` becomes an owner — with a clean audit row
# saying they did it on purpose.
#
# THE CLOSED QUESTION: a `@service` whose signature carries a ROLE-SHAPED
# parameter, and whose body puts that parameter into a ROLE POSITION, must show
# a bound against the actor in the same body.
#
# role-shaped name is `role`, `default_role`, or ends `_role`
# role position a `role=`/`*_role=` keyword on any call, or an assignment to
# a `.role`/`.*_role` attribute
# a bound a call to the escalation wall — `_refuse_escalation`, or
# `_refuse_role_above_the_configurer`, which wraps it
#
# The bound is looked for as a CALL to the wall, not as `authz.require`, and
# that is the whole shape of the decision: `require` asks "may this actor act on
# this object"; a grant also has a *role being granted*, and the refusal is
# about the relationship between that role and the granter's own effective role.
# There is no object a policy predicate could inspect that carries it.
#
# The valve is `# role-bound: <reason>`, read with the same grammar as
# `# reach:` and counted the same way, because the honest exceptions are real: a
# path where nobody is granting (an IdP asserted an identity) has no granter to
# measure, and the ceiling lives where a person actually acted.
_ROLE_PARAM = re.compile(r"^(role|default_role|.*_role)$")
_ROLE_WALL = {"_refuse_escalation", "_refuse_role_above_the_configurer"}
# A ROLE POSITION IS A MODEL WRITE. Three things can be one: a model
# constructor keyword (`Membership(role=...)`), a queryset write keyword
# (`.create(role=...)`, `.update(role=...)`), or an attribute assignment
# (`.role = role`). A `role=` handed to another FUNCTION is none of them — the
# row is written there, and there is where the bound belongs.
#
# That distinction is the whole reason `accounts.services.ensure_membership`
# needs no exemption. It forwards `role` to `add_membership`, which is itself a
# @service in this population and is bounded on every path — including this one,
# where the wall correctly short-circuits because no actor is granting (an IdP
# asserted an identity). Judging the forwarder would have demanded an exemption
# with the reason parked in rules.yaml, away from the code; judging the writer
# puts the bound where the row is.
#
# The residual — a role forwarded to a non-@service helper that writes the row —
# is covered one layer down rather than here: rule 13 requires every write in a
# services.py to be a @service, and rule 10 keeps writes out of the doors. It is
# declared on the rule regardless.
_ROLE_WRITE_CALLS = {
    "create",
    "get_or_create",
    "update_or_create",
    "update",
    "bulk_create",
    "bulk_update",
}
# `role=` on a READ narrows a query; it grants nothing, and counting it would
# make every service that so much as filters by role a finding — a rule
# ratcheted into noise is a rule nobody reads. Found by writing the negative
# (`role_never_written.py`), which is what negatives are for.
_ROLE_READ_CALLS = {
    "filter",
    "exclude",
    "get",
    "count",
    "exists",
    "values",
    "values_list",
    "annotate",
    "aggregate",
    "order_by",
    "only",
    "defer",
    "first",
    "last",
    "all",
}
_ROLE_BOUND_RE = re.compile(r"#\s*role-bound\b:?\s*(.*)$")
_MIN_ROLE_REASON = 12


def _role_bound_reason(lines: list[str], line: int) -> str | None:
    """The reason a `# role-bound:` marker claims at this line, or None."""
    if not lines or line < 1 or line > len(lines):
        return None
    m = _ROLE_BOUND_RE.search(lines[line - 1])
    if m:
        return m.group(1).strip()
    i = line - 2
    while i >= 0 and lines[i].strip().startswith("#"):
        m = _ROLE_BOUND_RE.search(lines[i])
        if m:
            return m.group(1).strip()
        i -= 1
    return None


def _role_positions(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, params: set[str]
) -> list[tuple[int, str]]:
    """(line, description) everywhere a role-shaped PARAMETER lands in a role position."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            callee = _call_name(node)
            # A model CONSTRUCTOR is capitalised (`Membership(...)`); a queryset
            # write is one of the write verbs. Everything else — the wall
            # itself, a read verb, a call to another service — is not a place a
            # row is written, so it is not a role position.
            constructor = bool(callee[:1].isupper())
            if not constructor and callee not in _ROLE_WRITE_CALLS:
                continue
            for kw in node.keywords:
                if (
                    kw.arg
                    and _ROLE_PARAM.match(kw.arg)
                    and isinstance(kw.value, ast.Name)
                    and kw.value.id in params
                ):
                    found.append((node.lineno, f"{callee or 'a call'}({kw.arg}=)"))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and _ROLE_PARAM.match(target.attr)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in params
                ):
                    found.append((node.lineno, f".{target.attr} ="))
    return found


def role_bound_assignment(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    # LEX-1 gap 4, cosmetic: these were ONE counter, so a scope exemption (a
    # judgement parked in rules.yaml, away from the code) and a `# role-bound:`
    # comment (a judgement written where the grant is) added up to a single
    # number nobody could read back. Both start at 0 so both always print —
    # which is what makes the rule's "NO EXEMPTIONS" claim visible rather than
    # merely written down.
    out.targets_matched["role_bound_exemptions"] = 0
    out.targets_matched["role_bound_comments"] = 0
    for path in sorted(root.glob("apps/*/services.py")):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        app = rel.split("/")[1]
        lines = _read(path).splitlines()
        out.count("services_files")
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "service" not in _decorator_names(node):
                continue
            args = [a for a in _all_args(node) if _ROLE_PARAM.match(a.arg)]
            if not args:
                continue
            out.count("role_param_services")
            params = {a.arg for a in args}
            positions = _role_positions(node, params)
            if not positions:
                # A role-named parameter that never reaches a role position is
                # not this rule's subject, and reading it as one would make
                # every read-only lookup taking `role=` a finding.
                continue
            out.count("role_writing_services")
            if _ROLE_WALL & {_call_name(c) for c in ast.walk(node) if isinstance(c, ast.Call)}:
                out.count("role_bounds")
                continue
            if _exempt(rule, rel, node.name):
                out.count("role_bound_exemptions")
                continue
            whole = _role_bound_reason(lines, node.lineno)
            reason = next(
                (r for r in (_role_bound_reason(lines, a.lineno) for a in args) if r is not None),
                whole,
            )
            line, where = positions[0]
            if reason is not None:
                if len(reason) >= _MIN_ROLE_REASON:
                    out.count("role_bound_comments")
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"`# role-bound:` with no reason on {node.name}("
                    f"{'/'.join(sorted(params))}=) — an escape hatch nobody has to justify is "
                    "an off switch; write the sentence a reviewer can disagree with",
                    klass=app,
                )
                continue
            out.hit(
                rel,
                line,
                f"{node.name} puts {'/'.join(sorted(params))} into a role position "
                f"({where}) with no bound against the actor — an admin who may pass "
                "'owner' becomes an owner, and the audit row says they meant to. Call the "
                "escalation wall (_refuse_escalation / _refuse_role_above_the_configurer), "
                "or record `# role-bound: <reason>`",
                klass=app,
            )
    return out


# --- rule 30: a retry clock that nothing reads is a promise nobody keeps -------
#
# P1-R1's HIGH, generalised (ADR events-3). `emit()` wrote
# `Outbox.next_attempt_at`, indexed it over `(status, next_attempt_at)`,
# documented it in three modules — and NOTHING in production ever queried it. A
# row whose dispatch died held a promise for ever, with a management command
# nobody had a reason to run as the only recovery. The column was not broken; it
# was unread, and unread looks exactly like working.
#
# THE CLOSED QUESTION over a name-shaped population: a `DateTimeField` whose
# name matches the retry-clock grammar must be READ by production code outside
# its own declaring module and outside tests.
#
# A READ is a query, and the distinction is the entire rule. On this tree the
# field is *mentioned* in eleven places that are not reads: two writes in
# services.py, and prose in activities.py and workflows.py. A grep-shaped rule
# would have been green through the whole period the column had no reader —
# which is the period the review found.
_CLOCK_FIELD = re.compile(r"^(next_attempt_at|.*_retry_at|retry_after_.*)$")
# The queryset verbs whose STRING arguments name fields.
_FIELD_STRING_CALLS = {"order_by", "only", "values", "values_list", "defer", "F", "distinct"}
# LEX-1: the verbs whose KEYWORD arguments name a field being READ. The first
# draft matched a `field=`/`field__` keyword on ANY call, which is the rule's own
# defect wearing the rule's pass: `Outbox.objects.filter(...).update(
# next_attempt_at=None)` clears the clock and `Outbox(next_attempt_at=when)` sets
# it, and each counted as its own reader. A product that closed its clock from a
# second module therefore SILENCED rule 30 with a write — the exact state
# (written everywhere, queried nowhere) the rule was written to find.
#
# ENUMERATED FROM WHAT THIS TREE ACTUALLY USES, counted over apps/ minus
# migrations: `filter` (259 keyword callsites), `get` (207), `Q` (19),
# `exclude` (4), `get_or_create` (1). `When`, `annotate` and `aggregate` are in
# the set with zero callsites today, and deliberately: they are the ordinary
# next spellings of a lookup, and a rule that fired on the first `annotate` a
# product wrote would be accusing a field that IS read. `update_or_create` is in
# for the same reason and on the same terms as `get_or_create`.
#
# `get_or_create`/`update_or_create` are the LOOKUP HALF only, and that falls out
# of the shape rather than needing an exclusion: the lookup is keywords on the
# call, while the write half lives inside `defaults={...}` as dict KEYS, which
# are not keyword arguments and are never matched here.
#
# Writes are absent by construction — `update`, `bulk_update`, `create` and a
# model constructor are none of them read verbs, so none of them can answer for
# a clock. `order_by`/`values`/`F` and the rest name fields as STRINGS and are
# handled by _FIELD_STRING_CALLS above.
_READ_KWARG_CALLS = {
    "filter",
    "exclude",
    "get",
    "get_or_create",
    "update_or_create",
    "Q",
    "When",
    "annotate",
    "aggregate",
}


def _reads_field(tree: ast.Module, field: str) -> list[int]:
    """Lines where this module QUERIES `field` — never merely mentions it."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _call_name(node)
        # filter(next_attempt_at__lt=...) / exclude(next_attempt_at=None) — and
        # ONLY on a read verb: .update(next_attempt_at=None) is a write.
        if callee in _READ_KWARG_CALLS:
            for kw in node.keywords:
                if kw.arg and (kw.arg == field or kw.arg.startswith(f"{field}__")):
                    lines.append(node.lineno)
        # order_by("next_attempt_at"), order_by("-next_attempt_at"), F("...")
        if callee in _FIELD_STRING_CALLS:
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value.lstrip("-+") == field
                ):
                    lines.append(node.lineno)
    return sorted(set(lines))


def retry_clock_readers(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path, node in _model_classes(root):
        rel = path.relative_to(root).as_posix()
        for line, name, value in _field_assignments(node):
            if not _CLOCK_FIELD.match(name) or "DateTimeField" not in _call_name(value):
                continue
            out.count("retry_clocks")
            readers: list[str] = []
            for other in _py_files(root, "apps"):
                orel = other.relative_to(root).as_posix()
                if orel == rel or "/tests/" in orel or "/migrations/" in orel:
                    continue
                otree = _parse(other)
                if otree is None:
                    continue
                readers += [f"{orel}:{n}" for n in _reads_field(otree, name)]
            if readers:
                out.count("clocks_with_readers")
                continue
            out.hit(
                rel,
                line,
                f"{node.name}.{name} is a retry clock that production code writes and "
                "NOTHING reads — no filter, no order_by, anywhere outside this module and "
                "the tests. A row whose work died holds its promise for ever and nothing "
                "will ever notice. Give the clock its reader — a selector, and a schedule "
                "that runs it (ADR events-3)",
                klass="clocks",
            )
    return out


# --- rule 37: no scoped model orders the whole deployment by time --------------
#
# ADR core-11 / . `BaseModel` shipped `created_at` with `db_index=True`
# behind `ordering = ["-created_at"]`, so every concrete model in the tree
# inherited an index over the WHOLE DEPLOYMENT's timeline while every supported
# read is tenant-scoped. A paginated page walked backwards down that index and
# threw away other tenants' entries one at a time (F1a measured 102,300 foreign
# rows examined per page; F1b measured 255,000 on `AuditEntry`). The fix is the
# `(tenant, -created_at)` composite declared once in `TenantScopedModel.Meta`.
#
# WHY A RULE AND NOT JUST THE FIX. Django does NOT merge `Meta.indexes` down an
# inheritance chain: a concrete model that declares its own `indexes` list
# SHADOWS the abstract one and silently loses the composite. That hole is
# invisible in review — the model looks like it has indexes — and it is one
# line wide. The same census refuses the next hand-written tenant-blind index
# and the next `DateTimeField(db_index=True)`, which is the disease's original
# spelling and the shape a product's builder reaches for first.
#
# THE POPULATION IS DERIVED, NEVER TYPED — every concrete class that reaches
# `TenantScopedModel`, off the same AST walk rules 8, 24 and 38 use. A hand
# list here would be the misses ledger's hand-list-goes-stale class (cycle-0
# #8): `exports.Export` landed between this rule's design and its build and was
# in scope the moment it existed, with no edit to this file.
#
# THE RULE READS DECLARATIONS AND NEVER PLANS. Whether the planner actually
# picks the composite is rule 35's job and the perf harness's.

_DATE_FIELDS = {"DateTimeField", "DateField"}
_RECENCY_COLUMN = "created_at"


def _nested_class(node: ast.ClassDef, name: str) -> ast.ClassDef | None:
    for stmt in node.body:
        if isinstance(stmt, ast.ClassDef) and stmt.name == name:
            return stmt
    return None


def _meta_parent(meta: ast.ClassDef) -> str | None:
    """`class Meta(TenantScopedModel.Meta)` -> `TenantScopedModel`.

    Django's Meta inheritance is plain Python class inheritance of the inner
    class, so this is the whole of the resolution rule.
    """
    for base in meta.bases:
        if isinstance(base, ast.Attribute) and base.attr == "Meta":
            if isinstance(base.value, ast.Name):
                return base.value.id
    return None


def _model_index_of(root: Path) -> dict[str, tuple[Path, ast.ClassDef]]:
    return {node.name: (path, node) for path, node in _model_classes(root)}


def _meta_attribute(
    index: dict[str, tuple[Path, ast.ClassDef]], model: str, attr: str
) -> ast.expr | None:
    """The value of `Meta.<attr>` as Python attribute lookup would find it.

    The FIRST `Meta` in the chain that declares the name wins — which is
    exactly why a concrete model's own `indexes` shadows the abstract base's,
    and why this rule exists.
    """
    seen: set[str] = set()
    name: str | None = model
    while name is not None and name not in seen:
        seen.add(name)
        entry = index.get(name)
        if entry is None:
            return None
        meta = _nested_class(entry[1], "Meta")
        if meta is None:
            return None
        for _line, declared, value in _field_assignments(meta):
            if declared == attr:
                return value
        name = _meta_parent(meta)
    return None


def _is_abstract(index: dict[str, tuple[Path, ast.ClassDef]], model: str) -> bool:
    entry = index.get(model)
    if entry is None:
        return False
    meta = _nested_class(entry[1], "Meta")
    if meta is None:
        return False
    for _line, declared, value in _field_assignments(meta):
        if declared == "abstract" and isinstance(value, ast.Constant) and value.value is True:
            return True
    return False


def _date_fields_of(
    index: dict[str, tuple[Path, ast.ClassDef]], model: str
) -> dict[str, tuple[int, bool]]:
    """`{field name: (line, db_index)}` for every date field the model has, its
    INHERITED ones included — `BaseModel.created_at` is the whole point, since
    that one line is what put a blind index on every table in the tree."""
    found: dict[str, tuple[int, bool]] = {}
    stack = [model]
    seen: set[str] = set()
    while stack:
        name = stack.pop(0)
        if name in seen:
            continue
        seen.add(name)
        entry = index.get(name)
        if entry is None:
            continue
        for line, field_name, value in _field_assignments(entry[1]):
            if _call_name(value) not in _DATE_FIELDS or not isinstance(value, ast.Call):
                continue
            indexed = any(
                kw.arg == "db_index" and isinstance(kw.value, ast.Constant) and kw.value.value
                for kw in value.keywords
            )
            # A subclass redeclaring the field wins over its base's: the walk is
            # breadth-first from the model itself, so the first write stands.
            found.setdefault(field_name, (line, indexed))
        stack.extend(_base_names(entry[1]))
    return found


def _string_list(value: ast.expr | None) -> list[str] | None:
    if not isinstance(value, ast.List):
        return None
    out: list[str] = []
    for element in value.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        out.append(element.value)
    return out


def _declared_indexes(value: ast.expr | None) -> list[tuple[int, list[str] | None, bool]]:
    """`(line, fields — None for an expression index, whether it has a condition)`."""
    if not isinstance(value, ast.List):
        return []
    out: list[tuple[int, list[str] | None, bool]] = []
    for element in value.elts:
        if not isinstance(element, ast.Call) or _call_name(element) != "Index":
            continue
        fields: list[str] | None = None
        conditional = False
        for kw in element.keywords:
            if kw.arg == "fields":
                fields = _string_list(kw.value)
            elif kw.arg == "condition":
                conditional = True
        out.append((element.lineno, fields, conditional))
    return out


def _leads_on(columns: list[str], column: str) -> bool:
    return bool(columns) and columns[0].lstrip("-") == column


def _is_the_composite(columns: list[str]) -> bool:
    """First two columns `(tenant, created_at)`, in either direction.

    The census asserts LEADING COLUMNS and never a spelling: coverage is the
    guarantee, and a product that names its own composite something else is
    still covered.
    """
    return (
        len(columns) >= 2
        and columns[0].lstrip("-") == "tenant"
        and columns[1].lstrip("-") == _RECENCY_COLUMN
    )


def tenant_blind_index_census(root: Path, rule: dict) -> CheckResult:
    """Rule 37: three edges over one discovered population."""
    out = CheckResult()
    index = _model_index_of(root)
    scoped = {name for name in scoped_model_names(root) if not _is_abstract(index, name)}

    for model in sorted(scoped):
        entry = index.get(model)
        if entry is None:
            continue
        path, node = entry
        rel = path.relative_to(root).as_posix()
        out.count("scoped_models_censused")

        ordering = _string_list(_meta_attribute(index, model, "ordering")) or []
        declared = _declared_indexes(_meta_attribute(index, model, "indexes"))
        dates = _date_fields_of(index, model)

        # --- edge 1: COVERAGE -------------------------------------------------
        if _leads_on(ordering, _RECENCY_COLUMN):
            out.count("recency_ordered_models")
            if any(fields is not None and _is_the_composite(fields) for _l, fields, _c in declared):
                out.count("composites_found")
            elif _exempt(rule, rel, model):
                out.count("coverage_waivers")
            else:
                out.hit(
                    rel,
                    node.lineno,
                    f"{model} orders by `{ordering[0]}` and carries no index leading on "
                    "(tenant, created_at). Every page of its default list walks the whole "
                    "DEPLOYMENT's timeline and discards other tenants' rows one at a time "
                    "(F1a: 102,300 foreign rows examined per page). "
                    "`TenantScopedModel.Meta` declares that composite for you — but Django "
                    "does not merge `Meta.indexes` down an inheritance chain, so this "
                    "model's own `indexes` list SHADOWS it. Re-add "
                    '`models.Index(fields=["tenant", "-created_at"], name="'
                    f'{model.lower()}_recency")` to that list (rule 37, ADR core-11)',
                    klass="coverage",
                )

        # --- edge 2: NO BLIND INDEX -------------------------------------------
        for line, fields, conditional in declared:
            if fields is None:
                # `models.Index(expressions=...)` has no leading fields list.
                out.count("expression_indexes_unseen")
                continue
            if not fields or fields[0].lstrip("-") not in dates:
                continue
            if conditional:
                # The `AuditEntry` platform-partial shape (ADR core-8): index
                # the population the read is over, never the whole table.
                out.count("platform_partial_indexes")
                continue
            if _exempt(rule, rel, f"{model}.index@{fields[0].lstrip('-')}"):
                out.count("blind_index_waivers")
                continue
            out.hit(
                rel,
                line,
                f"{model} declares an index leading on the time column "
                f"`{fields[0].lstrip('-')}` with no `condition` — a tenant-blind index over "
                "the whole deployment, the exact shape ADR core-11 removed. Lead with "
                "`tenant`, or carry a `condition` that excludes tenant rows (the "
                "`AuditEntry` platform-partial shape), or exempt it in rules.yaml with the "
                "reason (rule 37)",
                klass="no_blind_time_index",
            )

        # --- edge 3: NO BLIND FIELD INDEX -------------------------------------
        for field_name, (line, indexed) in sorted(dates.items()):
            if not indexed:
                continue
            if _exempt(rule, rel, f"{model}.{field_name}"):
                out.count("blind_field_waivers")
                continue
            out.hit(
                rel,
                line,
                f"{model}.{field_name} is a date field with `db_index=True` — the original "
                "disease's exact spelling (ADR core-11). A bare index on a time column of a "
                "SCOPED model orders the whole deployment, and every read of this table is "
                "tenant-scoped. Drop the flag and lead a composite with `tenant`, or exempt "
                "it in rules.yaml naming the cross-tenant reader that wants it (rule 37)",
                klass="no_blind_field_index",
            )

    return out


# --- rule 15's secret-at-rest clause ------------------------------------------
#
# P1-R1's plaintext-credential class, closed by W6a for the one field that had
# it. `WebhookEndpoint.secret` was a plain `CharField` in a tree where every
# sibling credential was already encrypted — the outbound signing secret sat in
# the clear beside `Connection.credentials` (EncryptedJSONField) and
# `SsoConnection.metadata` (the same). One field being wrong while its
# neighbours are right is what a rule is for: nobody decided it, it was just
# never noticed.
#
# THE POPULATION IS NAME-SHAPED, and the grammar is written out rather than
# gestured at, because a name set nobody can read is a name set nobody can argue
# with. `credentials` is in it deliberately: without it,
# `Connection.credentials` would be silent because the rule never LOOKED, and a
# negative that passes for the wrong reason is decoration.
_SECRET_FIELD = re.compile(
    r"^(secret|token|password|credentials|signing_key|api_key|private_key"
    r"|access_token|refresh_token|client_secret"
    r"|.*_secret|.*_token|.*_password|.*_credentials|.*_signing_key|.*_api_key"
    r"|.*_private_key)$"
)
# A digest is not a recoverable secret. Encrypting one would protect nothing and
# would break the unique lookup that authenticates every request — `key_hash`
# and `token_hash` are the tree's two, and both are right as they are. Excluded
# by construction rather than by two allow-list entries that would breed.
_DIGEST_FIELD = re.compile(r"_hash$")
# A secret-shaped name on a RELATION points at a row; it holds nothing.
_RELATION_FIELDS = ("ForeignKey", "OneToOneField", "ManyToManyField")


def secret_at_rest(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path, node in _model_classes(root):
        rel = path.relative_to(root).as_posix()
        for line, name, value in _field_assignments(node):
            call = _call_name(value)
            if not call.endswith("Field"):
                continue
            out.count("model_fields")
            short = call.rsplit(".", 1)[-1]
            if short in _RELATION_FIELDS:
                continue
            if _DIGEST_FIELD.search(name) or not _SECRET_FIELD.match(name):
                continue
            out.count("secret_fields")
            if "Encrypted" in short:
                out.count("encrypted_secrets")
                continue
            if _exempt(rule, rel, f"{node.name}.{name}"):
                out.count("secret_waivers")
                continue
            out.hit(
                rel,
                line,
                f"{node.name}.{name} is a {short} — a secret-shaped field in the clear. "
                "Every sibling credential in this tree is encrypted at rest "
                "(core.fields.EncryptedCharField / EncryptedJSONField); a database dump, a "
                "replica, a backup and a traceback are four ways a plaintext one leaves. "
                "Use an encrypted field type, or allow-list it in rules.yaml with the "
                "reason (rule 15, P1-R1)",
                klass="secrets",
            )
    return out


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


# --- rule 20 (enforceable half): declared-append-only models are never rewritten --
#
# ADR core-6. This rule used to hard-code the name `AuditEntry`, which is the
# shape that does not survive a product: a witnessed fact, an accrual and a
# stage-transition log make the same promise and none of them is called
# AuditEntry. The population is now DISCOVERED — every model that declared
# `append_only = True` (`core.models.APPEND_ONLY_ATTR`, and
# `core.models.append_only_models()` is the same question asked of the live
# registry). A product adds a member by declaring it, and this rule covers it
# in the same commit with no edit to rules.yaml.

_APPEND_ONLY_ATTR = "append_only"


def _class_attribute_is_true(node: ast.ClassDef, attr: str) -> bool:
    """Whether this class body assigns `attr = True` (annotated or not)."""
    for stmt in node.body:
        target: str | None = None
        value: ast.expr | None = None
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target, value = stmt.target.id, stmt.value
        elif (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            target, value = stmt.targets[0].id, stmt.value
        if target != attr:
            continue
        if isinstance(value, ast.Constant) and value.value is True:
            return True
    return False


def append_only_model_names(root: Path) -> dict[str, str]:
    """{model name: the module that declares it} for every declared append-only model.

    Derived from the tree on every run. The declaring module is remembered
    because that is the one place a member's own rows are reviewed — `AuditEntry`
    lives in `apps/core/audit.py`, and the archival job a product one day writes
    belongs there too, where this rule can see it was read.
    """
    found: dict[str, str] = {}
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _class_attribute_is_true(node, _APPEND_ONLY_ATTR):
                found[node.name] = path.relative_to(root).as_posix()
    return found


# : The queryset-level rewrites. A manager or queryset expression is the
# : receiver, so the model's name is IN the receiver and the word-bounded match
# : below finds it.
_QUERYSET_REWRITES = ("delete", "update", "bulk_update")

# : The INSTANCE-level rewrites, and the whole of LF-Q's static tightening.
# : `entry.save()` on a row that was READ back and `entry.delete()` on any row of
# : an append-only model are the same forbidden act as
# : `AuditEntry.objects.update(...)`, and until they were invisible:
# : the receiver is a local name and the model's name is nowhere in it. The
# : runtime belt (`BaseModel.save`/`.delete`, ADR core-14, LF1-2) raises
# : `AppendOnlyViolation` on exactly this path — this half is its PAIR, not its
# : replacement, and the two catch different things: the belt sees every instance
# : whatever its name, at the cost of needing the line to run; this sees the line
# : without running it, at the cost of needing the binding to be legible.
# :
# : THE ASYMMETRY IS THE BELT'S, COPIED EXACTLY. `save()` refuses only when
# : `_state.adding` is False, because the ONE legitimate write an append-only
# : model ever does is its create — `entry = WidgetEntry(...)` then
# : `entry.save()`, which is `apps/example/services.py::_append_entry` and is the
# : worked example of a correct ledger append. `delete()` refuses always. A
# : static half that fired on both would accuse the one shape the rule exists to
# : permit, which is how a rule earns an override at its own worked example.
_INSTANCE_REWRITE_ALWAYS = ("delete",)
_INSTANCE_REWRITE_IF_READ_BACK = ("save",)

# : The two ways a name comes to hold a row, and the reason they are told apart.
_BOUND_CONSTRUCTED = "constructed"
_BOUND_READ_BACK = "read back"


def _names_bound_to(tree: ast.Module, model: str) -> dict[str, str]:
    """{local name: how it was bound} for names bound to an expression NAMING `model`.

    Three bindings, and they are the three a person writes:

        entry = AuditEntry.objects.get(...) # read back
        for entry in AuditEntry.objects.all(): # read back, per row
        entry = AuditEntry(...) # constructed, not yet a row

    Word-bounded for its reason, applied one layer further out than it was:
    `draft = AuditEntryDraft.objects.get(...)` binds `draft` to a DIFFERENT
    model whose name merely begins with a member's, and a substring match here
    would accuse `draft.save()` — the same bystander, one indirection along.

    A bare call ON THE MODEL CLASS is `constructed`: that row does not exist yet
    and saving it is the create the rule permits. Anything else that names the
    model is `read back`, including `Model.objects.create(...)` — a row that
    round-tripped is a witnessed row, and `.save()` on it is a rewrite. Where a
    name is bound both ways, `read back` wins: the louder reading of an
    ambiguous module is the safe one.

    A name bound in one function and rewritten in another is still caught, and
    that is deliberate over-reach in the same direction. The declared blind spot
    is the other one — a binding this cannot see (a function parameter, a dict
    value, a comprehension target) leaves the rewrite invisible, which is
    precisely what the runtime belt is for.
    """
    pattern = re.compile(rf"\b{re.escape(model)}\b")
    bound: dict[str, str] = {}

    def _is_construction(value: ast.expr) -> bool:
        if not isinstance(value, ast.Call):
            return False
        func = value.func
        if isinstance(func, ast.Name):
            return func.id == model
        if isinstance(func, ast.Attribute):
            return func.attr == model
        return False

    def _record(target: ast.expr, value: ast.expr, *, constructed_ok: bool = True) -> None:
        if not isinstance(target, ast.Name):
            return
        if not pattern.search(ast.unparse(value)):
            return
        how = _BOUND_CONSTRUCTED if constructed_ok and _is_construction(value) else _BOUND_READ_BACK
        if bound.get(target.id) == _BOUND_READ_BACK:
            return
        bound[target.id] = how

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and node.value is not None:
            for target in node.targets:
                _record(target, node.value)
        elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
            _record(node.target, node.value)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            # Iterating a construction is not a thing; every loop variable that
            # names the model holds a row that came back.
            _record(node.target, node.iter, constructed_ok=False)
    return bound


def append_only_writes(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    declared = append_only_model_names(root)
    out.targets_matched["append_only_models"] = len(declared)
    for path in _py_files(root, "apps", "config"):
        rel = path.relative_to(root).as_posix()
        text = _read(path)
        subjects = {name for name, home in declared.items() if home != rel and name in text}
        if not subjects:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        # : local name -> (the member it was bound to, how). Built once per module.
        bound: dict[str, tuple[str, str]] = {}
        for name in sorted(subjects):
            for local, how in _names_bound_to(tree, name).items():
                if bound.get(local, ("", ""))[1] != _BOUND_READ_BACK:
                    bound[local] = (name, how)
        out.count("bound_names", len(bound))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            receiver = ast.unparse(node.func.value)
            if node.func.attr in _QUERYSET_REWRITES:
                for name in sorted(subjects):
                    # WORD-BOUNDED, not substring . `AuditEntryDraft` is a
                    # different model that merely starts with a member's name, and
                    # a substring match made every write to it a finding with an
                    # override as the only exit — the rule accusing a bystander.
                    if re.search(rf"\b{re.escape(name)}\b", receiver):
                        out.hit(
                            rel,
                            node.lineno,
                            f"{name}.{node.func.attr}(...) — {name} declared itself "
                            "append-only (core.models.append_only); a service may create a "
                            "row and no code path anywhere may update or delete one",
                        )
                        break
                continue
            if receiver not in bound:
                continue
            model, how = bound[receiver]
            if node.func.attr in _INSTANCE_REWRITE_ALWAYS or (
                node.func.attr in _INSTANCE_REWRITE_IF_READ_BACK and how == _BOUND_READ_BACK
            ):
                out.hit(
                    rel,
                    node.lineno,
                    f"{model} row `{receiver}` ({how}): `{receiver}.{node.func.attr}()` "
                    f"rewrites it — {model} declared itself append-only "
                    "(core.models.append_only), so a row may be created and never updated "
                    "or removed. The runtime belt (`BaseModel.save`/`.delete`, ADR core-14) "
                    "raises `AppendOnlyViolation` here the moment this line runs; this is "
                    "the static half of the same wall and it fires without running it. "
                    "Create a new row that supersedes this one, or take the model out of "
                    "the append-only population — the declaration IS the promise",
                )
    return out


# --- rule 24: org-scoped reads chain visible_to; the tree is written by services --

# The same door/service/selector set rule 8 watches. Rule 24 is rule 8 one level
# down: rule 8 asks "whose tenant", this asks "whose part of it".
_RULE24_FILES = dict.fromkeys(_RULE8_FILES)

_ORG_BASE = "OrgScopedModel"

# The two model names whose shape-bearing columns only their own services may
# write. Named here rather than derived, because they ARE the hierarchy: a
# product that renames them has rewritten the primitive.
_MEMBERSHIP = "Membership"
_ORGANIZATION = "Organization"
# The columns that decide who can see what. `role` on a membership, `path` and
# `parent` on an organization; everything else about either row is ordinary.
_ORG_SHAPE_FIELDS = ("path", "parent")

# ADR core-3 (G1). `governing(org)` resolves configuration UPWARDS — the nearest
# row on the actor's ancestor chain wins — and it is legal on exactly one
# population: models that declared `InheritedDownward`. The widening and its
# fence are born together, which is why the marker's name and its attribute are
# both read here: `core.models.is_inherited_downward` is an attribute lookup, so
# a model that writes `inherited_downward = True` by hand has declared it just as
# loudly as one that inherits the marker class.
_INHERITED_BASE = "InheritedDownward"
_INHERITED_ATTR = "inherited_downward"


def _class_bases_by_name(root: Path) -> dict[str, set[str]]:
    """{class name: base names} across the whole app tree, by AST."""
    class_bases: dict[str, set[str]] = {}
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = set()
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.add(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.add(b.attr)
            class_bases.setdefault(node.name, set()).update(bases)
    return class_bases


def _transitive(class_bases: dict[str, set[str]], seed: str) -> set[str]:
    reached = {seed}
    changed = True
    while changed:
        changed = False
        for name, bases in class_bases.items():
            if name not in reached and bases & reached:
                reached.add(name)
                changed = True
    reached.discard(seed)
    return reached


def inherited_downward_model_names(root: Path) -> set[str]:
    """Every class that declared itself inherited-downwards, by base or by attribute."""
    names = _transitive(_class_bases_by_name(root), _INHERITED_BASE)
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _class_attribute_is_true(node, _INHERITED_ATTR):
                names.add(node.name)
    # The marker class carries the attribute itself — it is the declaration, not
    # a model that made one.
    names.discard(_INHERITED_BASE)
    return names


def org_scoped_model_names(root: Path) -> set[str]:
    """Every class inheriting OrgScopedModel, transitively, by AST.

    Derived from the tree on every run, exactly as rule 8 derives its own set:
    a new org-scoped model is in scope the moment it exists, without anybody
    editing a list.
    """
    return _transitive(_class_bases_by_name(root), _ORG_BASE)


def _parent_map(tree: ast.Module) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _chained_after(parents: dict[int, ast.AST], node: ast.AST) -> set[str]:
    """Every attribute called on the result of `node`, walking the chain out.

    `X.objects.for_tenant(t).visible_to(o).filter(...)` -> {"visible_to",
    "filter"}. It stops the moment the expression stops being a method chain,
    so a queryset handed to another function and widened there is invisible
    here — declared in `does_not_cover`.
    """
    attrs: set[str] = set()
    current: ast.AST = node
    while True:
        parent = parents.get(id(current))
        if isinstance(parent, ast.Attribute) and parent.value is current:
            attrs.add(parent.attr)
            current = parent
        elif isinstance(parent, ast.Call) and parent.func is current:
            current = parent
        else:
            return attrs


def _rule24_paths(rule: dict, key: str) -> dict[str, set[str]]:
    """{path: {function, ...}} from a scope allow-list. An empty set means
    "anywhere in that file"."""
    allowed: dict[str, set[str]] = {}
    for entry in (rule.get("scope") or {}).get(key) or []:
        path = str(entry.get("path", ""))
        if not path:
            continue
        allowed.setdefault(path, set()).update(str(name) for name in entry.get("functions") or [])
    return allowed


def _allowed_here(allowed: dict[str, set[str]], rel: str, function: str | None) -> bool:
    if rel not in allowed:
        return False
    functions = allowed[rel]
    return not functions or (function in functions)


def org_scoped_reads(root: Path, rule: dict) -> CheckResult:
    """Rule 24, in four parts, because they are one rule from four sides.

    1. **Reads**: an `OrgScopedModel` read as `for_tenant(...)` with neither
       `.visible_to(...)` nor `.governing(...)` after it hands the whole tenant
       to whoever asked.
    2. **The fence on the widening** (ADR core-3): `.governing(...)` is upward
       *config resolution*, never upward *visibility*, and it is legal on
       exactly one population — models that declared `InheritedDownward`. A
       `governing()` on an unmarked model is a violation here for the same
       reason it is a `TypeError` there: the widening and its fence are born
       together, or the widening is a hole with no edges.
    3. **Grants**: a `Membership.role` written outside the membership services
       walks around the escalation wall rather than through it.
    4. **Shape**: an `Organization.path` or `.parent` written outside the move
       services silently detaches a subtree from every read in the product.
    """
    out = CheckResult()
    org_models = org_scoped_model_names(root)
    inherited = inherited_downward_model_names(root)
    known_models = org_models | scoped_model_names(root)
    out.targets_matched["org_scoped_models"] = len(org_models)
    out.targets_matched["inherited_downward_models"] = len(inherited)
    role_writers = _rule24_paths(rule, "membership_role_writers")
    shape_writers = _rule24_paths(rule, "organization_shape_writers")

    files = _py_files(root, "apps", named=set(_RULE24_FILES)) + _py_files(root, "config")
    for path in files:
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = path.relative_to(root).as_posix()
        src = _read(path)
        spans = _enclosing_functions(tree)
        parents = _parent_map(tree)

        # (1) the read.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "for_tenant":
                continue
            base = _chain_root(node)
            if not (isinstance(base, ast.Name) and base.id in org_models):
                continue
            chained = _chained_after(parents, node)
            if "visible_to" in chained:
                continue
            if "governing" in chained:
                # Legal, and its own fence is part (2) below — which judges the
                # call whether or not it followed a for_tenant().
                continue
            out.hit(
                rel,
                node.lineno,
                f"{base.id}.objects.for_tenant(...) on an org-scoped model without "
                ".visible_to(...) — a tenant-wide read of a row one part of the tenant "
                "owns; chain .visible_to(actor_or_org) after it, or .governing(org) when "
                "the model declared InheritedDownward",
            )

        # (2) governing() is legal only on a model that declared InheritedDownward.
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "governing":
                continue
            base = _chain_root(node)
            if not (isinstance(base, ast.Name) and base.id in known_models):
                continue
            if base.id in inherited:
                continue
            out.hit(
                rel,
                node.lineno,
                f"{base.id}.objects...governing(...) — {base.id} has not declared "
                "InheritedDownward, so the nearest-ancestor read is not legal on it. "
                "governing() is upward CONFIG resolution and never upward visibility: it "
                "returns rows a branch could never list, which is only safe where the "
                "model's rows are configuration inherited downwards. Declare "
                "`InheritedDownward` on the model (apps.core.models) if that is what it "
                "is, or read it with .visible_to(actor_or_org) (ADR core-3)",
            )

        # (3) who may write a membership's role.
        if _MEMBERSHIP in src:
            for lineno, what in _role_writes(tree):
                if _allowed_here(role_writers, rel, _function_at(spans, lineno)):
                    continue
                out.hit(
                    rel,
                    lineno,
                    f"{what} outside the membership services — a role granted here skips "
                    "the escalation wall (no grant above your own effective role, none "
                    "outside your subtree)",
                )

        # (4) who may write the tree's shape.
        if _ORGANIZATION in src:
            for lineno, what in _shape_writes(tree):
                if _allowed_here(shape_writers, rel, _function_at(spans, lineno)):
                    continue
                out.hit(
                    rel,
                    lineno,
                    f"{what} outside the organization services — a path or parent written "
                    "by hand detaches a subtree from every visible_to in the product; "
                    "re-parenting is move_organization",
                )
    return out


def _role_writes(tree: ast.Module) -> list[tuple[int, str]]:
    """Every way this module changes what somebody may do."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr == "role":
                    hits.append((node.lineno, "an assignment to .role"))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == _MEMBERSHIP:
                hits.append((node.lineno, "a Membership(...) constructed"))
            if isinstance(node.func, ast.Attribute) and node.func.attr in (
                "update",
                "create",
                "get_or_create",
                "update_or_create",
                "bulk_create",
            ):
                if any(keyword.arg == "role" for keyword in node.keywords):
                    hits.append((node.lineno, f".{node.func.attr}(role=...)"))
    return hits


def _shape_writes(tree: ast.Module) -> list[tuple[int, str]]:
    """Every way this module moves a node in the tree."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Attribute) and target.attr in _ORG_SHAPE_FIELDS:
                    hits.append((node.lineno, f"an assignment to .{target.attr}"))
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("update", "bulk_update")
        ):
            for keyword in node.keywords:
                if keyword.arg in _ORG_SHAPE_FIELDS:
                    hits.append((node.lineno, f".{node.func.attr}({keyword.arg}=...)"))
    return hits


# --- rule 23: supply chain (secret patterns; the tool legs live in check.sh) --

_SECRET_PATTERNS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "an AWS access key id"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"), "a private key block"),
    (re.compile(r"xox[bpoas]-[0-9A-Za-z-]{10,}"), "a Slack token"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}"), "a GitHub personal access token"),
]


def supply_chain(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for sub in ("apps", "config", "scripts"):
        base = root / sub
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix in (".pyc", ".sqlite3"):
                continue
            if "__pycache__" in path.parts:
                continue
            text = _read(path)
            if not text:
                continue
            out.count("files_scanned")
            rel = str(path.relative_to(root))
            for pattern, what in _SECRET_PATTERNS:
                m = pattern.search(text)
                if m:
                    line = text[: m.start()].count("\n") + 1
                    out.hit(
                        rel,
                        line,
                        f"{what} in the tree — secrets live in the environment, never the repo",
                    )
    pyproject = _read(root / "pyproject.toml")
    for tool in ("pip-audit", "pip-licenses", "detect-secrets"):
        if tool not in pyproject:
            out.hit(
                "pyproject.toml",
                1,
                f"{tool} is not a declared dev dependency — the supply-chain legs have nothing "
                "to run",
            )
    check_sh = _read(root / "scripts" / "check.sh")
    if check_sh:
        for tool in ("pip-audit", "pip-licenses", "detect-secrets"):
            if tool not in check_sh:
                out.hit("scripts/check.sh", 1, f"the {tool} leg is missing from the full gate")
    if not (root / ".secrets.baseline").exists():
        out.hit(
            ".secrets.baseline",
            1,
            "no detect-secrets baseline — the secrets leg cannot tell new from known",
        )
    return out


# --- rule 25: only comms sends ------------------------------------------------
#
# The closed question: does any module under apps/ outside the allow-list import
# a module that CARRIES A MESSAGE OUT OF THIS PRODUCT? `comms.send()` is the only
# legal sender — consent, quiet hours and suppression are enforced INSIDE it, so
# a feature that reaches for one of these reaches around all three. The rule is
# mechanical because the alternative is remembering.
#
# THE POPULATION IS DATA (ING-4 T2). It was two hard-coded mail modules
# while email was the only transport; ADR comms-9 grows the product to three
# (`twilio` now, `firebase_admin` at T3), and the ADR's own sentence is that the
# wall "covers three transports, same rule id". So the senders are declared in
# `rules.yaml` beside the allow-list they are allowed at, one entry with its
# reason, and adding the next transport is a yaml line and a canary rather than
# an edit here. The two mail modules stay the default when a rule declares no
# senders at all, so the check still answers for a rule file that predates this.
_DEFAULT_SENDERS = ("django.core.mail", "apps.core.mail")
MAIL_KLASS = "mail_imports"


def _senders(rule: dict) -> tuple[str, ...]:
    """The sender modules this rule forbids, declared in `scope.senders`."""
    declared = [
        str(entry.get("module", "")).strip()
        for entry in (rule.get("scope") or {}).get("senders") or []
        if str(entry.get("module", "")).strip()
    ]
    return tuple(declared) or _DEFAULT_SENDERS


def _sender_packages(senders: tuple[str, ...]) -> dict[str, str]:
    """`{"apps.core": "apps.core.mail"}` — derived, so a declaration is enough.

    It is the `from apps.core import mail` shape and it needs the parent package
    and the leaf name, which a dotted sender already carries. A sender that is a
    whole top-level package (`twilio`) has no such shape to derive: `from twilio
    import rest` is caught by the name itself, one branch up.
    """
    out: dict[str, str] = {}
    for module in senders:
        package, _, leaf = module.rpartition(".")
        if package:
            out[f"{package}:{leaf}"] = module
    return out


def _mail_import(node: ast.AST, senders: tuple[str, ...]) -> str | None:
    """The sender module this statement pulls in, or None. Import shapes only.

    Three forms reach a sender and they are the three a person writes:
    `from django.core.mail import send_mail`, `from apps.core import mail`, and
    `import django.core.mail` — and, for a sender that is a package rather than
    a module, `from twilio.rest import Client` and `import twilio`, which the
    same two branches already cover. Prose that merely NAMES one — every
    docstring in `apps/comms` does — is not an import and is not a finding; that
    restraint is what the negatives here are for.
    """
    packages = _sender_packages(senders)
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module in senders or any(module.startswith(f"{m}.") for m in senders):
            return module
        for alias in node.names:
            named = packages.get(f"{module}:{alias.name}")
            if named:
                return named
        return None
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name in senders or any(alias.name.startswith(f"{m}.") for m in senders):
                return alias.name
    return None


def _permitted_senders(rel: str, rule: dict, senders: tuple[str, ...]) -> set[str]:
    """Which senders this file may import, unioned over every allow entry it matches.

    An entry with no `modules` list permits every sender at that path, which is
    what the mail-only allow-list has always meant. An entry WITH one is a
    pinned exemption — ADR comms-9 asks for exactly one, `twilio` at
    `apps/comms/providers.py` — and pinning is the difference between "the comms
    app may carry messages" and "any file in the comms app may reach for a
    vendor's SDK".
    """
    permitted: set[str] = set()
    for entry in (rule.get("scope") or {}).get("allow") or []:
        path = str(entry.get("path", ""))
        if not path or not (rel == path or rel.startswith(path)):
            continue
        modules = [str(name).strip() for name in entry.get("modules") or [] if str(name).strip()]
        permitted |= set(modules) if modules else set(senders)
    return permitted


def mail_imports(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    senders = _senders(rule)
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        permitted = _permitted_senders(rel, rule, senders)
        for node in ast.walk(tree):
            module = _mail_import(node, senders)
            if module is None:
                continue
            if any(module == name or module.startswith(f"{name}.") for name in permitted):
                # The allow-list's own matches are counted, and the count is
                # floored: if the recogniser above ever stopped recognising an
                # import, THESE would go quiet first and the floor would say so
                # — where the violation count going to zero would read as a pass.
                out.count("allowed_mail_modules")
                continue
            out.hit(
                rel,
                getattr(node, "lineno", 1),
                f"imports {module} — comms.send() is the only legal sender in this product, "
                "and consent, quiet hours and suppression are enforced inside it. Call it, or "
                "add this module to rule 25's allow-list in quality/rules.yaml with the reason",
                klass=MAIL_KLASS,
            )
    return out


# --- rule 26: a service names nothing the actor could not have reached --------
#
# ADR core-4 (G3). `core.authz.may_be_named(actor, obj)` is the check; this rule
# is what makes calling it non-optional in the one population where forgetting
# it is a leak rather than a bug: a `@service` that WRITES an org-scoped row and
# takes a reference to an org-scoped row it was handed.
#
# The closed question, stated exactly: a `@service` in an app's `services.py`
# that writes an org-scoped row, and takes a parameter ANNOTATED with an
# org-scoped model, must either pass that parameter through `may_be_named`
# somewhere in its body, or carry `# reach: <reason>` on the parameter (or on
# the function). Which keyword arguments are foreign-key targets is unknowable
# in general — ADR core-4 says so, and rejects generic enforcement inside
# `@service` for exactly that reason — so **the annotation is the declaration**
# this rule reads. A target laundered through a local variable, a helper, or an
# unannotated parameter is outside the question, and `does_not_cover` says so
# rather than pretending otherwise.

# The valve. `# reach: <reason>` — a sentence somebody wrote and a reviewer can
# disagree with, on the line it excuses. It is not a disable: every one is
# counted (`reach_overrides` on the rule's own status line) and every one is
# visible to `grep -rn "# reach:" apps/`.
_REACH_RE = re.compile(r"#\s*reach\b:?\s*(.*)$")
# Long enough to force a clause, exactly as the gate's own override reasons are.
_MIN_REACH_REASON = 12
_ORG_WRITE_CALLS = _WRITE_MANAGER_CALLS | {"update", "delete", "bulk_update"}


def _annotation_names(node: ast.expr | None) -> set[str]:
    """Every class name an annotation mentions. `Widget | None` -> {"Widget"}.

    String annotations are parsed rather than skipped, because a product may
    quote one even with `from __future__ import annotations` on.
    """
    if node is None:
        return set()
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, str):
            return set()
        try:
            return _annotation_names(ast.parse(node.value, mode="eval").body)
        except (SyntaxError, ValueError):
            return set()
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            out.add(sub.id)
        elif isinstance(sub, ast.Attribute):
            out.add(sub.attr)
        elif isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub is not node:
            out |= _annotation_names(sub)
    return out


def _reach_reason(lines: list[str], line: int) -> str | None:
    """The reason a `# reach:` marker claims at this line, or None when none is.

    On the line itself, or in the CONTIGUOUS comment block directly above it —
    the same grammar the gate reads `# rule-<id>:` overrides with, so there is
    one shape to learn and an exemption cannot drift onto a parameter nobody
    thought about.
    """
    if not lines or line < 1 or line > len(lines):
        return None
    m = _REACH_RE.search(lines[line - 1])
    if m:
        return m.group(1).strip()
    i = line - 2
    while i >= 0 and lines[i].strip().startswith("#"):
        m = _REACH_RE.search(lines[i])
        if m:
            return m.group(1).strip()
        i -= 1
    return None


def _all_args(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    return list(fn.args.posonlyargs) + list(fn.args.args) + list(fn.args.kwonlyargs)


def _org_bound_names(fn: ast.FunctionDef | ast.AsyncFunctionDef, org_models: set[str]) -> set[str]:
    """Local names this function holds an org-scoped row in, as far as AST sees.

    Three ways to be one: a parameter annotated with an org-scoped model, a name
    annotated with one, and a name assigned from an expression whose chain root
    IS one (`row = Widget(...)`, `row = Message.objects.create(...)`).
    """
    bound = {a.arg for a in _all_args(fn) if _annotation_names(a.annotation) & org_models}
    for node in ast.walk(fn):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if _annotation_names(node.annotation) & org_models:
                bound.add(node.target.id)
        elif isinstance(node, ast.Assign) and node.value is not None:
            root = _chain_root(node.value)
            if isinstance(root, ast.Name) and root.id in org_models:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bound.add(target.id)
    return bound


def _writes_org_scoped(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, org_models: set[str], bound: set[str]
) -> bool:
    """Whether this function writes a row one part of a tenant owns.

    Three witnesses, each of them closed:

    1. a manager or queryset write whose chain root names an org-scoped model
       (`Widget.objects.create(...)`, `Message.objects.filter(...).update(...)`);
    2. a `.save()` / `.delete()` on a name bound to an org-scoped row above;
    3. ANY ORM write at all inside a service whose return annotation names an
       org-scoped model — which is how a row assembled by a private helper and
       saved here is still recognised as the row this service writes.
    """
    writes = False
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        if attr in _ORG_WRITE_CALLS:
            root = _chain_root(node.func.value)
            if isinstance(root, ast.Name) and root.id in org_models:
                return True
        if attr in ("save", "delete", "update"):
            receiver = node.func.value
            if isinstance(receiver, ast.Name):
                if receiver.id in bound:
                    return True
                if receiver.id not in _NON_MODEL_RECEIVERS:
                    writes = True
    return writes and bool(_annotation_names(fn.returns) & org_models)


def _named_through_may_be_named(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Every name handed DIRECTLY to a `may_be_named(...)` call in this function.

    Direct is the whole point . This used to walk each argument and count
    every `Name` inside it, so `may_be_named(actor, widget.parent)` marked
    `widget` checked — while the thing checked was its parent and `widget`
    itself was never asked about. That is the rule's own subject laundered
    through an attribute access, and it read as compliance.

    A bare `Name` argument is the only form that means "this parameter was
    checked". Anything else — an attribute, a subscript, a call, an f-string —
    checks something *derived from* the parameter, which is a different row,
    and the parameter it came from stays unchecked. An author who really did
    mean to clear the parameter writes it, and an author who meant the parent
    writes `# reach:` and says why.
    """
    checked: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else "")
        )
        if name != "may_be_named":
            continue
        for arg in list(node.args) + [k.value for k in node.keywords]:
            if isinstance(arg, ast.Name):
                checked.add(arg.id)
    return checked


def service_reach(root: Path, rule: dict) -> CheckResult:
    """Rule 26. Findings are classed by APP, so one app's backlog cannot pay for
    another app's growth — the per-app numbers in the measurement report and the
    per-app ratchets in `rules.yaml` are the same numbers."""
    out = CheckResult()
    org_models = org_scoped_model_names(root)
    out.targets_matched["org_scoped_models"] = len(org_models)
    # Seeded at zero rather than counted up from nothing, so the rule's own
    # status line always PRINTS the standing valve count — "counted and printed"
    # is the whole discipline, and a key that only appears when it is non-zero
    # is a number nobody sees fall to zero either.
    out.targets_matched["reach_overrides"] = 0
    out.targets_matched["reachability_checks"] = 0
    for path in _py_files(root, "apps", named={"services.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = path.relative_to(root).as_posix()
        app = path.parent.name
        lines = _read(path).splitlines()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "service" not in _decorator_names(node):
                continue
            bound = _org_bound_names(node, org_models)
            if not _writes_org_scoped(node, org_models, bound):
                continue
            out.count("writing_services")
            checked = _named_through_may_be_named(node)
            top = min([d.lineno for d in node.decorator_list] or [node.lineno])
            whole_function = _reach_reason(lines, node.lineno) or _reach_reason(lines, top)
            for arg in _all_args(node):
                targets = sorted(_annotation_names(arg.annotation) & org_models)
                if not targets:
                    continue
                out.count("fk_target_kwargs")
                if arg.arg in checked:
                    out.count("reachability_checks")
                    continue
                reason = _reach_reason(lines, arg.lineno)
                if reason is None:
                    reason = whole_function
                if reason is not None:
                    if len(reason) >= _MIN_REACH_REASON:
                        out.count("reach_overrides")
                        continue
                    out.hit(
                        rel,
                        arg.lineno,
                        f"`# reach:` with no reason on {node.name}({arg.arg}=) — an escape "
                        "hatch nobody has to justify is an off switch; write the sentence a "
                        "reviewer can disagree with",
                        klass=app,
                    )
                    continue
                out.hit(
                    rel,
                    arg.lineno,
                    f"{node.name} writes an org-scoped row and takes {arg.arg}: "
                    f"{'/'.join(targets)} without passing it through "
                    "core.authz.may_be_named(actor, ...) — a reference the actor may never "
                    "have been able to reach, in a branch it holds no membership over. Check "
                    "it and refuse when it is False, or record `# reach: <reason>` on the "
                    "parameter (ADR core-4)",
                    klass=app,
                )
    return out


# --- rule 27: one door to the identity platform -------------------------------
#
# ADR ident-2, P0 W2-R2. Identity configuration is written through our audited
# services and materialised in Zitadel by one activity; the console is a window,
# not a door. A check cannot see the console — that is the declared blind spot —
# but it can see the half that is in this tree, and this is that half, stated as
# a closed question with two shapes:
#
# 1. **the credential**: `ZITADEL_PAT` is named in `apps/accounts/zitadel.py`
# (where it is used) and in `config/settings/` (where the environment is
# read), and nowhere else. A third reader is a third place a PAT can reach a
# log line, an exception message or a subprocess environment.
# 2. **the client**: `apps.accounts.zitadel` is imported only from the places
# where a management call is legitimate — the activity, where a failure is a
# Temporal retry, and the two `zitadel_*` commands, which are the shell door.
# A service importing it would put external I/O inside a transaction (C2); a
# route or a tool importing it would put an unbounded network call on
# somebody's request.
#
# Both halves are read from the AST rather than from the text, which is what
# makes the negatives possible: this module's own prose names `ZITADEL_PAT`
# repeatedly, and a check that fired on the word would fire on its own reasons.

# The setting whose only two homes are the client and the settings module.
PAT_SETTING = "ZITADEL_PAT"
# The module every other module must go through, and never around.
CLIENT_MODULE = "apps.accounts.zitadel"
CLIENT_PACKAGE, _, CLIENT_NAME = CLIENT_MODULE.rpartition(".")
ZITADEL_KLASS = "zitadel_client"


def _names_pat(node: ast.AST) -> bool:
    """Whether this node names the PAT setting. **Never prose.**

    Three shapes and exactly three: `settings.ZITADEL_PAT` (an attribute),
    `getattr(settings, "ZITADEL_PAT")` / `env.str("ZITADEL_PAT")` (a string
    constant that IS the name, not one that contains it), and a bare
    `ZITADEL_PAT` binding, which is how a settings module declares one. A
    docstring that mentions the variable is a `Constant` whose value is the
    whole docstring, so equality — rather than membership — is what keeps this
    silent on documentation.
    """
    if isinstance(node, ast.Attribute):
        return node.attr == PAT_SETTING
    if isinstance(node, ast.Name):
        return node.id == PAT_SETTING
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and node.value == PAT_SETTING
    return False


def _imports_client(node: ast.AST) -> bool:
    """Whether this statement pulls in the management client. Import shapes only.

    The three a person writes: `from apps.accounts.zitadel import x`,
    `from apps.accounts import zitadel`, and `import apps.accounts.zitadel`.
    """
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module == CLIENT_MODULE or module.startswith(f"{CLIENT_MODULE}."):
            return True
        return module == CLIENT_PACKAGE and any(a.name == CLIENT_NAME for a in node.names)
    if isinstance(node, ast.Import):
        return any(
            a.name == CLIENT_MODULE or a.name.startswith(f"{CLIENT_MODULE}.") for a in node.names
        )
    return False


def zitadel_client(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    scope = rule.get("scope") or {}
    importers = [str(e.get("path", "")) for e in scope.get("allow_import") or [] if e.get("path")]
    readers = [str(e.get("path", "")) for e in scope.get("allow_secret") or [] if e.get("path")]
    client_rel = CLIENT_MODULE.replace(".", "/") + ".py"

    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        if rel == client_rel:
            # The module the rule funnels everything into. Its own PAT read and
            # its own client are the point, and they are counted so that a
            # recogniser that stopped recognising anything trips the floor
            # rather than reporting a clean nothing.
            out.count("client_module")
            for node in ast.walk(tree):
                if _names_pat(node):
                    out.count("pat_sites")
            continue

        may_import = any(rel == entry or rel.startswith(entry) for entry in importers)
        may_read = any(rel == entry or rel.startswith(entry) for entry in readers)

        for node in ast.walk(tree):
            if _names_pat(node):
                if may_read:
                    out.count("pat_sites")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"names the {PAT_SETTING} setting — the platform credential is read in "
                        f"{client_rel} and declared in config/settings, and nowhere else. Call "
                        f"{CLIENT_MODULE}, or add this module to rule 27's allow-list in "
                        "quality/rules.yaml with the reason",
                        klass=ZITADEL_KLASS,
                    )
                continue
            if not _imports_client(node):
                continue
            if may_import:
                out.count("client_importers")
                continue
            out.hit(
                rel,
                getattr(node, "lineno", 1),
                f"imports {CLIENT_MODULE} — the Zitadel management API is reached from an "
                "activity (where a failure is a retry) or a zitadel_* command, never from a "
                "service, a door or a selector: an external call inside a transaction is a "
                "hiccup that rolls back a legitimate row. Start "
                "SyncIdentityConfigWorkflow instead, or add this module to rule 27's "
                "allow-list in quality/rules.yaml with the reason",
                klass=ZITADEL_KLASS,
            )
    return out


# --- rule 33: one door to the search index (ADR search-2, R-a) ------------
#
# The rule-27 shape, pointed at a different external system and for a sharper
# reason. Zitadel's fence is about a CREDENTIAL and a transaction boundary;
# this one is about a WALL.
#
# An external index that does not carry the tenant walls is a probing oracle:
# type a word, learn whether somebody else's row contains it. The walls are
# injected by exactly one function (`apps/search/selectors.py`), and that
# sentence is only true while there is exactly one way to reach the engine. A
# second module holding a Meili client is not a style problem — it is a second
# query path with no filter on it, and nothing anywhere would go red.
#
# TWO HALVES, as rule 27 has:
#
# 1. **the credential and the address**: `MEILI_URL` and `MEILI_MASTER_KEY` are
# named in `apps/search/engine.py` (where they are used) and in
# `config/settings/` (where the environment is read), and nowhere else. A
# third reader is a third place a master key can reach a log line, an
# exception message or a subprocess environment — and a fourth way to dial
# the index.
# 2. **the client**: `meilisearch` is imported ONLY by `engine.py`, and
# `apps.search.engine` is imported only from the allow-list below — the
# chokepoint, the write services, the reconcile activity, the backstop
# command and the tests.
#
# Both halves are read from the AST rather than from the text, which is what
# makes the negatives possible: this module's own prose names
# `MEILI_MASTER_KEY` repeatedly, and a check that fired on the word would fire
# on its own reasons.

# : The two names that may not travel. `MEILI_ENV` is deliberately NOT one of
# : them: it selects the server's own mode and is neither an address nor a
# : credential, so refusing it would be the rule getting bigger than its reason.
MEILI_SETTINGS = ("MEILI_URL", "MEILI_MASTER_KEY")

# : The client library the fence exists to confine.
MEILI_PACKAGE = "meilisearch"

# : The module every other module must go through, and never around.
ENGINE_MODULE = "apps.search.engine"
ENGINE_PACKAGE, _, ENGINE_NAME = ENGINE_MODULE.rpartition(".")
MEILI_KLASS = "meili_client"


def _names_meili_setting(node: ast.AST) -> str | None:
    """Which fenced name this node names, or `None`. **Never prose.**

    The three shapes and exactly three: `settings.MEILI_URL` (an attribute), a
    string constant that IS the name (`os.environ["MEILI_URL"]`,
    `env.str("MEILI_URL")`), and a bare binding, which is how a settings module
    declares one. A docstring that mentions the variable is a `Constant` whose
    value is the whole docstring, so EQUALITY — rather than membership — is what
    keeps this silent on documentation.
    """
    if isinstance(node, ast.Attribute) and node.attr in MEILI_SETTINGS:
        return node.attr
    if isinstance(node, ast.Name) and node.id in MEILI_SETTINGS:
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if node.value in MEILI_SETTINGS else None
    return None


def _imports_meili(node: ast.AST) -> bool:
    """Whether this statement pulls in the Meilisearch client library itself."""
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return module == MEILI_PACKAGE or module.startswith(f"{MEILI_PACKAGE}.")
    if isinstance(node, ast.Import):
        return any(
            alias.name == MEILI_PACKAGE or alias.name.startswith(f"{MEILI_PACKAGE}.")
            for alias in node.names
        )
    return False


def _imports_engine(node: ast.AST) -> bool:
    """Whether this statement pulls in the fenced engine module.

    The three shapes a person writes: `from apps.search.engine import x`,
    `from apps.search import engine`, and `import apps.search.engine`.
    """
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        if module == ENGINE_MODULE or module.startswith(f"{ENGINE_MODULE}."):
            return True
        return module == ENGINE_PACKAGE and any(a.name == ENGINE_NAME for a in node.names)
    if isinstance(node, ast.Import):
        return any(
            a.name == ENGINE_MODULE or a.name.startswith(f"{ENGINE_MODULE}.") for a in node.names
        )
    return False


def meili_client(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    scope = rule.get("scope") or {}
    importers = [str(e.get("path", "")) for e in scope.get("allow_import") or [] if e.get("path")]
    readers = [str(e.get("path", "")) for e in scope.get("allow_secret") or [] if e.get("path")]
    engine_rel = ENGINE_MODULE.replace(".", "/") + ".py"

    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        if rel == engine_rel:
            # The module the rule funnels everything into. Its own client and
            # its own two environment reads are the POINT, and they are counted
            # so that a recogniser which stopped recognising anything trips the
            # floor rather than reporting a clean nothing.
            out.count("engine_module")
            for node in ast.walk(tree):
                if _names_meili_setting(node):
                    out.count("secret_sites")
                elif _imports_meili(node):
                    out.count("client_imports")
            continue

        may_import = any(rel == entry or rel.startswith(entry) for entry in importers)
        may_read = any(rel == entry or rel.startswith(entry) for entry in readers)

        for node in ast.walk(tree):
            named = _names_meili_setting(node)
            if named:
                if may_read:
                    out.count("secret_sites")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"names {named} — the search index's address and master key are read "
                        f"in {engine_rel} and declared in config/settings, and nowhere else. "
                        "A second reader is a second way to dial the index, and the index is "
                        "where the tenant walls are injected. Call apps.search.selectors."
                        "search(), or add this module to rule 33's allow-list in "
                        "quality/rules.yaml with the reason",
                        klass=MEILI_KLASS,
                    )
                continue
            if _imports_meili(node):
                out.hit(
                    rel,
                    getattr(node, "lineno", 1),
                    f"imports {MEILI_PACKAGE} — the search engine is reached through "
                    f"{engine_rel} and nowhere else. A client here is a query path with no "
                    "scope filter on it: the walls are injected by ONE function "
                    "(apps/search/selectors.py) and an unfenced client is how an index "
                    "becomes a probing oracle. Call apps.search.selectors.search()",
                    klass=MEILI_KLASS,
                )
                continue
            if not _imports_engine(node):
                continue
            if may_import:
                out.count("engine_importers")
                continue
            out.hit(
                rel,
                getattr(node, "lineno", 1),
                f"imports {ENGINE_MODULE} — the engine takes a ScopeFilter it does not "
                "build, so a caller outside the chokepoint is a caller choosing its own "
                "walls. Reads go through apps.search.selectors.search(); writes go "
                "through apps.search.services. Or add this module to rule 33's "
                "allow-list in quality/rules.yaml with the reason",
                klass=MEILI_KLASS,
            )
    return out


# --- the diff-aware layer ------------------------------------------------------


# --- rule 35: hot-path plan shapes (ADR gate-2) --------------------------------


def hot_path_sargability(root: Path, rule: dict) -> CheckResult:
    """EXPLAIN every probed registry entry's real read, via the probe subprocess.

    The subprocess (`quality/hotpath_probe.py`) owns the per-checkout `_hp`
    probe database, migrates it, ANALYZEs it (the declared statistics
    assumption — the seeder's precedent, F1d), sets `enable_seqscan = off` and
    applies each entry's clauses to the statements the read actually issued.
    A probe that cannot run reports zero targets, which the floors turn into
    UNBOUND — enforcement broken, never a pass.
    """
    out = CheckResult()
    registry = rule.get("registry") or []
    out.count("hot_paths", len(registry))
    proc = subprocess.run(
        [sys.executable, str(root / "quality" / "hotpath_probe.py")],
        cwd=root,
        capture_output=True,
        text=True,
        env=dict(os.environ),
        check=False,
    )
    if proc.returncode != 0:
        # No probed/explained counts land, so the floors report UNBOUND (exit
        # 2); this finding says why, so the reader is not left with a bare
        # "may be watching nothing".
        tail = (proc.stderr or proc.stdout).strip()[-1500:]
        out.hit(
            "quality/hotpath_probe.py",
            0,
            f"the hot-path probe could not run (exit {proc.returncode}) — rule 35 is "
            f"enforcing nothing until it can:\n{tail}",
        )
        return out
    try:
        report = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        out.hit(
            "quality/hotpath_probe.py",
            0,
            "the hot-path probe produced no report — rule 35 is enforcing nothing "
            f"until it does. stdout tail:\n{proc.stdout.strip()[-800:]}",
        )
        return out
    out.count("probed_paths", int(report.get("probed", 0)))
    out.count("explained_statements", int(report.get("explained_statements", 0)))
    declared = int(report.get("lookup_columns_declared", 0))
    untyped = int(report.get("index_served_untyped", 0))
    proven = int(report.get("lookup_columns_proven", 0))
    unproven = int(report.get("lookup_columns_unproven", 0))
    out.count("lookup_columns_declared", declared)
    out.count("lookup_columns_proven", proven)
    out.count("lookup_columns_unproven", unproven)
    out.count("index_served_untyped", untyped)
    out.findings.extend(_untyped_ratchet(root, untyped))
    out.findings.extend(_unproven_ratchet(root, unproven))
    out.findings.extend(_vacuous_negatives(root, rule, report.get("plan_shapes") or {}))
    for note in report.get("notes", []):
        if "UNPROVEN" in str(note) or "is proven at gate scale" in str(note):
            # The world every declaration rests on, printed on every run. A
            # number a reviewer never sees is a blind spot, not a measurement.
            out.count("lookup_world_reported", 1)
    for finding in report.get("findings", []):
        dotted = str(finding).split(":", 1)[0]
        out.hit(_dotted_to_file(root, dotted), 0, str(finding))
    return out


def _unproven_ratchet(root: Path, unproven: int) -> list[Finding]:
    """`lookup_columns_unproven` may fall and never rise (b)).

    The declaration says a named column's predicate IS the lookup. That is only
    an assertion in a world where the planner could have chosen otherwise; on a
    nought-row table under `enable_seqscan = off` it is a restatement of the
    setting. Four of the five declarations were in that state when this was
    built — the header's own sizing argument, applied to one table out of five —
    and nothing said so. It is not a violation (the harness holds the evidence
    for those columns), it is a POPULATION, so it lives under the same
    rising-floor grammar as `index_served_untyped`: it may shrink, never grow.

    The finding points at `quality/hotpaths.py` and not at the budgets file,
    because the thing that has to change to shrink it is the WORLD.
    """
    recorded_file = yaml.safe_load((root / "quality" / "budgets.yaml").read_text()) or {}
    section = recorded_file.get("hot_path_lookup_columns") or {}
    ceiling = section.get("lookup_columns_unproven")
    if ceiling is None:
        return [
            Finding(
                "quality/hotpaths.py",
                0,
                "hot_path_lookup_columns.lookup_columns_unproven is not recorded — the "
                f"{unproven} declared lookup column(s) sitting on a probe table too small "
                "to falsify them are an undeclared population; record the measured number "
                "in quality/budgets.yaml",
            )
        ]
    if unproven > int(ceiling):
        return [
            Finding(
                "quality/hotpaths.py",
                0,
                f"lookup_columns_unproven is at {unproven}, past the recorded ratchet of "
                f"{ceiling} — a declared lookup column has lost the world that made it an "
                "assertion. Either the probe world shrank (quality/hotpaths.py sizes it, "
                "and says what the sizes buy) or a new declaration landed on a table that "
                "has no rows. Grow the world, or raise the number in a diff a reviewer "
                "reads",
            )
        ]
    return []


def _vacuous_negatives(root: Path, rule: dict, shapes: dict) -> list[Finding]:
    """A planted negative must actually CONTAIN the shape it claims to exempt.

    A negative is silent for one of two reasons: the rule shows restraint, or
    the shape was never there. Those look identical from outside, and rule 35
    shipped one of each for a cycle — `filtered_audit_read.py` claimed to exempt
    "a Filter beside an Index Cond" while the planner folded its predicate into
    the Index Cond, so no `Filter:` was ever produced and the negative proved
    nothing at all ().

    So a rule-35 negative may declare `plan_shape: {marker, path, table,
    contains}`. `marker` is a string the fixture carries; when it is present in
    the plant target the fixture IS planted, and the shape it names must be in
    the plans the probe just read. When it is absent this costs nothing — which
    is every ordinary run.
    """
    out: list[Finding] = []
    for entry in rule.get("negatives") or []:
        shape = entry.get("plan_shape")
        if not shape:
            continue
        target = root / str(entry.get("plant_at", ""))
        if not target.is_file() or str(shape.get("marker", "")) not in _read(target):
            continue
        seen = (shapes.get(str(shape.get("path"))) or {}).get(str(shape.get("table"))) or []
        wanted = str(shape.get("contains"))
        if not any(wanted in str(item) for item in seen):
            out.append(
                Finding(
                    str(entry.get("plant_at", "quality/rules.yaml")),
                    0,
                    f"VACUOUS NEGATIVE — {entry.get('fixture')} is planted and claims to "
                    f"exempt {wanted!r} on {shape.get('table')}, but the plans for "
                    f"{shape.get('path')} carry {seen or 'nothing for that table'}. A "
                    "negative that is silent because the shape was never there proves the "
                    "rule ignores something nobody wrote; rewrite the fixture until its "
                    "plan carries the shape, then the silence means restraint",
                )
            )
    return out


def _untyped_ratchet(root: Path, untyped: int) -> list[Finding]:
    """`index_served_untyped` may fall and never rise (F2-4).

    The declared blind spot of the subject-column form is the population that
    has NOT declared one: those entries keep the weak any-Index-Cond semantics
    P-1 walked through. A blind spot that can grow while nobody looks is not a
    declared blind spot, so the size of it is a number in `budgets.yaml` and
    growth is a violation — the same rising-floor grammar every other budget
    uses, checked on every run rather than only against a diff, because a fresh
    checkout has no diff and the population is a property of the tree.
    """
    recorded_file = yaml.safe_load((root / "quality" / "budgets.yaml").read_text()) or {}
    section = recorded_file.get("hot_path_lookup_columns") or {}
    ceiling = section.get("index_served_untyped")
    if ceiling is None:
        return [
            Finding(
                "quality/budgets.yaml",
                0,
                "hot_path_lookup_columns.index_served_untyped is not recorded — the "
                f"{untyped} index_served table(s) keeping the weak any-Index-Cond "
                "semantics are an undeclared population, which is how P-1 stayed "
                "invisible; record the measured number",
            )
        ]
    if untyped > int(ceiling):
        return [
            Finding(
                "quality/budgets.yaml",
                0,
                f"index_served_untyped is at {untyped}, past the recorded ratchet of "
                f"{ceiling} — a new index_served table arrived with no `lookup_columns`, "
                "so its scan is index-served by whatever Index Cond happens to be there "
                "(the tenant leg, typically). Declare the column, or raise the number in "
                "a diff a reviewer reads",
            )
        ]
    return []


# --- rule 36: socket fan-out discipline (ADR gate-2; M4 §8) --------------------

_GROUP_BUILDER_TENANT = "tenant_group"


def _callee_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _message_carries_org(node: ast.expr) -> str | None:
    """Why this payload is org-bearing, or None when nothing says it is."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and sub.value == "organization_id":
            return 'it names "organization_id"'
        if isinstance(sub, ast.Attribute) and sub.attr == "organization_id":
            return "it reads .organization_id"
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "model_dump"
        ):
            return "it serialises an envelope (.model_dump), which carries organization_id"
    return None


def socket_group_discipline(root: Path, rule: dict) -> CheckResult:
    """An org-bearing payload is never pushed to a bare tenant group.

    Exact-shape by design (M4 §8): the whole subject is one decision point
    (`apps/realtime/bridge.py::group_for`) and the `group_send` call sites under
    `apps/`. A `group_send` whose group argument is a direct `tenant_group(...)`
    call and whose message is org-bearing is the org-blind push P3-R0 found.
    """
    out = CheckResult()
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _callee_name(node.func) != "group_send":
                continue
            out.count("group_send_sites")
            args = list(node.args)
            group = args[0] if args else None
            message = args[1] if len(args) > 1 else None
            is_bare_tenant = (
                isinstance(group, ast.Call) and _callee_name(group.func) == _GROUP_BUILDER_TENANT
            )
            if not is_bare_tenant:
                continue
            if message is None:
                continue
            reason = _message_carries_org(message)
            if reason is not None:
                out.hit(
                    rel,
                    node.lineno,
                    f"an org-bearing payload is pushed to the bare tenant group ({reason}) — "
                    "every branch's socket hears another branch's rows (P3-R0's HIGH, priced "
                    "at 495 wrong-branch frames per 500 sockets by M4). The group is "
                    "`group_for`'s decision, never `tenant_group(...)` at a push site.",
                )
    bridge = root / "apps" / "realtime" / "bridge.py"
    bridge_tree = _parse(bridge)
    if bridge_tree is not None:
        for node in bridge_tree.body:
            is_decision = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            if is_decision and node.name == "group_for":
                out.count("decision_points")
    return out


def _camel_suffix_pairs(model: str, stem: str) -> bool:
    """Does an `Out` schema named `<stem>Out` read rows of the model `<model>`?

    The house convention (rule 16) is `<Model>Out`, and the exact match is the
    ordinary answer. The other legal form is a schema that drops a qualifying
    *prefix* the model carries — `ChannelPreference` is reported by
    `PreferenceOut`, because the app has one kind of preference and the word
    "channel" is noise on the wire. So the pairing is "the stem is the model
    name, or a CamelCase-word-boundary **suffix** of it".

    Suffix and never prefix, deliberately: `WidgetStatsOut` is an aggregate over
    widgets and not a widget, and pairing it with `Widget` would demand an
    `organization_id` on a shape that has no single row behind it.
    """
    if stem == model:
        return True
    if not stem or not model.endswith(stem) or len(stem) >= len(model):
        return False
    # The boundary must be a CamelCase word start, so `Entry` pairs with
    # `WidgetEntry` while `Try` does not.
    return stem[0].isupper()


def _out_fields_with_inheritance(path: Path) -> dict[str, dict[str, str]]:
    """`_out_fields`, plus the fields an `Out` inherits from a sibling in the file.

    A `class WidgetDetailOut(WidgetOut)` that adds two fields has declared every
    field `WidgetOut` declared. Reading only the class body would call that a
    violation, which is a false positive the negatives keep honest.
    """
    source = _read(path)
    own = _out_fields(source)
    tree = _parse(path)
    if tree is None:
        return own
    bases: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in own:
            bases[node.name] = [b.id for b in node.bases if isinstance(b, ast.Name)]
    resolved: dict[str, dict[str, str]] = {}

    def fields_of(name: str, seen: frozenset[str]) -> dict[str, str]:
        if name in resolved:
            return resolved[name]
        if name in seen or name not in own:
            return {}
        merged: dict[str, str] = {}
        for base in bases.get(name, []):
            merged.update(fields_of(base, seen | {name}))
        merged.update(own[name])
        resolved[name] = merged
        return merged

    return {name: fields_of(name, frozenset()) for name in own}


def _schema_modules(root: Path) -> list[Path]:
    """Every app's `schemas.py` — the canonical home rule 11 puts them in."""
    return [p for p in _py_files(root, "apps") if p.name == "schemas.py"]


def _org_models_by_app(root: Path) -> dict[str, set[str]]:
    """{app label: org-scoped model names it declares}, derived, never typed.

    The population is `org_scoped_model_names` — the same transitive walk rule 8
    and rule 24 use — located to the app whose `models.py` declares each one, so
    a schema is only ever asked about its own app's rows.
    """
    org_names = org_scoped_model_names(root)
    by_app: dict[str, set[str]] = {}
    for path in _model_files(root):
        tree = _parse(path)
        if tree is None:
            continue
        app = path.parent.name
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in org_names:
                by_app.setdefault(app, set()).add(node.name)
    return by_app


def org_scoped_out_schemas(root: Path, rule: dict) -> CheckResult:
    """Every `Out` schema of an `OrgScopedModel` declares `organization_id`.

    The invariant **one seam earlier** than rule 36 (P3 SEC-1's argument, built
    by SEC-R2). Rule 36 is an AST rule over push call sites, there is exactly one
    such site and it is generic — `group_for` can only ever read
    `event.organization_id` — so rule 36 structurally cannot see a payload that
    never carried the key. `events.services._subject_organization` derives the
    fan-out's narrowing from the subject's own `Out` schema, so a schema that
    omits `organization_id` produces an event that no branch owns, and the socket
    door reads that as *tenant-wide*: the row goes to every socket in the tenant.

    The population is derived, never listed: `OrgScopedModel` subclasses off the
    same transitive walk rule 8 uses, located to their app, paired with the
    `*Out` schemas in that app's `schemas.py` by the house naming convention
    (`_camel_suffix_pairs`). A hand-list would go stale the first time somebody
    adds a model, which is the failure class this house has a ledger for.
    """
    out = CheckResult()
    org_by_app = _org_models_by_app(root)
    for models in org_by_app.values():
        out.count("org_scoped_models", len(models))
    for path in _schema_modules(root):
        app = path.parent.name
        models = org_by_app.get(app)
        if not models:
            continue
        rel = str(path.relative_to(root))
        fields = _out_fields_with_inheritance(path)
        tree = _parse(path)
        lines = {}
        if tree is not None:
            lines = {
                node.name: node.lineno for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            }
        for schema, declared in sorted(fields.items()):
            stem = schema[: -len("Out")]
            paired = sorted(m for m in models if _camel_suffix_pairs(m, stem))
            if not paired:
                continue
            out.count("out_schemas_paired")
            if "organization_id" in declared:
                continue
            out.hit(
                rel,
                lines.get(schema, 1),
                f"{schema} is the read shape of {', '.join(paired)} — an OrgScopedModel — "
                "and does not declare `organization_id`. The socket fan-out narrows on that "
                "key and nothing else (`events.services._subject_organization`); a payload "
                "built from this shape carries no branch, and `bridge.group_for` reads "
                "no-branch as TENANT-WIDE. Declare `organization_id: UUID`, or rename the "
                "schema so it does not claim to be this model's read shape.",
            )
    return out


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )
    return proc.stdout


# Filled once per diff_checks() call, so a run costs one `git ls-files` rather
# than one per file — and so the self-test's plant/restore cycles never see a
# stale listing (the cache lives exactly as long as one diff pass).
_UNTRACKED_CACHE: dict[str, list[str]] = {}


def _untracked_files(root: Path) -> list[str]:
    key = str(root)
    if key not in _UNTRACKED_CACHE:
        lines = _git(root, "ls-files", "--others", "--exclude-standard").splitlines()
        _UNTRACKED_CACHE[key] = [ln.strip() for ln in lines if ln.strip()]
    return _UNTRACKED_CACHE[key]


def _changed_files(root: Path, ref: str) -> list[str]:
    """Tracked changes against ref, PLUS untracked non-ignored files.

    `git diff` cannot see a brand-new file that was never staged, and a new
    api.py is exactly the change these checks exist to judge.
    """
    lines = _git(root, "diff", "--name-only", ref).splitlines()
    changed = [ln.strip() for ln in lines if ln.strip()]
    return sorted(set(changed) | set(_untracked_files(root)))


def _added_lines(root: Path, ref: str, path: str) -> list[tuple[int, str]]:
    """(new-file line number, text) for every + line in the diff of one file.

    An untracked file is all additions.
    """
    target = root / path
    if path in _untracked_files(root):
        return list(enumerate(_read(target).splitlines(), start=1))
    out: list[tuple[int, str]] = []
    lineno = 0
    for raw in _git(root, "diff", "--unified=0", ref, "--", path).splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", raw)
        if m:
            lineno = int(m.group(1)) - 1
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            lineno += 1
            out.append((lineno, raw[1:]))
    return out


def _ref_source(root: Path, ref: str, path: str) -> str:
    return _git(root, "show", f"{ref}:{path}")


# The textual form, kept for exactly one case: a models.py that does not parse
# (a builder mid-edit). Falling back to it is stricter than skipping the file,
# and "the tree does not parse" is a state the diff layer must not read as clean.
_FIELD_TEXT_RE = r"=\s*models\.\w+Field\(|=\s*models\.(ForeignKey|OneToOneField|ManyToManyField)\("


def _field_declaration_lines(path: Path) -> set[int] | None:
    """Line numbers carrying a REAL model field declaration, or None if unparseable.

    Read off the AST rather than off the text, because `models.ForeignKey(...)`
    in a docstring is prose: the conventions in this repo are taught by example
    and the examples live in docstrings, so a rule that reads them as fields
    demands a migration for a paragraph. Only an assignment inside a class body
    whose value is a call to `models.<Something>` counts, and only the lines
    that assignment's own callee spans — the same lines the text form matched,
    so nothing that used to fire stops firing.
    """
    tree = _parse(path)
    if tree is None:
        return None
    lines: set[int] = set()
    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef):
            continue
        for stmt in cls.body:
            value: ast.expr | None = None
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                value = stmt.value
            if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)):
                continue
            root_of_call = _chain_root(value.func)
            if not (isinstance(root_of_call, ast.Name) and root_of_call.id == "models"):
                continue
            end = value.func.end_lineno or stmt.lineno
            lines.update(range(stmt.lineno, end + 1))
    return lines


def _out_fields(source: str) -> dict[str, dict[str, str]]:
    """{OutClassName: {field: annotation}} for every *Out schema in a module."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    found: dict[str, dict[str, str]] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name.endswith("Out")):
            continue
        fields: dict[str, str] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                fields[stmt.target.id] = ast.unparse(stmt.annotation)
        found[node.name] = fields
    return found


def _is_test_module(path: str) -> bool:
    """A module that only ever runs under pytest.

    `tests` anywhere in the path, or a `test_*.py` basename — the two shapes a
    test takes here (`apps/<x>/tests/test_api.py`, `apps/test_gate_liveness.py`).
    A test module is never a door and never declares the product's API version:
    `test_api.py` ends in `api.py`, which is how its escape came to be
    readable out of the test suite.
    """
    return "tests" in Path(path).parts or Path(path).name.startswith("test_")


def _is_route_module(path: str) -> bool:
    """Where routes live: `apps/<x>/api.py`, or a module of an `apps/<x>/api/`
    package — and never a test module ."""
    parts = Path(path).parts
    if _is_test_module(path) or len(parts) < 3 or parts[0] != "apps":
        return False
    return Path(path).name == "api.py" or (
        len(parts) > 3 and parts[2] == "api" and path.endswith(".py")
    )


# : The DECLARED escape from the breaking-change layer, written as a comment on a
# : line somebody typed on purpose: the version this change moves the contract to.
_API_VERSION_MARKER_RE = re.compile(r"#\s*api-version:\s*(\d+)\b")

# : The mount's own declaration of the version segment. `config/urls.py` owns it
# : (`API_PREFIX = "api/v1/"`); an app never writes it, which is exactly what
# : makes a v2 mount a change to ONE file the escape can be read off.
_URLS_MODULE = "config/urls.py"
_API_PREFIX_NAME = "API_PREFIX"
_API_PREFIX_VERSION_RE = re.compile(r"\bv(\d+)\b")


def _mounted_api_version(source: str) -> int | None:
    """The major API version `config/urls.py` mounts under, or None.

    Read by AST off the module-level `API_PREFIX` assignment rather than by
    scanning text, so a `v2` inside a docstring, a comment or a local name is
    not the mount saying anything.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == _API_PREFIX_NAME for t in stmt.targets):
            continue
        if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
            m = _API_PREFIX_VERSION_RE.search(stmt.value.value)
            if m:
                return int(m.group(1))
    return None


def _breaking_change_is_declared(root: Path, ref: str, changed: list[str]) -> bool:
    """Whether this change DECLARES that it is moving the API's version.

    Two declared forms, and no third:

      * **the mount moves** — `config/urls.py`'s `API_PREFIX` names a higher
        major version at the tip than it did at `ref`. That is what a version
        bump IS here, because `config/urls.py` owns the version segment and an
        app never writes it, so the honest form needs no comment at all; or
      * **a marker line** — `# api-version: <N>`, N above the version the mount
        carries, added to a door module or under `config/`. That is the shape a
        `v2` router beside `v1` takes before the whole mount moves, and it is a
        sentence a reviewer can disagree with rather than a token.

    IT USED TO BE A TOKEN SCAN . `version\\s*=\\s*["']2|/v2/|api/v2|_v2\\b|
    V2Router` over any path ending `api.py` — `tests/test_api.py` included, since
    that ends in `api.py` too — and any one of those substrings appearing on any
    added line disarmed the breaking-change layer of rules 3, 5, 13, 16 and 17
    for the whole commit. A draft local named `offered_v2` did exactly that, and
    the only reason anybody found out is that rule 17's canary died in the same
    run. An escape an ordinary identifier can trip is not an escape; it is a
    hole that happens to spell like a name.
    """
    was = _mounted_api_version(_ref_source(root, ref, _URLS_MODULE))
    now = _mounted_api_version(_read(root / _URLS_MODULE))
    if was is not None and now is not None and now > was:
        return True
    # The version the marker has to beat: what the mount carries today, so a
    # `# api-version: 2` left behind after the mount has moved to v2 declares
    # nothing and escapes nothing.
    floor = now if now is not None else 1
    for path in changed:
        if _is_test_module(path):
            continue
        if not (_is_route_module(path) or path.startswith("config/")):
            continue
        for _, text in _added_lines(root, ref, path):
            m = _API_VERSION_MARKER_RE.search(text)
            if m and int(m.group(1)) > floor:
                return True
    return False


def diff_checks(root: Path, ref: str, rules_by_id: dict[str, dict]) -> dict[str, CheckResult]:
    """The change-shaped checks, each attributed to its host rule.

    Run by pre-commit against HEAD and by the full gate against the merge-base
    when on a branch. Deterministic on (tree, ref) like everything else here.
    """
    _UNTRACKED_CACHE.pop(str(root), None)
    results: dict[str, CheckResult] = {
        rid: CheckResult() for rid in ("3", "5", "13", "16", "17", "22")
    }
    # Only the product tree is the diff layer's subject — a change to the
    # engine, the scripts or the docs is not an app change.
    changed = [p for p in _changed_files(root, ref) if p.startswith(("apps/", "config/"))]
    for rid in results:
        results[rid].targets_matched["changed_files"] = len(changed)

    # The v2 escape is DECLARED, never sniffed, and it is read from the door
    # layer only — a version bump lives on the mount or on a marker line in an
    # api.py, nowhere else, and never in a test module .
    v2_added = _breaking_change_is_declared(root, ref, changed)

    for path in changed:
        parts = Path(path).parts
        app = parts[1] if len(parts) > 1 and parts[0] == "apps" else None

        # rule 22 — a model change ships with its migration, in the same change.
        if app and Path(path).name == "models.py" and "tests" not in parts:
            declared = _field_declaration_lines(root / path)
            field_lines = [
                (n, t)
                for n, t in _added_lines(root, ref, path)
                if (n in declared if declared is not None else re.search(_FIELD_TEXT_RE, t))
            ]
            if field_lines and not any(p.startswith(f"apps/{app}/migrations/") for p in changed):
                results["22"].hit(
                    path,
                    field_lines[0][0],
                    f"a field change in {app}/models.py with no migration in the same change — "
                    "make the migration in the same change (makemigrations "
                    f"{app})",
                )

        # Where routes live, for the two change-shaped route rules below: the
        # flat `api.py`, or any module of an `api/` package ( — the same
        # blindness the AST half carried, and closed the same way, because a
        # change is judged by the rule the tree is judged by or the two layers
        # disagree about what a route is). A test module is not one of them
        # : `tests/test_api.py` ends in `api.py` and holds no route.
        is_route_module = app and _is_route_module(path)

        # rule 3 — a new route arrives with a test that names its url_name.
        if is_route_module:
            for lineno, text in _added_lines(root, ref, path):
                m = re.search(r'url_name\s*=\s*["\']([\w-]+)["\']', text)
                if not m:
                    continue
                url_name = m.group(1)
                tests_dir = root / "apps" / app / "tests"
                named = tests_dir.exists() and any(
                    url_name in _read(p) for p in sorted(tests_dir.rglob("*.py"))
                )
                if not named:
                    results["3"].hit(
                        path,
                        lineno,
                        f"new route {url_name!r} and no test in apps/{app}/tests names it — "
                        "an unproven door",
                    )

            # rule 5 — a new list route arrives with a query-budget pin.
            for lineno, text in _added_lines(root, ref, path):
                if "@paginate" not in text:
                    continue
                if not _app_is_pinned(root / "apps" / str(app)):
                    results["5"].hit(
                        path,
                        lineno,
                        f"a new paginated list route in apps/{app} and no query-budget test — "
                        "pin it with assert_num_queries at seeded scale",
                    )

        # rule 17 — a removed or re-typed field on an existing Out schema is a
        # breaking change; it blocks unless this same change adds a v2 router.
        if app and Path(path).name == "schemas.py":
            old = _out_fields(_ref_source(root, ref, path))
            new = _out_fields(_read(root / path))
            for cls, old_fields in old.items():
                if cls not in new:
                    if not v2_added:
                        results["17"].hit(
                            path,
                            1,
                            f"{cls} was removed — a breaking contract change is DECLARED: "
                            "move the mount (`API_PREFIX` in config/urls.py), or carry "
                            "`# api-version: <N>` on a line of this app's api.py",
                        )
                    continue
                for fname, ann in old_fields.items():
                    if fname not in new[cls]:
                        if not v2_added:
                            results["17"].hit(
                                path,
                                1,
                                f"{cls}.{fname} was removed from a published Out schema — "
                                "additive changes only; a breaking change is DECLARED: move "
                                "the mount (`API_PREFIX` in config/urls.py), or carry "
                                "`# api-version: <N>` on a line of this app's api.py",
                            )
                    elif new[cls][fname] != ann:
                        if not v2_added:
                            results["17"].hit(
                                path,
                                1,
                                f"{cls}.{fname} changed type ({ann} -> {new[cls][fname]}) on a "
                                "published Out schema — a breaking change is DECLARED: move "
                                "the mount (`API_PREFIX` in config/urls.py), or carry "
                                "`# api-version: <N>` on a line of this app's api.py",
                            )

        # rule 13 — a new tenant-owned service writes an audit row, which means
        # it takes tenant=; a new @service without one writes none.
        if app and Path(path).name == "services.py" and "tests" not in parts:
            added = _added_lines(root, ref, path)
            added_lines_set = {n for n, _ in added}
            tree = _parse(root / path)
            if tree is not None:
                for node in tree.body:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if node.lineno not in added_lines_set and not any(
                        node.lineno <= n <= (node.end_lineno or node.lineno)
                        and re.match(r"\s*def ", t)
                        for n, t in added
                    ):
                        continue
                    if "service" not in _decorator_names(node):
                        continue
                    if not any(a.arg == "tenant" for a in node.args.kwonlyargs):
                        results["13"].hit(
                            path,
                            node.lineno,
                            f"new service {node.name} takes no tenant= — @service writes its "
                            "audit row "
                            "only for tenant-owned writes; pass tenant, or carry # rule-13: "
                            "<reason>",
                        )

        # rule 16 — an event emitted in this change is declared in events.py.
        if app and Path(path).name in ("services.py", "activities.py") and "tests" not in parts:
            declared = ""
            events_py = root / "apps" / app / "events.py"
            if events_py.exists():
                declared = _read(events_py)
            for lineno, text in _added_lines(root, ref, path):
                m = re.search(r'(?:emit|_publish)\(\s*(?:name\s*=\s*)?["\']([\w.]+)["\']', text)
                if m and m.group(1) not in declared:
                    results["16"].hit(
                        path,
                        lineno,
                        f"emits {m.group(1)!r} but apps/{app}/events.py does not declare it — "
                        "an event name is a published contract, declared once, never a literal",
                    )
    return results


# --- rule 40: a header is read by its declared name ----------------------------
#
# Three populations, one rule, because they are three views of one contract —
# "the spelling of a header lives in exactly one place":
#
# A. INBOUND READS. `request.headers.get(<arg>)` / `request.headers[<arg>]`,
# `request.META[<HTTP_*>]`, and the ASGI `scope["headers"]` loop (the
# socket and MCP doors, which have no `request`). The read is legal when
# `<arg>` is — or is derived from — a module-level header DECLARATION.
# B. THE DECLARATION POPULATION. Module-level assignments named `HEADER` or
# `*_HEADER` whose value is a string literal. Derived by the same walk,
# never listed: a new constant is in scope with no edit here.
# C. `Remedy(label, "header:<name>")`. A refusal that politely points at a
# header nobody reads is a dead end, so the name after `header:` must be
# some declaration's VALUE; and every destination's KIND must be one the
# `Remedy` docstring in `apps/core/exceptions.py` enumerates — read from
# that docstring, never re-typed here, so a sixth kind added there is
# seen with no edit to this file.
#
# Plus the CORS census (N100b-3): every declaration read by an HTTP request
# reader must appear, lowercased, in `CORS_ALLOW_HEADERS`. A header the API
# reads and a browser may not send is a door that is open on the server and
# shut in the client, which is exactly how `X-Org` was unreachable from a
# cross-origin front end for a cycle with no error anywhere.

# : The receivers whose `.headers` is an INBOUND request's. A `response.headers`
# : read is somebody else's contract (`Retry-After`, `Content-Type` off a
# : third-party reply) and is declared in `does_not_cover`, not scanned.
_REQUEST_RECEIVERS = {"request", "req"}

_CORS_SETTINGS_FILE = "config/settings/base.py"
_CORS_SETTING = "CORS_ALLOW_HEADERS"
_REMEDY_KIND_SOURCE = "apps/core/exceptions.py"
_REMEDY_DESTINATION_RE = re.compile(r"`([a-z]+):([A-Za-z0-9_.-]+)`")


def _is_header_constant_name(name: str) -> bool:
    """The declaration grammar: `HEADER`, or anything ending `_HEADER`.

    `apps/core/idempotency.py` names its own `HEADER` because the module IS the
    subject; every other declaration qualifies the noun. Both are declarations.
    """
    return name == "HEADER" or name.endswith("_HEADER")


def header_declarations(root: Path) -> dict[str, list[tuple[str, int, str]]]:
    """name -> [(file, line, value)] for every module-level header declaration.

    DERIVED by the same walk that finds the reads, so a constant added anywhere
    under `apps/` or `config/` is in the population with no edit to this file
    and no hand-list to go stale.
    """
    found: dict[str, list[tuple[str, int, str]]] = {}
    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        for node in tree.body:
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = list(node.targets), node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None or not isinstance(value, ast.Constant):
                continue
            if not isinstance(value.value, str):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and _is_header_constant_name(target.id):
                    found.setdefault(target.id, []).append((rel, node.lineno, value.value))
    return found


def _literal_root(node: ast.expr) -> str | None:
    """The str/bytes literal this expression is built from, if it is built from one.

    `"X-Tenant"`, `b"x-org"` and `"authorization".encode()` all answer; a name
    does not. This is what tells a spelled-out header name from a named one.
    """
    current = node
    while isinstance(current, ast.Call):
        current = current.func
    while isinstance(current, ast.Attribute):
        current = current.value
        while isinstance(current, ast.Call):
            current = current.func
    if isinstance(current, ast.Constant) and isinstance(current.value, (str, bytes)):
        return (
            current.value
            if isinstance(current.value, str)
            else current.value.decode("latin-1", "replace")
        )
    return None


def _name_root(node: ast.expr) -> str | None:
    """The bare name this expression is rooted at — `TENANT_HEADER.lower().encode()`
    is rooted at `TENANT_HEADER`, which is the whole point of allowing a chain."""
    current = node
    while True:
        if isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Attribute):
            current = current.value
        else:
            break
    return current.id if isinstance(current, ast.Name) else None


def _scope_header_loops(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.For]:
    """The `for key, value in scope["headers"]` loops in this function.

    The structural test for "this is an ASGI header lookup": a loop over a
    `headers` collection taken off a `scope`. It is deliberately the LOOP and
    not the function's text — `scheme.lower() != "bearer"` beside a
    `request.headers.get(...)` is not a header name, and a text test read it as
    one while this was being built.
    """
    out: list[ast.For] = []
    for node in ast.walk(fn):
        if isinstance(node, (ast.For, ast.AsyncFor)):
            source = ast.dump(node.iter)
            if "'headers'" in source and "scope" in source:
                out.append(node)  # type: ignore[arg-type]
    return out


def _scope_header_helpers(tree: ast.Module) -> dict[str, int]:
    """`name -> parameter index` for every function that IS an ASGI header lookup.

    Derived, not named: a function qualifies when it walks `scope[...]`/
    `scope.get("headers"...)` and compares the key against something rooted in
    one of its own PARAMETERS. That parameter is the header name, so every call
    to the function is a read and its argument at that index is `<arg>`.

    A function whose loop compares against a LITERAL is not a helper — it is a
    read, spelled inline, and `_header_reads` reports it where it stands.
    """
    helpers: dict[str, int] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not _scope_header_loops(node):
            continue
        params = [a.arg for a in _all_args(node)]
        # One hop of local rebinding, because that is how all three of these
        # helpers are written: `wanted = name.lower().encode()`, and then the
        # loop compares against `wanted`. Chasing exactly one hop keeps the
        # walk honest about what it can see (declared in does_not_cover).
        local_root: dict[str, str] = {}
        for assign in ast.walk(node):
            if not isinstance(assign, ast.Assign) or len(assign.targets) != 1:
                continue
            target = assign.targets[0]
            root = _name_root(assign.value)
            if isinstance(target, ast.Name) and root is not None:
                local_root[target.id] = root
        for compare in ast.walk(node):
            if not isinstance(compare, ast.Compare):
                continue
            for side in [compare.left, *compare.comparators]:
                root = _name_root(side)
                root = local_root.get(root or "", root)
                if root is not None and root in params and root != "scope":
                    helpers[node.name] = params.index(root)
                    break
    return helpers


def _header_reads(tree: ast.Module) -> list[tuple[int, ast.expr, str]]:
    """(line, the header-name expression, what kind of read it is) for one module."""
    reads: list[tuple[int, ast.expr, str]] = []
    helpers = _scope_header_helpers(tree)
    for node in ast.walk(tree):
        # `request.headers.get(name)` / `request.META.get("HTTP_X")`
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            func = node.func
            if func.attr in {"get", "__getitem__"} and isinstance(func.value, ast.Attribute):
                owner = func.value
                if owner.attr in {"headers", "META"} and node.args:
                    root = _name_root(owner.value)
                    if root in _REQUEST_RECEIVERS:
                        reads.append((node.lineno, node.args[0], "request"))
            if func.attr in helpers:
                index = helpers[func.attr]
                if len(node.args) > index:
                    reads.append((node.lineno, node.args[index], "scope"))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in helpers:
                index = helpers[node.func.id]
                if len(node.args) > index:
                    reads.append((node.lineno, node.args[index], "scope"))
        # `request.headers[name]` / `request.META["HTTP_X"]`
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute):
            owner = node.value
            if owner.attr in {"headers", "META"}:
                root = _name_root(owner.value)
                if root in _REQUEST_RECEIVERS and isinstance(node.ctx, ast.Load):
                    reads.append((node.lineno, node.slice, "request"))
    # The loop itself: inside a function that walks an ASGI `scope`'s headers,
    # a comparison against a spelled-out name IS the read — there is no
    # `request` there to hang it off, which is precisely why the socket and MCP
    # doors are where a second spelling hides.
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for loop in _scope_header_loops(node):
            for compare in ast.walk(loop):
                if not isinstance(compare, ast.Compare):
                    continue
                for side in [compare.left, *compare.comparators]:
                    if _literal_root(side) is not None:
                        reads.append((compare.lineno, side, "scope-loop"))
    return reads


def _imported_modules(tree: ast.Module) -> dict[str, str]:
    """`local name -> the module file it was imported from`, for `from X import Y`.

    Two apps legitimately declare a `TENANT_HEADER`: the HTTP one (`X-Tenant`)
    and Temporal's (`djb-tenant-id`). Which VALUE a read names is therefore the
    import's business, not the name's, and the census below would otherwise
    demand a Temporal header in the browser's CORS list.
    """
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            where = node.module.replace(".", "/") + ".py"
            for alias in node.names:
                out[alias.asname or alias.name] = where
    return out


def _declared_values(
    declarations: dict[str, list[tuple[str, int, str]]],
    name: str,
    *,
    here: str,
    imports: dict[str, str],
) -> list[str]:
    """The value(s) this name means AT THIS READ — same module, then the import."""
    entries = declarations.get(name) or []
    if len(entries) <= 1:
        return [value for _, _, value in entries]
    same = [value for file, _, value in entries if file == here]
    if same:
        return same
    source = imports.get(name)
    if source:
        via = [value for file, _, value in entries if file == source]
        if via:
            return via
    return [value for _, _, value in entries]


def _remedy_kinds(root: Path) -> set[str]:
    """The destination kinds, read off `Remedy`'s own docstring in core.exceptions.

    The kinds are the template's published contract and they are enumerated in
    exactly one place — the class docstring that explains what a destination is.
    Reading them from there rather than re-typing them here is what makes a
    sixth kind a one-file change: add it to the docstring beside the others and
    this rule accepts it, with no edit to `quality/`.
    """
    tree = _parse(root / _REMEDY_KIND_SOURCE)
    if tree is None:
        return set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Remedy":
            doc = ast.get_docstring(node) or ""
            return {m.group(1) for m in _REMEDY_DESTINATION_RE.finditer(doc)}
    return set()


def _remedy_destinations(tree: ast.Module) -> list[tuple[int, str]]:
    """(line, destination) for every `Remedy(...)` whose destination is a literal."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name is None and isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name != "Remedy":
            continue
        candidate: ast.expr | None = None
        if len(node.args) >= 2:
            candidate = node.args[1]
        for keyword in node.keywords:
            if keyword.arg == "destination":
                candidate = keyword.value
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            out.append((node.lineno, candidate.value))
    return out


def _cors_allowed(root: Path) -> list[str] | None:
    """`CORS_ALLOW_HEADERS` as the settings file declares it, read by AST.

    By AST and not by importing settings, for the reason the settings file
    itself gives: settings are read before the app registry is ready, so the
    census cannot travel as an import in either direction. The LAST module-level
    assignment wins, so a canary appended to the file is what the check sees.
    """
    tree = _parse(root / _CORS_SETTINGS_FILE)
    if tree is None:
        return None
    found: list[str] | None = None
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id == _CORS_SETTING:
                try:
                    value = ast.literal_eval(node.value)  # type: ignore[arg-type]
                except (ValueError, TypeError, SyntaxError):
                    return None
                if isinstance(value, (list, tuple)):
                    found = [str(v) for v in value]
    return found


def header_contracts(root: Path, rule: dict) -> CheckResult:
    """Rule 40. A header is read by its declared name, and a remedy names one.

    Three clauses over three derived populations (the reads, the declarations,
    the remedies) plus the CORS census. Every one of them is a walk, so the
    populations grow with the tree and nothing here is a list somebody has to
    remember to extend.
    """
    out = CheckResult()
    declarations = header_declarations(root)
    values = {value for entries in declarations.values() for _, _, value in entries}
    out.count("header_declarations", len(declarations))

    allowed_literals = {
        str(entry) for entry in (rule.get("scope") or {}).get("standard_http_headers") or []
    }
    kinds = _remedy_kinds(root)
    if not kinds:
        out.hit(
            _REMEDY_KIND_SOURCE,
            0,
            "the Remedy docstring no longer enumerates its destination kinds, so this rule "
            "has nothing to validate a destination's kind against — the kind set is the "
            "contract and it is declared there, once (ADR core-5)",
        )
    out.count("remedy_kinds", len(kinds))

    read_values: set[str] = set()
    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        spans = _enclosing_functions(tree)
        imports = _imported_modules(tree)
        for line, arg, kind in _header_reads(tree):
            out.count("header_reads", 1)
            if _exempt(rule, rel, _function_at(spans, line)):
                continue
            named = _name_root(arg)
            if named is not None and named in declarations:
                if kind == "request":
                    # The CORS census population: what an HTTP door reads. The
                    # socket and MCP doors are not preflighted and are not in it.
                    read_values.update(
                        _declared_values(declarations, named, here=rel, imports=imports)
                    )
                continue
            literal = _literal_root(arg)
            if literal is None:
                # A name that is not a declaration and not a literal: threaded
                # through a parameter, or built at runtime. Declared blind spot.
                out.count("header_reads_unresolved", 1)
                continue
            if literal in allowed_literals:
                continue
            match = sorted(
                name
                for name, entries in declarations.items()
                if any(value.lower() == literal.lower() for _, _, value in entries)
            )
            suggestion = (
                " — " + " / ".join(f"`{m}`" for m in match) + " already declares this "
                "exact spelling; name it"
                if match
                else " — declare it once as a module-level `*_HEADER` constant and read that"
            )
            out.hit(
                rel,
                line,
                f"the {kind} header read names {literal!r} as a literal rather than a "
                f"declared constant{suggestion}. A second spelling of a header is a "
                "fail-open the compiler cannot see: the read simply finds nothing, and "
                "the request is answered as though the caller had asked for nothing",
                root=root,
                klass=kind,
            )

        for line, destination in _remedy_destinations(tree):
            out.count("remedy_destinations", 1)
            kind, _, name = destination.partition(":")
            if kinds and kind not in kinds:
                out.hit(
                    rel,
                    line,
                    f"Remedy destination {destination!r} uses kind {kind!r}, which the "
                    f"Remedy docstring does not enumerate ({', '.join(sorted(kinds))}) — a "
                    "destination a renderer cannot classify is a button with nowhere to go. "
                    f"Add the kind beside the others in {_REMEDY_KIND_SOURCE}, or use one",
                    root=root,
                )
                continue
            if kind != "header":
                continue
            out.count("header_remedies", 1)
            if name in values or name in allowed_literals:
                continue
            out.hit(
                rel,
                line,
                f"Remedy destination {destination!r} names a header no declaration in this "
                "tree spells — the refusal politely points the caller at a header the "
                "server does not read. Name a declared constant's value",
                root=root,
            )

    # --- the CORS census (N100b-3): a list, derived, not a copy ----------------
    allowed = _cors_allowed(root)
    if allowed is None:
        out.hit(
            _CORS_SETTINGS_FILE,
            0,
            f"{_CORS_SETTING} could not be read as a literal tuple, so the census that "
            "keeps the browser's allow-list in step with the headers this API reads is "
            "enforcing nothing",
        )
    else:
        lowered = {entry.lower() for entry in allowed}
        out.count("cors_census_headers", len(read_values))
        for value in sorted(read_values):
            if value.lower() in lowered:
                continue
            out.hit(
                _CORS_SETTINGS_FILE,
                0,
                f"{_CORS_SETTING} does not list {value.lower()!r}, and an HTTP door reads "
                f"the header {value!r} — a cross-origin browser client cannot send it at "
                "all, so every one of its requests is answered as though it had not, with "
                "no error anywhere (the hat nobody could put on)",
            )
    return out


# --- floor proxies for the Django-check rules -----------------------------------
#
# The system checks (rules 2, 3, 11, 13-half, 15, 17, 21) run inside Django and
# report violations, not counts — so their UNBOUND guard is an AST-side proxy:
# a cheap count of the same subject, floored in rules.yaml. A registry that
# somehow resolved to nothing would trip the proxy here even though the check
# itself printed a clean nothing.


def count_model_classes(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    files = _py_files(root, "apps", named={"models.py"}) + [
        root / "apps/core/audit.py",
        root / "apps/core/idempotency.py",
    ]
    for path in files:
        tree = _parse(path) if path.exists() else None
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.bases:
                out.count("model_classes")
    return out


def count_routes(root: Path, rule: dict) -> CheckResult:
    """Rules 3 and 17's floor: how many routes there are to be judged.

    , 2026-08-24 — (a)'s twin, found while closing it and booked rather
    than swept in. This walked `api.py` by BASENAME and so read 69 where the
    live ninja registry has 86: `apps/core/api/routes.py`'s seventeen routes
    were outside the floor of both rules that use this proxy. Nothing was
    unenforced (djb.E003/E030/E031 and djb.E017 all read the live registry),
    but a floor five below the truth cannot notice its subject shrinking, which
    is the whole job of a floor. `api_modules()` is the same population
    `config/api.py` mounts, and the same one rules 5 and 41 walk — one
    function, so the four rules cannot come to disagree about what an API
    module is.
    """
    out = CheckResult()
    for path in [module for app in _app_dirs(root) for module in api_modules(app)]:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute) and target.attr in (
                    "get",
                    "post",
                    "patch",
                    "put",
                    "delete",
                ):
                    out.count("routes")
    return out


# --- rule 42: every service is reachable through a door -----------------------
#
# P5 WA-1 commit 2. The owner's ruling: "mechanisms without doors is a miss in
# the development standard". The template grew a foundation — organizations,
# memberships, invitations, tenant settings, erasure, webhook endpoints, the run
# ledger — and none of it was reachable by anybody who was not holding a shell.
# A mechanism nobody can call is indistinguishable from a mechanism that was
# never built, except that it costs the same to maintain.
#
# THE QUESTION IS CLOSED, which is what makes it a rule and not a review: the
# population is every `@service` in the tree (rule 13 already guarantees that
# every write is one), and the answer is whether a DOOR module calls it by name.
# Door modules are the conventional ones the mounts already discover — api.py,
# mcp.py, consumers.py, activities.py, receivers.py and the shell's
# management/commands/** — so "what is a door" is not this rule's opinion.
#
# REACHABILITY IS DIRECT, DELIBERATELY. A service called only by another service
# is counted doorless, because that is exactly the finding: `create_organization`
# reached through `bootstrap_tenant` still has no door of its own, and the wave
# that gives the foundation doors is measured by this number falling. The valve
# for a service that genuinely should not have one — `emit()`, an operator act —
# is `# door: <reason>`, counted and printed like every other valve in this
# engine.

_DOOR_RE = re.compile(r"#\s*door\b:?\s*(.*)$")
_MIN_DOOR_REASON = 12

# : The conventional door modules — the same names the mounts discover. A door
# : mounted some other way is invisible here, and that is in `does_not_cover`.
DOOR_GLOBS = (
    "apps/*/api.py",
    "apps/*/api/*.py",
    "apps/*/mcp.py",
    "apps/*/consumers.py",
    "apps/*/activities.py",
    "apps/*/receivers.py",
    "apps/*/management/commands/*.py",
)


def _door_reason(lines: list[str], line: int) -> str | None:
    """The reason a `# door:` marker claims at this line, or None.

    On the line itself or in the contiguous comment block above it — the same
    grammar as `# reach:` and `# rule-<id>:`, so there is one shape to learn.
    """
    if not lines or line < 1 or line > len(lines):
        return None
    m = _DOOR_RE.search(lines[line - 1])
    if m:
        return m.group(1).strip()
    i = line - 2
    while i >= 0 and lines[i].strip().startswith("#"):
        m = _DOOR_RE.search(lines[i])
        if m:
            return m.group(1).strip()
        i -= 1
    return None


def _door_modules(root: Path) -> list[Path]:
    seen: dict[str, Path] = {}
    for pattern in DOOR_GLOBS:
        for path in sorted(root.glob(pattern)):
            parts = set(path.parts)
            if parts & SKIP_PARTS or not path.is_file():
                continue
            seen[path.as_posix()] = path
    return [seen[key] for key in sorted(seen)]


# : The module a call could not be resolved to. `("*", name)` is the declared
# : valve: a call through a registry, a `getattr`, `self`, a parameter or a
# : local variable has no import to resolve, and rule 42 counts it by bare name
# : exactly as the whole check used to. `does_not_cover` names that valve.
UNRESOLVED = "*"


def _dotted(root: Path, path: Path) -> str:
    """The import path a module in this tree would be imported by."""
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _is_first_party_module(root: Path, dotted: str) -> bool:
    """Whether this dotted name is a module IN THIS TREE (a file or a package)."""
    if not dotted:
        return False
    base = root.joinpath(*dotted.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def _import_maps(root: Path, tree: ast.Module, here: str) -> tuple[dict[str, str], dict[str, str]]:
    """(module_alias -> dotted module, symbol_alias -> dotted owning module).

    ONE LEVEL of resolution, which is all the shape needs and all an AST
    can honestly claim: what a name in THIS module was bound to by an import
    statement in THIS module. `from apps.accounts import zitadel` binds a
    module; `from apps.accounts.services import deactivate_user` binds a
    symbol and records which module owns it. A relative import is resolved
    against `here`, the door module's own dotted path.
    """
    modules: dict[str, str] = {}
    symbols: dict[str, str] = {}
    package = here.rsplit(".", 1)[0] if "." in here else ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".") if package else []
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                origin = ".".join([*base, node.module]) if node.module else ".".join(base)
            else:
                origin = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                candidate = f"{origin}.{alias.name}" if origin else alias.name
                if _is_first_party_module(root, candidate):
                    modules[bound] = candidate
                else:
                    # Either a symbol from a first-party module, or anything at
                    # all from a third-party one. Both resolve to a module that
                    # is not a first-party `services.py`, which is the only
                    # question this census asks.
                    symbols[bound] = origin
    return modules, symbols


def _flatten(node: ast.expr) -> list[str] | None:
    """`a.b.c` -> ["a", "b", "c"]; anything not a pure name chain -> None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return list(reversed(parts))


def _called_qualnames(root: Path, tree: ast.Module, here: str) -> set[tuple[str, str]]:
    """Every call this module makes, as (owning module, name).

    , 2026-08-24 — the recorded live false pass. `apps/accounts/activities.py`
    calls `zitadel.deactivate_user(...)`, a DIFFERENT function that happens to
    share a name with the doorless service `accounts.services.deactivate_user`,
    and the bare-name census read the service as reached. The census now
    resolves the called name to the module it was imported from, so
    `("apps.accounts.zitadel", "deactivate_user")` no longer answers for
    `("apps.accounts.services", "deactivate_user")`.

    Where an import cannot answer — `self.x()`, `handler()` bound at runtime, a
    registry lookup — the pair is `(UNRESOLVED, name)` and matches by bare name
    as before. That is the declared valve, not an oversight: a census that
    called every unresolvable name doorless would invent findings out of its
    own blind spot.
    """
    modules, symbols = _import_maps(root, tree, here)
    local = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    return _resolved_calls(tree, here=here, modules=modules, symbols=symbols, local=local)


def _resolved_calls(
    node: ast.AST,
    *,
    here: str,
    modules: dict[str, str],
    symbols: dict[str, str],
    local: set[str],
) -> set[tuple[str, str]]:
    """The resolution itself, over any subtree.

    Split out of `_called_qualnames` so a rule that asks "what does THIS
    FUNCTION call" (rule 41's clause) and a rule that asks "what does this
    MODULE call" (rule 42) share one resolver. Two copies of a resolution is the
    shape this engine refuses everywhere else; it would be odd here.
    """
    out: set[tuple[str, str]] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            if func.id in symbols:
                out.add((symbols[func.id], func.id))
            elif func.id in local:
                out.add((here, func.id))  # defined right here; no service is
            else:
                out.add((UNRESOLVED, func.id))
            continue
        if not isinstance(func, ast.Attribute):
            continue
        chain = _flatten(func)
        if chain is None:
            out.add((UNRESOLVED, func.attr))
            continue
        head, middle, name = chain[0], chain[1:-1], chain[-1]
        if head in modules:
            out.add((".".join([modules[head], *middle]), name))
        elif head in symbols:
            out.add((".".join([symbols[head], head, *middle]), name))
        else:
            out.add((UNRESOLVED, name))
    return out


def door_reachability(root: Path, rule: dict) -> CheckResult:
    """Rule 42. Findings are classed by APP, so one app's backlog cannot pay for
    another app's growth — the per-app numbers in the census report and the
    per-app ratchets in `rules.yaml` are the same numbers."""
    out = CheckResult()
    out.targets_matched["door_overrides"] = 0
    out.targets_matched["reachable_services"] = 0
    reached: set[tuple[str, str]] = set()
    for path in _door_modules(root):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("door_modules")
        reached |= _called_qualnames(root, tree, _dotted(root, path))
    unresolved = {name for module, name in reached if module == UNRESOLVED}
    # The residual false-pass surface, printed on the rule's status line beside
    # `door_overrides` because it is the same kind of thing: a service counted
    # reachable ONLY because a call somewhere could not be resolved to a
    # module. It measured 0 on the tree that landed the resolution, so
    # every reachable service today is reachable by a qualified name.
    out.targets_matched["reached_by_bare_name"] = 0
    for path in _py_files(root, "apps", named={"services.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("service_files")
        rel = path.relative_to(root).as_posix()
        app = path.parent.name
        here = _dotted(root, path)
        lines = _read(path).splitlines()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "service" not in _decorator_names(node):
                continue
            out.count("services_censused")
            if (here, node.name) in reached:
                out.count("reachable_services")
                continue
            if node.name in unresolved:
                out.count("reachable_services")
                out.count("reached_by_bare_name")
                continue
            top = min([d.lineno for d in node.decorator_list] or [node.lineno])
            reason = _door_reason(lines, node.lineno) or _door_reason(lines, top)
            if reason is not None:
                if len(reason) >= _MIN_DOOR_REASON:
                    out.count("door_overrides")
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"`# door:` with no reason on {node.name} — an escape hatch nobody has "
                    "to justify is an off switch; write the sentence a reviewer can "
                    "disagree with",
                    klass=app,
                )
                continue
            out.hit(
                rel,
                node.lineno,
                f"{node.name} is not called from any door — no route, tool, consumer, "
                "activity, receiver or management command reaches it, so nobody outside "
                "this tree can. Give it a door, or record `# door: <reason>` saying why it "
                "is deliberately unreachable (house rule 42)",
                klass=app,
            )
    return out


def count_contract_surface(root: Path, rule: dict) -> CheckResult:
    """Rule 41's floors: how much contract surface there is to be documented.

    Four populations rather than one, because rule 41 has four subjects and a
    single count would let three of them collapse to nothing while the fourth
    kept the floor satisfied — routes, the docstrings that document them, the
    tag declarations that name their groups, and the machine-door twins that
    have to render the same words.

    (a), 2026-08-24: the walk is `api_modules()` — the SAME population
    `config/api.py` mounts and the same one rule 5 was widened to in —
    rather than `api.py` by basename. An app whose routes have outgrown one
    file was outside all four counts, so `apps/core/api/routes.py` contributed
    nothing: TAG-1 moved core's `TAGS` from one entry to two and the floor
    counter read 8 either way, which is a floor that would not notice core's
    tags vanishing altogether. The counts are the tree's, measured in
    quality/contract-standard-measurement.md, and the floors below them are
    pinned AT the measurement (rules.yaml, rule 41) so a contraction is a
    number a human re-commits rather than a silence.
    """
    out = CheckResult()
    for path in [module for app in _app_dirs(root) for module in api_modules(app)]:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
                names = {t.id for t in node.targets if isinstance(t, ast.Name)}
                if "TAGS" in names:
                    out.count("tag_declarations", len(node.value.keys))
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute) and target.attr in (
                    "get",
                    "post",
                    "patch",
                    "put",
                    "delete",
                ):
                    out.count("documented_routes")
                    if ast.get_docstring(node):
                        out.count("contract_docstrings")
    for path in _py_files(root, "apps", named={"mcp.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "tool":
                out.count("twin_tools")
    return out


def count_mount_surface(root: Path, rule: dict) -> CheckResult:
    """Rule 32's floors: how much URL surface there is for a label to leak onto.

    Two populations, because rule 32 joins two and a single count would let
    either collapse while the other kept the floor satisfied — the api modules
    that expose a `router` (each one a `PREFIX` decision) and the app labels
    those prefixes could collide with. If discovery ever finds no api module,
    or the app registry no app, the census would pass by having nothing to
    census, and this is what says so instead.
    """
    out = CheckResult()
    out.targets_matched["app_labels"] = len(_app_dirs(root))
    for path in [*_py_files(root, "apps", named={"api.py"}), *root.glob("apps/*/api/*.py")]:
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "router" for t in node.targets
            ):
                out.count("mounted_routers")
                break
    return out


def count_apps(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    out.targets_matched["apps"] = len(_app_dirs(root))
    return out


def count_admin_classes(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path in _py_files(root, "apps", named={"admin.py"}):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.bases:
                out.count("admin_classes")
    return out


FLOOR_PROXIES = {
    "count_model_classes": count_model_classes,
    "count_routes": count_routes,
    "count_contract_surface": count_contract_surface,
    "count_mount_surface": count_mount_surface,
    "count_apps": count_apps,
    "count_admin_classes": count_admin_classes,
}


# --- registry ------------------------------------------------------------------

# --- rule 41's clause: the refusal block against the raise sites ---------
#
# P5 QB-R2, and it is a CLAUSE ON RULE 41 rather than a rule 44 because it
# closes rule 41's own declared gap — "THE REFUSAL ENUMERATION IS A SUPERSET
# where a route did not narrow it ... WHETHER A DOCUMENTED CODE CAN ACTUALLY BE
# RAISED THERE is nobody's check today" (declared). A rule and its
# blind spot are born together; a blind spot closed somewhere else is a second
# rule about one subject, and the two drift.
#
# WHAT IT COMPARES. For each route: the codes the document publishes against the
# codes something it can actually reach RAISES, one level deep — the route body
# plus every function it calls that this tree can resolve, using QB-R1's
# qualified-name resolution . Class to code comes off the class's own
# `code = "..."`, which is the same declaration `register_refusal` is checked
# against, so the mapping is the registry's and not this rule's.
#
# TWO DIRECTIONS, AND THE VOCABULARY IS WHAT KEEPS THEM HONEST:
#
# * UNDERCLAIM — something reachable raises a code the block does not carry.
# On a `@refuses(...)` route the block is exact, so any such code fires. On
# an UNNARROWED route the block is the door-shape superset, and this clause
# can only speak about codes that superset can never contain — the
# vocabulary is read off `derived_refusals` in `apps/core/api/docs.py`, so
# a tenth shape-code added there is understood here with no edit.
# * OVERCLAIM — a `@refuses(...)` code outside that vocabulary that nothing
# reachable raises. A door-shape code is raised by the door machinery and
# not by anything this walk can see, which is why the vocabulary is
# excluded from this direction rather than counted as unreachable.
#
# AND ONE SUPPRESSION, WHICH IS THE POINT OF THE `unresolved` COUNT: a route
# with a callee this walk could not resolve — a registry dispatch, a `getattr`,
# a handler bound at runtime — cannot be shown to be overclaiming, because the
# thing that would raise the code is exactly the thing that could not be read.
# The route is counted and left alone. Silence there is the honest answer.

# : `derived_refusals` is where a route's shape becomes a list of codes. Its
# : vocabulary is read, never re-typed: a second copy of that list here would be
# : the drift house rule 41 exists to refuse, one layer down.
_DERIVATION_SOURCE = "apps/core/api/docs.py"
_DERIVATION_FUNCTION = "derived_refusals"


def _door_shape_vocabulary(root: Path) -> set[str]:
    """Every code the door-shape derivation can produce, off its own body."""
    tree = _parse(root / _DERIVATION_SOURCE)
    if tree is None:
        return set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != _DERIVATION_FUNCTION:
            continue
        # Only what is put INTO the code list. Walking every string in the
        # function would collect its docstring and its method names, which is
        # how a vocabulary read stops being a vocabulary.
        found: set[str] = set()
        for child in ast.walk(node):
            if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
                continue
            if child.func.attr not in ("append", "extend"):
                continue
            owner = child.func.value
            if not (isinstance(owner, ast.Name) and owner.id == "codes"):
                continue
            for argument in child.args:
                for leaf in ast.walk(argument):
                    if isinstance(leaf, ast.Constant) and isinstance(leaf.value, str):
                        found.add(leaf.value)
        return found
    return set()


def _refusal_codes_by_class(root: Path) -> dict[str, str]:
    """{class name: code} for every refusal class that declares one.

    Read off `code = "..."` in the class body — the same declaration
    `register_refusal` is checked against by `DomainError.__init_subclass__`, so
    this mapping is the registry's and never a second list.
    """
    out: dict[str, str] = {}
    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for statement in node.body:
                if not isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = (
                    statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                )
                if not any(isinstance(t, ast.Name) and t.id == "code" for t in targets):
                    continue
                value = statement.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    out[node.name] = value.value
    return out


def _raised_codes(node: ast.AST, codes_by_class: dict[str, str]) -> set[str]:
    """Every registered code a `raise` inside this subtree can produce.

    A `raise HttpError(400, ...)` names no code and is skipped — the door's own
    vocabulary, which rule 14 already governs and which this clause declares.
    """
    found: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Raise) or child.exc is None:
            continue
        target = child.exc.func if isinstance(child.exc, ast.Call) else child.exc
        name = None
        if isinstance(target, ast.Name):
            name = target.id
        elif isinstance(target, ast.Attribute):
            name = target.attr
        if name and name in codes_by_class:
            found.add(codes_by_class[name])
    return found


def _function_in(root: Path, dotted: str, name: str) -> ast.AST | None:
    """The body of a first-party function named by a resolved call, or None."""
    if not (dotted.startswith("apps.") or dotted.startswith("config.")):
        return None
    base = root.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if not candidate.is_file():
            continue
        tree = _parse(candidate)
        if tree is None:
            return None
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                return node
        return None
    return None


def _route_decorators(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[bool, tuple[str, ...] | None]:
    """(is a route, the `@refuses(...)` codes or None for an unnarrowed one)."""
    is_route = False
    declared: tuple[str, ...] | None = None
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr in (
            "get",
            "post",
            "patch",
            "put",
            "delete",
        ):
            is_route = True
        name = None
        if isinstance(target, ast.Name):
            name = target.id
        elif isinstance(target, ast.Attribute):
            name = target.attr
        if name == "refuses" and isinstance(dec, ast.Call):
            declared = tuple(
                arg.value
                for arg in dec.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            )
    return is_route, declared


def _dispatches_opaquely(
    node: ast.AST,
    *,
    modules: dict[str, str],
    symbols: dict[str, str],
    local: set[str],
) -> bool:
    """Whether this route reaches a callee no walk can read.

    Two shapes, and deliberately only two: a `getattr(...)` call, and a bare
    name called that is neither defined here, nor imported, nor a builtin — a
    handler pulled out of a registry or bound at runtime. A METHOD call on an
    object (`queryset.filter(...)`, `request.headers.get(...)`) is not dispatch
    to a service and is not counted, which matters: counting it would make every
    route in the tree opaque and the overclaim direction would never speak.
    """
    import builtins

    known = set(dir(builtins))
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name):
            if func.id == "getattr":
                return True
            if func.id not in local and func.id not in symbols and func.id not in known:
                return True
    return False


# --- rule 41's role-promise clause ------------------------------------
#
# , and the OWNER'S QUESTION is what makes it a rule: "is there a
# correctness pattern we can enforce here?" had just found that the
# sentence "403 forbidden — you are not an owner or an administrator of the
# tenant" had been PASTED onto five reads in `apps/events` that check no role at
# all. It was not a typo and it was not five typos: `derived_refusals` gives
# every authenticated route a `forbidden`, and a builder writing the prose
# transcribed that superset as though it were a decision somebody had made per
# route. The same sentence was sitting in three more api modules.
#
# WHY NOTHING CAUGHT IT. Every existing mechanism was satisfied. The code is
# registered (rule 41's older clause). It IS reachable — `_acting` raises a bare
# 403 when no tenant resolves — so its overclaim direction is silent and
# correct to be. The route answers 200 for a member and the document says 403,
# and no test compares those two facts. The failure is entirely in the SENTENCE
# somebody wrote about the code: a reader is told there is a permission wall
# where there is none, and the direction of that error is the dangerous one —
# it reads as security and delivers none.
#
# THE PREDICATE. A contract half that promises the caller a ROLE — the
# authorization seam's own refusal named beside a word for a privileged role —
# must have a permission check under it: `core.authz.require(...)` in the route
# body or in a function it calls by a name this tree can resolve, or rule 13's
# `# authz: <reason>` valve on that callee, which is the same declaration rule
# 13 already accepts from a service that delegates its check.
#
# NOTHING HERE IS HAND-COPIED. The code is read off `core.authz.require`'s own
# raise site, so renaming `Forbidden` moves the tell rather than blinding it;
# the role words are read off `Membership.is_privileged`, which is where this
# tree declares what "privileged" means. Typing `"forbidden"` and
# `{"owner", "admin"}` into this file would be a third copy of two decisions
# that already have homes.

# : Where the authorization seam lives, and its name. House rules 13, 24 and 26
# : all read the same one; it is not this clause's opinion about where a
# : permission check goes.
_AUTHZ_SOURCE = "apps/core/authz.py"
_AUTHZ_SEAM = "require"

# : Rule 13's declared valve, written on the line it excuses. A service that
# : delegates its check to the one it calls says so here, and this clause takes
# : that sentence at its word for the same reason rule 13 does.
_AUTHZ_VALVE = "# authz:"

# : Where the tree declares which roles are privileged: `Membership.is_privileged`
# : and the `Role` choices it names.
_ROLE_SOURCE = "apps/core/models.py"
_PRIVILEGE_DECLARATION = "is_privileged"


def _policy_refusal_code(root: Path, codes_by_class: dict[str, str]) -> str | None:
    """The code the authorization seam itself answers with.

    Read off `core.authz.require`'s raise site rather than typed here. The tell
    this clause looks for in prose is "the refusal a permission check gives
    you"; deriving it means a rename of that exception class moves the tell
    instead of quietly emptying it.
    """
    tree = _parse(root / _AUTHZ_SOURCE)
    if tree is None:
        return None
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name != _AUTHZ_SEAM:
            continue
        codes = _raised_codes(node, codes_by_class)
        # Exactly one, or nothing. A seam that grew a second refusal is a
        # change to what "the permission answer" means, and guessing which of
        # two codes the prose is about would be this clause inventing the
        # decision it exists to read.
        return next(iter(codes)) if len(codes) == 1 else None
    return None


def _privileged_role_words(root: Path) -> set[str]:
    """The role values `Membership.is_privileged` names, as prose spells them.

    `{Role.OWNER, Role.ADMIN}` resolved through the `TextChoices` body to
    `{"owner", "admin"}` — the strings a docstring actually contains. This is
    the tree's own declaration of "privileged" and there is no second list of
    it anywhere; writing one here is how the tell survives a role being added
    and stops seeing it.
    """
    tree = _parse(root / _ROLE_SOURCE)
    if tree is None:
        return set()
    values: dict[str, str] = {}
    privileged: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name == "Role":
            for statement in node.body:
                if not isinstance(statement, ast.Assign):
                    continue
                value = statement.value
                # `OWNER = "owner", "Owner"` — the first element is the value
                # the database and every docstring speak.
                if isinstance(value, ast.Tuple) and value.elts:
                    value = value.elts[0]
                if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                    continue
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        values[target.id] = value.value
        for statement in ast.walk(node):
            if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if statement.name != _PRIVILEGE_DECLARATION:
                continue
            for leaf in ast.walk(statement):
                if isinstance(leaf, ast.Attribute):
                    privileged.add(leaf.attr)
    return {values[name] for name in privileged if name in values}


def _promising_spans(doc: str | None, *, code: str, roles: set[str], divider: str) -> list[str]:
    """The chunks of a CONTRACT HALF that promise a role check.

    A chunk is a bullet or a paragraph, and the two halves of the tell have to
    meet inside ONE of them. That is what keeps the clause off its own
    corrected prose, which names the owner-or-administrator acts in the very
    sentence that says this read is not one of them — a different bullet, about
    a different code, and a reader would never confuse the two.
    """
    if not doc:
        return []
    lines = []
    for raw in doc.splitlines():
        # The divider and everything under it is the workshop half: notes for
        # whoever maintains this, never a promise to a caller.
        if raw.strip() == divider:
            break
        lines.append(raw)
    chunks: list[str] = []
    current: list[str] = []
    for line in lines:
        stripped = line.strip()
        starts_a_bullet = stripped.startswith("* ")
        if starts_a_bullet or not stripped:
            if current:
                chunks.append(" ".join(current))
            current = [stripped] if starts_a_bullet else []
            continue
        current.append(stripped)
    if current:
        chunks.append(" ".join(current))
    found = []
    for chunk in chunks:
        if not re.search(rf"\b{re.escape(code)}\b", chunk):
            continue
        # `admin` reaches `administrator` and `administer`, `owner` reaches
        # `owners`: a docstring writes English, not choice values, and a tell
        # that only matched the literal would miss every sentence it is for.
        if any(re.search(rf"\b{re.escape(word)}[a-z]*\b", chunk, re.I) for word in roles):
            found.append(chunk)
    return found


def _calls_the_seam(node: ast.AST) -> bool:
    """Whether this subtree calls `require(...)`, however it is imported."""
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        func = child.func
        if isinstance(func, ast.Name) and func.id == _AUTHZ_SEAM:
            return True
        if isinstance(func, ast.Attribute) and func.attr == _AUTHZ_SEAM:
            return True
    return False


def _module_file(root: Path, dotted: str) -> Path | None:
    """The file a resolved dotted module names, or None if it is not ours."""
    if not (dotted.startswith("apps.") or dotted.startswith("config.")):
        return None
    base = root.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _declares_the_valve(root: Path, dotted: str, node: ast.AST) -> bool:
    """Whether rule 13's `# authz:` valve is written inside this function.

    A comment, so it is read off the source lines rather than the tree. That is
    the point of the valve: it is a sentence somebody wrote, on the line it
    excuses, that a reviewer can disagree with — the same grammar rule 13 reads
    and rule 26's `# reach:` reads beside it.
    """
    path = _module_file(root, dotted)
    if path is None:
        return False
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if start is None or end is None:
        return False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(_AUTHZ_VALVE in line for line in lines[start - 1 : end])


def refusal_block_census(root: Path, rule: dict) -> CheckResult:
    """Rule 41's and clauses: the published refusals against the code.

    asks whether a code the document names can actually be raised here.
    asks the question one layer up — whether a refusal the prose describes
    as a ROLE check has a role check under it.
    """
    out = CheckResult()
    vocabulary = _door_shape_vocabulary(root)
    codes_by_class = _refusal_codes_by_class(root)
    policy_code = _policy_refusal_code(root, codes_by_class)
    role_words = _privileged_role_words(root)
    out.targets_matched["shape_codes"] = len(vocabulary)
    out.targets_matched["refusal_classes"] = len(codes_by_class)
    out.targets_matched["narrowed_routes"] = 0
    out.targets_matched["routes_with_an_unresolved_callee"] = 0
    out.targets_matched["privileged_role_words"] = len(role_words)
    out.targets_matched["role_promising_routes"] = 0
    divider = _module_constants(root, root / _CONTRACT_DIVIDER_SOURCE).get(
        "CONTRACT_DIVIDER", "---"
    )

    for app in _app_dirs(root):
        for path in api_modules(app):
            tree = _parse(path)
            if tree is None:
                continue
            rel = path.relative_to(root).as_posix()
            here = _dotted(root, path)
            modules, symbols = _import_maps(root, tree, here)
            local = {
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                is_route, declared = _route_decorators(node)
                if not is_route:
                    continue
                out.count("censused_routes")
                if declared is not None:
                    out.count("narrowed_routes")
                calls = _resolved_calls(
                    node, here=here, modules=modules, symbols=symbols, local=local
                )
                opaque = _dispatches_opaquely(node, modules=modules, symbols=symbols, local=local)
                reachable = _raised_codes(node, codes_by_class)
                authorizes = _calls_the_seam(node)
                for module, name in sorted(calls):
                    callee = _function_in(root, module, name)
                    if callee is None:
                        continue
                    out.count("callees_read")
                    reachable |= _raised_codes(callee, codes_by_class)
                    if _calls_the_seam(callee) or _declares_the_valve(root, module, callee):
                        authorizes = True
                if opaque:
                    out.count("routes_with_an_unresolved_callee")

                # . The prose promised a role; the code under it must ask.
                if policy_code and role_words:
                    promises = _promising_spans(
                        ast.get_docstring(node),
                        code=policy_code,
                        roles=role_words,
                        divider=divider,
                    )
                    if promises:
                        out.count("role_promising_routes")
                    if promises and not authorizes:
                        out.hit(
                            rel,
                            node.lineno,
                            f"{node.name} tells a caller that {policy_code!r} here means they are "
                            f"not {' or '.join(sorted(role_words))} — and nothing under it asks. "
                            f"Neither the route body nor a function it calls by name calls "
                            f"`{_AUTHZ_SEAM}(...)` or carries `{_AUTHZ_VALVE} <reason>`. The "
                            "sentence reads as a permission wall and there is none; a member who "
                            "believed it never tries, and a reviewer who believed it never looks "
                            f"(house rule 41). The promise: {promises[0][:120]!r}",
                            root=root,
                            klass="unbacked_promise",
                        )

                published = set(declared) if declared is not None else None
                for code in sorted(reachable):
                    if published is not None:
                        if code in published:
                            continue
                        out.hit(
                            rel,
                            node.lineno,
                            f"{node.name} narrows its refusals with `@refuses(...)` and does not "
                            f"name {code!r}, which something it calls directly raises. A narrowed "
                            "block is a promise that the list is the whole list — a client that "
                            f"branches on the document has no branch for {code!r} and will meet "
                            "one (house rule 41)",
                            root=root,
                            klass="underclaim",
                        )
                        continue
                    if code in vocabulary:
                        continue
                    out.hit(
                        rel,
                        node.lineno,
                        f"{node.name} can answer {code!r} — something it calls directly raises "
                        "it — and the door-shape derivation can never produce that code, so the "
                        "document does not mention it anywhere. Narrow the route with "
                        "`@refuses(...)` naming it (house rule 41)",
                        root=root,
                        klass="undocumented",
                    )
                if published is None or opaque:
                    continue
                for code in sorted(published - reachable - vocabulary):
                    out.hit(
                        rel,
                        node.lineno,
                        f"{node.name} publishes {code!r} and nothing it reaches raises it — not "
                        "its own body and not the services it calls. A refusal a client is told "
                        "to handle and can never meet is a branch nobody will ever exercise "
                        "(house rule 41)",
                        root=root,
                        klass="overclaim",
                    )
    return out


# --- rule 43: one outbound signer, and the scheme census ----------------------
#
# P5 QB-R2. Rule 40's `does_not_cover` carried the trigger in prose — "OUTBOUND
# header dictionaries ... a later rung may unify them (trigger: the second
# outbound signer)" — and landed a second SCHEME through the one signer,
# which is the moment that trigger stops being hypothetical. Two failures, and
# both are silent:
#
# 1. A SECOND SIGNER. A module that computes an HMAC over an outbound body and
# puts it in a header is a second implementation of the one thing every
# subscriber's code is written against. It breaks nothing on the day it
# lands; it breaks later, when the two disagree about a prefix, an encoding
# or a timestamp, inside somebody else's integration.
# 2. A SCHEME DROPPED IN FEWER THAN ALL ITS SITES. A scheme lives in three
# places at once — the header the delivery writes, the reference receiver a
# subscriber copies, and the prose the contract publishes. Drop it in one
# and the tree is green while a stranger's verifier stops matching, or
# while the document promises a header nothing sends.
#
# THE CONTRACTION IS THE DESIGN CONSTRAINT, not an afterthought. `X-Signature`
# is recorded-not-taken: it goes when the first product's subscribers have
# migrated, and the day it goes must be ONE green commit. So every number here
# survives it — `signature_schemes` floors at 1 and is never hardwired to 2 —
# and the populations are the three sites the recorded contraction actually
# edits.
#
# WHY THE VERIFIER MODULE IS NOT ONE OF THE THREE. `apps/events/receivers.py`
# keeps `signature_matches` after the contraction, because that bare-HMAC shape
# also verifies INBOUND PROVIDER deliveries, whose schemes are theirs . A
# three-way equality that included the verifier module would refuse the
# contraction it was built to allow. What the verifier owes instead is the other
# direction, as a subset: every VERSIONED house seam it grows must be a scheme
# the delivery actually sends — a parser for a header nobody sends is a branch
# nothing can reach, and the shape a reviewer reads as support.

# : `X-Signature`, `X-Signature-V2`, and whatever a later scheme is called.
_SIGNATURE_NAME_RE = re.compile(r"X-Signature[A-Za-z0-9-]*", re.IGNORECASE)

# : The house verifier's seam grammar: `signature_v2_matches`, `parse_signature_v2`.
# : A bare `signature_matches` is v1 and is the declared dual-role shape.
_VERIFIER_SEAM_RE = re.compile(r"^(?:parse_)?signature_v(\d+)(?:_matches)?$")

# : Where the contract divider is defined. Read, never re-typed (rule 41's own).
_CONTRACT_DIVIDER_SOURCE = "apps/core/api/docs.py"


def _module_constants(root: Path, path: Path) -> dict[str, str]:
    """Module-level `NAME = "literal"` string constants, by name."""
    tree = _parse(path)
    out: dict[str, str] = {}
    if tree is None:
        return out
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                out[target.id] = node.value.value
    return out


def _as_header_string(
    node: ast.expr, *, root: Path, here_constants: dict[str, str], modules: dict[str, str]
) -> str | None:
    """The string an expression names, when it is one this walk can resolve.

    Three forms and no more, for the same reason rule 40's read resolution stops
    where it does: a literal, a constant in this module, and a constant reached
    through a module this module imported. A name built at runtime is somebody
    else's control flow.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return here_constants.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        dotted = modules.get(node.value.id)
        if not dotted:
            return None
        target = root.joinpath(*dotted.split("."))
        for candidate in (target.with_suffix(".py"), target / "__init__.py"):
            if candidate.is_file():
                return _module_constants(root, candidate).get(node.attr)
    return None


def _signature_names(root: Path, path: Path, *, kinds: set[str]) -> set[str]:
    """Every `X-Signature*` name this module NAMES IN CODE, by expression kind.

    `dict` is a key in a dict literal or a subscript assignment — the shape a
    header is written in. `call` is an argument or a subscript slice — the shape
    a header is read in. Never a docstring or a comment: prose is population B's
    third site, and reading it here would let a paragraph stand in for a header.
    """
    tree = _parse(path)
    if tree is None:
        return set()
    here = _module_constants(root, path)
    modules, _symbols = _import_maps(root, tree, _dotted(root, path))
    candidates: list[ast.expr] = []
    for node in ast.walk(tree):
        if "dict" in kinds:
            if isinstance(node, ast.Dict):
                candidates.extend(key for key in node.keys if key is not None)
            elif isinstance(node, ast.Assign):
                candidates.extend(
                    target.slice for target in node.targets if isinstance(target, ast.Subscript)
                )
        if "call" in kinds:
            if isinstance(node, ast.Call):
                candidates.extend(node.args)
                candidates.extend(keyword.value for keyword in node.keywords)
            elif isinstance(node, ast.Subscript):
                candidates.append(node.slice)
    found: set[str] = set()
    for candidate in candidates:
        value = _as_header_string(candidate, root=root, here_constants=here, modules=modules)
        if value and _SIGNATURE_NAME_RE.fullmatch(value):
            found.add(value)
    return found


def _hmac_shape(tree: ast.Module) -> tuple[bool, bool]:
    """(computes an HMAC, compares one). The discriminator between the two jobs.

    A VERIFIER computes a digest and hands it to `hmac.compare_digest`; a SIGNER
    computes one and sends it. Derived rather than listed, so a product's own
    inbound verifier is outside this rule the day it is written and never needs
    an exemption — and so that a module which stops comparing and starts sending
    is in the population from that commit.
    """
    computes = compares = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        owner = func.value.id if isinstance(func.value, ast.Name) else ""
        if owner == "hmac" and func.attr in ("new", "digest"):
            computes = True
        if func.attr == "compare_digest":
            compares = True
    return computes, compares


def _contract_docstring(root: Path, rel: str, function: str) -> str:
    """The contract half of one route's docstring, read the way `docs.py` reads it.

    The divider is read OFF `apps/core/api/docs.py` rather than typed here: the
    convention belongs to the module that publishes it, and a rule carrying its
    own copy would be the second spelling this engine exists to refuse.
    """
    divider = _module_constants(root, root / _CONTRACT_DIVIDER_SOURCE).get(
        "CONTRACT_DIVIDER", "---"
    )
    tree = _parse(root / rel)
    if tree is None:
        return ""
    # The LAST definition wins, because that is what Python does: a module that
    # defines a name twice answers with the second one. It is also what makes an
    # append a legal plant site — a canary that redefines the route is the tree
    # this module would really import.
    doc = ""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function:
            doc = ast.get_docstring(node) or ""
    lines = doc.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == divider:
            return "\n".join(lines[:index])
    return doc


def outbound_signer_census(root: Path, rule: dict) -> CheckResult:
    """Rule 43. One signer, and a scheme is sent, verifiable and documented.

    Every site is DECLARED in `rules.yaml` with the reason it is that site,
    because "which module signs" is a judgement and not a discovery. What is
    derived is everything else: who ELSE signs, and which schemes each site
    names.
    """
    out = CheckResult()
    scope = rule.get("scope") or {}
    signer_rel = str((scope.get("declared_signer") or {}).get("module", ""))
    verifier_rel = str((scope.get("declared_verifier") or {}).get("module", ""))
    receiver_rel = str((scope.get("reference_receiver") or {}).get("module", ""))
    contract = scope.get("contract_prose") or {}
    contract_rel = str(contract.get("module", ""))
    contract_fn = str(contract.get("function", ""))

    # --- population A: who signs ---------------------------------------------
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        computes, compares = _hmac_shape(tree)
        writes = _signature_names(root, path, kinds={"dict"})
        if not ((computes and not compares) or writes):
            continue
        out.count("signer_modules")
        if rel in (signer_rel, verifier_rel):
            continue
        out.hit(
            rel,
            0,
            "this module signs an outbound body — it computes an HMAC it never compares, or "
            f"writes an `X-Signature*` header — and {signer_rel} is the one signer. Two "
            "signers do not disagree on the day the second lands; they disagree later, about "
            "a prefix or an encoding or a timestamp, inside somebody else's verifier. Call "
            "the one signer, or take a second scheme through it (house rule 43)",
            root=root,
            klass="signers",
        )

    # --- population B: the census --------------------------------------------
    sent = _signature_names(root, root / signer_rel, kinds={"dict"}) if signer_rel else set()
    received = (
        _signature_names(root, root / receiver_rel, kinds={"call"}) if receiver_rel else set()
    )
    documented = (
        set(_SIGNATURE_NAME_RE.findall(_contract_docstring(root, contract_rel, contract_fn)))
        if contract_rel
        else set()
    )
    out.targets_matched["signature_schemes"] = len(sent)
    sites = (
        ("the delivery writes", signer_rel, sent),
        ("the reference receiver reads", receiver_rel, received),
        ("the contract prose documents", contract_rel, documented),
    )
    for scheme in sorted(sent | received | documented):
        holders = [label for label, _rel, names in sites if scheme in names]
        if len(holders) == len(sites):
            out.count("schemes_censused")
            continue
        missing = [(label, rel) for label, rel, names in sites if scheme not in names]
        out.hit(
            missing[0][1],
            0,
            f"{scheme} is named where {' and '.join(holders) or 'nothing does'} and not where "
            + " and ".join(label for label, _rel in missing)
            + f" — a scheme lives at all three sites or at none. Dropping {scheme} is one "
            "commit that edits all three; this is that commit half-made, and the missing "
            "half is invisible until somebody else's verifier stops matching (house rule 43)",
            root=root,
            klass="census",
        )

    # --- the verifier's own direction: no branch for a scheme nobody sends ----
    verifier_tree = _parse(root / verifier_rel) if verifier_rel else None
    if verifier_tree is not None:
        for node in verifier_tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            found = _VERIFIER_SEAM_RE.match(node.name)
            if not found:
                continue
            out.count("verifier_seams")
            scheme = f"X-Signature-V{found.group(1)}"
            if scheme in sent:
                continue
            out.hit(
                verifier_rel,
                node.lineno,
                f"{node.name} parses {scheme} and no delivery sends it — the signer writes "
                f"{', '.join(sorted(sent)) or 'nothing'}. A verifier branch for a scheme "
                "nothing sends is unreachable code that reads to a reviewer as support for a "
                "scheme this product does not have (house rule 43)",
                root=root,
                klass="census",
            )
    return out


# --- rule 44: the library internals we hold, censused ---------------------------
#
# `config/api.py` holds two wraps of django-ninja's own privates — the
# token-ceiling guard over `Operation._run_checks` (ADR ident-7) and the
# method-refusal envelope over `PathView._sync_view` / `._async_view` —
# and each carries an import tripwire that raises `RuntimeError` when the
# attribute it needs is gone. The tripwire is the right shape and it fires at
# the WRONG TIME: at import, on the machine that has already installed the new
# ninja, with the whole API mount taken down behind it. This is the same fact,
# read off the installed package by the gate, before anything is mounted.
#
# THE POPULATION IS DERIVED AND THE CENSUS IS DECLARED. Which modules rebind a
# private attribute on an object they did not define is a walk (a `self`/`cls`
# assignment is an object's own state; a dunder is the interpreter's protocol;
# a test module builds fakes for a living). WHY each one is held, and which
# ninja class it belongs to, is a judgement that cannot be discovered — so it is
# written down, one entry per attribute, and a third wrap joins the census in
# the same commit that adds it.

# : The census lives in the rules file, so that is where a finding about the
# : census itself is pathed.
_CENSUS_DECLARATION = "quality/rules.yaml"

# : The library whose privates this repository reaches into.
_NINJA_PACKAGE = "ninja"

# : The other one, and the class the whole machine door hangs off.
_MCP_PACKAGE = "mcp"
_MCP_SERVER_CLASS = "MCPServer"

# : Not a wrap: an object's own state.
_OWN_STATE = {"self", "cls"}


def _installed_package_dir(package: str) -> Path | None:
    """Where an INSTALLED package lives — resolved, never imported.

    `import ninja` builds a pydantic settings object off `django.conf.settings`
    at module scope, so importing it here would mean standing up Django to read
    three attribute names; `import mcp.server.mcpserver` drags anyio and the
    whole transport in for two. `find_spec` resolves the package along the same
    path the interpreter would use and executes none of it.
    """
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ValueError):  # pragma: no cover - a broken install
        return None
    if spec is None or spec.origin is None:
        return None
    return Path(spec.origin).parent


def _ninja_source_dir() -> Path | None:
    """Where the INSTALLED django-ninja lives. See `_installed_package_dir`."""
    return _installed_package_dir(_NINJA_PACKAGE)


def _package_class_attributes(package: str) -> dict[str, set[str]] | None:
    """`{ClassName: {every name its body or its in-package bases define}}`, by AST.

    Read across the whole package rather than one module, because a census entry
    names a CLASS: ninja moving `PathView` between modules is not a rename and
    must not read as one. `None` when the package cannot be found at all —
    which is a floor away from exit 2, not a clean pass.
    """
    base = _installed_package_dir(package)
    if base is None:
        return None
    direct: dict[str, set[str]] = {}
    bases: dict[str, list[str]] = {}
    for path in sorted(base.rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names = direct.setdefault(node.name, set())
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(stmt.name)
                elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names.add(stmt.target.id)
                elif isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            names.add(target.id)
            bases.setdefault(node.name, []).extend(
                b.id for b in node.bases if isinstance(b, ast.Name)
            )
    # One inheritance pass per level, bounded: an attribute a subclass is
    # wrapped through may be defined on its ninja base (`AsyncOperation` over
    # `Operation`), and a census entry naming the base is still true of it.
    for _ in range(4):
        for name, parents in bases.items():
            for parent in parents:
                direct[name] |= direct.get(parent, set())
    return direct


def _ninja_class_attributes() -> dict[str, set[str]] | None:
    """Rule 44's ninja half. See `_package_class_attributes`."""
    return _package_class_attributes(_NINJA_PACKAGE)


def _mcp_class_attributes() -> dict[str, set[str]] | None:
    """Rule 44's MCP half, and rule 45's. See `_package_class_attributes`."""
    return _package_class_attributes(_MCP_PACKAGE)


def _mcp_server_manager_attributes() -> set[str] | None:
    """Every `self._<something>_manager` the installed `MCPServer.__init__` binds.

    Rule 45's DERIVED half. The census says which dispatch surfaces this
    repository believes the server has; this says which ones it really has, read
    off the package on disk by the same means rule 44 reads ninja. A manager the
    census has never heard of is a fourth dispatch surface nobody wrote a
    ceiling for, and the point of the rule is that such a thing cannot arrive
    quietly.

    `None` when the package cannot be found at all — a floor away from exit 2,
    never a clean pass.
    """
    base = _installed_package_dir(_MCP_PACKAGE)
    if base is None:
        return None
    found: set[str] = set()
    for path in sorted(base.rglob("*.py")):
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or node.name != _MCP_SERVER_CLASS:
                continue
            for sub in ast.walk(node):
                targets: list[ast.expr] = []
                if isinstance(sub, ast.Assign):
                    targets = list(sub.targets)
                elif isinstance(sub, (ast.AnnAssign, ast.AugAssign)):
                    targets = [sub.target]
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Name)
                        and target.value.id == "self"
                        and target.attr.endswith("_manager")
                    ):
                        found.add(target.attr)
    return found


def _private_attribute_bindings(tree: ast.Module) -> list[tuple[int, str, str]]:
    """`(line, owner, attribute)` for every `<name>._private = ...` in a module.

    Rebinding a private attribute on an object this code did not define is the
    one shape that can hold both sides of a seam a library never published, and
    it is the shape both of `config/api.py`'s wraps take. `self`/`cls` are not
    wraps, and a dunder is the interpreter's protocol rather than a library's
    private.
    """
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Attribute):
                continue
            if not isinstance(target.value, ast.Name) or target.value.id in _OWN_STATE:
                continue
            attr = target.attr
            if not attr.startswith("_") or attr.startswith("__"):
                continue
            found.append((node.lineno, target.value.id, attr))
    return sorted(found)


def ninja_internals_census(root: Path, rule: dict) -> CheckResult:
    """Rule 44. Every library private this tree holds is declared, and still exists.

    Two clauses over one declared list:

      * every private attribute a production module rebinds on somebody else's
        object is named in the census, with the class it belongs to and the
        reason it is held; and
      * every censused name is still defined on the INSTALLED django-ninja, read
        off the package on disk. A rename upstream is a finding here, and — via
        `census_attributes_present` — exit 2, said by the gate on the machine
        that ran `uv sync`, rather than a `RuntimeError` from the mount on the
        machine that ran the server.
    """
    out = CheckResult()
    entries = (rule.get("scope") or {}).get("ninja_internals_we_hold") or []
    declared: dict[str, dict] = {str(entry["attribute"]): entry for entry in entries}
    out.count("census_attributes", len(declared))

    classes = _ninja_class_attributes()
    for name, entry in sorted(declared.items()):
        klass = str(entry.get("ninja_class") or "")
        if classes is None:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census names `{klass}.{name}` and the installed django-ninja could "
                "not be found on the import path at all, so nothing here is validating "
                "anything — the wraps in config/api.py would discover it at mount",
                klass="census",
            )
            continue
        members = classes.get(klass)
        if members is None:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census names `{klass}.{name}` and the installed django-ninja has no "
                f"class `{klass}` — the wrap that holds it will raise at import, taking "
                "the whole API mount with it. Follow the rename here first",
                klass="census",
            )
            continue
        if name not in members:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census names `{klass}.{name}` and the installed django-ninja's "
                f"`{klass}` no longer defines `{name}` — this is the ninja upgrade the "
                "import tripwire in config/api.py exists for, said before anything is "
                "mounted instead of after",
                klass="census",
            )
            continue
        out.count("census_attributes_present", 1)

    bound: dict[str, list[tuple[str, int]]] = {}
    for path in _py_files(root, "apps", "config"):
        rel = str(path.relative_to(root))
        if _is_test_module(rel):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for line, owner, attr in _private_attribute_bindings(tree):
            bound.setdefault(attr, []).append((rel, line))
            if attr in declared:
                continue
            known = classes is not None and any(attr in names for names in classes.values())
            where = (
                "django-ninja does define it, so this is a third wrap and the census has "
                "not been told"
                if known
                else "and django-ninja does not define it anywhere, so the wrap is holding "
                "a seam that is not there"
            )
            out.hit(
                rel,
                line,
                f"`{owner}.{attr}` rebinds a private attribute on an object this module "
                f"did not define — {where}. A private we hold is declared in "
                "`ninja_internals_we_hold` (quality/rules.yaml) with the class it belongs "
                "to and the reason, in the same commit that binds it, so that the gate can "
                "tell an upstream rename BEFORE the import tripwire does",
                root=root,
                klass="wrap",
            )
    out.count("ninja_wrap_attributes", len(bound))
    out.count("ninja_wrap_sites", sum(len(sites) for sites in bound.values()))

    for name in sorted(set(declared) - set(bound)):
        out.hit(
            _CENSUS_DECLARATION,
            0,
            f"the census names `{name}` and nothing under apps/ or config/ binds it any "
            "more — a census that lists a wrap this tree does not hold is a claim about "
            "somebody else's tree. Drop the entry in the commit that drops the wrap",
            klass="census",
        )

    # THE MCP HALF ('s second half). Declared-only, and the reason is
    # stated in the rule's `does_not_cover`: neither of the two things held on
    # the MCP side is a PRIVATE attribute binding, so the walk above cannot
    # derive them. `install_ceiling_gate` rebinds `call_tool`, which is the SDK's
    # own public dispatch method — deliberately, and the alternatives it rejected
    # were all privates — and `TOOL_ERROR_SENTENCE` is not a binding at all but a
    # verbatim copy of somebody else's prose. Both are seams this tree holds and
    # both break the same way on an upgrade, so both are censused and both are
    # checked for EXISTENCE off the installed package, which is the half a census
    # can do.
    mcp_entries = (rule.get("scope") or {}).get("mcp_internals_we_hold") or []
    out.count("mcp_census_entries", len(mcp_entries))
    mcp_classes = _mcp_class_attributes()
    for entry in mcp_entries:
        name = str(entry.get("attribute") or "")
        klass_name = str(entry.get("mcp_class") or "")
        if mcp_classes is None:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census names `{klass_name}.{name}` and the installed `{_MCP_PACKAGE}` "
                "SDK could not be found on the import path at all, so nothing here is "
                "validating anything — the machine door would discover it at mount",
                klass="census",
            )
            continue
        members = mcp_classes.get(klass_name)
        if members is None:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census names `{klass_name}.{name}` and the installed MCP SDK has no "
                f"class `{klass_name}` — the seam this tree holds against it is gone. "
                "Follow the rename here first",
                klass="census",
            )
            continue
        if name not in members:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census names `{klass_name}.{name}` and the installed MCP SDK's "
                f"`{klass_name}` no longer defines `{name}` — said by the gate on the "
                "machine that ran `uv sync`, before the mount says it by failing",
                klass="census",
            )
            continue
        out.count("mcp_census_entries_present", 1)
    return out


# --- rule 45: every MCP dispatch surface is ceilinged --------------------------
#
# . The server has three dispatch surfaces — `tools/call`, `resources/read`,
# `prompts/get` — each with its own manager, its own validation and its own path
# through the transport. Exactly one of them has a ceiling in front of it
# (`install_ceiling_gate`); the other two have a comment. Nothing is
# exposed today because this product registers no resources and no prompts, and
# that is precisely the moment to write the rule: rule 30's refusal in the other
# direction says a wall for a door nobody has is a schema built for a poller
# nobody wrote, so this rule refuses the FIRST registration on an unguarded
# surface and says nothing at all until then.


def _mcp_registration_sites(root: Path, names: set[str]) -> list[tuple[str, int, str]]:
    """`(relpath, line, attribute)` for every `<something>.<name>(...)` call under
    `apps/`/`config/`, for the registering attribute names a surface declares.

    DERIVED, because registration is by discovery: an app contributes a tool by
    exposing `register(server)` in its `mcp.py` and nothing here is edited when
    an app is added, so a list of modules would be the one thing the rest of the
    system refuses to keep. Test modules are outside the walk for rule 44's
    reason: a test that stands up its own server and registers a probe tool on
    it is how the door is proved at all.
    """
    sites: list[tuple[str, int, str]] = []
    for path in _py_files(root, "apps", "config"):
        rel = str(path.relative_to(root))
        if _is_test_module(rel):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in names:
                sites.append((rel, node.lineno, func.attr))
    return sites


def _marker_is_called(root: Path, marker: str) -> bool:
    """Whether anything under `apps/`/`config/` CALLS the named guard.

    A marker, not a proof: that the guard is correct is the mcp-wall tests' job
    and this rule says so out loud in `does_not_cover`. What it can see is the
    difference between a surface somebody put a wall in front of and a surface
    nobody did.
    """
    for path in _py_files(root, "apps", "config"):
        rel = str(path.relative_to(root))
        if _is_test_module(rel):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == marker:
                return True
    return False


def mcp_dispatch_surfaces(root: Path, rule: dict) -> CheckResult:
    """Rule 45. Every dispatch surface the server has is censused, and ceilinged
    the moment anything is registered on it.

    Three clauses over one declared census:

      * every censused surface still exists on the INSTALLED SDK — its dispatch
        method and its manager attribute both — read off the package on disk;
      * every manager-shaped attribute the installed `MCPServer` binds is
        NAMED in the census, so a fourth surface cannot arrive unnoticed; and
      * a surface holding at least one registration whose declared guard marker
        is called nowhere is a violation, at every registration site.

    The first two are floors, which is to say exit 2: a census that cannot see
    cannot pass, and a green from a census that has gone blind is worse than no
    census at all.
    """
    out = CheckResult()
    entries = (rule.get("scope") or {}).get("mcp_dispatch_surfaces") or []
    classes = _mcp_class_attributes()
    managers = _mcp_server_manager_attributes()

    censused_managers: set[str] = set()
    for entry in entries:
        surface = str(entry.get("surface") or "?")
        dispatch = str(entry.get("dispatch") or "")
        manager = str(entry.get("manager") or "")
        guard = str(entry.get("guard") or "")
        registers = {str(name) for name in (entry.get("registers") or [])}
        censused_managers.add(manager)

        if classes is None or managers is None:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census names the `{surface}` surface and the installed `{_MCP_PACKAGE}` "
                "SDK could not be found on the import path at all, so nothing here is "
                "validating anything — the mount would discover it at startup",
                klass="census",
            )
            continue
        members = classes.get(_MCP_SERVER_CLASS, set())
        if dispatch not in members:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census says `{surface}` is dispatched by "
                f"`{_MCP_SERVER_CLASS}.{dispatch}` and the installed SDK no longer defines "
                f"`{dispatch}` — the wrap that holds it (or the wrap that would have to) is "
                "aimed at a seam that is not there. Follow the rename here first",
                klass="census",
            )
            continue
        if manager not in managers:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the census says `{surface}` is served by `{_MCP_SERVER_CLASS}.{manager}` "
                f"and the installed SDK binds no such attribute (it binds "
                f"{', '.join(sorted(managers)) or 'none'}) — a census reading a manager that "
                "is gone cannot tell whether anything is registered on that surface",
                klass="census",
            )
            continue
        out.count("censused_surfaces", 1)

        guarded = bool(guard) and _marker_is_called(root, guard)
        if guarded:
            out.count("guarded_surfaces", 1)
        sites = _mcp_registration_sites(root, registers)
        # `tools/call` counts as `tools_registered` — the surface's own noun, so
        # the floor below reads as the fact it pins.
        out.count(f"{surface.split('/')[0]}_registered", len(sites))
        if not sites or guarded:
            continue
        for rel, line, attr in sites:
            out.hit(
                rel,
                line,
                f"`.{attr}(...)` registers on the `{surface}` dispatch surface and nothing "
                f"under apps/ or config/ calls `{guard}` — that surface reaches the "
                f"transport through `{_MCP_SERVER_CLASS}.{dispatch}` with no token-ceiling "
                "check in front of it, so a bearer whose ceiling reaches nothing here is "
                "answered about the request instead of refused (one surface "
                f"over). Install the guard from the registering app's `register()`, the way "
                "`install_ceiling_gate` is installed, and name it in this surface's census "
                "entry (quality/rules.yaml, rule 45)",
                root=root,
                klass="unguarded",
            )

    if managers is not None:
        unnamed = sorted(managers - censused_managers)
        if not unnamed:
            out.count("census_names_every_manager", 1)
        for attr in unnamed:
            out.hit(
                _CENSUS_DECLARATION,
                0,
                f"the installed `{_MCP_SERVER_CLASS}` binds `{attr}` and the census names no "
                "surface served by it — that is a dispatch surface this repository has never "
                "heard of, and a census that cannot see one cannot say the others are "
                "ceilinged. Add the entry (surface, dispatch, manager, registers, guard) in "
                "the commit that takes the SDK upgrade",
                klass="census",
            )
    return out


# --- rule 46: every door pair owes a parity test -------------------------------
#
# . Rule 17 diffs two REGISTRIES and proves a capability exists on both
# doors; it cannot see one consumer answering two credentials two ways,
# and it cannot see two doors serialising one row differently . Both of
# those were caught by a test in the owning app, and the family had exactly one
# member with nothing making a new door pair grow one. This is the census that
# makes it grow: the POPULATION is derived from the door modules that exist, and
# the ANSWER is a module-level `DOOR_PAIR` marker in that app's tests.

# : The module-level name a parity test claims its pair with.
_DOOR_PAIR_MARKER = "DOOR_PAIR"


def _door_pairs_owed(app: Path) -> list[tuple[tuple[str, str], Path]]:
    """The pairs this app owes a parity test for, DERIVED from the doors it has.

    Two kinds, and both are read off files rather than off any list: an app with
    a REST door and an `mcp.py` owes `(rest, mcp)`, because those are two
    renderings of one capability and rule 17 compares the registries and not the
    wire; an app with a `consumers.py` owes `(session, bearer)`, because the
    socket door has no second registry to diff and the credential is the axis
    came in on.
    """
    owed: list[tuple[tuple[str, str], Path]] = []
    rest = bool(api_modules(app))
    mcp = app / "mcp.py"
    if rest and mcp.is_file():
        owed.append((("rest", "mcp"), mcp))
    consumers = app / "consumers.py"
    if consumers.is_file():
        owed.append((("session", "bearer"), consumers))
    return owed


def _door_pairs_claimed(app: Path) -> list[tuple[tuple[str, str], Path, int]]:
    """`(pair, path, line)` for every `DOOR_PAIR` marker in this app's tests.

    Read by AST off a module-level assignment, never by grep: a marker inside a
    function or a docstring is not a claim about the module. Both shapes are
    accepted — one pair, or a sequence of them for a module that answers two —
    and anything else is reported as a malformed claim rather than ignored.
    """
    claimed: list[tuple[tuple[str, str], Path, int]] = []
    tests = app / "tests"
    if not tests.is_dir():
        return claimed
    for path in sorted(tests.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if _DOOR_PAIR_MARKER not in names:
                continue
            for pair in _pairs_in(node.value):
                claimed.append((pair, path, node.lineno))
    return claimed


def _pairs_in(value: ast.expr) -> list[tuple[str, str]]:
    """Every `("a", "b")` a `DOOR_PAIR` marker's right-hand side holds."""
    if not isinstance(value, (ast.Tuple, ast.List)):
        return []
    elements = list(value.elts)
    if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elements):
        if len(elements) == 2:
            return [(str(elements[0].value), str(elements[1].value))]  # type: ignore[attr-defined]
        return []
    out: list[tuple[str, str]] = []
    for element in elements:
        out.extend(_pairs_in(element))
    return out


def door_pair_parity(root: Path, rule: dict) -> CheckResult:
    """Rule 46. Every door pair an app has owes a named parity test in that app.

    The population is derived; the answer is claimed. A pair is answered by a
    module-level `DOOR_PAIR = ("rest", "mcp")` in the owning app's `tests/`, and
    the census is the difference. A marker claiming a pair the app does not own
    is a lie in the other direction and fires as one — an app can otherwise
    answer its backlog by writing the marker into any file.

    MEASURED BEFORE ENFORCED (quality/door-parity-measurement.md): the backlog is
    ratcheted per APP, so a new app's first door pair is a violation from birth
    while the five apps that predate the rule are a standing backlog that may
    shrink and never grow.
    """
    out = CheckResult()
    for app in _app_dirs(root):
        label = app.name
        owed = _door_pairs_owed(app)
        claimed = _door_pairs_claimed(app)
        out.count("apps_scanned", 1)
        out.count("door_pairs_owed", len(owed))
        answered = {pair for pair, _, _ in claimed}
        owed_pairs = {pair for pair, _ in owed}

        for pair, module in owed:
            if pair in answered:
                out.count("door_pairs_answered", 1)
                continue
            out.hit(
                module,
                1,
                f"`{label}` has both halves of the ({pair[0]}, {pair[1]}) door pair and no "
                f"test in `apps/{label}/tests/` claims it. Rule 17 diffs the two REGISTRIES "
                "and proves the capability exists on both; it cannot see the two doors "
                "answering it differently — a serialization that differs by rendering "
                "or a credential that resolves a different hat, both of which were "
                "found by a test of exactly this shape and by nothing else. Write the parity "
                f"test and mark it `{_DOOR_PAIR_MARKER} = ({pair[0]!r}, {pair[1]!r})` at "
                "module level",
                root=root,
                klass=label,
            )
        for pair, path, line in claimed:
            if pair in owed_pairs:
                continue
            out.hit(
                path,
                line,
                f"this module claims the ({pair[0]}, {pair[1]}) door pair for `{label}` and "
                f"`{label}` does not own that pair — the doors it would be about are not "
                "there. A marker is how an app says a pair is answered, so a marker for a "
                "pair nobody owes retires a debt that was never taken on. Drop it, or name "
                "the pair this module really tests",
                root=root,
                klass="claim",
            )
    return out


# --- rule 47: a declared refusal reaches the document --------------------------
#
# its find, and the reason it is a rule rather than a fix: the drop is
# SILENT. `config/api.py::_document_operation` turns a route's refusal codes into
# responses through `CODE_STATUS.get(code)` guarded by `if status is not None`,
# so a code with no line in that table leaves the document without a word — the
# route still refuses that way on the wire, and the published `x-refusal-codes` a
# generated client switches on has no branch for it.
#
# PRODUCTION STAYS TOLERANT. The mount does not raise for this and must not: the
# document is built at import, and a refusal to build it takes the whole API down
# on the machine that ran the server — rule 44's docstring records that exact
# malady. The gate is the right time, on the machine that ran `uv sync`.


def _code_status_drop_site(root: Path) -> tuple[str, int]:
    """Where the silent drop is written, DERIVED rather than typed.

    A finding that names `config/api.py:953` is right until somebody adds a line
    above it, so the line is found by reading for the guard itself.
    """
    rel = "config/api.py"
    path = root / rel
    tree = _parse(path)
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            test = node.test
            if (
                isinstance(test, ast.Compare)
                and isinstance(test.left, ast.Name)
                and test.left.id == "status"
                and any(isinstance(op, ast.IsNot) for op in test.ops)
            ):
                return rel, node.lineno
    return rel, 0


def declared_refusals_documented(root: Path, rule: dict) -> CheckResult:
    """Rule 47. Every refusal a bound operation can answer with is in the document.

    The probe (`quality/refusal_probe.py`) is a subprocess for rule 44's reason:
    `document_api()` runs at import of `config/api.py`, so a gate that imported
    it would take every other rule's canary down with it the day that import
    broke.

    Two branches, and the difference between them is the whole of . A missing
    code that is ALSO absent from `CODE_STATUS` is the one drop this rule has
    proven, and the finding names the table line to add. A missing code that IS
    in `CODE_STATUS` went somewhere else, and the finding says exactly that — a
    violation that admits what it has not established, rather than one that names
    a cause it guessed.
    """
    out = CheckResult()
    proc = subprocess.run(
        [sys.executable, str(root / "quality" / "refusal_probe.py")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(proc.stdout)
    except (ValueError, TypeError):
        report = None
    if proc.returncode != 0 or not isinstance(report, dict):
        out.hit(
            _CENSUS_DECLARATION,
            0,
            "rule 47's probe could not read the document at all (exit "
            f"{proc.returncode}) — the mount did not import, or did not answer. That is "
            "enforcement broken and not a clean document; the floors below say so as exit "
            f"2. Output:\n{(proc.stdout + proc.stderr).strip()[-1500:]}",
            klass="probe",
        )
        return out

    out.count("operations_checked", int(report.get("operations", 0)))
    out.count("registry_codes", int(report.get("registry_codes", 0)))
    out.count("documented_codes", int(report.get("documented_codes", 0)))
    out.count("narrowed_routes", int(report.get("narrowed_routes", 0)))

    table_rel, table_line = _code_status_drop_site(root)
    for drop in report.get("drops") or []:
        code = str(drop.get("code"))
        route = str(drop.get("route"))
        said = "declares with `@refuses(...)`" if drop.get("declared") else "derives"
        if not drop.get("in_code_status"):
            out.hit(
                str(drop.get("path")),
                int(drop.get("line") or 1),
                f"`{route}` {said} the refusal `{code}`, and the published document does "
                f"not carry it. `{code}` has no line in `CODE_STATUS`, so "
                f"`_document_operation`'s `if status is not None` ({table_rel}:{table_line}) "
                "drops it without a word: the route refuses that way on the wire and a "
                "client that branches on `x-refusal-codes` has no branch for it. Add the "
                f'`CODE_STATUS["{code}"] = ...` line beside its siblings, in the same commit '
                "that registers the code",
                root=root,
                klass="unmapped",
            )
        else:
            out.hit(
                str(drop.get("path")),
                int(drop.get("line") or 1),
                f"`{route}` {said} the refusal `{code}`, and the published document does "
                f"not carry it — AND `{code}` IS in `CODE_STATUS` (status "
                f"{drop.get('status')}), "
                f"so this is NOT the `if status is not None` drop at {table_rel}:{table_line} "
                "that this rule has proven. Where it went is UNDIAGNOSED: this message says "
                "so rather than naming a cause nobody established, and the fix starts by "
                "finding out",
                root=root,
                klass="undiagnosed",
            )
    return out


# --- rule 31: every model declares how its data dies ---------------------------
#
# ADR core-13, LF-1's primitive (`apps/core/lifecycle.py`), LF-Q's rule. Two
# questions, one probe, and they fail in different classes because they have
# different repairs.
#
# THE CENSUS. Every concrete model in the LIVE registry either carries a
# `Lifecycle` or does not, and the complement is a backlog measured before it is
# enforced (`quality/lifecycle-measurement.md`), ratcheted per Django
# `app_label`. Per-app and not per-rule for rule 46's reason and for the schema
# discipline's: the declaration fan-out is five builders in five apps, and a
# shared number is a shared file.
#
# THE TOOTH. A `PURGED` declaration names a callable, and a callable nothing
# runs is the poller that was never built — its shape, and the fifth sighting
# of that class is what exists to end. The chain is walked outwards
# from the declaration: `purged_by` -> an activity that references it -> a
# workflow that executes that activity -> a `ScheduleDeclaration` whose action
# names that workflow. The schedule half comes off LC-1's STRUCTURED REGISTRY
# (`apps.workflows.client.discovered_schedules`) and never off a tree walk; the
# workflow half is read from the resolved class's own source, because
# `workflow.execute_activity("name", ...)` takes a string at a call site and
# there is no runtime edge to follow.
#
# WHY A SUBPROCESS. The population is `django_apps.get_models()` and the
# registry is `discovered_schedules()`: both need a booted Django, and the gate
# must not stand Django up in its own process (rule 44's docstring records
# living through exactly that — one bad import and every rule's canary dies at
# once). `quality/lifecycle_probe.py` owns the boot and answers in JSON.

_LIFECYCLE_PROBE = "quality/lifecycle_probe.py"


def declared_lifecycles(root: Path, rule: dict) -> CheckResult:
    """Rule 31. Every concrete model declares how its data dies, and a purge is reached.

    Two classes of finding and one probe. An undeclared model fires in its own
    APP's class, so the measured backlog shrinks per app and never pays for
    another app's growth. A `purged` declaration whose callable no
    `ScheduleDeclaration` chain reaches fires in `unreachable` (or
    `unresolvable`, when the dotted path names nothing importable), neither of
    which is ratcheted: the tooth is born clean because the one live member
    (`core.IdempotencyRecord`) has its whole chain written down.

    Declaration-time reachability ONLY. That the chain is written, end to end,
    in the tree being gated — never that the schedule is live on a server, that
    its last tick ran, or that the filter deletes the right rows. Those are
    runtime facts and belong to LC-2/LC-3's census; the boundary is in
    `does_not_cover` so a green rule 31 is never read as a purge that ran.
    """
    out = CheckResult()
    proc = subprocess.run(
        [sys.executable, str(root / _LIFECYCLE_PROBE)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(proc.stdout)
    except (ValueError, TypeError):
        report = None
    if proc.returncode != 0 or not isinstance(report, dict):
        out.hit(
            _CENSUS_DECLARATION,
            0,
            f"rule 31's probe could not read the model registry at all (exit "
            f"{proc.returncode}) — Django did not boot, or did not answer. That is "
            "enforcement broken and not an empty backlog; the floors below say so as exit "
            f"2. Output:\n{(proc.stdout + proc.stderr).strip()[-1500:]}",
            klass="probe",
        )
        return out

    out.count("concrete_models", int(report.get("concrete", 0)))
    out.count("declared_lifecycles", int(report.get("declared", 0)))
    out.count("scheduled_workflows", int(report.get("scheduled_workflows", 0)))
    out.count("purged_declarations", len(report.get("purged") or []))
    out.count("lifecycle_kinds", len(report.get("kinds") or {}))

    for model in report.get("undeclared") or []:
        label = str(model.get("label"))
        app_label = str(model.get("app_label"))
        in_tree = bool(model.get("in_tree"))
        if in_tree:
            where, line = str(model.get("file")), int(model.get("line") or 1)
            how = (
                "declare it on the model — `lifecycle: ClassVar[Lifecycle] = "
                "Lifecycle(kind=...)`, in the class body, where the person adding the "
                "table is already standing"
            )
        else:
            where, line = _CENSUS_DECLARATION, 0
            how = (
                "this table belongs to somebody else and will never grow an attribute, so "
                "whichever app OWNS THE CONCERN declares it in its own "
                "`apps/<app>/lifecycle.py::register(registry)` — discovered, never listed "
                "(a central dict would be one file every app in a parallel wave has to edit)"
            )
        out.hit(
            where,
            line,
            f"{label} is a concrete model and nothing says how its rows die. Four kinds "
            "and no fifth (ADR core-13): `purged` names the callable that sweeps it, "
            "`bounded` says the rows die with their parent, `unbounded` and `append_only` "
            "carry a reason and a dated trigger. A retention document is the shape that "
            "does not survive a product — the table added on Thursday is never in it — so "
            f"the declaration lives with the table. {how}",
            root=root,
            klass=app_label,
        )

    for entry in report.get("purged") or []:
        if entry.get("reachable"):
            continue
        label = str(entry.get("label"))
        dotted = str(entry.get("purged_by"))
        # Pathed at the DECLARATION, never at the callable: the declaration is
        # the promise, and it is the line whose author owes either a schedule or
        # a truer kind. The callable's own site rides in the message.
        if entry.get("model_in_tree"):
            where, line = str(entry.get("model_file")), int(entry.get("model_line") or 1)
        else:
            where, line = _CENSUS_DECLARATION, 0
        klass = "unresolvable" if not entry.get("resolved") else "unreachable"
        at = (
            f" (`{dotted}` is written at {entry.get('file')}:{entry.get('line')})"
            if entry.get("resolved") and entry.get("file")
            else ""
        )
        schedules = ", ".join(
            f"{one.get('name')} -> {one.get('workflow')}" for one in report.get("schedules") or []
        )
        out.hit(
            where,
            line,
            f"{label} declares `purged` and names `{dotted}`, and no ScheduleDeclaration "
            f"chain reaches it: {entry.get('why')}{at}. The chain rule 31 walks is "
            "`purged_by` -> an activity that references it -> a workflow that executes "
            "that activity -> a `ScheduleDeclaration` in some app's "
            "`activities.py::SCHEDULES` whose action names that workflow. The declared "
            f"machines today are [{schedules}]. A table declared purged with nothing "
            "purging it is the poller that was never built — the defect this whole "
            "vocabulary exists to catch, and the one this rule is the fifth sighting of. "
            "Write the activity and its ScheduleDeclaration in the same commit as the "
            "declaration, or say a truer kind",
            root=root,
            klass=klass,
        )
    return out


# --- rule 48: one door to the object store (ADR files-2, P7 Q-32) -------------
#
# The third fence of the rule-27 shape, and the one with the widest blast
# radius. Zitadel's is about a CREDENTIAL and a transaction boundary; the search
# index's (rule 33) is about a WALL. This one is about BYTES: an object store is
# a flat key space with no tenancy in it at all, so the only thing standing
# between one customer's document and another's is the KEY GRAMMAR
# (`apps/files/storage.py::version_key` — `t/<tenant pk>/f/<file pk>/v/<n>`) and
# the belt that refuses a key outside the caller's own prefix
# (`refuse_foreign_key`). Both live in one module, and both are only true while
# that module is the only way to reach a bucket.
#
# FOUR CLAUSES, because there are four ways to open a second door, and only the
# first of them needs the AWS SDK:
#
# 1. **the client**: `boto3`/`botocore` imported by anything under `apps/` that
# is neither the seam nor the readiness probe.
# 2. **the address, the bucket and the credential**: `AWS_STORAGE_BUCKET_NAME`,
# `AWS_S3_ENDPOINT_URL`, `AWS_S3_REGION_NAME`, `AWS_S3_CUSTOM_DOMAIN`,
# `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, named outside the seam and
# outside `config/settings/`, where the environment is read.
# 3. **signing**, and 4. **reading an object's bytes**: `generate_presigned_url`
# / `generate_presigned_post`, `get_object` / `download_fileobj` /
# `download_file`. These are the belt for a module handed a client it did not
# build — no import, no setting, and a signed URL for any key it likes.
#
# AND THE FIFTH DOOR, which is the one that was actually walked through:
# `django.core.files.storage`. `config/settings/base.py` points `STORAGES`
# "default" at `storages.backends.s3.S3Storage` the moment a bucket is named, so
# `default_storage.open()` reads an object's bytes and `default_storage.url()`
# signs a URL — the same two clauses, reached with no boto3 import and no
# setting named anywhere. `apps/exports` wrote its archives exactly that way
# until XPr re-pointed it onto `files.services.store_bytes`, and its key
# grammar (`tenants/<slug>/<uuid>-<name>`) was a key built out of two renamable,
# user-supplied things. This clause is what stops it coming back.
#
# WHAT F1 LEFT, and why this is a rule now: `apps/files/tests/test_storage_fence.py`
# is the census the wall is written against — a hand-pinned set of the modules
# that import the SDK, so a second importer is a line somebody reads. It covers
# clause 1 and only clause 1: a module that names the bucket, signs a URL, reads
# an object or takes the Django storage door passes it in silence. That pin stays
# (it is the app's own doorbell and it fails by NAME); this rule is the other
# four clauses, planted canaries and all.
#
# Every clause is read from the AST rather than the text, which is what makes
# the negatives possible: this module's prose names `AWS_STORAGE_BUCKET_NAME`
# and boto3 repeatedly — it has to, to explain the fence.

# : The names that may not travel: the bucket, the address, the credential.
# : Deliberately NOT here — `AWS_DEFAULT_ACL`, `AWS_QUERYSTRING_AUTH`,
# : `AWS_QUERYSTRING_EXPIRE`, `AWS_S3_FILE_OVERWRITE` — which configure
# : django-storages' behaviour and dial nothing. Naming one is configuration in
# : the wrong file, not a second door, and refusing it would be the rule growing
# : past its reason (rule 33 stays silent on `MEILI_ENV` for the same reason).
STORAGE_SETTINGS = (
    "AWS_STORAGE_BUCKET_NAME",
    "AWS_S3_ENDPOINT_URL",
    "AWS_S3_REGION_NAME",
    "AWS_S3_CUSTOM_DOMAIN",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
)

# : The client libraries the fence exists to confine.
STORAGE_PACKAGES = ("boto3", "botocore")

# : Django's own storage API — the fifth door, and the one this tree has actually
# : used. An import of it under `apps/` is a caller reaching `default_storage`,
# : which `STORAGES` points at the same bucket.
DJANGO_STORAGE_MODULE = "django.core.files.storage"

# : Signing a URL. Both are boto3 client method names and neither collides with
# : the seam's own public API (`presign_get`, `presign_put`).
SIGNING_METHODS = ("generate_presigned_url", "generate_presigned_post")

# : Reading an object's bytes. Also boto3's own names. `delete_object` is
# : deliberately absent: it is ALSO the name of the seam's own public function
# : (`apps/files/storage.py::delete_object`, which `apps/exports/services.py`
# : calls), so a recogniser holding it would fire on the legal door.
OBJECT_READ_METHODS = ("get_object", "download_fileobj", "download_file")

# : The module every other module must go through, and never around.
SEAM_MODULE = "apps.files.storage"
SEAM_REL = SEAM_MODULE.replace(".", "/") + ".py"
STORAGE_KLASS = "storage_client"


def _names_storage_setting(node: ast.AST) -> str | None:
    """Which fenced name this node names, or `None`. **Never prose.**

    The three shapes and exactly three, as rule 33 has them:
    `settings.AWS_STORAGE_BUCKET_NAME` (an attribute), a string constant that IS
    the name (`os.environ["AWS_STORAGE_BUCKET_NAME"]`), and a bare binding,
    which is how a settings module declares one. A docstring that mentions the
    variable is a `Constant` whose value is the whole docstring, so EQUALITY —
    rather than membership — is what keeps this silent on documentation.
    """
    if isinstance(node, ast.Attribute) and node.attr in STORAGE_SETTINGS:
        return node.attr
    if isinstance(node, ast.Name) and node.id in STORAGE_SETTINGS:
        return node.id
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if node.value in STORAGE_SETTINGS else None
    return None


def _imports_any(node: ast.AST, packages: tuple[str, ...]) -> bool:
    """Whether this statement pulls in one of these packages, in either form."""
    if isinstance(node, ast.ImportFrom):
        module = node.module or ""
        return any(module == p or module.startswith(f"{p}.") for p in packages)
    if isinstance(node, ast.Import):
        return any(
            alias.name == p or alias.name.startswith(f"{p}.")
            for alias in node.names
            for p in packages
        )
    return False


def _calls_method(node: ast.AST, names: tuple[str, ...]) -> str | None:
    """The fenced method this call calls on something, or `None`.

    Attribute calls only: `client.generate_presigned_url(...)`. A bare
    `get_object(...)` is a module-level function somebody defined here and is
    not the SDK — the whole point of the clause is a client handed in from
    elsewhere, and a client is always a receiver.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr if node.func.attr in names else None
    return None


def storage_client(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    scope = rule.get("scope") or {}
    importers = [str(e.get("path", "")) for e in scope.get("allow_import") or [] if e.get("path")]
    readers = [str(e.get("path", "")) for e in scope.get("allow_secret") or [] if e.get("path")]

    for path in _py_files(root, "apps", "config"):
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_scanned")
        rel = str(path.relative_to(root))
        is_seam = rel == SEAM_REL
        if is_seam:
            # The module the rule funnels everything into. Its own client, its
            # own settings, its own signing and its own object read are the
            # POINT, and they are counted so that a recogniser which stopped
            # recognising anything trips a floor rather than reporting a clean
            # nothing.
            out.count("seam_module")
        may_import = is_seam or any(rel == e or rel.startswith(e) for e in importers)
        may_read = is_seam or any(rel == e or rel.startswith(e) for e in readers)

        for node in ast.walk(tree):
            named = _names_storage_setting(node)
            if named:
                if may_read:
                    out.count("secret_sites")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"names {named} — the bucket, the address and the credential are read "
                        f"in {SEAM_REL} and declared in config/settings, and nowhere else. An "
                        "object store is a flat key space with no tenancy in it: the only "
                        "thing between one tenant's bytes and another's is the key grammar in "
                        "that module and the prefix belt beside it. Call apps.files.services, "
                        "or add this module to rule 48's allow-list in quality/rules.yaml "
                        "with the reason",
                        klass=STORAGE_KLASS,
                    )
                continue
            if _imports_any(node, STORAGE_PACKAGES):
                if may_import:
                    out.count("sdk_imports")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"imports the AWS SDK — the object store is reached through {SEAM_REL} "
                        "and nowhere else. A client here is a second key space with no grammar "
                        "on it: `version_key` and `refuse_foreign_key` are what keep one "
                        "tenant's bytes out of another's reach, and a client that never met "
                        "them can address any key in the bucket. Call apps.files.services, or "
                        "add this module to rule 48's allow-list in quality/rules.yaml with "
                        "the reason",
                        klass=STORAGE_KLASS,
                    )
                continue
            if _imports_any(node, (DJANGO_STORAGE_MODULE,)):
                if may_import:
                    out.count("storage_api_imports")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"imports {DJANGO_STORAGE_MODULE} — `STORAGES` points `default_storage` "
                        "at the same bucket the moment one is named, so `.open()` reads an "
                        "object's bytes and `.url()` signs a URL with no boto3 import and no "
                        "setting named anywhere. This is the door apps/exports took until XPr, "
                        "under a key built from a renamable slug and a user-supplied filename. "
                        f"Call apps.files.services, or add this module to rule 48's allow-list "
                        "in quality/rules.yaml with the reason",
                        klass=STORAGE_KLASS,
                    )
                continue
            method = _calls_method(node, SIGNING_METHODS)
            if method:
                if may_import:
                    out.count("signing_sites")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"calls {method}() — signing is issuance, and issuance is audited in "
                        f"{SEAM_REL} behind a service that knows whose key it is. A module "
                        "handed a client can sign for any key in the bucket without importing "
                        "anything or naming a setting, which is why the method name is fenced "
                        "as well as the import. Call apps.files.services",
                        klass=STORAGE_KLASS,
                    )
                continue
            method = _calls_method(node, OBJECT_READ_METHODS)
            if method:
                if may_import:
                    out.count("object_reads")
                else:
                    out.hit(
                        rel,
                        getattr(node, "lineno", 1),
                        f"calls {method}() — reading an object's bytes outside {SEAM_REL} is a "
                        "read with no prefix belt in front of it (`refuse_foreign_key`), and "
                        "bytes travelling through Django is the one shape apps/files is built "
                        "to prevent. Call apps.files.services",
                        klass=STORAGE_KLASS,
                    )
    return out


# --- rule 49: every audit emitter declared WHO and WHERE ------------------------
#
# ADR core-22. The audit trail answers NIST SP 800-53 AU-3's content elements off
# columns this table already had — and `core.service.write_audit` takes the WHO
# from the `actor` a service was given AND FROM NOWHERE ELSE, deliberately: the
# bound context has a `user_id` on it and it is ambient observability data, while
# an audit row is a claim. So a service that does not take an actor cannot record
# a person even when a person is standing at the door, and its probe found
# exactly that — `actor_user_id` None on every row of the one compliance-shaped
# table in the product.
#
# WHY A DEFAULT IS THE FAILURE AND AN ABSENCE IS NOT. The decorator reads the
# audited population off the DECLARATION and writes the row from the CALL. A
# service with no `actor` at all is making a claim a reviewer can check — nobody
# asked for this, it is machine work — and the allow-list below is where that
# claim is written down. A service with a DEFAULTED actor is making no claim at
# all: it looks attributed, and it files under nobody the moment one caller
# leaves the argument out, with nothing anywhere recording which callers did.
# That is precisely how `accounts.sync_workforce_identity_config` went unaudited
# under ADR core-8 while its signature said otherwise, and this rule is that
# lesson turned from a paragraph into a check. `tenant` reads the same way, and
# `Tenant | None` with no default is CONFORMANT: nullable is a real declared
# population (core-8 (b)); required-but-nullable made the caller say.
#
# ONE SEAM, IMPORTED AND NEVER MIRRORED. The population is whatever
# `apps.core.service._declares_tenant` says it is — the same predicate `@service`
# reads at decoration time. The probe imports it. A rule that re-implemented "a
# keyword-only parameter named tenant" would be a second opinion about the
# population, and the day the seam moved the rule would enforce the old one and
# report green; the seam breaking is exit 2 here, never an empty census.
#
# THE ALLOW-LIST GROWS ADR-FIRST. Every entry names an enumerated absence in
# core-22 by number and carries its ground. A new exemption is an amendment to
# that ADR and THEN a line here — never a line here because a rung went red.

_AUDIT_PROBE = "quality/audit_population_probe.py"
_AUDIT_KLASS = "audit_shape"


def _audit_allow_list(rule: dict) -> dict[str, str]:
    """`{dotted service name: reason}` off the rule's own scope."""
    scope = rule.get("scope") or {}
    out: dict[str, str] = {}
    for entry in scope.get("enumerated_absence") or []:
        name = str(entry.get("service", "")).strip()
        if name:
            out[name] = str(entry.get("reason", "")).strip()
    return out


def audit_row_shape(root: Path, rule: dict) -> CheckResult:
    """Rule 49. Every audit emitter declares who acted and which workspace.

    Signature tier only, and the boundary is in `does_not_cover`: this sees that
    a service was MADE to be told, never that the door told it the truth. The
    worked counter-example is real and is named there — `TenantAdmin
    .call_service` dropped an actor whose signature was already perfect — and
    `apps/core/tests/test_admin_actor_passthrough.py` is the other half of that
    division of labor.
    """
    out = CheckResult()
    proc = subprocess.run(
        [sys.executable, str(root / _AUDIT_PROBE)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        report = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        report = {}
    if proc.returncode != 0 or not report:
        out.hit(
            _AUDIT_PROBE,
            1,
            "the audited-population probe could not run, so the population is unknown "
            f"and nothing below was measured: {(proc.stderr or '').strip()[:400]}",
            klass=_AUDIT_KLASS,
        )
        return out

    # THE CONSISTENCY CANARY. A seam that could not be imported is enforcement
    # broken, not a clean tree: the census would be empty and an empty census
    # reads as a pass. No counts are emitted on this path, so every floor below
    # is unbound and the gate exits 2 rather than 1.
    if not report.get("seam"):
        out.hit(
            _AUDIT_PROBE,
            1,
            "apps.core.service._declares_tenant could not be imported, so this rule has "
            "no population to check and cannot tell a conformant tree from an empty one: "
            f"{report.get('seam_error', '')}. The rule reads the SEAM and never a copy of "
            "it (ADR core-22); fix the import, never the rule",
            klass=_AUDIT_KLASS,
        )
        return out

    allow = _audit_allow_list(rule)
    every_service = set(report.get("services") or [])
    audited = report.get("audited") or []

    # THE ALLOW-LIST'S OWN CONSISTENCY HALF. An entry naming no service at all is
    # a ghost: it exempts nothing, and it will go on exempting nothing after the
    # name it was written for has gone. Same reasoning as its `_scope_paths`
    # assertion for a path that does not resolve.
    for name in sorted(allow):
        if name not in every_service:
            out.hit(
                "quality/rules.yaml",
                1,
                f"the enumerated-absence list names {name!r}, which is no @service in this "
                "tree — a ghost exemption, covering nothing and outliving its own reason. "
                "Remove it, or fix the name",
                klass=_AUDIT_KLASS,
            )

    for row in audited:
        out.count("audited_services")
        dotted = row["dotted"]
        exempt = dotted in allow
        if exempt:
            out.count("enumerated_absences")
        bad = False
        for parameter in ("actor", "tenant"):
            shape = row[parameter]
            if shape == "required":
                continue
            # AN ENUMERATED ABSENCE IS AN ABSENCE, NEVER A LICENCE TO DEFAULT.
            # The list excuses a service for taking NO actor — a claim a reviewer
            # can read, grounded in a numbered absence in ADR core-22. It cannot
            # excuse a DEFAULT: no absence in that ADR describes a signature that
            # says a person is recorded beside call sites that quietly say
            # otherwise, and letting the list cover it would turn the list into a
            # way to buy silence for the exact shape this rule catches.
            if exempt and shape == "absent":
                continue
            bad = True
            out.count("nonconformant")
            if shape == "absent":
                out.hit(
                    row["file"],
                    row["line"],
                    f"{dotted} writes an AuditEntry (it declares a tenant, so @service "
                    f"audits it) and takes no {parameter} — so the row it writes can never "
                    f"name {'who acted' if parameter == 'actor' else 'which workspace'}. "
                    "Take it as a required keyword-only parameter, or enumerate the service "
                    "in rule 49's absence list with its ADR core-22 absence number (which is "
                    "an amendment to that ADR first, and a line here second)",
                    klass=_AUDIT_KLASS,
                )
            else:
                out.hit(
                    row["file"],
                    row["line"],
                    f"{dotted} DEFAULTS its {parameter}. The decorator reads the audited "
                    "population off the declaration and writes the row from the call, so a "
                    "defaulted parameter is a service that looks attributed and files every "
                    "row under nobody the moment one caller leaves it out — with nothing "
                    "recording which callers did. `X | None` with NO default is fine (a "
                    "nullable value is a real declared population); a default is not. This "
                    "is ADR core-8's sync_workforce lesson, checked",
                    klass=_AUDIT_KLASS,
                )
        if not bad:
            out.count("conformant")
    return out


REGISTRY = {
    "auth_user_import": auth_user_import,
    "signal_logic": signal_logic,
    "query_budget_tests": query_budget_tests,
    "depends_on_imports": depends_on_imports,
    "scoped_reads": scoped_reads,
    "migration_leaves": migration_leaves,
    "migration_expand_contract": migration_expand_contract,
    "workflow_determinism": workflow_determinism,
    "door_writes": door_writes,
    "selector_service_split": selector_service_split,
    "service_shape": service_shape,
    "http_below_doors": http_below_doors,
    "event_grammar": event_grammar,
    "naming_grammar": naming_grammar,
    "workflow_ids": workflow_ids,
    "workflows_close_runs": workflows_close_runs,
    "role_bound_assignment": role_bound_assignment,
    "retry_clock_readers": retry_clock_readers,
    "tenant_blind_index_census": tenant_blind_index_census,
    "secret_at_rest": secret_at_rest,
    "structured_logging": structured_logging,
    "append_only_writes": append_only_writes,
    "org_scoped_reads": org_scoped_reads,
    "supply_chain": supply_chain,
    "mail_imports": mail_imports,
    "service_reach": service_reach,
    "door_reachability": door_reachability,
    "zitadel_client": zitadel_client,
    "meili_client": meili_client,
    "storage_client": storage_client,
    "hot_path_sargability": hot_path_sargability,
    "socket_group_discipline": socket_group_discipline,
    "org_scoped_out_schemas": org_scoped_out_schemas,
    "header_contracts": header_contracts,
    "refusal_block_census": refusal_block_census,
    "outbound_signer_census": outbound_signer_census,
    "ninja_internals_census": ninja_internals_census,
    "mcp_dispatch_surfaces": mcp_dispatch_surfaces,
    "door_pair_parity": door_pair_parity,
    "declared_refusals_documented": declared_refusals_documented,
    "declared_lifecycles": declared_lifecycles,
    "audit_row_shape": audit_row_shape,
}
