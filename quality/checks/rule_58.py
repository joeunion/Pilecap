"""Rule 58: socket join discipline (R4 F1; ADR realtime-2)."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 58: socket join discipline (R4 F1; ADR realtime-2) -------------------
#
# THE FINDING. `apps/realtime/consumers.py` says "nobody names their own group"
# and it was a convention for ONE consumer. A planted `consumers.py` in `apps/example/`
# doing `group_add(f"tenant.{query['tenant']}")` and `accept()`, mounted bare in
# `websocket_urlpatterns`, is discovered by `config/asgi.py` like any other, is
# accepted with NO credential, and hears that tenant's events. Rule 36 reads
# `group_send` sites — the PUSH side — and nothing read the JOIN side at all;
# rule 46 asks only for a `DOOR_PAIR` marker, and its own `does_not_cover` says
# so in capitals ("THE MARKER PROVES EXISTENCE, NEVER STRENGTH"), so the whole
# gate answer to a second consumer was one line in a test file.
#
# TWO CLASSES, because the plant is two independent defects and closing either
# one alone still leaves a door. A consumer that derives its groups correctly and
# is mounted with no authentication is an anonymous subscriber to real branches;
# a consumer behind `token_auth` that names its own group reads somebody else's
# tenant with a valid credential of its own.

#: The three group names the bridge derives, and the only names a `group_add`
#: may take. A constant rather than an import: these checks run without Django
#: and never import `apps.*`. MOVE-TRIGGER: the day `apps/realtime/bridge.py`
#: grows a fourth builder, or the three move out of it.
_GROUP_BUILDERS = ("tenant_group", "org_group", "user_group")

#: The base every socket consumer extends, the wrapper every mounted pattern
#: passes through, and the module-level list `config/asgi.py` discovers.
_CONSUMER_BASE = "TenantEventsConsumer"
_SOCKET_AUTH_WRAPPER = "token_auth"
_PATTERN_LIST = "websocket_urlpatterns"
_PATTERN_CALLS = {"path", "re_path"}


def _is_derived_group(node: ast.expr | None, derived: set[str]) -> bool:
    """Whether this expression provably holds one of the bridge's derived names.

    Fail-closed by construction: a direct call to a builder, a Name the scope
    bound to one, or a collection/comprehension every element of which is one.
    Anything else — an f-string, a `.format`, a parameter, a name from another
    module — is a finding, which is the same reading rule 55 takes of a node.
    """
    if isinstance(node, ast.Call):
        return _callee_name(node.func) in _GROUP_BUILDERS
    if isinstance(node, ast.Name):
        return node.id in derived
    if isinstance(node, ast.Starred):
        return _is_derived_group(node.value, derived)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return bool(node.elts) and all(_is_derived_group(e, derived) for e in node.elts)
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
        return _is_derived_group(node.elt, derived)
    return False


def _nodes_in_scope(body: list[ast.stmt]) -> list[ast.AST]:
    """Every node in these statements, NOT descending into a nested scope.

    Per-scope rather than per-module, so a name bound to a derived group in one
    function cannot excuse a same-named f-string in another — which is exactly
    the laundering shape the rule exists to refuse.
    """
    out: list[ast.AST] = []
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        out.append(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            stack.append(child)
    return out


def _derived_in(body: list[ast.stmt], seed: set[str]) -> set[str]:
    """Every name THIS scope binds to a derived group name, seeded from above.

    Three passes rather than one because the real consumer launders through two
    hops the right way round — a list of builder calls, then a `for` over that
    list — and the order `ast` hands the statements back in is not the order
    they execute in. A fixpoint is cheap over a function body and does not care.
    """
    derived = set(seed)
    for _ in range(3):
        before = set(derived)
        for node in _nodes_in_scope(body):
            if isinstance(node, ast.Assign) and _is_derived_group(node.value, derived):
                derived.update(t.id for t in node.targets if isinstance(t, ast.Name))
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and _is_derived_group(node.value, derived)
            ):
                derived.add(node.target.id)
            elif (
                isinstance(node, (ast.For, ast.AsyncFor))
                and isinstance(node.target, ast.Name)
                and _is_derived_group(node.iter, derived)
            ):
                derived.add(node.target.id)
        if derived == before:
            break
    return derived


def _scope_bodies(tree: ast.Module) -> list[tuple[list[ast.stmt], set[str]]]:
    """(body, seed) for the module scope and for every function in it."""
    top = [
        stmt
        for stmt in tree.body
        if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    module_names = _derived_in(top, set())
    scopes: list[tuple[list[ast.stmt], set[str]]] = [(top, set())]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scopes.append((node.body, module_names))
    return scopes


def _module_bindings(tree: ast.Module) -> dict[str, ast.expr]:
    """Module-level `name = <expr>`, so a pattern's application can be resolved."""
    bindings: dict[str, ast.expr] = {}
    for node in tree.body:
        names, value = _assigned(node)
        if value is not None:
            for name in names:
                bindings[name] = value
    return bindings


def _resolve_binding(node: ast.expr | None, bindings: dict[str, ast.expr]) -> ast.expr | None:
    """Follow module-level names to the expression they hold. Bounded at 5 hops."""
    seen: set[str] = set()
    for _ in range(5):
        if not isinstance(node, ast.Name) or node.id in seen or node.id not in bindings:
            return node
        seen.add(node.id)
        node = bindings[node.id]
    return node


def _consumer_classes(tree: ast.Module) -> dict[str, list[str]]:
    """{class name: base names} for every class this module declares."""
    return {
        node.name: [_callee_name(base) or "" for base in node.bases]
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
    }


def _extends_the_base(name: str, classes: dict[str, list[str]]) -> bool:
    """Whether this class IS the base, or reaches it through this module's bases."""
    seen: set[str] = set()
    pending = [name]
    while pending:
        current = pending.pop()
        if current == _CONSUMER_BASE:
            return True
        if current in seen:
            continue
        seen.add(current)
        pending.extend(classes.get(current, []))
    return False


def _as_asgi_class(node: ast.expr | None) -> str | None:
    """The class name behind an `X.as_asgi()` somewhere in this expression."""
    if node is None:
        return None
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "as_asgi"
            and isinstance(sub.func.value, ast.Name)
        ):
            return sub.func.value.id
    return None


def _pattern_entries(tree: ast.Module) -> list[ast.Call]:
    """Every `path(...)` / `re_path(...)` in a module-level `websocket_urlpatterns`."""
    entries: list[ast.Call] = []
    for node in tree.body:
        names, value = _assigned(node)
        if not names:
            continue
        if _PATTERN_LIST not in names or not isinstance(value, (ast.List, ast.Tuple)):
            continue
        entries.extend(
            element
            for element in value.elts
            if isinstance(element, ast.Call) and _callee_name(element.func) in _PATTERN_CALLS
        )
    return entries


def socket_join_discipline(root: Path, rule: dict) -> CheckResult:
    """Rule 58. Nobody names their own group, and nobody mounts an open socket.

    Two classes over `apps/`, both exact-shape for the reason rule 36 gives about
    its own subject: the population is small, derived from the tree, and a
    heuristic here would be a guess about who may read a tenant.

    * **`join`** — every `group_add` takes its group from one of the bridge's
      three derived builders, directly or through a name this scope bound to one.
    * **`mount`** — every entry in a discovered `websocket_urlpatterns` wraps its
      application in `token_auth(...)` and names a consumer that extends
      `TenantEventsConsumer`.
    """
    out = CheckResult()
    for path in _py_files(root, "apps"):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))

        for body, seed in _scope_bodies(tree):
            derived = _derived_in(body, seed)
            for node in _nodes_in_scope(body):
                if not isinstance(node, ast.Call) or _callee_name(node.func) != "group_add":
                    continue
                out.count("group_add_sites")
                group = node.args[0] if node.args else None
                if _is_derived_group(group, derived):
                    continue
                out.hit(
                    rel,
                    node.lineno,
                    "this `group_add` names its own group rather than taking one of the "
                    "bridge's three derived names (`tenant_group`, `org_group`, "
                    "`user_group`). A group name built here is a subscription to whatever "
                    "the expression evaluates to — a tenant the caller chose, spelled from "
                    "a query string — and the fan-out cannot tell it from a real one. "
                    "Derive the name, or say why on the line",
                    klass="join",
                )

        bindings = _module_bindings(tree)
        classes = _consumer_classes(tree)
        for entry in _pattern_entries(tree):
            out.count("consumer_patterns")
            application = entry.args[1] if len(entry.args) > 1 else None
            resolved = _resolve_binding(application, bindings)
            wrapped = (
                isinstance(resolved, ast.Call)
                and _callee_name(resolved.func) == _SOCKET_AUTH_WRAPPER
            )
            if not wrapped:
                out.hit(
                    rel,
                    entry.lineno,
                    f"this socket pattern is not wrapped in `{_SOCKET_AUTH_WRAPPER}(...)`, so "
                    "the only credential it can have is whatever the session stack happened "
                    "to resolve — which for a machine client is `AnonymousUser`. "
                    "`config/asgi.py` discovers this pattern like any other and mounts it: "
                    "an unwrapped consumer that accepts is an anonymous door onto a tenant. "
                    f"Wrap it — `path(ROUTE, {_SOCKET_AUTH_WRAPPER}(Consumer.as_asgi()))`",
                    klass="mount",
                )
            named = _as_asgi_class(resolved)
            if named is None or not _extends_the_base(named, classes):
                out.hit(
                    rel,
                    entry.lineno,
                    f"this socket pattern does not name a consumer extending "
                    f"`{_CONSUMER_BASE}` ({named or 'no `as_asgi()` call'}). That base is "
                    "where the three refusals live — no principal, no tenant, no "
                    "self-named group — and a consumer written beside it inherits none of "
                    "them however carefully it is reviewed. Subclass it, or say why on the "
                    "line",
                    klass="mount",
                )
    return out


from quality.checks.rule_13_clauses_i_iv import _assigned  # noqa: E402
from quality.checks.rule_36 import _callee_name  # noqa: E402
