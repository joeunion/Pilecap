"""The `enum` arm: a status enum, its one-step chain and its press."""

from __future__ import annotations

import keyword
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from apps.core.scaffold.arms._common import DROP, Arms, _refuse
from apps.core.scaffold.copier import Golden, snake
from apps.core.scaffold.shapes import Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("enum",)

#: The enum golden's own field and its three values, first to last.
GOLDEN_ENUM = ("DRAFT", "ACTIVE", "RETIRED")
ENUM_VALUE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def enum_lines(line: str, field: str, values: Sequence[str]) -> str:
    """A golden `status` line as the enum `field` with `values` says it, chain first to last."""
    first, second, last = GOLDEN_ENUM
    indent = line[: len(line) - len(line.lstrip())]
    said = line.strip()
    if said == f'{first} = "{first.lower()}", "{first.capitalize()}"':
        return "\n".join(
            f'{indent}{v} = "{v.lower()}", "{v.replace("_", " ").capitalize()}"' for v in values
        )
    if said in (f'{v} = "{v.lower()}", "{v.capitalize()}"' for v in (second, last)):
        return DROP
    if said == f"Status.{second}: Status.{last},":
        return DROP
    if said == f"Status.{first}: Status.{second},":
        line = "\n".join(
            f"{indent}Status.{a}: Status.{b}," for a, b in zip(values, values[1:], strict=False)
        )
    else:
        for old, new in ((first, values[0]), (second, values[1]), (last, values[-1])):
            line = line.replace(old, new).replace(f'"{old.lower()}"', f'"{new.lower()}"')
    camel = "".join(part.capitalize() for part in field.split("_"))
    line = re.sub(r"\bstatus\b", field, line)
    line = re.sub(r"\bStatus\b", camel, line)
    return line.replace("STATUS_", f"{field.upper()}_")


class EnumArm(Arms):
    """`scaffold enum`."""

    def enum(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`enum <app> <Noun> <field> <A,B,C>`: the choices, their one-step chain and its press."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 4:
            raise _refuse(
                "enum takes <app> <Noun> <field> <A,B,C> — e.g. "
                "`enum orders Order stage OPEN,SHIPPED,CLOSED`."
            )
        label, noun, field, spelled = words
        if not re.match(r"^[a-z][a-z0-9_]*$", field) or keyword.iskeyword(field):
            raise _refuse(f"{field!r} is no field name — lower case words joined by `_`.")
        said = spelled.split(",")
        values = [v.upper() for v in said]
        if len(values) < len(GOLDEN_ENUM) or len(set(values)) != len(values):
            raise _refuse(
                f"{spelled!r} names fewer than {len(GOLDEN_ENUM)} distinct values — a chain of "
                "two is a yes-or-no, which is a boolean field (`is_<x>`), never an enum."
            )
        bad = [v for v in said if not ENUM_VALUE.match(v.upper()) or len(v) > 20]
        if bad:
            raise _refuse(
                f"{' '.join(bad)}: a value is a letter, then letters, digits or `_`, at most 20 "
                "characters."
            )
        if values != said:
            self.stdout.write(f"values: {', '.join(values)} (upper-cased from your input)")
        services = root / "apps" / label / "services.py"
        if not options["check"] and services.is_file():
            if f"def transition_{snake(noun)}(" in services.read_text():
                raise _refuse(
                    f"apps/{label}/services.py already has `transition_{snake(noun)}` — "
                    "one transitioned enum per noun."
                )
        self.additive(
            root,
            golden,
            label,
            noun,
            lambda line: enum_lines(line, field, values),
            options,
            taken=field,
            migration=f"{snake(noun)}_{field}",
        )
