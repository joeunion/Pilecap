"""The `search` arm: a noun's search kind, its generated column and its tests."""

from __future__ import annotations

import ast
import keyword
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from apps.core.scaffold.arms._common import DROP, GOLDEN_APP, VERB_WORD, Arms, _refuse
from apps.core.scaffold.copier import Golden, snake
from apps.core.scaffold.shapes import Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("search",)

#: The search golden's own field list, in its ranking order.
GOLDEN_SEARCH_FIELDS = ("name", "notes")
#: Postgres's four `setweight` labels: the ranking a field list is given, first to last.
SEARCH_WEIGHTS = "ABCD"
#: The model fields a searched column may be.
TEXT_COLUMNS = frozenset({"CharField", "TextField"})


def _weighted(fields: Sequence[str]) -> str:
    """A field list as `Searchable.fields` spells it, weighted in order."""
    return ", ".join(f'("{f}", "{w}")' for f, w in zip(fields, SEARCH_WEIGHTS, strict=False))


def search_lines(
    line: str, fields: Sequence[str], label: str, moved: bool = True, source: str = GOLDEN_APP
) -> str:
    """A golden search line as the field list `fields` says it, on `label`'s noun."""
    stripped = line.strip()
    vector = 'SearchVector("{}", weight="{}", config=SEARCH_CONFIG)'
    first = vector.format(GOLDEN_SEARCH_FIELDS[0], SEARCH_WEIGHTS[0])
    if stripped == first:
        indent = line[: len(line) - len(line.lstrip())]
        terms = [vector.format(f, w) for f, w in zip(fields, SEARCH_WEIGHTS, strict=False)]
        return "\n".join(indent + ("+ " if i else "") + term for i, term in enumerate(terms))
    if any(
        stripped.startswith("+ " + vector.format(f, w))
        for f, w in zip(GOLDEN_SEARCH_FIELDS[1:], SEARCH_WEIGHTS[1:], strict=False)
    ):
        return DROP
    if not moved and stripped == "events.WIDGET_MOVED,":
        return DROP
    if tuple(fields) != GOLDEN_SEARCH_FIELDS:
        line = searched_rows(line, fields)
        if line == DROP:
            return DROP
    golden = list(GOLDEN_SEARCH_FIELDS)
    for old, new in (
        (f"[{_weighted(golden)}]", f"[{_weighted(fields)}]"),
        (
            f"DECLARATION.fields] == {golden!r}".replace("'", '"'),
            f"DECLARATION.fields] == {list(fields)!r}".replace("'", '"'),
        ),
        (
            f"DECLARATION.fields] == {list(SEARCH_WEIGHTS[:2])!r}".replace("'", '"'),
            f"DECLARATION.fields] == {list(SEARCH_WEIGHTS[: len(fields)])!r}".replace("'", '"'),
        ),
        (f'"app": "{source}"', f'"app": "{label}"'),
        (f"{source}_widget", f"{label}_widget"),
    ):
        line = line.replace(old, new)
    return line


#: A golden row's searched words: `name="…"`, and `notes="…"` when the row says it.
ROW_WORDS = re.compile(r'\bname="(?P<name>[^"]*)"(?:, notes="(?P<notes>[^"]*)")?')
#: The lines a golden test writes its rows on: a create, an update, or a create's wrapped tail.
ROW_LINE = re.compile(r"(?:create_widget\(|update_widget\(|^tenant=\w+, actor=\w+, name=)")
#: The weighted test's two rows found in ranking order, and its rank comparison.
RANKED = (
    "assert [hit.id for hit in page.items] == [in_the_name.pk, in_the_notes.pk]",
    "assert page.items[0].rank > page.items[1].rank",
)


def searched_rows(line: str, fields: Sequence[str]) -> str:
    """A golden test line with its `name`/`notes` words moved onto `fields`, place for place."""
    stripped = line.strip()
    named = dict(zip(GOLDEN_SEARCH_FIELDS, fields, strict=False))
    for golden in GOLDEN_SEARCH_FIELDS:
        for said in (f'document["{golden}"]', f'upserted[-1]["{golden}"]'):
            if said in stripped:
                if golden not in named:
                    return DROP
                return line.replace(said, said.replace(f'"{golden}"', f'"{named[golden]}"'))
    if len(fields) == 1 and stripped == RANKED[0]:
        return line.replace("[in_the_name.pk, in_the_notes.pk]", "[in_the_name.pk]")
    if len(fields) == 1 and stripped == RANKED[1]:
        return DROP
    if not ROW_LINE.search(stripped):
        return line

    def moved(found: re.Match[str]) -> str:
        words = {k: v for k, v in found.groupdict().items() if v is not None}
        row = {"name": words["name"]}
        row.update({named[g]: words[g] for g in GOLDEN_SEARCH_FIELDS if g in named and g in words})
        if "notes" in words and "notes" not in row and "notes" not in named.values():
            row["notes"] = words["notes"]
        return ", ".join(f'{k}="{v}"' for k, v in row.items())

    return ROW_WORDS.sub(moved, line)


def text_columns(models: str, noun: str) -> frozenset[str]:
    """The `CharField`/`TextField` columns class `noun` declares in a models module's text."""
    for node in ast.parse(models).body:
        if isinstance(node, ast.ClassDef) and node.name == noun:
            return frozenset(
                target.id
                for stmt in node.body
                if isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Call)
                and isinstance(stmt.value.func, ast.Attribute)
                and stmt.value.func.attr in TEXT_COLUMNS
                for target in stmt.targets
                if isinstance(target, ast.Name)
            )
    return frozenset()


def model_fields(models: str, noun: str) -> frozenset[str]:
    """Every `<name> = models.<Field>(…)` class `noun` declares in a models module's text."""
    for node in ast.parse(models).body:
        if isinstance(node, ast.ClassDef) and node.name == noun:
            return frozenset(
                target.id
                for stmt in node.body
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call)
                for target in stmt.targets
                if isinstance(target, ast.Name)
            )
    return frozenset()


class SearchArm(Arms):
    """`scaffold search`."""

    def search(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`search <app> <Noun> <fields>`: the noun's kind, its generated column, its tests."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 3:
            raise _refuse(
                "search takes <app> <Noun> <fields> — e.g. `search orders Order name,notes`."
            )
        label, noun, listed = words
        fields = listed.split(",")
        if any(not VERB_WORD.match(f) or keyword.iskeyword(f) for f in fields):
            raise _refuse(
                f"{listed!r} is no field list — the noun's text columns in ranking order, "
                "comma-separated, e.g. `name,notes`."
            )
        twice = sorted({f for f in fields if fields.count(f) > 1})
        if twice:
            raise _refuse(f"{' '.join(twice)}: named twice — a column is indexed under one weight.")
        if len(fields) > len(SEARCH_WEIGHTS):
            raise _refuse(
                f"{len(fields)} fields — Postgres has four `setweight` labels "
                f"({', '.join(SEARCH_WEIGHTS)}), so a kind ranks at most four."
            )
        app_dir = root / "apps" / label
        if not options["check"]:
            models = app_dir / "models.py"
            text = models.read_text() if models.is_file() else ""
            if not re.search(rf"^class {noun}\(", text, re.M):
                raise _refuse(
                    f"apps/{label}/models.py declares no `{noun}` — a search adopts a noun "
                    f"`scaffold noun {label} {noun}` wrote; scaffold the noun first."
                )
            columns = text_columns(text, noun)
            absent = [f for f in fields if f not in model_fields(text, noun)]
            if absent:
                raise _refuse(
                    f"{noun} has no {' '.join(absent)} — scaffold field first: "
                    + "; ".join(f"`scaffold field {label} {noun} {f}:str?`" for f in absent)
                    + ", then the search. Nothing was written."
                )
            missing = [f for f in fields if f not in columns]
            if missing:
                raise _refuse(
                    f"`{noun}` declares no text column {' '.join(missing)} — a searched field is "
                    f"a `CharField` or `TextField` on the noun ({' '.join(sorted(columns))})."
                )
            if re.search(r"^    search_vector = ", text, re.M):
                raise _refuse(
                    f"`{noun}` already declares `search_vector` — one kind per noun; its "
                    f"fields are the list in apps/{label}/search.py."
                )
            if (app_dir / "search.py").is_file():
                raise _refuse(
                    f"apps/{label} already has a `search.py` — a second kind goes into its "
                    "`SEARCHABLES` by hand."
                )
        events = app_dir / "events.py"
        moved = events.is_file() and f"{snake(noun).upper()}_MOVED = " in events.read_text()
        self.additive(
            root,
            golden,
            label,
            noun,
            lambda line: search_lines(line, fields, label, moved, golden.app),
            options,
            taken="search_vector",
            migration=f"{snake(noun)}_search",
        )
