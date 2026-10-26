"""`./scripts/take_release.sh`: a scratch product takes a scratch release, step by step."""

# does-not-cover: the census, the SDK step and the gate themselves — stubbed with their own lines.

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from quality.djb.rituals import divergence, feature, take_release

pytestmark = pytest.mark.drives("quality/djb/rituals/take_release.py", "scripts/take_release.sh")

LEAF = "apps/gears/migrations/max_migration.txt"
BASE = divergence.TEMPLATE_BASE_DRAWER
SDK_LINES = """\
== sdk step · abc → v2.0.0
   surface    v2.0.0 (2.0.0): read
census: sdk imports=3 removed=0 unread=0 target=2.0.0
== CLEAN · no product import of a removed SDK name
"""


def _git(root: Path, *argv: str) -> str:
    done = subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=True)
    return done.stdout


def _commit(root: Path, files: dict[str, str], message: str) -> None:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
        _git(root, "add", "--", rel)
    _git(root, "commit", "-q", "-m", message)


def _repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "k@example.com")
    _git(root, "config", "user.name", "k")
    _git(root, "config", "commit.gpgsign", "false")
    return root


@pytest.fixture
def worlds(tmp_path: Path) -> tuple[Path, Path]:
    """A template with `v1.0.0`, a product cloned from it, and the template's `v2.0.0`."""
    template = _repo(tmp_path / "template")
    _commit(template, {"TEMPLATE_VERSION": "1.0.0\n", LEAF: "0001_a\n"}, "v1")
    _git(template, "tag", "v1.0.0")
    product = tmp_path / "product"
    _git(tmp_path, "clone", "-q", "-o", "template", str(template), str(product))
    _git(product, "config", "user.email", "k@example.com")
    _git(product, "config", "user.name", "k")
    _git(product, "config", "commit.gpgsign", "false")
    _commit(template, {"TEMPLATE_VERSION": "2.0.0\n", "apps/core/x.py": "x = 2\n"}, "v2")
    _git(template, "tag", "v2.0.0")
    return template, product


def _runner(answers: dict[str, tuple[int, str]], ran: list[str]) -> feature.Runner:
    """Git for real; the census, the fold, the SDK step and the gate answer as given."""

    def run(root: Path, step: feature.Step, tag: str) -> feature.Ran:
        ran.append(step.name)
        if step.argv[0] == "git":
            return feature.run_step(root, step, tag)
        if step.name == "fold":
            (root / LEAF).write_text("0003_b\n")
        code, text = answers.get(step.name, (0, SDK_LINES if step.name == "sdk" else "ok\n"))
        return feature.Ran(code, 0, root / f"{step.name}.log", text)

    return run


def test_a_clean_release_prints_six_steps_and_the_sdk_lines(
    worlds: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, product = worlds
    ran: list[str] = []
    assert take_release.main(["v2.0.0"], product, _runner({}, ran)) == 0
    said = capsys.readouterr().out
    steps = [
        line.split(" · ")[0]
        for line in said.splitlines()
        if line[:2] in {f"{n}/" for n in "123456"}
    ]
    assert steps == ["1/6 fetch", "2/6 census", "3/6 merge", "4/6 fold", "5/6 sdk", "6/6 gate"]
    assert "    census: sdk imports=3 removed=0 unread=0 target=2.0.0" in said
    assert "    == CLEAN · no product import of a removed SDK name" in said
    assert said.splitlines()[-2:] == [
        "taken: v2.0.0",
        "next: ./scripts/feature.sh <app> --loop for each app you own, then the PR road",
    ]
    assert (product / "TEMPLATE_VERSION").read_text() == "2.0.0\n"
    assert ran == ["fetch", "census", "merge", "sdk", "gate"]


def test_two_leaves_in_one_app_are_folded_and_the_merge_committed(
    worlds: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    template, product = worlds
    _commit(template, {LEAF: "0002_theirs\n"}, "their migration")
    _git(template, "tag", "-f", "v2.0.0")
    _commit(product, {LEAF: "0002_ours\n"}, "our migration")
    ran: list[str] = []
    assert take_release.main(["v2.0.0"], product, _runner({}, ran)) == 0
    assert ran[3] == "fold"
    assert "4/6 fold" in capsys.readouterr().out
    assert _git(product, "status", "--porcelain", "--", ".", f":!{BASE}") == ""
    assert (product / LEAF).read_text() == "0003_b\n"


def test_a_conflict_outside_the_migrations_stops_naming_its_file(
    worlds: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, product = worlds
    _commit(product, {"apps/core/x.py": "x = 'ours'\n"}, "a product edit to a template file")
    assert take_release.main(["v2.0.0"], product, _runner({}, [])) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2].startswith("red: apps/core/x.py — the merge left 1 conflict(s)")
    assert lines[-1] == "next: resolve them, git commit, then ./scripts/take_release.sh v2.0.0"


def test_a_red_census_stops_before_the_merge(
    worlds: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, product = worlds
    census = (1, "  x collides: apps/core/models.py:12: class Gear is the release's own\n")
    ran: list[str] = []
    assert take_release.main(["v2.0.0"], product, _runner({"census": census}, ran)) == 1
    assert ran == ["fetch", "census"]
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2].startswith("red: apps/core/models.py:12 — x collides")
    assert (product / "TEMPLATE_VERSION").read_text() == "1.0.0\n"


def test_a_release_before_the_sdk_step_says_so_and_goes_on(
    worlds: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, product = worlds
    answer = (2, "!! unknown argument '--sdk': divergence_census.sh takes nothing\n")
    assert take_release.main(["v2.0.0"], product, _runner({"sdk": answer}, [])) == 0
    assert "has no --sdk step — a release before the SDK" in capsys.readouterr().out


def test_no_remote_a_dirty_tree_or_no_tag_is_refused(worlds: tuple[Path, Path]) -> None:
    _, product = worlds
    assert take_release.main(["v2.0.0", "--remote", "upstream"], product, _runner({}, [])) == 2
    assert take_release.main([], product, _runner({}, [])) == 2
    assert take_release.main(["v9.9.9"], product, _runner({}, [])) == 2
    (product / "TEMPLATE_VERSION").write_text("dirty\n")
    assert take_release.main(["v2.0.0"], product, _runner({}, [])) == 2


def _rule_60_gate(ran: list[str]) -> feature.Runner:
    """The road's runner; its gate judges as rule 60 does, each `apps/` path against the base."""
    stub = _runner({}, ran)

    def run(root: Path, step: feature.Step, tag: str) -> feature.Ran:
        if step.name != "gate":
            return stub(root, step, tag)
        ran.append(step.name)
        base = divergence.declare_base(root, {})
        assert base is not None
        moved = _git(root, "diff", "--name-only", base.ref, "--", "apps").split()
        text = "".join(
            f"  x rule 60 {p} is template-owned and its content is not the declared base's\n"
            for p in moved
        )
        return feature.Ran(1 if moved else 0, 0, root / "gate.log", text or "ok\n")

    return run


def test_the_base_is_recorded_before_the_gate_so_rule_60_reads_the_release_taken(
    worlds: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, product = worlds
    was = _git(product, "rev-parse", "v1.0.0^{commit}").strip()
    _commit(product, {BASE: f"{was}\n"}, "declared")
    ran: list[str] = []
    assert take_release.main(["v2.0.0"], product, _rule_60_gate(ran)) == 0
    now = _git(product, "rev-parse", "v2.0.0^{commit}").strip()
    assert (product / BASE).read_text() == f"{now}\n"
    said = capsys.readouterr().out
    assert f"    base · {BASE}: {was} → {now} (v2.0.0^{{commit}})" in said
    assert said.index("    base · ") < said.index("6/6 gate")
    assert ran[-1] == "gate"


def test_a_product_that_never_declared_is_told_and_the_base_is_still_written(
    worlds: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, product = worlds
    assert take_release.main(["v2.0.0"], product, _rule_60_gate([])) == 0
    now = _git(product, "rev-parse", "v2.0.0^{commit}").strip()
    assert (product / BASE).read_text() == f"{now}\n"
    said = capsys.readouterr().out
    assert f"    base · {BASE} was absent — this product never declared" in said
    assert f"    base · {BASE}: {now} (v2.0.0^{{commit}})" in said


def test_an_uncommitted_base_from_a_red_road_does_not_refuse_the_rerun(
    worlds: tuple[Path, Path],
) -> None:
    _, product = worlds
    _commit(product, {BASE: _git(product, "rev-parse", "v1.0.0^{commit}")}, "declared")
    assert take_release.main(["v2.0.0"], product, _runner({"gate": (1, "x red\n")}, [])) == 1
    assert _git(product, "status", "--porcelain") == f" M {BASE}\n"
    assert take_release.main(["v2.0.0"], product, _runner({}, [])) == 0


UV_LOCK = 'version = 1\n\n[[package]]\nname = "certifi"\nversion = "{v}"\n'
PNPM_LOCK = "lockfileVersion: '9.0'\n\npackages:\n\n  vite@{v}:\n    resolution: {{}}\n"


def test_newer_locks_are_said(
    worlds: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    template, product = worlds
    locks = {"uv.lock": UV_LOCK, "frontend/pnpm-lock.yaml": PNPM_LOCK}
    _commit(template, {p: t.format(v="1.0.0") for p, t in locks.items()}, "the locks")
    _git(product, "pull", "-q", "--no-rebase", "--no-edit", "template", "main")
    _commit(template, {p: t.format(v="2.0.0") for p, t in locks.items()}, "the release's bumps")
    _git(template, "tag", "-f", "v2.0.0")
    assert take_release.main(["v2.0.0"], product, _runner({}, [])) == 0
    said = capsys.readouterr().out.splitlines()
    line = "    locks: the release's uv.lock/pnpm-lock.yaml are newer than this product's (2 pins)"
    assert line in said, said
    assert said.index(line) == next(i for i, s in enumerate(said) if s.startswith("2/6 census")) + 2


def test_the_same_locks_say_nothing(
    worlds: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    _, product = worlds
    assert take_release.main(["v2.0.0"], product, _runner({}, [])) == 0
    assert "locks:" not in capsys.readouterr().out
