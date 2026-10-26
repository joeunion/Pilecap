"""`manage.py scaffold` — a registered shape copied from its golden extract into a product app."""

# does-not-cover: a verb adopted on a noun whose modules exist — the copy writes new modules only.
# does-not-cover: what the copy needs beyond the rename — a two-FK noun, a ledger, an M2M.

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import CommandParser

from apps.core.scaffold.arms._common import BY_HAND, NOUN, PENDING, _refuse
from apps.core.scaffold.arms._common import newapp_stubs as newapp_stubs
from apps.core.scaffold.arms.adopt import AdoptArm
from apps.core.scaffold.arms.child import ChildArm
from apps.core.scaffold.arms.enum import EnumArm
from apps.core.scaffold.arms.field import FieldArm
from apps.core.scaffold.arms.filter import FilterArm
from apps.core.scaffold.arms.migration import MigrationArm
from apps.core.scaffold.arms.noun import NounArm
from apps.core.scaffold.arms.ordering import OrderingArm
from apps.core.scaffold.arms.policy import PolicyArm
from apps.core.scaffold.arms.screen import ScreenArm
from apps.core.scaffold.arms.search import SearchArm
from apps.core.scaffold.arms.stat import StatArm
from apps.core.scaffold.arms.surface import ROLE, SURFACE, SurfaceArm
from apps.core.scaffold.arms.verb import VerbArm
from apps.core.scaffold.arms.webhook_in import WebhookInArm
from apps.core.scaffold.arms.workflow import WorkflowArm
from apps.core.scaffold.copier import FACE, GOLDENS, Golden, index
from apps.core.scaffold.shapes import ADOPT, SHAPES, adopt_verbs

#: How `--list` names the one shape drawn from no golden: the stub is the shape.
STUBBED = "no golden: makemigrations --empty, filled with a paired forward/reverse stub"


class Command(
    FieldArm,
    FilterArm,
    OrderingArm,
    VerbArm,
    EnumArm,
    MigrationArm,
    WorkflowArm,
    PolicyArm,
    StatArm,
    SearchArm,
    ChildArm,
    ScreenArm,
    SurfaceArm,
    WebhookInArm,
    NounArm,
    AdoptArm,
):
    help = "Copy a registered shape's golden into a product app, renamed; --list prints them."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--list", action="store_true", help="every registered shape")
        parser.add_argument("shape", nargs="?", help="a registered shape (`--list`)")
        parser.add_argument(
            "words", nargs="*", help="adopt: <verb> <app> <Noun> · noun: <app> <Noun>"
        )
        parser.add_argument(
            "--check", action="store_true", help="diff against the target's own fences; no write"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="every path or anchor it would write; no write"
        )
        parser.add_argument("--data", action="store_true", help="migration: a data migration")
        parser.add_argument(
            "--schedule",
            default="",
            help="workflow: refused — the golden is per-row; a schedule waits for the sweep golden",
        )
        parser.add_argument(
            "--remove",
            action="store_true",
            help="noun, adopt and field: revert the copy and its lines",
        )
        parser.add_argument("--role", help="surface: the role the surface admits")
        parser.add_argument(
            "--permissions",
            help="role and surface: the role's permission patterns, comma-separated",
        )
        parser.add_argument("--families", help="surface: the families it exposes, comma-separated")

    def handle(self, *args: Any, **options: Any) -> None:
        root = Path(settings.BASE_DIR)
        if not (root / "quality" / "engine").is_dir():
            raise _refuse(
                "the scaffold runs on a source checkout — this tree has no quality/ (a deployed "
                "image drops it), so nothing here could be measured; scaffold in development."
            )
        goldens = index(root)
        if options["list"]:
            self.listing(root, goldens)
            return
        wanted = str(options["shape"] or "")
        registered = next((s for s in SHAPES if s.key == wanted), None)
        if registered is None:
            raise _refuse(
                f"{wanted!r} is no registered shape — `manage.py scaffold --list` prints the "
                f"closed registry ({' '.join(s.key for s in SHAPES)})."
            )
        self.dry_run = bool(options["dry_run"])
        self.removing = bool(options["remove"])
        if self.removing and registered.key not in (NOUN, ADOPT, "field"):
            raise _refuse(f"`{registered.key}`: {BY_HAND}.")
        if registered.key == NOUN:
            self.noun(root, goldens, [str(w) for w in options["words"]], bool(options["check"]))
            return
        if registered.golden == FACE:
            words = [str(w) for w in options["words"]]
            self.screen(root, goldens, words, bool(options["check"]), bool(options["dry_run"]))
            return
        if registered.key in (SURFACE, ROLE):
            self.declare(root, goldens, registered, options)
            return
        if registered.key == "migration":
            self.migration(root, [str(w) for w in options["words"]], bool(options["data"]))
            return
        if registered.key == "ordering":
            self.ordering(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key == "filter":
            self.filter(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key == "enum":
            self.enum(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key == "stat":
            self.stat(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key == "policy":
            self.policy(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key == "search":
            self.search(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key == "child":
            self.child(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key == "workflow":
            self.workflow(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key == "webhook-in":
            self.webhook_in(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key in ("verb", "event"):
            self.verb(root, goldens, registered, [str(w) for w in options["words"]], options)
            return
        if registered.key == "field":
            words = [str(w) for w in options["words"]]
            self.field(root, goldens, registered, words, options)
            return
        words = [str(w) for w in options["words"]]
        self.adopt(root, goldens, registered, words, options)

    def listing(self, root: Path, goldens: dict[str, Golden]) -> None:
        """One line per registered shape: its extract, or `golden pending: <slice>`."""
        width = max(len(s.key) for s in SHAPES)
        said = max(len(s.args) for s in SHAPES)
        on = max(len(s.on) for s in SHAPES) + 3
        for shape in SHAPES:
            grammar = f"{shape.args:<{said}}  {'on ' + shape.on:<{on}} "
            if shape.key == ADOPT:
                for verb in adopt_verbs(root):
                    found = goldens.get(f"{ADOPT}.{verb}")
                    where = self.where(found) if found else PENDING
                    self.stdout.write(f"{shape.key:<{width}}  {verb:<9} {grammar} {where}")
                continue
            found = self.drawn(shape, goldens)
            where = self.where(found) if found else PENDING
            if shape.key == "migration":
                where = STUBBED
            if shape.key == "event" and found:
                where = f"{GOLDENS}/{found.key}/ (its events.py alone, fenced in apps/{found.app})"
            self.stdout.write(f"{shape.key:<{width}}  {'':<9} {grammar} {where}")

    @staticmethod
    def where(golden: Golden) -> str:
        """An extract as `--list` names it: its directory and how many modules it holds."""
        home = f"apps/{golden.app}" if golden.app else "the worked face"
        return f"{GOLDENS}/{golden.key}/ ({len(golden.files)} modules, fenced in {home})"
