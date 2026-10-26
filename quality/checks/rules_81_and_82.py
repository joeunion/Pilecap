"""Rules 81 and 82: the archive's two quiet traps."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _exempt, _parse, _py_files, _read
from quality.worlds import decorator_names, fixed_point, service_modules

# --- rules 81 and 82: the archive's two quiet traps -----------------------------
#
# Both populations are `declared_marker_classes(root, "archivable", "Archivable")`
# — rule 76's resolver shape, by class name to a fixed point over `apps/`.

_ARCHIVABLE_ATTR = "archivable"
_ARCHIVABLE_MIXIN = "Archivable"
_ARCHIVED_AT = "archived_at"
#: The one module whose own widenings ARE the widenings (`including_archived`,
#: `archived_only`), and so the one module rule 81 does not read.
_WIDENINGS_MODULE = "apps/core/models.py"


def _names_the_archive_column(call: ast.Call) -> str | None:
    """The `archived_at` lookup a `.filter(...)` / `.exclude(...)` keyword spells, or None."""
    for keyword in call.keywords:
        if keyword.arg and (
            keyword.arg == _ARCHIVED_AT or keyword.arg.startswith(f"{_ARCHIVED_AT}__")
        ):
            return keyword.arg
    return None


def archive_widenings_are_the_only_widenings(root: Path, rule: dict) -> CheckResult:
    """Rule 81. An archivable noun's archived rows are reached only through its widenings.

    `for_tenant()` leaves archived rows out, so a hand filter on `archived_at`
    after it — `.filter(archived_at__isnull=False)`, `.exclude(archived_at=None)`
    — answers `[]` with no error: the rows it asks for were removed a step
    earlier. `.archived_only()` and `.including_archived()` are the only roads.
    A `.filter(...)` / `.exclude(...)` whose keyword names `archived_at`, on a
    queryset rooted at an archivable class, fires.
    """
    out = CheckResult()
    archivable = declared_marker_classes(root, _ARCHIVABLE_ATTR, _ARCHIVABLE_MIXIN)
    out.count("archivable_classes", len(archivable))
    models_only = sorted(archivable - {_ARCHIVABLE_MIXIN})
    for path in _py_files(root, "apps"):
        rel = path.relative_to(root).as_posix()
        if rel == _WIDENINGS_MODULE or _is_test_module(rel) or "/migrations/" in rel:
            continue
        if _exempt(rule, rel):
            continue
        text = _read(path)
        if _ARCHIVED_AT not in text:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        out.count("files_read")
        for model in models_only:
            if not re.search(rf"\b{re.escape(model)}\b", text):
                continue
            qs_names, helpers = _queryset_bindings(tree, model)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in ("filter", "exclude"):
                    continue
                lookup = _names_the_archive_column(node)
                if lookup is None:
                    continue
                if not _queryset_rooted(node.func.value, model, qs_names, helpers):
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    f"`.{node.func.attr}({lookup}=…)` on the archivable {model} — `for_tenant()` "
                    "already left the archived rows out, so this answers nothing and says "
                    "nothing. Ask with `.archived_only()` (the archived cut) or "
                    "`.including_archived()` (both), the only widenings (house rule 81).",
                )
    return out


def _service_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and "service" in decorator_names(node)
    ]


def _calls_require_live(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = _callee_name(func)
        if name == "require_live":
            return True
    return False


def archivable_writes_require_live(root: Path, rule: dict) -> CheckResult:
    """Rule 82. A writing `@service` on an archivable noun calls `require_live`, or is the pair.

    An archived row's writes other than its restore refuse `archived`
    (`core.verbs.require_live`) — but only where the service calls it, so a
    service that forgot edits a row nobody can see in the book. A `@service`
    in `apps/*/services.py` named for a keyword parameter annotated by an
    archivable class (by name) — `<verb>_<param>(*, <param>: Noun)`, a write ON
    that row — that is not the `archive_`/`restore_` pair, and whose body calls
    no `require_live(`, fires.
    """
    out = CheckResult()
    archivable = declared_marker_classes(root, _ARCHIVABLE_ATTR, _ARCHIVABLE_MIXIN)
    out.count("archivable_classes", len(archivable))
    models_only = archivable - {_ARCHIVABLE_MIXIN}
    for path in service_modules(root):
        rel = path.relative_to(root).as_posix()
        if _is_test_module(rel) or _exempt(rule, rel):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for fn in _service_functions(tree):
            out.count("services_read")
            # The row the service is ABOUT: a keyword parameter annotated by an
            # archivable class whose NAME the service's own name ends with —
            # `suppress_recipient(*, recipient: Recipient)`, `frob_widget(*,
            # widget: Widget)`. A service that takes the row as a reference to
            # write something else (`send(*, recipient)` writes a message,
            # `create_widget(*, policy)` a widget) is not a write on it.
            held = sorted(
                {
                    name
                    for argument in fn.args.kwonlyargs
                    if fn.name.endswith(f"_{argument.arg}")
                    for name in _annotation_names(argument.annotation) & models_only
                }
            )
            if not held:
                continue
            out.count("archivable_services")
            if fn.name.startswith(("archive_", "restore_")):
                continue
            if _calls_require_live(fn):
                continue
            out.hit(
                rel,
                fn.lineno,
                f"{fn.name} takes a {', '.join(held)} — archivable — and never calls "
                "`require_live(...)`, so it writes an archived row in place: a change nobody "
                "can see in the book. Call `core.verbs.require_live(row, noun=…)` before the "
                "write, or record `# rule-82: <reason>` when this service writes something "
                "that is not the row (house rule 82).",
                klass="unguarded_write",
            )
    return out


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


# : The methods whose answer is a ROW or a plain value, never a queryset. A name
# : bound to one of these does not hold a member's queryset, so `.update(...)`
# : on it is not this rule's subject — `aggregate(...)` and `in_bulk(...)` hand
# : back a dict, and `dict.update` is the over-fire this list exists to keep out.
_NOT_A_QUERYSET = (
    "aggregate",
    "count",
    "create",
    "earliest",
    "exists",
    "first",
    "get",
    "get_or_create",
    "in_bulk",
    "last",
    "latest",
    "update_or_create",
)


def _queryset_rooted(node: ast.expr, model: str, names: set[str], helpers: set[str]) -> bool:
    """Whether `node` is a queryset of `model`, walked down to its root.

    The receiver forms the word-bounded match cannot see, because the model's
    name is not in them: a name BOUND to the member's manager
    (`entries = AuditEntry.objects.for_tenant(t)`, then `entries.update(...)`),
    a name bound from such a name (`qs = entries.filter(...)`), and a call to a
    function in the same module whose every return is one
    (`_errors(t).update(...)`). The walk follows calls, attribute reads and
    slices down to a root; the root is the model itself, a bound name, or a
    call to such a helper.
    """
    while True:
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in helpers:
                return True
            node = node.func
        elif isinstance(node, ast.Attribute):
            if node.attr == model:
                return True
            node = node.value
        elif isinstance(node, ast.Subscript):
            # A SLICE answers a queryset (`qs[:10]`); an INDEX answers one row
            # (`qs.values()[0]` is a dict), and a row is not a queryset.
            if not isinstance(node.slice, ast.Slice):
                return False
            node = node.value
        elif isinstance(node, ast.Name):
            return node.id == model or node.id in names
        else:
            return False


def _is_queryset_value(value: ast.expr, model: str, names: set[str], helpers: set[str]) -> bool:
    """A binding's value that holds a queryset of `model` — not a row, not a dict."""
    if isinstance(value, ast.Call):
        func = value.func
        # A bare call on the model class is a construction: a row, not a queryset.
        if (isinstance(func, ast.Name) and func.id == model) or (
            isinstance(func, ast.Attribute) and func.attr == model
        ):
            return False
        if isinstance(func, ast.Attribute) and func.attr in _NOT_A_QUERYSET:
            return False
        if isinstance(func, ast.Name) and func.id not in helpers:
            # `list(qs)`, `len(qs)` — a builtin over a queryset is not one.
            return False
    elif isinstance(value, ast.Attribute):
        # Only the manager itself: `AuditEntry.objects`. A column read off a
        # row (`entry.metadata`) is not a queryset.
        if value.attr != "objects":
            return False
    elif not isinstance(value, (ast.Name, ast.Subscript)):
        return False
    return _queryset_rooted(value, model, names, helpers)


def _queryset_bindings(tree: ast.Module, model: str) -> tuple[set[str], set[str]]:
    """(names bound to a queryset of `model`, same-module functions returning one).

    Walked to a fixed point, because each feeds the other: a helper may return
    a bound name, and a name may be bound from a helper. The same over-reach as
    `_names_bound_to` and in the same direction — a name bound in one function
    and rewritten in another is still caught.
    """
    names: set[str] = set()
    helpers: set[str] = set()
    functions = [
        n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    def grow() -> bool:
        changed = False
        for node in ast.walk(tree):
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, (ast.AnnAssign, ast.NamedExpr)) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None or not _is_queryset_value(value, model, names, helpers):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in names:
                    names.add(target.id)
                    changed = True
        for fn in functions:
            if fn.name in helpers:
                continue
            returns = [
                r.value for r in ast.walk(fn) if isinstance(r, ast.Return) and r.value is not None
            ]
            if returns and all(_is_queryset_value(v, model, names, helpers) for v in returns):
                helpers.add(fn.name)
                changed = True
        return changed

    fixed_point(grow)
    return names, helpers


from quality.checks.rule_26 import _annotation_names  # noqa: E402
from quality.checks.rule_36 import _callee_name, _is_test_module  # noqa: E402
from quality.checks.rule_76 import declared_marker_classes  # noqa: E402
