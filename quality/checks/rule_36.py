"""Rule 36: socket fan-out discipline (ADR gate-2)."""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from quality.checks._hub import (
    CheckResult,
    _app_is_pinned,
    _parse,
    _py_files,
    _read,
    facade_reexports,
)
from quality.tree import untracked_paths
from quality.worlds import decorator_names, is_service_module, service_modules

# --- rule 36: socket fan-out discipline (ADR gate-2) -----------------------------

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

    Exact-shape by design: the whole subject is one decision point
    (`apps/realtime/bridge.py::group_for`) and the `group_send` call sites under
    `apps/`. A `group_send` whose group argument is a direct `tenant_group(...)`
    call and whose message is org-bearing is the org-blind push the socket probe found.
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
                    "every branch's socket hears another branch's rows (a HIGH finding, priced "
                    "at 495 wrong-branch frames per 500 sockets by the socket probe). The group is "
                    "`group_for`'s decision, never `tenant_group(...)` at a push site.",
                )
    bridge = root / "apps" / "realtime" / "bridge.py"
    bridge_tree = _parse(bridge)
    if bridge_tree is not None:
        for node in bridge_tree.body:
            is_decision = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            if is_decision and node.name == "group_for":
                out.count("decision_points")
    writers = _status_writer_census(root)
    out.findings.extend(writers.findings)
    for key, value in writers.targets_matched.items():
        out.count(key, value)
    return out


#: The seam a service that darkens a tenant has to reach, and the enum path a
#: status write takes. Both derived from the tree's own vocabulary rather than
#: guessed: `Tenant.Status` is `apps/core/models.py`'s `TextChoices` class and
#: `close_tenant_sockets_on_commit` is `apps/core/services/sockets.py`'s one registration.
_TENANT_STATUS_SEAM = "close_tenant_sockets_on_commit"
_TENANT_STATUS_ENUM = ("Tenant", "Status")
_TENANT_STATUS_LIVE = "ACTIVE"


def _tenant_status_written(node: ast.Assign) -> str | None:
    """The `Tenant.Status.<NAME>` this assignment puts on a `.status`, or None.

    Exact-shape, like the rest of this rule: `<anything>.status =
    Tenant.Status.<NAME>`. A status built from a variable, an f-string or a
    `.update(status=...)` is not seen here and is named in `does_not_cover` —
    the population this exists for is the two operator services, and a guess
    about which write darkens a tenant is worse than a declared blind spot.
    """
    if not any(isinstance(t, ast.Attribute) and t.attr == "status" for t in node.targets):
        return None
    value = node.value
    if not isinstance(value, ast.Attribute) or not isinstance(value.value, ast.Attribute):
        return None
    enum, holder = value.value, value.value.value
    if not isinstance(holder, ast.Name):
        return None
    if (holder.id, enum.attr) != _TENANT_STATUS_ENUM:
        return None
    return value.attr


def _status_writer_census(root: Path) -> CheckResult:
    """Rule 36, class `status_writer`: a tenant that goes dark hangs up.

    R4's F2. `suspend_tenant` and `close_tenant` wrote a status and registered
    NOTHING, while the only kick primitive was per person — so a suspended
    tenant's live sockets went on hearing for the life of the connection, and
    the REST door answered 403 to the same credential. A new handshake was
    already refused, which is exactly what made the gap invisible.

    The population is every `@service` that assigns a non-`ACTIVE`
    `Tenant.Status` — derived, so the third such service is in it on the run it
    lands — and the answer is a call to `close_tenant_sockets_on_commit` in the
    same body. Deliberately NOT `resume_tenant`: a widening kicks nobody, which
    is the asymmetry `kick_if_reads_narrowed` already states one level down.
    """
    out = CheckResult()
    for path in service_modules(root):
        tree = _parse(path)
        if tree is None:
            continue
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if "service" not in decorator_names(node):
                continue
            written = [
                (sub, name)
                for sub in ast.walk(node)
                if isinstance(sub, ast.Assign)
                for name in [_tenant_status_written(sub)]
                if name is not None and name != _TENANT_STATUS_LIVE
            ]
            if not written:
                continue
            out.count("status_writers", len(written))
            reaches = any(
                isinstance(sub, ast.Call) and _callee_name(sub.func) == _TENANT_STATUS_SEAM
                for sub in ast.walk(node)
            )
            if reaches:
                continue
            for assignment, name in written:
                out.hit(
                    rel,
                    assignment.lineno,
                    f"`{node.name}` puts a tenant into `{name}` and never calls "
                    f"`{_TENANT_STATUS_SEAM}`. A tenant going dark is refused at the next "
                    "HANDSHAKE and nowhere else, so every socket already open goes on "
                    "hearing — for the hours the bridge's docstring expects a connection to "
                    "last — while the REST door answers 403 to the same credential. That "
                    "disagreement between two doors is the finding. Register the kick on "
                    "commit in this body, or say why on the line",
                    klass="status_writer",
                )
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


#: The one module whose classes a schema module's `Out` may inherit fields from
#: ACROSS a file boundary: the family's shared bases (`ArchivedOut`, `ActsOut`,
#: `HomedOut`, `VersionedOut`, …) live here, and an `Out` that moved a field
#: into one of them has not removed it. Every class the module defines counts —
#: derived from the module, never a list.
_CORE_SCHEMAS = "apps/core/schemas.py"
_CORE_SCHEMAS_MODULE = "apps.core.schemas"


def _class_fields(tree: ast.Module) -> tuple[dict[str, dict[str, str]], dict[str, list[str]]]:
    """({class: own annotated fields}, {class: its `ast.Name` bases}) for every class."""
    fields: dict[str, dict[str, str]] = {}
    bases: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        fields[node.name] = {
            stmt.target.id: ast.unparse(stmt.annotation)
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
        bases[node.name] = [b.id for b in node.bases if isinstance(b, ast.Name)]
    return fields, bases


def _resolve_fields(
    name: str,
    fields: dict[str, dict[str, str]],
    bases: dict[str, list[str]],
    imported: dict[str, dict[str, str]],
    seen: frozenset[str] = frozenset(),
) -> dict[str, str]:
    """A class's fields with every base it names merged beneath its own."""
    if name in seen:
        return {}
    if name not in fields:
        return dict(imported.get(name, {}))
    merged: dict[str, str] = {}
    for base in bases.get(name, []):
        merged.update(_resolve_fields(base, fields, bases, imported, seen | {name}))
    merged.update(fields[name])
    return merged


_CORE_FIELDS_CACHE: dict[str, dict[str, dict[str, str]]] = {}


def _core_schema_fields(root: Path | None) -> dict[str, dict[str, str]]:
    """{class: fields, inherited within the module} for every class core schemas define."""
    if root is None:
        return {}
    key = str(root)
    if key not in _CORE_FIELDS_CACHE:
        tree = _parse(root / _CORE_SCHEMAS)
        if tree is None:
            _CORE_FIELDS_CACHE[key] = {}
        else:
            fields, bases = _class_fields(tree)
            _CORE_FIELDS_CACHE[key] = {
                name: _resolve_fields(name, fields, bases, {}) for name in fields
            }
    return _CORE_FIELDS_CACHE[key]


def _out_fields_inherited(source: str, root: Path | None) -> dict[str, dict[str, str]]:
    """`_out_fields`, with every base resolved — same-file, or from core's schemas (via `pilecap`).

    A `class RecipientOut(ArchivedOut)` whose `archived_at` moved from its own
    body into the imported base has not lost the field; reading only the class
    body (or only same-file bases) called that a REMOVAL, and two adopters paid
    a `# rule-17:` valve for it. A base imported from anywhere else is not
    resolved (declared).
    """
    own = _out_fields(source)
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return own
    fields, bases = _class_fields(tree)
    core = _core_schema_fields(root)
    facade = facade_reexports(root) if root is not None else {}
    imported: dict[str, dict[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        for alias in node.names:
            source, name = facade.get((node.module, alias.name), (node.module, alias.name))
            if source == _CORE_SCHEMAS_MODULE and name in core:
                imported[alias.asname or alias.name] = core[name]
    return {name: _resolve_fields(name, fields, bases, imported) for name in own}


def _out_fields_with_inheritance(path: Path, root: Path | None = None) -> dict[str, dict[str, str]]:
    """`_out_fields`, plus the fields an `Out` inherits from a sibling in the file
    or from a base it imports from `apps/core/schemas.py`.

    A `class WidgetDetailOut(WidgetOut)` that adds two fields has declared every
    field `WidgetOut` declared. Reading only the class body would call that a
    violation, which is a false positive the negatives keep honest.
    """
    if root is None:
        # The tree this module sits in: `apps/<x>/schemas.py` → the checkout.
        parts = path.resolve().parts
        root = Path(*parts[: parts.index("apps")]) if "apps" in parts else None
    return _out_fields_inherited(_read(path), root)


def _schema_modules(root: Path) -> list[Path]:
    """Every app's `schemas.py` — the canonical home rule 11 puts them in."""
    return [p for p in _py_files(root, "apps") if p.name == "schemas.py"]


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
    """The measured tree's paths HEAD does not carry — `quality.tree.untracked_paths`."""
    key = str(root)
    if key not in _UNTRACKED_CACHE:
        _UNTRACKED_CACHE[key] = untracked_paths(root, fresh=True)
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


def renamed_annotation(annotation: str, renamed: dict[str, str]) -> str:
    """The annotation with every renamed class spelled by its new name — word for word."""
    for old, new in renamed.items():
        annotation = re.sub(rf"\b{re.escape(old)}\b", new, annotation)
    return annotation


def schema_renames(
    before: dict[str, dict[str, dict[str, str]]],
    after: dict[str, dict[str, dict[str, str]]],
) -> dict[str, str]:
    """{old name: new name} for every Out that left under one name and was born under another.

    Both maps are `{schemas.py path: {Out class: {field: annotation}}}` over the
    change's schema modules, at the ref and at the tip. A class GONE from every
    one of them pairs with a class BORN in any of them (a name no module had at
    the ref) when their fields are equal — the gone class's annotations read
    through the renames already found, so a field naming another renamed class
    (`list[TagOut]` then `list[DjbTagOut]`) is the same field. Found to a fixed
    point, because one rename can be what makes the next one's fields equal.

    ONE CANDIDATE OR NONE. A gone class with two born classes carrying its
    fields is ambiguous and pairs with neither, so the removal stands and is
    refused — a reading that guessed which one would be a guess about the wire.
    """
    had = {cls for classes in before.values() for cls in classes}
    has = {cls for classes in after.values() for cls in classes}
    gone = [(cls, fields) for classes in before.values() for cls, fields in classes.items()]
    gone = [(cls, fields) for cls, fields in gone if cls not in has]
    born = [(cls, fields) for classes in after.values() for cls, fields in classes.items()]
    born = [(cls, fields) for cls, fields in born if cls not in had]
    renamed: dict[str, str] = {}
    progress = True
    while progress:
        progress = False
        taken = set(renamed.values())
        for old, fields in gone:
            if old in renamed:
                continue
            want = {name: renamed_annotation(ann, renamed) for name, ann in fields.items()}
            matches = [new for new, got in born if new not in taken and got == want]
            if len(matches) == 1:
                renamed[old] = matches[0]
                taken.add(matches[0])
                progress = True
    return renamed


#: Rule 17's probe of the published shape (`model_json_schema`), run per tree.
_SCHEMA_PROBE = "quality/schema_probe.py"


def _probe_schemas(tree: Path, probe: Path, specs: list[str]) -> dict[str, Any] | None:
    """`{path::Class: {field: schema}}` as `tree` publishes them, or None when it could not look."""
    try:
        proc = subprocess.run(
            [sys.executable, str(probe), *specs],
            cwd=tree,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        answer = json.loads(proc.stdout)
    except ValueError:
        return None
    return answer if isinstance(answer, dict) else None


def _ref_schemas(root: Path, ref: str, specs: list[str]) -> dict[str, Any] | None:
    """The same probe over the REF's tree: a throwaway detached worktree, removed after."""
    scratch = Path(tempfile.mkdtemp(prefix="djb-rule17-ref."))
    tree = scratch / "tree"
    try:
        added = subprocess.run(
            ["git", "-C", str(root), "worktree", "add", "--detach", "--quiet", str(tree), ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if added.returncode != 0:
            return None
        env_file = root / ".env"
        if env_file.is_file():
            (tree / ".env").write_text(env_file.read_text())
        return _probe_schemas(tree, root / _SCHEMA_PROBE, specs)
    finally:
        subprocess.run(
            ["git", "-C", str(root), "worktree", "remove", "--force", str(tree)],
            capture_output=True,
            check=False,
        )
        import shutil

        shutil.rmtree(scratch, ignore_errors=True)


def _narrows_or_equals(old: Any, new: Any) -> bool:
    """Whether an Out field's NEW published shape is one every reader of the OLD one accepts.

    Equal is safe; so is a nullable made non-nullable, an array whose items narrow, and a
    map typed as a record whose keys are all required and each value narrows the map's.
    """
    if old == new:
        return True
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False
    if isinstance(old.get("anyOf"), list):
        kept = [branch for branch in old["anyOf"] if branch != {"type": "null"}]
        if len(kept) < len(old["anyOf"]):
            if len(kept) == 1 and _narrows_or_equals(kept[0], new):
                return True
            rest = {k: v for k, v in old.items() if k != "anyOf"}
            if {**rest, "anyOf": kept} == new:
                return True
    if old.get("type") == new.get("type") == "array":
        same_rest = {k: v for k, v in old.items() if k != "items"} == {
            k: v for k, v in new.items() if k != "items"
        }
        return same_rest and _narrows_or_equals(old.get("items", {}), new.get("items", {}))
    if old.get("type") == new.get("type") == "object" and set(old) == {
        "type",
        "additionalProperties",
    }:
        properties = new.get("properties")
        return (
            isinstance(properties, dict)
            and set(new) <= {"type", "properties", "required", "additionalProperties"}
            and new.get("additionalProperties", False) is False
            and sorted(new.get("required", [])) == sorted(properties)
            and all(_narrows_or_equals(old["additionalProperties"], v) for v in properties.values())
        )
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

    # THE MOVE. A schema class that leaves one module and arrives,
    # field for field identical, in another module IN THE SAME CHANGE has not
    # left the wire — it has been promoted, which is the ordinary refactor
    # (a shared `Out` moving to `core/schemas.py`). Read per FILE, this looked
    # exactly like a deletion, and the message then offered the two heaviest
    # exits in the engine: move the mount, or declare a version. A rule that
    # answers the safest change class with "declare a breaking change" teaches
    # the version marker as a way past the gate.
    #
    # The comparison is the whole class body's fields, not the name: a class
    # that arrives elsewhere with a field removed or re-typed is a move AND a
    # break, and the message below says so instead of choosing one.
    schema_paths = [p for p in changed if p.startswith("apps/") and Path(p).name == "schemas.py"]
    schema_before = {
        p: _out_fields_inherited(_ref_source(root, ref, p), root) for p in schema_paths
    }
    schema_after = {p: _out_fields_inherited(_read(root / p), root) for p in schema_paths}

    # THE RENAME. A class that leaves under one name and is born under another
    # in the same change, field for field identical, is the same body on the
    # wire under a new component name — not a removal (`schema_renames`).
    renamed = schema_renames(schema_before, schema_after)

    #: (path, class, field, annotation before, annotation after) per re-typed field.
    retyped: list[tuple[str, str, str, str, str]] = []

    def _arrivals(cls: str, source: str) -> list[tuple[str, dict[str, str]]]:
        """Every OTHER changed schemas.py this class newly appeared in."""
        return [
            (other, schema_after[other][cls])
            for other in schema_paths
            if other != source and cls in schema_after[other] and cls not in schema_before[other]
        ]

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
            old = schema_before.get(path, _out_fields_inherited(_ref_source(root, ref, path), root))
            new = schema_after.get(path, _out_fields_inherited(_read(root / path), root))
            for cls, old_fields in old.items():
                if cls not in new:
                    arrivals = _arrivals(cls, path)
                    clean = [where for where, fields in arrivals if fields == old_fields]
                    if clean:
                        # A MOVE, not a deletion. Recorded on the diff result —
                        # and NOT on rule 17's status line today, because
                        # `live_scan` merges the diff layer's FINDINGS and not
                        # its TARGETS (quality/engine/cli.py::live_scan). The count is
                        # written here so it becomes visible the moment that
                        # merge exists; that it does not yet is flagged, not
                        # claimed away.
                        results["17"].count("schema_moves")
                        continue
                    if cls in renamed:
                        results["17"].count("schema_renames")
                        continue
                    if not v2_added:
                        broke = (
                            ""
                            if not arrivals
                            else (
                                f" It DID arrive in {', '.join(w for w, _ in arrivals)}, with "
                                "different fields — that is a move AND a break, and only the "
                                "break is this rule's."
                            )
                        )
                        results["17"].hit(
                            path,
                            1,
                            f"{cls} was removed — a breaking contract change is DECLARED: "
                            "move the mount (`API_PREFIX` in config/urls.py), or carry "
                            f"`# api-version: <N>` on a line of this app's api.py.{broke}"
                            " If you MOVED or RENAMED this class rather than deleting it, "
                            "the arrival has to land in this same change with the same "
                            "fields: a move or a rename split across two commits is a "
                            "deletion here, and nothing can tell them apart from one commit",
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
                    elif new[cls][fname] != renamed_annotation(ann, renamed):
                        if not v2_added:
                            # A RE-TYPED ANNOTATION IS A QUESTION, NOT YET A
                            # BREAK: the wire is the published schema. Judged
                            # below, once, over every re-typed field.
                            retyped.append((path, cls, fname, ann, new[cls][fname]))

        # rule 13 — a new tenant-owned service writes an audit row, which means
        # it takes tenant=; a new @service without one writes none.
        if app and is_service_module(path) and "tests" not in parts:
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
                    if "service" not in decorator_names(node):
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
        emitter = is_service_module(path) or Path(path).name == "activities.py"
        if app and emitter and "tests" not in parts:
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

    # rule 17's re-typed fields, judged by the PUBLISHED schema on both trees. A
    # probe that could not look leaves the annotation's answer standing (the
    # loud direction): a re-type nobody could prove harmless is a break.
    if retyped:
        specs = sorted({f"{path}::{cls}" for path, cls, _f, _a, _b in retyped})
        before = _ref_schemas(root, ref, specs)
        after = _probe_schemas(root, root / _SCHEMA_PROBE, specs)
        for path, cls, fname, was, now in retyped:
            spec = f"{path}::{cls}"
            old_shape = ((before or {}).get(spec) or {}).get(fname)
            new_shape = ((after or {}).get(spec) or {}).get(fname)
            if old_shape is not None and new_shape is not None:
                results["17"].count("retypes_schema_compared")
                if _narrows_or_equals(old_shape, new_shape):
                    results["17"].count("retypes_publishing_the_same_shape")
                    continue
                said = "and its published JSON schema moved"
            else:
                said = "and the published schema could not be compared on both trees"
            results["17"].hit(
                path,
                1,
                f"{cls}.{fname} changed type ({was} -> {now}) on a published Out schema {said} "
                "— a breaking change is DECLARED: move the mount (`API_PREFIX` in "
                "config/urls.py), or carry `# api-version: <N>` on a line of this app's api.py",
            )
    return results


from quality.checks.rules_10_12 import _chain_root  # noqa: E402
