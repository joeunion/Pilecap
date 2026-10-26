"""Each leg runs the commands it declares, as the shell body it ports ran them, with its exits."""

# does-not-cover: a tool's own verdict on this tree — the legs run under `--fast`, not here.

# names, never reads: docs/product/queue-detail.md — the checkout fixture's copy, unlinked

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from quality.djb import registry as R
from quality.djb.legs import _run
from quality.djb.legs import queue_index as queue_leg
from quality.tests.fixtures import shell_gate

pytestmark = pytest.mark.drives("quality/djb/legs/", "scripts/gate_refuse.sh")

ROOT = Path(__file__).resolve().parents[2]
GATE_TEXT = shell_gate.text()
PY = str(ROOT / ".venv/bin/python")
STATIC = [g for g in R.discover() if g.unit == "static"]
#: The static legs born in Python after the port, which no shell body at `SHELL_AT` ran.
BORN_IN_PYTHON = frozenset({"sdk-reference", "threat-census", "collection-census"})
PORTED = [g for g in STATIC if g.name not in BORN_IN_PYTHON]
_FUNCTION = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\(\) *\{ *$")


def _functions(text: str) -> dict[str, str]:
    """Every column-zero shell function's body, by name."""
    bodies: dict[str, str] = {}
    name: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        start = _FUNCTION.match(line)
        if start:
            name, lines = start.group(1), []
        elif name and line.startswith("}"):
            bodies[name] = "\n".join(lines)
            name = None
        elif name:
            lines.append(line)
    return bodies


FUNCTIONS = _functions(GATE_TEXT)


def _shell_body(leg: str) -> str:
    """A leg's shell body to its `gate_run_body` line, and each `check.sh` function it calls."""
    found = re.search(
        rf"^(\w+)\(\) *\{{ *\n(.*?)^gate_run_body {re.escape(leg)} \1 ",
        GATE_TEXT,
        re.MULTILINE | re.DOTALL,
    )
    assert found, f"{leg} has no body before its gate_run_body line in {R.GATE}"
    body = found.group(2)
    called = [FUNCTIONS[w] for w in set(re.findall(r"[a-z_]+", body)) if w in FUNCTIONS]
    return "\n".join([body, *called])


def _spelled(argv: Sequence[str]) -> str:
    return " ".join(argv[1:] if argv[0] == "<checkout python>" else argv)


@pytest.mark.parametrize("leg", PORTED, ids=[g.name for g in PORTED])
def test_every_declared_command_is_in_the_shell_body_it_ports(leg: R.Leg) -> None:
    body = _shell_body(leg.name)
    assert leg.argv, f"{leg.name} declares no command"
    for argv in leg.argv:
        if argv[0] == "source":
            library = (ROOT / argv[1]).read_text()
            assert re.search(rf"^{argv[2]}\(\)", library, re.MULTILINE), argv
            assert argv[2] in body, argv
        else:
            assert _spelled(argv) in body, argv


@pytest.mark.parametrize("leg", PORTED, ids=[g.name for g in PORTED])
def test_every_tool_the_shell_body_runs_is_declared(leg: R.Leg) -> None:
    shell = {
        m.strip()
        for m in re.findall(r"uv run [^\n$`\"']+", _shell_body(leg.name))
        if " -c " not in m and not m.endswith(" -c")
    }
    assert shell <= {_spelled(a) for a in leg.argv}


@pytest.mark.parametrize("leg", PORTED, ids=[g.name for g in PORTED])
def test_every_environment_name_the_leg_sets_the_shell_body_set(leg: R.Leg) -> None:
    module = __import__(f"quality.djb.legs.{leg.name.replace('-', '_')}", fromlist=["ENV"])
    for key, value in getattr(module, "ENV", {}).items():
        assert f"{key}={value}" in _shell_body(leg.name), key


class _Recorder:
    """`subprocess.run` replaced: each call recorded, an exit and its streams supplied."""

    def __init__(self, rc: int = 0, out: str = "", err: str = "") -> None:
        self.calls: list[list[str]] = []
        self.rc, self.out, self.err = rc, out, err

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        for stream, text in ((kw.get("stdout"), self.out), (kw.get("stderr"), self.err)):
            if stream is not None and hasattr(stream, "write") and text:
                stream.write(text.encode())
        return subprocess.CompletedProcess(argv, self.rc)


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Recorder]:
    found = _Recorder()
    monkeypatch.setattr(subprocess, "run", found)
    yield found


def _ctx(mode: str = "fast", root: Path = ROOT) -> R.Ctx:
    return R.Ctx(root, mode, {"PATH": "/usr/bin:/bin"})


@pytest.mark.parametrize("leg", STATIC, ids=[g.name for g in STATIC])
def test_the_body_runs_what_it_declares_in_order(leg: R.Leg, recorder: _Recorder) -> None:
    assert leg.body is not None
    assert leg.body(_ctx("full")) == 0
    want: list[str] = []
    for argv in leg.argv:
        if argv[0] == "source":
            want.append(f"bash::{argv[2]}")
        else:
            want.append(" ".join(PY if w == "<checkout python>" else w for w in argv))
    got = []
    for call in recorder.calls:
        if call[:2] == ["bash", "-c"]:
            got += [f"bash::{a[2]}" for a in leg.argv if a[0] == "source" and a[2] in call[2]]
        else:
            got.append(" ".join(call))
    assert sorted(set(got)) == sorted(set(want))


def test_house_rules_passes_terse_in_loop_and_skips_the_django_leg(recorder: _Recorder) -> None:
    leg = next(g for g in STATIC if g.name == "house-rules")
    assert leg.body is not None
    leg.body(_ctx("loop"))
    assert recorder.calls[-1][-1] == "--terse"
    leg.body(_ctx("fast"))
    assert recorder.calls[-1][-1] == "HEAD"


@pytest.mark.parametrize(
    ("rc", "out", "offered", "broken"),
    [
        (0, "budget: 3\n", False, False),
        (1, "  x budget: 3\n", True, False),
        (1, "rule 7\n", False, False),
        (2, "", False, True),
    ],
    ids=["green", "a-budget-red", "another-red", "broken"],
)
def test_house_rules_returns_the_engine_exit_and_offers_only_on_a_budget(
    rc: int,
    out: str,
    offered: bool,
    broken: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(subprocess, "run", _Recorder(rc, out=out))
    leg = next(g for g in STATIC if g.name == "house-rules")
    assert leg.body is not None
    assert leg.body(_ctx()) == rc
    seen = capsys.readouterr()
    assert ("offer: ./scripts/rung_tidy.sh --budgets" in seen.out) is offered
    assert ("ENFORCEMENT ITSELF IS BROKEN" in seen.err) is broken


@pytest.mark.parametrize("name", ["queue-index", "ledger-check"])
def test_a_callee_exit_2_banner_carries_the_callees_own_cause(
    name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    said = "!! COULD NOT LOOK: the planted record is unreadable\n"
    monkeypatch.setattr(subprocess, "run", _Recorder(2, err=said))
    leg = next(g for g in STATIC if g.name == name)
    assert leg.body is not None
    assert leg.body(_ctx()) == 2
    err = capsys.readouterr().err
    assert "   cause: COULD NOT LOOK: the planted record is unreadable\n" in err
    assert _run.cause_none(ROOT) not in err


@pytest.mark.parametrize("name", ["queue-index", "ledger-check"])
def test_a_callee_that_said_nothing_is_named_as_saying_nothing(
    name: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(subprocess, "run", _Recorder(2))
    leg = next(g for g in STATIC if g.name == name)
    assert leg.body is not None
    assert leg.body(_ctx()) == 2
    assert f"   cause: {_run.cause_none(ROOT)}\n" in capsys.readouterr().err


def test_the_placeholder_is_the_shells_own_sentence() -> None:
    text = (ROOT / "scripts/gate_refuse.sh").read_text()
    assert f"GATE_CAUSE_NONE='{_run.cause_none(ROOT)}'" in text


def test_a_library_exit_2_carries_the_cause_the_library_recorded() -> None:
    rc, cause = _run.library(_ctx(), 'gate_refuse "the planted cause"\nexit 2\n')
    assert (rc, cause) == (2, "the planted cause")


def test_plant_collisions_turns_any_red_into_2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _Recorder(1))
    leg = next(g for g in STATIC if g.name == "plant-collisions")
    assert leg.body is not None and leg.body(_ctx()) == 2


def test_collectstatic_is_a_finding_and_cleans_its_scratch_root(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = _Recorder(1)
    monkeypatch.setattr(subprocess, "run", seen)
    leg = next(g for g in STATIC if g.name == "collectstatic")
    assert leg.body is not None and leg.body(_ctx("full")) == 1
    assert "RED: collectstatic failed (exit 1)" in capsys.readouterr().err


def _venv(checkout: Path) -> Path:
    (checkout / ".venv").symlink_to(ROOT / ".venv")
    return checkout


def test_queue_index_on_a_lost_record_names_the_scripts_own_cause(
    checkout: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    (_venv(checkout) / "docs/product/queue-detail.md").unlink()
    assert queue_leg.run(R.Ctx(checkout, "fast")) == 2
    err = capfd.readouterr().err
    said = _run.cause_of(err)
    assert said and f"   cause: {said}\n" in err
    assert _run.cause_none(ROOT) not in err


def _gate_tests_tree(checkout: Path, planted: str) -> Path:
    tests = _venv(checkout) / "quality/tests"
    for module in tests.rglob("test_*.py"):  # the subpackages too: `deploy/` is ~150 cases
        if module != tests / "test_drives.py":
            module.unlink()
    (tests / "test_zz_planted.py").write_text(planted)
    return checkout


def test_gate_tests_reds_on_a_failing_assertion_planted_in_quality_tests(
    checkout: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    leg = R.discover()
    gate_tests = next(g for g in leg if g.name == "gate-tests")
    assert gate_tests.body is not None
    tree = _gate_tests_tree(checkout, "def test_planted() -> None:\n    assert 1 == 2\n")
    assert gate_tests.body(R.Ctx(tree, "full")) == 1
    assert "test_zz_planted.py::test_planted" in capfd.readouterr().out
    shutil.rmtree(tree / "quality/tests/__pycache__")  # same size, same second: a stale .pyc
    (tree / "quality/tests/test_zz_planted.py").write_text(
        "def test_planted() -> None:\n    assert 1 == 1\n"
    )
    assert gate_tests.body(R.Ctx(tree, "full")) == 0


def test_gate_tests_reds_on_a_type_error_planted_in_quality_tests(
    checkout: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    gate_tests = next(g for g in R.discover() if g.name == "gate-tests")
    assert gate_tests.body is not None
    tree = _gate_tests_tree(checkout, "def test_planted() -> None:\n    n: int = 'one'\n")
    assert gate_tests.body(R.Ctx(tree, "full")) == 1
    assert "test_zz_planted.py:2: error" in capfd.readouterr().out


#: The pre-port engine families whose own errors the gate-tests member's mypy may silence.
SILENCED_FAMILIES = ("quality.engine.*", "quality.checks.*", "quality.worlds", "quality.scan_ahead")


def _silenced_quality_modules(pyproject: str) -> list[str]:
    """Every `quality` module a mypy override silences — `follow_imports` or `ignore_errors`."""
    overrides = tomllib.loads(pyproject)["tool"]["mypy"].get("overrides", [])
    found: list[str] = []
    for block in overrides:
        if block.get("follow_imports") in ("silent", "skip") or block.get("ignore_errors"):
            modules = block["module"]
            found += [modules] if isinstance(modules, str) else list(modules)
    return [m for m in found if m == "quality" or m.startswith("quality.")]


def test_gate_tests_mypy_silences_only_the_declared_engine_families() -> None:
    planted = (
        '[tool.mypy]\n[[tool.mypy.overrides]]\nmodule = ["quality.djb.*"]\nignore_errors = true\n'
    )
    assert _silenced_quality_modules(planted) == ["quality.djb.*"]
    silenced = _silenced_quality_modules((ROOT / "pyproject.toml").read_text())
    outside = [m for m in silenced if m not in SILENCED_FAMILIES]
    assert not outside, f"pyproject.toml silences {outside}: only {SILENCED_FAMILIES} may be"
    assert silenced, "the engine families' override is gone: strict mypy over quality/tests reds"


def test_gate_tests_names_each_failure_in_the_log_as_it_happens() -> None:
    from quality.djb.legs import gate_tests

    pytest_argv = gate_tests.ARGV[0]
    assert "-v" in pytest_argv, f"no per-test result line until the session ends: {pytest_argv}"
    assert "-q" not in pytest_argv, "-q cancels -v: a cut session names no failure"


def _collected_modules() -> list[str]:
    """The test modules pytest itself collects from the member's home, the drive runner out."""
    from quality.djb.legs import gate_tests

    ran = subprocess.run(
        [PY, *("-q" if w == "-v" else w for w in gate_tests.ARGV[0][1:]), "--collect-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ran.returncode == 0, ran.stdout[-2000:] + ran.stderr[-2000:]
    return sorted({line.split("::")[0] for line in ran.stdout.splitlines() if "::" in line})


def test_gate_tests_pieces_partition_the_collection_with_no_module_in_two() -> None:
    from quality.djb.legs import gate_tests

    floor = gate_tests.LEG.pieces
    assert floor > 1, "the member is one piece: the selftest unit's plan cannot split it"
    walls = R.walls_view([ROOT / h for h in R.WALLS_HOMES], R.CI_MACHINE, only=True)
    every = gate_tests.modules(ROOT)
    assert every == _collected_modules()
    lpt = gate_tests.split(ROOT)
    assert lpt.n >= R.pieces_of(walls, gate_tests.NAME, floor)
    for n in sorted({floor, lpt.n}):
        pieces = [gate_tests.piece(every, k, n) for k in range(n)]
        if n == lpt.n:
            pieces = [list(p) for p in lpt.lists]
        flat = [m for p in pieces for m in p]
        assert all(pieces), f"an empty piece of {n}: {[len(p) for p in pieces]}"
        assert len(flat) == len(set(flat)), f"a module is in two of {n} pieces"
        assert sorted(flat) == every, n


def _stub_checkout(tmp_path: Path) -> tuple[Path, Path]:
    """This tree's table, walls and tests behind symlinks; its python a stub recording argv."""
    root, ran = tmp_path / "root", tmp_path / "ran"
    (root / ".venv/bin").mkdir(parents=True)
    for name in ("scripts", "quality"):
        (root / name).symlink_to(ROOT / name)
    py = root / ".venv/bin/python"
    py.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"{ran}"\nexit 0\n')
    py.chmod(0o755)
    return root, ran


def _shard_run(root: Path, ran: Path, k: int, n: int) -> tuple[list[str], int]:
    """The test paths the member's pytest named in shard k/n, and how many mypy runs it made."""
    from quality.djb.legs import gate_tests

    ran.unlink(missing_ok=True)
    env = {"PATH": os.environ["PATH"], "GATE_LEG_UNIT": "selftest"}
    env.update(GATE_SHARD_K=str(k), GATE_SHARD_N=str(n))
    assert gate_tests.LEG.body is not None
    assert gate_tests.LEG.body(R.Ctx(root, "full", env)) == 0
    lines = ran.read_text().splitlines() if ran.exists() else []
    named = [w for x in lines if "pytest" in x.split() for w in x.split() if w.endswith(".py")]
    named += [w for x in lines if "pytest" in x.split() for w in x.split() if w == "quality/tests"]
    return [w for w in named if not w.startswith("--")], sum("mypy" in x.split() for x in lines)


@pytest.mark.parametrize("n", [1, 3, 4])
def test_gate_tests_at_shard_k_of_n_runs_a_strict_subset_and_at_1_of_1_the_whole(
    tmp_path: Path, n: int
) -> None:
    from quality.djb.legs import gate_tests

    root, ran = _stub_checkout(tmp_path)
    every = gate_tests.modules(ROOT)
    seen: list[str] = []
    mypy = 0
    for k in range(1, n + 1):
        named, typed = _shard_run(root, ran, k, n)
        mypy += typed
        if n == 1:
            assert named == [gate_tests.HOME], named
            continue
        assert set(named) < set(every), f"shard {k}/{n} ran {named[:3]} — not a strict subset"
        seen += named
    assert mypy == 1, f"mypy ran {mypy} times over {n} shards"
    if n > 1:
        assert sorted(seen) == every, "the shards' pieces do not add up to the collection"
