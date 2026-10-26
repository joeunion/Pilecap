"""The `stat` arm: one measured number on both doors, with its recomputing tests."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from apps.core.scaffold.arms._common import (
    FIELD_TYPES,
    MODEL_TYPES,
    VERB_WORD,
    Arms,
    _refuse,
)
from apps.core.scaffold.copier import Golden, snake
from apps.core.scaffold.shapes import Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("stat",)

#: The stat golden's own measure: the label its `MeasuredOut` answers under.
GOLDEN_MEASURE = "count"

#: `<key>[=sum:<field>|avg:<field>|count]`, as the shape's own argument says it.
MEASURE_SPEC = re.compile(r"^(?P<key>[^=]+)(?:=(?P<how>[a-z]+)(?::(?P<field>.*))?)?$")
#: The field types a sum or an average is honest over: a number, never a text or a moment.
MEASURABLE = ("int", "decimal")
#: The golden counts this many rows in its no-growth test; a measure sums as many samples.
COUNTED = 10


@dataclass(frozen=True)
class Measure:
    """What one `stat` measures: its key, `count` or `sum`/`avg` over a field, that field's type."""

    key: str
    how: str = GOLDEN_MEASURE
    field: str = ""
    kind: str = ""

    @property
    def formula(self) -> str:
        """The `basis.formula` the measure travels with (ADR core-7)."""
        summed = f"sum({self.field})"
        return f"{summed} / rows" if self.how == "avg" else summed

    def value(self, summed: Decimal, rows: int) -> Decimal:
        """The value the served formula answers over `summed` and `rows`, as the server does."""
        if self.how == "sum":
            return summed
        return summed / Decimal(rows) if rows else Decimal(0)


def _samples(kind: str) -> tuple[tuple[str, str], tuple[Decimal, Decimal]]:
    """The field type's two Python spellings and the numbers they are."""
    found = FIELD_TYPES[kind]
    return found.python, (Decimal(found.wire[0].strip('"')), Decimal(found.wire[1].strip('"')))


def _measure_lines(measure: Measure) -> dict[str, str]:
    """Each golden line a `sum`/`avg` measure says differently, as that measure says it."""
    key, field, formula = measure.key, measure.field, measure.formula
    (first, second), (one, two) = _samples(measure.kind)
    counted, pair = Decimal(COUNTED) * one, one + two
    inputs = f'{{"sum({field})": summed, "rows": rows}}'

    def expected(summed: Decimal, rows: int) -> str:
        return f'{{"sum({field})": Decimal("{summed}"), "rows": Decimal({rows})}}'

    def basis(of: str) -> str:
        return f'{{name: Decimal(said) for name, said in {of}["basis"]["inputs"].items()}}'

    recompute = f'Decimal(str(basis["inputs"]["sum({field})"]))'
    if measure.how == "avg":
        recompute = (
            f'rows = Decimal(str(basis["inputs"]["rows"]))\n    recomputed = {recompute} / rows '
            "if rows else Decimal(0)"
        )
    else:
        recompute = f"recomputed = {recompute}"
    return {
        # api.py
        "from decimal import Decimal": (
            "from decimal import Decimal\n\nfrom django.db.models import Count, Sum"
        ),
        (
            '"""The measured widget count for one hat, `live + archived` with both terms '
            '(ADR core-7)."""'
        ): (
            f'"""The {measure.how} of `{field}` over one hat\'s widgets, with its terms '
            '(ADR core-7)."""'
        ),
        "live = visible.filter(archived_at__isnull=True).count()": (
            f'measured = visible.aggregate(summed=Sum("{field}"), rows=Count("pk"))'
        ),
        "archived = visible.filter(archived_at__isnull=False).count()": (
            'summed, rows = Decimal(measured["summed"] or 0), Decimal(measured["rows"])'
        ),
        "value=Decimal(live + archived),": (
            "value=summed,"
            if measure.how == "sum"
            else "value=summed / rows if rows else Decimal(0),"
        ),
        'formula="live + archived",': f'formula="{formula}",',
        'inputs={"live": Decimal(live), "archived": Decimal(archived)},': f"inputs={inputs},",
        "How many widgets you can see, with the arithmetic attached.": (
            f"The {measure.how} of `{field}` over the widgets you can see, with the arithmetic "
            "attached."
        ),
        "The count comes back as a **measured** number rather than a bare integer.": (
            f"The {key} comes back as a **measured** number rather than a bare one."
        ),
        '`"live + archived"`) and `basis.inputs` (an object with `live` and': (
            f'`"{formula}"`) and `basis.inputs` (an object with `sum({field})` and'
        ),
        "`archived` in it), so you can check the sum without asking a second question.": (
            "`rows` in it), so you can check the arithmetic without asking a second question."
        ),
        # schemas.py
        '"""The widget count for the acting hat, **with the arithmetic attached**.': (
            f'"""The widgets\' {measure.how} of `{field}` for the acting hat, **with the '
            "arithmetic attached**."
        ),
        "`live + archived`, and both terms are on the wire — a client can check": (
            f"`{formula}`, and its terms are on the wire — a client can check"
        ),
        # tests/test_api.py
        (
            "# `/stats/`: the fixed request cost plus the two COUNTs its basis is built from "
            "(ADR core-7)."
        ): (
            "# `/stats/`: the fixed request cost plus the one aggregate its basis is built from "
            "(ADR core-7)."
        ),
        "STATS_QUERY_BUDGET = REQUEST_FIXED_QUERIES + 2": (
            "STATS_QUERY_BUDGET = REQUEST_FIXED_QUERIES + 1"
        ),
        '"""The measured number costs two COUNTs and no more, at any number of rows."""': (
            '"""The measured number costs one aggregate and no more, at any number of rows."""'
        ),
        'create_widget(tenant=tenant, actor=owner_actor, name=f"Counted {index}")': (
            f'create_widget(tenant=tenant, actor=owner_actor, name=f"Counted {{index}}", '
            f"{field}={first})"
        ),
        'assert body["count"]["value"] == "10"': (
            f'assert Decimal(body["count"]["value"]) == '
            f'Decimal("{measure.value(counted, COUNTED)}")'
        ),
        'assert body["count"]["basis"]["inputs"] == {"live": "10", "archived": "0"}': (
            f"assert {basis('body["count"]')} == {expected(counted, COUNTED)}"
        ),
        '"""The inputs are read off the table, not remembered. Archive one and watch.': (
            '"""The inputs are read off the table, not remembered: two values, archived or not.'
        ),
        'answered `{"live": n, "archived": "0"}`, which is a formula that happens': (
            "answered ten times one sample, which is a formula that happens"
        ),
        'first = create_widget(tenant=tenant, actor=owner_actor, name="First")': (
            'first = create_widget(tenant=tenant, actor=owner_actor, name="First", '
            f"{field}={first})"
        ),
        'create_widget(tenant=tenant, actor=owner_actor, name="Second")': (
            f'create_widget(tenant=tenant, actor=owner_actor, name="Second", {field}={second})'
        ),
        'assert body["count"]["basis"]["inputs"] == {"live": "1", "archived": "1"}': (
            f"assert {basis('body["count"]')} == {expected(pair, 2)}"
        ),
        'assert body["count"]["value"] == "2"': (
            f'assert Decimal(body["count"]["value"]) == Decimal("{measure.value(pair, 2)}")'
        ),
        # tests/test_doors_over_the_wire.py
        (
            'assert rest_body["count"]["value"] == "1", "a Decimal on the wire is a string, '
            'not a float"'
        ): (
            'assert rest_body["count"]["value"] == "0", "a Decimal on the wire is a string, not a '
            'float"'
        ),
        'assert basis["formula"] == "live + archived"': f'assert basis["formula"] == "{formula}"',
        'recomputed = sum(Decimal(str(value)) for value in basis["inputs"].values())': recompute,
        "assert recomputed == Decimal(1)": (
            f'assert Decimal(str(basis["inputs"]["rows"])) == Decimal(1)\n    '
            f'assert Decimal(str(basis["inputs"]["sum({field})"])) == Decimal(0), '
            '"an unset field sums to 0, never null"'
        ),
    }


def stat_lines(line: str, measure: str | Measure) -> str:
    """A golden `count` line as `measure` says it: its key, and for a sum or average its field."""
    said = measure if isinstance(measure, Measure) else Measure(measure)
    if said.how != GOLDEN_MEASURE:
        indent = line[: len(line) - len(line.lstrip())]
        if (swapped := _measure_lines(said).get(line.strip())) is not None:
            line = indent + swapped
    for old, new in (
        (f'"{GOLDEN_MEASURE}"', f'"{said.key}"'),
        (f"{GOLDEN_MEASURE}=MeasuredOut(", f"{said.key}=MeasuredOut("),
        (f"{GOLDEN_MEASURE}: MeasuredOut", f"{said.key}: MeasuredOut"),
        (f"`{GOLDEN_MEASURE}`", f"`{said.key}`"),
    ):
        line = line.replace(old, new)
    return line


def _class_body(models: str, noun: str) -> str:
    """`noun`'s class body in `models`, up to the next top-level class; empty when absent."""
    start = re.search(rf"^class {noun}\(", models, re.M)
    if start is None:
        return ""
    end = re.search(r"^class ", models[start.end() :], re.M)
    return models[start.start() : start.end() + end.start()] if end else models[start.start() :]


def parse_measure(spec: str, noun: str, models: str) -> Measure:
    """`<key>[=sum:<field>|avg:<field>|count]` read against `noun`'s fields, or the refusal."""
    matched = MEASURE_SPEC.match(spec)
    key = matched.group("key") if matched else spec
    if matched is None or not VERB_WORD.match(key) or keyword.iskeyword(key):
        raise _refuse(f"{spec!r} is no measure — lower snake case, e.g. `total`.")
    how, field = matched.group("how") or GOLDEN_MEASURE, matched.group("field")
    if how not in (GOLDEN_MEASURE, "sum", "avg"):
        raise _refuse(f"{spec!r} is no measure — `<key>=sum:<field>`, `avg:<field>` or `count`.")
    if how == GOLDEN_MEASURE:
        if field is not None:
            raise _refuse(f"{spec!r}: a count names no field — `{key}` or `{key}=count`.")
        return Measure(key)
    if not field:
        raise _refuse(f"{spec!r} names no field — `{key}={how}:<field>`.")
    body = _class_body(models, noun)
    typed = re.search(rf"^    {re.escape(field)} = models\.(\w+)\(", body, re.M)
    if typed is None:
        raise _refuse(f"`{noun}` has no `{field}` field — `scaffold field` adds one first.")
    kind = MODEL_TYPES.get(typed.group(1), typed.group(1))
    if kind not in MEASURABLE:
        raise _refuse(
            f"`{field}` is a {kind} field — sum and avg measure an int or decimal field; "
            f"a count is `{key}`."
        )
    return Measure(key, how, field, kind)


class StatArm(Arms):
    """`scaffold stat`."""

    def stat(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`stat <app> <Noun> <key>[=sum:<field>|avg:<field>|count]`: one measured number."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 3:
            raise _refuse(
                "stat takes <app> <Noun> <key>[=sum:<field>|avg:<field>|count] — e.g. "
                "`stat orders Order total`."
            )
        label, noun, spec = words
        models = root / "apps" / label / "models.py"
        held = models.read_text() if models.is_file() else ""
        measure = parse_measure(spec, noun, held)
        if not options["check"]:
            if re.search(rf"^    {measure.key} = ", held, re.M):
                raise _refuse(
                    f"`{noun}` already has a `{measure.key}` — a measure names a new key; to "
                    f"measure the field, `total=sum:{measure.key}`."
                )
            api = root / "apps" / label / "api.py"
            if api.is_file() and f"def {snake(noun)}_stats(" in api.read_text():
                raise _refuse(
                    f"apps/{label}/api.py already has `{snake(noun)}_stats` — one measured stat "
                    f"per noun; a second measure is a second `MeasuredOut` on `{noun}StatsOut`."
                )
        self.additive(
            root,
            golden,
            label,
            noun,
            lambda line: stat_lines(line, measure),
            options,
            imports="" if measure.how == GOLDEN_MEASURE else "from decimal import Decimal",
        )
