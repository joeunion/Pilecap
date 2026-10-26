"""The registry's table: discovered, validated at load, and byte-equal to the shell's listing."""

# does-not-cover: what a drawer leg runs — test_drawer.py runs them; this reads their headers.

# moved: test_the_listing_reads_through_a_pipe_and_the_census_refuses_one — this module, renamed

from __future__ import annotations

import importlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from quality import loop_key
from quality.could_not_look import CouldNotLook
from quality.djb import cli
from quality.djb import registry as R
from quality.tests.fixtures import shell_gate
from quality.tests.fixtures.dry_clone import base_of, clone_into

pytestmark = pytest.mark.drives("quality/djb/registry.py", "quality/djb/cli.py")

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = Path(__file__).parent / "golden"
#: The one field the listing may move against the shell's: the selftest unit's needs gain `network`.
PERMITTED_NEED = "network"


def _rows(text: str) -> dict[str, list[str]]:
    return {line.split("\t")[0]: line.split("\t") for line in text.splitlines()}


def _shell_drives() -> list[str]:
    """The drives `check.sh` registers, read here by a pattern of this test's own."""
    pattern = r"^\./(?:scripts|deploy)/tests/test_([a-z_]+)\.sh$"
    return re.findall(pattern, shell_gate.text(), re.MULTILINE)


def _walls_count(members: list[str]) -> int:
    """The CI shard count recomputed from the walls table: ceil(sum / max(heaviest, 300))."""
    doc = json.loads((ROOT / R.WALLS_HOMES[0]).read_text())
    walls = {n: row[R.CI_MACHINE] for n, row in doc["members"].items() if R.CI_MACHINE in row}
    population = ["house-rules-engine", *(m for m in members if m != "selftest")]
    homes = [ROOT / h for h in R.WALLS_HOMES]
    parts = R.member_parts(homes, R.CI_MACHINE, _table().units(ROOT))
    floors = {"house-rules-engine": 1, **_table().pieces()}
    for name, floor in floors.items():
        if name not in walls:
            continue
        loads = R.split_member(walls[name], floor, parts.get(name)).loads
        split = [R.piece_name(name, k) for k in range(1, len(loads) + 1)]
        at = population.index(name)
        population[at : at + 1] = split
        walls.update(dict(zip(split, loads, strict=True)))
    seen = sorted(walls[n] for n in population if n in walls)
    mid = len(seen) // 2
    median = seen[mid] if len(seen) % 2 else int((seen[mid - 1] + seen[mid]) / 2)
    weights = [walls.get(n, median) for n in population]
    bound = max(max(weights), R.SHARD_CEILING_S)
    n = max(1, int(math.ceil(sum(weights) / max(max(weights), R.SHARD_FLOOR_S))))
    while n < len(weights) and R.lpt_heaviest(weights, n) > bound:
        n += 1
    return n


def _table() -> R.Table:
    return R.load(ROOT)


@pytest.mark.parametrize("ci", [False, True], ids=["plain", "ci"])
def test_the_listing_is_byte_identical_to_the_golden_but_the_selftest_line(ci: bool) -> None:
    golden = (GOLDEN / ("list_legs_ci.txt" if ci else "list_legs.txt")).read_text()
    mine = R.list_legs(_table(), ci=ci, root=ROOT)
    assert [u for u in _rows(mine)] == [u for u in _rows(golden)]
    for unit, row in _rows(mine).items():
        if unit != "selftest":
            assert row == _rows(golden)[unit], unit


@pytest.mark.parametrize("ci", [False, True], ids=["plain", "ci"])
def test_the_selftest_line_moves_by_its_need_and_its_derived_tail(ci: bool) -> None:
    golden = _rows((GOLDEN / ("list_legs_ci.txt" if ci else "list_legs.txt")).read_text())
    row = _rows(R.list_legs(_table(), ci=ci, root=ROOT))["selftest"]
    assert row[1] == golden["selftest"][1] and row[1].endswith(f",{PERMITTED_NEED}")
    shell = {name for name, _ in R.shell_legs(shell_gate.text())}
    python_members = [g.name for g in _table().legs if g.unit == "selftest" and g.name not in shell]
    members = ["selftest", *_shell_drives(), *python_members]
    assert row[3] == ",".join(members)
    assert row[2] == (str(_walls_count(members)) if ci else golden["selftest"][2])
    if ci:
        assert row[4] == golden["selftest"][4]


def test_the_listing_equals_the_shells_on_a_checkout_of_head(
    checkout: Path, gate: Callable[..., object]
) -> None:
    for ci in (False, True):
        ran = gate("--list-legs", *(["--ci"] if ci else []), cwd=checkout)
        assert ran.rc == 0, ran.text()  # type: ignore[attr-defined]
        shell = _rows(ran.text())  # type: ignore[attr-defined]
        mine = _rows(R.list_legs(R.load(checkout), ci=ci, root=checkout))
        assert mine == shell


def test_the_pin_can_fail_two_legs_swapped_red_the_static_line() -> None:
    legs = list(R.discover())
    ruff = next(g for g in legs if g.name == "ruff")
    mypy = next(g for g in legs if g.name == "mypy")
    lint = next(g for g in legs if g.name == "import-linter")
    ref = next(g for g in legs if g.name == "sdk-reference")
    swapped = [g for g in legs if g.name not in {"ruff", "sdk-reference", "mypy", "import-linter"}]
    swapped += [
        R.Leg("mypy", "static", mypy.banner, mypy.body, "db-pin", argv=mypy.argv),
        R.Leg("ruff", "static", ruff.banner, ruff.body, "mypy", argv=ruff.argv),
        R.Leg("sdk-reference", "static", ref.banner, ref.body, "ruff", argv=ref.argv),
        R.Leg("import-linter", "static", lint.banner, lint.body, "sdk-reference", argv=lint.argv),
    ]
    golden = (GOLDEN / "list_legs.txt").read_text()
    mine = R.list_legs(R.build(swapped, shell_gate.text()), ci=False)
    assert _rows(mine)["static"] != _rows(golden)["static"]
    assert _rows(mine)["static"][3].startswith("db-pin,mypy,ruff,")


def _leg(name: str, unit: str = "static", after: str | None = None, **kw: object) -> R.Leg:
    return R.Leg(name, unit, name, lambda ctx: 0, after, **kw)  # type: ignore[arg-type]


GATE_ONE = textwrap.dedent(
    """\
    gate_unit static db 0
    gate_unit selftest db N-capable
    gate_run_body old gate_leg_old static "old"
    gate_run_body selftest gate_leg_selftest selftest "selftest"
    ./scripts/tests/test_one.sh
    """
)
UNITS_ONE = (R.Unit("static", ("db",), "0"), R.Unit("selftest", ("db",), "N-capable"))


@pytest.mark.parametrize(
    ("legs", "gate_text", "says"),
    [
        ([_leg("a"), _leg("a", after="a")], GATE_ONE, "two legs are named 'a'"),
        ([_leg("a", unit="nowhere")], GATE_ONE, "names unit 'nowhere'"),
        ([_leg("old", unit="selftest")], GATE_ONE, "a leg in two units"),
        ([_leg("a"), _leg("b")], GATE_ONE, "exactly one leads"),
        ([_leg("a"), _leg("b", after="zz")], GATE_ONE, "no Python leg of unit 'static'"),
        ([_leg("a"), _leg("b", after="a"), _leg("c", after="a")], GATE_ONE, "both follow 'a'"),
        ([_leg("a"), _leg("b", after="c"), _leg("c", after="b")], GATE_ONE, "in a cycle"),
        ([_leg("a", modes=frozenset({"weekly"}))], GATE_ONE, "names modes ['weekly']"),
        ([_leg("a", modes=frozenset({"full"}))], GATE_ONE, "mode 'fast' names no leg"),
        ([_leg("a")], GATE_ONE.replace("gate_unit selftest", "gate_unit other"), "one table"),
        ([_leg("a")], GATE_ONE + 'gate_run_body x gate_leg_x stray "x"\n', "unit 'stray'"),
        ([_leg("a")], GATE_ONE + "./scripts/tests/test_one.sh\n", "registered twice"),
        (
            [_leg("a")],
            "gate_unit static db 0\ngate_unit selftest db N-capable\n",
            "unit 'selftest' has no leg",
        ),
    ],
    ids=[
        "two-legs-one-name",
        "a-unit-nobody-declared",
        "a-leg-in-two-units",
        "two-heads",
        "after-names-nothing",
        "two-follow-one",
        "a-cycle",
        "an-unknown-mode",
        "a-mode-with-no-leg",
        "the-shell-table-drifted",
        "a-shell-leg-in-an-undeclared-unit",
        "a-drive-registered-twice",
        "a-unit-with-no-leg",
    ],
)
def test_the_table_refuses_at_load(legs: list[R.Leg], gate_text: str, says: str) -> None:
    with pytest.raises(R.RegistryError, match=re.escape(says)):
        R.build(legs, gate_text, UNITS_ONE, R.shell_drives(gate_text))


def test_a_still_shell_leg_the_registry_does_not_carry_is_listed_from_the_shell() -> None:
    table = R.build([_leg("a")], GATE_ONE, UNITS_ONE, R.shell_drives(GATE_ONE))
    assert table.rows[0][1] == ("old", "a")
    assert table.rows[1][1] == ("selftest", "one")


def test_a_python_leg_shadows_the_shell_line_of_its_own_name() -> None:
    table = R.build([_leg("old")], GATE_ONE, UNITS_ONE, R.shell_drives(GATE_ONE))
    assert table.rows[0][1] == ("old",)


def _plant_package(scratch: Path, name: str, modules: dict[str, str]) -> str:
    home = scratch / name
    home.mkdir()
    (home / "__init__.py").write_text("")
    for module, text in modules.items():
        (home / f"{module}.py").write_text(textwrap.dedent(text))
    sys.path.insert(0, str(scratch))
    return name


def test_a_module_that_declares_no_leg_is_refused(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "path", list(sys.path))
    package = _plant_package(scratch, "planted_legs_none", {"stray": "X = 1\n", "_helper": ""})
    with pytest.raises(R.RegistryError, match="planted_legs_none.stray declares no `LEG"):
        R.discover(package)


def test_a_planted_leg_module_is_discovered_with_no_edit(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "path", list(sys.path))
    leg = """\
        from quality.djb.registry import Leg
        LEG = Leg("planted", "static", "planted", lambda ctx: 0)
        """
    package = _plant_package(scratch, "planted_legs_one", {"planted": leg, "_helper": ""})
    assert [g.name for g in R.discover(package)] == ["planted"]


def test_every_module_under_the_legs_package_is_one_leg() -> None:
    modules = sorted(
        p.stem for p in (ROOT / "quality/djb/legs").glob("*.py") if not p.stem.startswith("_")
    )
    declared = [importlib.import_module(f"{R.LEGS_PACKAGE}.{m}").LEG for m in modules]
    assert all(isinstance(g, R.Leg) for g in declared)
    assert sorted(g.name for g in declared) == sorted(g.name for g in R.discover())


def test_a_product_drive_joins_the_selftest_unit_after_the_templates_drives(
    scratch: Path,
) -> None:
    tree = _tree_without_drawer(scratch)
    home = tree / R.DRAWERS[1]
    home.mkdir(parents=True)
    drive = home / "test_acme.sh"
    drive.write_text("#!/usr/bin/env bash\n. scripts/tests/drive_preamble.sh\nexit 0\n")
    drive.chmod(0o755)
    members = _rows(R.list_legs(R.load(tree), ci=False, root=tree))["selftest"][3].split(",")
    assert members[-1] == "local:acme"
    assert members[:-1] == _rows(R.list_legs(_table(), ci=False))["selftest"][3].split(",")
    for text in (
        "#!/usr/bin/env bash\n# does not source drive_preamble.sh\nexit 0\n",
        "#!/usr/bin/env bash\necho no preamble\nexit 0\n",
    ):
        drive.write_text(text)
        with pytest.raises(R.RegistryError, match="does not source"):
            R.load(tree)
    drive.unlink()
    (home / "test_Probe.sh").write_text(
        "#!/usr/bin/env bash\n. scripts/tests/drive_preamble.sh\nexit 0\n"
    )
    (home / "test_Probe.sh").chmod(0o755)
    with pytest.raises(R.RegistryError, match="'Probe' is not a drive name"):
        R.load(tree)


def test_the_check_modules_are_derived_from_the_static_legs_argv() -> None:
    table = _table()
    runs = {
        (word, argv[i + 1])
        for g in table.legs
        if g.unit == "static"
        for argv in g.argv
        for i, word in enumerate(argv[:-1])
    }
    assert {m for m, flag in runs if m.startswith("scripts/") and flag == "--check"} == set(
        table.check_modules()
    )
    assert {"scripts/ledger_check.py", "scripts/queue_index.py"} <= table.check_modules()


def test_the_fast_mode_is_the_static_unit_before_check_deploy() -> None:
    table = _table()
    static = list(table.unit("static")[1])
    assert [g.name for g in table.mode_legs("fast")] == static[: static.index("deploy-check")]


def test_the_engine_is_cut_into_members_under_the_ceiling() -> None:
    assert R.SHARD_CEILING_S == 600
    assert [R.engine_pieces({R.ENGINE_MEMBER: s}) for s in (1432, 600, 601, 90)] == [3, 1, 2, 1]
    assert R.engine_pieces({}) == 1, "an unmeasured engine is one member"
    priced, names = R.pieced({R.ENGINE_MEMBER: 1500, "a": 10}, [R.ENGINE_MEMBER, "a"], {})
    assert names == [R.piece_name(R.ENGINE_MEMBER, k) for k in (1, 2, 3)] + ["a"]
    assert priced[R.piece_name(R.ENGINE_MEMBER, 2)] == 500
    _, named = R.pieced({R.ENGINE_MEMBER: 1500}, [R.ENGINE_MEMBER], {R.ENGINE_MEMBER: 1})
    assert len(named) == 3, "a declared count is a floor: it never lowers the derived one"
    _, named = R.pieced({R.ENGINE_MEMBER: 1500}, [R.ENGINE_MEMBER], {R.ENGINE_MEMBER: 4})
    assert len(named) == 4, "and it raises it"


def test_the_shard_count_rises_until_no_planned_shard_passes_the_ceiling() -> None:
    walls = {"a": 550, "b": 350, "c": 350, "d": 350, "e": 350}
    assert math.ceil(sum(walls.values()) / 550) == 4, "the floor formula alone plans 4"
    assert R.lpt_heaviest(list(walls.values()), 4) == 700, "and its LPT puts 700 s in one shard"
    assert R.shard_count(walls, list(walls)) == 5
    assert R.lpt_heaviest([1816, 1816, 1816, 477, 477, 477, 10, 6], 4) == 1816
    assert R.shard_count({"x": 1800, "y": 100}, ["x", "y"]) == 2, "an indivisible pole binds"


def test_the_plan_names_the_bound_its_heaviest_member_sits_under() -> None:
    under = R.ceiling_line({"a": 477, "b": 10}, ["a", "b"])
    assert under == "the ceiling 600 s bound; heaviest member a 477 s", under
    over = R.ceiling_line({"gate-tests#3": 1816, "a": 477}, ["a", "gate-tests#3"])
    assert over.startswith("gate-tests#3 at 1816 s bound, over the ceiling 600 s"), over


#: The CI walls row PP-R1 harvested (run 38097781680): the plan's inputs, planted.
CI_ROW = {R.ENGINE_MEMBER: 1432, "gate-tests": 5448, "drive_preamble": 10, "fast_censuses": 6}


@pytest.mark.parametrize(("wall", "want"), [(5448, 10), (1700, 3), (1801, 4)])
def test_the_gate_tests_piece_count_is_derived_from_its_wall_under_the_ceiling(
    wall: int, want: int
) -> None:
    walls = {**CI_ROW, "gate-tests": wall}
    population = [R.ENGINE_MEMBER, "fast_censuses", "drive_preamble", "gate-tests"]
    priced, names = R.pieced(walls, population, _table().pieces())
    over = {n: int(priced[n]) for n in names if priced.get(n, 0) > R.SHARD_CEILING_S}
    assert not over, f"planned rows over the ceiling {R.SHARD_CEILING_S} s: {over}"
    held = [n for n in names if n.startswith(f"gate-tests{R.PIECE}")]
    assert len(held) == want, f"gate-tests at {wall} s planned {len(held)} pieces"
    line = R.ceiling_line(priced, names)
    assert line.startswith(f"the ceiling {R.SHARD_CEILING_S} s bound"), line


HEAVY = "quality/tests/test_heavy.py"
LIGHT = [f"quality/tests/test_light_{i}.py" for i in range(9)]


def test_one_module_over_the_ceiling_is_planned_alone_and_named_indivisible() -> None:
    column = {HEAVY: 745.0, **dict.fromkeys(LIGHT, 50.0)}
    cut = R.split_member(1195, 3, ([*LIGHT, HEAVY], column))
    assert cut.lists[0] == (HEAVY,) and cut.alone == {0: HEAVY}, cut
    assert max(cut.loads[1:]) <= R.SHARD_CEILING_S, cut.loads
    walls = {"gate-tests": 1195}
    parts = {"gate-tests": ([*LIGHT, HEAVY], column)}
    priced, names = R.pieced(walls, ["gate-tests"], {"gate-tests": 3}, parts)
    line = R.ceiling_line(priced, names, R.alone(walls, {"gate-tests": 3}, parts))
    assert line.startswith(f"gate-tests#1 ({HEAVY} alone) at 745 s bound"), line


def test_the_pieces_rise_until_every_row_over_the_ceiling_is_one_module() -> None:
    mods = [f"quality/tests/test_m{i}.py" for i in range(5)]
    cut = R.split_member(2000, 3, (mods, dict.fromkeys(mods, 400.0)))
    assert cut.n == 5 and max(cut.loads) == 400, cut


def test_without_a_module_column_the_pieces_go_by_count() -> None:
    mods = [f"quality/tests/test_m{i}.py" for i in range(7)]
    cut = R.split_member(1700, 3, (mods, {}))
    assert cut.lists == (tuple(mods[0::3]), tuple(mods[1::3]), tuple(mods[2::3]))
    assert cut.loads == (1700 / 3,) * 3 and cut.alone == {}


def test_the_declared_piece_count_is_a_floor_never_a_ceiling() -> None:
    assert _table().pieces() == {"gate-tests": 3}
    assert R.pieces_of({}, "gate-tests", 3) == 3, "an unmeasured member keeps its floor"
    assert R.pieces_of({"gate-tests": 90}, "gate-tests", 3) == 3
    assert R.pieces_of({"gate-tests": 5448}, "gate-tests", 3) == 10


def test_the_shard_count_takes_an_unmeasured_member_at_the_median() -> None:
    assert R.shard_count({"a": 100, "b": 300}, ["a", "b", "c"]) == math.ceil(600 / 300)
    assert R.shard_count({"a": 900}, ["a", "b"]) == 2
    assert R.shard_count({}, ["a"]) == 1


def test_the_registry_imports_under_the_system_interpreter(scratch: Path) -> None:
    system = shutil.which("python3", path="/usr/bin")
    if system is None:
        raise CouldNotLook("no /usr/bin/python3 on this machine")
    out = scratch / "listing.txt"
    code = (
        f"import sys; sys.path.insert(0, {str(ROOT)!r}); "
        "from quality.djb import cli; sys.exit(cli.main(['--list-legs']))"
    )
    with out.open("w") as sink:
        rc = subprocess.run([system, "-I", "-S", "-c", code], stdout=sink, cwd=scratch).returncode
    assert rc == 0
    assert out.read_text() == R.list_legs(_table(), ci=False)


def test_an_unknown_flag_is_exit_2_naming_the_modes_and_touches_no_lock(
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = (
        Path(
            subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "--absolute-git-dir"], text=True
            ).strip()
        )
        / "djb-gate-lock"
    )
    before = lock.exists()
    assert cli.main(["--fastt"]) == 2
    err = capsys.readouterr().err
    assert err == f"!! unknown argument '--fastt': quality.djb.cli takes {cli.known()}\n"
    assert lock.exists() == before


def test_a_modifier_another_mode_owns_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--census", "--ci"]) == 2
    assert "unexpected extra arguments: --ci" in capsys.readouterr().err


def test_the_usage_and_the_parser_are_one_table(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    usage = capsys.readouterr().out
    for mode in cli.MODES:
        assert re.search(rf"^  {re.escape(mode.flag)}\b", usage, re.MULTILINE), mode.flag
    flags = re.findall(r"^  (-{0,2}[a-z][a-z-]*)", usage, re.MULTILINE)
    assert flags == [m.flag for m in cli.MODES]


def test_the_listing_and_the_census_read_through_a_pipe(scratch: Path) -> None:
    py = ROOT / ".venv/bin/python"
    env = {k: v for k, v in os.environ.items() if k != "CI"}
    for mode, want in (("--list-legs", 0), ("--census", 0)):
        reader = subprocess.Popen(["cat"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        rc = subprocess.run(
            [str(py), "-m", "quality.djb.cli", mode],
            cwd=ROOT,
            stdout=reader.stdin,
            stderr=subprocess.DEVNULL,
            env=env,
        ).returncode
        assert reader.stdin is not None
        reader.stdin.close()
        reader.wait()
        assert rc == want, mode


def test_rule_90_reads_the_registry_for_the_modules_a_static_leg_runs(scratch: Path) -> None:
    (scratch / "scripts").mkdir()
    (scratch / R.GATE).write_text('gate_run_body other gate_leg_other pytest-x2 "other"\n')
    assert _table().check_modules() <= loop_key.static_check_modules(scratch)


def test_rule_90_reads_the_registry_s_static_legs_as_files_equal_to_discovery() -> None:
    static = [leg for leg in R.discover() if leg.unit == "static"]
    names, modules = loop_key._registry_static()
    assert names == {leg.name for leg in static}
    assert (
        modules == R.check_modules(static) == {"scripts/ledger_check.py", "scripts/queue_index.py"}
    )
    listed = _rows(R.list_legs(_table(), ci=False))["static"][3]
    assert names == set(listed.split(","))


def test_rule_90_could_not_look_at_a_leg_it_cannot_read_as_a_literal(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legs = scratch / loop_key.LEGS
    legs.mkdir(parents=True)
    (legs / "computed.py").write_text(
        'ARGV = build()\nLEG = Leg("x", "static", "b", run, argv=ARGV)\n'
    )
    monkeypatch.setattr(loop_key, "HOME", scratch)
    with pytest.raises(CouldNotLook, match="computed.py: the leg's `argv` is not a literal"):
        loop_key._registry_static()


def test_the_drive_table_is_the_shells_registration_while_the_shell_has_one() -> None:
    shell = R.shell_drives(shell_gate.text())
    assert not shell or shell == list(R.DRIVE_NAMES)
    with pytest.raises(R.RegistryError, match="one population"):
        R.build(list(R.discover()), shell_gate.text(), drives=("a_drive_nobody_registered",))


def test_a_loop_only_leg_runs_after_the_static_legs_in_loop_order_and_is_listed_nowhere() -> None:
    legs = [
        _leg("a"),
        _leg("pytest", R.LOOP_ONLY, modes=frozenset({"loop"})),
        _leg("secrets", R.LOOP_ONLY, modes=frozenset({"loop"})),
    ]
    table = R.build(legs, GATE_ONE, UNITS_ONE, R.shell_drives(GATE_ONE))
    assert [g.name for g in table.mode_legs("loop")] == ["a", "secrets", "pytest"]
    assert "secrets" not in R.list_legs(table, ci=False)
    with pytest.raises(R.RegistryError, match="only a loop-only"):
        R.build([_leg("a"), _leg("x", R.LOOP_ONLY)], GATE_ONE, UNITS_ONE, ())


# The unit runs, `--leg <unit> [--shard k/N] [--passes p]`, in a clone of HEAD (test_list_legs.sh).
# does-not-cover: what a unit's leg bodies do — every unit run here is dry or full-house-rules.

LEG_DRY = re.compile(r"^  leg: ([a-z0-9_-]+) \(DJB_GATE_LEGS_DRY", re.MULTILINE)
_UNIT_RUNS: dict[tuple[str, ...], tuple[int, str]] = {}


def _unit(gate: Callable[..., object], clone: Path, *args: str, dry: bool = True) -> str:
    """`check.sh <args>`'s transcript in `clone`, dry unless asked, once per module."""
    key = (str(dry), *args)
    if key not in _UNIT_RUNS:
        env = {"DJB_GATE_LEASE_DIR": str(clone.parent / "lease")}
        ran = gate(*args, cwd=clone, env={**env, "DJB_GATE_LEGS_DRY": "1"} if dry else env)
        _UNIT_RUNS[key] = (ran.rc, ran.text())  # type: ignore[attr-defined]
    return _UNIT_RUNS[key][1]


def _unit_rc(gate: Callable[..., object], clone: Path, *args: str, dry: bool = True) -> int:
    _unit(gate, clone, *args, dry=dry)
    return _UNIT_RUNS[(str(dry), *args)][0]


def _legs_of(text: str) -> list[str]:
    return list(dict.fromkeys(LEG_DRY.findall(text)))


def _composed(text: str) -> str:
    return next(
        x[len("  composed-of: ") :] for x in text.splitlines() if x.startswith("  composed-of: ")
    )


def test_a_dry_sharded_selftest_prints_its_plan_with_the_flags_k(
    gate: Callable[..., object], dry_clone: Path
) -> None:
    plan = re.compile(
        r"^  selftest shard (\d+)/6: (\d+) members, predicted (\d+) s \(LPT over "
        r"the walls table, [^']+'s column; ",
        re.MULTILINE,
    )
    members = 0
    for k in range(1, 7):
        text = _unit(gate, dry_clone, "--leg", "selftest", "--shard", f"{k}/6")
        found = plan.search(text)
        assert found, text[-400:]
        assert found.group(1) == str(k)
        members += int(found.group(2))
    listed = _rows(_unit(gate, dry_clone, "--list-legs", dry=False))["selftest"][3].split(",")
    walls = R.walls_view([dry_clone / h for h in R.WALLS_HOMES], R._machine(), only=False)
    floors = R.load(dry_clone).pieces()
    split = sum(R.pieces_of(walls, name, f) - 1 for name, f in floors.items() if name in walls)
    split += R.engine_pieces(walls) - 1
    assert members == len(listed) + split, "the plan holds every member, each piece once"


def test_leg_static_announces_its_legs_and_no_other(
    gate: Callable[..., object], dry_clone: Path
) -> None:
    full = ledger_full_legs()
    for unit, row in _rows(_unit(gate, dry_clone, "--list-legs", dry=False)).items():
        text = _unit(gate, dry_clone, "--leg", unit)
        assert _legs_of(text) == [m for m in row[3].split(",") if m in full], unit
        banners = sum(1 for x in text.splitlines() if x.startswith("- "))
        assert banners == text.count("DJB_GATE_LEGS_DRY — announced") + 1, unit


def ledger_full_legs() -> list[str]:
    from quality.djb import ledger

    return ledger.full_legs(ROOT)


def _cksum(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def test_leg_takes_no_lease_no_lock_and_writes_no_verdict(
    gate: Callable[..., object], dry_clone: Path
) -> None:
    common = subprocess.check_output(
        ["git", "-C", str(dry_clone), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        text=True,
    ).strip()
    verdicts = Path(common) / "djb-gate-verdicts"
    before = _cksum(verdicts)
    text = _unit(gate, dry_clone, "--leg", "full-house-rules", dry=False)
    assert _unit_rc(gate, dry_clone, "--leg", "full-house-rules", dry=False) == 0, text[-600:]
    assert "gate lease" not in text
    git_dir = subprocess.check_output(
        ["git", "-C", str(dry_clone), "rev-parse", "--absolute-git-dir"], text=True
    ).strip()
    assert not (Path(git_dir) / "djb-gate.lock").exists()
    assert _cksum(verdicts) == before
    assert "no verdict recorded — --leg full-house-rules" in text


def test_leg_needs_no_sanction(gate: Callable[..., object], dry_clone: Path) -> None:
    assert "DJB_GATE_SANCTION" not in os.environ
    text = _unit(gate, dry_clone, "--leg", "full-house-rules", dry=False)
    assert "REFUSING an unsanctioned FULL gate" not in text
    assert _unit_rc(gate, dry_clone, "--leg", "full-house-rules", dry=False) != 2


def test_an_unknown_unit_is_exit_2_naming_the_listing(
    gate: Callable[..., object], dry_clone: Path
) -> None:
    assert _unit_rc(gate, dry_clone, "--leg", "zzz-not-a-unit", dry=False) == 2
    assert "--list-legs" in _unit(gate, dry_clone, "--leg", "zzz-not-a-unit", dry=False)
    assert _unit_rc(gate, dry_clone, "--leg", dry=False) == 2


def test_shard_on_a_non_pytest_unit_is_exit_2(gate: Callable[..., object], dry_clone: Path) -> None:
    table = _rows(_unit(gate, dry_clone, "--list-legs", dry=False))
    whole = [u for u, row in table.items() if row[2] == "0"]
    assert whole and any(row[2] == "N-capable" for row in table.values())
    for unit in whole:
        args = ("--leg", unit, "--shard", "1/3")
        assert _unit_rc(gate, dry_clone, *args, dry=False) == 2, unit
        assert "indivisible" in _unit(gate, dry_clone, *args, dry=False), unit


def test_a_malformed_shard_pair_is_exit_2(gate: Callable[..., object], dry_clone: Path) -> None:
    for pair in ("4/3", "0/3", "1/0", "a/3", "13"):
        assert _unit_rc(gate, dry_clone, "--leg", "pytest-x2", "--shard", pair, dry=False) == 2
    assert _unit_rc(gate, dry_clone, "--leg", "pytest-x2", "--shard", dry=False) == 2
    assert _unit_rc(gate, dry_clone, "--loop", "--shard", "1/3", dry=False) == 2
    said = _unit(gate, dry_clone, "--loop", "--shard", "1/3", dry=False)
    assert "unexpected extra arguments: --shard 1/3" in said


def test_passes_outside_a_shard_or_malformed_is_exit_2(
    gate: Callable[..., object], dry_clone: Path
) -> None:
    whole, count = (
        "the suite leg runs 1 or 2 whole passes",
        ("--leg", "pytest-x2", "--shard", "1/3"),
    )
    refusals = [
        (
            "the whole-suite two-pass belt is this unit's own",
            ("--leg", "pytest-x2", "--passes", "1"),
        ),
        (whole, (*count, "--passes")),
        *((whole, (*count, "--passes", p)) for p in ("0", "3", "x")),
        (whole, (*count, "--passes=x")),
        ("two ways to say pass 2 is not run", (*count, "--passes", "1", "--store-durations")),
    ]
    table = _rows(_unit(gate, dry_clone, "--list-legs", dry=False))
    suiteless = [
        u for u, r in table.items() if r[2] == "N-capable" and "pytest-x2" not in r[3].split(",")
    ]
    assert suiteless
    refusals += [
        ("that unit runs no suite", ("--leg", u, "--shard", "1/3", "--passes", "1"))
        for u in suiteless
    ]
    for want, args in refusals:
        text = _unit(gate, dry_clone, *args, dry=False)
        assert _unit_rc(gate, dry_clone, *args, dry=False) == 2, args
        assert want in text, (args, text[:300])
        assert not any(x.startswith("- ") for x in text.splitlines()), args
    said = _unit(gate, dry_clone, "--loop", "--passes", "1", dry=False)
    assert _unit_rc(gate, dry_clone, "--loop", "--passes", "1", dry=False) == 2
    assert "unexpected extra arguments: --passes 1" in said


def test_passes_1_runs_one_pass_and_says_so(gate: Callable[..., object], dry_clone: Path) -> None:
    two = _unit(gate, dry_clone, "--leg", "pytest-x2", "--shard", "1/3")
    one = _unit(gate, dry_clone, "--leg", "pytest-x2", "--shard", "1/3", "--passes", "1")
    assert _legs_of(one) == _legs_of(two)
    assert _legs_of(one) == ["pytest-x2"]
    assert "both passes" not in one and "--passes 1" in one
    assert "both passes" in two


def test_composed_of_names_the_pass_count(gate: Callable[..., object], dry_clone: Path) -> None:
    listed = _rows(_unit(gate, dry_clone, "--list-legs", dry=False))["pytest-x2"][3]
    absent = _unit(gate, dry_clone, "--leg", "pytest-x2", "--shard", "1/3")
    assert _composed(absent) == listed
    one = _unit(gate, dry_clone, "--leg", "pytest-x2", "--shard", "1/3", "--passes", "1")
    want = ",".join("pytest-x2/1" if m == "pytest-x2" else m for m in listed.split(","))
    assert _composed(one) == want
    two = _unit(gate, dry_clone, "--leg", "pytest-x2", "--shard", "1/3", "--passes", "2")
    assert _composed(two) == _composed(absent)
    banner = [x for x in absent.splitlines() if x.startswith("- ")][0]
    assert [x for x in two.splitlines() if x.startswith("- ")][0] == banner


def test_list_legs_carries_no_pass_count(gate: Callable[..., object], dry_clone: Path) -> None:
    table = _rows(_unit(gate, dry_clone, "--list-legs", dry=False))
    assert not [m for row in table.values() for m in row[3].split(",") if "/" in m]
    assert _composed(_unit(gate, dry_clone, "--leg", "pytest-x2")) == table["pytest-x2"][3]


def test_collectstatic_is_a_leg_in_the_static_unit(
    gate: Callable[..., object], dry_clone: Path
) -> None:
    assert "collectstatic" in ledger_full_legs()
    assert "collectstatic" in _rows(R.list_legs(_table(), ci=False))["static"][3].split(",")
    env = {"DJB_LOOP_HERE": "test_registry: a dry --loop", "DJB_GATE_LEASE_DIR": "x"}
    env["DJB_GATE_LEASE_DIR"] = str(dry_clone.parent / "lease")
    ran = gate("--loop", cwd=dry_clone, env={**env, "DJB_GATE_LEGS_DRY": "1"})
    assert ran.rc == 0, ran.text()  # type: ignore[attr-defined]
    assert "collectstatic" not in LEG_DRY.findall(ran.text())  # type: ignore[attr-defined]


def test_clone_into_gets_a_main_from_either_source_shape(dry_clone: Path, scratch: Path) -> None:
    def main_of(where: Path) -> str:
        return subprocess.check_output(
            ["git", "-C", str(where), "rev-parse", "--verify", "-q", "main"], text=True
        ).strip()

    assert main_of(dry_clone) == base_of(ROOT)
    on_main = clone_into(ROOT, scratch / "on-main")
    subprocess.run(["git", "-C", str(on_main), "checkout", "-q", "main"], check=True)
    runner = clone_into(on_main, scratch / "runner")
    subprocess.run(["git", "-C", str(runner), "branch", "-q", "-D", "main"], check=True)
    assert base_of(runner) == base_of(ROOT), "a runner's origin/main is not its base"
    assert main_of(clone_into(on_main, scratch / "from-main")) == base_of(ROOT)
    assert main_of(clone_into(runner, scratch / "from-runner")) == base_of(ROOT)


def _tree_without_drawer(scratch: Path) -> Path:
    tree = scratch / "tree"
    (tree / "scripts").mkdir(parents=True)
    (tree / R.GATE).write_text((ROOT / R.GATE).read_text())
    return tree


def test_an_absent_drawer_is_byte_identical(scratch: Path) -> None:
    tree = _tree_without_drawer(scratch)
    absent = R.list_legs(R.load(tree), ci=False, root=tree)
    assert absent == R.list_legs(R.load(ROOT), ci=False, root=ROOT)
    assert not any(m.startswith("local:") for r in _rows(absent).values() for m in r[3].split(","))


def test_the_drawer_is_in_the_measured_trees_declaration_sources() -> None:
    sources = loop_key.decider_value("GATE_TREE_DECL_SOURCES", ROOT).split()
    assert {"scripts/local/*/*.sh", "scripts/local/*.sh"} <= set(sources)
    assert not any("**" in s for s in sources)


# --- the drawer reader: `scripts/local/legs/` (check.sh's local-legs block, F-3a-A's spec) ------


def plant_leg(drawer: Path, name: str, code: int = 0, **fields: str) -> Path:
    """A product leg `<drawer>/<name>.sh` with a v1 header (`two_means` spells `two-means`)."""
    head = {"unit": "local", "needs": "none", "tier": "full"} | {
        k.replace("_", "-"): v for k, v in fields.items()
    }
    lines = ["#!/usr/bin/env bash", "# >>> leg v1 >>>", *(f"# {k}: {v}" for k, v in head.items())]
    leg = drawer / f"{name}.sh"
    drawer.mkdir(parents=True, exist_ok=True)
    body = [
        *lines,
        "# <<< leg <<<",
        f'echo "{name}: this is a planted product leg"',
        f"exit {code}",
    ]
    leg.write_text("\n".join(body) + "\n")
    leg.chmod(0o755)
    return leg


def test_an_empty_drawer_lists_byte_identical_to_none(scratch: Path) -> None:
    tree = _tree_without_drawer(scratch)
    absent = R.list_legs(R.load(tree), ci=False, root=tree)
    (tree / R.DRAWERS[0]).mkdir(parents=True)
    assert R.list_legs(R.load(tree), ci=False, root=tree) == absent


def test_a_declared_leg_joins_the_listing_as_its_own_unit(scratch: Path) -> None:
    tree = _tree_without_drawer(scratch)
    drawer = tree / R.DRAWERS[0]
    plant_leg(drawer, "canary", 1)
    plant_leg(drawer, "typecheck", unit="frontend", needs="node,network", tier="fast")
    assert [g.name for g in R.local_legs(drawer)] == ["local:canary", "local:typecheck"]
    table = _rows(R.list_legs(R.load(tree), ci=False, root=tree))
    assert table["local"] == ["local", "none", "0", "local:canary"]
    assert table["frontend"] == ["frontend", "network,node", "0", "local:typecheck"]


#: Imports each drawer case module by file with the shell gate's commit absent; one line per skip.
_DRAWER_CASE_PROBE = """
import importlib.util, sys
import django
import pytest
django.setup()
from quality.tests.fixtures import shell_gate
def absent():
    pytest.skip(f"the shell gate's commit {shell_gate.SHELL_AT} is absent", allow_module_level=True)
shell_gate.raw = absent
shell_gate.text.cache_clear()
for n, rel in enumerate(sys.argv[1:]):
    spec = importlib.util.spec_from_file_location(f"_drawer_case_{n}", rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except pytest.skip.Exception as why:
        print(f"skipped {rel}: {why}")
"""


def test_every_pytest_drawer_case_collects_where_the_shell_gates_commit_is_absent() -> None:
    """A product's history has no shell-gate commit: no drawer case's module reads it at import."""
    from quality.checks import rule_60_second_class as C

    rows, _ = C.drawer_rows((ROOT / C._DRAWERS_DOC).read_text())
    cases = sorted(
        {r.case.partition("::")[0] for r in rows if r.state == "live" and ".py::" in r.case}
    )
    assert cases, "the drawers table names no pytest case — the population this reads is empty"
    done = subprocess.run(
        [sys.executable, "-c", _DRAWER_CASE_PROBE, *cases],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "PYTHONPATH": str(ROOT),
        },
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "skipped " not in done.stdout, done.stdout


def test_tier_decides_which_modes_run_a_leg(scratch: Path) -> None:
    drawer = scratch / "legs"
    plant_leg(drawer, "cheap", tier="loop")
    plant_leg(drawer, "dear", tier="full")
    plant_leg(drawer, "early", tier="fast")
    legs = R.local_legs(drawer)
    assert R.local_tier(legs, "fast") == ["local:early"]
    assert R.local_tier(legs, "loop") == ["local:cheap", "local:early"]
    assert R.local_tier(legs, "full") == ["local:cheap", "local:dear", "local:early"]


def test_touches_skips_under_a_narrowed_mode_and_never_under_full(scratch: Path) -> None:
    drawer = scratch / "legs"
    plant_leg(drawer, "fescan", tier="loop", touches="frontend")
    (leg,) = R.local_legs(drawer)
    assert R.local_touched(leg, ["apps/nowhere/nothing.py"]) is False
    assert R.local_touched(leg, ["frontend/app/page.tsx"]) is True
    with pytest.raises(CouldNotLook):
        R.local_touched(leg, [])


@pytest.mark.parametrize(
    ("plant", "said"),
    [
        ({"two_means": "finding"}, "2 means could not look everywhere; exit 1 for a finding"),
        ({"unit": "selftest"}, "selftest"),
        ({"tier": "sometimes"}, "sometimes"),
        ({"zzz": "x"}, "unknown header field 'zzz'"),
        ({"needs": ""}, "header field 'needs:' is empty"),
    ],
)
def test_a_malformed_leg_is_exit_2_naming_the_file_and_the_field(
    scratch: Path, plant: dict[str, str], said: str
) -> None:
    drawer = scratch / "legs"
    leg = plant_leg(drawer, "canary", 0, **plant)
    with pytest.raises(R.RegistryError, match=re.escape(said)) as refused:
        R.local_legs(drawer)
    assert str(leg) in str(refused.value) or leg.name in str(refused.value)


def test_a_leg_with_no_header_no_x_or_a_known_name_is_exit_2(scratch: Path) -> None:
    drawer = scratch / "legs"
    bare = drawer / "bare.sh"
    drawer.mkdir()
    bare.write_text("#!/usr/bin/env bash\nexit 0\n")
    bare.chmod(0o755)
    with pytest.raises(R.RegistryError, match="header"):
        R.local_legs(drawer)
    bare.unlink()
    plant_leg(drawer, "canary").chmod(0o644)
    with pytest.raises(R.RegistryError, match="canary"):
        R.local_legs(drawer)
    (drawer / "canary.sh").unlink()
    plant_leg(drawer, "ruff")
    with pytest.raises(R.RegistryError, match="ruff"):
        R.local_legs(drawer)


def test_the_verdict_row_names_each_local_leg(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quality.djb import ledger

    template = ledger.full_legs(ROOT)
    assert "full-house-rules" in template
    assert not any(x.startswith("local:") for x in template)
    plant_leg(scratch / "legs", "canary")
    monkeypatch.setenv("DJB_LOCAL_LEGS_DIR", str(scratch / "legs"))
    assert "local:canary" in ledger.full_legs(ROOT)
