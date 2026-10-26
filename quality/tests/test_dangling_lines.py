"""`dangling_paths.py`'s `path:line` arm: past the end, a blank line, a bare closer — refused."""

# does-not-cover: whether a non-blank cited line is the RIGHT line — presence and shape only.
# does-not-cover: the SHIP set's own population — `dangling_paths.py <root> --ship` measures it.

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.drives("scripts/dangling_paths.py")

ROOT = Path(__file__).resolve().parents[2]
# Halves, so this shipped file spells no pointer the dangling-docs census would judge.
DOC = "docs" + "/a.md"
SHIM = "".join(f"line {n}\n" if n != 5 else "\n" for n in range(1, 14))
MODULE = '''"""A module."""


def guard(x: int) -> int:
    """Refuse."""
    return (
        x
    )


LIMIT = 3
'''


def _reader() -> ModuleType:
    """The shipped `scripts/dangling_paths.py`, imported by path."""
    path = ROOT / "scripts/dangling_paths.py"
    spec = importlib.util.spec_from_file_location("dangling_paths_t", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reader = _reader()


def _world(tmp_path: Path, doc: str) -> tuple[Path, Path]:
    """A root with a 13-line shim, a Python module and one doc citing them; the NUL list."""
    root = tmp_path / "root"
    (root / "scripts").mkdir(parents=True)
    (root / "apps/x").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "scripts/shim.sh").write_text(SHIM)
    (root / "apps/x/mod.py").write_text(MODULE)
    (root / DOC).write_text(doc)
    listing = tmp_path / "list"
    listing.write_bytes(f"{DOC}\0".encode())
    return root, listing


def _run(tmp_path: Path, doc: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    root, listing = _world(tmp_path, doc)
    rc = reader.main([str(root), str(listing)])
    said = capsys.readouterr()
    return rc, said.out + said.err


def test_a_line_past_the_files_end_is_exit_1_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, said = _run(tmp_path, "The shim's act is `scripts/shim.sh:99`.\n", capsys)
    assert rc == 1, said
    assert "scripts/shim.sh:99 cites past scripts/shim.sh's end (it has 13 lines)" in said
    assert f"spelled in {DOC}:1" in said


def test_a_blank_line_is_exit_1_naming_blank(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, said = _run(tmp_path, "See `scripts/shim.sh:5`.\n", capsys)
    assert rc == 1, said
    assert "scripts/shim.sh:5 lands on a blank line" in said


def test_a_range_ending_past_the_end_is_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, said = _run(tmp_path, "See `scripts/shim.sh:10-20`.\n", capsys)
    assert rc == 1, said
    assert "scripts/shim.sh:10-20 cites past scripts/shim.sh's end" in said


def test_a_single_line_on_a_bare_closer_is_exit_1_and_a_range_may_end_on_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, said = _run(tmp_path, "See `apps/x/mod.py:8`.\n", capsys)
    assert rc == 1, said
    assert "apps/x/mod.py:8 lands on a bare closer `)`" in said
    rc, said = _run(tmp_path / "range", "See `apps/x/mod.py:4-8`.\n", capsys)
    assert rc == 0, said


def test_a_resolving_name_and_a_line_that_says_something_are_exit_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = "The guard: `apps/x/mod.py::guard`, `apps/x/mod.py::LIMIT`, `scripts/shim.sh:13`.\n"
    rc, said = _run(tmp_path, doc, capsys)
    assert rc == 0, said
    assert said == ""


def test_a_line_in_an_example_fence_or_after_a_placeholder_is_not_judged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    doc = "```example\n`scripts/shim.sh:99`\n```\nA product's `apps/<x>/mod.py:99`.\n"
    rc, said = _run(tmp_path, doc, capsys)
    assert rc == 0, said


def test_rewrite_lines_proposes_the_definition_and_leaves_what_has_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root, _ = _world(tmp_path, "`apps/x/mod.py:6` and `apps/x/mod.py:11` and `scripts/shim.sh:3`\n")
    rc = reader.main([str(root), "--rewrite-lines", DOC, "--write"])
    said = capsys.readouterr().out
    assert rc == 0, said
    assert "apps/x/mod.py:6 -> apps/x/mod.py::guard" in said
    assert "scripts/shim.sh:3 stays — not Python" in said
    text = (root / DOC).read_text()
    assert text == "`apps/x/mod.py::guard` and `apps/x/mod.py::LIMIT` and `scripts/shim.sh:3`\n"


def _unreadable_repo(root: Path) -> Path:
    """A root whose `.git` names a directory that is not there: every git call fails, saying so."""
    (root / ".git").write_text("gitdir: /nonexistent/djb-not-a-repo\n")
    (root / "a.md").write_text("see " + "docs" + "/nowhere.md\n")
    return root


def test_a_git_that_cannot_list_the_root_is_quoted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _unreadable_repo(tmp_path)
    (tmp_path / "list").write_bytes(b"a.md\0")
    assert reader.main([str(root), str(tmp_path / "list")]) == 2
    err = capsys.readouterr().err
    assert "\n   the tool said: fatal: not a git repository" in err, err


def test_the_dangling_docs_leg_quotes_git_through_the_reader(tmp_path: Path) -> None:
    from quality.could_not_look import CouldNotLook
    from quality.djb.legs import dangling_docs

    root = _unreadable_repo(tmp_path)
    with pytest.raises(CouldNotLook) as refused:
        dangling_docs.dangling_docs(root, ["a.md"], "the tree")
    assert "\n   the tool said: fatal: not a git repository" in str(refused.value)
