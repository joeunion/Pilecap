"""The `noun` arm: the base noun and its doors, into a new or a fresh `newapp` app."""

from __future__ import annotations

from pathlib import Path

from apps.core.scaffold.arms._common import FIRST_MIGRATION, NOUN, _refuse, newapp_stubs
from apps.core.scaffold.arms.remove import RemoveArm
from apps.core.scaffold.baseline import NOUN_SWEEP, noun_baseline
from apps.core.scaffold.copier import FenceError, Golden, NoFormatter, from_golden
from apps.core.scaffold.shapes import SHAPES

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("noun",)


class NounArm(RemoveArm):
    """`scaffold noun`."""

    def noun(self, root: Path, goldens: dict[str, Golden], words: list[str], check: bool) -> None:
        """`noun <app> <Noun>`: the base noun and its doors, into a new or a fresh `newapp` app."""
        registered = next(s for s in SHAPES if s.key == NOUN)
        golden = goldens.get(registered.golden)
        if golden is None:
            self.pending(registered, goldens)
            return
        if len(words) != 2:
            raise _refuse("noun takes <app> <Noun> — e.g. `scaffold noun orders Order`.")
        label, noun = words
        self.refuse_names(root, label, noun, check=check)
        try:
            copy = from_golden(root, golden, label, noun)
        except (FenceError, NoFormatter) as error:
            raise _refuse(f"the golden could not be read: {error}") from error
        if self.removing:
            self.remove(root, label, noun, copy, first=True)
            return
        self.refuse_collisions(root, label, noun, copy)
        self.refuse_overlong(root, label, noun, copy)
        if check:
            self.compare(root, golden, label, copy)
            return
        self.refuse_plants(root, label, copy.files)
        if self.dry_run:
            self.plan(root, golden, label, copy, fresh=newapp_stubs(label), noun=True)
            self.stdout.write(f"would migrate apps/{label}/migrations/{FIRST_MIGRATION}")
            self.stdout.write(
                f"would write {noun_baseline(label, noun)}: the first run of {NOUN_SWEEP}"
            )
            return
        self.written(root, label, copy, f"noun {label} {noun}", first=noun)
