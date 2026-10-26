"""Rule 13, clauses (i)–(iv): the KIND a service writes vs the KEY it asks."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from quality.checks._hub import _WRITE_MANAGER_CALLS, CheckResult, Finding, _app_dirs, _parse
from quality.worlds import comment_reason

# --- rule 13, clauses (i)–(iv): the KIND a service writes vs the KEY it asks --
#
# The three clauses above are about the SHAPE of a service;
# these four are about its SUBJECT, and they exist because a `require` proves
# only that somebody asked something — never that they asked about the thing
# they then wrote. `create_widget` guarded by `widget_policy.create` is a
# perfectly shaped service that authorizes the wrong noun, and every layer in
# this tree reads as green over it.
#
# The four clauses, and the closed question each is:
#
# (i)   WHAT A SERVICE WRITES, as a kind. An AST model registry read off the
#       app `models.py` files — `authz_kind` (a string, or `None` to opt out),
#       `authz_kind_of` (the owned child, authorized under its aggregate's
#       kind), else `snake_case(ClassName)`, which is `apps.core.authz`'s own
#       derivation re-derived here. NEVER an import of Django: this check runs
#       inside the gate process, and the self-test plants a `models.py` and
#       re-runs it in the same process, which a cached `django.setup()` could
#       not see.
# (ii)  WHAT A SERVICE ASKS FOR, as a key. Every string literal that is the
#       SECOND positional argument of `require(`/`allows(`/`holds(`, plus a
#       `Name` bound at module level to a string constant (PM Overrule 4,
#       2026-09-15 — `apps/workflows/services.py` asks through four of them and
#       a literals-only reading would have called the whole app unguarded).
# (iii) A WRITTEN KIND THE SERVICE NEVER ASKED ABOUT is a finding, on the write
#       line, unless that line carries `# authz-kind: <reason>`. The population
#       is the services that ASK AT LEAST ONE KEY: a service that asks nothing
#       at all is the clause above's subject and carries `# authz:` — see the
#       `does_not_cover` note in rules.yaml, which says so rather than leaving
#       a reader to infer it from silence.
# (iv)  A REQUIRED KEY THAT IS IN NO VOCABULARY is a finding, on the ask line;
#       so is a key that is neither a literal nor a module constant, unless it
#       carries `# authz-key: <reason>`. The key set is RE-DERIVED here from
#       `apps/*/models.py` (the four CRUD verbs per kind) and `apps/*/policies.py`
#       (`ACTION_PROSE`, `RENAMED_PERMISSIONS`) rather than imported — the same
#       reason as (i) — and rule 54 (a) is where the re-derivation is proved to
#       agree with `apps.core.authz.vocabulary()` itself.
#
# Findings are classed per app — `<app>` for (iii), `<app>.key` for (iv) — so
# one app's standing backlog cannot pay for another app's growth, and so a NEW
# undeclared key in an app with a clause-(iii) ratchet is still a violation
# from the first one. The ratchets are in rules.yaml with the tree they were
# measured on.

#: `# authz-kind: <reason>` — the valve on clause (iii), on the write line or
#: in the contiguous comment block above it. `# authz-key: <reason>` is (iv)'s.
#: Both are counted and printed on the rule's own status line: a valve nobody
#: counts is an off switch.
#: Rule 13's service valve: `# authz: <reason>`. The colon is required, so the
#: two siblings below (`authz-kind`, `authz-key`) are never read as this one.
_AUTHZ_RE = re.compile(r"#\s*authz:\s*(.*)$")
_AUTHZ_KIND_RE = re.compile(r"#\s*authz-kind:\s*(.*)$")
_AUTHZ_KEY_RE = re.compile(r"#\s*authz-key:\s*(.*)$")

#: The bases that make a class in a `models.py` a model. The same four names
#: `org_scoped_model_names` walks from, widened by the two a concrete model may
#: sit directly on — a class whose base is itself in the registry is in too, so
#: a product's own intermediate base needs no entry here.
_MODEL_BASE_NAMES = frozenset({"Model", "BaseModel", "TenantScopedModel", "OrgScopedModel"})
#: `apps.core.authz.CRUD_VERBS`, re-derived. The four verbs every kind gets.
_CRUD_VERBS = ("create", "read", "update", "delete")
#: `apps.core.models.AUTHZ_KIND_DERIVED` — the sentinel that means "derive it".
_AUTHZ_KIND_DERIVED = "*derive*"
#: `apps.core.authz.RESERVED_PERMISSIONS` — core's own, which no model derives.
_RESERVED_KEYS = frozenset({"tenant.own"})
#: The three functions that ask. `holds(actor, key, at=...)` takes its key
#: second exactly as the other two do, which is what makes one reading enough.
_ASK_FUNCTIONS = frozenset({"require", "allows", "holds"})
_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _snake_kind(name: str) -> str:
    """`WidgetEntry -> widget_entry`. `apps.core.authz.snake_case`, re-derived."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def _class_base_names(node: ast.ClassDef) -> set[str]:
    """The last segment of every base's dotted name, subscripts unwrapped."""
    out: set[str] = set()
    for base in node.bases:
        cur: ast.expr = base
        while isinstance(cur, ast.Subscript):
            cur = cur.value
        if isinstance(cur, ast.Attribute):
            out.add(cur.attr)
        elif isinstance(cur, ast.Name):
            out.add(cur.id)
    return out


def _class_level_value(node: ast.ClassDef, name: str) -> ast.expr | None | str:
    """The expression a class body assigns to `name`; the string `"absent"` when
    it assigns none. Three-valued on purpose: `authz_kind = None` is a
    DECLARATION (the opt-out) and must not read as "never mentioned"."""
    for stmt in node.body:
        names, value = _assigned(stmt)
        target = names[0] if len(names) == 1 else None
        if target == name:
            return value
    return "absent"


def _owned_child_declaration(
    value: ast.expr | None | str, module_constants: dict[str, str]
) -> tuple[bool, str | None]:
    """`authz_kind_of`, read the way `apps.core.authz` reads it, in one place.

    Returns `(declares, field)`:

    * `declares` mirrors the registry's `getattr(model, "authz_kind_of", None)
      is not None` EXACTLY — the two shapes that are NOT a declaration are the
      class never mentioning the attribute (`_class_level_value`'s `"absent"`
      sentinel, and its bare `None` for an annotation carrying no value) and
      the class binding it to the literal `None`, which is the abstract base's
      own default restated and leaves `getattr` answering `None`.
    * `field` is the foreign key's NAME when this walk can resolve one: a
      string literal, or a module-level constant bound to a string. It is
      `None` when the declaration is real but unreadable here, which leaves the
      caller to fall back rather than to guess.

    ONE function because the two readers of this attribute drifted apart twice:
    a skip that asked for a literal where the registry asked for any value, and
    a resolver that asked the same narrow question one screen away. Both halves
    now read this, so a third reader cannot open the gap again.
    """
    if value is None or value == "absent":
        return False, None
    if isinstance(value, ast.Constant):
        if value.value is None:
            return False, None
        return True, value.value if isinstance(value.value, str) else None
    if isinstance(value, ast.Name):
        return True, module_constants.get(value.id)
    return True, None


def _model_facts(root: Path) -> dict[str, dict[str, Any]]:
    """Every concrete model this tree defines, by class name, read by AST.

    The population is `_model_classes` — every module-level class under
    `apps/` that reaches a `*Model` base, judged per definition — which is the
    same population rule 16's naming grammar reads, so the two cannot come to
    disagree about what a model is.
    """
    facts: dict[str, dict[str, Any]] = {}
    by_path: dict[Path, list[ast.ClassDef]] = {}
    for model_path, model_node in _model_classes(root):
        by_path.setdefault(model_path, []).append(model_node)
    for path, nodes in by_path.items():
        parts = path.relative_to(root).parts
        app = parts[1] if len(parts) > 1 else ""
        tree = _parse(path)
        if tree is None:
            continue
        # `authz_kind_of = PARENT_KIND` is the ordinary way to bind a foreign
        # key's name once rather than spell it twice, so the module's own string
        # constants are part of reading this file's declarations.
        module_constants = _module_string_constants(tree)
        for node in nodes:
            abstract = False
            for stmt in node.body:
                if isinstance(stmt, ast.ClassDef) and stmt.name == "Meta":
                    for inner in stmt.body:
                        if isinstance(inner, ast.Assign) and any(
                            getattr(t, "id", "") == "abstract" for t in inner.targets
                        ):
                            abstract = bool(getattr(inner.value, "value", False))
            foreign_keys: dict[str, str | None] = {}
            for stmt in node.body:
                if not (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, ast.Call)
                ):
                    continue
                func = stmt.value.func
                called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if called not in ("ForeignKey", "OneToOneField"):
                    continue
                first = stmt.value.args[0] if stmt.value.args else None
                target = None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    target = first.value.split(".")[-1]
                elif isinstance(first, ast.Name):
                    target = first.id
                foreign_keys[stmt.targets[0].id] = target
            reason = _class_level_value(node, "authz_kind_reason")
            owned_child = _class_level_value(node, "authz_kind_of")
            declares_child, child_field = _owned_child_declaration(owned_child, module_constants)
            facts[node.name] = {
                "app": app,
                "file": path.relative_to(root).as_posix(),
                "lineno": node.lineno,
                "abstract": abstract,
                "authz_kind": _class_level_value(node, "authz_kind"),
                # THE RAW `authz_kind_of` NODE IS NOT PUBLISHED, and that is the
                # point: it was a third answer to a question two facts below
                # already answer, nobody read it, and a fact nobody reads is an
                # attractor for a reader who resolves it differently from the
                # registry. The registry's own two questions about
                # `authz_kind_of`, asked once here so no reader of these facts
                # has to re-derive either and get it subtly different, are these
                # two. See `_owned_child_declaration`.
                "declares_owned_child": declares_child,
                "owned_child_field": child_field,
                # The sentence an opt-out owes. Read as text when it is a plain
                # literal and as "something is there" when it is a joined or
                # parenthesised string, which is how every long one in this tree
                # is written — the check asks whether a sentence EXISTS, and
                # judging its quality is review's.
                "authz_kind_reason": (
                    reason.value
                    if isinstance(reason, ast.Constant) and isinstance(reason.value, str)
                    else ("" if reason == "absent" or reason is None else "declared")
                ),
                "foreign_keys": foreign_keys,
            }
    return facts


def _own_kind(name: str, fact: dict[str, Any]) -> str | None:
    """A model's own kind: the declaration, the opt-out, or the derived name."""
    declared = fact["authz_kind"]
    if declared == "absent":
        return _snake_kind(name)
    if isinstance(declared, ast.Constant):
        return None if declared.value is None else str(declared.value)
    if isinstance(declared, ast.Name) and declared.id == "AUTHZ_KIND_DERIVED":
        return _snake_kind(name)
    # A declaration this walk cannot read is NOT silently treated as an opt-out:
    # an unreadable `authz_kind` falls back to the derived name, which is what
    # `apps.core.authz` does with anything that is not the sentinel.
    return _snake_kind(name)


def model_kinds(root: Path) -> dict[str, str | None]:
    """Class name -> authorization kind (None when the model opted out).

    `authz_kind_of` resolves through the named foreign key to the aggregate's
    OWN kind, which is what makes an owned child authorized under its parent —
    `apps.core.authz.kind_of`'s own branch, and it reads the declaration
    through `_owned_child_declaration` so the two cannot come to disagree about
    what one is. A declaration this walk cannot resolve to a field name (a call,
    an import, an f-string) falls back to the model's own kind rather than
    guessing; the runtime answers `_parent_kind` there and the difference is
    named in rule 54's `does_not_cover`.
    """
    facts = _model_facts(root)
    kinds: dict[str, str | None] = {}
    for name, fact in facts.items():
        if fact["abstract"]:
            continue
        parent_field = fact["owned_child_field"]
        if parent_field:
            parent = fact["foreign_keys"].get(parent_field)
            kinds[name] = _own_kind(parent, facts[parent]) if parent in facts else None
            continue
        kinds[name] = _own_kind(name, fact)
    return kinds


def _assigned(node: ast.AST) -> tuple[list[str], ast.expr | None]:
    """The names an assignment statement binds, and the value it binds them to.

    `([names], value)` for an `Assign` (every plain-name target) or an
    `AnnAssign` (its one target, `value` None when it only annotates);
    `([], None)` for anything else. The one reading of "what does this
    statement name", for every reader that used to unpack the two shapes itself.
    """
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)], node.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id], node.value
    return [], None


def _module_string_constants(tree: ast.Module | None) -> dict[str, str]:
    """Module-level `NAME = "literal"` bindings, by name; empty for an unparsable module."""
    out: dict[str, str] = {}
    for node in tree.body if tree is not None else []:
        names, value = _assigned(node)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for name in names:
                out[name] = value.value
    return out


def string_constants(root: Path, path: Path, tree: ast.Module) -> dict[str, str]:
    """Every name this module can resolve to a string literal, one hop deep.

    Its own module-level bindings, plus the ones it IMPORTED from another
    first-party module — `from apps.workflows.services import READ_ACTION` is
    the shape on this tree, and reading only the local half would have called
    `apps/workflows/selectors.py` a pair of reads that never ask, which is the
    opposite of what it does. One hop and no further: a constant re-exported
    through a chain is outside, declared in the rules that use this.
    """
    out = _module_string_constants(tree)
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("apps."):
            continue
        source = root / Path(*node.module.split(".")).with_suffix(".py")
        if not source.is_file():
            continue
        other = _parse(source)
        if other is None:
            continue
        theirs = _module_string_constants(other)
        for alias in node.names:
            value = theirs.get(alias.name)
            if value is not None:
                out.setdefault(alias.asname or alias.name, value)
    return out


def declared_key_sites(
    root: Path,
) -> tuple[
    dict[str, tuple[str, int]],
    dict[str, str],
    list[tuple[str, int, str]],
    list[tuple[str, int, str, str]],
]:
    """(`ACTION_PROSE` key -> where it is declared, `RENAMED_PERMISSIONS`, …).

    The SITE and not just the key, because rule 54 reports a non-conforming key
    on the line that declares it: a finding pathed at the rule file instead of
    at the app's own `policies.py` is one nobody can act on without a grep.

    **The fourth value is every OTHER key-bearing dict a `policies.py` declares**
    — `POLICIES` and `DEFAULT_ROLES` — as `(rel, line, key, dict name)`. Those
    two name ACTIONS the way `ACTION_PROSE` does, and nothing read them: a
    `POLICIES` entry for a key the vocabulary does not hold is a predicate for a
    capability nobody can be given, and it is invisible — `vocabulary()` reads
    the registry only for keys it already has, so the key is in no census, no
    `non_conforming()` list and no test. `DEFAULT_ROLES` is read here for its
    KEY; clause (b) reads the same dict for the ROLE it offers to, which is a
    different question about the same line.
    """
    prose: dict[str, tuple[str, int]] = {}
    renames: dict[str, str] = {}
    unreadable: list[tuple[str, int, str]] = []
    declarations: list[tuple[str, int, str, str]] = []
    for app in _app_dirs(root):
        path = app / "policies.py"
        tree = _parse(path) if path.exists() else None
        if tree is None:
            continue
        for node in tree.body:
            names, value = _assigned(node)
            target = names[0] if len(names) == 1 else None
            if not isinstance(value, ast.Dict):
                continue
            if target == "ACTION_PROSE":
                for key in value.keys:
                    if key is None:
                        continue
                    site = (path.relative_to(root).as_posix(), key.lineno)
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        prose.setdefault(key.value, site)
                    else:
                        # A KEY THIS CENSUS CANNOT READ. `USAGE_READ_REPORT.action`
                        # is the live instance: the key is computed off a dataclass
                        # at import, so the registry has it and an AST walk does
                        # not. Recorded with its own sentinel rather than dropped,
                        # because a key silently missing from the census is the one
                        # thing this census exists not to have.
                        unreadable.append((*site, ast.unparse(key)))
            elif target == "RENAMED_PERMISSIONS":
                for key, val in zip(value.keys, value.values, strict=False):
                    if (
                        isinstance(key, ast.Constant)
                        and isinstance(val, ast.Constant)
                        and isinstance(key.value, str)
                    ):
                        renames[key.value] = str(val.value)
            elif target in _KEY_BEARING_DECLARATIONS:
                for key in value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        declarations.append(
                            (path.relative_to(root).as_posix(), key.lineno, key.value, target)
                        )
    return prose, renames, unreadable, declarations


def ast_vocabulary(root: Path) -> set[str]:
    """Every key this tree can answer, re-derived from models and policies.

    Four CRUD verbs per kind, plus every declared `ACTION_PROSE` key, plus the
    old half of every rename (which `resolve_renamed` still answers), plus
    core's reserved key. Rule 54 (a) is where this is proved equal to
    `apps.core.authz.vocabulary()`; here it is what clause (iv) judges against.
    """
    kinds = {k for k in model_kinds(root).values() if k}
    prose, renames, _unreadable, _declarations = declared_key_sites(root)
    derived = {f"{kind}.{verb}" for kind in kinds for verb in _CRUD_VERBS}
    derived |= family_derived_keys(root)
    return derived | set(prose) | set(renames) | set(renames.values()) | set(_RESERVED_KEYS)


#: `core.models.ARCHIVABLE_ATTR` and the mixin that sets it, re-derived — rule
#: 75's resolver and this census read the same two names.
_ARCHIVABLE_ATTR = "archivable"
_ARCHIVABLE_MIXIN = "Archivable"

#: `apps.core.verbs.ROADS`, re-derived: the verbs each family marker adds to its
#: kind's derived keys. The runtime reads the table; this census reads the tree,
#: and a marker joining the family joins both in the same commit.
_FAMILY_MARKER_VERBS: dict[str, tuple[str, ...]] = {
    _ARCHIVABLE_ATTR: ("archive", "restore"),
    "movable": ("move",),
    "mergeable": ("merge",),
}

#: The mixin that seeds each marker's population (rule 75's resolver shape).
_FAMILY_MARKER_MIXINS: dict[str, str] = {
    _ARCHIVABLE_ATTR: _ARCHIVABLE_MIXIN,
    "movable": "Movable",
    "mergeable": "Mergeable",
}


def family_derived_keys(root: Path) -> set[str]:
    """`<kind>.<verb>` for every family verb a marked model's kind derives.

    `apps.core.authz.family_verbs`, re-derived by AST: a model that declared
    `Archivable` (itself or through a base) derives `<kind>.archive` and
    `<kind>.restore` exactly as it derives its four CRUD keys.
    """
    kinds = model_kinds(root)
    _sites, _append_only, archivable = declared_class_populations(root)
    marked = {_ARCHIVABLE_ATTR: archivable}
    for marker, mixin in _FAMILY_MARKER_MIXINS.items():
        if marker not in marked:
            marked[marker] = declared_marker_classes(root, marker, mixin)
    keys: set[str] = set()
    for marker, verbs in _FAMILY_MARKER_VERBS.items():
        for name in marked[marker]:
            kind = kinds.get(name)
            if kind:
                keys.update(f"{kind}.{verb}" for verb in verbs)
    return keys


def _asks(fn: ast.AST, constants: dict[str, str]) -> list[tuple[int, str | None, str]]:
    """(line, key or None, source) for every require/allows/holds in this body."""
    out: list[tuple[int, str | None, str]] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = (
            func.id
            if isinstance(func, ast.Name)
            else (func.attr if isinstance(func, ast.Attribute) else "")
        )
        if name not in _ASK_FUNCTIONS or len(node.args) < 2:
            continue
        arg = node.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append((node.lineno, arg.value, arg.value))
        elif isinstance(arg, ast.Name) and arg.id in constants:
            out.append((node.lineno, constants[arg.id], f"{arg.id} = {constants[arg.id]!r}"))
        else:
            out.append((node.lineno, None, ast.unparse(arg)))
    return out


def _bound_models(fn: ast.AST, registry: dict[str, Any]) -> dict[str, str]:
    """Local name -> the model class it holds, as far as AST can see.

    Three ways, the same three rule 26's `_org_bound_names` reads: a parameter
    annotated with a model (rule 26's annotation walk, reused rather than
    re-invented), a name annotated with one, and a name assigned from an
    expression whose chain root IS one (`row = Gadget(...)`,
    `row = Gadget.objects.create(...)`).
    """
    bound: dict[str, str] = {}
    for arg in _all_args(fn):  # type: ignore[arg-type]
        for name in sorted(_annotation_names(arg.annotation)):
            if name in registry:
                bound[arg.arg] = name
    for node in ast.walk(fn):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            for name in sorted(_annotation_names(node.annotation)):
                if name in registry:
                    bound[node.target.id] = name
        elif isinstance(node, ast.Assign) and node.value is not None:
            root = _chain_root(node.value)
            if isinstance(root, ast.Name) and root.id in registry:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bound[target.id] = root.id
                    elif isinstance(target, ast.Tuple):
                        for element in target.elts:
                            if isinstance(element, ast.Name):
                                bound[element.id] = root.id
    return bound


def _written_models(fn: ast.AST, registry: dict[str, Any]) -> list[tuple[int, str, str]]:
    """(line, model class, what) for every write whose subject AST can name.

    The four shapes clause (i) enumerates: `Model.objects.<write>(...)`, a
    queryset `.update()`/`.delete()`/`.bulk_update()` whose chain root is a
    model, and `.save()`/`.delete()` on a name bound above — which covers both
    `row = Model(...)` and a parameter annotated with one.
    """
    bound = _bound_models(fn, registry)
    out: list[tuple[int, str, str]] = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        attr = node.func.attr
        receiver = node.func.value
        if (
            attr in _WRITE_MANAGER_CALLS
            and isinstance(receiver, ast.Attribute)
            and receiver.attr == "objects"
        ):
            root = _chain_root(receiver)
            if isinstance(root, ast.Name) and root.id in registry:
                out.append((node.lineno, root.id, f".objects.{attr}()"))
            continue
        if attr in ("update", "delete", "bulk_update") and isinstance(receiver, ast.Call):
            root = _chain_root(receiver)
            if isinstance(root, ast.Name) and root.id in registry:
                out.append((node.lineno, root.id, f".{attr}()"))
            continue
        if attr in ("save", "delete") and isinstance(receiver, ast.Name):
            model = bound.get(receiver.id)
            if model is not None:
                out.append((node.lineno, model, f"{receiver.id}.{attr}()"))
    return out


def _kind_findings(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    rel: str,
    app: str,
    lines: list[str],
    constants: dict[str, str],
    kinds: dict[str, str | None],
    vocabulary: set[str],
    out: CheckResult,
) -> list[Finding]:
    """Clauses (iii) and (iv) for one @service. Counts ride on `out`."""
    found: list[Finding] = []

    asks = _asks(node, constants)
    required: set[str] = set()
    for line, key, source in asks:
        if key is not None:
            out.count("literal_keys_seen")
            if "." in key:
                required.add(key.rsplit(".", 1)[0])
            if key not in vocabulary:
                found.append(
                    Finding(
                        rel,
                        line,
                        f"{node.name} asks for {key!r}, which no model derives and no "
                        "`ACTION_PROSE` declares — a key outside the vocabulary can never be "
                        "held by anybody, so the ask refuses everyone for a reason nobody can "
                        "read. Declare it, or name the key that exists",
                        f"{app}.key",
                    )
                )
            continue
        reason = comment_reason(lines, line, _AUTHZ_KEY_RE)
        if reason is not None and reason.holds:
            out.count("authz_key_valves")
            continue
        if reason is not None:
            found.append(
                Finding(
                    rel,
                    line,
                    f"`# authz-key:` with no reason on {node.name} — an escape hatch nobody "
                    "has to justify is an off switch; write the sentence a reviewer can "
                    "disagree with",
                    f"{app}.key",
                )
            )
            continue
        found.append(
            Finding(
                rel,
                line,
                f"{node.name} asks for a key this tree cannot read — `{source}` is neither a "
                "literal nor a module-level string constant, so no census can say which "
                "capability it names. Name it, or record `# authz-key: <reason>`",
                f"{app}.key",
            )
        )

    writes = _written_models(node, kinds)
    for line, model, what in writes:
        kind = kinds.get(model)
        if kind is None:
            continue
        out.count("written_kinds_resolved")
        # A service that asks NOTHING is the `# authz:` clause's subject, not
        # this one's: judging it here would ask a platform service with no
        # actor to justify every write twice, in two different comments.
        if not required or kind in required:
            continue
        reason = comment_reason(lines, line, _AUTHZ_KIND_RE)
        if reason is not None and reason.holds:
            out.count("authz_kind_valves")
            continue
        if reason is not None:
            found.append(
                Finding(
                    rel,
                    line,
                    f"`# authz-kind:` with no reason in {node.name} — an escape hatch nobody "
                    "has to justify is an off switch; write the sentence a reviewer can "
                    "disagree with",
                    app,
                )
            )
            continue
        found.append(
            Finding(
                rel,
                line,
                f"{node.name} writes {model} ({what}), whose authorization kind is {kind!r}, "
                f"and asks for no {kind}.* key — it asks about "
                f"{', '.join(sorted(required))}. A service that authorizes one noun and "
                f"writes another is green everywhere else in this tree. Ask for the kind you "
                f"write, or record `# authz-kind: <reason>` on the write",
                app,
            )
        )
    return found


from quality.checks.rule_16_the_rest_of_the_grammar import _model_classes  # noqa: E402
from quality.checks.rule_26 import _all_args, _annotation_names  # noqa: E402
from quality.checks.rule_54 import _KEY_BEARING_DECLARATIONS  # noqa: E402
from quality.checks.rule_75_resolver import declared_class_populations  # noqa: E402
from quality.checks.rule_76 import declared_marker_classes  # noqa: E402
from quality.checks.rules_10_12 import _chain_root  # noqa: E402
