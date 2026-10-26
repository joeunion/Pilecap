"""`manage.py fold_migrations` over a two-act scratch migration graph.

**The story, which is the one that really happened.** A product on v2.1.0 added
its own migrations to a template app. The v2.1.1 tag arrives with a chain of its
own from the same ancestor, `git merge` lands both in one directory and
`max_migration.txt` holds a conflict. Act one is that fold. Act two is the NEXT
release, whose migration depends on an ancestor act one renumbered — a
dependency that names a file which no longer exists under that name, and the
half `rebase_migration` cannot reach at all (ADR core-28).

**The graph is scratch and it is never the real one.** Every act is built in the
test's own `tmp_path`, as an importable package, and reached through
`MIGRATION_MODULES` — so `MigrationDetails` resolves the app's migrations
directory to a directory this test created and will delete, and
`apps/core/migrations/` is neither read nor written. `core` is the carrier label
only: it is the app that is never optional, and the recorder rows for it are
cleared explicitly at the top of each graph so `migration_applied` answers about
a state this test set rather than one the test database happened to have.

**The properties are asserted through Django's own graph**, not through the
command's parser: a `MigrationGraph` built from the files on disk, then
`validate_consistency()` (a dependency naming nothing is `NodeNotFoundError`
here, exactly as it would be at `migrate`) and `leaf_nodes()` (one leaf per app
is the whole invariant `django-linear-migrations` exists to keep). Asserting the
fold with the fold's own reader would only prove the reader agrees with itself.

**DEVIATION, RECORDED.** The brief asks for `makemigrations --check` clean and
`showmigrations` listing one leaf per app. Neither is reachable over a scratch
graph: both build the WHOLE project's migration state, and a fabricated chain
for one app has no relationship to that app's real models or to the seven
cross-app dependencies other apps already write against its real migration
names. What those two commands would be measuring here — no dangling dependency,
exactly one leaf, and `max_migration.txt` naming it — is measured directly, over
the same files, by `_graph()` and dlm's own grammar. Said out loud rather than
quietly substituted.
"""

from __future__ import annotations

import ast
import importlib
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml
from django.conf import settings as django_settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.migrations.exceptions import NodeNotFoundError
from django.db.migrations.graph import MigrationGraph
from django.db.migrations.recorder import MigrationRecorder
from django_linear_migrations.management.commands import rebase_migration

from apps.core.management.commands import fold_migrations

pytestmark = pytest.mark.django_db

#: The app label the scratch graph borrows. It is a LABEL and nothing else —
#: every file under it is fabricated by this module — and it is `core` because
#: `core` is the one app a product can never switch off, so the test cannot be
#: deselected into silence by an optional-app configuration.
CARRIER = "core"

ROOT = Path(django_settings.BASE_DIR)
RULES_PATH = ROOT / "quality" / "rules.yaml"


def _migration(dependencies: str, *, header: str = "") -> str:
    return (
        "from django.db import migrations\n"
        f"{header}"
        "\n\nclass Migration(migrations.Migration):\n"
        f"    dependencies = {dependencies}\n"
        "\n    operations = []\n"
    )


#: ACT ONE. `0007_...` is the shared ancestor both sides were cut from;
#: `0008_acme`/`0009_acme2` are the product's own; the other three are the
#: template chain the merge brought in. `0008_identity_branding` carries a
#: cross-app tuple and a `swappable_dependency(...)` call precisely so the graft
#: can be shown to leave both alone.
ACT_ONE: dict[str, str] = {
    "0007_tenant_leading_recency_composite": _migration("[]"),
    "0008_acme": _migration('[("core", "0007_tenant_leading_recency_composite")]'),
    "0009_acme2": _migration('[("core", "0008_acme")]'),
    "0008_identity_branding": _migration(
        "[\n"
        '        ("core", "0007_tenant_leading_recency_composite"),\n'
        '        ("accounts", "0001_initial"),\n'
        "        migrations.swappable_dependency(settings.AUTH_USER_MODEL),\n"
        "    ]",
        header="from django.conf import settings\n",
    ),
    "0009_ssodomain_verified_at": _migration('[("core", "0008_identity_branding")]'),
    "0010_default_role_is_a_key": _migration('[("core", "0009_ssodomain_verified_at")]'),
}

#: The conflict `git merge <tag>` leaves: HEAD is the product, the bottom is the
#: arriving template leaf. The command reads it positionally — see
#: `test_the_direction_is_positional_even_mid_merge`.
ACT_ONE_CONFLICT = "<<<<<<< HEAD\n0009_acme2\n=======\n0010_default_role_is_a_key\n>>>>>>> v2.1.1\n"


def _build(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
    files: dict[str, str],
    max_migration: str,
) -> Path:
    """Write a scratch migrations package and point the carrier app at it."""
    package = f"foldscratch_{uuid4().hex}"
    directory = tmp_path / package / "migrations"
    directory.mkdir(parents=True)
    (tmp_path / package / "__init__.py").write_text("")
    (directory / "__init__.py").write_text("")
    for name, source in files.items():
        (directory / f"{name}.py").write_text(source)
    (directory / "max_migration.txt").write_text(max_migration)
    monkeypatch.syspath_prepend(str(tmp_path))
    settings.MIGRATION_MODULES = {CARRIER: f"{package}.migrations"}
    # The command asks the LOCAL recorder whether an arriving migration has
    # already run. The scratch names are not the carrier's real ones, but a
    # census that depended on that coincidence would be a census nobody could
    # read: the state is set here, explicitly, and rolled back with the test.
    MigrationRecorder.Migration.objects.filter(app=CARRIER).delete()
    return directory


def _names(directory: Path) -> list[str]:
    return sorted(path.stem for path in directory.glob("[0-9]*.py"))


def _dependencies(path: Path) -> list[tuple[str, str]]:
    """Every literal `(app, name)` tuple in the file's `dependencies`.

    A second, independent reader — the command's own parser is the thing under
    test, and a test that read the tree through it could only ever prove the
    parser self-consistent.
    """
    found: list[tuple[str, str]] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "dependencies" for t in node.targets):
            continue
        for element in getattr(node.value, "elts", []):
            if not isinstance(element, (ast.Tuple, ast.List)) or len(element.elts) != 2:
                continue
            first, second = element.elts
            if isinstance(first, ast.Constant) and isinstance(second, ast.Constant):
                found.append((str(first.value), str(second.value)))
    return found


def _graph(directory: Path) -> MigrationGraph:
    """Django's own graph over the app's own files, dummy nodes and all."""
    graph = MigrationGraph()
    names = _names(directory)
    for name in names:
        graph.add_node((CARRIER, name), None)
    for name in names:
        for app_label, dependency in _dependencies(directory / f"{name}.py"):
            if app_label == CARRIER:
                graph.add_dependency(
                    None, (CARRIER, name), (CARRIER, dependency), skip_validation=True
                )
    return graph


def _one_leaf(directory: Path) -> str:
    graph = _graph(directory)
    graph.validate_consistency()
    leaves = graph.leaf_nodes(CARRIER)
    assert len(leaves) == 1, f"expected one leaf, got {sorted(name for _, name in leaves)}"
    return str(leaves[0][1])


# --- act one: the arriving chain is grafted onto the product's leaf ----------


def test_the_arriving_chain_is_renumbered_past_the_products_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)

    call_command("fold_migrations", CARRIER)

    assert _names(directory) == [
        "0007_tenant_leading_recency_composite",
        "0008_acme",
        "0009_acme2",
        "0010_identity_branding",
        "0011_ssodomain_verified_at",
        "0012_default_role_is_a_key",
    ]
    assert (directory / "max_migration.txt").read_text() == "0012_default_role_is_a_key\n"
    assert _one_leaf(directory) == "0012_default_role_is_a_key"


def test_each_grafted_migration_depends_on_the_one_before_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)

    call_command("fold_migrations", CARRIER)

    in_app = {
        name: [dep for app, dep in _dependencies(directory / f"{name}.py") if app == CARRIER]
        for name in _names(directory)
    }
    assert in_app["0010_identity_branding"] == ["0009_acme2"]
    assert in_app["0011_ssodomain_verified_at"] == ["0010_identity_branding"]
    assert in_app["0012_default_role_is_a_key"] == ["0011_ssodomain_verified_at"]
    # The product's own two are untouched.
    assert in_app["0008_acme"] == ["0007_tenant_leading_recency_composite"]
    assert in_app["0009_acme2"] == ["0008_acme"]


def test_a_cross_app_dependency_and_a_swappable_one_survive_the_graft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)

    call_command("fold_migrations", CARRIER)

    grafted = (directory / "0010_identity_branding.py").read_text()
    assert ("accounts", "0001_initial") in _dependencies(directory / "0010_identity_branding.py")
    assert "migrations.swappable_dependency(settings.AUTH_USER_MODEL)" in grafted
    assert "from django.conf import settings" in grafted
    assert "operations = []" in grafted


# --- act two: an ancestor act one renamed, resolved by its stem --------------


def test_a_renamed_ancestor_is_resolved_by_its_stem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    """The next release depends on `0010_default_role_is_a_key`; act one made it `0012_`."""
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)
    call_command("fold_migrations", CARRIER)

    # The v2.1.2 tag arrives. Its migration is Django-native and carries the
    # TEMPLATE's numbering, which this tree renumbered a release ago.
    (directory / "0011_a_later_thing.py").write_text(
        _migration('[("core", "0010_default_role_is_a_key")]')
    )
    (directory / "max_migration.txt").write_text(
        "<<<<<<< HEAD\n0012_default_role_is_a_key\n=======\n0011_a_later_thing\n>>>>>>> v2.1.2\n"
    )
    # The dangling dependency is real: Django cannot build this graph.
    with pytest.raises(NodeNotFoundError):
        _graph(directory).validate_consistency()

    call_command("fold_migrations", CARRIER)

    assert "0013_a_later_thing" in _names(directory)
    assert _dependencies(directory / "0013_a_later_thing.py") == [
        ("core", "0012_default_role_is_a_key")
    ]
    assert (directory / "max_migration.txt").read_text() == "0013_a_later_thing\n"
    assert _one_leaf(directory) == "0013_a_later_thing"


# --- the plan, printed and not applied ---------------------------------------


def test_dry_run_prints_the_plan_and_moves_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    settings: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)
    before = _names(directory)

    call_command("fold_migrations", CARRIER, "--dry-run")

    # The plan is column-aligned for a human; the assertion is about the words.
    printed = "\n".join(" ".join(line.split()) for line in capsys.readouterr().out.splitlines())
    assert "0008_identity_branding -> 0010_identity_branding" in printed
    assert '0010_identity_branding dependency ("core", "0009_acme2")' in printed
    assert "0010_default_role_is_a_key -> 0012_default_role_is_a_key" in printed
    assert "max_migration.txt -> 0012_default_role_is_a_key" in printed
    assert "dry run — nothing was moved." in printed
    assert _names(directory) == before
    assert (directory / "max_migration.txt").read_text() == ACT_ONE_CONFLICT


# --- the direction, which is the opposite of rebase_migration's --------------


def test_the_direction_is_positional_even_mid_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    """HEAD is the product whether the working tree is mid-merge or mid-rebase.

    `rebase_migration` swaps the pair during a merge, because for it a merge
    means main arrived and YOUR migration is the one to move. The fold is the
    other direction, so the swap is undone — and the visible consequence is that
    the outcome is identical either way.

    BOTH predicates are patched, and that is the point of the test as much as
    the outcome is: `find_migration_names` calls the library module's own
    `is_merge_in_progress` to decide whether to swap, and the command calls the
    name it imported to decide whether to swap back. Patching one is a fold in
    the wrong direction — which is what this test caught the first time it ran.
    """
    monkeypatch.setattr(rebase_migration, "is_merge_in_progress", lambda: True)
    monkeypatch.setattr(fold_migrations, "is_merge_in_progress", lambda: True)
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)

    call_command("fold_migrations", CARRIER)

    assert (directory / "max_migration.txt").read_text() == "0012_default_role_is_a_key\n"
    assert _one_leaf(directory) == "0012_default_role_is_a_key"


# --- and a REBASE is refused, because under one HEAD is the upstream ---------


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - a scratch repo this test just created
        ["git", *args],  # noqa: S607 — `git` resolved on PATH, as the gate's own legs run it
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
    )


def _scratch_repo(tmp_path: Path, *, mid_rebase: bool) -> Path:
    """A real git repository, optionally stopped in a real `git rebase`.

    Not a fake and not a monkeypatched predicate: the whole finding is that
    `REBASE_HEAD` exists and `MERGE_HEAD` does not in a state neither this
    command nor the library had ever been run in, and the only instrument that
    can prove the guard sees it is git itself. The conflict is manufactured
    (one file, two edits, one shared parent) so the rebase stops deterministically.
    """
    repo = tmp_path / ("rebasing" if mid_rebase else "quiet")
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "rung@example.test")
    _git(repo, "config", "user.name", "fold scratch")
    (repo / "f.txt").write_text("base\n")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "base")
    if not mid_rebase:
        return repo
    _git(repo, "checkout", "-q", "-b", "product")
    (repo / "f.txt").write_text("product\n")
    _git(repo, "commit", "-qam", "product")
    _git(repo, "checkout", "-q", "main")
    (repo / "f.txt").write_text("template\n")
    _git(repo, "commit", "-qam", "template")
    _git(repo, "checkout", "-q", "product")
    _git(repo, "rebase", "main", check=False)  # stops on the conflict, by construction
    assert _git(repo, "rev-parse", "--verify", "REBASE_HEAD", check=False).returncode == 0, (
        "this git did not leave a REBASE_HEAD — the state the guard reads is not reproduced"
    )
    assert _git(repo, "rev-parse", "--verify", "MERGE_HEAD", check=False).returncode != 0, (
        "a rebase must not look like a merge, or the inversion this guard exists for is moot"
    )
    return repo


def test_a_rebase_is_refused_because_head_is_the_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    """Under a rebase the markers invert and the fold would renumber the PRODUCT.

    `git rebase` replays your commits onto the upstream, so while it is stopped
    HEAD is the template and there is no `MERGE_HEAD` — the library does not
    swap, this command does not swap back, and the two inversions cancel into a
    graft pointing the wrong way. The refusal is checked, and so is the tree:
    nothing is renamed, no dependency is rewritten, `max_migration.txt` still
    holds the conflict byte for byte.
    """
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)
    before = {name: (directory / f"{name}.py").read_text() for name in _names(directory)}
    monkeypatch.chdir(_scratch_repo(tmp_path, mid_rebase=True))

    refusal = _refusal(CARRIER)

    assert "under a rebase HEAD is the upstream" in str(refusal)
    assert _names(directory) == sorted(ACT_ONE)
    assert {name: (directory / f"{name}.py").read_text() for name in _names(directory)} == before
    assert (directory / "max_migration.txt").read_text() == ACT_ONE_CONFLICT


def test_a_repository_with_no_rebase_in_it_is_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    """The guard's other half: a quiet repository folds exactly as before.

    Same harness, same scratch repository code, one commit and no rebase — so a
    guard that had become "refuse whenever git answers at all" fails here rather
    than passing as caution.
    """
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)
    monkeypatch.chdir(_scratch_repo(tmp_path, mid_rebase=False))

    call_command("fold_migrations", CARRIER)

    assert (directory / "max_migration.txt").read_text() == "0012_default_role_is_a_key\n"
    assert _one_leaf(directory) == "0012_default_role_is_a_key"


# --- what rebase_migration does with the same conflict (the defect) ----------


def test_rebase_migration_leaves_the_rest_of_the_arriving_chain_hanging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    """The library's command moves ONE migration; the fold needs the chain.

    This is the reported defect as an assertion rather than a sentence: the
    same conflict, the same directory, the library's own command — and two
    leaves in one app, which is the state `django-linear-migrations` refuses
    everything downstream of.
    """
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)

    call_command("rebase_migration", CARRIER)

    leaves = sorted(name for _, name in _graph(directory).leaf_nodes(CARRIER))
    assert leaves == ["0009_ssodomain_verified_at", "0010_default_role_is_a_key"]


# --- the refusals ------------------------------------------------------------


def _refusal(*argv: str) -> CommandError:
    with pytest.raises(CommandError) as caught:
        call_command("fold_migrations", *argv)
    assert caught.value.returncode == 2, "a fold that could not be computed exits 2"
    return caught.value


def test_an_applied_arriving_migration_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, ACT_ONE_CONFLICT)
    MigrationRecorder.Migration.objects.create(app=CARRIER, name="0009_ssodomain_verified_at")

    refusal = _refusal(CARRIER)

    assert "0009_ssodomain_verified_at" in str(refusal)
    assert "applied to the local database" in str(refusal)
    assert _names(directory) == sorted(ACT_ONE)


def test_a_stem_that_resolves_to_nothing_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    files = dict(ACT_ONE)
    files["0010_default_role_is_a_key"] = _migration('[("core", "0009_a_stem_nobody_has")]')
    directory = _build(tmp_path, monkeypatch, settings, files, ACT_ONE_CONFLICT)

    refusal = _refusal(CARRIER)

    assert "0009_a_stem_nobody_has" in str(refusal)
    assert "a_stem_nobody_has" in str(refusal)
    assert _names(directory) == sorted(files)


def test_a_stem_that_resolves_to_two_migrations_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    files = dict(ACT_ONE)
    # A second migration sharing the ancestor's stem — the state
    # `test_migration_stems.py` keeps the template out of.
    files["0006_ssodomain_verified_at"] = _migration("[]")
    files["0010_default_role_is_a_key"] = _migration('[("core", "0099_ssodomain_verified_at")]')
    directory = _build(tmp_path, monkeypatch, settings, files, ACT_ONE_CONFLICT)

    refusal = _refusal(CARRIER)

    assert "0099_ssodomain_verified_at" in str(refusal)
    assert "matches 2 migrations" in str(refusal)
    assert "0006_ssodomain_verified_at" in str(refusal)
    assert _names(directory) == sorted(files)


def test_a_max_migration_with_no_conflict_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    directory = _build(tmp_path, monkeypatch, settings, ACT_ONE, "0010_default_role_is_a_key\n")

    refusal = _refusal(CARRIER)

    assert "does not hold a merge conflict" in str(refusal)
    assert _names(directory) == sorted(ACT_ONE)


def test_a_leaf_the_conflict_names_that_does_not_exist_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Any
) -> None:
    _build(
        tmp_path,
        monkeypatch,
        settings,
        ACT_ONE,
        "<<<<<<< HEAD\n0009_acme2\n=======\n0042_never_written\n>>>>>>> v2.1.1\n",
    )

    refusal = _refusal(CARRIER)

    assert "0042_never_written" in str(refusal)
    assert "no such migration exists" in str(refusal)


# --- rule 44: the library internals this command holds -----------------------


def test_the_linear_migrations_internals_we_hold_still_exist() -> None:
    """Rule 44's third half, instrumented here because its check cannot walk it.

    `quality/checks/rule_44.py::ninja_internals_census` validates the ninja and MCP
    halves off the installed packages; its two lists are named in code, so a
    third declared list is checked by nobody. Rule 44's own comment says this
    and names this test. What it does is the half a census can do on a
    declared-only seam: assert every name is still THERE, off the installed
    package, on the machine that ran `uv sync` — before `fold_migrations`
    discovers it by failing to import at the fold.
    """
    rules = yaml.safe_load(RULES_PATH.read_text())["rules"]
    rule = next(r for r in rules if str(r["id"]) == "44")
    entries = rule["scope"]["linear_migrations_internals_we_hold"]
    assert len(entries) >= 4, "the declared list emptied — rule 44 is validating nothing here"

    missing = []
    for entry in entries:
        module_name = str(entry["module"])
        attribute = str(entry["attribute"])
        try:
            module = importlib.import_module(module_name)
        except ImportError:  # pragma: no cover - the rename this exists to catch
            missing.append(f"{module_name} (module gone)")
            continue
        if not hasattr(module, attribute):
            missing.append(f"{module_name}.{attribute}")
    assert not missing, (
        "django-linear-migrations no longer defines what fold_migrations holds: "
        + ", ".join(missing)
        + " — follow the rename in apps/core/management/commands/fold_migrations.py and in "
        "rule 44's `linear_migrations_internals_we_hold` (quality/rules.yaml)"
    )


def test_the_command_really_imports_every_internal_it_declares() -> None:
    """The other direction: a declared name the command stopped holding.

    A census that lists a seam this tree does not hold is a claim about somebody
    else's tree — the same sentence `ninja_internals_census` prints for its own
    half, made true for this one.

    **Read off the IMPORT, never off the text.** A substring search over the
    source was the first form of this test and it was VACUOUS for the entry
    that matters most: `Command` is a substring of `CommandError`, which this
    module imports from Django, so the one entry naming the class the command
    SUBCLASSES would have stayed green with the whole `django_linear_migrations`
    import gone. The population is now the names actually imported FROM the
    declared module, which is the fact the entry is making.
    """
    rules = yaml.safe_load(RULES_PATH.read_text())["rules"]
    rule = next(r for r in rules if str(r["id"]) == "44")
    entries = rule["scope"]["linear_migrations_internals_we_hold"]

    imported: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(Path(fold_migrations.__file__).read_text())):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.setdefault(node.module, set()).update(alias.name for alias in node.names)

    unheld = [
        f"{entry['module']}.{entry['attribute']}"
        for entry in entries
        if str(entry["attribute"]) not in imported.get(str(entry["module"]), set())
    ]
    assert not unheld, (
        "rule 44 declares these linear-migrations internals held and "
        "fold_migrations.py no longer imports them: " + ", ".join(unheld)
    )


def test_the_import_census_is_not_satisfied_by_a_lookalike_name() -> None:
    """The falsifier for the test above, on the exact shape that fooled it.

    `Command` really is a substring of `CommandError`, and `CommandError` really
    is imported here — so a text search answers "held" for a module that imports
    nothing from the library at all. The reader is driven against that source
    directly rather than trusted to have stopped doing it.
    """
    source = "from django.core.management.base import CommandError\n"
    imported: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.setdefault(node.module, set()).update(alias.name for alias in node.names)

    assert "Command" in source, "the substring the old form matched on"
    assert "Command" not in imported.get(
        "django_linear_migrations.management.commands.rebase_migration", set()
    ), "the import census must not see a lookalike as the held class"
