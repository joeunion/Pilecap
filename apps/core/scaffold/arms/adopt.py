"""The `adopt` and `import` arms: one family verb's standalone noun, into a fresh app."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.core.scaffold.arms._common import _refuse, newapp_stubs
from apps.core.scaffold.arms.remove import RemoveArm
from apps.core.scaffold.copier import GOLDENS, FenceError, Golden, NoFormatter, from_golden
from apps.core.scaffold.shapes import ADOPT, Shape, adopt_verbs

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("adopt", "import")


class AdoptArm(RemoveArm):
    """`scaffold adopt` and `scaffold import`."""

    def adopt(
        self,
        root: Path,
        goldens: dict[str, Golden],
        registered: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`adopt <verb> <app> <Noun>` · `import <app> <Noun>`: a verb's noun, whole."""
        if registered.key == "import":
            if len(words) != 2:
                raise _refuse("import takes <app> <Noun> — e.g. `scaffold import orders Order`.")
            words = ["import", *words]
        elif registered.key != ADOPT:
            self.pending(registered, goldens)
        if len(words) != 3:
            raise _refuse(
                "adopt takes <verb> <app> <Noun> — e.g. `scaffold adopt archive orders Order`."
            )
        verb, label, noun = words
        verbs = adopt_verbs(root)
        if verb not in verbs:
            raise _refuse(f"{verb!r} is no verb adopt knows ({' '.join(verbs)}).")
        golden = goldens.get(f"{ADOPT}.{verb}")
        if golden is None:
            raise _refuse(
                f"`adopt {verb}` has no golden extract under {GOLDENS} — run the fold's "
                "`goldens` step on the template, or take a release that carries it."
            )
        self.refuse_names(root, label, noun, check=bool(options["check"]))
        try:
            copy = from_golden(root, golden, label, noun)
        except (FenceError, NoFormatter) as error:
            raise _refuse(f"the golden could not be read: {error}") from error
        if self.removing:
            self.remove(root, label, noun, copy)
            return
        self.refuse_collisions(root, label, noun, copy)
        self.refuse_overlong(root, label, noun, copy)
        if options["check"]:
            self.compare(root, golden, label, copy)
            return
        self.refuse_held(root, label, noun, f"adopt {verb}")
        self.refuse_plants(root, label, copy.files)
        if self.dry_run:
            self.plan(root, golden, label, copy, fresh=newapp_stubs(label), noun=True)
            self.retire_stub(root, label, copy)
            return
        self.written(root, label, copy, f"adopt {verb} {label} {noun}")
        self.stdout.write(
            f"road: a new app's noun is `scaffold noun {label} {noun}` — archive, version and "
            f"history drawn in; `adopt {verb}` copies that one verb's standalone noun, with the "
            "family verbs' door-parity module `tests/test_golden_verbs_parity.py` (house rule 46)."
        )
