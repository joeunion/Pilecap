"""The `--remove` path: a noun or an adopted copy reverted, every shared line taken back."""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any

from apps.core.scaffold import anchors, floors
from apps.core.scaffold.arms._common import (
    BUDGETS,
    BY_HAND,
    DOOR_PARITY,
    DRAWER,
    FAMILIES,
    FAMILY_DRAWER,
    FIRST_MIGRATION,
    PARITY_STUB,
    Arms,
    _refuse,
    _tag_keys,
    namespace,
    newapp_stubs,
    only_lacking,
    with_reset,
)
from apps.core.scaffold.baseline import noun_baseline
from apps.core.scaffold.copier import Copy, Golden, tidied

#: The shapes this module's arm writes: none — `--remove` reverts a copy another arm made.
KEYS: tuple[str, ...] = ()

MIGRATION = re.compile(r"^(\d{4})_\w+\.py$")


def _canon(lines: list[str]) -> str:
    """Lines as the formatter cannot change them: no whitespace, no comma before a closer."""
    return re.sub(r",(?=[)\]}])", "", re.sub(r"\s+", "", "".join(lines)))


def _span(lines: list[str], used: set[int], piece: list[str]) -> range | None:
    """The first unused run of `lines` that reads as `piece` once both are canonical, or None."""
    want = _canon(piece)
    if not want:
        return None
    for start, first in enumerate(lines):
        if start in used or not _canon([first]) or not want.startswith(_canon([first])):
            continue
        for end in range(start + 1, len(lines) + 1):
            if end - 1 in used:
                break
            said = _canon(lines[start:end])
            if said == want:
                return range(start, end)
            if not want.startswith(said.rstrip(",")):
                break
    return None


def unwritten(
    text: str, pieces: list[anchors.Piece], tidy: Callable[[str], str], reset: str
) -> str | None:
    """`text` before the arm put `pieces` (and `reset`) in, proved by re-inserting; None if not."""
    lines = text.splitlines()
    used: set[int] = set()
    for piece in pieces:
        if piece.anchor.side == "imports" and not piece.anchor.scope:
            continue
        span = _span(lines, used, piece.lines)
        if span is None:
            return None
        used.update(span)
    if reset:
        used.update(i for i, line in enumerate(lines) if line.strip() == f'"{reset}",')
    before = tidy("".join(line + "\n" for i, line in enumerate(lines) if i not in used))
    try:
        again = tidy(anchors.insert(before, only_lacking(pieces, before))[0])
    except anchors.AnchorMissing:
        return None
    if reset and (put := with_reset(again, reset)) is not None:
        again = put[0]
    return before if again == text else None


class RemoveArm(Arms):
    """`scaffold noun|adopt|field … --remove`."""

    def execute(self, *args: Any, **options: Any) -> Any:
        """A `--remove` run skips the system checks: it reverts by anchor, never by import."""
        if options.get("remove"):
            options["skip_checks"] = True
        return super().execute(*args, **options)

    def remove_fragments(
        self,
        root: Path,
        golden: Golden,
        label: str,
        noun: str,
        lines: Callable[[str], str],
        imports: str,
        name: str,
        migration: str,
    ) -> None:
        """An additive shape's anchored lines and its migration taken back, every module proved."""
        app_dir = root / "apps" / label
        found = self.fragments(root, golden, label, noun, lines, imports)
        reverted: dict[str, str] = {}
        for rel, pieces in sorted(found.items()):
            target = app_dir / rel
            text = target.read_text() if target.is_file() else ""
            before = unwritten(
                text,
                pieces,
                partial(tidied, root=root, rel=rel, app=label),
                name * (rel == "models.py"),
            )
            if before is None:
                raise _refuse(
                    f"apps/{label}/{rel} is not the module the scaffold wrote `{name}` into — "
                    f"your lines are in it; {BY_HAND}. Nothing was removed."
                )
            reverted[rel] = before
        made = self.made_migration(app_dir, label, migration)
        dry, total = self.dry_run, 0
        before_floors = floors.measure(root, label)
        for rel, text in reverted.items():
            gone = len((app_dir / rel).read_text().splitlines()) - len(text.splitlines())
            total += gone
            if not dry:
                (app_dir / rel).write_text(text)
            self.stdout.write(
                f"{'would revert' if dry else 'reverted'} apps/{label}/{rel}: {gone} lines"
            )
        if made is not None:
            path, previous = made
            if not dry:
                path.unlink()
                (path.parent / "max_migration.txt").write_text(f"{previous}\n")
            self.stdout.write(f"{self.gone} apps/{label}/migrations/{path.name}")
        if dry:
            return
        self.record_floors(root, label, before_floors)
        self.stdout.write(
            f"removed: `{name}` from `{noun}` — {total} lines in {len(reverted)} files; a budget "
            f"ceiling it raised in {BUDGETS} stays, the tidy only raises"
        )

    def made_migration(self, app_dir: Path, label: str, migration: str) -> tuple[Path, str] | None:
        """The shape's migration and the one before it, when it is the app's last; None if none."""
        folder = app_dir / "migrations"
        numbered = sorted(p for p in folder.glob("0*.py") if MIGRATION.match(p.name))
        mine = [p for p in numbered if p.stem.partition("_")[2] == migration]
        if not mine:
            return None
        if mine[-1] != numbered[-1]:
            raise _refuse(
                f"apps/{label}/migrations/{numbered[-1].name} came after {mine[-1].name} — "
                f"your lines are in it; {BY_HAND}. Nothing was removed."
            )
        if len(numbered) < 2:
            raise _refuse(f"apps/{label}/migrations/{mine[-1].name} is the app's first; {BY_HAND}.")
        return mine[-1], numbered[-2].stem

    def remove(self, root: Path, label: str, noun: str, copy: Copy, first: bool = False) -> None:
        """The copy reverted to `newapp`'s stubs and every shared line it wrote taken back."""
        app_dir = root / "apps" / label
        later = sorted(
            p.name
            for p in (app_dir / "migrations").glob("0*.py")
            if first and p.name != FIRST_MIGRATION
        )
        if later:
            raise _refuse(
                f"apps/{label}/migrations/{later[0]} came after the noun's first migration — "
                f"your lines are in it; {BY_HAND}."
            )
        changed = sorted(
            rel
            for rel, text in copy.files.items()
            if (app_dir / rel).is_file() and (app_dir / rel).read_text() != text
        )
        if not (app_dir / "models.py").is_file() or changed:
            raise _refuse(
                f"apps/{label}/{changed[0] if changed else 'models.py'} is not the copy the "
                f"scaffold wrote for `{noun}` — your lines are in it; {BY_HAND}."
            )
        stubs = newapp_stubs(label)
        born = (
            (app_dir / "apps.py")
            .read_text()
            .startswith(("from django.apps import AppConfig\n", "from typing import ClassVar\n"))
        )
        dry = self.dry_run
        before = {} if born else floors.measure(root, label)
        for rel in copy.files:
            if rel in stubs and not born:
                if not dry:
                    (app_dir / rel).write_text(stubs[rel])
                self.stdout.write(
                    f"{'would revert' if dry else 'reverted'} apps/{label}/{rel} to newapp's stub"
                )
            else:
                if not dry:
                    (app_dir / rel).unlink()
                self.stdout.write(f"{self.gone} apps/{label}/{rel}")
        stub = app_dir / PARITY_STUB
        if not born and self.claims_elsewhere(copy) and not stub.exists():
            if not dry:
                stub.write_text(stubs[PARITY_STUB])
            self.stdout.write(
                f"{'would restore' if dry else 'restored'} apps/{label}/{PARITY_STUB}, "
                "newapp's stub"
            )
        if first:
            self.unfirst(root, label, noun, keep=born)
        self.unrecord_family(root, copy)
        self.unrecord_budgets(root, label, copy)
        self.unrecord_populations(root, copy)
        if born:
            if not dry:
                shutil.rmtree(app_dir)
            self.stdout.write(f"{self.gone} apps/{label}/ — the copy made it")
        elif dry:
            self.stdout.write(
                f"would record apps/{label}/apps.py: ratchet_floors, rule 91's classes"
            )
        else:
            self.record_floors(root, label, before)

    def unfirst(self, root: Path, label: str, noun: str, keep: bool) -> None:
        """The noun's first migration and baseline removed — unless the app goes whole (`keep`)."""
        app_dir = root / "apps" / label
        made = [
            app_dir / "migrations" / FIRST_MIGRATION,
            app_dir / "migrations" / "max_migration.txt",
            root / noun_baseline(label, noun),
        ]
        for path in made:
            if keep or not path.is_file():
                continue
            if not self.dry_run:
                path.unlink()
            self.stdout.write(f"{self.gone} {path.relative_to(root).as_posix()}")

    def unrecord_family(self, root: Path, copy: Copy) -> None:
        """The copy's tag keys taken out of the census or the drawer that froze them."""
        keys = _tag_keys(copy)
        product = namespace(root) is not None
        census = root / (FAMILY_DRAWER if product else FAMILIES)
        if not census.is_file():
            return
        text = census.read_text()
        for key in keys:
            line = f"  - {key}\n" if product else f'    "{key}",\n'
            if line in text:
                text = text.replace(line, "", 1)
                self.stdout.write(f"{self.would}frozen family: {census.relative_to(root)} -= {key}")
        if product and text.strip() == "families:":
            if not self.dry_run:
                census.unlink()
            self.stdout.write(f"{self.gone} {FAMILY_DRAWER} — no family left in it")
            return
        if not self.dry_run:
            census.write_text(text)

    def unrecord_budgets(self, root: Path, label: str, copy: Copy) -> None:
        """Every budget row naming a module the copy wrote, taken out and printed."""
        budgets = root / BUDGETS
        mine = tuple(f"apps/{label}/{rel}" for rel in copy.files)
        kept: list[str] = []
        for line in budgets.read_text().splitlines(keepends=True):
            key = line.strip().partition(": ")[0]
            if line.startswith("  ") and key.split("::")[0] in mine:
                self.stdout.write(f"{self.would}budget row: {BUDGETS} -= {line.strip()}")
                continue
            kept.append(line)
        if not self.dry_run:
            budgets.write_text("".join(kept))

    def unrecord_populations(self, root: Path, copy: Copy) -> None:
        """The copy's door-parity modules taken out of the drawer's addend, the line printed."""
        name, token = DOOR_PARITY
        grown = sum(1 for rel, text in copy.files.items() if "tests/" in rel and token in text)
        drawer = root / DRAWER
        held = re.search(rf'"{name}": (\d+)', drawer.read_text()) if drawer.is_file() else None
        if not grown or held is None:
            return
        text = drawer.read_text()
        left = int(held.group(1)) - grown
        born = (
            '"""This product\'s fixtures drawer: the populations its tests add."""\n\n'
            f'DJB_POPULATION_FLOOR_ADDENDS: dict[str, int] = {{"{name}": {grown}}}\n'
        )
        if left <= 0 and text == born:
            if not self.dry_run:
                drawer.unlink()
            self.stdout.write(f"{self.gone} {DRAWER} — the copy made it")
            return
        if not self.dry_run:
            drawer.write_text(text[: held.start(1)] + str(max(left, 0)) + text[held.end(1) :])
        self.stdout.write(
            f"{self.would}population: {DRAWER} DJB_POPULATION_FLOOR_ADDENDS {name} -= {grown}"
        )
