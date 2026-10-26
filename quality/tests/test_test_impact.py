"""The test-impact map writer: every collected test mapped or declared; a hole is could-not-look."""

# does-not-cover: whether the map is true — coverage's attribution is fed in, never judged.
# does-not-cover: what a test reaches through a subprocess — the subject's own declared blind spot.
# does-not-cover: the acceptance box's two passes and the fetch — test_pm_push's.

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from coverage import CoverageData

from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives("scripts/test_impact.py", "scripts/test_impact.json")

ROOT = Path(__file__).resolve().parents[2]
SUBJECT = ROOT / "scripts" / "test_impact.py"
EXECUTES = "apps/alpha/tests/test_services.py::test_executes"
PURE = "apps/alpha/tests/test_pure.py::test_pure"
READS = "apps/alpha/tests/test_reads.py::test_reads_by_path"
GONE = "apps/alpha/tests/test_gone.py::test_gone"
REASON = "no source line recorded — reads the tree by path (read_text/ast) or is pure"


def collected_list(world: Path, *nodeids: str) -> None:
    """The shape `pytest --collect-only -q` prints: the nodeids, a blank, a summary line."""
    body = "".join(f"{n}\n" for n in nodeids) + f"\n{len(nodeids)} tests collected in 0.42s\n"
    (world / "collected.txt").write_text(body)


@pytest.fixture
def world(scratch: Path) -> Path:
    """A fake checkout and a coverage database holding the census's four context shapes."""
    root = scratch / "root"
    (root / "apps/alpha/tests").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "apps/alpha/services.py").write_text("")
    (root / "apps/alpha/tests/test_services.py").write_text("")
    db = scratch / "coverage.db"
    data = CoverageData(basename=str(db))
    data.set_context(f"{EXECUTES}|run")
    data.add_lines(
        {
            f"{root}/apps/alpha/services.py": [1, 2, 3],
            f"{root}/apps/alpha/tests/test_services.py": [1, 5],
        }
    )
    data.set_context(f"{PURE}|run")
    data.add_lines({"/opt/elsewhere/lib.py": [7]})
    data.set_context(f"{GONE}|run")
    data.add_lines({f"{root}/apps/alpha/services.py": [2]})
    data.write()
    # The empty context, inserted directly: `CoverageData` makes no context row without lines.
    con = sqlite3.connect(db)
    con.execute("insert into context (context) values (?)", (f"{READS}|run",))
    con.commit()
    con.close()
    collected_list(scratch, EXECUTES, PURE, READS)
    return scratch


@pytest.fixture
def write_map(world: Path, capture: Callable[..., Captured]) -> Callable[..., Captured]:
    """Run the subject's `write` over the world, through the checkout's own interpreter."""

    def run(*argv: str) -> Captured:
        return capture(
            [
                sys.executable,
                str(SUBJECT),
                "write",
                "--coverage",
                str(world / "coverage.db"),
                "--collected",
                str(world / "collected.txt"),
                "--root",
                str(world / "root"),
                "--out",
                str(world / "root/scripts/test_impact.json"),
                *argv,
            ]
        )

    return run


def the_map(world: Path) -> dict[str, dict[str, object]]:
    loaded: dict[str, dict[str, object]] = json.loads(
        (world / "root/scripts/test_impact.json").read_text()
    )
    return loaded


def test_every_collected_test_is_mapped_or_declared(
    world: Path, write_map: Callable[..., Captured]
) -> None:
    ran = write_map()
    out = ran.text()
    assert ran.rc == 0, out
    doc = the_map(world)
    assert (len(doc["tests"]), len(doc["unmapped"])) == (1, 2)
    assert len(doc["tests"]) + len(doc["unmapped"]) == 3
    assert doc["tests"][EXECUTES] == [
        "apps/alpha/services.py",
        "apps/alpha/tests/test_services.py",
    ]
    assert doc["unmapped"] == {PURE: REASON, READS: REASON}
    assert PURE not in doc["tests"]
    assert sorted(doc) == ["generated", "tests", "unmapped"]
    assert sorted(doc["generated"]) == ["at", "pytest", "tree"]
    assert "1 tests mapped" in out
    assert "2 unmapped" in out
    assert GONE in out
    assert "vanished" in out


def test_a_collected_test_with_no_context_is_could_not_look(
    world: Path, write_map: Callable[..., Captured]
) -> None:
    collected_list(world, EXECUTES, PURE, READS, "apps/alpha/tests/test_orphan.py::test_orphan")
    ran = write_map()
    assert ran.rc == 2
    assert (
        "!! test_impact: could not look — apps/alpha/tests/test_orphan.py::test_orphan collected,"
        " no context"
    ) in ran.text()
    assert not (world / "root/scripts/test_impact.json").exists()


def test_the_map_is_deterministic(world: Path, write_map: Callable[..., Captured]) -> None:
    written = world / "root/scripts/test_impact.json"
    assert write_map().rc == 0
    first = written.read_bytes()
    assert write_map().rc == 0
    assert written.read_bytes() == first
    lines = written.read_text().splitlines()
    assert sum("test_services.py::test_executes" in line for line in lines) == 1
    line = f'    "{EXECUTES}": ["apps/alpha/services.py", "apps/alpha/tests/test_services.py"]'
    assert line in lines or f"{line}," in lines


def test_a_missing_input_is_could_not_look(world: Path, write_map: Callable[..., Captured]) -> None:
    shutil.move(world / "coverage.db", world / "coverage.away")
    ran = write_map()
    assert ran.rc == 2
    assert "!! test_impact: could not look — no coverage database at" in ran.text()
    shutil.move(world / "coverage.away", world / "coverage.db")

    shutil.move(world / "collected.txt", world / "collected.away")
    ran = write_map()
    assert ran.rc == 2
    assert "!! test_impact: could not look — no collected list at" in ran.text()
    shutil.move(world / "collected.away", world / "collected.txt")

    collected_list(world)
    ran = write_map()
    assert ran.rc == 2
    assert "!! test_impact: could not look — the collected list is empty" in ran.text()
    assert not (world / "root/scripts/test_impact.json").exists()


def test_an_unknown_subcommand_is_refused(world: Path, capture: Callable[..., Captured]) -> None:
    ran = capture([sys.executable, str(SUBJECT), "wrote", "--coverage", str(world / "coverage.db")])
    assert ran.rc != 0
    assert "tests mapped" not in ran.text()
