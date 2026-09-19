"""Move every tenant's rows from a retired permission key onto its successor.

The rename table (`RENAMED_PERMISSIONS`, declared per app beside the prose)
keeps an old key ANSWERING after a sweep renames it: `core.authz.resolve_renamed`
maps it at `require` time, so nothing breaks the day the rename lands. What the
table does not do is move the tenant's own rows — a `Grant` or a
`RolePermission` written before the sweep still says the old word, the deploy
census reports it as a key naming nothing, and it stays that way forever unless
somebody rewrites it. This is that somebody.

**An operator act, and the command is its door.** It runs across every tenant at
once, at an altitude no tenant persona holds — the `bootstrap_tenant` precedent
— and it is the deployment's own maintenance rather than a tenant's, so it
writes no per-tenant audit row and prints its counts instead (the service's
docstring says why).

**It refuses more than it does.** A pair the rename table does not declare is
not a rename, it is a typo or a decision nobody wrote down; a `new` key outside
the vocabulary is a rewrite onto a word nothing answers. Both are exit 2 — the
could-not-look class — because a half-applied rename across every tenant is
worse than one that did not start.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from apps.core.authz import renamed_permissions, vocabulary
from apps.core.services import rename_permission_rows


class Command(BaseCommand):
    """`manage.py rename_permission <old> <new>`."""

    help = "Rewrite Grant and RolePermission rows from a retired permission key to its successor."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("old", help="the retired key, as RENAMED_PERMISSIONS declares it")
        parser.add_argument("new", help="its successor, which must be in the vocabulary")

    def handle(self, *args: Any, **options: Any) -> None:
        old = str(options["old"])
        new = str(options["new"])

        if new not in vocabulary():
            self.stderr.write(
                f"{new!r} is not a permission this deployment declares. Nothing was rewritten."
            )
            raise SystemExit(2)

        declared = renamed_permissions()
        if declared.get(old) != new:
            self.stderr.write(
                f"{old!r} -> {new!r} is not a declared rename. "
                "Add it to the owning app's `RENAMED_PERMISSIONS` first, so the old key "
                "keeps answering while the rows move. Nothing was rewritten."
            )
            raise SystemExit(2)

        moved = rename_permission_rows(old=old, new=new)
        for table, count in sorted(moved.items()):
            self.stdout.write(f"{table}: {count} row(s) rewritten from {old} to {new}")
