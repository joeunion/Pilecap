"""The `always-on` leg: its selection, its sessions and its verdict, as the shell leg's."""

# does-not-cover: a real drives session over the tracked drives — the box's `--loop` runs that.

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from quality.djb import registry as R
from quality.djb import scope
from quality.djb.legs import always_on as ao
from quality.tests.fixtures import shell_gate

pytestmark = pytest.mark.drives(
    "quality/djb/legs/always_on.py",
    "quality/djb/legs/selftest.py",
    "scripts/tests/test_drive_preamble.sh",
)

ROOT = Path(__file__).resolve().parents[2]
GATE_TEXT = shell_gate.text()
OPEN, CLOSE = "# >>> always-on-leg >>>", "# <<< always-on-leg <<<"
FENCE = GATE_TEXT.split(f"\n{OPEN}\n", 1)[1].split(f"\n{CLOSE}\n", 1)[0]
_TIMES = re.compile(r"\(\d+s\)|\d+s of member wall, \d+s of leg")


def _plant(home: Path, members: dict[str, int], census: Sequence[str] = ()) -> Path:
    """A planted drive set: `test_<name>.sh` exiting as told, the named ones cross-app."""
    home.mkdir(parents=True)
    (home / "drive_preamble.sh").write_text("# a planted preamble\n")
    for name, rc in members.items():
        head = "#!/bin/sh\n"
        if name in census:
            head += "# census: cross-app a planted census; no organs\n"
        body = f'# drives: scripts/tests/drive_preamble.sh\necho "planted {name} speaking"\n'
        path = home / f"test_{name}.sh"
        path.write_text(f"{head}{body}exit {rc}\n")
        path.chmod(0o755)
    return home


def _durations(path: Path, seconds: dict[str, int]) -> Path:
    doc = {"measured_at": "planted", "machine": "Scratch 0.0", "members": seconds}
    path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


@pytest.fixture
def world(scratch: Path) -> Callable[..., dict[str, str]]:
    """The environment a planted run reads: the drive set, its walls, a scratch ledger."""

    def build(
        members: dict[str, int],
        seconds: dict[str, int] | None = None,
        census: Sequence[str] = (),
        changed: str = "",
    ) -> dict[str, str]:
        home = _plant(scratch / "drives", members, census)
        ledger = scratch / "verdicts"
        ledger.write_text("")
        env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", str(scratch)),
            "DJB_SELFTEST_DRIVES_DIR": str(home),
            "DJB_GATE_LEDGER": str(ledger),
            "DJB_ALWAYS_ON_CHANGED_FILES": changed,
            "TMPDIR": str(scratch),
        }
        if seconds is not None:
            env["DJB_GATE_MEMBER_DURATIONS"] = str(_durations(scratch / "walls.json", seconds))
        return env

    return build


def _shell(env: dict[str, str]) -> tuple[int, str]:
    script = "\n".join(
        (
            "set +e",
            ". scripts/gate_refuse.sh",
            ". scripts/gate_ledger.sh",
            f". {shell_gate.library('loop_tier.sh')}",
            f"LOOP_TIER_ROOT={ROOT}",
            "local_legs_changed_files() { :; }",
            FENCE,
            "MEASURED_START=$(gate_measured_tree 2>/dev/null || true)",
            "export MEASURED_START",
            "always_on_leg",
        )
    )
    done = subprocess.run(["bash", "-c", script], cwd=ROOT, env=env, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def _python(env: dict[str, str], capfd: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capfd.readouterr()
    rc = ao.leg(R.Ctx(ROOT, "loop", env))
    seen = capfd.readouterr()
    return rc, seen.out + seen.err


def _norm(text: str) -> list[str]:
    return sorted(_TIMES.sub("(T)", line).rstrip() for line in text.splitlines() if line.strip())


def test_the_registry_claims_the_loop_only_leg_after_secrets() -> None:
    table = R.load(ROOT)
    leg = table.leg("always-on")
    assert (leg.unit, set(leg.modes), leg.body) == (R.LOOP_ONLY, {"loop"}, ao.run)
    order = [g.name for g in table.mode_legs("loop")]
    assert order[-3:] == ["secrets", "always-on", "pytest"]
    assert all("always-on" not in members for _, members in table.rows)


@pytest.mark.parametrize(
    ("members", "seconds", "census"),
    [
        ({"aa": 0, "bb": 1, "cc": 2}, {"aa": 1, "bb": 2, "cc": 3}, ()),
        ({"aa": 0, "bb": 0}, {"aa": 1, "bb": 50}, ("bb",)),
        ({"aa": 0, "bb": 1}, {}, ("aa",)),
        ({"aa": 0}, {"aa": 1, "zz": 2}, ()),
        ({"aa": 0, "bb": 0}, {"aa": 3}, ()),
    ],
    ids=["one-each", "census-above-floor", "no-walls", "unknown-member", "unmeasured"],
)
def test_on_one_planted_world_the_port_says_and_exits_what_the_shell_did(
    world: Callable[..., dict[str, str]],
    capfd: pytest.CaptureFixture[str],
    members: dict[str, int],
    seconds: dict[str, int] | None,
    census: Sequence[str],
) -> None:
    env = world(members, seconds, census)
    second = Path(env["DJB_GATE_LEDGER"] + ".port")
    second.write_text("")
    shell_rc, shell_text = _shell(env)
    port_rc, port_text = _python({**env, "DJB_GATE_LEDGER": str(second)}, capfd)
    assert port_rc == shell_rc, (shell_text, port_text)
    assert _norm(port_text) == _norm(shell_text)


def test_a_red_and_a_could_not_look_member_compose_to_2_naming_both(
    world: Callable[..., dict[str, str]], capfd: pytest.CaptureFixture[str]
) -> None:
    env = world({"aa": 0, "bb": 1, "cc": 2}, {"aa": 1, "bb": 1, "cc": 1})
    rc, text = _python(env, capfd)
    assert rc == 2
    assert "!! COULD NOT LOOK: cc" in text and "!! and RED: bb" in text
    assert "      | planted bb speaking" in text


def test_a_green_member_is_banked_and_reused_on_the_next_run(
    world: Callable[..., dict[str, str]], capfd: pytest.CaptureFixture[str], scratch: Path
) -> None:
    drive = ROOT / "scripts/tests/test_drive_preamble.sh"
    env = world({"aa": 0}, {"aa": 1})
    env["DJB_SELFTEST_DRIVES_DIR"] = ""
    ctx = R.Ctx(ROOT, "loop", env)
    member = ao.Member("member", "drive_preamble", path=drive)
    tree, why = ao.keyed(ctx, [member])
    assert tree and not why and member.key.key, member.key
    ao.settle(ctx, ao.Tally(), tree, member, 0, 3, "")
    again = ao.Member("member", "drive_preamble", path=drive)
    ao.keyed(ctx, [again])
    tally = ao.Tally()
    capfd.readouterr()
    assert ao.consult(ctx, again, "", tally) is False
    assert tally.green == 1
    assert f"REUSED from {member.key.key}" in capfd.readouterr().out


# --- the touched half ------------------------------------------------------------------------


def _rows(*names: str) -> list[tuple[str, Path]]:
    return [(n, ROOT / "scripts" / "tests" / f"test_{n}.sh") for n in names]


def test_the_committed_walls_table_names_only_this_gates_members(
    capfd: pytest.CaptureFixture[str],
) -> None:
    table = R.load(ROOT)
    ctx = R.Ctx(ROOT, "loop", dict(os.environ))
    rc, _, _ = ao.measured(ctx, table, list(R.DRIVE_NAMES), [])
    assert rc == 0, capfd.readouterr().err


def _planted(scratch: Path, **declares: str) -> list[tuple[str, Path]]:
    """Scratch drives, each `# drives:` naming the one path given: no swept drive is needed."""
    rows = []
    for name, path in declares.items():
        drive = scratch / f"test_{name}.sh"
        drive.write_text(f"#!/usr/bin/env bash\n# drives: {path}\nexit 0\n")
        rows.append((name, drive))
    return rows


def test_a_changed_shell_file_selects_the_drives_that_declare_it(
    capfd: pytest.CaptureFixture[str], scratch: Path
) -> None:
    ctx = R.Ctx(ROOT, "loop", dict(os.environ))
    rows = _planted(scratch, alpha="scripts/gate_refuse.sh", beta="scripts/db.sh")
    picked = ao.touched(ctx, rows, ["scripts/gate_refuse.sh"], [], [])
    said = capfd.readouterr().out
    assert picked == ["alpha"]
    assert "always-on (touched): " in said and "drives cover scripts/gate_refuse.sh" in said
    assert "a shell file changed" not in said


def test_an_already_selected_drive_runs_once_and_says_where(
    capfd: pytest.CaptureFixture[str], scratch: Path
) -> None:
    ctx = R.Ctx(ROOT, "loop", dict(os.environ))
    rows = _planted(scratch, alpha="scripts/gate_refuse.sh")
    picked = ao.touched(ctx, rows, ["scripts/gate_refuse.sh"], ["alpha"], [])
    assert "alpha" not in picked
    assert "already selected (declared); runs once there" in capfd.readouterr().out


def test_no_change_selects_nothing_and_says_nothing() -> None:
    ctx = R.Ctx(ROOT, "loop", dict(os.environ))
    assert ao.touched(ctx, _rows("gate_lease"), [], [], []) == []
    assert ao.touched(ctx, _rows("gate_lease"), ["docs/product/queue.md"], [], []) == []


def test_a_fence_that_passes_arguments_or_never_runs_the_drive_bare_is_a_finding(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    fence = scratch / "check.sh"
    fence.write_text(
        "# >>> drive: one >>>\n./scripts/tests/test_one.sh --case x\n# <<< drive: one <<<\n"
        "# >>> drive: two >>>\n./scripts/tests/test_two.sh\n# <<< drive: two <<<\n"
        "# >>> drive: three >>>\necho nothing\n# <<< drive: three <<<\n"
    )
    ctx = R.Ctx(ROOT, "loop", {"DJB_ALWAYS_ON_FENCE_FILE": str(fence)})
    tests = ROOT / "scripts/tests"
    assert ao.fence_finding(ctx, "one", tests / "test_one.sh") == 1
    assert ao.fence_finding(ctx, "two", tests / "test_two.sh") == 0
    assert ao.fence_finding(ctx, "three", tests / "test_three.sh") == 1
    said = capfd.readouterr().out
    assert "invokes 'scripts/tests/test_one.sh --case x'" in said.replace("./scripts", "scripts")
    assert "invokes '(no bare invocation in the fence)'" in said


def test_the_touched_gate_tests_come_from_the_mode_and_never_name_the_runner() -> None:
    env = {"GATE_LOOP_TOUCHED": f"quality/tests/test_hold.py {ao.RUNNER}"}
    assert ao.touched_tests(R.Ctx(ROOT, "loop", env), []) == ["quality/tests/test_hold.py"]
    assert ao.touched_tests(R.Ctx(ROOT, "loop", {"DJB_SELFTEST_DRIVES_DIR": "x"}), ["a"]) == []


# --- the drives session ------------------------------------------------------------------------


class _Session:
    """`session` replaced: each call recorded, each named drive's verdict written as told."""

    def __init__(self, verdicts: dict[str, int], rc: dict[str, int] | None = None) -> None:
        self.verdicts, self.rc = verdicts, rc or {}
        self.calls: list[tuple[str, int, list[str]]] = []

    def __call__(
        self, ctx: R.Ctx, log: Path, results: Path, workers: int, argv: Sequence[str]
    ) -> int:
        self.calls.append((log.stem, workers, list(argv)))
        log.write_text(f"{log.stem} session log\n")
        for word in argv:
            found = re.search(r"\[(\w+)\]$", word)
            if found and found.group(1) in self.verdicts:
                name = found.group(1)
                (results / f"{name}.out").write_text(f"{name} said this\n")
                (results / f"{name}.done").write_text(f"{self.verdicts[name]} 4\n")
        return self.rc.get(log.stem, 0)


def _members(*names: str) -> list[ao.Member]:
    return [ao.Member("member", n, path=ROOT / "scripts/tests" / f"test_{n}.sh") for n in names]


def test_serial_drives_run_alone_after_the_parallel_session_longest_first(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    home = scratch / "scripts" / "tests"
    home.mkdir(parents=True)
    for name, head in (("plain", ""), ("lone", "# serial: planted\n"), ("long", "")):
        (home / f"test_{name}.sh").write_text(f"#!/bin/sh\n{head}exit 0\n")
    members = [
        ao.Member("member", n, path=home / f"test_{n}.sh") for n in ("plain", "lone", "long")
    ]
    assert ao.is_serial(home / "test_lone.sh")
    fake = _Session({"long": 0, "plain": 0, "lone": 0})
    monkeypatch.setattr(ao, "session", fake)
    monkeypatch.setattr(ao, "box_workers", lambda ctx: 8)
    tally = ao.Tally()
    ctx = R.Ctx(scratch, "loop", {"DJB_GATE_LEGS_DRY": "1"})
    ao.queue_run(ctx, tally, "", members, {"long": 9})
    arms = [(c[0], c[1]) for c in fake.calls]
    assert arms == [("harness", 2), ("drives", 2), ("serial", 1)]
    assert fake.calls[1][2][2:] == [
        f"{ao.RUNNER}::test_drive[long]",
        f"{ao.RUNNER}::test_drive[plain]",
    ]
    assert fake.calls[2][2] == [f"{ao.RUNNER}::test_drive[lone]"]
    assert (
        "2 under pytest-xdist -n 2, longest recorded first; 1 serial after"
        in capfd.readouterr().out
    )
    assert tally.green == 3


def test_a_session_that_exits_worse_than_its_drives_turns_their_green_to_could_not_look(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Session({"gate_lease": 0}, {"drives": 3})
    monkeypatch.setattr(ao, "session", fake)
    monkeypatch.setattr(ao, "box_workers", lambda ctx: 1)
    tally = ao.Tally()
    ao.queue_run(
        R.Ctx(ROOT, "loop", {"DJB_GATE_LEGS_DRY": "1"}), tally, "", _members("gate_lease"), {}
    )
    assert tally.cannot == ["drives-session", "gate_lease"]


def test_a_drive_the_session_left_no_verdict_for_could_not_look(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ao, "session", _Session({}))
    monkeypatch.setattr(ao, "box_workers", lambda ctx: 1)
    tally = ao.Tally()
    ao.queue_run(R.Ctx(ROOT, "loop", {}), tally, "", _members("gate_lease"), {})
    assert tally.cannot == ["gate_lease"]
    assert "the drives session left no verdict for gate_lease" in capfd.readouterr().out


def test_a_red_harness_session_is_its_own_red_member(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ao, "session", _Session({"gate_lease": 0}, {"harness": 1}))
    monkeypatch.setattr(ao, "box_workers", lambda ctx: 1)
    tally = ao.Tally()
    ctx = R.Ctx(ROOT, "loop", {"DJB_GATE_LEGS_DRY": "1"})
    ao.queue_run(ctx, tally, "", _members("gate_lease"), {}, ["quality/tests/test_hold.py"])
    assert tally.red == ["quality-tests"]


def test_the_touched_gate_tests_run_beside_the_harness_with_no_drive_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _Session({})
    monkeypatch.setattr(ao, "session", fake)
    ao.queue_run(R.Ctx(ROOT, "loop", {}), ao.Tally(), "", [], {}, ["quality/tests/test_hold.py"])
    harness = [*ao.HARNESS, "quality/tests/test_hold.py", *ao.LOOP_DESELECT]
    assert fake.calls == [("harness", 0, harness)]


@pytest.mark.parametrize(
    ("rc", "done", "outside", "said"),
    [
        (0, {}, "", ""),
        (1, {"aa": "1 3"}, "", ""),
        (3, {"aa": "1 3"}, "", "the drives session exited 3 and no drive in it says worse than 1"),
        (1, {"aa": "0 3"}, "teardown failed x\n", "with a failed teardown no drive owns: "),
    ],
)
def test_doubt_names_what_no_drive_owns(
    scratch: Path, rc: int, done: dict[str, str], outside: str, said: str
) -> None:
    for name, line in done.items():
        (scratch / f"{name}.done").write_text(line + "\n")
    if outside:
        (scratch / "outside.drives").write_text(outside)
    found = ao.doubt(scratch, "drives", rc, list(done))
    assert said in found and bool(found) is bool(said)


def test_compose_is_two_over_one_over_zero(capfd: pytest.CaptureFixture[str]) -> None:
    assert ao.compose(ao.Tally(green=2), 0.0) == 0
    assert ao.compose(ao.Tally(red=["a"]), 0.0) == 1
    assert ao.compose(ao.Tally(red=["a"], cannot=["b"]), 0.0) == 2
    assert "!! and RED: a" in capfd.readouterr().err


def test_an_apps_touch_selects_golden_copy_and_the_loop_deselects_its_full_gate_verb_arm() -> None:
    from quality.djb import scope

    module = "quality/tests/test_golden_copy.py"
    assert module in scope.touched(ROOT, ["apps/example/models.py"])
    assert ao.LOOP_DESELECT == ("-m", "not full_gate")

    def collected(*extra: str) -> list[str]:
        done = subprocess.run(
            [str(ROOT / ".venv/bin/python"), "-m", "pytest", "--collect-only", "-q", module]
            + ["-p", "no:randomly", *extra],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        return [line for line in done.stdout.splitlines() if "::" in line]

    whole, loop = collected(), collected(*ao.LOOP_DESELECT)
    arm = [n for n in whole if "test_verb_the_worked_example" in n]
    assert arm, "the verb arm is not in the module the full gate collects"
    assert not any("test_verb_the_worked_example" in n for n in loop)
    assert sorted(loop) == sorted(set(whole) - set(arm))


def test_the_census_population_is_derived_from_the_marker_and_never_typed() -> None:
    """Every marked `apps/` test module is always-on, read off the marker; no module types one."""
    population = ao.census_population(ROOT)
    marked = [path for path, _ in scope.declared_censuses(ROOT, "apps", "test_*.py")]
    assert population == marked and len(population) > 5, population
    assert "apps/core/tests/test_tree_census.py" in population
    assert ao.census_line(population) == f"always-on: {len(population)} census modules"
    typed = re.compile(r"""["'`][^"'`\n]*test_\w*census\w*\.py["'`]""")
    for module in ("quality/djb/legs/always_on.py", "quality/djb/scope.py"):
        text = (ROOT / module).read_text(encoding="utf-8")
        assert not typed.search(text), f"{module} types a census module path"
        assert [p for p in population if p in text or f'"{Path(p).name}"' in text] == []


def _product(tmp_path: Path, drawer: str = "rule_id_namespace: acme\n") -> Path:
    """A checkout whose drawer declares a namespace: the product tree, and nothing else."""
    (tmp_path / "quality/local").mkdir(parents=True)
    (tmp_path / "quality/local/rules.yaml").write_text(drawer)
    return tmp_path


def test_a_product_trees_loop_collects_no_platform_test_module_and_says_how_many(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    fake = _Session({})
    monkeypatch.setattr(ao, "session", fake)
    touched = ["quality/tests/test_hold.py", "quality/tests/test_layer_boundary.py"]
    tally = ao.Tally()
    ao.queue_run(R.Ctx(_product(tmp_path), "loop", {}), tally, "", [], {}, touched)
    out = capfd.readouterr().out
    assert fake.calls == [], fake.calls
    assert "gate tests (touched)" not in out
    left = len({*ao.HARNESS, *touched})
    line = (
        f"  loop: a product tree — {left} platform test module(s) and 0 platform drive(s) not"
        " collected: a product never pays for the platform's tests"
    )
    assert out.splitlines() == [line] and not tally.red and not tally.cannot


def test_a_product_trees_own_gate_tests_under_its_drawer_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    fake = _Session({})
    monkeypatch.setattr(ao, "session", fake)
    mine = "quality/local/tests/test_acme.py"
    touched = [mine, "quality/tests/test_hold.py"]
    ao.queue_run(R.Ctx(_product(tmp_path), "loop", {}), ao.Tally(), "", [], {}, touched)
    assert fake.calls == [("harness", 0, [mine, *ao.LOOP_DESELECT])]
    assert f"{len(ao.HARNESS) + 1} platform test module(s) and 0" in capfd.readouterr().out


def test_an_unreadable_drawer_is_could_not_look_and_collects_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _Session({})
    monkeypatch.setattr(ao, "session", fake)
    tally = ao.Tally()
    ctx = R.Ctx(_product(tmp_path, "rule_id_namespace: [\n"), "loop", {})
    ao.queue_run(ctx, tally, "", [], {}, ["quality/tests/test_hold.py"])
    assert fake.calls == [] and tally.cannot == ["drawer"]


def _drive(root: Path, rel: str) -> ao.Member:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return ao.Member("census", path.stem[len("test_") :], path=path)


def test_a_product_trees_loop_runs_no_platform_drive_and_its_own_still_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    fake = _Session({})
    monkeypatch.setattr(ao, "session", fake)
    root = _product(tmp_path)
    platform = [_drive(root, "scripts/tests/test_aa.sh"), _drive(root, "deploy/tests/test_bb.sh")]
    mine = _drive(root, "scripts/local/tests/test_cc.sh")
    tally = ao.Tally()
    ao.queue_run(R.Ctx(root, "loop", {"DJB_GATE_LEGS_DRY": "1"}), tally, "", [*platform, mine], {})
    out = capfd.readouterr().out.splitlines()
    assert fake.calls == [], fake.calls
    assert out[0] == (
        f"  loop: a product tree — {len(ao.HARNESS)} platform test module(s) and 2 platform"
        " drive(s) not collected: a product never pays for the platform's tests"
    )
    assert out[1:] == ["  census cc: exit 0 (0s)"] and tally.green == 1 and not tally.cannot


def test_a_census_joins_only_when_its_population_moved() -> None:
    """CI-THIRD-3 3.3: an `apps/` diff joins the censuses over it; a diff outside, the `every`."""
    declared = scope.declared_censuses(ROOT, *ao.CENSUS_HOME)
    every = [p for p, d in declared if not d.startswith(scope.CENSUS_POPULATION)]
    over = {p: d for p, d in declared}

    def joined(changed: list[str]) -> list[str]:
        return [p for p, d in declared if scope.census_moved(d, changed)]

    services = joined(["apps/example/services.py"])
    assert "apps/core/tests/test_audit_actor_class.py" in services
    assert "apps/core/tests/test_four_doors_census.py" not in services, over
    assert joined([".github/workflows/ci.yml"]) == every
    assert 0 < len(every) < len(declared)
    line = ao.joined_line(services, [p for p, _ in declared])
    unmoved = len(declared) - len(services)
    assert line == (
        f"always-on: {len(services)} of {len(declared)} census modules joined — {unmoved}"
        " populations unmoved"
    )


def test_a_changed_set_git_cannot_derive_is_quoted(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    said = "fatal: detected dubious ownership in repository at '/src'"

    def refuse(ctx: R.Ctx) -> list[str]:
        raise subprocess.CalledProcessError(128, ["git", "diff"], stderr=said)

    monkeypatch.setattr(ao, "drives", lambda ctx, table: [])
    monkeypatch.setattr(scope, "declared_censuses", lambda *a: [])
    monkeypatch.setattr(ao, "measured", lambda *a: (0, [], 0))
    monkeypatch.setattr(ao, "changed", refuse)
    capfd.readouterr()
    assert ao.leg(R.Ctx(ROOT, "loop", {"DJB_SELFTEST_DRIVES_DIR": "x"})) == 2
    assert f"\n   the tool said: {said}" in capfd.readouterr().err
