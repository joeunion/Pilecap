"""The `archaeology` leg over a scratch repository: each of six shapes fires, the rest is silent."""

# deleted: case_fast_wires_the_archaeology_leg_and_loop_does_not_run_it_twice — dies with the shim
# pin: test_the_leg_runs_once_in_fast_and_its_could_not_look_names_the_leg (registry.mode_legs)

# does-not-cover: publish.sh's full-artifact scan — the leg reads the changed set only.
# does-not-cover: whether a pattern's word list is complete — each shape is planted once.

# names, never reads: docs/product/in-flight.md — the lib's R7 home list, scratch only

from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.djb import registry
from quality.djb.legs import archaeology
from quality.djb.legs._run import LIBRARIES

pytestmark = pytest.mark.drives(
    "docs/product/in-flight.md",
    "docs/product/queue.md",
    "scripts/archaeology_lib.sh",
    "scripts/check.sh",
    "scripts/secrets_scan.sh",
)

ROOT = Path(__file__).resolve().parents[2]
#: Each shape's label and a token that fires it, split so this file is not itself a finding.
SHAPES = (
    ("finding-id", "N" + "347"),
    ("rung-token", "P" + "9-2"),
    ("narrative", "PROVE" + "-1"),
    ("private-name", "Att" + "icus"),
    ("former-brand", "Django" + "Bootstrap"),
    ("deploy-coordinate", "pilecap" + "-staging"),
)
THIN = "no local refs/heads/main to fork from"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _libraries(repo: Path) -> None:
    """The libraries the leg sources, committed into `repo` so they are never the changed set."""
    for lib in LIBRARIES:
        (repo / lib).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / lib, repo / lib)
    _git(repo, "add", "scripts")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "libraries")


@pytest.fixture
def repo(scratch_repo: Callable[..., Path]) -> Path:
    """A repository on `main` carrying the leg's libraries and the three bucket directories."""
    where = scratch_repo("archaeology")
    _libraries(where)
    for d in ("apps/example", "docs/product"):
        (where / d).mkdir(parents=True, exist_ok=True)
    return where


def _plant(repo: Path, path: str, text: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(text)
    _git(repo, "add", "-A")


def _run(repo: Path, capfd: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capfd.readouterr()
    rc = archaeology.LEG.body(registry.Ctx(repo, "fast"))  # type: ignore[misc]
    out = capfd.readouterr()
    return rc, out.out + out.err


def test_each_pattern_fires_on_a_changed_ship_file(
    scratch_repo: Callable[..., Path], capfd: pytest.CaptureFixture[str]
) -> None:
    for label, token in SHAPES:
        repo = scratch_repo(f"shape-{label}")
        _libraries(repo)
        _plant(repo, "scripts/plant.sh", f"# a plant: {token}\n")
        rc, out = _run(repo, capfd)
        assert rc == 1, (label, out)
        assert re.search(rf"archaeology-census: scripts/plant\.sh:[0-9]+  {label}", out), (
            label,
            out,
        )
        assert f'"{token}"' in out, label


def test_allowlisted_forms_stay_silent(repo: Path, capfd: pytest.CaptureFixture[str]) -> None:
    stack = "django" + "bootstrap"
    _plant(repo, "scripts/plant.sh", f"Pilecap ships its own name.\nthe stack is `name: {stack}`\n")
    rc, out = _run(repo, capfd)
    assert rc == 0, out
    assert "VIOLATION" not in out


def test_skeleton_bucket_stays_silent(repo: Path, capfd: pytest.CaptureFixture[str]) -> None:
    n, rung, story = SHAPES[0][1], SHAPES[1][1], SHAPES[2][1]
    _plant(repo, "docs/product/queue.md", f"| {n} | {rung} | done | {story} |\n")
    rc, out = _run(repo, capfd)
    assert rc == 0, out
    assert "NOTHING TO SCAN" in out


def test_ship_file_beside_skeleton_still_scanned(
    repo: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    (repo / "docs/product/queue.md").write_text(f"| {SHAPES[0][1]} |\n")
    _plant(repo, "scripts/plant.sh", "this " + "rung\n")
    rc, out = _run(repo, capfd)
    assert rc == 1, out
    assert "archaeology-census: scripts/plant.sh" in out
    assert "queue.md" not in out


def test_nothing_changed(repo: Path, capfd: pytest.CaptureFixture[str]) -> None:
    _plant(repo, "scripts/plant.sh", "# nothing archaeological here\n")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    rc, out = _run(repo, capfd)
    assert rc == 0, out
    assert "NOTHING TO SCAN" in out


def test_could_not_look_no_git(scratch: Path, capfd: pytest.CaptureFixture[str]) -> None:
    bare = scratch / "not-a-repo"
    for lib in LIBRARIES:
        (bare / lib).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / lib, bare / lib)
    rc, out = _run(bare, capfd)
    assert rc == 2, out


def test_timing_printed(repo: Path, capfd: pytest.CaptureFixture[str]) -> None:
    _plant(repo, "scripts/plant.sh", "# nothing archaeological\n")
    started = time.monotonic()
    rc, out = _run(repo, capfd)
    took = int((time.monotonic() - started) * 1000)
    print(f"measured: {took}ms (one changed file, one repo — this case's own overhead)")
    assert rc == 0, out


def test_a_planted_id_in_a_ship_bucket_comment_reds_fast(
    repo: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    _plant(repo, "scripts/plant.sh", "# see " + "N" + "999 and this " + "rung\n")
    rc, out = _run(repo, capfd)
    assert rc == 1, out
    for label in ("finding-id", "narrative"):
        assert re.search(rf"archaeology-census: scripts/plant\.sh:[0-9]+  {label}", out), (
            label,
            out,
        )


def test_the_leg_runs_once_in_fast_and_its_could_not_look_names_the_leg(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    table = registry.load(ROOT)
    fast = [g.name for g in table.mode_legs("fast")]
    assert fast.count("archaeology") == 1
    members = [m for _, ms in table.rows for m in ms]
    assert members.count("archaeology") == 1
    bare = scratch / "not-a-repo"
    for lib in LIBRARIES:
        (bare / lib).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / lib, bare / lib)
    rc, out = _run(bare, capfd)
    assert rc == 2
    assert "the archaeology-census leg COULD NOT DERIVE" in out
    assert "cause:" in out


def test_fast_on_a_thin_basis_scans_the_uncommitted_set_and_says_so(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    thin = scratch / "thin"
    (thin / "docs/product").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "elsewhere", str(thin)], check=True)
    _plant(thin, "scripts/base.sh", "# nothing archaeological\n")
    _libraries(thin)
    _plant(thin, "scripts/plant.sh", "# a plant: " + "N" + "999\n")
    rc, out = _run(thin, capfd)
    assert rc == 1, out
    assert THIN in out
    assert "archaeology-census: scripts/plant.sh" in out
    _plant(thin, "scripts/plant.sh", "# nothing archaeological\n")
    rc, out = _run(thin, capfd)
    assert rc == 0, out
    assert THIN in out


def test_r12_is_the_measured_files_the_readers_default_to() -> None:
    from quality.djb import scope
    from quality.djb.legs import pytest_x2

    lines = (ROOT / "scripts" / "archaeology_lib.sh").read_text().splitlines()
    rule = next(line for line in lines if 'hit="$hit R12"' in line)
    named = set(re.findall(r"scripts/[a-z_]+\.json", rule))
    assert named == {pytest_x2.DURATIONS, registry.WALLS_HOMES[0], scope.MAP_PATH}


#: The platform's own proofs; a product's repository keeps `ci.yml`, its gate.
OWN_PROOFS = ("proof-from-zero.yml", "nightly-proof.yml", "mirror-images.yml")


def _bucket(path: str) -> str:
    script = (
        'source scripts/archaeology_lib.sh && r=$(rules_for "$1") && '
        'printf "%s %s" "$r" "$(bucket_for_rule "$r")"'
    )
    done = subprocess.run(
        ["bash", "-c", script, "_", path], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return done.stdout


@pytest.mark.parametrize("name", OWN_PROOFS)
def test_the_platforms_own_proofs_trim(name: str) -> None:
    assert _bucket(f".github/workflows/{name}") == "R14 TRIM"


def test_the_products_gate_workflow_ships() -> None:
    assert _bucket(".github/workflows/ci.yml") == "R3 SHIP"
