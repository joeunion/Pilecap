"""Rule 44: the library internals we hold, censused."""

from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

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
                "tell an upstream rename BEFORE the import tripwire does. Declaring it is "
                "the road that BUYS something — the census then watches the upstream name "
                "for you; `# rule-44: <reason>` on this line is the counted, printed road "
                "that only silences this line and buys nothing, which is why it is named "
                "second",
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


from quality.checks.rule_36 import _is_test_module  # noqa: E402
