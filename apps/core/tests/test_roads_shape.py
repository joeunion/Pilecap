# census: cross-app the tree's top level, linked into a scratch tree for the drawn plans
"""`manage.py roads shape`: the scaffold's own dry run, each file's rules, and the `next:` line."""

# does-not-cover: every rule that judges a path — only those whose canaries plant one like it.

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands.scaffold import newapp_stubs
from apps.core.scaffold.copier import from_golden, index
from apps.core.scaffold.shapes import ADOPT, SHAPES, adopt_verbs
from apps.core.tests.platform_tree import platform_tree
from apps.core.tests.tree_census import source_text

ROOT = Path(__file__).resolve().parents[3]
#: A product app and noun no tree holds: plural, not the noun's own plural (rule 32), unregistered.
LABEL, NOUN = "zzzk9s", "Gear"
WOULD = "would "
SHARED = ("apps/core/api/frozen_families.py", "quality/budgets.yaml", "apps/conftest_local.py")


def _cases() -> list[tuple[str, ...]]:
    """One argv per registered shape (one per verb for `adopt`), read off the registry."""
    cases: list[tuple[str, ...]] = []
    for shape in SHAPES:
        if shape.key == ADOPT:
            cases.extend((ADOPT, verb, LABEL, NOUN) for verb in adopt_verbs(ROOT))
        else:
            cases.append((shape.key, LABEL, NOUN))
    return cases


def _run(command: str, *argv: str) -> tuple[int, str, str]:
    """A command's exit status, standard output and refusal text."""
    out, err = io.StringIO(), io.StringIO()
    try:
        call_command(command, *argv, stdout=out, stderr=err)
    except CommandError as refused:
        return refused.returncode, out.getvalue(), str(refused)
    except SystemExit as stopped:
        return int(stopped.code or 0), out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


def _dirt() -> str:
    """The uncommitted paths a scaffold could write: a dry run leaves them as they were."""
    return subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `git`, no shell
        ["git", "status", "--porcelain", "--untracked-files=all", "--", f"apps/{LABEL}", *SHARED],  # noqa: S607 — `git` resolved on PATH, as the gate's own legs run it
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.mark.parametrize("argv", _cases(), ids=lambda argv: "-".join(argv[:2]))
def test_roads_shape_is_the_scaffolds_dry_run_both_ways(argv: tuple[str, ...]) -> None:
    before = _dirt()
    scaffolded = _run("scaffold", *argv, "--dry-run")
    shaped = _run("roads", "shape", *argv)
    assert _dirt() == before
    status, out, refused = scaffolded
    assert shaped[0] == status, (shaped, scaffolded)
    if status:
        assert status == 2 and refused, scaffolded
        assert refused in shaped[2], (shaped, scaffolded)
        return
    planned = [line for line in out.splitlines() if line.startswith(WOULD)]
    assert planned and planned == out.splitlines()
    assert [line for line in shaped[1].splitlines() if line.startswith(WOULD)] == planned
    assert shaped[1].splitlines()[-1] == f"next: uv run python manage.py scaffold {' '.join(argv)}"


def test_each_planned_module_names_the_rules_that_plant_one_like_it(
    tmp_path: Path, settings: Any
) -> None:
    settings.BASE_DIR = platform_tree(tmp_path, None)
    status, out, _ = _run("roads", "shape", "noun", LABEL, NOUN)
    assert status == 0
    lines = out.splitlines()
    services = lines.index(next(line for line in lines if f"apps/{LABEL}/services.py:" in line))
    assert lines[services + 1].startswith("    answers to: rules ")
    named = lines[services + 1].removeprefix("    answers to: rules ").split()
    assert {"8", "13"} <= set(named), named


def test_a_pending_shape_prints_the_pending_line_and_exits_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.core.management.commands import scaffold

    drawn = index(ROOT)
    # Every shape is drawn on this tree, so one golden is taken away to make the pending answer.
    pending = next(s for s in SHAPES if s.key not in (ADOPT, "noun") and s.golden in drawn)
    rest = {key: golden for key, golden in drawn.items() if key != pending.golden}
    monkeypatch.setattr(scaffold, "index", lambda root: rest)
    status, _, refused = _run("roads", "shape", pending.key, LABEL, NOUN)
    assert status == 2
    assert "golden pending" in refused or "arm is not built" in refused, refused


def test_shape_with_no_shape_names_the_registry() -> None:
    with pytest.raises(CommandError) as refused:
        call_command("scaffold", "--dry-run", stdout=io.StringIO())
    assert refused.value.returncode == 2
    status, _, said = _run("roads", "shape")
    assert status == 2 and "--list" in said, said


#: One drawn path per additive shape: each lands on the scratch noun, so the census compares plans.
DRAWN = (
    ("field", LABEL, NOUN, "color:str?"),
    ("filter", LABEL, NOUN, "notes=exact"),
    ("ordering", LABEL, NOUN, "notes"),
    ("verb", LABEL, NOUN, "close"),
    ("event", LABEL, NOUN, "close"),
    ("enum", LABEL, NOUN, "stage", "OPEN,PACKED,SHUT"),
    ("migration", LABEL, "fixup", "--data"),
    ("stat", LABEL, NOUN, "total"),
    ("policy", LABEL, f"{NOUN}Policy"),
    ("workflow", LABEL, NOUN, "review"),
    ("search", LABEL, NOUN, "name,notes"),
    ("child", LABEL, NOUN, "Visit"),
    ("webhook-in", LABEL, NOUN, "acme"),
)


@pytest.fixture
def scratch_noun(tmp_path: Path, settings: Any) -> Path:
    """This tree through links, with `newapp` and `scaffold noun` of the scratch noun under it."""
    root = tmp_path / "tree"
    (root / "apps").mkdir(parents=True)
    for child in ROOT.iterdir():
        if child.name != "apps":
            (root / child.name).symlink_to(child)
    for child in (ROOT / "apps").iterdir():
        (root / "apps" / child.name).symlink_to(child)
    for rel, text in from_golden(ROOT, index(ROOT)["noun"], LABEL, NOUN).files.items():
        (root / "apps" / LABEL / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / "apps" / LABEL / rel).write_text(text)
    (root / "apps" / LABEL / "migrations").mkdir(exist_ok=True)
    (root / "apps" / LABEL / "migrations" / "__init__.py").write_text("")
    stub = newapp_stubs(LABEL)["apps.py"]
    if not (root / "apps" / LABEL / "apps.py").is_file():
        (root / "apps" / LABEL / "apps.py").write_text(stub)
    settings.BASE_DIR = root
    return root


@pytest.mark.parametrize("argv", DRAWN, ids=lambda argv: argv[0])
def test_an_additive_shape_plans_the_same_drawn_path_both_ways(
    argv: tuple[str, ...], scratch_noun: Path
) -> None:
    before = {p: source_text(p) for p in (scratch_noun / "apps" / LABEL).rglob("*.py")}
    scaffolded = _run("scaffold", *argv, "--dry-run")
    shaped = _run("roads", "shape", *argv)
    after = {p: source_text(p) for p in (scratch_noun / "apps" / LABEL).rglob("*.py")}
    assert scaffolded[0] == shaped[0] == 0, (scaffolded, shaped)
    planned = [line for line in scaffolded[1].splitlines() if line.startswith(WOULD)]
    assert planned and [x for x in shaped[1].splitlines() if x.startswith(WOULD)] == planned
    assert after == before


def test_a_scheduled_workflow_is_refused_both_ways_with_one_sentence(scratch_noun: Path) -> None:
    argv = ("workflow", LABEL, NOUN, "review", "--schedule", "6h")
    scaffolded = _run("scaffold", *argv, "--dry-run")
    shaped = _run("roads", "shape", *argv)
    assert scaffolded[0] == shaped[0] == 2, (scaffolded, shaped)
    assert "a schedule starts a sweep with no row and no tenant" in scaffolded[2]
    assert scaffolded[2] in shaped[2], (scaffolded, shaped)


def test_a_second_provider_seam_is_refused_where_one_is_written(scratch_noun: Path) -> None:
    (scratch_noun / "apps" / LABEL / "integrations.py").write_text('"""Somebody\'s."""\n')
    status, out, said = _run("scaffold", "webhook-in", LABEL, NOUN, "acme", "--dry-run")
    assert (status, out) == (2, ""), (status, out, said)
    assert "already has an `integrations.py`" in said, said


def test_roads_takes_every_flag_the_scaffold_does_but_the_four_it_holds_back() -> None:
    from apps.core.management.commands.roads import UNFORWARDED
    from apps.core.management.commands.roads import Command as Roads
    from apps.core.management.commands.scaffold import Command as Scaffold

    arm = Scaffold().create_parser("manage.py", "scaffold")._option_string_actions
    roads = Roads().create_parser("manage.py", "roads")._option_string_actions
    assert {"--data", "--schedule", "--role", "--permissions", "--families"} <= (
        set(arm) - UNFORWARDED
    )
    assert set(arm) - UNFORWARDED <= set(roads) and UNFORWARDED & set(roads) == {"--remove"}


def test_a_removal_is_refused_with_its_road_and_nothing_is_removed(scratch_noun: Path) -> None:
    before = {p: source_text(p) for p in (scratch_noun / "apps" / LABEL).rglob("*.py")}
    status, out, said = _run("roads", "shape", "noun", LABEL, NOUN, "--remove")
    after = {p: source_text(p) for p in (scratch_noun / "apps" / LABEL).rglob("*.py")}
    assert (status, out) == (2, "") and after == before
    assert f"`scaffold noun {LABEL} {NOUN} --remove --dry-run`" in said
