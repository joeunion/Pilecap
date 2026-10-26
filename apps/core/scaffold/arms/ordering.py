"""The `ordering` arm: a column `?ordering=` may name, on both doors."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from apps.core.scaffold.arms._common import GOLDEN_FIELD, Arms, _refuse
from apps.core.scaffold.copier import Golden
from apps.core.scaffold.shapes import Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("ordering",)


class OrderingArm(Arms):
    """`scaffold ordering`."""

    def ordering(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`ordering <app> <Noun> <field>`: a column `?ordering=` may name, on both doors."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 3:
            raise _refuse(
                "ordering takes <app> <Noun> <field> — e.g. `ordering orders Order code`."
            )
        label, noun, field = words
        self.refuse_names(root, label, noun, check=bool(options["check"]))
        models = root / "apps" / label / "models.py"
        text = models.read_text() if models.is_file() else ""
        if not re.search(rf"^    {re.escape(field)} = models\.\w+\(", text, re.M):
            raise _refuse(
                f"`{noun}` declares no `{field}` in apps/{label}/models.py — an ordering names a "
                "column of the noun's own, never a relation."
            )
        api = root / "apps" / label / "api.py"
        if not options["check"] and f'ORDERING += ("{field}",)' in api.read_text():
            raise _refuse(f"apps/{label}/api.py already orders by `{field}`.")
        self.additive(
            root, golden, label, noun, lambda line: line.replace(GOLDEN_FIELD, field), options
        )
