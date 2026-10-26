"""The fold's secrets step over scratch repositories, judged by the real `detect-secrets`."""

# does-not-cover: detect-secrets' plugin catalogue — one Secret Keyword shape is driven, not all.
# does-not-cover: the fold's other steps — every world here runs `--only secrets`.

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from quality.tests.fixtures.capture import Captured, run_to
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives("quality/djb/rituals/fold.py", ".secrets.baseline")

ROOT = Path(__file__).resolve().parents[2]
BIN = Path(sys.executable).parent
ENTRY = (
    "import sys; from pathlib import Path; "
    "from quality.djb.rituals.fold import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
#: A `uv` whose `run <tool> …` is this venv's real tool, so the scan judges for real.
UV = f'#!/bin/sh\nshift\nexec "{BIN}/$@"\n'
#: Assembled at runtime so this file's own text carries no secret-shaped literal.
KEYWORD = "pass" + "word"


def literal(n: int) -> str:
    """One line the Secret Keyword plugin reports, distinct per `n`."""
    return f'{KEYWORD} = "Zq{n}vR8kLm2Xw9Tp4Hs7Jd"\n'


class Repo:
    """One scratch checkout with a committed, stripped baseline the real scanner wrote."""

    def __init__(self, scratch: Path, stubs: StubPath, name: str) -> None:
        self.root = scratch / name
        self.root.mkdir()
        self.scratch = scratch
        self.stubs = stubs
        for step in (
            ["init", "-q", "-b", "main"],
            ["config", "user.email", "drive@example.invalid"],
            ["config", "user.name", "fold secrets drive"],
            ["config", "commit.gpgsign", "false"],
        ):
            self.git(*step)

    def git(self, *argv: str) -> str:
        """`git -C <root> <argv>`'s stdout; a failure fails the test."""
        done = subprocess.run(
            ["git", "-C", str(self.root), *argv], capture_output=True, text=True, check=False
        )
        assert done.returncode == 0, f"git {' '.join(argv)}: {done.stderr}"
        return done.stdout.strip()

    def write(self, rel: str, text: str) -> None:
        """Write one file and commit it."""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        self.git("add", rel)
        self.git("commit", "-q", "-m", f"write {rel}")

    def baseline(self) -> None:
        """The real scanner's baseline of what is committed now, stripped and committed."""
        path = self.root / ".secrets.baseline"
        with path.open("w") as sink:
            subprocess.run(
                [str(BIN / "detect-secrets"), "scan"], cwd=self.root, stdout=sink, check=True
            )
        subprocess.run(
            [str(BIN / "detect-secrets"), "scan", "--baseline", ".secrets.baseline"],
            cwd=self.root,
            check=True,
        )
        data = json.loads(path.read_text())
        data.pop("generated_at", None)
        for entries in data["results"].values():
            for entry in entries:
                entry.pop("line_number", None)
        self.write(".secrets.baseline", json.dumps(data, indent=2) + "\n")

    def results(self) -> dict[str, list[dict[str, object]]]:
        """The committed baseline's results map."""
        return dict(json.loads((self.root / ".secrets.baseline").read_text())["results"])

    def fold(self) -> Captured:
        """`--only secrets`, both streams to a file outside the checkout."""
        sink = self.scratch / f"fold-{self.root.name}-{len(list(self.scratch.glob('fold-*')))}"
        env = {
            **os.environ,
            "PATH": f"{self.stubs.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "PYTHONPATH": str(ROOT),
            "DJB_FOLD_UV": "uv",
        }
        return run_to(sink, [sys.executable, "-c", ENTRY, "--only", "secrets"], self.root, env)


@pytest.fixture
def repo(scratch: Path, stub_path: StubPath) -> Repo:
    """A checkout holding one known secret, its baseline recording exactly that one."""
    stub_path.plant("uv", UV)
    made = Repo(scratch, stub_path, "repo")
    made.write("src/known.py", literal(1))
    made.baseline()
    assert list(made.results()) == ["src/known.py"]
    return made


def test_a_new_secret_dies_with_its_line_printed(repo: Repo) -> None:
    repo.write("src/leak.py", "first = 1\n" + literal(2))
    head = repo.git("rev-parse", "HEAD")
    before = (repo.root / ".secrets.baseline").read_bytes()
    said = repo.fold()
    text = said.text()
    assert said.rc == 2, text
    assert "src/leak.py:2 Secret Keyword" in text
    assert "# pragma: allowlist secret" in text
    assert "BASELINE SHIFTED" not in text
    assert (repo.root / ".secrets.baseline").read_bytes() == before
    assert repo.git("status", "--porcelain") == ""
    assert repo.git("rev-parse", "HEAD") == head


def test_a_new_secret_carrying_the_pragma_is_not_growth(repo: Repo) -> None:
    repo.write("src/fixture.py", literal(3).rstrip("\n") + "  # pragma: allowlist secret\n")
    head = repo.git("rev-parse", "HEAD")
    said = repo.fold()
    assert said.rc == 0, said.text()
    assert repo.git("rev-parse", "HEAD") == head
    assert list(repo.results()) == ["src/known.py"]


def test_one_fewer_secret_shrinks_the_baseline_and_passes(repo: Repo) -> None:
    repo.write("src/known.py", "nothing secret here any more\n")
    said = repo.fold()
    text = said.text()
    assert said.rc == 0, text
    assert "BASELINE SHIFTED" in text
    assert repo.results() == {}
    assert repo.git("log", "-1", "--format=%s") == "fold: baseline shifted"
    assert repo.git("status", "--porcelain") == ""


def test_the_committed_baseline_carries_no_result() -> None:
    data = json.loads((ROOT / ".secrets.baseline").read_text())
    absorbed = {
        f"{path} {entry['type']}" for path, entries in data["results"].items() for entry in entries
    }
    assert not absorbed, "\n".join(sorted(absorbed))
