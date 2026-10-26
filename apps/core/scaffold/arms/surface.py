"""The `surface` and `role` arms: a declaration copied beside its app's models."""

from __future__ import annotations

import ast
import difflib
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from django.core.management.base import CommandError

from apps.core.management.commands.newapp import LABEL
from apps.core.scaffold.arms._common import (
    PARTITION,
    PENDING,
    Arms,
    _refuse,
    _tag_keys_of,
    namespace,
    platform_apps,
)
from apps.core.scaffold.baseline import BASELINE, BASELINE_COMMAND
from apps.core.scaffold.copier import Copy, Golden, fenced_copy, tidied, unfenced
from apps.core.scaffold.shapes import SHAPES, Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("surface", "role")

SURFACE_WORD = re.compile(r"^[a-z][a-z0-9_]*$")

SURFACE = "surface"
ROLE = "role"

#: The two declarations a surface and a role are copied into, beside their app's models.
SURFACES_MODULE = "surfaces.py"
ROLES_MODULE = "roles.py"


def _tags_of(root: Path, label: str) -> list[str]:
    """The keys of an app's own `TAGS`: the families its doors answer."""
    api = root / "apps" / label / "api.py"
    return _tag_keys_of(api.read_text()) if api.is_file() else []


#: The bases a model class in `models.py` inherits from outside its own file.
MODEL_BASES = frozenset({"BaseModel", "TenantScopedModel", "OrgScopedModel", "Model"})
KINDS_READ = (
    "each `<kind>.read` is read from models.py alone — a model in another module, an "
    "`authz_kind_of` parent in another app, or a base other than BaseModel, TenantScopedModel or "
    "OrgScopedModel gives no kind, and two models of one kind give it once; name what is missing "
    "in --permissions."
)


def _kinds_of(root: Path, label: str) -> list[str]:
    """The authorization kinds `apps/<label>/models.py` declares, in definition order."""
    models_py = root / "apps" / label / "models.py"
    return _kinds_in(models_py.read_text()) if models_py.is_file() else []


def _kinds_in(text: str) -> list[str]:
    """`apps.core.authz.kind_of` over a models module's source, read without installing it."""
    from apps.core.authz import snake_case

    kinds: dict[str, str | None] = {}
    seen = set(MODEL_BASES)
    for node in ast.parse(text).body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {
            b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "") for b in node.bases
        }
        if not bases & seen:
            continue
        seen.add(node.name)
        if _abstract(node):
            continue
        declared = _class_values(node)
        if "authz_kind_of" in declared:
            parent = _foreign_target(node, str(declared["authz_kind_of"]))
            kinds[node.name] = kinds.get(parent) if parent else None
        elif "authz_kind" in declared:
            kinds[node.name] = declared["authz_kind"]
        else:
            kinds[node.name] = snake_case(node.name)
    return list(dict.fromkeys(k for k in kinds.values() if k))


def _abstract(node: ast.ClassDef) -> bool:
    meta = next((n for n in node.body if isinstance(n, ast.ClassDef) and n.name == "Meta"), None)
    return meta is not None and _class_values(meta).get("abstract") is True


def _class_values(node: ast.ClassDef) -> dict[str, Any]:
    """The literal values a class body assigns, plain or annotated."""
    held: dict[str, Any] = {}
    for stmt in node.body:
        target = stmt.targets[0] if isinstance(stmt, ast.Assign) else getattr(stmt, "target", None)
        value = getattr(stmt, "value", None)
        if isinstance(target, ast.Name) and value is not None:
            try:
                held[target.id] = ast.literal_eval(value)
            except ValueError:
                held.setdefault(target.id, value)
    return held


def _foreign_target(node: ast.ClassDef, field: str) -> str | None:
    """The class name a field's foreign key points at, as written in its first argument."""
    call = _class_values(node).get(field)
    if not isinstance(call, ast.Call) or not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value.rsplit(".", 1)[-1]
    return first.id if isinstance(first, ast.Name) else None


def _listed(raw: object) -> list[str]:
    """A comma-separated option as its words; none when it was not given."""
    return [word.strip() for word in str(raw or "").split(",") if word.strip()]


def declared_values(text: str) -> dict[str, Any]:
    """A declaration module's one entry: `""` its dict key, then each keyword's literal value."""
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Dict) and len(node.keys) == 1:
            entry, call = node.keys[0], node.values[0]
            if isinstance(entry, ast.Constant) and isinstance(call, ast.Call):
                held: dict[str, Any] = {"": entry.value}
                for keyword_ in call.keywords:
                    if keyword_.arg:
                        held[keyword_.arg] = ast.literal_eval(keyword_.value)
                return held
    raise _refuse("the golden declares no one-entry dict — it is not a surface or a role.")


def _literal(value: Any) -> str:
    """A value as the declaration spells it: a sorted set, a tuple, a string."""
    if isinstance(value, (set, frozenset)):
        return "{" + ", ".join(json.dumps(v) for v in sorted(value)) + "}" if value else "set()"
    if isinstance(value, tuple):
        return (
            "(" + ", ".join(json.dumps(v) for v in value) + ("," if len(value) == 1 else "") + ")"
        )
    return json.dumps(value)


def redeclared(text: str, values: dict[str, Any]) -> str:
    """`text` with its one entry's dict key and named keywords re-spelled from `values`."""
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    spans: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and len(node.keys) == 1:
            entry, call = node.keys[0], node.values[0]
            if isinstance(entry, ast.Constant) and isinstance(call, ast.Call):
                targets: list[tuple[ast.expr, str]] = [(entry, "")]
                targets += [(k.value, k.arg) for k in call.keywords if k.arg in values]
                for target, name in targets:
                    if name not in values or ast.literal_eval(target) == values[name]:
                        continue
                    start = offsets[target.lineno - 1] + target.col_offset
                    end = offsets[(target.end_lineno or target.lineno) - 1] + (
                        target.end_col_offset or 0
                    )
                    spans.append((start, end, _literal(values[name])))
    for start, end, spelled in sorted(spans, reverse=True):
        text = text[:start] + spelled + text[end:]
    return text


class SurfaceArm(Arms):
    """`scaffold surface` and `scaffold role`."""

    def declare(
        self, root: Path, goldens: dict[str, Golden], registered: Shape, options: dict[str, Any]
    ) -> None:
        """`surface <app> <key> --role <name>` · `role <app> <key> --permissions …`."""
        words = [str(w) for w in options["words"]]
        if len(words) != 2:
            raise _refuse(
                f"{registered.key} takes <app> <key> — e.g. `scaffold surface partners partner "
                "--role viewer` or `scaffold role partners viewer --permissions order.read`."
            )
        label, key = words
        check = bool(options["check"])
        surfacing = registered.key == SURFACE
        role = str(options["role"] or "") if surfacing else key
        if surfacing and not role:
            raise _refuse("surface takes --role <name>: the one role the surface admits.")
        wanted = [f"{registered.golden}.{SURFACE}"] if surfacing else []
        wanted.append(f"{next(s.golden for s in SHAPES if s.key == ROLE)}.{ROLE}")
        missing = [name for name in wanted if name not in goldens]
        if missing:
            raise _refuse(f"`{registered.key}` has no golden extract `{missing[0]}`: {PENDING}.")
        self.refuse_declaration(root, label, key, role, check, surfacing)
        sources = [goldens[name] for name in wanted]
        same = label == sources[0].app
        copy = Copy()
        for golden in sources:
            (rel,) = golden.files
            text = (root / golden.path(rel)).read_text()
            values = self.values(root, label, key, role, options, text, same, surfacing)
            copy.files[rel] = tidied(unfenced(redeclared(text, values)), root, rel, label)
            copy.spans[rel] = golden.path(rel)
        if check:
            theirs: dict[str, str] = {}
            for golden in sources:
                theirs.update(fenced_copy(root, golden, root / "apps" / label))
            self.compare_files(label, f"{registered.key} {key}", theirs, copy)
            return
        taken = sorted(rel for rel in copy.files if (root / "apps" / label / rel).exists())
        if taken:
            raise _refuse(
                f"apps/{label}/{taken[0]} already exists — the scaffold writes new modules and "
                f"never overwrites one; add the entry by hand:\n{copy.files[taken[0]]}"
            )
        if self.dry_run:
            written = [
                (f"apps/{label}/{rel}", text.count("\n"), copy.spans[rel])
                for rel, text in copy.files.items()
            ]
            self.plan(root, None, label, written=written, records=False, baseline=True)
            return
        for rel, text in copy.files.items():
            (root / "apps" / label / rel).write_text(text)
            self.stdout.write(f"copied apps/{label}/{rel} from {copy.spans[rel]}")
        self.rederive_baseline(root)
        if not same and not options["permissions"]:
            self.stdout.write(f"kinds: {KINDS_READ}")
        if surfacing:
            self.stdout.write(
                f"Next: the `{key}` surface's pages — a route-table row with `surfaces: "
                f'["{key}"]` each, named in its `screens` (house rule 85), and SURFACE_HOSTS.'
            )

    def refuse_declaration(
        self, root: Path, label: str, key: str, role: str, check: bool, surfacing: bool
    ) -> None:
        """The app, the keys and the one-surface rule refused before a byte is written."""
        if not LABEL.match(label) or not (root / "apps" / label / "apps.py").is_file():
            raise _refuse(f"{label!r} is no app under apps/ — a declaration lives in its app.")
        if not check and label in platform_apps(root):
            raise _refuse(
                f"apps/{label} is a platform app ({PARTITION}) — the template's, never a "
                "product's to write into. Declare it in an app of your own."
            )
        for word in (key, role):
            if not SURFACE_WORD.match(word):
                raise _refuse(f"{word!r} is no key — lower case, a letter first, `_` between.")
        from apps.core.authz import OWNER_ROLE, role_declarers

        holder = role_declarers().get(role, "core" if role == OWNER_ROLE else "")
        if holder and holder != label:
            raise _refuse(
                f"the role {role!r} is apps/{holder}'s — a role belongs to one surface, so the "
                "surface admits a role of its own app's; name a new one."
            )

    def values(
        self,
        root: Path,
        label: str,
        key: str,
        role: str,
        options: dict[str, Any],
        text: str,
        same: bool,
        surfacing: bool,
    ) -> dict[str, Any]:
        """The declaration's new values: the golden's own on its own app, the target's elsewhere."""
        held = declared_values(text)
        families = _listed(options["families"])
        permissions = _listed(options["permissions"])
        if "families" in held:
            return {
                "": key,
                "roles": {role},
                "families": set(families or ([] if same else _tags_of(root, label)))
                or held["families"],
                "screens": held["screens"] if same else set(),
            }
        chosen = tuple(permissions) or (
            held["permissions"]
            if same
            else tuple(f"{kind}.read" for kind in _kinds_of(root, label))
        )
        if not chosen:
            raise _refuse(f"role {role!r} holds nothing — name its --permissions.")
        return {
            "": role,
            "key": role,
            "name": role.replace("_", " ").capitalize() if not same else held["name"],
            "permissions": chosen,
            "description": held["description"] if same else f"Holds {', '.join(chosen)}.",
        }

    def compare_files(self, label: str, what: str, theirs: dict[str, str], copy: Copy) -> None:
        """Exit 0 when the app's own fences hold exactly the copy; the diff and 1 otherwise."""
        drift: list[str] = []
        for rel in sorted(set(copy.files) | set(theirs)):
            drift.extend(
                difflib.unified_diff(
                    theirs.get(rel, "").splitlines(keepends=True),
                    copy.files.get(rel, "").splitlines(keepends=True),
                    f"apps/{label}/{rel} (fenced)",
                    f"{copy.spans.get(rel, rel)} (generated)",
                )
            )
        if drift:
            self.stdout.write("".join(drift))
            raise CommandError(f"apps/{label} differs from its golden", returncode=1)
        self.stdout.write(f"apps/{label}: `{what}` regenerates byte-for-byte.")

    def rederive_baseline(self, root: Path) -> None:
        """The flat census re-derived by its own command on the template; printed, not judged."""
        if namespace(root) is not None:
            self.stdout.write(
                f"baseline: {BASELINE} is the platform's — a product's role never moves it."
            )
            return
        before = (root / BASELINE).read_text()
        command = BASELINE_COMMAND
        done = subprocess.run(shlex.split(command), cwd=root, capture_output=True, text=True)  # noqa: S603 — BASELINE_COMMAND is a module constant split to argv; no shell
        if done.returncode != 0:
            (root / BASELINE).write_text(before)
            self.stdout.write(f"baseline: NOT re-derived — run `{command}` and read what it says.")
            return
        after = (root / BASELINE).read_text()
        roles = (json.loads(before)["roles"], json.loads(after)["roles"])
        moved = sum(
            1
            for line in difflib.unified_diff(before.splitlines(), after.splitlines(), n=0)
            if line[:1] in "+-" and line[:3] not in ("+++", "---")
        )
        self.stdout.write(
            f"baseline: {BASELINE} re-derived — roles {roles[0]} -> {roles[1]}, {moved} "
            "line(s) moved; `test_flat_baseline_document` holds it."
        )
