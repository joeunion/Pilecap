"""The rung's secret scan: the set `scope.changed_files` derives, the leg, and the baseline."""

# narrowed: case_a_directory_that_is_no_repository_cannot_look — the CouldNotLook cause, no GATE_LAST_REFUSAL  # noqa: E501
# narrowed: case_a_planted_secret_in_a_changed_file_fails_the_leg — a scratch rung, never this tree
# narrowed: case_the_loop_leg_names_the_preserving_subcommand — `secrets.ARGV` and `supply_chain.SECRETS`  # noqa: E501
# does-not-cover: an untracked, never-staged file — git does not name it, so nothing scans it.
# does-not-cover: detect-secrets' plugin set — two shapes are driven, its catalogue is not.
# does-not-cover: a baseline writer outside `scripts/*.sh` spelled as one string.
# does-not-cover: this tree's baseline at zero results — the hook short-circuits before writing.

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.djb import registry as R
from quality.djb import scope
from quality.djb.legs import secrets, supply_chain
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    ".secrets.baseline",
    ".claude/skills/rung-execution/SKILL.md",
    "scripts/secrets_scan.sh",
    "scripts/pm_fold.sh",
    "quality/djb/rituals/fold.py",
)

ROOT = Path(__file__).resolve().parents[2]
BIN = Path(sys.executable).parent
HOOK = BIN / "detect-secrets-hook"
SCAN = BIN / "detect-secrets"
#: The key prefix, assembled: rule 23's raw scanner reads this file's text.
AKI = "AK" + "I"
SCAN_LINE = "detect-secrets scan --baseline"


def _git(repo: Path, *argv: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(argv)}: {done.stderr}"
    return done.stdout.strip()


def commit_in(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def results(path: Path) -> tuple[list[str], int]:
    """The baseline's result files, sorted, and its entry count."""
    found = json.loads(path.read_text())["results"]
    return sorted(found), sum(len(v) for v in found.values())


# --- the changed set -------------------------------------------------------------


@pytest.fixture
def repo(scratch_repo: Callable[..., Path]) -> Path:
    """main two commits deep — an untouched, a shared, a doomed and a renamed file."""
    root = scratch_repo("repo", "secrets-scan-drive")
    for name, body in (
        ("untouched.txt", "nobody touches this"),
        ("shared.txt", "one"),
        ("doomed.txt", "doomed"),
        ("renamed_from.txt", "before"),
    ):
        (root / name).write_text(f"{body}\n")
    commit_in(root, "the fixture")
    (root / "shared.txt").write_text("two\n")
    commit_in(root, "on main")
    return root


def on_a_rung(repo: Path, work: bool = True) -> None:
    """A `rung` branch from main's parent; `work` commits `rung.txt` on it."""
    _git(repo, "checkout", "-q", "-b", "rung", _git(repo, "rev-parse", "HEAD~1"))
    if work:
        (repo / "rung.txt").write_text("the rung's own work\n")
        commit_in(repo, "rung work")


def collapsed(repo: Path, box: Path) -> Path:
    """A depth-1 clone of `rung` with a local main forced onto it — the box's shape."""
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", "rung", f"file://{repo}", str(box)],
        check=True,
        capture_output=True,
    )
    _git(box, "branch", "-q", "-f", "main", "HEAD")
    _git(box, "checkout", "-q", "main")
    return box


def test_a_committed_change_on_a_branch_is_in_the_set(repo: Path) -> None:
    on_a_rung(repo)
    got = scope.changed_files(repo)
    assert "rung.txt" in got.paths
    assert "1 file(s) committed on 'rung' since the merge-base with main" in got.basis


def test_a_file_the_rung_did_not_touch_is_absent(repo: Path) -> None:
    on_a_rung(repo)
    assert "untouched.txt" not in scope.changed_files(repo).paths


def test_a_change_only_on_main_is_absent(repo: Path) -> None:
    on_a_rung(repo)
    assert "shared.txt" not in scope.changed_files(repo).paths


def test_an_unstaged_edit_is_in_the_set(repo: Path) -> None:
    on_a_rung(repo, work=False)
    with (repo / "untouched.txt").open("a") as sink:
        sink.write("edited, not staged\n")
    assert "untouched.txt" in scope.changed_files(repo).paths


def test_a_staged_new_file_is_in_the_set(repo: Path) -> None:
    on_a_rung(repo, work=False)
    (repo / "staged.txt").write_text("new and staged\n")
    _git(repo, "add", "staged.txt")
    assert "staged.txt" in scope.changed_files(repo).paths


def test_an_untracked_file_is_absent(repo: Path) -> None:
    on_a_rung(repo, work=False)
    (repo / "untracked.txt").write_text("scratch\n")
    assert "untracked.txt" not in scope.changed_files(repo).paths


def test_on_main_only_the_working_tree_is_read(repo: Path) -> None:
    with (repo / "untouched.txt").open("a") as sink:
        sink.write("edited on main\n")
    got = scope.changed_files(repo)
    assert "on main itself" in got.basis
    assert "ONLY this checkout's uncommitted changes were scanned" in got.basis
    assert "untouched.txt" in got.paths
    assert "shared.txt" not in got.paths


def test_a_branch_with_no_commits_yet_reads_the_working_tree(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "rung")
    with (repo / "untouched.txt").open("a") as sink:
        sink.write("not committed yet\n")
    got = scope.changed_files(repo)
    assert "branch 'rung' has committed nothing yet" in got.basis
    assert "untouched.txt" in got.paths


def test_a_committed_deletion_is_excluded_without_erroring(repo: Path) -> None:
    on_a_rung(repo, work=False)
    _git(repo, "rm", "-q", "doomed.txt")
    commit_in(repo, "delete it")
    assert "doomed.txt" not in scope.changed_files(repo).paths


def test_a_working_tree_deletion_is_excluded_without_erroring(repo: Path) -> None:
    on_a_rung(repo, work=False)
    (repo / "doomed.txt").unlink()
    assert "doomed.txt" not in scope.changed_files(repo).paths


def test_a_rename_names_the_destination_that_exists(repo: Path) -> None:
    on_a_rung(repo, work=False)
    _git(repo, "mv", "renamed_from.txt", "renamed_to.txt")
    commit_in(repo, "rename")
    paths = scope.changed_files(repo).paths
    assert "renamed_to.txt" in paths
    assert "renamed_from.txt" not in paths


def test_no_local_main_falls_back_and_says_so(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "rung")
    _git(repo, "branch", "-q", "-m", "main", "trunk")
    with (repo / "untouched.txt").open("a") as sink:
        sink.write("changed\n")
    got = scope.changed_files(repo)
    assert "no local refs/heads/main to fork from" in got.basis
    assert "untouched.txt" in got.paths


def test_a_linked_worktree_derives_against_the_shared_main(repo: Path, scratch: Path) -> None:
    wt = scratch / "wt"
    _git(repo, "worktree", "add", "-q", "-b", "rung", str(wt), _git(repo, "rev-parse", "HEAD~1"))
    (wt / "rung.txt").write_text("the rung's own work\n")
    commit_in(wt, "rung work")
    got = scope.changed_files(wt)
    assert "rung.txt" in got.paths
    assert "since the merge-base with main" in got.basis
    assert "shared.txt" not in got.paths


def test_an_empty_change_set_says_nothing_was_scanned(
    repo: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    rc = secrets.run(R.Ctx(repo, "loop", {"PATH": "/usr/bin:/bin"}))
    out = capfd.readouterr().out
    assert rc == 0
    assert "NOTHING WAS SCANNED" in out
    assert "FULL-TREE scan over `git ls-files` runs at push" in out
    assert "scanning" not in out


def test_a_collapsed_checkout_derives_nothing_without_a_carried_base(
    repo: Path, scratch: Path
) -> None:
    on_a_rung(repo)
    got = scope.changed_files(collapsed(repo, scratch / "box"))
    assert got.paths == []
    assert "on main itself" in got.basis


def test_a_carried_base_gives_the_collapsed_checkout_the_rungs_own_files(
    repo: Path, scratch: Path
) -> None:
    on_a_rung(repo)
    base = _git(repo, "merge-base", "rung", "main")
    box = collapsed(repo, scratch / "box")
    _git(repo, "update-ref", "refs/djb/base", base)
    _git(box, "fetch", "-q", "--depth", "1", f"file://{repo}", "+refs/djb/base:refs/djb/base")
    got = scope.changed_files(box, carried="refs/djb/base")
    assert "rung.txt" in got.paths
    assert "shared.txt" not in got.paths
    assert "CARRIED fork point" in got.basis
    assert "DJB_LOOP_SCOPE_BASE" in got.basis


def test_a_carried_base_never_overrides_a_real_fork_point(repo: Path) -> None:
    on_a_rung(repo)
    _git(repo, "update-ref", "refs/djb/base", _git(repo, "rev-list", "--max-parents=0", "HEAD"))
    got = scope.changed_files(repo, carried="refs/djb/base")
    assert "rung.txt" in got.paths
    assert "untouched.txt" not in got.paths
    assert "since the merge-base with main" in got.basis


def test_a_carried_base_that_resolves_to_nothing_is_ignored(repo: Path, scratch: Path) -> None:
    on_a_rung(repo)
    got = scope.changed_files(collapsed(repo, scratch / "box"), carried="refs/djb/base")
    assert got.paths == []
    assert "on main itself" in got.basis


def test_a_directory_that_is_no_repository_cannot_look(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    lone = scratch / "not-a-repo"
    lone.mkdir()
    env = {"PATH": "/usr/bin:/bin", "GIT_CEILING_DIRECTORIES": str(scratch)}
    assert secrets.run(R.Ctx(lone, "loop", env)) == 2
    said = capfd.readouterr().err
    assert "cause: the secret scan could not read a git directory here" in said


# --- the leg and the real hook ---------------------------------------------------


@pytest.fixture
def real_hook(stub_path: StubPath) -> dict[str, str]:
    """A `uv` that runs this venv's real `detect-secrets-hook`, so the leg judges for real."""
    stub_path.plant("uv", f'#!/bin/sh\nshift\nexec "{BIN}/$@"\n')
    return {"PATH": stub_path.path}


def test_a_planted_secret_in_a_changed_file_fails_the_leg(
    repo: Path, real_hook: dict[str, str], capfd: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(ROOT / ".secrets.baseline", repo / ".secrets.baseline")
    on_a_rung(repo)
    probe = repo / "rung.txt"
    kept = probe.read_text()
    capfd.readouterr()
    assert secrets.run(R.Ctx(repo, "loop", real_hook)) == 0
    assert "basis:" in capfd.readouterr().out
    probe.write_text(kept + "# -----BEGIN RSA " + "PRIVATE KEY-----\n")
    assert secrets.run(R.Ctx(repo, "loop", real_hook)) != 0
    assert "rung.txt" in capfd.readouterr().out
    probe.write_text(kept)
    assert secrets.run(R.Ctx(repo, "loop", real_hook)) == 0


@pytest.fixture
def hook_on(scratch: Path, capture: Callable[..., Captured]) -> Callable[[str, str], Captured]:
    """The real hook over one scratch file, against a copy of this tree's baseline."""
    baseline = scratch / "baseline.json"
    shutil.copy(ROOT / ".secrets.baseline", baseline)

    def run(name: str, body: str) -> Captured:
        (scratch / name).write_text(body)
        return capture([str(HOOK), "--baseline", str(baseline), str(scratch / name)])

    return run


PASSWORDLESS = (
    ("policy.py", 'ORG_OWN_POLICY = {\n    "passwordlessType": "PASSWORDLESS_TYPE_ALLOWED",\n}\n'),
    ("constant.py", 'PASSWORDLESS_TYPE_ALLOWED = "PASSWORDLESS_TYPE_ALLOWED"\n'),
    ("policy.json", '{"policy": {"passwordlessType": "PASSWORDLESS_TYPE_NOT_ALLOWED"}}\n'),
    ("policy.yaml", "passwordlessType: PASSWORDLESS_TYPE_ALLOWED\n"),
)


def test_the_zitadel_passwordless_enum_is_not_a_secret(
    hook_on: Callable[[str, str], Captured],
) -> None:
    for name, body in PASSWORDLESS:
        assert hook_on(name, body).rc == 0, f"the enum in {name} read as a secret"


def test_a_real_secret_on_a_passwordless_line_still_fires(
    hook_on: Callable[[str, str], Captured],
) -> None:
    ran = hook_on("canary.py", f'PASSWORDLESS_TYPE_SIGNING_KEY = "{AKI}AIOSFODNN7EXAMPLE"\n')
    assert ran.rc != 0, "a planted key on a PASSWORDLESS_ line did not fire — the filter is a hole"
    assert "AWS Access Key" in ran.text()


# --- the baseline guard ----------------------------------------------------------


@pytest.fixture
def victim(scratch_repo: Callable[..., Path]) -> Path:
    """Three key-shaped files and a clean one, fully scanned into a baseline with results."""
    root = scratch_repo("victim", "drive")
    for name, last in (("alpha", "E"), ("beta", "F"), ("gamma", "G")):
        (root / f"{name}.py").write_text(f'aws_key = "{AKI}AIOSFODNN7EXAMPL{last}"\n')
    (root / "delta.py").write_text("ordinary = 1\n")
    commit_in(root, "base")
    with (root / ".secrets.baseline").open("w") as sink:
        subprocess.run([str(SCAN), "scan"], cwd=root, stdout=sink, check=True)
    _git(root, "add", ".secrets.baseline")
    shutil.copy(root / ".secrets.baseline", root / "baseline.before")
    return root


def test_the_installed_scanner_names_its_own_version() -> None:
    from detect_secrets.__version__ import VERSION

    print(f"detect-secrets {VERSION} · hook {HOOK} · scan {SCAN}")
    assert HOOK.is_file() and SCAN.is_file(), "the scanner is not in this checkout's venv"
    major, minor, *_ = VERSION.split(".")
    assert major.isdigit() and minor.isdigit(), f"{VERSION!r} is not a version"


def test_the_hook_over_a_partial_set_preserves_the_files_it_did_not_scan(
    victim: Path, capture: Callable[..., Captured]
) -> None:
    before = results(victim / "baseline.before")
    assert before[1] >= 3, "the victim baseline needs three entries to see a drop"
    capture([str(HOOK), "--baseline", ".secrets.baseline", "alpha.py"], cwd=victim)
    assert results(victim / ".secrets.baseline") == before


def test_the_scan_subcommand_over_a_partial_set_drops_them(
    victim: Path, capture: Callable[..., Captured]
) -> None:
    _, before = results(victim / "baseline.before")
    capture([str(SCAN), "scan", "--baseline", ".secrets.baseline", "alpha.py"], cwd=victim)
    _, after = results(victim / ".secrets.baseline")
    assert after < before, "the positive control lost its drop — the hook case is no evidence"


def test_the_loop_shaped_invocation_leaves_this_baseline_byte_identical(
    scratch: Path, capture: Callable[..., Captured]
) -> None:
    copy = scratch / "baseline.json"
    shutil.copy(ROOT / ".secrets.baseline", copy)
    paths = scope.changed_files(ROOT).paths or ["scripts/secrets_scan.sh", "scripts/pm_fold.sh"]
    ran = capture([str(HOOK), "--baseline", str(copy), *paths], cwd=ROOT)
    assert ran.rc in (0, 3), "a finding or a broken scanner — the baseline cannot be judged"
    assert copy.read_bytes() == (ROOT / ".secrets.baseline").read_bytes()
    print(f"live result entries: {results(ROOT / '.secrets.baseline')[1]}")


def test_a_stampless_baseline_is_accepted_by_the_installed_scanner(
    victim: Path, capture: Callable[..., Captured]
) -> None:
    assert '"generated_at"' not in (ROOT / ".secrets.baseline").read_text()
    baseline = victim / ".secrets.baseline"
    data = json.loads(baseline.read_text())
    data.pop("generated_at", None)
    baseline.write_text(json.dumps(data, indent=2) + "\n")
    shutil.copy(baseline, victim / "baseline.before")
    _git(victim, "add", ".secrets.baseline")
    assert capture([str(HOOK), "--baseline", ".secrets.baseline", "delta.py"], cwd=victim).rc == 0
    (victim / "epsilon.py").write_text(f'aws_key = "{AKI}AIOSFODNN7EXAMPLZ"\n')
    assert capture([str(HOOK), "--baseline", ".secrets.baseline", "epsilon.py"], cwd=victim).rc
    assert baseline.read_bytes() == (victim / "baseline.before").read_bytes()


def test_the_loop_leg_names_the_preserving_subcommand() -> None:
    for argv in (secrets.ARGV[0], supply_chain.SECRETS):
        assert argv[2:5] == ("detect-secrets-hook", "--baseline", ".secrets.baseline")
        assert "scan" not in argv


def stray_writers(scripts: Path) -> list[str]:
    """The `scripts/*.sh` other than the fold that invoke the narrowing scan."""
    found = []
    for path in sorted(scripts.glob("*.sh")):
        if path.name == "pm_fold.sh":
            continue
        for line in path.read_text(errors="replace").splitlines():
            if SCAN_LINE in line and not line.lstrip().startswith(("#", "echo ", "printf ")):
                found.append(path.name)
                break
    return found


def scan_argvs(package: Path) -> dict[str, list[list[str]]]:
    """Every `detect-secrets scan` argv literal in the package's modules, by module."""
    found: dict[str, list[list[str]]] = {}
    for path in sorted(package.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(errors="replace"))):
            if not isinstance(node, (ast.List, ast.Tuple)):
                continue
            words = [
                e.value
                for e in node.elts
                if isinstance(e, ast.Constant) and isinstance(e.value, str)
            ]
            if "detect-secrets" in words and "scan" in words:
                found.setdefault(path.relative_to(ROOT).as_posix(), []).append(words)
    return found


def test_the_fold_is_the_only_baseline_writer_and_names_no_paths() -> None:
    found = scan_argvs(ROOT / "quality/djb")
    assert list(found) == ["quality/djb/rituals/fold.py"], f"the baseline's writers: {found}"
    for words in found["quality/djb/rituals/fold.py"]:
        at = words.index("scan")
        assert words[at:] == ["scan", "--baseline", ".secrets.baseline"], (
            f"the fold's re-scan carries path arguments: {words}"
        )
    assert stray_writers(ROOT / "scripts") == []


def test_a_planted_second_writer_in_rung_tidy_is_caught(scratch: Path) -> None:
    copy = scratch / "scripts"
    copy.mkdir()
    for path in (ROOT / "scripts").glob("*.sh"):
        shutil.copy(path, copy / path.name)
    assert (copy / "rung_tidy.sh").is_file()
    assert stray_writers(copy) == [], (
        "the control already names a writer — the plant proves nothing"
    )
    with (copy / "rung_tidy.sh").open("a") as sink:
        sink.write(f"\nuv run {SCAN_LINE} .secrets.baseline apps/core/services.py\n")
    assert stray_writers(copy) == ["rung_tidy.sh"]
