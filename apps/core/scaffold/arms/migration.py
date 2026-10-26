"""The `migration` arm: makemigrations' empty file with a paired forward/reverse stub."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from django.core.management.base import CommandError

from apps.core.management.commands.newapp import LABEL
from apps.core.scaffold.arms._common import PARTITION, Arms, _refuse, platform_apps
from apps.core.scaffold.copier import tidied

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("migration",)

#: The paired stub `scaffold migration --data` writes into the empty migration Django made.
DATA_STUB = """from django.apps.registry import Apps
from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def forward(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    \"\"\"Move the rows forward; read every model through `apps.get_model`, never an import.\"\"\"


def reverse(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    \"\"\"Undo what `forward` wrote, so the migration runs backwards (house rule 22).\"\"\"
"""
DATA_OPERATIONS = "    operations = [\n        migrations.RunPython(forward, reverse),\n    ]\n"


def data_migration(empty: str) -> str:
    """The empty migration `makemigrations --empty` wrote, with the paired forward/reverse stub."""
    head, found, tail = empty.partition("from django.db import migrations\n")
    if not found or "operations = [" not in tail:
        raise _refuse("the empty migration is not the shape `makemigrations --empty` writes.")
    body = re.sub(r"    operations = \[\s*\]\n", DATA_OPERATIONS, tail)
    return head + DATA_STUB + body


class MigrationArm(Arms):
    """`scaffold migration`."""

    def migration(self, root: Path, words: list[str], data: bool) -> None:
        """`migration <app> <name> --data`: makemigrations' empty file with a paired stub."""
        if len(words) != 2 or not data:
            raise _refuse(
                "migration takes <app> <name> --data — a schema migration is `makemigrations`' "
                "own; the scaffold writes the data one's paired stub (house rule 22)."
            )
        label, name = words
        if not LABEL.match(label) or not (root / "apps" / label / "migrations").is_dir():
            raise _refuse(f"apps/{label} has no migrations/ — a data migration goes into an app.")
        if label in platform_apps(root):
            raise _refuse(f"apps/{label} is a platform app ({PARTITION}) — never a product's.")
        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            raise _refuse(f"{name!r} is no migration name — lower case, digits and underscores.")
        if self.dry_run:
            self.plan(root, None, label, migration=name, records=False)
            return
        done = subprocess.run(  # noqa: S603 — argv list to this interpreter's manage.py; label and name are validated words
            [sys.executable, "manage.py", "makemigrations", label, "--empty", "-n", name],
            cwd=root,
            capture_output=True,
            text=True,
        )
        said = (done.stdout + done.stderr).strip()
        made = [line.strip() for line in said.splitlines() if line.strip().endswith(".py")]
        if done.returncode != 0 or not made:
            raise CommandError(f"makemigrations {label} --empty refused: {said}", returncode=1)
        path = root / made[0]
        path.write_text(
            tidied(data_migration(path.read_text()), root, f"migrations/{path.name}", label)
        )
        self.stdout.write(f"migration: {made[0]} — RunPython(forward, reverse); fill both.")
