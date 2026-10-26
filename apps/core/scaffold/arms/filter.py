"""The `filter` arm: a list narrowing on both doors, over the closed lookups."""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.management.base import CommandError

from apps.core.scaffold.arms._common import FIELD_TYPES, MODEL_TYPES, Arms, _refuse
from apps.core.scaffold.copier import SOURCE_NOUN, Golden, snake
from apps.core.scaffold.shapes import Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("filter",)

#: The closed lookups `scaffold filter` takes, and the types each reads.
LOOKUPS: dict[str, frozenset[str]] = {
    "exact": frozenset(FIELD_TYPES),
    "icontains": frozenset({"str", "text"}),
    "gte": frozenset({"int", "decimal", "date", "datetime"}),
    "lte": frozenset({"int", "decimal", "date", "datetime"}),
}
FILTER_SPEC = re.compile(r"^(?P<name>[a-z][a-z0-9_]*)=(?P<lookup>[a-z]+)$")
#: The filter golden's own lines, as `filter name=icontains` spells them.
GOLDEN_FILTER = (
    'name: Annotated[str | None, FilterLookup(q="name__icontains")] = Field(',
    'default=None, json_schema_extra=example("bench")',
    "name: str | None = None,",
    "filters.name = name",
    'NAME_FINDS: dict[str, Any] = {"name": "Left bench"}',
    'NAME_MISSES: dict[str, Any] = {"name": "Other"}',
    'NAME_ASKS: dict[str, Any] = {"name": "bench"}',
)


def filtered(schemas: Path, cls: str, param: str) -> int:
    """The line `cls` in `schemas` declares `param` on, 0 when it declares none."""
    tree = ast.parse(schemas.read_text() if schemas.is_file() else "")
    return next(
        (
            node.lineno
            for top in tree.body
            if isinstance(top, ast.ClassDef) and top.name == cls
            for node in top.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == param
        ),
        0,
    )


def held_lookup(schemas: Path, line: int) -> str:
    """The lookup the filter declared on `line` of `schemas` reads: its `q`'s suffix, or exact."""
    said = re.search(
        r'FilterLookup\(q="\w+?(?:__(\w+))?"\)', schemas.read_text().split("\n")[line - 1]
    )
    return (said.group(1) or "exact") if said else "exact"


@dataclass(frozen=True)
class Choices:
    """An enum field's choices class and its first two members, as `models.py` declares them."""

    cls: str
    members: tuple[str, str]
    first: str


@dataclass(frozen=True)
class Declared:
    """What the noun's `models.py` and `services.py` say about one field a filter names."""

    model: str
    choices: Choices | None
    created: bool


def _assigned(body: list[ast.stmt]) -> dict[str, ast.expr]:
    """Each plain `name = <value>` in a class body, by name."""
    return {
        target.id: stmt.value
        for stmt in body
        if isinstance(stmt, ast.Assign)
        for target in stmt.targets
        if isinstance(target, ast.Name)
    }


def declared_field(models: str, services: str, noun: str, field: str) -> Declared | None:
    """`field` on class `noun` in a models module's text, or None when the noun has none."""
    found = next(
        (n for n in ast.parse(models).body if isinstance(n, ast.ClassDef) and n.name == noun), None
    )
    value = _assigned(found.body).get(field) if found is not None else None
    if found is None or not isinstance(value, ast.Call):
        return None
    func = value.func
    model = func.attr if isinstance(func, ast.Attribute) else ""
    said = next((k.value for k in value.keywords if k.arg == "choices"), None)
    cls = (
        said.value.id
        if isinstance(said, ast.Attribute)
        and said.attr == "choices"
        and isinstance(said.value, ast.Name)
        else ""
    )
    inner = next((n for n in found.body if isinstance(n, ast.ClassDef) and n.name == cls), None)
    members = [
        (name, said_value.elts[0].value)
        for name, said_value in (_assigned(inner.body) if inner is not None else {}).items()
        if isinstance(said_value, ast.Tuple)
        and said_value.elts
        and isinstance(said_value.elts[0], ast.Constant)
        and isinstance(said_value.elts[0].value, str)
    ]
    choices = (
        Choices(cls, (members[0][0], members[1][0]), members[0][1]) if len(members) >= 2 else None
    )
    create = f"create_{snake(noun)}"
    takes = next(
        (
            {a.arg for a in n.args.kwonlyargs}
            for n in ast.parse(services).body
            if isinstance(n, ast.FunctionDef) and n.name == create
        ),
        set(),
    )
    return Declared(model, choices, field in takes)


#: The golden test's two rows, as `filter name=icontains` spells them, after its `NAME_` rename.
GOLDEN_ROWS = (
    'found = create_widget(tenant=tenant, actor=owner_actor, **{{"name": "Found", **{}_FINDS}})',
    'create_widget(tenant=tenant, actor=owner_actor, **{{"name": "Missed", **{}_MISSES}})',
)


def filter_lines(
    line: str,
    field: str,
    lookup: str,
    kind: str,
    choices: Choices | None = None,
    created: bool = True,
) -> str:
    """A golden `name` filter line as the `field=lookup` filter of type `kind`, enum or not."""
    param = field if lookup in ("exact", "icontains") else f"{field}_{lookup}"
    sort = FIELD_TYPES[kind]
    hint = "AwareDatetime" if kind == "datetime" else sort.annotation
    query = field if lookup == "exact" else f"{field}__{lookup}"
    first, second = sort.python
    sample = '"bench"' if lookup == "icontains" else sort.wire[0]
    if choices is not None:
        first, second = (f"{SOURCE_NOUN}.{choices.cls}.{m}" for m in choices.members)
        sample = f'"{choices.first}"'
    finds, misses, asks = {
        "icontains": ('"Left bench"', '"Other"', '"bench"'),
        "exact": (first, second, first),
        "gte": (second, first, second),
        "lte": (first, second, first),
    }[lookup]
    if choices is not None and lookup == "icontains":
        finds, misses, asks = first, second, sample
    said = (
        f'{param}: Annotated[{hint} | None, FilterLookup(q="{query}")] = Field(',
        f"default=None, json_schema_extra=example({sample})",
        f"{param}: {hint} | None = None,",
        f"filters.{param} = {param}",
        f'{param.upper()}_FINDS: dict[str, Any] = {{"{field}": {finds}}}',
        f'{param.upper()}_MISSES: dict[str, Any] = {{"{field}": {misses}}}',
        f'{param.upper()}_ASKS: dict[str, Any] = {{"{param}": {asks}}}',
    )
    for old, new in zip(GOLDEN_FILTER, said, strict=True):
        if line.strip() == old:
            return line.replace(old, new)
    line = line.replace("NAME_", f"{param.upper()}_").replace(
        "the_name_filter", f"the_{param}_filter"
    )
    if not created:
        indent = line[: len(line) - len(line.lstrip())]
        for row, held, side in zip(
            GOLDEN_ROWS, ("found", "missed"), ("FINDS", "MISSES"), strict=True
        ):
            if line.strip() == row.format(param.upper()):
                create = f'create_widget(tenant=tenant, actor=owner_actor, name="{held.title()}")'
                return (
                    f"{indent}{held} = {create}\n{indent}{SOURCE_NOUN}.objects.filter("
                    f"pk={held}.pk).update(**{param.upper()}_{side})"
                )
    return line


class FilterArm(Arms):
    """`scaffold filter`."""

    def filter(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`filter <app> <Noun> <field>=<lookup>`: a list narrowing on both doors, with its test."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 3:
            raise _refuse(
                "filter takes <app> <Noun> <field>=<lookup> — e.g. `filter orders Order code=exact`"
            )
        label, noun, spec = words
        matched = FILTER_SPEC.match(spec)
        if matched is None or matched.group("lookup") not in LOOKUPS:
            raise _refuse(
                f"{spec!r} is no `<field>=<lookup>` over the closed lookups ({' '.join(LOOKUPS)})"
                " — `in` is refused: its list reads differently on the two doors' wires."
            )
        field, lookup = matched.group("name"), matched.group("lookup")
        self.refuse_names(root, label, noun, check=bool(options["check"]))
        app_dir = root / "apps" / label
        models, services = app_dir / "models.py", app_dir / "services.py"
        declared = declared_field(
            models.read_text() if models.is_file() else "",
            services.read_text() if services.is_file() else "",
            noun,
            field,
        )
        if declared is None:
            raise _refuse(
                f"{noun} has no {field} — scaffold field first: "
                f"`scaffold field {label} {noun} {field}:<type>?`, then the filter. "
                "Nothing was written."
            )
        kind = MODEL_TYPES.get(declared.model, "")
        if not kind:
            raise _refuse(
                f"`{noun}` declares no `{field}` of a type the scaffold reads "
                f"({' '.join(MODEL_TYPES)}) in apps/{label}/models.py — add the field first "
                f"(`scaffold field {label} {noun} {field}:<type>?`)."
            )
        if kind not in LOOKUPS[lookup]:
            raise _refuse(
                f"`{lookup}` does not read a {kind} field — take one of: "
                + " ".join(k for k, kinds in LOOKUPS.items() if kind in kinds)
                + "."
            )
        param = field if lookup in ("exact", "icontains") else f"{field}_{lookup}"
        held = filtered(root / "apps" / label / "schemas.py", f"{noun}Filter", param)
        if held and not options["check"]:
            raise _refuse(
                f"`{noun}Filter` already filters `{param}` (apps/{label}/schemas.py:{held}) — "
                f"one narrowing per name; change its lookup there by hand, or ask "
                f"`{field}=<another lookup>`."
            )
        sort = FIELD_TYPES[kind]

        if held and label != golden.app:
            holds = held_lookup(root / "apps" / label / "schemas.py", held)
            if holds not in LOOKUPS:
                raise _refuse(
                    f"`{noun}Filter` filters `{param}` by `{holds}` (apps/{label}/schemas.py:"
                    f"{held}), a lookup the scaffold does not declare — it declares "
                    f"{' '.join(LOOKUPS)}."
                )
            said = f"`{noun}Filter` already filters `{param}` by `{holds}` (schemas.py:{held})"
            said += "" if holds == lookup else f", not `{lookup}`"

            def held_lines(line: str) -> str:
                return filter_lines(line, field, holds, kind, declared.choices, declared.created)

            self.filter_state(root, golden, label, noun, held_lines, sort.imports, said)
            return
        self.additive(
            root,
            golden,
            label,
            noun,
            lambda line: filter_lines(
                line, field, lookup, kind, declared.choices, declared.created
            ),
            options,
            imports=sort.imports,
        )

    def filter_state(
        self,
        root: Path,
        golden: Golden,
        label: str,
        noun: str,
        lines: Callable[[str], str],
        imports: str,
        said: str,
    ) -> None:
        """A `--check` of a filter the noun holds: its state, exit 0 when every line is there."""
        for rel, pieces in self.fragments(root, golden, label, noun, lines, imports).items():
            target = root / "apps" / label / rel
            text = target.read_text() if target.is_file() else ""
            there = {line.strip() for line in text.split("\n")}
            for piece in pieces:
                gone = next((ln for ln in piece.lines if ln.strip() not in there), None)
                if gone is not None:
                    raise CommandError(
                        f"apps/{label}: {said}, but apps/{label}/{rel} lacks `{gone.strip()}` — "
                        "the filter's line there was edited by hand.",
                        returncode=1,
                    )
        self.stdout.write(f"apps/{label}: {said} — every fragment in place.")
