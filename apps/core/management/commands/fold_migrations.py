"""Graft an arriving template migration chain onto the product's own leaf.

**The fold this exists for.** A product built on this template adds its own
migrations to a template app — `core`, `accounts` — because that is where the
model it extended lives. The next template release adds migrations to the same
app, from the same ancestor, and `git merge <tag>` lands both chains in one
directory with `max_migration.txt` in conflict: two leaves, one app, and
`django-linear-migrations` refusing everything downstream of that until a human
picks. The consumer paid for this by hand at v2.1.0 — twelve `[divergence]`
commits, one of them nothing but renumbered migrations.

**Why `rebase_migration` is not it, though it is most of it.** The library's
command moves exactly ONE migration — the rebased side of the conflict — to
`leaf + 1` and repoints its single in-app dependency at the merged leaf. Two
things about the fold are outside that:

* **The arriving side is a CHAIN, not a migration.** A release adds three or
  four migrations to `accounts`; moving only the last one leaves the rest
  hanging off an ancestor the product's own chain has already passed, which is
  two leaves again (or, once a cross-app dependency names one of them, a
  `NodeNotFoundError` at the next `migrate`).
* **The ancestor may have been RENAMED by the previous fold.** The release
  after next depends on `("accounts", "0010_default_role_is_a_key")` — a name
  that, in the product's tree, this very command turned into
  `0012_default_role_is_a_key` a release ago. The dependency dangles, and no
  amount of renumbering fixes a name that is not there.

So: subclass the library's command (principle 2 — the established technology,
generalised, not replaced), keep its conflict-marker grammar, its
applied-migration refusal and its dependency-rewriting technique, and widen the
subject from one migration to the chain, resolving a renamed ancestor by the
one thing a rename here preserves — the stem after `NNNN_`.

**The direction, stated once, because it is the opposite of the library's.**
`rebase_migration` moves YOURS onto THEIRS: you merged main into your feature
branch, so main's leaf is the base and your migration is renumbered.
`fold_migrations` moves THEIRS onto YOURS: the product merges a template tag
into its own main, so the PRODUCT's leaf is the base and the arriving TEMPLATE
chain is renumbered. The top of a conflict block (`<<<<<<< HEAD`) is the
product either way, which is why this command reads the markers positionally
and undoes the library's merge-time swap.

**Template migration files stay Django-native.** Nothing here is spelled into
the template's own tree — no named-ancestor indirection, no fold-aware
dependency syntax that `makemigrations` would regenerate away. This is the
PRODUCT's tool, run once per app at the fold, and its whole effect is a rename
plus a dependency rewrite that
`git checkout -- <app>/migrations && git clean -f <app>/migrations` undoes
(principle 6) — BOTH halves, because a rename leaves the new filename as an
UNTRACKED file that `git checkout` alone restores nothing about, so a checkout
on its own gives you the old chain and the grafted copies side by side.

**It refuses more than it does.** A `git rebase` in progress, an arriving
migration already applied to the local database, a dependency whose stem
resolves to nothing or to two migrations, a `max_migration.txt` with no
conflict in it, a target filename already taken — all exit 2, the
could-not-look class, naming the migration. A half-grafted chain is worse than
one that did not start.

**THE CROSS-APP GAP, DECLARED.** A dependency from ANOTHER app onto a migration
this command renumbered — `("accounts", "0008_identity_branding")` written in
`apps/comms/migrations/…` while the fold made it `0010_identity_branding` — is
left exactly as written: the stem resolution runs only within the app being
folded, because a stem is unique per app and nothing here is entitled to edit
another app's files. Django's own loader then raises `NodeNotFoundError`
naming both ends at the next `migrate` or `manage.py check`. That is loud and
it is never wrong, which is why it is a declared gap and not a silent one; the
fix is to fold the other app too, or to repoint that one dependency by hand.
ADR core-28 records it, and closing it is queued.

ADR core-28 (`docs/product/architecture.md`).
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.apps import apps
from django.core.management.base import CommandError
from django_linear_migrations.apps import MigrationDetails, is_first_party_app_config
from django_linear_migrations.management.commands.rebase_migration import (
    Command as RebaseMigrationCommand,
)
from django_linear_migrations.management.commands.rebase_migration import (
    find_migration_names,
    is_merge_in_progress,
    migration_applied,
)

#: `0012_default_role_is_a_key` -> `("0012", "default_role_is_a_key")`. The stem
#: is what a renumbering preserves and therefore the only handle a renamed
#: ancestor leaves behind; `test_migration_stems.py` pins that the template
#: never ships two migrations in one app with the same stem, which is the
#: precondition that makes resolving by it a closed question.
_NUMBERED = re.compile(r"^(\d+)_(.+)$")

#: A walk over a dependency chain cannot be longer than the app's own file
#: count; anything past that is a cycle somebody hand-edited in, and a command
#: that spins forever on it is worse than one that says so.
_CYCLE_GUARD_SLACK = 1

#: What the plan prints where a common ancestor would go when the arriving chain
#: reaches all the way back to the app's root without meeting the product's own
#: history — legal, and worth saying rather than printing an empty column.
_NO_ANCESTOR = "(none — the arriving chain starts at the root)"


def _rebase_in_progress() -> bool:
    """Whether a `git rebase` is stopped in this working tree.

    `REBASE_HEAD` is the ref git writes when a rebase halts — at a conflict, an
    `edit`, a failed `--exec` — and it is the only one of the three states that
    inverts this command's direction (see `_read_markers`). Written here rather
    than borrowed because the library has no equivalent: `rebase_migration`
    WANTS the rebase case and has no reason to detect it.

    A git that is missing, broken, or run outside a repository answers False,
    which is `is_merge_in_progress`'s own convention and the right one: a tree
    with no git in it cannot be mid-rebase, and inventing a refusal for it would
    refuse every fold run from an exported tarball.
    """
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", "REBASE_HEAD"],  # noqa: S607 — `git` from PATH in the developer's checkout
            capture_output=True,
            check=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return True


def _refuse(message: str) -> CommandError:
    """The could-not-look class: exit 2, naming what could not be resolved.

    Exit 2 rather than 1 for the reason the gate uses the same split — a
    refusal here means the fold could not be *computed*, not that the tree is
    wrong, and the operator's next move is to look rather than to fix.
    """
    return CommandError(message, returncode=2)


def _split(name: str) -> tuple[int, str]:
    match = _NUMBERED.match(name)
    if match is None:
        raise _refuse(
            f"{name!r} is not a numbered migration name (`NNNN_stem`), so it has no stem "
            "to graft by. Rename it or fold this app by hand."
        )
    return int(match.group(1)), match.group(2)


def _stem(name: str) -> str:
    return _split(name)[1]


@dataclass(frozen=True)
class _Dependency:
    """One entry of a migration's `dependencies`, and the AST node it came from.

    `app_label`/`name` are `None` for anything that is not a literal two-string
    tuple — `swappable_dependency(...)`, a name built at import, a malformed
    entry. Those are copied through untouched, exactly as `rebase_migration`
    copies them, because rewriting something whose value is computed would be
    guessing at what it computes to.
    """

    node: ast.expr
    app_label: str | None
    name: str | None


@dataclass
class _MigrationFile:
    """One migration on disk, parsed far enough to renumber and repoint it."""

    path: Path
    name: str
    number: int
    stem: str
    content: str
    dependencies_node: ast.List | ast.Tuple
    dependencies: list[_Dependency]

    def in_app(self, app_label: str) -> list[_Dependency]:
        return [d for d in self.dependencies if d.app_label == app_label]


def _parse_migration(path: Path, name: str) -> _MigrationFile:
    """Read one migration file into the shape the graft needs.

    Deliberately AST over import: the whole point of this command is a
    directory Django's own loader refuses to build a graph from, so importing
    the modules to read their dependencies would mean standing up the thing the
    conflict has broken. `rebase_migration` reads its one file the same way and
    for the same reason.
    """
    number, stem = _split(name)
    content = path.read_text()
    try:
        module = ast.parse(content)
    except SyntaxError as bad:
        raise _refuse(f"{path.name!r} does not parse: {bad}") from bad

    class_defs = [
        node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "Migration"
    ]
    if len(class_defs) != 1:
        raise _refuse(
            f"{path.name!r} holds {len(class_defs)} `Migration` classes; a migration this "
            "command can graft holds exactly one."
        )

    assignments = [
        node
        for node in class_defs[0].body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "dependencies"
        and isinstance(node.value, (ast.List, ast.Tuple))
    ]
    if len(assignments) != 1:
        raise _refuse(
            f"{path.name!r} holds {len(assignments)} `dependencies = [...]` assignments; a "
            "migration this command can graft holds exactly one."
        )
    node = assignments[0].value
    assert isinstance(node, (ast.List, ast.Tuple))  # noqa: S101 — narrows the ast type for mypy; a False is a bug, not input

    dependencies: list[_Dependency] = []
    for element in node.elts:
        literal = (
            isinstance(element, (ast.Tuple, ast.List))
            and len(element.elts) == 2
            and all(
                isinstance(part, ast.Constant) and isinstance(part.value, str)
                for part in element.elts
            )
        )
        if not literal:
            dependencies.append(_Dependency(node=element, app_label=None, name=None))
            continue
        assert isinstance(element, (ast.Tuple, ast.List))  # noqa: S101 — narrows the ast type for mypy; a False is a bug, not input
        first, second = element.elts
        assert isinstance(first, ast.Constant) and isinstance(second, ast.Constant)  # noqa: S101 — narrows the ast type for mypy; a False is a bug, not input
        dependencies.append(
            _Dependency(node=element, app_label=str(first.value), name=str(second.value))
        )

    return _MigrationFile(
        path=path,
        name=name,
        number=number,
        stem=stem,
        content=content,
        dependencies_node=node,
        dependencies=dependencies,
    )


@dataclass(frozen=True)
class _Graft:
    """One arriving migration, its new name, and the in-app parent it lands on."""

    migration: _MigrationFile
    new_name: str
    new_parent: str


@dataclass(frozen=True)
class _Plan:
    """Everything the fold will do, computed before anything moves.

    Separated from the doing so `--dry-run` is the SAME computation printed
    rather than a second, kinder one — a dry run that took a different path
    would be a description of a program nobody runs.
    """

    app_label: str
    directory: Path
    product_leaf: str
    arriving_leaf: str
    ancestor: str | None
    grafts: tuple[_Graft, ...]

    def describe(self) -> list[str]:
        lines = [
            f"fold_migrations {self.app_label}",
            f"  product leaf     {self.product_leaf}",
            f"  arriving leaf    {self.arriving_leaf}",
            f"  common ancestor  {self.ancestor or _NO_ANCESTOR}",
            f"  grafting {len(self.grafts)} migration(s) onto {self.product_leaf}:",
        ]
        width = max(len(graft.migration.name) for graft in self.grafts)
        for graft in self.grafts:
            lines.append(
                f"    {graft.migration.name:<{width}} -> {graft.new_name}"
                f'   dependency ("{self.app_label}", "{graft.new_parent}")'
            )
        lines.append(f"  max_migration.txt -> {self.grafts[-1].new_name}")
        return lines


class Command(RebaseMigrationCommand):
    """`manage.py fold_migrations <app> [--dry-run]`.

    Subclasses `rebase_migration` for what the fold shares with it — chiefly
    `requires_system_checks = []`, without which
    `django_linear_migrations`' own `dlm.E002` check refuses to let any command
    run at all while `max_migration.txt` holds a conflict, which is every time
    this one is wanted.
    """

    help = (
        "Graft an arriving template migration chain onto this product's own leaf after a "
        "template merge left max_migration.txt in conflict."
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "app_label",
            help="The app whose max_migration.txt holds the conflict.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the graft and change nothing.",
        )

    def handle(self, *args: Any, app_label: str, **options: Any) -> None:
        plan = self._plan(app_label)
        for line in plan.describe():
            self.stdout.write(line)
        if options.get("dry_run"):
            self.stdout.write("  dry run — nothing was moved.")
            return
        self._apply(plan)
        self.stdout.write(
            f"Grafted {len(plan.grafts)} migration(s) onto {plan.product_leaf}, rewrote their "
            f"dependencies, and set max_migration.txt to {plan.grafts[-1].new_name}."
        )

    # -- the computation -------------------------------------------------

    def _plan(self, app_label: str) -> _Plan:
        app_config = apps.get_app_config(app_label)
        if not is_first_party_app_config(app_config):
            raise _refuse(f"{app_label!r} is not a first-party app.")

        details = MigrationDetails(app_label)
        max_migration_txt = details.dir / "max_migration.txt"
        if not max_migration_txt.exists():
            raise _refuse(f"{app_label} does not have a max_migration.txt.")

        product_leaf, arriving_leaf = self._read_markers(app_label, max_migration_txt)
        for label, name in (("product", product_leaf), ("arriving", arriving_leaf)):
            if name not in details.names:
                raise _refuse(
                    f"Parsed {name!r} as the {label} leaf from {app_label}'s "
                    f"max_migration.txt, but no such migration exists."
                )

        files = {
            name: _parse_migration(details.dir / f"{name}.py", name)
            for name in sorted(details.names)
            if _NUMBERED.match(name)
        }
        by_stem: dict[str, list[str]] = {}
        for name, migration in files.items():
            by_stem.setdefault(migration.stem, []).append(name)

        product_chain = self._walk_back(app_label, files, by_stem, product_leaf)
        arriving, ancestor = self._arriving_chain(
            app_label, files, by_stem, arriving_leaf, set(product_chain)
        )

        for migration in arriving:
            if migration_applied(app_label, migration.name):
                raise _refuse(
                    f"{migration.name} is one of the arriving migrations, but it is applied to "
                    "the local database. A migration that has already run cannot be renumbered "
                    "underneath the recorder. Reverse it, or fold this app on a database that "
                    "has not seen the arriving chain, and try again."
                )

        next_number = files[product_leaf].number + 1
        grafts: list[_Graft] = []
        parent = product_leaf
        for offset, migration in enumerate(arriving):
            new_name = f"{str(next_number + offset).zfill(4)}_{migration.stem}"
            grafts.append(_Graft(migration=migration, new_name=new_name, new_parent=parent))
            parent = new_name

        moving = {graft.migration.name for graft in grafts}
        for graft in grafts:
            if graft.new_name in files and graft.new_name not in moving:
                raise _refuse(
                    f"Grafting {graft.migration.name} would name it {graft.new_name}, and "
                    f"{graft.new_name} is already a migration in {app_label} that this fold is "
                    "not moving. Fold this app by hand."
                )

        return _Plan(
            app_label=app_label,
            directory=details.dir,
            product_leaf=product_leaf,
            arriving_leaf=arriving_leaf,
            ancestor=ancestor,
            grafts=tuple(grafts),
        )

    def _read_markers(self, app_label: str, max_migration_txt: Path) -> tuple[str, str]:
        """`(the product's leaf, the arriving template leaf)` from the conflict.

        `find_migration_names` is the library's — its grammar for what a
        conflict block looks like is exactly the grammar this command wants —
        and it returns `(merged, rebased)` with the pair SWAPPED during a merge,
        because for `rebase_migration` a merge means main arrived and your own
        migration is the one to move. The fold is the other direction (see the
        module docstring), so the swap is undone: the top of the block is the
        product's leaf whether the working tree is mid-merge or not.

        **AND A REBASE IS REFUSED OUTRIGHT, because under one the top of the
        block is not the product.** `git rebase` replays YOUR commits onto the
        upstream, so while it is stopped `HEAD` is the upstream — the template —
        and `MERGE_HEAD` does not exist, which means the library does not swap
        and neither does this command. The two inversions cancel into a fold
        that renumbers the PRODUCT's own chain onto the template's leaf and says
        nothing at all about it: a silent wrong answer, which is the one outcome
        this command is not allowed to have. `REBASE_HEAD` is the tell, and it
        is checked before the markers are read rather than after, so nothing is
        computed against a direction that is already known to be backwards.
        """
        if _rebase_in_progress():
            raise _refuse(
                "the fold expects a merge; under a rebase HEAD is the upstream, so the top of "
                f"{app_label}'s max_migration.txt conflict is the TEMPLATE's leaf and not this "
                "product's, and grafting it would renumber the product's own chain. Finish or "
                "abort the rebase and `git merge` the template tag instead. Nothing was moved."
            )
        names = find_migration_names(max_migration_txt.read_text().splitlines())
        if names is None:
            raise _refuse(
                f"{app_label}'s max_migration.txt does not hold a merge conflict. "
                "fold_migrations grafts an arriving chain onto a product's leaf; with one leaf "
                "there is nothing to graft."
            )
        first, second = names
        if is_merge_in_progress():
            first, second = second, first
        return first, second

    def _resolve(
        self,
        app_label: str,
        files: dict[str, _MigrationFile],
        by_stem: dict[str, list[str]],
        name: str,
    ) -> str:
        """The migration a dependency names, following a rename by its stem.

        The exact name wins when it is there. When it is not — the dependency
        was written against a template numbering an earlier fold renumbered —
        the stem is the handle, and the answer has to be exactly one migration:
        nothing means the ancestor is not in this tree at all, and two means the
        app ships one stem twice and the handle is not a handle. Both refuse by
        name rather than picking.
        """
        if name in files:
            return name
        stem = _stem(name)
        candidates = sorted(by_stem.get(stem, []))
        if not candidates:
            raise _refuse(
                f"A migration in {app_label} depends on {name!r}, which does not exist and "
                f"whose stem {stem!r} matches no migration in the app either. An earlier fold "
                "renumbered it under a different stem, or it was never merged. Nothing was moved."
            )
        if len(candidates) > 1:
            raise _refuse(
                f"A migration in {app_label} depends on {name!r}, which does not exist, and its "
                f"stem {stem!r} matches {len(candidates)} migrations ({', '.join(candidates)}). "
                "A stem this command grafts by names one migration. Nothing was moved."
            )
        return candidates[0]

    def _parent_of(
        self,
        app_label: str,
        files: dict[str, _MigrationFile],
        by_stem: dict[str, list[str]],
        migration: _MigrationFile,
    ) -> str | None:
        """The one in-app migration this one depends on, resolved, or `None` at the root."""
        in_app = migration.in_app(app_label)
        if not in_app:
            return None
        if len(in_app) > 1:
            raise _refuse(
                f"{migration.name} has {len(in_app)} dependencies within {app_label}; a chain "
                "this command grafts is linear. Fold this app by hand."
            )
        named = in_app[0].name
        assert named is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
        return self._resolve(app_label, files, by_stem, named)

    def _walk_back(
        self,
        app_label: str,
        files: dict[str, _MigrationFile],
        by_stem: dict[str, list[str]],
        leaf: str,
    ) -> list[str]:
        """Every migration reachable from `leaf` by in-app dependencies, leaf first."""
        chain: list[str] = []
        seen: set[str] = set()
        current: str | None = leaf
        while current is not None:
            if current in seen:
                raise _refuse(
                    f"{app_label}'s migrations loop at {current} — a cycle in the in-app "
                    "dependency chain. Nothing was moved."
                )
            seen.add(current)
            chain.append(current)
            if len(chain) > len(files) + _CYCLE_GUARD_SLACK:  # pragma: no cover - belt
                raise _refuse(f"{app_label}'s migration chain does not terminate.")
            current = self._parent_of(app_label, files, by_stem, files[current])
        return chain

    def _arriving_chain(
        self,
        app_label: str,
        files: dict[str, _MigrationFile],
        by_stem: dict[str, list[str]],
        arriving_leaf: str,
        product_chain: set[str],
    ) -> tuple[list[_MigrationFile], str | None]:
        """The arriving migrations oldest-first, and the ancestor they hang off.

        "Arriving" is defined by reachability, not by numbering: everything the
        arriving leaf depends on that the product's own history does NOT already
        hold. That is what makes the command idempotent in the useful sense — a
        chain already grafted has nothing outside the product's history left,
        and the walk stops at once.
        """
        arriving: list[_MigrationFile] = []
        current: str | None = arriving_leaf
        ancestor: str | None = None
        seen: set[str] = set()
        while current is not None:
            if current in product_chain:
                ancestor = current
                break
            if current in seen:
                raise _refuse(
                    f"{app_label}'s migrations loop at {current} — a cycle in the in-app "
                    "dependency chain. Nothing was moved."
                )
            seen.add(current)
            arriving.append(files[current])
            current = self._parent_of(app_label, files, by_stem, files[current])
        if not arriving:
            raise _refuse(
                f"{arriving_leaf} is already in {app_label}'s own history — there is no arriving "
                "chain to graft. Resolve max_migration.txt by hand."
            )
        arriving.reverse()
        return arriving, ancestor

    # -- the doing -------------------------------------------------------

    def _apply(self, plan: _Plan) -> None:
        """Rewrite, then rename, then the marker file — in that order.

        Contents first so a crash leaves files whose names still say what they
        were; the two-phase rename is for the case where a new name is an old
        name of a migration further down the same chain, which a one-pass
        rename would clobber.
        """
        for graft in plan.grafts:
            graft.migration.path.write_text(self._rewritten(plan.app_label, graft))

        staged: list[tuple[Path, Path]] = []
        for graft in plan.grafts:
            parked = graft.migration.path.with_name(f"~{graft.new_name}.py")
            graft.migration.path.rename(parked)
            staged.append((parked, plan.directory / f"{graft.new_name}.py"))
        for parked, final in staged:
            parked.rename(final)

        (plan.directory / "max_migration.txt").write_text(f"{plan.grafts[-1].new_name}\n")

    def _rewritten(self, app_label: str, graft: _Graft) -> str:
        """The migration's text with its one in-app dependency repointed.

        The byte-slice around the `dependencies` node is `rebase_migration`'s
        technique, held deliberately: it rewrites the dependency list and leaves
        every other byte of somebody else's generated file — imports, comments,
        operations, formatting — exactly as it was, which is what makes the
        graft reviewable as a diff.
        """
        migration = graft.migration
        node = migration.dependencies_node
        lines = migration.content.splitlines(keepends=True)
        start = sum(len(line) for line in lines[: node.lineno - 1]) + node.col_offset
        assert node.end_lineno is not None and node.end_col_offset is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
        end = sum(len(line) for line in lines[: node.end_lineno - 1]) + node.end_col_offset

        rebuilt: ast.Tuple | ast.List = (
            ast.Tuple(elts=[]) if isinstance(node, ast.Tuple) else ast.List(elts=[])
        )
        for dependency in migration.dependencies:
            if dependency.app_label == app_label:
                rebuilt.elts.append(
                    ast.Tuple(elts=[ast.Constant(app_label), ast.Constant(graft.new_parent)])
                )
            else:
                rebuilt.elts.append(dependency.node)
        return migration.content[:start] + ast.unparse(rebuilt) + migration.content[end:]
