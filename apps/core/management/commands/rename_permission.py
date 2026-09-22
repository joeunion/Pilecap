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

**Three modes, one reader.** `<old> <new>` moves one declared pair. `--declared`
moves EVERY declared pair in one pass, which is what a deployment upgrading
across a rename release actually wants, and which is idempotent by construction
(the second run finds no row under an old key and says so). `--table` writes
nothing at all: it prints the release note's own rename table, derived from
`renamed_permissions()` — the union of every app's `RENAMED_PERMISSIONS` — so
the CHANGELOG's table is this command's OUTPUT rather than a hand list beside
it. `apps/core/tests/test_vocabulary.py` is the census that refuses a pair
declared in code and absent from the note.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.authz import _declarations, renamed_permissions, vocabulary
from apps.core.services import rename_permission_rows

#: The two fixed lines of the markdown table `--table` prints. They are spelled
#: here, once, because the census in `apps/core/tests/test_vocabulary.py` finds
#: the CHANGELOG's tables BY this header: a table shape that drifts has to drift
#: in one place, and the census stops finding it rather than quietly passing
#: over a table it no longer recognises.
TABLE_HEADER = "| app | old key | new key |"
TABLE_RULE = "|---|---|---|"


def declared_renames() -> list[tuple[str, str, str]]:
    """`(app label, old key, new key)` for every declared rename, sorted.

    **The pair set is `renamed_permissions()`'s and nothing else's** — that
    function is the union every other reader in the tree already asks, and a
    second walk that built its own set could come to disagree with the one
    `resolve_renamed` answers from. The declaration walk is asked for ONE thing
    the union does not carry: which app's `policies.py` declared each old key,
    which is the first column of the release note's table.

    **Two refusals, both could-not-look (exit 2), because a wrong first column
    is worse than no table.** A pair in the union that no walked declaration
    claims would mean the union and the walk disagree about what exists. And
    TWO apps declaring one old key would silently attribute the pair to
    whichever app the registry walked last: `authz._discover_renames` already
    refuses two declarers that disagree about the SUCCESSOR, so the case that
    reaches here is two apps agreeing — which reads as harmless and is not, at
    the moment a reader follows the note's first column to the file that owns
    the key. Both refusals name every party.
    """
    declarers: dict[str, str] = {}
    contested: dict[str, list[str]] = {}
    for config, declared in _declarations("policies", "RENAMED_PERMISSIONS"):
        label = str(config.label)
        for raw_old in declared:
            old_key = str(raw_old)
            if old_key in declarers and declarers[old_key] != label:
                contested.setdefault(old_key, [declarers[old_key]]).append(label)
            declarers[old_key] = label

    if contested:
        named = "; ".join(
            f"{key!r} by {' and '.join(sorted(apps))}" for key, apps in sorted(contested.items())
        )
        raise CommandError(
            f"one old key, two declaring apps: {named}. `renamed_permissions()` unions "
            "them into one pair, so the table's first column would name whichever app "
            "the registry walked last. Declare the rename in the app that owns the key "
            "and nowhere else. Nothing was printed.",
            returncode=2,
        )

    rows: list[tuple[str, str, str]] = []
    unattributed: list[str] = []
    for old, new in renamed_permissions().items():
        app = declarers.get(old)
        if app is None:
            unattributed.append(old)
            continue
        rows.append((app, old, new))

    if unattributed:
        raise CommandError(
            f"{', '.join(sorted(unattributed))} is renamed by `renamed_permissions()` "
            "but no app's `policies.py` declares it. The union and the declaration "
            "walk disagree; nothing was printed.",
            returncode=2,
        )
    return sorted(rows)


def rename_table() -> str:
    """The release note's table, as text, ending in a newline."""
    lines = [TABLE_HEADER, TABLE_RULE]
    lines += [f"| {app} | `{old}` | `{new}` |" for app, old, new in declared_renames()]
    return "\n".join(lines) + "\n"


class Command(BaseCommand):
    """`manage.py rename_permission <old> <new> | --declared | --table`."""

    help = "Rewrite Grant and RolePermission rows from retired permission keys to their successors."

    def add_arguments(self, parser: CommandParser) -> None:
        # The two positionals become optional so `--declared` and `--table` can
        # stand alone; the mode check in `handle` is what refuses a bare call,
        # because argparse cannot express "these two, or exactly one flag".
        parser.add_argument(
            "old",
            nargs="?",
            default=None,
            help="the retired key, as RENAMED_PERMISSIONS declares it",
        )
        parser.add_argument(
            "new", nargs="?", default=None, help="its successor, which must be in the vocabulary"
        )
        parser.add_argument(
            "--declared",
            action="store_true",
            help="move every declared pair in one pass; idempotent, and says so when nothing moves",
        )
        parser.add_argument(
            "--table",
            action="store_true",
            help=(
                "print the release note's rename table, derived from "
                "renamed_permissions(); writes nothing"
            ),
        )

    def handle(self, *args: Any, **options: Any) -> None:
        old = options["old"]
        new = options["new"]
        table = bool(options["table"])
        declared_mode = bool(options["declared"])

        if table and declared_mode:
            self.stderr.write(
                "--table prints and --declared writes. Ask for one. Nothing was done."
            )
            raise SystemExit(2)
        if (table or declared_mode) and (old is not None or new is not None):
            self.stderr.write(
                "--table and --declared read the whole declared table; they take no key "
                "arguments. Nothing was done."
            )
            raise SystemExit(2)
        if table:
            self.stdout.write(rename_table(), ending="")
            return
        if declared_mode:
            self._move_every_declared_pair()
            return
        if old is None or new is None:
            self.stderr.write(
                "Name a pair (`<old> <new>`), or --declared for every declared pair, "
                "or --table to print the table. Nothing was done."
            )
            raise SystemExit(2)

        self._move_one_pair(str(old), str(new))

    def _move_one_pair(self, old: str, new: str) -> None:
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
        for table_name, count in sorted(moved.items()):
            self.stdout.write(f"{table_name}: {count} row(s) rewritten from {old} to {new}")

    def _move_every_declared_pair(self) -> None:
        """Every declared pair, one pass, across every tenant.

        Idempotent because the underlying service is: the second run's
        `filter(permission=<old>)` matches nothing, every count is zero, and the
        summary says so rather than printing twenty-nine zero lines an operator
        would have to read to learn that nothing happened.
        """
        pairs = declared_renames()
        total = 0
        for _app, old, new in pairs:
            moved = rename_permission_rows(old=old, new=new)
            pair_total = sum(moved.values())
            total += pair_total
            if pair_total:
                counts = ", ".join(f"{name} {count}" for name, count in sorted(moved.items()))
                self.stdout.write(f"{old} -> {new}: {counts}")

        if total:
            self.stdout.write(f"{len(pairs)} declared rename(s); {total} row(s) rewritten.")
        else:
            self.stdout.write(
                f"{len(pairs)} declared rename(s); nothing to rewrite — "
                "no row in any tenant names a retired key."
            )
