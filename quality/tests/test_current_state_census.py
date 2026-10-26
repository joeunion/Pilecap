"""`scripts/current_state_census.py`: a page naming an id, a trimmed path or a gone future: 1."""

# does-not-cover: whether a future the census admits (a dated trigger, a blind spot) is still true.

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CENSUS = ROOT / "scripts" / "current_state_census.py"
#: The fixture paths, assembled so this file spells no path its own tree lacks.
DOCS = "docs/"
PAGE = DOCS + "runbooks/page.md"
REPORT = DOCS + "product/reports/p1/options.md"
#: A queue-row id, assembled so this file spells none.
ROW = "N" + "2303"


@pytest.fixture
def world(tmp_path: Path) -> Path:
    """A checkout carrying the manifest, its classifier and one trimmed report."""
    (tmp_path / "scripts").mkdir()
    for lib in ("archaeology_lib.sh", "gate_refuse.sh"):
        shutil.copy(ROOT / "scripts" / lib, tmp_path / "scripts" / lib)
    for rel, text in {
        "docs/product/publication-manifest.md": "# manifest\n",
        REPORT: "# a report\n",
        DOCS + "product/adrs/x-1.md": "until LA-WORKER-1 lands (the log keeps its words)\n",
    }.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    return tmp_path


def census(root: Path, page: str, rel: str = PAGE) -> subprocess.CompletedProcess[str]:
    """`page` written at `rel`, tracked, and the census run over the root's SHIP set."""
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(page)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    return subprocess.run(
        [sys.executable, str(CENSUS), str(root), "--ship"], capture_output=True, text=True
    )


def kinds(done: subprocess.CompletedProcess[str]) -> list[str]:
    """The class column of every refused line."""
    return [line.split("  ")[1] for line in done.stdout.splitlines()]


def test_a_ledger_id_is_refused_with_its_line(world: Path) -> None:
    done = census(world, f"# Page\n\nThe move is unbuilt today ({ROW}).\n")
    assert done.returncode == 1, done.stderr
    assert done.stdout.startswith(f"{PAGE}:3  ledger-id  The move is unbuilt"), done.stdout


def test_a_passed_future_under_a_current_heading_is_refused(world: Path) -> None:
    done = census(world, "# Page\n\n## Today\n\nThe worker is unsteady until LA-WORKER-1 lands.\n")
    assert done.returncode == 1
    assert kinds(done) == ["ledger-id", "future-tense"], done.stdout


def test_the_same_sentence_under_blind_spots_keeps_only_its_id(world: Path) -> None:
    page = "# Page\n\n## Blind spots\n\nThe worker is unsteady until LA-WORKER-1 lands.\n"
    done = census(world, page)
    assert kinds(done) == ["ledger-id"], done.stdout


def test_a_future_under_blind_spots_is_admitted(world: Path) -> None:
    done = census(world, "# Page\n\n## Blind spots\n\n- Unsteady until the drain lands.\n")
    assert (done.returncode, done.stdout) == (0, ""), done.stdout


def test_a_future_dated_by_its_release_is_admitted(world: Path) -> None:
    done = census(world, "# Page\n\nThe second web box is deferred to 2.6.\n")
    assert (done.returncode, done.stdout) == (0, ""), done.stdout


def test_a_planned_fence_admits_its_body_and_nothing_after_it(world: Path) -> None:
    page = (
        "# P\n\n<!-- planned -->\nThe drill is planned.\n<!-- /planned -->\nThe soak is unbuilt.\n"
    )
    done = census(world, page)
    assert [line.split("  ")[0] for line in done.stdout.splitlines()] == [f"{PAGE}:6"]


def test_a_trimmed_path_and_a_report_named_bare_are_refused(world: Path) -> None:
    page = f"# P\n\nSee `{REPORT}`.\n\nAnd `options.md` § 8.\n"
    done = census(world, page)
    assert kinds(done) == ["trimmed-path", "trimmed-path"], done.stdout


def test_a_shipped_path_and_a_drawer_are_not_trimmed(world: Path) -> None:
    page = "# P\n\n`docs/product/publication-manifest.md`, `patterns.local.md`.\n"
    assert census(world, page).returncode == 0


def test_an_example_fence_the_changelog_history_and_the_adr_log_are_not_read(world: Path) -> None:
    census(world, f"```text example\n{ROW} is unbuilt\n```\n")
    done = census(
        world, f"## [Unreleased]\n\nok\n\n## [2.4.0]\n\n- {ROW} unbuilt\n", "CHANGELOG.md"
    )
    assert (done.returncode, done.stdout) == (0, ""), done.stdout


def test_a_root_without_its_manifest_could_not_look(world: Path) -> None:
    (world / "scripts/archaeology_lib.sh").unlink()
    done = census(world, "# P\n")
    assert done.returncode == 2
    assert "no manifest" in done.stderr


def test_the_dangling_docs_body_runs_the_census(world: Path) -> None:
    """`docs_current_state_check`, as `docs_dangling_docs_loop` calls it: each line, then 1."""
    census(world, f"# P\n\nThe move is unbuilt ({ROW}).\n")
    listing = world / "list"
    listing.write_bytes(f"{PAGE}\0".encode())
    libraries = "".join(
        f". {lib} || exit 2\n"
        for lib in ("scripts/secrets_scan.sh", "scripts/archaeology_lib.sh", "scripts/docs_legs.sh")
    )
    script = (
        f"set -uo pipefail\n{libraries}docs_current_state_check {str(world)!r} {str(listing)!r}\n"
    )
    done = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert done.returncode == 1, done.stdout + done.stderr
    assert f"VIOLATION  {PAGE}:3  ledger-id  The move is unbuilt ({ROW})." in done.stdout
