"""Rule 54: the vocabulary is one shape."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality import loop_key as LK
from quality.checks._hub import CheckResult, _app_dirs, _exempt, _parse, _py_files, _read
from quality.worlds import Valve, comment_reason

# --- rule 54: the vocabulary is one shape -------------------------------------
#
# One statement, five clauses, one census — and they are one rule because they
# are one question asked at five layers: **is the word for a capability decided
# in exactly one place?** Splitting them into five ids would give five rules
# that can only be read together, and the ratchet lines are per clause already.
#
# (a) THE VOCABULARY IS DERIVED. Every first-party concrete model yields one
#     kind — `authz_kind`, `authz_kind_of`, or `snake_case(ClassName)` — or
#     opts out with a sentence; four verbs per kind are the derived keys, and a
#     key an app DECLARES is classified against them. A declared key that is a
#     second spelling of a derived one, or names no kind at all, is
#     non-conforming, and the count is a ratchet (`quality.worlds.Bound`).
# (b) A DECLARATION NAMES DECLARED THINGS. A `roles.py` may not declare the
#     platform's own `owner` or a reserved key as a role, and two apps may not
#     declare one role; a `DEFAULT_ROLES` entry may not offer a capability to a
#     role nobody declares. `djb.W054` is the half of this that reads a
#     deployment's ROWS at `--deploy`; this half reads the code, in the tree,
#     where the gate can see it.
# (c) NO ROLE BY VALUE. Outside `apps/core/authz.py` and `apps/core/models.py`,
#     production code does not ask "what role is this" — not by the enum, not
#     by rank, not by a comparison against a string. A predicate that needs to
#     know how much authority somebody has asks
#     `holds(actor, "<kind>.<verb>", at=...)`, because a role is data a tenant
#     owns and a rank table is a second opinion about it that no tenant can
#     edit. Ratcheted per app; each sweep drives its own app to zero.
# (d) A READ ASKS, and (e) IT ASKS ABOUT WHAT IT RETURNS. Every public `get_`/
#     `list_` selector whose return annotation names a model with a kind calls
#     `require(actor, "<that kind>.read", …)`, or carries `# read-open:` (a
#     machine read, pre-auth or system) or `# read-kind:` (it returns one kind
#     and is authorized under another). RATCHET-ONLY in this cycle by design —
#     "measured before enforced" — and the per-app numbers below are the
#     measurement the read sweeps drive to zero.
#
# WHAT THIS HALF NEVER DOES IS IMPORT. Every derivation here is AST, for the
# reason rule 13's kind clauses give: the self-test plants a `models.py`, a
# `policies.py` and a `roles.py` into the tree and re-runs this check in the
# same process, and a cached `django.setup()` could not see any of them. The
# consequence is declared rather than hidden: the two underivable cases —
# a kind claimed by two models, an opt-out with no sentence — are
# `ImproperlyConfigured` at runtime and are findings here, so this half exits 1
# where the registry would refuse to load at all. `djb.E025` is the half that
# refuses, it runs in the gate's own django leg, and it is what makes the
# stronger guarantee; this one is what makes the census readable on a tree.

#: `apps.core.authz.READ_ALIAS_VERBS` — the three other spellings of `read`.
_READ_ALIAS_VERBS = frozenset({"view", "list", "get"})
#: `apps.core.authz.VIRTUAL_KINDS` — a kind with no row behind it. A list of
#: one, re-derived here so "the kind is not in the model registry" stays a
#: finding rather than a shrug the next unbound noun slips through.
_VIRTUAL_KINDS = frozenset({"deployment"})
#: The tokens that read a role BY VALUE. The call names, the rank constants,
#: the enum path, and a comparison of a `.role` attribute against a literal.
_ROLE_VALUE_CALLS = frozenset({"rank", "effective_role", "actor_role"})
_ROLE_VALUE_NAMES = frozenset({"ROLE_RANK", "ADMIN_RANK"})
_ROLE_VALUE_RE = re.compile(r"#\s*role-value:\s*(.*)$")
#: The key-bearing dicts a `policies.py` declares BESIDE `ACTION_PROSE` and
#: `RENAMED_PERMISSIONS` — the ones whose keys are ACTIONS. Named rather than
#: discovered because "a dict in this file whose keys look like keys" would read
#: a product's own lookup table as a declaration; these two are the declarations
#: `apps.core.authz._declarations` itself walks for.
_KEY_BEARING_DECLARATIONS = ("POLICIES", "DEFAULT_ROLES")

_READ_OPEN_RE = re.compile(r"#\s*read-open:\s*(.*)$")
_READ_KIND_RE = re.compile(r"#\s*read-kind:\s*(.*)$")


def _classify_declared_key(action: str, kinds: set[str]) -> str:
    """Why a DECLARED key does not conform, or `""` when it does.

    `apps.core.authz._classify`, re-derived. The four sentences are its
    sentences, because a reader meeting one of them in a gate red and one of
    them in `introspect` must not have to work out that they are the same fact.
    """
    parts = action.split(".")
    if len(parts) != 2:
        return f"a key is `<kind>.<verb>`; {action!r} has {len(parts)} parts"
    kind, verb = parts
    if kind not in kinds and kind not in _VIRTUAL_KINDS:
        return (
            f"no kind {kind!r}: no first-party model derives or declares it, and it is not "
            "one of the virtual kinds"
        )
    if verb in _CRUD_VERBS:
        return f"a second spelling of the derived key {action!r}"
    if verb in _READ_ALIAS_VERBS:
        return f"`read` is THE read verb; {verb!r} is another spelling of it"
    return ""


def _dict_entries(tree: ast.Module, name: str) -> ast.Dict | None:
    """The module-level dict literal assigned to `name`, or None."""
    for node in tree.body:
        names, value = _assigned(node)
        target = names[0] if len(names) == 1 else None
        if target == name and isinstance(value, ast.Dict):
            return value
    return None


def _role_declarations(root: Path) -> list[tuple[str, int, str, str]]:
    """(rel, line, role key, app) for every `ROLES` entry in an `apps/*/roles.py`."""
    out: list[tuple[str, int, str, str]] = []
    for app in _app_dirs(root):
        path = app / "roles.py"
        tree = _parse(path) if path.exists() else None
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        entries = _dict_entries(tree, "ROLES")
        if entries is None:
            continue
        for key in entries.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                out.append((rel, key.lineno, key.value, app.name))
    return out


def _default_role_offers(root: Path) -> list[tuple[str, int, str, str]]:
    """(rel, line, action, role) for every `DEFAULT_ROLES` entry in a policies.py."""
    out: list[tuple[str, int, str, str]] = []
    for app in _app_dirs(root):
        path = app / "policies.py"
        tree = _parse(path) if path.exists() else None
        if tree is None:
            continue
        rel = path.relative_to(root).as_posix()
        entries = _dict_entries(tree, "DEFAULT_ROLES")
        if entries is None:
            continue
        for key, value in zip(entries.keys, entries.values, strict=False):
            action = key.value if isinstance(key, ast.Constant) else "?"
            for element in ast.walk(value):
                if isinstance(element, ast.Constant) and isinstance(element.value, str):
                    out.append((rel, element.lineno, str(action), element.value))
    return out


#: Where `Membership` lives, for the properties that read a role by value.
_MEMBERSHIP_SOURCE = "apps/core/models.py"


def _membership_role_readers(root: Path) -> frozenset[str]:
    """The `Membership` members whose body reads `self.role`: a role read by value, renamed.

    Derived from the model rather than named here: a property that answers
    "is this person an owner or an admin" is the role compared by value, and
    the next such property is read the day it is written.
    """
    tree = _parse(root / _MEMBERSHIP_SOURCE)
    if tree is None:
        return frozenset()
    names: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == "Membership"):
            continue
        for member in node.body:
            if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if member.name.startswith("__"):
                continue
            if any(
                isinstance(leaf, ast.Attribute)
                and leaf.attr == "role"
                and isinstance(leaf.value, ast.Name)
                and leaf.value.id == "self"
                for leaf in ast.walk(member)
            ):
                names.add(member.name)
    return frozenset(names)


def _role_value_sites(
    tree: ast.Module, role_readers: frozenset[str] | None = None
) -> dict[int, list[str]]:
    """Line -> what reads a role by value there. Imports and strings excluded.

    An import of `rank` or `ADMIN_RANK` is not a use of it — the file that
    imports the compat shim and never calls it is not asking what role anybody
    has — and a sentence in a docstring that spells `rank()` is prose. Both are
    outside by construction here, which is what the AST buys over the grep the
    measurement was taken with.
    """
    if role_readers is None:
        role_readers = _membership_role_readers(Path(LK.__file__).resolve().parents[1])
    found: dict[int, list[str]] = {}

    def note(line: int, what: str) -> None:
        found.setdefault(line, [])
        if what not in found[line]:
            found[line].append(what)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Name) and node.id in _ROLE_VALUE_NAMES:
            note(node.lineno, node.id)
        elif isinstance(node, ast.Attribute) and node.attr in role_readers:
            note(node.lineno, f".{node.attr}")
        elif isinstance(node, ast.Attribute):
            chain = _dotted_role_chain(node)
            if len(chain) >= 3 and chain[0] == "Membership" and chain[1] == "Role":
                note(node.lineno, ".".join(chain))
        elif isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                other = [x for x in [node.left, *node.comparators] if x is not side]
                if not (isinstance(side, ast.Attribute) and side.attr == "role"):
                    continue
                for value in other:
                    # THE EMPTY STRING IS NOT A ROLE. `invitation.role == ""`
                    # asks whether a role was named at all — an offer of a place
                    # and nothing more — which is a question about the FIELD
                    # being set, not about how much authority anybody has. The
                    # `does_not_cover` paragraph already puts `Invitation.role`'s
                    # key-shaped uses outside this clause; this is the one of
                    # them that wears a comparison.
                    if (
                        isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                        and value.value
                    ):
                        note(node.lineno, f".role == {value.value!r}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else "")
            )
            if name in _ROLE_VALUE_CALLS:
                note(node.lineno, f"{name}()")
            for keyword in node.keywords:
                if keyword.arg == "role__in":
                    note(node.lineno, "role__in=")
                elif keyword.arg == "role" and isinstance(keyword.value, ast.Attribute):
                    chain = _dotted_role_chain(keyword.value)
                    if chain and chain[0] == "Membership":
                        note(keyword.value.lineno, f"role={'.'.join(chain)}")
    return found


def _dotted_role_chain(node: ast.Attribute) -> list[str]:
    """`Membership.Role.OWNER` -> `["Membership", "Role", "OWNER"]`."""
    chain: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        chain.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        chain.append(cur.id)
    chain.reverse()
    return chain


def _function_valve(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    src: str,
    lines: list[str],
    pattern: re.Pattern[str],
) -> Valve | None:
    """A valve marker anywhere a reader would put it on a function.

    Three sites, and they are the three the conventions describe: inside the
    function's own source (its docstring, or a comment in the body), on the
    `def` line, and in the contiguous comment block above the first decorator.

    **AND THE MARKER OPENS A COMMENT LINE — prose that SPELLS it is not a
    valve.** The block-above form has always required `strip().startswith("#")`
    (`quality.worlds.comment_reason`); the in-source form did not, so a docstring paragraph
    explaining why this selector needs no valve read as the valve itself. That
    is a phantom registration, and it is the exact class the conventions warn
    about: a sentence spelling a censused marker gets counted like real code.
    The line has to BE the comment, not mention one.

    THE ONE IN-FUNCTION VALVE READER. Rule 54's `read-open`/`read-kind` and
    rule 13's `authz` both read through here; rule 13 once read its valve as a
    substring of the whole function, so a sentence that MENTIONED the marker
    mid-line excused the service — a second reader of one grammar, and the
    looser of the two.
    """
    segment = ast.get_source_segment(src, node) or ""
    for line in segment.splitlines():
        if line.strip().startswith("#"):
            found = comment_reason([line], 1, pattern)
            if found is not None:
                return found
    top = min([d.lineno for d in node.decorator_list] or [node.lineno])
    return comment_reason(lines, node.lineno, pattern) or comment_reason(lines, top, pattern)


def authz_vocabulary_shape(root: Path, rule: dict) -> CheckResult:
    """Rule 54, all five clauses, over one derivation of the vocabulary."""
    out = CheckResult()
    facts = _model_facts(root)
    kinds = model_kinds(root)
    kindset = {kind for kind in kinds.values() if kind}
    prose_sites, renames, unreadable, declarations = declared_key_sites(root)
    for key in (
        "role_value_valves",
        "read_open_valves",
        "read_kind_valves",
        "nonrequiring_selectors",
        "wrong_kind_selectors",
    ):
        out.targets_matched[key] = 0

    # --- (a) the vocabulary census ------------------------------------------
    owners: dict[str, str] = {}
    for name, fact in sorted(facts.items()):
        if fact["abstract"]:
            continue
        out.count("models_censused")
        kind = kinds.get(name)
        rel, line = fact["file"], fact["lineno"]
        if fact["declares_owned_child"]:
            # **AN OWNED CHILD ADDS NO KIND OF ITS OWN — that is what
            # `authz_kind_of` MEANS**, and `apps.core.authz.kind_registry_of`
            # skips these for exactly this reason (its own comment: "Resolved
            # for its refusals, not for its entry"). `model_kinds` above still
            # resolves one — through the same seam this line reads, so the two
            # agree by construction — because a SELECTOR returning a child has
            # to be able to ask for the parent's read, and clause (e) is built
            # on that. But entering the child in `owners` would read the child
            # and its parent as two models claiming one word, and refuse a
            # declaration the runtime accepts. Paid for by `files.FileVersion`,
            # the first model in this tree to declare `authz_kind_of`: the
            # census reported a collision the registry does not have.
            #
            # **THE QUESTION IS THE REGISTRY'S AND IT IS ASKED IN ONE PLACE.**
            # `_owned_child_declaration` is that place, and it mirrors
            # `getattr(model, "authz_kind_of", None) is not None` exactly. This
            # line asked the question itself twice before, and got it wrong in
            # both directions: first too narrow (an `ast.Constant` string only,
            # so a module constant fell through the skip and was censused as a
            # model with a kind of its own), then too wide (`not in (None,
            # "absent")`, which swallowed a CONCRETE model restating the base
            # class's `authz_kind_of = None` — `ast.Constant(None)`, which
            # leaves `getattr` answering `None`, so the registry does NOT skip
            # it and raises `ImproperlyConfigured` on a kind claimed twice
            # while this half said nothing).
            #
            # Both spellings now have a fixture beside them, and the abstract
            # base's own `authz_kind_of = None` is a negative rather than an
            # accident of the `abstract` filter one screen up.
            continue
        if kind is None:
            if not str(fact["authz_kind_reason"] or "").strip():
                out.hit(
                    rel,
                    line,
                    f"{name} sets `authz_kind = None` and declares no `authz_kind_reason` — "
                    "opting a model out of the vocabulary is a claim (no door reaches a row "
                    "of it, nobody could be given a capability over it) and a claim with no "
                    "sentence beside it is one nobody can disagree with",
                    klass="vocabulary",
                )
            continue
        if kind in owners and owners[kind] != name:
            out.hit(
                rel,
                line,
                f"{name} and {owners[kind]} both claim the authorization kind {kind!r} — the "
                "vocabulary cannot be derived at all while two models answer to one word. "
                "One of them declares its own `authz_kind`",
                klass="vocabulary",
            )
            continue
        owners.setdefault(kind, name)
    out.count("kinds", len(kindset))
    out.count("derived_keys", len(kindset) * len(_CRUD_VERBS))
    family_keys = family_derived_keys(root)

    for action, (rel, line) in sorted(prose_sites.items()):
        derived = (
            action.split(".")[0] in kindset and action.split(".")[-1] in _CRUD_VERBS
        ) or action in family_keys
        if derived and len(action.split(".")) == 2:
            # A sentence override of a key the registry already derived. Legal,
            # and the whole point of `ACTION_PROSE` for a derived key.
            continue
        if action in renames:
            continue
        out.count("declared_keys")
        why = _classify_declared_key(action, kindset)
        if why:
            out.hit(
                rel,
                line,
                f"the declared key {action!r} does not fit `<kind>.<verb>`: {why}. The key "
                "vocabulary is one shape or it is a list nobody can census — rename it in "
                "this app's `RENAMED_PERMISSIONS`, which keeps the old word answering",
                klass="nonconforming",
            )

    for rel, line, source in unreadable:
        out.hit(
            rel,
            line,
            f"the declared key `{source}` is computed rather than written — this census "
            "reads the tree by AST (the self-test plants a policies.py and re-runs it in "
            "the same process, which a cached `django.setup()` could not see), so a key "
            "assembled at import is one it cannot classify and one nobody can grep for. "
            "Write the string; the constant beside it may keep the name",
            klass="unreadable_prose",
        )

    # EVERY KEY-BEARING DECLARATION NAMES A KEY THE VOCABULARY HOLDS. The
    # vocabulary is derived from the kinds and DECLARED through `ACTION_PROSE`
    # and the rename table; a `POLICIES` or `DEFAULT_ROLES` entry is a
    # declaration of neither, so a key that appears only there is a predicate —
    # or a default — for a capability nobody can be given. It is invisible
    # everywhere else by construction: `vocabulary()` consults the policy
    # registry only for keys it has already derived, so the key joins no census,
    # no `non_conforming()` list and no pinned ratchet, and every layer stays
    # green. The remedy is the ordinary one — declare the key in `ACTION_PROSE`
    # with its sentence, or name the one that exists.
    words = (
        {f"{kind}.{verb}" for kind in kindset for verb in _CRUD_VERBS}
        | family_keys
        | set(prose_sites)
        | set(renames)
        | set(renames.values())
        | set(_RESERVED_KEYS)
    )
    for rel, line, action, declaration in declarations:
        if action in words:
            continue
        out.hit(
            rel,
            line,
            f"a `{declaration}` entry names {action!r}, which the vocabulary does not hold — "
            "a predicate (or a default) for a capability nobody can be given, and one no "
            "census can see: the registry is read for keys the vocabulary already has, so "
            "this key is in no list anywhere. Declare it in `ACTION_PROSE` with its "
            "sentence, or name the one that exists",
            klass="declaration",
        )

    # --- (b) a declaration names declared things ----------------------------
    declared_roles: dict[str, str] = {}
    for rel, line, key, app in _role_declarations(root):
        out.count("role_declarations")
        if key == "owner":
            out.hit(
                rel,
                line,
                "a `roles.py` declares the role 'owner', which is the platform's — `owner` "
                "IS the vocabulary, every key present and future, and a declaration that "
                "narrowed it would be a ceiling quietly disappearing",
                klass="declaration",
            )
            continue
        if key in _RESERVED_KEYS:
            out.hit(
                rel,
                line,
                f"a `roles.py` declares a role keyed {key!r}, which is a reserved PERMISSION "
                "— a role key and a permission key are different vocabularies and one name "
                "in both is a name two readers disagree about",
                klass="declaration",
            )
            continue
        if key in declared_roles and declared_roles[key] != app:
            out.hit(
                rel,
                line,
                f"{app} and {declared_roles[key]} both declare the role {key!r} — two "
                "collections under one name, and which one a membership gets would depend "
                "on import order",
                klass="declaration",
            )
            continue
        declared_roles.setdefault(key, app)
    known_roles = set(declared_roles) | {"owner"}
    for rel, line, action, role in _default_role_offers(root):
        if role in known_roles:
            continue
        out.hit(
            rel,
            line,
            f"a `DEFAULT_ROLES` entry offers {action!r} to the role {role!r}, which no app "
            "declares in a `roles.py` — the capability is offered to nobody",
            klass="declaration",
        )

    # --- (c) no role by value -----------------------------------------------
    for path in _py_files(root, "apps"):
        rel = path.relative_to(root).as_posix()
        if _exempt(rule, rel):
            continue
        tree = _parse(path)
        if tree is None:
            continue
        out.count("role_value_files_scanned")
        app = rel.split("/")[1]
        lines = _read(path).splitlines()
        for line, what in sorted(_role_value_sites(tree).items()):
            reason = comment_reason(lines, line, _ROLE_VALUE_RE)
            if reason is not None and reason.holds:
                out.count("role_value_valves")
                continue
            if reason is not None:
                out.hit(
                    rel,
                    line,
                    "`# role-value:` with no reason — an escape hatch nobody has to justify "
                    "is an off switch; write the sentence a reviewer can disagree with",
                    klass=f"{app}.role-value",
                )
                continue
            out.hit(
                rel,
                line,
                f"reads a role by value ({', '.join(what)}) — a role is DATA a tenant owns, "
                "and a rank table is a second opinion about it that no tenant can edit. A "
                'predicate that needs "how much authority" asks '
                "`holds(actor, '<kind>.<verb>', at=...)`, which reads the same rows the role "
                "editor writes",
                klass=f"{app}.role-value",
            )

    # --- (d)/(e) a read asks, and asks about what it returns -----------------
    for path in _py_files(root, "apps", named={"selectors.py"}):
        rel = path.relative_to(root).as_posix()
        tree = _parse(path)
        if tree is None:
            continue
        src = _read(path)
        lines = src.splitlines()
        app = rel.split("/")[1]
        constants = string_constants(root, path, tree)
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not (node.name.startswith("get_") or node.name.startswith("list_")):
                continue
            # **A VALVE IS COUNTED BY NAME, WHERE THE FINDINGS ARE BOUND BY
            # ANNOTATION.** The population clauses (d)/(e) can raise a finding
            # over is the one an annotation resolves to a kind; the population a
            # valve can be WRITTEN in is every public `get_`/`list_` a
            # `selectors.py` declares, and those two are not the same set. A
            # selector annotated with an aggregate — `-> MeasuredOut`,
            # `-> dict[str, MeasuredOut]` — is outside the findings by
            # annotation and its author still writes the sentence, because the
            # sentence is what a reviewer reads. Counted here, before the
            # annotation filter, so the status line's number equals the number
            # of valve lines in the tree instead of the subset this rule could
            # ever have flagged: a valve the census does not count is an off
            # switch nobody can see, and two of them sat in `apps/usage` unread.
            open_reason = _function_valve(node, src, lines, _READ_OPEN_RE)
            kind_reason = _function_valve(node, src, lines, _READ_KIND_RE)
            if open_reason is not None and open_reason.holds:
                out.count("read_open_valves")
            if kind_reason is not None and kind_reason.holds:
                out.count("read_kind_valves")
            returned = sorted(n for n in _annotation_names(node.returns) if kinds.get(n))
            if not returned:
                continue
            out.count("selectors_censused")
            kind = kinds[returned[0]]
            asked = {key for _, key, _ in _asks(node, constants) if key}
            reads = {key for key in asked if key.rsplit(".", 1)[-1] == "read"}
            if not reads:
                if open_reason is not None and open_reason.holds:
                    continue
                out.count("nonrequiring_selectors")
                out.hit(
                    rel,
                    node.lineno,
                    f"{node.name} returns {returned[0]} — kind {kind!r} — and asks no "
                    f"{kind}.read: a read that never asks is a read every door inherits for "
                    "free. Call `require(actor, '<kind>.read', ...)`, or record "
                    "`# read-open: <reason>` for a machine read",
                    klass=f"{app}.read",
                )
                continue
            if f"{kind}.read" in reads:
                continue
            if kind_reason is not None and kind_reason.holds:
                continue
            out.count("wrong_kind_selectors")
            out.hit(
                rel,
                node.lineno,
                f"{node.name} returns {returned[0]} — kind {kind!r} — and asks "
                f"{', '.join(sorted(reads))}: the capability guarding a read is the kind of "
                "the row it hands back, or the read is authorized by a word that means "
                "something else. Ask for `{kind}.read`, or record `# read-kind: <kind>` "
                "saying which aggregate answers for it",
                klass=f"{app}.read-kind",
            )
    return out


from quality.checks.rule_13_clauses_i_iv import (  # noqa: E402
    _CRUD_VERBS,
    _RESERVED_KEYS,
    _asks,
    _assigned,
    _model_facts,
    declared_key_sites,
    family_derived_keys,
    model_kinds,
    string_constants,
)
from quality.checks.rule_26 import _annotation_names  # noqa: E402
