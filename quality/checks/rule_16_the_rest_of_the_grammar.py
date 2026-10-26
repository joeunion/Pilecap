"""Rule 16, the rest of the grammar."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from apps.core.lexicon import PLURAL_REMEDY, looks_plural, verb_of
from apps.core.reach import extended_scope
from quality.checks._hub import CheckResult, _app_dirs, _parse
from quality.worlds import base_names, py_files, reaching, service_modules

# --- rule 16, the rest of the grammar -----------------------------------
#
# One rule, seven classes. The events half above is where rule 16 started; the
# six below extend it to the grammar the skills already taught and nothing
# checked. Each class is a CLOSED question with its own population, its own
# floor, its own canary and its own ratchet — measured before it was enforced
# (the retired `naming-grammar-measurement.md` is that measurement, committed
# first). A class with a backlog records the count in `rules.yaml` — a ratchet,
# judged by `quality.worlds.Bound` like every one-way number here.
#
# What is deliberately NOT here: whether a compliant name is a *good* name. A
# service called `create_thing_and_email_someone` starts with a verb in the
# lexicon and passes. That is review's, and it is in `does_not_cover`.

_base_names = base_names


def _scope_list(rule: dict, key: str) -> list[Any]:
    return list((rule.get("scope") or {}).get(key) or [])


def _model_files(root: Path) -> list[Path]:
    """Every module that may define a model: every `.py` under `apps/` the walk reads.

    ONE POPULATION. This used to be the app `models.py` files plus two `core`
    modules named by hand, while five other readers walked every module — so a
    model in `apps/<x>/ledger.py` was a model to one rule and not to another. A
    model is a class that reaches a `*Model` base (`_model_classes`), wherever
    it is defined; the walk's own skips (`SKIP_PARTS`) are the only exclusions.
    """
    # `pilecap` defines no model; read so a base imported through it resolves to its source.
    return py_files(root, "apps", "pilecap")


_ClassKey = tuple[str, str]


def _module_name(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_bindings(tree: ast.Module, module: str, is_package: bool) -> dict[str, str]:
    """{local name: the dotted name it is bound to} for this module's top-level imports."""
    package = module if is_package else module.rpartition(".")[0]
    bindings: dict[str, str] = {}
    stack: list[ast.stmt] = list(tree.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.If, ast.Try)):
            stack.extend(node.body + node.orelse + getattr(node, "finalbody", []))
            for handler in getattr(node, "handlers", []):
                stack.extend(handler.body)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    bindings[alias.asname] = alias.name
                else:
                    head = alias.name.split(".")[0]
                    bindings[head] = head
        elif isinstance(node, ast.ImportFrom):
            source = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                source = ".".join([*anchor, source] if source else anchor)
            for alias in node.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = f"{source}.{alias.name}"
    return bindings


def _model_classes(root: Path) -> list[tuple[Path, ast.ClassDef]]:
    """Module-level classes that reach a Django model base, each judged by its own bases.

    A base is the definition its module's import or class names; an unbound name, every namesake.
    The seed is a `django.*Model` base, or an unbound `*Model`; `pydantic.BaseModel` is no seed.
    """
    modules: dict[str, tuple[Path, ast.Module]] = {}
    for path in _model_files(root):
        tree = _parse(path)
        if isinstance(tree, ast.Module):
            modules[_module_name(root, path)] = (path, tree)
    classes: dict[_ClassKey, tuple[Path, ast.ClassDef]] = {}
    by_name: dict[str, set[_ClassKey]] = {}
    bindings: dict[str, dict[str, str]] = {}
    for module, (path, tree) in modules.items():
        bindings[module] = _import_bindings(tree, module, path.name == "__init__.py")
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                classes[(module, node.name)] = (path, node)
                by_name.setdefault(node.name, set()).add((module, node.name))

    def resolve(dotted: str, depth: int = 0) -> _ClassKey | str:
        module, _, name = dotted.rpartition(".")
        if (module, name) in classes:
            return (module, name)
        if module in modules and name in bindings[module] and depth < 8:
            return resolve(bindings[module][name], depth + 1)
        return dotted

    seed = "<a Django model base>"
    edges: dict[_ClassKey, set[_ClassKey | str]] = {}
    for (module, _name), (_path, node) in classes.items():
        targets: set[_ClassKey | str] = set()
        for base in node.bases:
            cur: ast.expr = base
            while isinstance(cur, ast.Subscript):
                cur = cur.value
            parts: list[str] = []
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if not isinstance(cur, ast.Name):
                continue
            parts.append(cur.id)
            parts.reverse()
            head = parts[0]
            if len(parts) == 1 and (module, head) in classes:
                targets.add((module, head))
            elif head in bindings[module]:
                found = resolve(".".join([bindings[module][head], *parts[1:]]))
                if isinstance(found, tuple):
                    targets.add(found)
                elif found.startswith("django.") and found.endswith("Model"):
                    targets.add(seed)
            elif len(parts) == 1 and head in by_name:
                targets.update(by_name[head])
            elif parts[-1].endswith("Model"):
                targets.add(seed)
        edges[(module, _name)] = targets
    resolved = reaching(edges, {seed})
    return [found for key, found in classes.items() if key in resolved]


def _module_functions(path: Path) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = _parse(path)
    if tree is None:
        return []
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _starts_with_verb(name: str, verbs: list[str]) -> bool:
    """Whether `name` begins with a declared verb — `apps.core.lexicon.verb_of`, the one matcher.

    The longest-prefix match the machine door and the history card ask through
    too, so a declared two-word verb (`dead_letter`) reads as the verb phrase
    it is and the gate cannot answer differently from the runtime.
    """
    return verb_of(name, verbs) in set(verbs)


def _field_assignments(
    node: ast.ClassDef,
) -> list[tuple[int, str, ast.expr]]:
    """(line, name, value) for every `x = ...` / `x: T = ...` in a class body."""
    out: list[tuple[int, str, ast.expr]] = []
    for stmt in node.body:
        names, value = _assigned(stmt)
        if len(names) == 1 and value is not None:
            out.append((stmt.lineno, names[0], value))
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
        for entry in extended_scope(root, rule).get("app_name_exemptions") or []
        if entry.get("app")
    }
    for app in _app_dirs(root):
        out.count("apps_named")
        if app.name in app_exempt:
            continue
        if not looks_plural(app.name):
            out.hit(
                str((app / "apps.py").relative_to(root)),
                1,
                f"app {app.name!r} is not plural — an app is a collection of things "
                f"(`orders`, not `order`). {PLURAL_REMEDY} (its `app_name_exemptions`); "
                "`# rule-16: <reason>` on line 1 of this apps.py is the cheap road when it "
                "is this one app, counted and printed",
                klass="apps",
            )

    # --- models are singular, and their booleans are is_/has_ -----------------
    models = _model_classes(root)
    for path, node in models:
        rel = str(path.relative_to(root))
        out.count("model_names")
        if looks_plural(node.name):
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
    # At call time: `quality.engine` imports this package, so a module-level import is a cycle.
    from quality.engine.lexicon import PRODUCT_VERBS_KEY, RULES_DRAWER, service_verb_lexicon

    lexicon = service_verb_lexicon(root, (str(v) for v in _scope_list(rule, "service_verbs")))
    verbs = sorted(lexicon, key=len, reverse=True)
    for path in (p for app in _app_dirs(root) for p in service_modules(root, app=app.name)):
        for node in _module_functions(path):
            if node.name.startswith("_"):
                continue  # a private helper is the inside of a service, not a capability
            out.count("service_names")
            if not _starts_with_verb(node.name, verbs):
                out.hit(
                    str(path.relative_to(root)),
                    node.lineno,
                    f"service {node.name!r} does not begin with a declared verb — a service "
                    "is something somebody DOES. Three roads, cheapest first: if this is a "
                    f"private helper rather than a capability, rename it `_{node.name}` and "
                    "it leaves the population outright; if this one function is the "
                    "exception, record `# rule-16: <reason>` on its `def` line (or the "
                    "contiguous comment block above it), which is counted and printed on "
                    "every run; if the LEXICON is what is wrong, a product adds the verb "
                    f"under `{PRODUCT_VERBS_KEY}:` in {RULES_DRAWER}, and the template to "
                    "`service_verbs` in rules.yaml, which widens it for every product forever",
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


from quality.checks.rule_13_clauses_i_iv import _assigned  # noqa: E402
from quality.checks.rule_16 import event_grammar  # noqa: E402
