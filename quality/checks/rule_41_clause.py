"""Rule 41's clause: the refusal block against the raise sites."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import _parse, _py_files

# --- registry ------------------------------------------------------------------

# --- rule 41's clause: the refusal block against the raise sites ---------
#
# It is a CLAUSE ON RULE 41 rather than a rule of its own because it
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
    return {name: code for name, (code, _rel, _line) in _refusal_code_sites(root).items()}


def _refusal_code_sites(root: Path) -> dict[str, tuple[str, str, int]]:
    """{class name: (code, relpath, line)} — the tree's one reading of the refusal registry."""
    out: dict[str, tuple[str, str, int]] = {}
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
                # An EMPTY code is a base that declares none (`DomainError`):
                # not a code, so not a member of the registry's population.
                if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
                    rel = path.relative_to(root).as_posix()
                    out[node.name] = (value.value, rel, statement.lineno)
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


def _reexported(root: Path, dotted: str, name: str) -> tuple[str, str]:
    """The module and name that define `dotted.name`, one re-export hop through a package."""
    init = root.joinpath(*dotted.split("."), "__init__.py")
    tree = _parse(init) if init.is_file() else None
    if tree is None:
        return dotted, name
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return dotted, name
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if node.level:
            parts = dotted.split(".")
            module = ".".join([*parts[: len(parts) - node.level + 1], module])
        if not module.startswith(f"{dotted}."):
            continue
        for alias in node.names:
            if (alias.asname or alias.name) == name:
                return module.rstrip("."), alias.name
    return dotted, name


def _function_in(root: Path, dotted: str, name: str) -> ast.AST | None:
    """The body of a first-party function named by a resolved call, or None."""
    if not (dotted.startswith("apps.") or dotted.startswith("config.")):
        return None
    dotted, name = _reexported(root, dotted, name)
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


def _added_refusals(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, ...]:
    """The codes a route's `@also_refuses(...)` ADDS to the set it publishes anyway."""
    for dec in node.decorator_list:
        if not isinstance(dec, ast.Call):
            continue
        target = dec.func
        name = _callee_name(target)
        if name == "also_refuses":
            return tuple(
                arg.value
                for arg in dec.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            )
    return ()


# : The ONE module whose raises the reach follows a second hop into: the family
# : seams every noun's service calls (`archive_row`, `require_live`, `rehome`,
# : `merge_rows`, …). A noun's `@service` is one call below its route and the
# : seam is one call below that, so a one-hop walk could never see the family's
# : refusals and every adopter paid a `# rule-41:` valve for it. Closed by the
# : module, never a list of function names.
_SECOND_HOP_MODULE = "apps.core.verbs"


def _second_hop_codes(root: Path, codes_by_class: dict[str, str]) -> dict[str, set[str]]:
    """{function name: the codes it raises} for every top-level function of the seam module."""
    tree = _parse(root.joinpath(*_SECOND_HOP_MODULE.split(".")).with_suffix(".py"))
    if tree is None:
        return {}
    return {
        node.name: _raised_codes(node, codes_by_class)
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


#: The router methods that bind a route — the one spelling of "this is a route".
ROUTE_METHODS = frozenset({"get", "post", "patch", "put", "delete"})


def _is_route_decorator(dec: ast.expr) -> bool:
    """Whether one decorator binds a route: `@router.<method>(…)`."""
    target = dec.func if isinstance(dec, ast.Call) else dec
    return isinstance(target, ast.Attribute) and target.attr in ROUTE_METHODS


def _route_decorators(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[bool, tuple[str, ...] | None]:
    """(is a route, the `@refuses(...)` codes or None for an unnarrowed one)."""
    is_route = False
    declared: tuple[str, ...] | None = None
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if _is_route_decorator(dec):
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


from quality.checks.rule_36 import _callee_name  # noqa: E402
