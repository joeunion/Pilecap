"""The `field` arm: a nullable field written through a noun's every door."""

# does-not-cover: a default — the arm writes nullable fields only; a default is the hand's.
# does-not-cover: a non-nullable column — rule 22 refuses it before a byte is written.
# does-not-cover: a child row — the arm adds to a noun `scaffold noun` wrote, never to a child.
# does-not-cover: a base imported by star or alias — `_reserved` reads bases imported by name.
# does-not-cover: a person's word rule 93's lexicon lacks (`nickname`) — plain samples, the gate's.

from __future__ import annotations

import ast
import importlib
import keyword
import re
from dataclasses import replace
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from django.conf import settings

from apps.core.scaffold.arms._common import (
    FIELD_TYPES,
    GOLDEN_AWARE,
    GOLDEN_FIELD,
    GOLDEN_HELP,
    GOLDEN_PYTHON,
    GOLDEN_WIRE,
    RULES,
    FieldType,
    _refuse,
    class_names,
)
from apps.core.scaffold.arms.remove import RemoveArm
from apps.core.scaffold.copier import Golden, snake
from apps.core.scaffold.shapes import Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("field",)

FIELD_SPEC = re.compile(r"^(?P<name>[a-z][a-z0-9_]*):(?P<type>[a-z]+)(?P<tail>\?|=.*)?$")
LOCAL_TZ = re.compile(r"(\w+)\.astimezone\(UTC\) if \1 is not None else None")
#: The golden `Out` line: the one a person's field wraps in `personal(...)`.
GOLDEN_OUT = f"{GOLDEN_FIELD}: datetime | None = Field(default=None, json_schema_extra=example("
MARKED = "json_schema_extra=personal(example("
PERSONAL_IMPORT = "from pilecap import personal"
#: A person's samples by the lexicon word that reads the field as one; a name is the default.
SHAPED: dict[str, tuple[str, str]] = {
    "email": ("sam@example.com", "kim@example.com"),
    "phone": ("+1 555 0100", "+1 555 0199"),
    "handle": ("@sam", "@kim"),
}
PERSON = ("Sam Rivera", "Kim Lee")


def field_lines(line: str, name: str, kind: FieldType) -> str:
    """A golden `due_at` line as the field `name` of `kind` reads it, before the noun's rename."""
    out = kind.personal and line.strip().startswith(GOLDEN_OUT)
    if kind.model != FIELD_TYPES["datetime"].model:
        line = line.replace(FIELD_TYPES["datetime"].model, kind.model)
        if kind.extra and line.strip() == "null=True,":
            line = line.replace("null=True,", f"{kind.extra}\n        null=True,")
        line = line.replace("AwareDatetime | None", f"{kind.annotation} | None")
        line = line.replace("datetime | None", f"{kind.annotation} | None")
        line = LOCAL_TZ.sub(r"\1", line)
        line = "" if line.strip() == GOLDEN_AWARE else line
        for old, new in (
            *zip(GOLDEN_PYTHON, kind.python, strict=True),
            *zip(GOLDEN_WIRE, kind.wire, strict=True),
        ):
            line = line.replace(old, new)
    if out:
        line = line.replace("json_schema_extra=example(", MARKED).removesuffix("))") + ")))"
    if name != GOLDEN_FIELD or kind.model != FIELD_TYPES["datetime"].model:
        line = line.replace(GOLDEN_HELP, f"The widget's {name.replace('_', ' ')}, if it has one.")
    return line.replace(GOLDEN_FIELD, name).replace(GOLDEN_FIELD.upper(), name.upper())


def naming_refusal(name: str, type_word: str) -> str | None:
    """Rule 15's refusal for a field `name` of `type_word`, in the system check's own sentence."""
    from apps.core.checks import field_name_policy

    broken = field_name_policy(FIELD_TYPES[type_word].field_class(), name)
    if broken is None:
        return None
    return (
        f"`{name}:{type_word}?` would be born red at `makemigrations` (djb.E015): {broken} "
        "Name the field to the rule. Nothing was written."
    )


@cache
def _person_lexicon(root: Path) -> dict[str, Any]:
    """Rule 93's detector lexicon, read from the rule itself."""
    rules = yaml.safe_load((root / RULES).read_text()) or {}
    rule = next(r for r in rules.get("rules") or [] if str(r.get("id")) == "93")
    return dict(rule.get("lexicon") or {})


def personal_kind(noun: str, name: str, kind: FieldType) -> FieldType | None:
    """`kind` with a person's samples and the `personal` mark when rule 93 reads `name` as one."""
    if kind.annotation != "str":
        return None
    hit = importlib.import_module("quality.checks.rule_93")._lexicon_hit
    if hit(f"{noun}Out", name, _person_lexicon(Path(settings.BASE_DIR))) is None:
        return None
    word = next((w for w in SHAPED if name.endswith(w)), "")
    first, second = (f'"{sample}"' for sample in SHAPED.get(word, PERSON))
    return replace(
        kind, python=(first, second), wire=(first, second), personal=True, imports=PERSONAL_IMPORT
    )


def _reserved(root: Path, label: str, noun: str, name: str) -> str | None:
    """Who already holds `name` on the noun — its own body or a base it inherits — or None."""
    models = root / "apps" / label / "models.py"
    if not models.is_file():
        return None
    source = models.read_text()
    tree = ast.parse(source)
    node = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == noun), None)
    if node is None:
        return None
    own = class_names(source, noun) | {
        n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    if name in own:
        return f"apps/{label}/models.py's `{noun}` declares it"
    imported = {
        alias.asname or alias.name: (stmt.module or "", alias.name)
        for stmt in tree.body
        if isinstance(stmt, ast.ImportFrom)
        for alias in stmt.names
    }
    for base in node.bases:
        if not isinstance(base, ast.Name) or base.id not in imported:
            continue
        module, attr = imported[base.id]
        try:
            held = getattr(importlib.import_module(module), attr)
        except (ImportError, AttributeError):
            continue
        meta = getattr(held, "_meta", None)
        fields = meta.fields if meta else ()
        columns = {f.name for f in fields} | {f.attname for f in fields}
        if name in columns or hasattr(held, name):
            return f"its base `{base.id}` ({module}) carries it"
    return None


class FieldArm(RemoveArm):
    """`scaffold field`."""

    def field(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`field <app> <Noun> <name>:<type>?`: a nullable field through the noun's every door."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 3:
            raise _refuse(
                "field takes <app> <Noun> <name>:<type>? — e.g. `field orders Order note:text?`."
            )
        label, noun, spec = words
        matched = FIELD_SPEC.match(spec)
        if matched is None or matched.group("type") not in FIELD_TYPES:
            raise _refuse(
                f"{spec!r} is no `<name>:<type>?` over the closed types "
                f"({' '.join(FIELD_TYPES)}) — e.g. `color:str?`."
            )
        name, type_word, tail = matched.group("name"), matched.group("type"), matched.group("tail")
        kind = FIELD_TYPES[type_word]
        kind = personal_kind(noun, name, kind) or kind
        if keyword.iskeyword(name):
            raise _refuse(f"{name!r} is a Python keyword, never a field name.")
        if not tail:
            raise _refuse(
                f"`{name}` is not nullable and names no default — house rule 22: a NOT NULL "
                "column added without a default cannot migrate a table that has rows. Write "
                f"`{name}:{type_word}?`."
            )
        if tail.startswith("="):
            raise _refuse(
                f"`{name}` names a default — the scaffold writes nullable fields only (`?`); a "
                "default is the developer's hand in the model, then `makemigrations`."
            )

        def lines(line: str) -> str:
            return field_lines(line, name, kind)

        migration = f"{snake(noun)}_{name}"
        if self.removing:
            self.refuse_names(root, label, noun, check=False)
            self.remove_fragments(root, golden, label, noun, lines, kind.imports, name, migration)
            return
        if broken := naming_refusal(name, type_word):
            raise _refuse(broken)
        check = bool(options["check"])
        self.refuse_names(root, label, noun, check=check)
        if not check and (holder := _reserved(root, label, noun, name)):
            raise _refuse(
                f"`{name}` is `{noun}`'s already — {holder}, and a field of that name would "
                "shadow it. Name the field something of its own. Nothing was written."
            )
        self.additive(
            root,
            golden,
            label,
            noun,
            lines,
            options,
            imports=kind.imports,
            taken=name,
            migration=migration,
            undo=f"scaffold field {label} {noun} {spec} --remove reverts every line above",
        )
