"""The harness proves itself: planted trees for each outcome, the drive judgment, and the census."""

# deleted: test_a_drive_the_session_left_no_verdict_for_settles_as_could_not_look — shim
# pin: test_legs_always_on.py::test_a_drive_the_session_left_no_verdict_for_could_not_look
# deleted: test_a_session_that_could_not_look_at_teardown_banks_no_green — dies with the shim
# pin: test_legs_always_on.py::test_doubt_names_what_no_drive_owns
# deleted: test_a_session_whose_exit_its_drives_explain_keeps_their_greens — dies with the shim
# pin: test_a_session_that_exits_worse_than_its_drives_turns_their_green_to_could_not_look
# deleted: test_a_session_exit_no_drive_explains_banks_no_green — dies with the shim
# pin: test_legs_always_on.py::test_doubt_names_what_no_drive_owns
# deleted: test_a_serial_drive_runs_alone_after_the_others — dies with the shim
# pin: test_legs_always_on.py::test_serial_drives_run_alone_after_the_parallel_session_longest_first
# deleted: test_the_drives_run_longest_recorded_first — dies with the shim
# pin: test_legs_always_on.py::test_serial_drives_run_alone_after_the_parallel_session_longest_first
# deleted: test_a_member_that_is_no_drive_runs_in_turn_and_settles_its_own_exit — dies with the shim
# pin: test_legs_always_on.py::test_a_red_and_a_could_not_look_member_compose_to_2_naming_both

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import registry as R
from quality.djb.legs import always_on as ao
from quality.tests.drives import drive_name, header_line, population, run_drive, verdict

pytestmark = pytest.mark.drives(
    "quality/tests/harness.py",
    "quality/tests/conftest.py",
    "scripts/check.sh",
    "scripts/tests/drive_preamble.sh",
)

ROOT = Path(__file__).resolve().parents[2]
Nested = Callable[..., tuple[int, str]]

PASS = "def test_passes():\n    assert True\n"  # noqa: S105 — a planted test module's source text
FAIL = "def test_fails():\n    assert False\n"
NOT_LOOKED = (
    "from quality.could_not_look import CouldNotLook\n\n\n"
    "def test_could_not_look():\n    raise CouldNotLook('planted')\n"
)
SKIP = "import pytest\n\n\ndef test_skips():\n    pytest.skip('planted')\n"


def test_a_pass_alone_is_exit_0(nested_pytest: Nested) -> None:
    rc, out = nested_pytest({"test_p.py": PASS})
    assert rc == 0, out
    assert "harness: 1 passed · 0 failed · 0 could not look" in out


def test_a_failure_is_exit_1(nested_pytest: Nested) -> None:
    rc, out = nested_pytest({"test_f.py": FAIL})
    assert rc == 1, out
    assert "harness: 0 passed · 1 failed · 0 could not look" in out


def test_could_not_look_beside_a_pass_is_exit_2(nested_pytest: Nested) -> None:
    rc, out = nested_pytest({"test_p.py": PASS, "test_c.py": NOT_LOOKED})
    assert rc == 2, out
    assert "harness: 1 passed · 0 failed · 1 could not look" in out


def test_could_not_look_outranks_a_failure(nested_pytest: Nested) -> None:
    rc, out = nested_pytest({"test_f.py": FAIL, "test_c.py": NOT_LOOKED})
    assert rc == 2, out
    assert "harness: 0 passed · 1 failed · 1 could not look" in out


def test_the_third_outcome_survives_xdist(nested_pytest: Nested) -> None:
    rc, out = nested_pytest({"test_p.py": PASS, "test_c.py": NOT_LOOKED}, workers=2)
    assert rc == 2, out
    assert "harness: 1 passed · 0 failed · 1 could not look" in out


def test_a_bare_skip_could_not_look(nested_pytest: Nested) -> None:
    rc, out = nested_pytest({"test_s.py": SKIP})
    assert rc == 2, out
    assert "a skip clears nothing" in out and "planted" in out


def test_a_module_nothing_can_select_is_exit_2(nested_pytest: Nested) -> None:
    rc, out = nested_pytest({"test_empty.py": "VALUE = 1\n"})
    assert rc == 2, out


def test_a_fixture_that_refuses_could_not_look_at_setup(nested_pytest: Nested) -> None:
    rc, out = nested_pytest({"test_r.py": "def test_r(scratch_repo):\n    scratch_repo('a/b')\n"})
    assert rc == 2, out
    assert "is not one directory name" in out


def test_a_planted_fixture_module_is_found_with_no_edit(
    nested_pytest: Nested, scratch: Path
) -> None:
    planted = "import pytest\n\n\n@pytest.fixture\ndef planted():\n    return 'found'\n"
    test = "def test_uses_it(planted):\n    assert planted == 'found'\n"
    rc, out = nested_pytest({"fixtures/planted.py": planted, "test_uses.py": test})
    assert rc == 0, out
    copied = next(scratch.glob("tree-*/conftest.py")).read_bytes()
    assert copied == (ROOT / "quality/tests/conftest.py").read_bytes()


def _stub(scratch: Path, name: str, body: str) -> Path:
    path = scratch / f"test_{name}.sh"
    path.write_text(f"#!/usr/bin/env bash\n# drives: nothing\n{body}\n")
    path.chmod(0o755)
    return path


def test_a_red_exit_is_red(scratch: Path) -> None:
    rc, _ = run_drive(_stub(scratch, "red", "exit 1"), scratch, scratch / "red.out")
    assert verdict(rc, (scratch / "red.out").read_text(), "test_red")[0] == 1


def test_a_green_exit_with_no_summary_could_not_look(scratch: Path) -> None:
    rc, _ = run_drive(_stub(scratch, "mute", "echo hello"), scratch, scratch / "mute.out")
    assert verdict(rc, (scratch / "mute.out").read_text(), "test_mute")[0] == 2


def test_a_green_exit_with_a_summary_is_green(scratch: Path) -> None:
    line = "echo 'test_ok: 3 passed · 0 failed · 0 skipped'"
    rc, _ = run_drive(_stub(scratch, "ok", line), scratch, scratch / "ok.out")
    assert verdict(rc, (scratch / "ok.out").read_text(), "test_ok")[0] == 0


def test_a_summary_counting_a_failure_is_red_whatever_the_exit() -> None:
    assert verdict(0, "test_x: 3 passed · 1 failed · 0 skipped\n", "test_x")[0] == 1


@pytest.mark.parametrize(
    "line",
    [
        "test_x: 3 passed · 0 failed · 0 skipped",
        "test_x: 81 passed · 0 failed",
        "test_x: 377 passed, 0 failed",
        "test_x: 30 passed · 0 failed · 0 could not look",
    ],
)
def test_every_summary_spelling_the_drives_print_is_read(line: str) -> None:
    assert verdict(0, f"ok    something\n{line}\n", "test_x")[0] == 0
    assert verdict(0, f"{line.replace('0 failed', '2 failed')}\n", "test_x")[0] == 1


def test_a_case_line_that_mentions_passed_is_no_summary() -> None:
    assert verdict(0, "   ok    one ok, 3 passed in the planted run\n", "test_x")[0] == 2


def test_a_summary_counting_could_not_look_could_not_look() -> None:
    assert verdict(0, "test_x: 5 passed · 0 failed · 2 could not look\n", "test_x")[0] == 2


def test_a_summary_that_asserted_nothing_could_not_look() -> None:
    assert verdict(0, "test_x: 0 passed · 0 failed · 7 skipped\n", "test_x")[0] == 2


def test_a_nested_childs_later_green_line_never_stands_in_for_the_drives_own() -> None:
    own_red = (
        "test_x: 4 passed · 2 failed · 0 skipped\ntest_child: 1 passed · 0 failed · 0 skipped\n"
    )
    assert verdict(0, own_red, "test_x")[0] == 1


def test_an_echoed_child_summary_before_an_early_exit_is_no_summary(scratch: Path) -> None:
    body = "echo 'test_child: 1 passed · 0 failed · 0 skipped'\nexit 0"
    rc, _ = run_drive(_stub(scratch, "early", body), scratch, scratch / "early.out")
    assert verdict(rc, (scratch / "early.out").read_text(), "test_early")[0] == 2


def test_the_preamble_names_its_summary_by_the_drives_stem(scratch: Path) -> None:
    (scratch / "scripts/tests").mkdir(parents=True)
    (scratch / "scripts/tests/drive_preamble.sh").write_bytes(
        (ROOT / "scripts/tests/drive_preamble.sh").read_bytes()
    )
    drive = scratch / "scripts/tests/test_named.sh"
    drive.write_text(
        "#!/usr/bin/env bash\n# drives: nothing\nset -eu\n"
        '. "$(dirname "$0")/drive_preamble.sh"\nok "one"\ndrive_finished\nexit 0\n'
    )
    drive.chmod(0o755)
    rc, _ = run_drive(drive, scratch, scratch / "named.out")
    output = (scratch / "named.out").read_text()
    assert verdict(rc, output, drive.stem) == (0, "exit 0 and a clean summary"), output


def test_a_param_with_no_drives_line_could_not_look(
    nested_pytest: Nested, scratch_repo: Callable[..., Path]
) -> None:
    repo = scratch_repo()
    (repo / "scripts/tests").mkdir(parents=True)
    _stub(repo / "scripts/tests", "bare", "exit 0").write_text("#!/usr/bin/env bash\nexit 0\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    test = (
        "from pathlib import Path\nimport pytest\n"
        "from quality.tests.drives import params, require_declared\n\n\n"
        f"@pytest.mark.parametrize('drive', list(params(Path({str(repo)!r}))))\n"
        "def test_drive(drive, request):\n    require_declared(request.node, drive)\n"
    )
    rc, out = nested_pytest({"test_d.py": test})
    assert rc == 2, out
    assert "has no `# drives:` line" in out


def test_one_param_per_tracked_drive() -> None:
    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:django",
            "-p",
            "no:randomly",
            "-W",
            "ignore::pytest.PytestConfigWarning",
            "--collect-only",
            "-q",
            "quality/tests/test_drives.py",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    ids = sorted(
        line.split("[", 1)[1].rstrip("]")
        for line in collected.stdout.splitlines()
        if "::test_drive[" in line
    )
    tracked = sorted(drive_name(path) for path in population(ROOT))
    assert ids == tracked, collected.stdout + collected.stderr


def test_every_tracked_drive_declares_what_it_drives() -> None:
    bare = [p for p in population(ROOT) if header_line(ROOT / p, "drives") is None]
    assert bare == []


def test_the_drives_marker_is_registered() -> None:
    listed = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:django", "--markers", "quality/tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert "@pytest.mark.drives(*globs)" in listed.stdout


def test_a_failed_teardown_is_written_where_the_leg_reads_it(
    nested_pytest: Nested, scratch: Path
) -> None:
    test = (
        "import pytest\nfrom quality.could_not_look import CouldNotLook\n\n\n"
        "@pytest.fixture(scope='session', autouse=True)\ndef moved():\n    yield\n"
        "    raise CouldNotLook('planted at teardown')\n\n\n"
        "def test_passes():\n    assert True\n"
    )
    results = scratch / "results"
    results.mkdir()
    rc, out = nested_pytest(
        {"test_t.py": test}, env={"PYTEST_ADDOPTS": f"--drives-results {results}"}
    )
    assert rc == 2, out
    assert "teardown could-not-look" in (results / "outside.lines").read_text(), out


def test_a_serial_drive_could_not_look_in_an_xdist_worker(
    nested_pytest: Nested, scratch: Path
) -> None:
    lone = scratch / "test_lone.sh"
    lone.write_text("#!/bin/sh\n# serial: planted\nexit 0\n")
    test = (
        "from pathlib import Path\nfrom quality.tests.drives import require_alone\n\n\n"
        f"def test_alone():\n    require_alone(Path({str(lone)!r}))\n"
    )
    rc, out = nested_pytest({"test_a.py": test}, workers=2)
    assert rc == 2, out
    assert "declares `# serial:`" in out, out
    rc, out = nested_pytest({"test_a.py": test})
    assert rc == 0, out
    lone.write_text("#!/bin/sh\nexit 0\n")
    rc, out = nested_pytest({"test_a.py": test}, workers=2)
    assert rc == 0, out


def _touched(scratch: Path, changed: str, capfd: pytest.CaptureFixture[str]) -> str:
    """`always_on.touched` over two planted drives and a planted changed set."""
    drives = scratch / "drives"
    drives.mkdir(exist_ok=True)
    rows = []
    for name in ("one", "two"):
        path = drives / f"test_{name}.sh"
        path.write_text("#!/bin/sh\n# drives: deploy/\nexit 0\n")
        rows.append((name, path))
    capfd.readouterr()
    picked = ao.touched(R.Ctx(ROOT, "loop", dict(os.environ)), rows, changed.split(), [], [])
    return capfd.readouterr().out + f"selected: {' '.join(picked)}"


@pytest.mark.parametrize("path", ["quality/tests/drives.py", "quality/could_not_look.py"])
def test_a_change_to_the_judge_touches_every_drive(
    scratch: Path, path: str, capfd: pytest.CaptureFixture[str]
) -> None:
    out = _touched(scratch, path, capfd)
    assert f"always-on (touched): 2 drives cover {path}" in out, out
    assert out.rstrip().endswith("selected: one two"), out


def test_a_change_outside_the_judge_touches_no_undeclaring_drive(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    out = _touched(scratch, "quality/tests/test_harness.py apps/example/api.py", capfd)
    assert out.rstrip().endswith("selected:"), out


def _judge_paths(scratch_repo: Callable[..., Path], files: dict[str, str]) -> list[str]:
    """`drive_judge_paths` over a planted tree: the paths of the judge's set."""
    repo = scratch_repo()
    for rel, body in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(body)
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "add", "-A"], check=True)
    tree = subprocess.run([*git, "write-tree"], capture_output=True, text=True, check=True)
    listing = repo.parent / "listing"
    listing.write_text(
        subprocess.run(
            [*git, "ls-tree", "-r", tree.stdout.strip()], capture_output=True, text=True, check=True
        ).stdout
    )
    script = f". '{ROOT}/scripts/gate_refuse.sh'; . '{ROOT}/scripts/gate_ledger.sh'; "
    script += f"drive_judge_paths '{listing}'"
    done = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return [line.split(" ", 1)[1] for line in done.stdout.splitlines() if line]


def test_a_fixture_module_named_test_is_in_the_judge(scratch_repo: Callable[..., Path]) -> None:
    paths = _judge_paths(
        scratch_repo,
        {
            "quality/tests/test_drives.py": "",
            "quality/tests/fixtures/test_zz.py": "",
            "quality/tests/test_other.py": "",
        },
    )
    assert "quality/tests/fixtures/test_zz.py" in paths, paths
    assert "quality/tests/test_other.py" not in paths, paths


def test_a_module_imported_from_its_package_is_in_the_judge(
    scratch_repo: Callable[..., Path],
) -> None:
    paths = _judge_paths(
        scratch_repo,
        {
            "quality/__init__.py": "",
            "quality/tests/test_drives.py": "from quality import zz_helper, zz_other as other\n",
            "quality/zz_helper.py": "",
            "quality/zz_other.py": "",
        },
    )
    assert {"quality/zz_helper.py", "quality/zz_other.py"} <= set(paths), paths


def _registered() -> list[str]:
    """The drive table's drives plus every `deploy/tests` drive that sources the preamble."""
    from quality.djb.drive_table import DRIVES

    paths = [d.path for d in DRIVES]
    for path in sorted((ROOT / "deploy" / "tests").glob("test_*.sh")):
        rel = path.relative_to(ROOT).as_posix()
        if "drive_preamble.sh" in path.read_text(errors="replace") and rel not in paths:
            paths.append(rel)
    assert paths, "the registered population is empty — a census over nothing asserts nothing"
    return paths


def test_every_registered_drive_calls_drive_finished() -> None:
    finished = re.compile(r"^( {4})?drive_finished$", re.MULTILINE)
    missing = [p for p in _registered() if not finished.search((ROOT / p).read_text())]
    assert missing == []
    assert not finished.search("#!/usr/bin/env bash\ncase_x() { :; }\ncase_x\n")
    assert finished.search("    drive_finished\n") and finished.search("drive_finished\n")


def test_every_registered_drive_keys_cleanly_against_the_measured_tree() -> None:
    from quality.djb import ledger

    tree = ledger.measured_tree(ROOT)
    entries = ledger.listing(ROOT, tree)
    cannot = []
    for path in _registered():
        try:
            ledger.drive_parts(ROOT, tree, path, entries)
        except (ledger.Mismatch, CouldNotLook) as exc:
            cannot.append(f"{path}: {exc}")
    assert cannot == []
