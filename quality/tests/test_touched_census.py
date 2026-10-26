"""`scope.touched` and its census: no gate test module goes unselected."""

# census: cross-app population=quality/,scripts/test_impact.json what a selection reads
# does-not-cover: a read joined to a name other than ROOT, HOME or REPO_ROOT, or a subprocess argv.
# does-not-cover: the map's own rows — the acceptance run writes them; this reads what it wrote.

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import scope


def _git(root: Path, *argv: str) -> None:
    done = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(argv)}: {done.stderr}"


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)


def _census_module() -> str:
    return f'"""A planted census."""\n\n{scope.CENSUS_MARKER} it reads every app\n'


def _marked_module(*globs: str) -> str:
    args = ", ".join(f'"{g}"' for g in globs)
    head = '"""A planted marked module."""\n\nimport pytest\n\n'
    return f"{head}pytestmark = pytest.mark.drives({args})\n"


@pytest.fixture
def gate_world(scratch_repo: Callable[..., Path]) -> Path:
    """A committed tree: one census module, one marked module, one mapped module, their subjects."""
    root = scratch_repo("touched", "touched census")
    _write(
        root,
        {
            "apps/mid/services.py": "base\n",
            "scripts/thing.sh": "base\n",
            "deploy/stage.sh": "base\n",
            "quality/djb/thing.py": "base\n",
            "quality/tests/conftest.py": "base\n",
            "quality/tests/test_planted_census.py": _census_module(),
            "quality/tests/test_planted_marked.py": _marked_module("scripts/thing.sh", "deploy/**"),
            "quality/tests/test_planted_mapped.py": '"""A planted mapped module."""\n',
            scope.MAP_PATH: json.dumps(
                {
                    "generated": {},
                    "tests": {
                        "quality/tests/test_planted_mapped.py::test_a": ["quality/djb/thing.py"]
                    },
                    "unmapped": {},
                }
            ),
        },
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def test_a_census_module_joins_every_own_scope(gate_world: Path) -> None:
    assert scope.touched(gate_world, ["apps/mid/services.py"]) == [
        "quality/tests/test_planted_census.py"
    ]


def test_a_drives_marker_selects_its_module_by_each_glob(gate_world: Path) -> None:
    for changed in ("scripts/thing.sh", "deploy/stage.sh"):
        assert "quality/tests/test_planted_marked.py" in scope.touched(gate_world, [changed])
    assert "quality/tests/test_planted_marked.py" not in scope.touched(
        gate_world, ["apps/mid/services.py"]
    )


def test_a_map_row_selects_the_module_that_executed_the_change(gate_world: Path) -> None:
    assert scope.touched(gate_world, ["quality/djb/thing.py"]) == [
        "quality/tests/test_planted_census.py",
        "quality/tests/test_planted_mapped.py",
    ]


def test_a_module_selects_itself_when_its_own_bytes_change(gate_world: Path) -> None:
    assert "quality/tests/test_planted_mapped.py" in scope.touched(
        gate_world, ["quality/tests/test_planted_mapped.py"]
    )


def test_a_change_to_the_shared_harness_selects_every_module(gate_world: Path) -> None:
    assert scope.touched(gate_world, ["quality/tests/conftest.py"]) == scope.gate_test_modules(
        gate_world
    )


def test_every_registered_drive_declares_what_it_drives(gate_world: Path) -> None:
    assert scope.census(gate_world) == []


def test_a_module_with_no_source_is_exit_2_with_the_sentence(
    gate_world: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(gate_world, {"quality/tests/test_planted_orphan.py": '"""Nobody selects me."""\n'})
    _git(gate_world, "add", "-A")
    with pytest.raises(SystemExit) as raised:
        scope.main(["--root", str(gate_world), "--census"])
    out = capsys.readouterr()
    assert raised.value.code == 2
    assert (
        f"quality/tests/test_planted_orphan.py: no impact-map entry, no drives marker and no"
        f" census line — {scope.UNSELECTABLE}" in out.out
    )
    assert "1 gate test module finding(s) above" in out.err


def test_a_drives_glob_matching_nothing_is_exit_2_naming_it(
    gate_world: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(
        gate_world, {"quality/tests/test_planted_marked.py": _marked_module("deploy/nothing/**")}
    )
    with pytest.raises(SystemExit) as raised:
        scope.main(["--root", str(gate_world), "--census"])
    assert raised.value.code == 2
    assert (
        "quality/tests/test_planted_marked.py: its drives glob deploy/nothing/** matches no"
        " tracked file" in capsys.readouterr().out
    )


def test_a_body_spelling_three_undeclared_paths_is_named_whole_and_refused_at_the_hook(
    gate_world: Path,
) -> None:
    body = (
        _marked_module("scripts/thing.sh")
        + "\nROOT = None\n\n\ndef test_reads() -> None:\n"
        + '    print(ROOT / "deploy/stage.sh", ROOT / "apps/mid/services.py",'
        + ' ROOT / "quality/djb/thing.py")\n'
    )
    _write(gate_world, {"quality/tests/test_planted_marked.py": body})
    assert scope.census(gate_world) == [
        "quality/tests/test_planted_marked.py: its body spells deploy/stage.sh,"
        " apps/mid/services.py and quality/djb/thing.py and its drives marker covers none of"
        " them — declare each, or the module is never selected when it changes"
    ]
    _write(
        gate_world,
        {
            "quality/tests/test_planted_marked.py": body.replace(
                '"scripts/thing.sh"',
                '"scripts/thing.sh", "deploy/**", "apps/mid/services.py", "quality/djb/thing.py"',
                1,
            )
        },
    )
    assert scope.census(gate_world) == []


def test_a_non_literal_drives_argument_could_not_look(gate_world: Path) -> None:
    _write(
        gate_world,
        {
            "quality/tests/test_planted_marked.py": (
                "import pytest\n\nGLOB = 'deploy/**'\npytestmark = pytest.mark.drives(GLOB)\n"
            )
        },
    )
    with pytest.raises(CouldNotLook, match="non-literal argument"):
        scope.touched(gate_world, ["deploy/stage.sh"])
