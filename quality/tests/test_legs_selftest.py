"""The `selftest` leg: a drive judged by its exit AND its summary, composed once, 2 first."""

from __future__ import annotations

import ast
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from quality.djb import registry as R
from quality.djb.legs import selftest as st
from quality.tests.fixtures.interpreter import untouched

pytestmark = pytest.mark.drives("quality/djb/legs/selftest.py", "quality/tests/drives.py")

ROOT = Path(__file__).resolve().parents[2]
GREEN = 'echo "{own}: 2 passed · 0 failed · 0 skipped"\nexit 0\n'
RED_SUMMARY = 'echo "  FAILED case_x"\necho "{own}: 1 passed · 3 failed · 0 skipped"\nexit 0\n'
NO_SUMMARY = 'echo "  nothing said"\nexit 0\n'


def _drive(home: Path, name: str, body: str) -> Path:
    path = home / f"test_{name}.sh"
    own = path.stem
    path.write_text(
        "#!/usr/bin/env bash\n# drives: scripts/tests/drive_preamble.sh\n" + body.format(own=own)
    )
    path.chmod(0o755)
    return path


@pytest.fixture
def world(tmp_path: Path) -> dict[str, str]:
    """A scratch drive set, a `uv` that answers the engine's selftest with 0, a scratch ledger."""
    (tmp_path / "drives").mkdir()
    (tmp_path / "bin").mkdir()
    uv = tmp_path / "bin/uv"
    uv.write_text(
        '#!/usr/bin/env bash\nfor a in "$@"; do\n'
        '    [ "$a" != --selftest-inputs ] || { echo scripts/tests/drive_preamble.sh; exit 0; }\n'
        'done\nexit "${DJB_FAKE_UV_RC:-0}"\n'
    )
    uv.chmod(0o755)
    return {
        "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "TMPDIR": str(tmp_path),
        "DJB_SELFTEST_DRIVES_DIR": str(tmp_path / "drives"),
        "DJB_GATE_LEDGER": str(tmp_path / "ledger"),
    }


def _run(world: dict[str, str], **env: str) -> int:
    return st.run(R.Ctx(ROOT, "full", {**world, **env}))


def test_the_leg_claims_the_selftest_line_first_and_gate_tests_stays_last() -> None:
    table = R.load(ROOT)
    members = table.unit("selftest")[1]
    assert table.leg("selftest") is st.LEG
    assert members[0] == "selftest" and members[-1] == "gate-tests"


def test_every_registered_drive_resolves_to_its_file() -> None:
    table = R.load(ROOT)
    named = st.drives(R.Ctx(ROOT, "full", {}), table)
    assert [n for n, _ in named] == list(R.DRIVE_NAMES)
    assert all(p.is_file() for _, p in named)


def test_a_drive_exit_0_with_no_summary_is_could_not_look(
    world: dict[str, str], capfd: pytest.CaptureFixture[str]
) -> None:
    _drive(Path(world["DJB_SELFTEST_DRIVES_DIR"]), "a_quiet", NO_SUMMARY)
    assert _run(world, DJB_SELFTEST_NO_REUSE="1") == 2
    out = capfd.readouterr()
    assert "with no `test_a_quiet:` summary line" in out.err
    assert "!! COULD NOT LOOK: a_quiet" in out.err


def test_a_drive_exit_0_with_a_red_summary_is_red_and_its_failed_lines_are_kept(
    world: dict[str, str], capfd: pytest.CaptureFixture[str]
) -> None:
    _drive(Path(world["DJB_SELFTEST_DRIVES_DIR"]), "b_liar", RED_SUMMARY)
    assert _run(world, DJB_SELFTEST_NO_REUSE="1") == 1
    err = capfd.readouterr().err
    assert "exit 0 but the summary counts 3 failed" in err
    assert "   b_liar: 1 FAILED line(s)\n     FAILED case_x" in err


def test_two_reds_and_a_could_not_look_are_all_named_and_2_outranks(
    world: dict[str, str], capfd: pytest.CaptureFixture[str]
) -> None:
    home = Path(world["DJB_SELFTEST_DRIVES_DIR"])
    for name, body in (("a_red", RED_SUMMARY), ("b_quiet", NO_SUMMARY), ("c_red", RED_SUMMARY)):
        _drive(home, name, body)
    _drive(home, "d_green", GREEN)
    assert _run(world, DJB_SELFTEST_NO_REUSE="1") == 2
    out = capfd.readouterr()
    assert "selftest: 2 drive(s) green · 2 red · 1 could-not-look" in out.out
    assert "!! COULD NOT LOOK: b_quiet" in out.err
    assert "!! and RED: a_red c_red" in out.err


def test_a_red_engine_selftest_still_runs_every_drive_and_the_leg_is_2(
    world: dict[str, str], capfd: pytest.CaptureFixture[str]
) -> None:
    _drive(Path(world["DJB_SELFTEST_DRIVES_DIR"]), "a_green", GREEN)
    assert _run(world, DJB_SELFTEST_NO_REUSE="1", DJB_FAKE_UV_RC="1") == 2
    out = capfd.readouterr()
    assert "drive a_green: exit 0" in out.out
    assert "ENFORCEMENT ITSELF IS BROKEN" in out.err
    assert "!! COULD NOT LOOK: house-rules-engine" in out.err


def test_a_green_drive_banks_and_the_next_run_reuses_it(
    world: dict[str, str], capfd: pytest.CaptureFixture[str]
) -> None:
    _drive(Path(world["DJB_SELFTEST_DRIVES_DIR"]), "a_green", GREEN)
    assert _run(world) == 0
    assert "drive a_green: exit 0" in capfd.readouterr().out
    assert _run(world) == 0
    assert "drive a_green: REUSED from " in capfd.readouterr().out


def test_all_green_prints_one_line_per_member_and_the_summary(
    world: dict[str, str], capfd: pytest.CaptureFixture[str]
) -> None:
    for name in ("a", "b"):
        _drive(Path(world["DJB_SELFTEST_DRIVES_DIR"]), name, GREEN)
    assert _run(world, DJB_SELFTEST_NO_REUSE="1") == 0
    out = capfd.readouterr().out
    for member in ("house-rules-engine", "a", "b"):
        assert f"  drive {member}: exit 0 (" in out
    assert "selftest: 3 drive(s) green · 0 red · 0 could-not-look" in out


def test_a_member_killed_mid_run_reaches_the_log_with_its_output_so_far(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    def killed(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        kw["stdout"].write(b"  half a case\n")
        raise KeyboardInterrupt

    monkeypatch.setattr(subprocess, "run", killed)
    with pytest.raises(KeyboardInterrupt):
        st.run_member(R.Ctx(ROOT, "full", {}), "slow", ["x"], {})
    out = capfd.readouterr().out
    assert "  drive slow: killed after 0s — its output so far:\n  half a case\n" in out


def test_no_member_exits_the_leg() -> None:
    tree = ast.parse((ROOT / "quality/djb/legs/selftest.py").read_text())
    exits = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and (node.func.attr, getattr(node.func.value, "id", ""))
        in {("exit", "sys"), ("_exit", "os")}
        or isinstance(node, ast.Raise)
        and isinstance(node.exc, (ast.Name, ast.Call))
        and "SystemExit" in ast.dump(node.exc)
    ]
    assert exits == []


@pytest.mark.parametrize(
    ("env", "says"),
    [
        ({"GATE_SHARD_K": "x", "GATE_SHARD_N": "2"}, "is not a k/N pair of integers"),
        ({"GATE_SHARD_K": "3", "GATE_SHARD_N": "2"}, "is outside 1..2"),
        ({"GATE_SHARD_K": "1", "GATE_SHARD_N": "0"}, "is outside 1..0"),
    ],
    ids=["not-integers", "k-above-n", "n-zero"],
)
def test_a_malformed_shard_is_2_before_any_member(
    env: dict[str, str], says: str, world: dict[str, str], capfd: pytest.CaptureFixture[str]
) -> None:
    assert _run(world, GATE_LEG_UNIT="selftest", **env) == 2
    out = capfd.readouterr()
    assert says in out.err and "drive house-rules-engine" not in out.out


def test_the_shard_plan_is_longest_first_onto_the_lightest_shard(tmp_path: Path) -> None:
    walls = tmp_path / "scripts/gate_member_durations.json"
    walls.parent.mkdir()
    rows = {"house-rules-engine": 100, "a": 90, "b": 50, "c": 40}
    machine = R._machine()
    walls.write_text(
        '{"measured_at": {}, "members": {'
        + ", ".join(f'"{k}": {{"{machine}": {v}}}' for k, v in rows.items())
        + "}}"
    )
    taken, line = st.plan(R.Ctx(tmp_path, "full", {}), ["a", "b", "c", "d"], 0, 2)
    assert taken == {"house-rules-engine": 0, "a": 1, "b": 0, "c": 0, "d": 1}
    assert line.startswith("  selftest shard 1/2: 3 members, predicted 190 s")


def test_with_no_walls_table_the_engine_is_shard_one_and_drives_go_round_robin(
    tmp_path: Path,
) -> None:
    taken, line = st.plan(R.Ctx(tmp_path, "full", {}), ["a", "b", "c"], 1, 2)
    assert taken == {"house-rules-engine": 0, "a": 0, "b": 1, "c": 0}
    assert "the index round-robin" in line


def test_the_moved_component_is_the_first_whose_digest_changed() -> None:
    assert st.moved("drive:1,judge:2,machine:3", "drive:1,judge:9,machine:3") == "judge"
    assert st.moved("drive:1,gone:2", "drive:1") == "gone"
    assert st.moved("drive:1", "drive:1") == ""


#: The drives whose body spells the preamble their `# drives:` line leaves to the key (train 19).
PREAMBLE_SPELLERS = ("drive_preamble",)


def test_a_drive_named_by_its_absolute_path_keys_as_it_does_relative(tmp_path: Path) -> None:
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(tmp_path)),
        "TMPDIR": str(tmp_path),
        "DJB_GATE_LEDGER": str(tmp_path / "ledger"),
        "MEASURED_START": tree,
    }
    named = [(name, st.drive_file(ROOT, name)) for name in PREAMBLE_SPELLERS]
    assert all(p is not None and p.is_absolute() for _, p in named)
    got, found = st.keys(R.Ctx(ROOT, "full", env), named)  # type: ignore[arg-type]
    assert got == tree
    assert {n: found[n].error for n in PREAMBLE_SPELLERS} == dict.fromkeys(PREAMBLE_SPELLERS, "")


def _stub_root(tmp_path: Path) -> Path:
    """This tree's table and walls behind symlinks, its `.venv` python a stub that records argv."""
    root = tmp_path / "root"
    (root / ".venv/bin").mkdir(parents=True)
    for name in ("scripts", "quality"):
        (root / name).symlink_to(ROOT / name)
    py = root / ".venv/bin/python"
    py.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"{tmp_path / "ran"}"\nexit 0\n')
    py.chmod(0o755)
    return root


def _product_root(tmp_path: Path) -> Path:
    """`_stub_root` with a drawer; `scripts/local`, `quality/local` real dirs, the rest linked."""
    root = tmp_path / "root"
    (root / ".venv/bin").mkdir(parents=True)
    (root / "scripts/local").mkdir(parents=True)
    for child in (ROOT / "scripts").iterdir():
        if child.name != "local":
            (root / "scripts" / child.name).symlink_to(child)
    (root / "quality/local").mkdir(parents=True)
    for child in (ROOT / "quality").iterdir():
        if child.name != "local":
            (root / "quality" / child.name).symlink_to(child)
    (root / "quality/local/rules.yaml").write_text(
        "rule_id_namespace: zzzk6a\ntemplate_rule_ids_through: 98\n"
    )
    py = root / ".venv/bin/python"
    py.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"{tmp_path / "ran"}"\nexit 0\n')
    py.chmod(0o755)
    return root


@pytest.fixture
def product_root(tmp_path: Path) -> Iterator[Path]:
    """`_product_root`, guarded: no write of the test's reaches the shared interpreter."""
    with untouched():
        yield _product_root(tmp_path)


@pytest.mark.parametrize("shard", [None, ("1", "3")])
def test_on_a_product_tree_gate_tests_says_its_line_and_runs_no_session(
    tmp_path: Path,
    product_root: Path,
    capsys: pytest.CaptureFixture[str],
    shard: tuple[str, str] | None,
) -> None:
    from quality.djb.legs import gate_tests

    root = product_root
    env = {"PATH": os.environ["PATH"], "DJB_GATE_LEDGER": str(tmp_path / "ledger")}
    if shard:
        env.update(GATE_LEG_UNIT="selftest", GATE_SHARD_K=shard[0], GATE_SHARD_N=shard[1])
    assert gate_tests.LEG.body is not None
    rc = gate_tests.LEG.body(R.Ctx(root, "full", env))
    assert not (tmp_path / "ran").exists(), "a product tree ran the platform's pytest session"
    assert rc == 0
    assert capsys.readouterr().out.splitlines() == [f"  {gate_tests.ON_A_PRODUCT}"]


def test_on_a_product_tree_the_full_gate_runs_its_own_drawer_tests_and_no_platform_one(
    tmp_path: Path, product_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from quality.djb.legs import gate_tests

    root = product_root
    own = "quality/local/tests/test_acme.py"
    (root / own).parent.mkdir(parents=True)
    (root / own).write_text("def test_acme() -> None:\n    assert True\n")
    assert gate_tests.LEG.body is not None
    rc = gate_tests.LEG.body(R.Ctx(root, "full", {"PATH": os.environ["PATH"]}))
    said = (tmp_path / "ran").read_text()
    assert rc == 0
    assert own in said and "quality/tests" not in said.replace(own, ""), said
    assert capsys.readouterr().out.splitlines() == [
        f"  {gate_tests.ON_A_PRODUCT}",
        f"  gate-tests: the product's own 1 module(s) under {gate_tests.PRODUCT_HOME}",
    ]


def test_on_a_product_tree_the_pr_harness_says_the_same_line_and_runs_no_session(
    tmp_path: Path, product_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from quality.djb.legs import gate_tests

    root = product_root
    for argv in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "the product"]):
        git = ["git", "-c", "user.email=a@b", "-c", "user.name=a", "-C", str(root), *argv]
        subprocess.run(git, check=True, capture_output=True)
    env = {"PATH": os.environ["PATH"], "GATE_PR": "1", "GATE_PR_BASE": "HEAD"}
    assert gate_tests.LEG.body is not None
    rc = gate_tests.LEG.body(R.Ctx(root, "full", env))
    assert not (tmp_path / "ran").exists(), "a product tree's --pr ran the platform's gate tests"
    assert rc == 0
    assert capsys.readouterr().out.splitlines() == [f"  {gate_tests.ON_A_PRODUCT}"]


@pytest.mark.parametrize("n", [2, 3])
def test_each_gate_tests_piece_runs_in_the_one_shard_the_plan_gives_it(
    tmp_path: Path, n: int
) -> None:
    from quality.djb.legs import gate_tests

    root = _stub_root(tmp_path)
    ran = tmp_path / "ran"
    hosts: dict[int, list[int]] = {}
    for k in range(1, n + 1):
        env = {"PATH": os.environ["PATH"], "GATE_LEG_UNIT": "selftest"}
        env.update(GATE_SHARD_K=str(k), GATE_SHARD_N=str(n))
        ran.unlink(missing_ok=True)
        assert gate_tests.LEG.body is not None
        assert gate_tests.LEG.body(R.Ctx(root, "full", env)) == 0
        plan = gate_tests.held(R.Ctx(root, "full", env))
        assert plan is not None
        hosts[k], of = sorted(plan[0]), plan[1]
        assert ran.exists() == bool(hosts[k]), f"shard {k}/{n} ran pytest holding no piece"
    taken, _ = st.unit_plan(R.Ctx(root, "full", {}), R.load(root), 0, n)
    assert of == sum(1 for m in taken if m.startswith(f"gate-tests{R.PIECE}")) >= gate_tests.FLOOR
    for i in range(of):
        held_by = [k for k, pieces in hosts.items() if i in pieces]
        assert held_by == [taken[R.piece_name("gate-tests", i + 1)] + 1], (i, hosts)


def _junit_root(tmp_path: Path, mypy_rc: int) -> Path:
    """`_stub_root` whose python exits `mypy_rc` for mypy and writes junit for the modules named."""
    root = _stub_root(tmp_path)
    (root / ".venv/bin/python").write_text(
        "#!/usr/bin/env bash\n"
        f'case " $* " in *" mypy "*) exit {mypy_rc};; esac\n'
        'xml=""; mods=""\n'
        'for a in "$@"; do case "$a" in --junitxml=*) xml="${a#--junitxml=}";;'
        ' *.py) mods="$mods $a";; esac; done\n'
        '[ -n "$xml" ] || exit 0\n'
        '{ echo "<testsuites><testsuite>"; for m in $mods; do c=${m%.py}; c=${c//\\//.};'
        ' echo "<testcase classname=\\"$c\\" name=\\"t\\" time=\\"1.5\\"/>"; done;'
        ' echo "</testsuite></testsuites>"; } >"$xml"\n'
    )
    return root


def test_each_piece_writes_its_module_rows_and_the_fold_harvests_the_column(
    tmp_path: Path,
) -> None:
    from quality.djb import ledger
    from quality.djb.legs import gate_tests
    from quality.djb.rituals.fold import modules_judgement

    root, sink, n = _junit_root(tmp_path, 0), tmp_path / "walls", 4
    for k in range(1, n + 1):
        env = {"PATH": os.environ["PATH"], "GATE_LEG_UNIT": "selftest"}
        env.update(GATE_SHARD_K=str(k), GATE_SHARD_N=str(n), DJB_MEMBER_WALLS_OUT=str(sink))
        assert gate_tests.LEG.body is not None
        assert gate_tests.LEG.body(R.Ctx(root, "full", env)) == 0
    rows = sink.read_text().splitlines()
    units = [r for r in rows if r.startswith(f"{R.MODULE_ROW}\t")]
    assert units, "no piece wrote a module-walls row"
    every = gate_tests.modules(ROOT)
    assert modules_judgement(units, {gate_tests.NAME: every}, rows) == ""
    table = tmp_path / "table.json"
    ledger.store_module_walls(table, "ubuntu-latest", "run:1 tree:a", {m: 1.5 for m in every})
    assert ledger.module_durations([table], "ubuntu-latest") == dict.fromkeys(every, 1.5)


def test_a_shard_whose_mypy_exits_2_still_writes_its_member_row_red(tmp_path: Path) -> None:
    from quality.djb.legs import gate_tests

    root, sink = _junit_root(tmp_path, 2), tmp_path / "walls"
    env = {
        "PATH": os.environ["PATH"],
        "GATE_LEG_UNIT": "selftest",
        "DJB_MEMBER_WALLS_OUT": str(sink),
    }
    env.update(GATE_SHARD_K="1", GATE_SHARD_N="1")
    assert gate_tests.LEG.body is not None
    assert gate_tests.LEG.body(R.Ctx(root, "full", env)) == 2
    rows = sink.read_text().splitlines() if sink.exists() else []
    member = [r.split("\t")[:3] for r in rows if r.startswith("member-walls/1\t")]
    assert member == [["member-walls/1", gate_tests.NAME, "2"]], rows


@pytest.mark.parametrize("n", [1, 4])
def test_the_gate_tests_pieces_write_rows_the_fold_harvests_as_one_member(
    tmp_path: Path, n: int
) -> None:
    from quality.djb.legs import gate_tests
    from quality.djb.rituals.fold import walls_judgement, whole_rows

    root = _stub_root(tmp_path)
    sink = tmp_path / "walls"
    for k in range(1, n + 1):
        env = {"PATH": os.environ["PATH"], "GATE_LEG_UNIT": "selftest"}
        env.update(GATE_SHARD_K=str(k), GATE_SHARD_N=str(n), DJB_MEMBER_WALLS_OUT=str(sink))
        assert gate_tests.LEG.body is not None
        assert gate_tests.LEG.body(R.Ctx(root, "full", env)) == 0
    rows = sink.read_text().splitlines() if sink.exists() else []
    assert rows, f"no gate-tests piece over {n} shard(s) wrote a member-walls row"
    folded, gap = whole_rows(rows)
    assert gap == "", gap
    assert walls_judgement(folded, [gate_tests.NAME]) == "", folded
    assert [r.split("\t")[:3] for r in folded] == [["member-walls/1", gate_tests.NAME, "0"]]


# --- the per-rule column: the engine's line, the leg's rows, the fold's harvest -------------

ENGINE_TEXT = (
    "  rule 41 routes-contract: canaries 3/3 · negatives 2/2 — ok\n"
    "  rule-wall 41: 6.5 s\n"
    "  rule 7 depends-on-honest: DISABLED — not planted\n"
    "  rule-wall 7: 0.0 s\n"
    "  rule-wall @whole: 2.0 s — the legs, the seam, the budget canary and the censuses\n"
)


def test_the_engine_spells_the_line_the_leg_reads_and_the_same_whole_id() -> None:
    import importlib

    engine = importlib.import_module("quality.engine.selftest")
    assert engine.WHOLE_PARTS == R.RULE_WHOLE
    assert st.rule_walls(f"  rule-wall 41: {6.54:.1f} s\n") == {"41": 6.5}
    assert st.rule_walls("  rule 41 routes-contract: canaries 3/3 · negatives 2/2 — ok\n") == {}


def test_each_rule_wall_line_is_one_rule_row_and_the_rest_is_fixed(tmp_path: Path) -> None:
    sink = tmp_path / "walls.tsv"
    st.rules_append(
        R.Ctx(ROOT, "full", {"DJB_MEMBER_WALLS_OUT": str(sink)}), ENGINE_TEXT, 20, "2/4"
    )
    rows = [line.split("\t") for line in sink.read_text().splitlines()]
    assert rows == [
        [R.RULE_ROW, "41", "6.5", "2/4"],
        [R.RULE_ROW, "7", "0.0", "2/4"],
        [R.RULE_ROW, R.RULE_WHOLE, "2.0", "2/4"],
        [R.RULE_ROW, R.RULE_FIXED, "11.5", "2/4"],
    ]
    st.rules_append(R.Ctx(ROOT, "full", {}), ENGINE_TEXT, 20, "2/4")
    assert len(sink.read_text().splitlines()) == 4, "a run that asked for no rows wrote some"


def _rule_rows(*pairs: tuple[str, str]) -> list[str]:
    return [f"{R.RULE_ROW}\t{rid}\t{secs}\t1/1" for rid, secs in pairs]


ENGINE_GREEN = [f"member-walls/1\t{R.ENGINE_MEMBER}\t0\t30\t1/1"]


@pytest.mark.parametrize(
    ("rows", "walls", "says"),
    [
        (_rule_rows(("41", "6.5"), ("7", "0.0")), ENGINE_GREEN, ""),
        (_rule_rows(("41", "6.5")), ENGINE_GREEN, "missing against the engine's rules: 7"),
        (
            _rule_rows(("41", "6.5"), ("7", "0.0"), ("41", "1.0")),
            ENGINE_GREEN,
            "timed twice: 41",
        ),
        (
            _rule_rows(("41", "6.5"), ("7", "0.0")),
            [f"member-walls/1\t{R.ENGINE_MEMBER}#2/3\t2\t30\t1/1"],
            "engine not green: house-rules-engine#2/3(exit 2)",
        ),
        (_rule_rows(("41", "6.5"), ("7", "0.0")), [], "no engine row green in this run"),
        (_rule_rows(("41", "6.5"), ("7", "0.0"), ("99", "1")), ENGINE_GREEN, "not a rule of"),
    ],
)
def test_the_per_rule_harvest_is_whole_or_names_why_not(
    rows: list[str], walls: list[str], says: str
) -> None:
    from quality.djb.rituals.fold import rules_judgement

    rows = [*rows, *_rule_rows((R.RULE_WHOLE, "2.0"), (R.RULE_FIXED, "9.0"))]
    why = rules_judgement(rows, ["41", "7"], walls)
    assert (why == "") if not says else (says in why), why


def test_the_per_rule_column_survives_a_member_write_and_reads_by_column(tmp_path: Path) -> None:
    from quality.djb import ledger

    table = tmp_path / "walls.json"
    ledger.store_durations(table, "ubuntu-latest", "run:1 tree:a", {R.ENGINE_MEMBER: 900})
    ledger.store_rule_walls(table, "ubuntu-latest", "run:1 tree:a", {"41": 6.54, "7": 0.0})
    ledger.store_durations(table, "darwin", "tree:b", {R.ENGINE_MEMBER: 200})
    assert ledger.rule_durations([table], "ubuntu-latest") == {"41": 6.5, "7": 0.0}
    assert ledger.durations(tmp_path, "darwin", homes=[table]) == {R.ENGINE_MEMBER: 200}
    ledger.store_rule_walls(table, "ubuntu-latest", "run:2 tree:c", {"41": 3.0})
    assert ledger.rule_durations([table], "ubuntu-latest") == {"41": 3.0}, "the column replaced"


# --- the engine as members -------------------------------------------------------------


def test_the_shard_holds_the_engine_whole_or_its_members_by_the_plan() -> None:
    whole = {R.ENGINE_MEMBER: 1, "a": 0}
    assert st.engine_held(whole, 1) == (1, [1]) and st.engine_held(whole, 0) == (1, [])
    split = {R.piece_name(R.ENGINE_MEMBER, k): s for k, s in ((1, 0), (2, 1), (3, 0))}
    assert st.engine_held(split, 0) == (3, [1, 3]) and st.engine_held(split, 2) == (3, [])


def test_the_members_lists_go_by_count_without_a_column_and_by_lpt_with_one(
    tmp_path: Path,
) -> None:
    ctx = R.Ctx(tmp_path, "full", {})
    ids = ["1", "2", "3", "4", "5"]
    lists, how = st.engine_lists(ctx, ids, 2)
    assert lists == [["1", "3", "5"], ["2", "4"]] and how == "by count (no per-rule column)"
    from quality.djb import ledger

    table = tmp_path / R.WALLS_HOMES[0]
    table.parent.mkdir(parents=True)
    secs = {"1": 50.0, "2": 10.0, "3": 10.0, "4": 10.0, "5": 10.0, R.RULE_WHOLE: 30.0}
    ledger.store_rule_walls(table, R._machine(), "run:1 tree:a", secs)
    lists, how = st.engine_lists(ctx, ids, 2)
    assert lists == [["2", "3", "4"], ["1", "5"]], "the whole parts' 30 s sit on member 1 first"
    assert how.startswith("LPT over the per-rule column (0 unmeasured"), how
    assert st.partition_gap(ids, lists) == ""


def test_a_partition_gap_names_the_lost_the_doubled_and_the_stranger() -> None:
    assert st.partition_gap(["1", "2", "3"], [["1"], ["2", "3"]]) == ""
    gap = st.partition_gap(["1", "2", "3"], [["1", "2"], ["2", "9"]])
    assert gap == "in two members: 2; in no member: 3; no rule: 9", gap


def test_a_split_members_rows_fold_into_one_row_or_name_the_gap() -> None:
    from quality.djb.rituals.fold import whole_rows

    e = R.ENGINE_MEMBER
    rows = [
        f"member-walls/1\t{e}#1,3/3\t0\t400\t2/4",
        f"member-walls/1\t{e}#2/3\t0\t450\t3/4",
        "member-walls/1\tfast_censuses\t0\t6\t4/4",
    ]
    folded, gap = whole_rows(rows)
    assert gap == "" and f"member-walls/1\t{e}\t0\t850\t2/4+3/4" in folded, folded
    _, gap = whole_rows(rows[:1])
    assert gap == f"split member incomplete: {e}(members 1,3 of 3)", gap
    folded, _ = whole_rows([rows[0], rows[1].replace("\t0\t450", "\t2\t450")])
    assert folded[0].split("\t")[2] == "2", "a red member is the member's red"


UV_SAID = "error: No interpreter found for Python 3.12 in managed installations"


def _refusing(stderr: str, stdout: str = "") -> Any:
    def run(argv: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        text = kwargs.get("text")
        out, err = (stdout, stderr) if text else (stdout.encode(), stderr.encode())
        return subprocess.CompletedProcess(argv, 2, out, err)

    return run


def test_rule_ids_that_did_not_answer_quote_the_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(subprocess, "run", _refusing(UV_SAID))
    with pytest.raises(ValueError) as refused:
        st.rule_ids(R.Ctx(ROOT, "full", {}))
    assert f"did not answer (exit 2)\n   the tool said: {UV_SAID}" in str(refused.value)


def test_selftest_inputs_that_exited_quote_the_tool_and_name_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(st, "engine_dir", lambda ctx: tmp_path)
    monkeypatch.setattr(subprocess, "run", _refusing(f"Traceback\n{UV_SAID}\n"))
    path, why = st.engine_drive_file(R.Ctx(ROOT, "full", {}), "t")
    assert path == ""
    assert str(tmp_path / "inputs.err") in why, why
    assert f"\n   the tool said: {UV_SAID}" in why, why
