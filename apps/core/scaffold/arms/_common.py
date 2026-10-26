"""What every scaffold arm shares: the refusals, the fragment insert, the shared-line records."""

from __future__ import annotations

import ast
import difflib
import importlib
import json
import keyword
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml
from django.conf import settings
from django.core.management.base import CommandError
from django.db import models
from django.template import Context, Engine

from apps.core.lexicon import PLURAL_REMEDY, looks_plural
from apps.core.management import BaseCommand
from apps.core.management.commands.newapp import (
    APP_TEMPLATE,
    LABEL,
    singular_apps_the_grammar_admits,
)
from apps.core.scaffold import anchors, floors
from apps.core.scaffold.baseline import (
    BASELINE,
    BASELINE_WRITE,
    BASELINE_WRITTEN,
    NOUN_SWEEP,
    noun_baseline,
)
from apps.core.scaffold.copier import (
    GOLDENS,
    SOURCE_NOUN,
    Copy,
    Golden,
    fenced_copy,
    overlong,
    relocations,
    snake,
    tidied,
    write_app,
)
from apps.core.scaffold.shapes import Shape, adopt_verbs

NOUN_WORD = re.compile(r"^[A-Z][A-Za-z0-9]*$")

NOUN = "noun"
#: The app the goldens are fenced in, which a run id or a search document names.
GOLDEN_APP = "example"
FIRST_MIGRATION = "0001_initial.py"

#: The longest noun every golden's lines are written to hold inside the line length.
LONGEST_NOUN = 16
FAMILIES = "apps/core/api/frozen_families.py"
FAMILIES_END = "\n)\n\n#: The departures"
BUDGETS = "quality/budgets.yaml"
PARTITION = "quality/partition.yaml"
PENDING = "golden pending — no fence on this tree"

#: The fixtures drawer a product declares its test populations in (`apps/testing/tier.py`).
DRAWER = "apps/conftest_local.py"
#: The door-parity population's name and token, as `apps/testing/tier.py` declares them.
DOOR_PARITY = ("door_parity_census", "DOOR_PAIR")
#: The parity stub `newapp` writes; a copy that claims the pair in another module retires it.
PARITY_STUB = "tests/test_doors_over_the_wire.py"

#: The flat census the role arm re-derives on the template, and the module that names its command.
FAMILY_DRAWER = "quality/local/frozen_families.yaml"
#: The product's own decision page, whose derived blocks read every `apps/*/apps.py` and door file.
ARCHITECTURE = "docs/product/architecture.md"
#: Run beside the scaffold as the tidy is: each block `quality.docs_derived` rewrote, one per line.
DERIVED = """
import sys
from pathlib import Path

from quality import docs_derived

root, page = Path(sys.argv[1]), Path(sys.argv[2])
stale = [b.name for b in docs_derived.blocks(page) if b.body != docs_derived.expected(b, root)]
docs_derived.write(page, root)
print("\\n".join(stale))
"""
BY_HAND = (
    "remove by hand — the anchored lines are yours; `--remove` reverts a noun, an adopted copy "
    "or a field"
)


@dataclass(frozen=True)
class FieldType:
    """One type `scaffold field` writes: the model field, the annotation, two samples, an import."""

    model: str
    annotation: str
    python: tuple[str, str]
    wire: tuple[str, str]
    extra: str = ""
    imports: str = ""
    #: Whether the `Out` carries the field `personal(...)` — a person's, as rule 93 reads it.
    personal: bool = False

    def field_class(self) -> type[models.Field[Any, Any]]:
        """The model field class `model` spells: `models.DateField(` is `DateField`."""
        found = getattr(models, self.model.partition("(")[0].removeprefix("models."))
        return cast("type[models.Field[Any, Any]]", found)


#: The golden's own samples, as the field's tests and examples spell them.
GOLDEN_FIELD = "due_at"
GOLDEN_PYTHON = (
    "datetime(2026, 11, 2, 17, 0, tzinfo=UTC)",
    "datetime(2026, 12, 1, 9, 30, tzinfo=UTC)",
)
GOLDEN_WIRE = ('"2026-11-02T17:00:00Z"', '"2026-12-01T09:30:00Z"')
GOLDEN_HELP = "When this widget is due, if it carries a due date."
GOLDEN_AWARE = "# Timezone-aware or refused: a moment with no offset is somebody's assumption."
UUIDS = ("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002")
#: The closed type map `scaffold field <name>:<type>?` takes.
FIELD_TYPES: dict[str, FieldType] = {
    "datetime": FieldType("models.DateTimeField(", "datetime", GOLDEN_PYTHON, GOLDEN_WIRE),
    "date": FieldType(
        "models.DateField(",
        "date",
        ("date(2026, 11, 2)", "date(2026, 12, 1)"),
        ('"2026-11-02"', '"2026-12-01"'),
        imports="from datetime import date",
    ),
    "str": FieldType(
        "models.CharField(  # noqa: DJ001",
        "str",
        ('"First"', '"Second"'),
        ('"First"', '"Second"'),
        extra="max_length=200,",
    ),
    "text": FieldType(
        "models.TextField(  # noqa: DJ001", "str", ('"First"', '"Second"'), ('"First"', '"Second"')
    ),
    "int": FieldType("models.IntegerField(", "int", ("3", "5"), ("3", "5")),
    "bool": FieldType("models.BooleanField(", "bool", ("True", "False"), ("True", "False")),
    "decimal": FieldType(
        "models.DecimalField(",
        "Decimal",
        ('Decimal("1.50")', 'Decimal("2.25")'),
        ('"1.50"', '"2.25"'),
        extra="max_digits=12,\n        decimal_places=2,",
        imports="from decimal import Decimal",
    ),
    "uuid": FieldType(
        "models.UUIDField(",
        "UUID",
        (f'UUID("{UUIDS[0]}")', f'UUID("{UUIDS[1]}")'),
        (f'"{UUIDS[0]}"', f'"{UUIDS[1]}"'),
        imports="from uuid import UUID",
    ),
}

#: A model field's class, as the field map names its type.
MODEL_TYPES: dict[str, str] = {
    "CharField": "str",
    "TextField": "text",
    "IntegerField": "int",
    "BooleanField": "bool",
    "DateTimeField": "datetime",
    "DateField": "date",
    "DecimalField": "decimal",
    "UUIDField": "uuid",
}

VERB_WORD = re.compile(r"^[a-z][a-z0-9]*(_[a-z][a-z0-9]*)*$")
#: The lexicon's verbs whose past tense no spelling rule gives.
RULES = "quality/rules.yaml"


def _particle(verb: str) -> str:
    """The `_<particle>` a phrasal verb ends in, else ``."""
    particles = importlib.import_module("quality.engine.lexicon").PARTICLES
    head, _, last = verb.rpartition("_")
    return f"_{last}" if head and last in particles else ""


def _irregular() -> dict[str, tuple[str, ...]]:
    """Rule 16's irregular table (`quality.engine.lexicon.IRREGULAR_PAST`): base → past forms."""
    table: dict[str, tuple[str, ...]] = importlib.import_module(
        "quality.engine.lexicon"
    ).IRREGULAR_PAST
    return table


def has_a_spelled_past(verb: str) -> bool:
    """Whether `past_tense(verb)`'s inflected word is an `-ed` or a tabled irregular."""
    word = past_tense(verb).removesuffix(_particle(verb)).rpartition("_")[2]
    return word.endswith("ed") or any(word in forms for forms in _irregular().values())


def past_tense(verb: str) -> str:
    """The past tense an event name says `verb` in: the irregular table, else the spelling rules."""
    if particle := _particle(verb):
        return past_tense(verb.removesuffix(particle)) + particle
    head, _, last = verb.rpartition("_")
    lead = f"{head}_" if head else ""
    if last in (table := _irregular()):
        return lead + table[last][0]
    if last.endswith("e"):
        return f"{lead}{last}d"
    if last.endswith("y") and last[-2:-1] not in ("a", "e", "i", "o", "u"):
        return f"{lead}{last[:-1]}ied"
    vowels = re.findall(r"[aeiou]+", last)
    cvc = re.search(r"[^aeiou][aeiou][^aeiouwxy]$", last)
    if len(vowels) == 1 and cvc:
        return f"{lead}{last}{last[-1]}ed"
    return f"{lead}{last}ed"


def lexicon(root: Path) -> tuple[str, ...]:
    """House rule 16's declared service verbs: its `service_verbs` list, then the product's."""
    rules = yaml.safe_load((root / RULES).read_text()) or {}
    platform: list[str] = []
    for rule in rules.get("rules") or []:
        verbs = (rule.get("scope") or {}).get("service_verbs") if isinstance(rule, dict) else None
        if verbs:
            platform = [str(v) for v in verbs]
            break
    reader = importlib.import_module("quality.engine.lexicon").service_verb_lexicon
    try:
        return cast("tuple[str, ...]", reader(root, platform))
    except ValueError as refused:
        raise _refuse(str(refused)) from refused


#: A line `enum_lines` leaves out of the fragment: the golden's own second and last values.
DROP = "\x00drop"

#: The parts house rule 84's private-copy census never reads (`quality.worlds.SKIP_PARTS`).
RULE_84_SKIPS = frozenset({"__pycache__", "migrations", "tests", "canary", "negative"})


def class_names(models: str, noun: str) -> frozenset[str]:
    """Every name class `noun` assigns in its body: its fields, its markers, its managers."""
    for node in ast.parse(models).body:
        if isinstance(node, ast.ClassDef) and node.name == noun:
            found: set[str] = set()
            for stmt in node.body:
                targets = stmt.targets if isinstance(stmt, ast.Assign) else []
                if isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                found.update(t.id for t in targets if isinstance(t, ast.Name))
            return frozenset(found)
    return frozenset()


RESETS = re.compile(r"^(?P<indent> *)resets=\(\n(?P<body>(?:.*\n)*?)(?P=indent)\),?$", re.M)


def with_reset(models: str, name: str) -> tuple[str, int] | None:
    """`models` with `name` last in its Duplicate's `resets`, and that line; None if it has none."""
    found = RESETS.search(models) if "Duplicate(" in models else None
    if found is None or f'"{name}",' in found.group("body"):
        return None
    line = f'{found.group("indent")}    "{name}",\n'
    at = found.start("body") + len(found.group("body"))
    return models[:at] + line + models[at:], models[:at].count("\n") + 1


def namespace(root: Path) -> str | None:
    """The tree's `rule_id_namespace:` by the engine's one reader; None on a template."""
    local = root / "quality/local/rules.yaml"
    doc = yaml.safe_load(local.read_text()) if local.is_file() else None
    reader = importlib.import_module("quality.engine.rules").declared_namespace
    return cast("str | None", reader(doc if isinstance(doc, dict) else {}))


EVENT_NAME = re.compile(r'^[A-Z_]+ = "([a-z0-9_]+\.[a-z0-9_]+\.[a-z0-9_]+)"', re.M)


def _served_by(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str]]:
    """`(kind, name)` a function serves by its decorators: a service, a route, its url, a tool."""
    found: list[tuple[str, str]] = []
    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        head = call.func if call is not None else decorator
        if isinstance(head, ast.Name) and head.id == "service":
            found.append(("service", node.name))
        if isinstance(head, ast.Attribute) and isinstance(head.value, ast.Name):
            words = {k.arg: k.value for k in (call.keywords if call else [])}
            if head.value.id == "router":
                found.append(("route", node.name))
                url = words.get("url_name")
                if isinstance(url, ast.Constant) and isinstance(url.value, str):
                    found.append(("url_name", url.value))
            name = words.get("name")
            if head.attr == "tool" and isinstance(name, ast.Constant):
                found.append(("tool", str(name.value)))
    return found


def served_names(files: dict[str, str], label: str) -> dict[str, dict[str, list[str]]]:
    """The served table a copy would add: `{kind: {name: [site]}}`, in the census's own form."""
    served: dict[str, dict[str, list[str]]] = {}
    for rel, text in sorted(files.items()):
        try:
            tree = ast.parse(textwrap.dedent(text))
        except SyntaxError:
            tree = ast.Module(body=[], type_ignores=[])
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for kind, name in _served_by(node):
                    served.setdefault(kind, {}).setdefault(name, []).append(
                        f"apps/{label}/{rel}:{node.lineno}"
                    )
        for found in EVENT_NAME.finditer(text):
            site = f"apps/{label}/{rel}:{text[: found.start()].count(chr(10)) + 1}"
            served.setdefault("event", {}).setdefault(found.group(1), []).append(site)
    return served


#: The page whose `newapp` step states the naming rule rule 32's refusal enforces.
ONE_PATH = "docs/sdk/the-one-path.md"


def rule_32_next(label: str, noun: str, mounted: str) -> str:
    """Rule 32's `next:`: an accepted label or noun built from the caller's words, and the page."""
    if mounted == label:
        other = f"{snake(noun)}_records"
        ask = (
            f"name the app for the collection the {noun} rows belong to — e.g. "
            f"`newapp {other}`, then `roads shape noun {other} {noun}`"
        )
    else:
        ask = (
            f"/{mounted}/ is the app `{mounted}`'s label — keep `{label}` and name a noun "
            f"whose plural no app holds, e.g. `roads shape noun {label} {noun}Item`"
        )
    return f"next: {ask}; the naming rule is {ONE_PATH} step 2 (`newapp`)."


def your_lines(root: Path, label: str, copy: Copy) -> str:
    """`apps/<label>/<module>:<line>` a copy's first edit is at: its model's class, else line 1."""
    module = "models.py" if "models.py" in copy.files else next(iter(copy.files), "models.py")
    path = root / "apps" / label / module
    text = path.read_text() if path.is_file() else ""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        tree = ast.Module(body=[], type_ignores=[])
    line = next((n.lineno for n in tree.body if isinstance(n, ast.ClassDef)), 1)
    return f"apps/{label}/{module}:{line}"


def _refuse(message: str) -> CommandError:
    """A refusal that exits 2, before any write."""
    return CommandError(message, returncode=2)


def platform_apps(root: Path) -> frozenset[str]:
    """The template's apps, read off the partition's lockfile; unreadable refuses every label."""
    try:
        loaded: Any = yaml.safe_load((root / PARTITION).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise _refuse(f"{PARTITION} is unreadable ({error})") from error
    return frozenset(str(app) for app in (loaded or {}).get("platform_apps") or [])


def regenerate_derived(root: Path) -> list[str]:
    """The derived blocks of `root / ARCHITECTURE` written over this tree's apps, a line each."""
    page = root / ARCHITECTURE
    remedy = f"run `python -m quality.docs_derived --write {ARCHITECTURE}` and read what it names"
    if not page.is_file():
        return []
    if not page.resolve().is_relative_to(root.resolve()):
        return [
            f"derived blocks: NOT regenerated — {ARCHITECTURE} links out of this tree; {remedy}"
        ]
    done = subprocess.run(  # noqa: S603 — argv list to this interpreter running a module constant program
        [sys.executable, "-P", "-c", DERIVED, str(root), str(page)],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        return [f"derived blocks: NOT regenerated (exit {done.returncode}) — {remedy}"]
    return [
        f"wrote: {ARCHITECTURE} derived block {name!r} — commit it with the app"
        for name in done.stdout.split()
    ]


def newapp_stubs(label: str) -> dict[str, str]:
    """`{relative path: text}` of every module `newapp <label>` writes, as it writes it."""
    engine = Engine()
    context = Context(
        {"app_name": label, "camel_case_app_name": label.title().replace("_", "")},
        autoescape=False,
    )
    return {
        tpl.relative_to(APP_TEMPLATE).as_posix().removesuffix("-tpl"): engine.from_string(
            tpl.read_text()
        ).render(context)
        for tpl in sorted(APP_TEMPLATE.rglob("*.py-tpl"))
    }


def _only_own(before: str, after: str, prefix: str) -> str:
    """`after` with every row outside `prefix` put back as `before` had it, or dropped if new."""
    row = re.compile(r"^\s+(\S+): \d+")
    old = {m.group(1): line for line in before.splitlines() if (m := row.match(line))}
    kept: list[str] = []
    for line in after.splitlines(keepends=True):
        matched = row.match(line)
        if matched is None or matched.group(1).startswith(prefix):
            kept.append(line)
        elif matched.group(1) in old:
            kept.append(old[matched.group(1)] + "\n")
    return "".join(kept)


def _tag_keys(copy: Copy) -> list[str]:
    """The keys of the copy's `TAGS` literal in `api.py`, in their order."""
    return _tag_keys_of(copy.files.get("api.py", ""))


def _tag_keys_of(text: str) -> list[str]:
    """The keys of a module's `TAGS` literal, in their order."""
    for node in ast.parse(text).body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "TAGS" for t in node.targets)
            and isinstance(node.value, ast.Dict)
        ):
            return [str(k.value) for k in node.value.keys if isinstance(k, ast.Constant)]
    return []


def _bound(statement: ast.stmt) -> set[str]:
    """The names an `import` or `from … import` statement binds; none for any other statement."""
    if isinstance(statement, ast.Import):
        return {(a.asname or a.name).partition(".")[0] for a in statement.names}
    if isinstance(statement, ast.ImportFrom):
        return {a.asname or a.name for a in statement.names}
    return set()


def lacks_import(module: str, line: str) -> bool:
    """Whether `module`'s top-level imports leave a name `line` binds unbound; a non-import is."""
    try:
        wanted = {name for stmt in ast.parse(line.strip()).body for name in _bound(stmt)}
        held = {name for stmt in ast.parse(module).body for name in _bound(stmt)}
    except SyntaxError:
        return True
    return not wanted or not wanted <= held


def only_lacking(pieces: list[anchors.Piece], module: str) -> list[anchors.Piece]:
    """`pieces` with every import line `module` already binds dropped, and a piece left empty."""
    kept: list[anchors.Piece] = []
    for piece in pieces:
        if piece.anchor.side == "imports" and not piece.anchor.scope:
            lines = [line for line in piece.lines if lacks_import(module, line)]
            if not lines:
                continue
            piece = anchors.Piece(piece.anchor, lines)
        kept.append(piece)
    return kept


def _module_seam(piece: anchors.Piece) -> bool:
    """Whether a fragment sits at a module's imports or end: one a new module can be born from."""
    return not piece.anchor.scope and piece.anchor.side in ("imports", "end")


def _top_level(text: str, kind: type[ast.stmt]) -> set[str]:
    """The names of a module's top-level classes or functions, or its `PREFIX` literal's value."""
    tree = ast.parse(text)
    if kind is ast.ClassDef or kind is ast.FunctionDef:
        return {node.name for node in tree.body if isinstance(node, kind)}
    return {
        str(node.value.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "PREFIX" for t in node.targets)
        and isinstance(node.value, ast.Constant)
    }


class Arms(BaseCommand):
    """The scaffold command's shared half: what every arm's write and refusal reaches."""

    dry_run = False
    removing = False

    @property
    def would(self) -> str:
        """The prefix a removal's shared-line print takes when it only plans."""
        return "would undo " if self.dry_run else ""

    @property
    def gone(self) -> str:
        """The verb a removal's file print takes: done, or only planned."""
        return "would remove" if self.dry_run else "removed"

    def written(self, root: Path, label: str, copy: Copy, argv: str, first: str = "") -> None:
        """A whole copy written over `newapp`'s stubs, every shared line it owes printed."""
        before = floors.measure(root, label) if (root / "apps" / label).is_dir() else {}
        self.write(root, label, copy, fresh=newapp_stubs(label), foot=False)
        self.retire_stub(root, label, copy)
        self.record_family(root, copy)
        self.record_budgets(root, label)
        self.record_floors(root, label, before)
        self.record_populations(root, copy)
        self.record_derived(root)
        if first and self.first_migration(root, label):
            self.first_baseline(root, label, first)
        self.stdout.write(f"undo: scaffold {argv} --remove reverts the copy and every line above")
        self.stdout.write(
            f"next: edit {your_lines(root, label, copy)}; ./scripts/feature.sh {label}"
        )

    @staticmethod
    def drawn(shape: Shape, goldens: dict[str, Golden]) -> Golden | None:
        """The extract a shape copies: its registered key, else the one fence of its word."""
        if found := goldens.get(shape.golden):
            return found
        mine = sorted(
            key for key in goldens if shape.fence and key.partition(".")[0] == shape.fence
        )
        return goldens[mine[0]] if len(mine) == 1 else None

    def golden_of(self, shape: Shape, goldens: dict[str, Golden]) -> Golden:
        """The extract a shape copies, or the pending refusal."""
        found = self.drawn(shape, goldens)
        if found is None:
            self.pending(shape, goldens)
        assert found is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
        return found

    def fragments(
        self,
        root: Path,
        golden: Golden,
        label: str,
        noun: str,
        lines: Callable[[str], str],
        imports: str = "",
        reads: dict[str, list[anchors.Piece]] | None = None,
    ) -> dict[str, list[anchors.Piece]]:
        """A fragment golden's pieces per module, renamed onto `noun` and rewritten by `lines`."""
        moves = relocations(golden.app, label, noun)
        found: dict[str, list[anchors.Piece]] = {}
        for rel in golden.files:
            read = anchors.read((root / golden.path(rel)).read_text())
            if reads is not None:
                reads[rel] = read
            pieces = anchors.renamed(read, (), moves)
            for piece in pieces:
                said = [self.renamed(lines(line), moves) for line in piece.lines]
                piece.lines = [one for line in said for one in line.split("\n") if one != DROP]
            text = "\n".join("\n".join(p.lines) for p in pieces)
            if imports and imports.rpartition(" ")[2] in text:
                pieces.append(anchors.Piece(anchors.Anchor((), "imports"), [imports]))
            found[rel] = pieces
        return found

    def additive(
        self,
        root: Path,
        golden: Golden,
        label: str,
        noun: str,
        lines: Callable[[str], str],
        options: dict[str, Any],
        imports: str = "",
        taken: str = "",
        migration: str = "",
        extra: tuple[str, str, int, str] | None = None,
        undo: str = "",
    ) -> None:
        """A fragment golden put into a noun's modules at its anchors; `extra` one module whole."""
        check, dry = bool(options["check"]), bool(options["dry_run"])
        self.refuse_names(root, label, noun, check=check)
        app_dir = root / "apps" / label
        modelled = app_dir / "models.py"
        if not check and modelled.is_file():
            if child := self.refuse_child(modelled.read_text(), label, noun):
                raise _refuse(child)
        reads: dict[str, list[anchors.Piece]] = {}
        found = self.fragments(root, golden, label, noun, lines, imports, reads)
        if check:
            self.compare_fragments(root, golden, label, found)
            return
        held = {rel: (app_dir / rel).read_text() for rel in found if (app_dir / rel).is_file()}
        anchors.carried(reads, found, held, label)
        found = {rel: only_lacking(pieces, held.get(rel, "")) for rel, pieces in found.items()}
        fragments = {
            rel: "\n".join(line for p in ps for line in p.lines) for rel, ps in found.items()
        }
        self.refuse_plants(root, label, fragments)
        self.refuse_titles(fragments)
        models = app_dir / "models.py"
        if not models.is_file() or not re.search(rf"^class {noun}\(", models.read_text(), re.M):
            raise _refuse(
                f"apps/{label}/models.py declares no `{noun}` — the shape adds to a noun "
                f"`scaffold noun {label} {noun}` wrote; scaffold the noun first."
            )
        if taken and re.search(rf"^    {taken} = models\.", models.read_text(), re.M):
            raise _refuse(f"`{noun}` already has a `{taken}` — one field per name.")
        written: dict[str, str] = {}
        places: list[tuple[str, int, str]] = []
        for rel, pieces in found.items():
            target = app_dir / rel
            if not target.is_file() and not all(_module_seam(p) for p in pieces):
                raise _refuse(
                    f"apps/{label}/{rel} is not there — the fragments go into the modules "
                    f"`scaffold noun {label} {noun}` wrote."
                )
            try:
                text, landed = anchors.insert(
                    target.read_text() if target.is_file() else "", pieces
                )
            except anchors.AnchorMissing as error:
                raise _refuse(f"apps/{label}/{rel}: {error} — nothing was written.") from error
            places.extend(
                (rel, line, p.anchor.where()) for p, line in zip(pieces, landed, strict=True)
            )
            written[rel] = tidied(text, root, rel, label)
        reset = with_reset(written.get("models.py", models.read_text()), taken) if taken else None
        if reset is not None:
            written["models.py"], at = reset
            places.append(("models.py", at, f"`{taken}` into the noun's Duplicate resets"))
        if extra is not None:
            rel, text, at, where = extra
            written[rel] = text
            places.append((rel, at, where))
        if dry:
            self.plan(root, golden, label, landed=places, migration=migration)
            if "policies.py" in written and (root / noun_baseline(label, noun)).is_file():
                self.stdout.write(
                    f"would move {noun_baseline(label, noun)}: the noun's sweep, re-run to write"
                )
            return
        for rel, line, where in places:
            self.stdout.write(f"apps/{label}/{rel}:{line} {where}")
        before = floors.measure(root, label)
        for rel, text in written.items():
            (app_dir / rel).write_text(text)
        if migration:
            try:
                self.migrate(root, label, migration)
            except CommandError:
                self.revert(app_dir, held, written, golden.key.partition(".")[0])
                raise
        if "policies.py" in written:
            self.move_baseline(root, label, noun)
        self.record_budgets(root, label)
        self.record_floors(root, label, before)
        self.record_derived(root)
        self.stdout.write(f"undo: {undo or BY_HAND}")

    def revert(
        self, app_dir: Path, held: dict[str, str], written: dict[str, str], shape: str
    ) -> None:
        """Each module `written` put back as `held` had it, a new one removed, the count printed."""
        # does-not-cover: a write a signal interrupted half-way — the revert is not a transaction.
        lines = 0
        for rel, text in written.items():
            was = held.get(rel, "")
            matcher = difflib.SequenceMatcher(a=was.splitlines(), b=text.splitlines())
            lines += sum(j2 - j1 for op, _, _, j1, j2 in matcher.get_opcodes() if op != "equal")
            if rel in held:
                (app_dir / rel).write_text(was)
            else:
                (app_dir / rel).unlink(missing_ok=True)
        self.stdout.write(
            f"reverted: {lines} lines in {len(written)} files — nothing of this {shape} remains"
        )

    @staticmethod
    def refuse_child(models: str, label: str, noun: str) -> str | None:
        """The one-line refusal when `noun` is a child row, or None when it is a noun."""
        if "derive_org_from" not in class_names(models, noun):
            return None
        return (
            f"`{noun}` in apps/{label}/models.py is a child (`scaffold child` wrote it) — a shape "
            "`on noun` adds to a noun `scaffold noun` wrote, never to a child; "
            "docs/sdk/shapes.md says what each shape goes on. Add the child's field by hand. "
            "Nothing was written."
        )

    @staticmethod
    def renamed(line: str, moves: tuple[tuple[str, str], ...]) -> str:
        """`line` under the noun's renames."""
        for old, new in moves:
            line = line.replace(old, new)
        return line

    def migrate(self, root: Path, label: str, name: str) -> None:
        """`makemigrations <label> -n <name>` beside this process, its path printed."""
        done = subprocess.run(  # noqa: S603 — argv list to this interpreter's manage.py; label and name are validated words
            [sys.executable, "manage.py", "makemigrations", label, "-n", name],
            cwd=root,
            capture_output=True,
            text=True,
        )
        said = (done.stdout + done.stderr).strip()
        if done.returncode != 0:
            raise CommandError(f"makemigrations {label} refused: {said}", returncode=1)
        for line in said.splitlines():
            if line.strip().endswith(".py"):
                self.stdout.write(f"migration: {line.strip()}")

    def first_migration(self, root: Path, label: str) -> bool:
        """The noun's `0001_initial.py` made, its path printed; False, and the command, when not."""
        done = subprocess.run(  # noqa: S603 — argv list to this interpreter's manage.py; label is a validated word
            [sys.executable, "manage.py", "makemigrations", label, "-n", "initial"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        said = (done.stdout + done.stderr).strip()
        made = f"apps/{label}/migrations/{FIRST_MIGRATION}"
        if done.returncode != 0 or not (root / made).is_file():
            last = said.splitlines()[-1] if said else ""
            self.stdout.write(
                f"migration: NOT made (makemigrations exited {done.returncode}: {last}) — run "
                f"`uv run python manage.py makemigrations {label} -n initial`."
            )
            return False
        self.stdout.write(f"migration: {made}")
        return True

    @staticmethod
    def write_baseline(root: Path, label: str) -> subprocess.CompletedProcess[str]:
        """The noun's sweep run on the copy with the write asked, so it writes the baseline."""
        return subprocess.run(  # noqa: S603 — argv list to this interpreter's pytest over the scaffold's own sweep
            [sys.executable, "-m", "pytest", f"apps/{label}/{NOUN_SWEEP}", "-q", "-k"]
            + ["baseline_says", "-p", "no:randomly", "-p", "no:cacheprovider"],
            cwd=root,
            env={**os.environ, BASELINE_WRITE: "1"},
            capture_output=True,
            text=True,
        )

    def move_baseline(self, root: Path, label: str, noun: str) -> None:
        """The noun's baseline moved by the keys a shape's policy lines add, each line printed."""
        path = noun_baseline(label, noun)
        held = root / path
        if not held.is_file():
            return
        before = held.read_text()
        done = self.write_baseline(root, label)
        if done.returncode != 0:
            held.write_text(before)
            self.stdout.write(
                f"baseline: {path} NOT moved (the sweep exited {done.returncode}) — run "
                f"`{BASELINE_WRITE}=1 uv run pytest apps/{label}/{NOUN_SWEEP}` and read the diff."
            )
            return
        was = json.loads(before)["answers"]
        now = json.loads(held.read_text())["answers"]
        moved = [f"added {key}" for key in sorted(set(now) - set(was))]
        moved += [f"removed {key}" for key in sorted(set(was) - set(now))]
        moved += [
            f"moved {key} · {cell}"
            for key in sorted(set(was) & set(now))
            for cell in sorted(set(was[key]) | set(now[key]))
            if was[key].get(cell) != now[key].get(cell)
        ]
        if not moved:
            self.stdout.write(f"baseline: {path} unmoved")
            return
        self.stdout.write(f"baseline: {path} moved — {'; '.join(moved)}; read it, commit it")

    def first_baseline(self, root: Path, label: str, noun: str) -> None:
        """The noun's sweep run once on the copy, so its first run writes the baseline."""
        path = noun_baseline(label, noun)
        sweep = f"apps/{label}/{NOUN_SWEEP}"
        done = self.write_baseline(root, label)
        if done.returncode != 0 or not (root / path).is_file():
            self.stdout.write(
                f"baseline: NOT written (the sweep exited {done.returncode}) — run "
                f"`uv run pytest {sweep}` and read what it says."
            )
            return
        self.stdout.write(BASELINE_WRITTEN.format(path=path))

    def compare_fragments(
        self, root: Path, golden: Golden, label: str, found: dict[str, list[anchors.Piece]]
    ) -> None:
        """Exit 0 when the noun's own view, fragments removed and re-inserted, reads the same."""
        # does-not-cover: blank lines — the formatter owns them, so the diff reads past them.
        verbs = adopt_verbs(root)
        drift: list[str] = []
        for rel, pieces in sorted(found.items()):
            source = (root / "apps" / label / rel).read_text()
            seen = anchors.view(source, golden.key, verbs, f"apps/{label}/{rel}")
            want = tidied(seen.text(with_key=True), root, rel, label)
            try:
                got = tidied(anchors.insert(seen.text(with_key=False), pieces)[0], root, rel, label)
            except anchors.AnchorMissing as error:
                raise CommandError(f"apps/{label}/{rel}: {error}", returncode=1) from error
            drift.extend(
                difflib.unified_diff(
                    [line for line in want.splitlines(keepends=True) if line.strip()],
                    [line for line in got.splitlines(keepends=True) if line.strip()],
                    f"apps/{label}/{rel} (fenced)",
                    f"{golden.path(rel)} (inserted)",
                )
            )
        if drift:
            self.stdout.write("".join(drift))
            raise CommandError(f"apps/{label} differs from its golden", returncode=1)
        self.stdout.write(f"apps/{label}: `{golden.key}` re-inserts line-for-line.")

    def record_family(self, root: Path, copy: Copy) -> None:
        """The copy's tag keys frozen — the core census on the template, the drawer on a product."""
        if namespace(root) is not None:
            self.record_drawer(root, copy)
            return
        census = root / FAMILIES
        text = census.read_text()
        head, closing, tail = text.partition(FAMILIES_END)
        if not closing:
            raise _refuse(f"{FAMILIES} has no `CORE_FAMILIES` tuple ending in {FAMILIES_END!r}.")
        frozen = set(re.findall(r'"([a-z0-9_-]+)"', head.partition("CORE_FAMILIES:")[2]))
        lines = [f'    "{key}",' for key in _tag_keys(copy) if key not in frozen]
        if lines:
            census.write_text(head + "".join(f"\n{line}" for line in lines) + closing + tail)
        for line in lines:
            self.stdout.write(f"frozen family: {FAMILIES} += {line.strip()}")

    def record_drawer(self, root: Path, copy: Copy) -> None:
        """The copy's tag keys appended to the product's frozen-families drawer, each printed."""
        from apps.core.api.frozen_families import FROZEN_FAMILIES, drawer_families

        drawer = root / FAMILY_DRAWER
        held = drawer_families(drawer)
        keys = [k for k in _tag_keys(copy) if k not in held and k not in FROZEN_FAMILIES]
        if not keys:
            return
        text = drawer.read_text() if held else "families:\n"
        drawer.parent.mkdir(parents=True, exist_ok=True)
        drawer.write_text(text.rstrip("\n") + "\n" + "".join(f"  - {k}\n" for k in keys))
        for key in keys:
            self.stdout.write(f"frozen family: {FAMILY_DRAWER} += {key}")

    def record_budgets(self, root: Path, label: str) -> None:
        """The copy's new budget subjects measured and written by the tidy, each line printed."""
        budgets = root / BUDGETS
        before = budgets.read_text()
        with tempfile.TemporaryFile("w+") as said:
            done = subprocess.run(
                [sys.executable, "-P", "-m", "quality.djb.rituals.tidy", "--budgets"],
                cwd=root,
                env={**os.environ, "PYTHONPATH": str(root)},
                stdout=said,
                stderr=subprocess.STDOUT,
                text=True,
            )
            said.seek(0)
            lines = said.read().splitlines()
        written = [line.strip() for line in lines if "budget applied:" in line]
        own = [line for line in written if f"apps/{label}/" in line]
        if done.returncode != 0:
            budgets.write_text(before)
            self.stdout.write(
                f"budgets: NOT recorded (the tidy exited {done.returncode}) — run "
                "`./scripts/rung_tidy.sh --budgets` and read what it names."
            )
            return
        budgets.write_text(_only_own(before, budgets.read_text(), f"apps/{label}/"))
        for line in own:
            self.stdout.write(f"budget row: {BUDGETS} {line.removeprefix('budget applied: ')}")
        for line in sorted(set(written) - set(own)):
            self.stdout.write(f"budgets: not this copy's, left unwritten — {line}")

    def record_floors(self, root: Path, label: str, before: dict[str, int] | None) -> None:
        """Rule 91's classes this write grew past `before`, each printed as a line to delete."""
        for line in floors.record(root, label, before):
            self.stdout.write(line)

    def record_derived(self, root: Path) -> None:
        """The product page's derived blocks rewritten over the app this write changed, printed."""
        for line in regenerate_derived(root):
            self.stdout.write(line)

    def record_populations(self, root: Path, copy: Copy) -> None:
        """The copy's door-parity modules added to the drawer's addend, the line printed."""
        name, token = DOOR_PARITY
        grown = sum(1 for rel, text in copy.files.items() if "tests/" in rel and token in text)
        if not grown:
            return
        drawer = root / DRAWER
        text = drawer.read_text() if drawer.is_file() else ""
        held = re.search(rf'"{name}": (\d+)', text)
        if not text:
            drawer.write_text(
                '"""This product\'s fixtures drawer: the populations its tests add."""\n\n'
                f'DJB_POPULATION_FLOOR_ADDENDS: dict[str, int] = {{"{name}": {grown}}}\n'
            )
        elif held is not None:
            total = int(held.group(1)) + grown
            drawer.write_text(text[: held.start(1)] + str(total) + text[held.end(1) :])
        else:
            self.stdout.write(
                f"population: {DRAWER} has no {name} addend — add {grown} to "
                "DJB_POPULATION_FLOOR_ADDENDS by hand."
            )
            return
        self.stdout.write(f"population: {DRAWER} DJB_POPULATION_FLOOR_ADDENDS {name} += {grown}")

    def pending(self, shape: Shape, goldens: dict[str, Golden]) -> None:
        """A shape this command cannot yet write: no extract, or an extract with no arm."""
        if shape.golden not in goldens:
            raise _refuse(
                f"`{shape.key}` has no golden extract: {PENDING}. A shape "
                "is copied from its golden and nothing else, so there is nothing to scaffold yet."
            )
        raise _refuse(
            f"`{shape.key}`'s golden is {GOLDENS}/{shape.golden}/, and its arm is not built; "
            "this command copies `adopt` today."
        )

    def refuse_held(self, root: Path, label: str, noun: str, what: str) -> None:
        """Refused when the app already holds the noun: the noun copy carries its verbs already."""
        models = root / "apps" / label / "models.py"
        lines = models.read_text().splitlines() if models.is_file() else []
        held = [n for n, text in enumerate(lines, 1) if text.startswith(f"class {noun}(")]
        if held:
            raise _refuse(
                f"apps/{label}/models.py:{held[0]} already holds `{noun}` — `{what}` copies a "
                f"whole noun into a fresh `newapp {label}`; the noun `scaffold noun` wrote "
                f"carries archive, version and history already, `scaffold verb {label} {noun} "
                "<verb>` adds a plain verb to it, and a family verb is adopted by hand from its "
                "recipe (docs/sdk/the-developers-hand.md § `adopt` vs `verb`), its worked "
                f"pattern read off the `{what}` copy in a fresh app."
            )

    @staticmethod
    def refuse_titles(files: dict[str, str]) -> None:
        """Refused before any write when a route the copy adds has a title rule 41 refuses."""
        from apps.core.api.docs import contract_half, title_faults, title_of

        try:
            tree = ast.parse(textwrap.dedent(files.get("api.py", "")))
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name)
                and d.func.value.id == "router"
                for d in node.decorator_list
            ):
                continue
            title = title_of(contract_half(ast.get_docstring(node, clean=False)))
            if faults := title_faults(title):
                raise _refuse(
                    f"the route `{node.name}` would be titled {title!r}, which {faults[0]} "
                    "(djb.E041, house rule 41) — nothing was written; name the noun or the "
                    "shape's word so its title reads as words."
                )

    def refuse_plants(self, root: Path, label: str, files: dict[str, str]) -> None:
        """Refused before any write when a name the copy would serve is a plant's (the census)."""
        plants = importlib.import_module("quality.engine.plants")
        refusals, _ = plants.plant_collision_census(
            plants.plant_collision_population(plants.RULES), served_names(files, label)
        )
        hits = [line for line in refusals if line.startswith("PLANT COLLISION — ")]
        if not hits:
            return
        name = hits[0].split(": ", 1)[1].split(" = ", 1)[0]
        plant = hits[0].split(" — ")[1].split(":")[0]
        said = f"the copy would serve {name}, which a plant of the house rules carries ({plant})"
        if namespace(root) is None:
            self.stdout.write(f"plant collision: {said} — rename the plant or pick another noun.")
            return
        raise _refuse(
            f"{said} — the canary would read the real site and go dead, and the plant is the "
            "platform's. Nothing was written; pick a noun of its own."
        )

    @staticmethod
    def claims_elsewhere(copy: Copy) -> bool:
        """Whether the copy claims its door pair in a module other than `newapp`'s stub."""
        token = DOOR_PARITY[1]
        return PARITY_STUB not in copy.files and any(
            "tests/" in rel and token in text for rel, text in copy.files.items()
        )

    def retire_stub(self, root: Path, label: str, copy: Copy) -> None:
        """`newapp`'s untouched parity stub removed when the copy's own module claims the pair."""
        stub = root / "apps" / label / PARITY_STUB
        if not self.claims_elsewhere(copy) or not stub.is_file():
            return
        if stub.read_text() != newapp_stubs(label).get(PARITY_STUB):
            return
        if not self.dry_run:
            stub.unlink()
        self.stdout.write(
            f"{self.gone} apps/{label}/{PARITY_STUB} — newapp's parity stub; the copy claims "
            "the pair in its own module"
        )

    def refuse_names(self, root: Path, label: str, noun: str, check: bool) -> None:
        """The target and the noun refused before a byte is written: rules 16 and the partition."""
        if not LABEL.match(label) or keyword.iskeyword(label):
            raise _refuse(
                f"{label!r} is no app under apps/ — a shape is copied into a product app "
                "(apps/<label>) or, for a screen, under frontend/src/; nothing else is a target."
            )
        if not check and label in platform_apps(root):
            raise _refuse(
                f"apps/{label} is a platform app ({PARTITION}) — the template's, never a "
                "product's to write into. Scaffold into an app of your own."
            )
        if not looks_plural(label) and label not in singular_apps_the_grammar_admits():
            raise _refuse(
                f"{label!r} is not plural — house rule 16: an app is a collection of things, "
                f"so this app would be born red; {PLURAL_REMEDY}."
            )
        if not NOUN_WORD.match(noun) or looks_plural(snake(noun)):
            raise _refuse(
                f"{noun!r} is not a singular PascalCase noun — house rule 16: models are "
                "singular, and the noun names the model the copy declares."
            )

    def refuse_collisions(self, root: Path, label: str, noun: str, copy: Copy) -> None:
        """Rules 83 (a schema class or mount held elsewhere), 32 (mount = label), 84 (a helper)."""
        mounts = _top_level(copy.files["api.py"], ast.Assign) if "api.py" in copy.files else set()
        labels = {name.removeprefix("apps.") for name in settings.LOCAL_APPS}
        if mounted := sorted(mounts & (labels | {label})):
            raise _refuse(
                f"the copy mounts at /{mounted[0]}/, which is an app label — house rule 32: "
                "a route's first segment is the resource, never the app. An app is the "
                f"collection its nouns belong to (`example` holds `Widget`), so its label is "
                f"never a noun's own plural.\n{rule_32_next(label, noun, mounted[0])}"
            )
        schemas = _top_level(copy.files.get("schemas.py", ""), ast.ClassDef)
        for other in sorted(labels - {label}):
            app_dir = root / "apps" / other
            theirs: set[str] = set()
            if (app_dir / "schemas.py").is_file():
                theirs |= _top_level((app_dir / "schemas.py").read_text(), ast.ClassDef)
            if (app_dir / "api.py").is_file():
                taken = _top_level((app_dir / "api.py").read_text(), ast.Assign) & mounts
                if taken:
                    raise _refuse(
                        f"apps/{other} already mounts /{sorted(taken)[0]}/ — house rule "
                        "83: one app per path. Pick a noun of its own."
                    )
            if clash := sorted(schemas & theirs):
                raise _refuse(
                    f"apps/{other} already defines {clash[0]} — house rule 83: one module "
                    "per schema class name. Pick a noun of its own."
                )
        helpers = {
            name: rel
            for rel, text in copy.files.items()
            if not RULE_84_SKIPS & set(Path(rel).parts)
            for name in _top_level(text, ast.FunctionDef)
            if name.startswith("_") and not name.endswith("__") and snake(noun) in name
        }
        for other in sorted(labels - {label}) if helpers else ():
            for path in sorted((root / "apps" / other).rglob("*.py")):
                if RULE_84_SKIPS & set(path.relative_to(root / "apps" / other).parts):
                    continue
                try:
                    defined = _top_level(path.read_text(), ast.FunctionDef)
                except SyntaxError:
                    continue
                if twin := sorted(set(helpers) & defined):
                    raise _refuse(
                        f"the copy's apps/{label}/{helpers[twin[0]]} defines `{twin[0]}`, which "
                        f"{path.relative_to(root)} already defines — house rule 84: one job, one "
                        f"private copy. Name the noun something else (e.g. `Service{noun}`)."
                    )

    def refuse_overlong(self, root: Path, label: str, noun: str, copy: Copy) -> None:
        """A copy whose renamed lines cross the line length refused before a byte is written."""
        if long := overlong(root, copy, label):
            raise _refuse(
                f"{long[0]} would pass the line length once `{SOURCE_NOUN}` reads "
                f"`{noun}` (ruff E501, {len(long)} line(s)) — the goldens hold a noun of "
                f"{LONGEST_NOUN} letters; name a shorter one."
            )

    def compare(self, root: Path, golden: Golden, label: str, copy: Copy) -> None:
        """Exit 0 when the target's own fences hold exactly the copy; the diff and 1 otherwise."""
        theirs = fenced_copy(root, golden, root / "apps" / label)
        drift: list[str] = []
        for rel in sorted(set(copy.files) | set(theirs)):
            drift.extend(
                difflib.unified_diff(
                    theirs.get(rel, "").splitlines(keepends=True),
                    copy.files.get(rel, "").splitlines(keepends=True),
                    f"apps/{label}/{rel} (fenced)",
                    f"{golden.path(rel)} (generated)",
                )
            )
        if drift:
            self.stdout.write("".join(drift))
            raise CommandError(f"apps/{label} differs from its golden", returncode=1)
        self.stdout.write(f"apps/{label}: `{golden.key}` regenerates byte-for-byte.")

    @staticmethod
    def refuse_taken(root: Path, label: str, copy: Copy, fresh: dict[str, str] | None) -> None:
        """Refused when a module the copy writes is there and is not `fresh`'s untouched stub."""
        destination = root / "apps" / label
        stubs = fresh or {}
        taken = sorted(
            rel
            for rel in copy.files
            if (destination / rel).exists() and (destination / rel).read_text() != stubs.get(rel)
        )
        if taken:
            raise _refuse(
                f"apps/{label}/{taken[0]} already exists — the scaffold writes new modules and "
                "never overwrites one: one noun per app — a second noun is a second `newapp` "
                "(docs/sdk/the-developers-hand.md § One noun per app)."
            )

    def plan(
        self,
        root: Path,
        golden: Golden | None,
        label: str,
        copy: Copy | None = None,
        fresh: dict[str, str] | None = None,
        noun: bool = False,
        landed: Sequence[tuple[str, int, str]] = (),
        migration: str = "",
        records: bool = True,
        written: Sequence[tuple[str, int, str]] = (),
        inserted: Sequence[tuple[str, int, str]] = (),
        baseline: bool = False,
    ) -> None:
        """`--dry-run`: one `would` line per path or anchor the write touches, refused as it is."""
        if copy is None:
            for path, lines, source in written:
                self.stdout.write(f"would write {path}:1-{lines} from {source}")
            for path, line, where in inserted:
                self.stdout.write(f"would insert {path}:{line} {where}")
            if baseline:
                self.stdout.write(f"would record {BASELINE}: the flat census, re-derived")
            for rel, line, where in landed:
                self.stdout.write(f"would insert apps/{label}/{rel}:{line} {where}")
            if migration:
                self.stdout.write(f"would migrate apps/{label}/migrations/ named {migration}")
            if not records:
                return
            self.stdout.write(f"would record {BUDGETS}: the budget rows of apps/{label}/")
            self.stdout.write(
                f"would record apps/{label}/apps.py: ratchet_floors, rule 91's classes"
            )
            return
        assert golden is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
        self.refuse_taken(root, label, copy, fresh)
        for rel, text in copy.files.items():
            lines = text.count("\n")
            self.stdout.write(f"would write apps/{label}/{rel}:1-{lines} from {golden.path(rel)}")
        if not noun:
            return
        if namespace(root) is not None:
            for key in _tag_keys(copy):
                self.stdout.write(f"would append {FAMILY_DRAWER}:1 {key}")
        else:
            census = (root / FAMILIES).read_text().partition(FAMILIES_END)[0]
            at = census.count("\n") + 2
            for key in _tag_keys(copy):
                self.stdout.write(f'would append {FAMILIES}:{at} "{key}",')
        self.stdout.write(f"would record {BUDGETS}: the budget rows of apps/{label}/")
        self.stdout.write(f"would record apps/{label}/apps.py: ratchet_floors, rule 91's classes")
        name, token = DOOR_PARITY
        grown = sum(1 for rel, text in copy.files.items() if "tests/" in rel and token in text)
        if grown:
            self.stdout.write(f"would add {DRAWER}: DJB_POPULATION_FLOOR_ADDENDS {name} += {grown}")

    def write(
        self,
        root: Path,
        label: str,
        copy: Copy,
        fresh: dict[str, str] | None = None,
        foot: bool = True,
    ) -> None:
        """The copy written, refused first if a module it writes is there and not `fresh`'s stub."""
        self.refuse_taken(root, label, copy, fresh)
        write_app(root / "apps" / label, label, copy)
        for line in copy.report():
            self.stdout.write(line)
        if foot:
            self.stdout.write(
                f"next: edit {your_lines(root, label, copy)}; ./scripts/feature.sh {label}"
            )
