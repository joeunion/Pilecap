"""The `policy` arm: a tenant policy inherited downward, its resolution and its doors."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from apps.core.scaffold.arms._common import NOUN, NOUN_WORD, Arms, _refuse
from apps.core.scaffold.copier import Golden, snake
from apps.core.scaffold.shapes import Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("policy",)

#: What the policy shape's second word ends in: the noun it governs, then this.
POLICY_SUFFIX = "Policy"


class PolicyArm(Arms):
    """`scaffold policy`."""

    def policy(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`policy <app> <Noun>Policy`: the config row, its resolution, the noun's FK, its doors."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 2:
            raise _refuse("policy takes <app> <Noun>Policy — e.g. `policy orders OrderPolicy`.")
        label, named = words
        noun = named.removesuffix(POLICY_SUFFIX)
        if not named.endswith(POLICY_SUFFIX) or not NOUN_WORD.match(noun):
            raise _refuse(
                f"{named!r} is no `<Noun>{POLICY_SUFFIX}` — the second word is the noun with "
                f"`{POLICY_SUFFIX}` appended, e.g. `policy orders OrderPolicy`."
            )
        if not options["check"]:
            app_dir = root / "apps" / label
            models = app_dir / "models.py"
            if not models.is_file() or not re.search(rf"^class {noun}\(", models.read_text(), re.M):
                raise _refuse(
                    f"apps/{label}/models.py declares no `{noun}` — a policy governs a noun "
                    f"`scaffold noun {label} {noun}` wrote; scaffold the noun first."
                )
            if re.search(rf"^class {named}\(", models.read_text(), re.M):
                raise _refuse(f"apps/{label}/models.py already declares `{named}`.")
            whole = sorted(
                rel
                for rel in golden.files
                if rel not in goldens[NOUN].files and (app_dir / rel).is_file()
            )
            if whole:
                raise _refuse(
                    f"apps/{label} already has {' '.join(whole)} — the policy writes "
                    "those modules whole; fold its pieces into the existing ones by hand."
                )
        self.additive(
            root,
            golden,
            label,
            noun,
            lambda line: line,
            options,
            taken="policy",
            migration=f"{snake(noun)}_policy",
        )
