"""The prose bound: one measure per language, a ceiling per root, the paste line on a breach."""

# does-not-cover: whether a WHY paragraph cut to pass the bound mattered — read the worst three.

from __future__ import annotations

import re
from pathlib import Path

import pytest

from quality.djb.legs.gate_tests import WORLDS_MYPY
from quality.engine.prose import (
    PROSE_ROOTS,
    WORLDS,
    prose_and_code,
    prose_census,
    prose_verdicts,
)

pytestmark = pytest.mark.drives(
    "quality/engine/prose.py", "quality/rules.yaml", "quality/djb/legs/gate_tests.py"
)

SHELL = "#!/usr/bin/env bash\n# the contract\n\nset -eu\necho one\necho two\n"
PYTHON = (
    '"""The module."""\n\n# a comment line\nX = 1  # a trailing comment is code\n\n\n'
    'def f():\n    """One\n    two."""\n    return X\n'
)


def world(root: Path) -> Path:
    """A tree with one file under every recorded root."""
    for key, sub in PROSE_ROOTS.items():
        (root / sub).mkdir(parents=True, exist_ok=True)
        if key in ("scripts", "deploy"):
            (root / sub / "run.sh").write_text(SHELL)
        else:
            (root / sub / "mod.py").write_text(PYTHON)
    return root


def recorded(root: Path) -> dict[str, int]:
    """The numbers this tree measures, as a human would paste them."""
    return {key: ratio for key, (ratio, _worst) in prose_census(root).items()}


def test_shell_counts_comment_and_blank_lines_as_prose(tmp_path: Path) -> None:
    path = tmp_path / "x.sh"
    path.write_text(SHELL)
    assert prose_and_code(path) == (3, 3)


def test_python_counts_docstring_and_comment_rows_as_prose(tmp_path: Path) -> None:
    path = tmp_path / "x.py"
    path.write_text(PYTHON)
    assert prose_and_code(path) == (4, 3)


def test_a_two_hundred_line_comment_under_scripts_is_red_then_green(tmp_path: Path) -> None:
    root = world(tmp_path)
    record = recorded(root)
    plant = root / "scripts" / "planted.sh"
    plant.write_text("".join(f"# narration line {n}\n" for n in range(200)) + "echo x\n")
    lines, problems, _notes = prose_verdicts(record, root)
    assert len(problems) == 1 and problems[0].startswith(
        "prose: prose over code under scripts/ (thousandths) is at"
    )
    assert problems[0].endswith(f"\n  scripts: {prose_census(root)['scripts'][0]}")
    assert "scripts/planted.sh" in lines[0] and lines[0].startswith("prose: scripts ")
    plant.unlink()
    assert prose_verdicts(record, root)[1] == []


@pytest.mark.parametrize("world_dir", WORLDS)
def test_a_prose_heavy_file_in_a_fixture_world_leaves_the_bound_unmoved(
    tmp_path: Path, world_dir: str
) -> None:
    root = world(tmp_path)
    record = recorded(root)
    plant = root / world_dir / "models.py"
    plant.parent.mkdir(parents=True)
    plant.write_text("".join(f"# narration line {n}\n" for n in range(200)) + "X = 1\n")
    assert recorded(root) == record
    assert prose_verdicts(record, root)[1] == []
    outside = root / "quality/tests/fixtures/elsewhere/models.py"
    outside.parent.mkdir(parents=True)
    outside.write_text(plant.read_text())
    assert recorded(root)["quality_tests"] > record["quality_tests"], "a non-world still counts"


def test_the_worlds_are_the_set_mypy_excludes() -> None:
    assert all(re.match(WORLDS_MYPY, f"{one}x.py") for one in WORLDS)
    names = re.search(r"\(([^)]*)\)", WORLDS_MYPY)
    assert names and sorted(names.group(1).split("|")) == sorted(
        one.rstrip("/").rsplit("/", 1)[1] for one in WORLDS
    )


def test_an_unrecorded_root_is_a_finding_with_its_paste_line(tmp_path: Path) -> None:
    root = world(tmp_path)
    record = recorded(root)
    del record["deploy"]
    problems = prose_verdicts(record, root)[1]
    assert problems == [
        f"prose: deploy has no recorded bound (measured {record_of(root, 'deploy')}) — a root "
        "nobody recorded is unread, never clean. The line to paste under quality/rules.yaml "
        f"`prose: prose_over_code:`:\n  deploy: {prose_census(root)['deploy'][0]}"
    ]


def test_a_root_under_its_number_is_a_room_note_never_a_red(tmp_path: Path) -> None:
    root = world(tmp_path)
    record = {key: n + 100 for key, n in recorded(root).items()}
    _lines, problems, notes = prose_verdicts(record, root)
    assert problems == [] and len(notes) == len(PROSE_ROOTS)


def test_the_tree_is_at_its_recorded_bound() -> None:
    assert prose_verdicts()[1] == []


def record_of(root: Path, key: str) -> str:
    """One root's measured ratio as the census prints it."""
    return f"{prose_census(root)[key][0] / 1000:.3f}"
