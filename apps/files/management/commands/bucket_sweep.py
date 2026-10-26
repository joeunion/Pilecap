"""`manage.py bucket_sweep` — db_sweep.sh's bucket half; FOREIGN goes only by --force-foreign."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from django.conf import settings

from apps.core.management import BaseCommand
from apps.files import storage


def _paths(lines: list[str], kind: str) -> list[Path]:
    prefix = f"{kind} "
    return [Path(line[len(prefix) :]).resolve() for line in lines if line.startswith(prefix)]


class Command(BaseCommand):
    help = "Census or remove the object-storage buckets derived from checkout paths."
    stealth_options = ("stdin",)

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--sweep", action="store_true", help="remove, not only list")
        parser.add_argument(
            "--orphans", action="store_true", help="every djb-* bucket, judged by stdin's paths"
        )
        parser.add_argument(
            "--roots",
            action="append",
            type=Path,
            default=[],
            help="a directory the census scanned for clones (repeatable)",
        )
        parser.add_argument(
            "--force-foreign",
            action="store_true",
            help="with --orphans --roots --sweep: remove every FOREIGN bucket too",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        roots: list[Path] = options["roots"]
        if options["force_foreign"]:
            self._refuse_unlicensed(roots=roots, orphans=options["orphans"], sweep=options["sweep"])
        try:
            if options["orphans"]:
                self._orphans(
                    sweep=options["sweep"],
                    stream=options.get("stdin") or sys.stdin,
                    roots=roots,
                    force_foreign=options["force_foreign"],
                )
            else:
                self._checkout(sweep=options["sweep"])
        except storage.StorageUnreadable as failure:
            self.stdout.write(f"could not look: buckets — {failure}")
            raise SystemExit(2) from failure

    def _refuse_unlicensed(self, *, roots: list[Path], orphans: bool, sweep: bool) -> None:
        if not roots:
            reason = (
                "--force-foreign needs --roots <dir> — the census must have been given every"
                " place clones live"
            )
        elif not (orphans and sweep):
            reason = "--force-foreign is a licence to remove and belongs to --orphans --sweep"
        else:
            reason = next(
                (
                    f"--roots {root} is not a directory; nothing was scanned there"
                    for root in roots
                    if not root.is_dir()
                ),
                "",
            )
        if reason:
            self.stdout.write(f"REFUSED: {reason}; nothing removed")
            raise SystemExit(2)

    def _checkout(self, *, sweep: bool) -> None:
        root = Path(settings.BASE_DIR)
        if sweep:
            removed = storage.remove_derived_buckets(root=root)
            for name in removed:
                self.stdout.write(f"  REMOVED  {name} — this checkout's ({root})")
            verb = "removed"
        else:
            removed = [n for n in storage.list_derived_buckets() if storage.derives(root, n)]
            for name in removed:
                self.stdout.write(f"  bucket   {name} — this checkout's ({root})")
            verb = "found"
        self.stdout.write(f"buckets: {len(removed)} {verb}")

    def _orphans(self, *, sweep: bool, stream: Any, roots: list[Path], force_foreign: bool) -> None:
        lines = [line.rstrip("\n") for line in stream.readlines()]
        live = _paths(lines, "live")
        if force_foreign and not live:
            self.stdout.write(
                "REFUSED: --force-foreign was handed no live checkout, so every bucket would"
                " read FOREIGN; nothing removed"
            )
            raise SystemExit(2)
        handed = [path for path in _paths(lines, "handed") if path not in live]
        for root in roots:
            self.stdout.write(f"  scanned  {root.resolve()}")
        orphans: list[tuple[str, Path]] = []
        foreign: list[str] = []
        for name in storage.list_derived_buckets():
            owner = next((path for path in live if storage.derives(path, name)), None)
            if owner is not None:
                self.stdout.write(f"  live     {name} — {owner}")
                continue
            dead = next((path for path in handed if storage.derives(path, name)), None)
            if dead is None:
                foreign.append(name)
                self.stdout.write(
                    f"  FOREIGN  {name} — no path this run was handed derives it; "
                    + ("--force-foreign removes" if force_foreign else "never removed")
                )
            else:
                orphans.append((name, dead))
                self.stdout.write(
                    f"  ORPHAN   {name} — derived from {dead}, no checkout there; --sweep removes"
                )
        removed = forced = 0
        if sweep:
            for name, dead in orphans:
                storage.remove_derived_buckets(root=dead)
                removed += 1
                self.stdout.write(f"  REMOVED  {name} — derived from {dead}")
        if sweep and force_foreign:
            for name in storage.remove_foreign_buckets(foreign, roots=roots):
                forced += 1
                self.stdout.write(f"  REMOVED  {name} — FOREIGN, on the operator's word")
        left_orphans = 0 if sweep else len(orphans)
        self.stdout.write(
            f"buckets: {removed + forced} removed ({forced} foreign) · {left_orphans} orphan"
            f" · {len(foreign) - forced} FOREIGN"
        )
