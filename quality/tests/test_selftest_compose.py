"""The selftest leg composed: every member runs, one verdict out of all of them, 2 outranking 1."""

# deleted: case_a_members_capture_puts_the_shells_own_handlers_back_byte_for_byte — a bash-`trap` composition that no longer exists; `subprocess` cannot touch the caller's handlers  # noqa: E501
# deleted: case_a_leg_in_a_subshell_does_not_bring_its_parents_handlers_to_life — a bash-`trap` composition that no longer exists; `subprocess` cannot touch the caller's handlers  # noqa: E501
# deleted: case_every_registered_drive_line_and_sentinel_survives_the_function — dies with the shim
# pin: test_the_unregistered_population_is_empty_and_the_gap_banner_is_silent (registry `unit`)
# deleted: case_the_gate_calls_the_function_and_owns_its_one_exit — dies with the shim
# pin: test_legs_selftest.py::test_the_leg_claims_the_selftest_line_first_and_gate_tests_stays_last
# narrowed: case_every_exit_in_the_leg_body_is_inside_a_drive_subshell — an `ast` census
# narrowed: every planted drive prints its summary line — the Python judge reads exit AND summary
# narrowed: case_a_named_non_shell_path_selects_its_drive — asked of `always_on.touched`
# narrowed: case_an_ingested_row_reuses_on_the_same_image — the engine banks no row (pin-red below)
# narrowed: case_no_reuse_runs_everything_and_banks — its engine row is the engine cases'
# narrowed: case_the_partition_balances_by_duration_and_names_the_table_it_read — names a column
# narrowed: case_the_plan_line_prints_the_flags_k_and_names_the_ci_table_first — column order
# narrowed: case_an_absent_durations_table_is_the_round_robin_and_says_so — the line names no path
# narrowed: case_the_engines_declaration_covers_exactly_its_inputs — read off the engine's row
# narrowed: case_the_engines_inputs_carry_the_products_drawer — the engine run in a checkout
# narrowed: case_a_product_drive_in_the_drawer_runs_and_is_named_local — the registry refuses it
# narrowed: case_a_red_product_drive_is_named_and_the_leg_is_exit_1 — the registry refuses it
# narrowed: case_a_drawer_drive_without_the_preamble_is_exit_2 — every drawer is refused, unrun
# narrowed: case_no_drawer_leaves_the_legs_transcript_byte_identical — no reader of the env seam
# narrowed: case_a_hand_typed_whole_run_on_an_unsharded_run_is_unset_with_a_line — through run()
# does-not-cover: a member that ignores the signal it is sent — the leg waits on it.
# does-not-cover: a product drive drawer — the registry refuses a tree carrying one.
# does-not-cover: whether the committed walls table is any good — every table here is planted.

from __future__ import annotations

import ast
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from quality.djb import env as djb_env
from quality.djb import ledger
from quality.djb import registry as R
from quality.djb.box.loop import box_ledger_ingest
from quality.djb.legs import always_on as ao
from quality.djb.legs import selftest as st
from quality.djb.modes import member_walls

pytestmark = pytest.mark.drives(
    "quality/djb/legs/selftest.py",
    "scripts/check.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_refuse.sh",
    "scripts/tests/drive_preamble.sh",
    "quality/tests/fixtures/runbook/render_recipe.py",
    "quality/tests/fixtures/collection_world/apps/world_alpha/nested/",
    "docs/product/build-contract.md",
    "compose.yaml",
    ".secrets.baseline",
)

ROOT = Path(__file__).resolve().parents[2]
#: The engine member's stand-in: answers `--selftest-inputs` from a file, every other ask by exit.
UV = """#!/bin/sh
for a in "$@"; do
    if [ "$a" = "--selftest-inputs" ]; then
        [ -z "${DJB_FAKE_INPUTS:-}" ] || cat "${DJB_FAKE_INPUTS}"
        exit "${DJB_FAKE_INPUTS_RC:-0}"
    fi
    if [ "$a" = "-c" ]; then
        printf '%s\\n' ${DJB_FAKE_RULE_IDS:-1 2 3}
        exit 0
    fi
done
[ -z "${DJB_FAKE_ARGV:-}" ] || echo "$*" >>"$DJB_FAKE_ARGV"
case " $* " in *" --rule ${DJB_FAKE_DEAD_RULE:-none} "*) echo "  !! rule dead"; exit 2 ;; esac
exit "${DJB_FAKE_UV_RC:-0}"
"""
INPUTS = "docs/product/build-contract.md\nscripts/tests/drive_preamble.sh\n"
#: The names a CI unit sets for the leg it runs; a world that inherits them shards itself.
UNIT_INPUTS = ("GATE_LEG_UNIT", "GATE_SHARD_K", "GATE_SHARD_N", "MEASURED_START")
PREAMBLE = "scripts/tests/drive_preamble.sh"
#: The `leg` fixture's runner: `(root, shard, **env)` to `(exit, transcript)`.
LegRun = Callable[..., tuple[int, str]]
#: A planted drive's verdict line, the shape `quality/tests/drives.py` reads.
SUMMARY = {
    0: 'echo "{own}: 1 passed · 0 failed · 0 skipped"',
    1: 'echo "{own}: 0 passed · 1 failed · 0 skipped"',
    2: 'echo "{own}: 0 passed · 0 failed · 0 skipped · 1 could not look"',
}


class World:
    """A scratch drive set, the stand-in `uv`, a scratch ledger and the leg's environment."""

    def __init__(self, home: Path) -> None:
        self.home = home
        self.drives = home / "drives"
        self.drives.mkdir(parents=True)
        (self.drives / "drive_preamble.sh").write_text("# a scratch drive set preamble\n")
        (home / "bin").mkdir()
        (home / "bin/uv").write_text(UV)
        (home / "bin/uv").chmod(0o755)
        (home / "inputs.txt").write_text(INPUTS)
        self.env = {
            **os.environ,
            "PATH": f"{home / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "TMPDIR": str(home),
            "DJB_FAKE_INPUTS": str(home / "inputs.txt"),
            "DJB_SELFTEST_DRIVES_DIR": str(self.drives),
            "DJB_LOCAL_DRIVES_DIR": str(home / "no-drive-drawer-at-all"),
            "DJB_GATE_MEMBER_WALLS_CI": str(home / "no-ci-walls-table.json"),
            "DJB_GATE_LEDGER": str(home / "ledger"),
        }
        for gone in (*djb_env.STEERS, "DJB_SELFTEST_NO_REUSE", *UNIT_INPUTS):
            self.env.pop(gone, None)

    def plant(self, *specs: str, body: str = "", decl: str = PREAMBLE) -> None:
        """`name:rc` drives: each speaks a line, prints its summary and exits `rc`."""
        for spec in specs:
            name, rc = spec.split(":")
            path = self.drives / f"test_{name}.sh"
            say = SUMMARY[int(rc)].format(own=path.stem)
            path.write_text(
                f"#!/bin/sh\n# drives: {decl}\n"
                f'echo "planted drive {name} speaking"\n{body}{say}\nexit {rc}\n'
            )
            path.chmod(0o755)

    def failing(self, name: str, n: int) -> None:
        """A red drive printing `n` FAILED lines."""
        lines = "".join(f'echo "  FAILED   case_{i} — planted why {i}"\n' for i in range(1, n + 1))
        path = self.drives / f"test_{name}.sh"
        path.write_text(
            "#!/bin/sh\n# drives: scripts/tests/drive_preamble.sh\n"
            f'echo "planted drive {name} speaking"\n{lines}'
            f'echo "{path.stem}: 0 passed · {n} failed · 0 skipped"\nexit 1\n'
        )
        path.chmod(0o755)


@pytest.fixture
def world(scratch: Path) -> World:
    return World(scratch / "world")


@pytest.fixture
def leg(world: World, capfd: pytest.CaptureFixture[str]) -> Callable[..., tuple[int, str]]:
    """The leg over the world, its exit and its whole transcript."""

    def run(root: Path = ROOT, shard: tuple[int, int] | None = None, **env: str) -> tuple[int, str]:
        capfd.readouterr()
        rc = st.run(R.Ctx(root, "full", {**world.env, **env}), shard)
        out, err = capfd.readouterr()
        return rc, out + err

    return run


# --- the composition ---------------------------------------------------------------


def test_all_green_prints_one_line_per_drive_and_the_summary(world: World, leg: LegRun) -> None:
    world.plant("1_alpha:0", "2_bravo:0", "3_charlie:0")
    rc, out = leg()
    assert rc == 0, out
    lines = out.splitlines()
    for name in ("1_alpha", "2_bravo", "3_charlie", "house-rules-engine"):
        assert any(
            line.startswith(f"  drive {name}: exit 0 (") and line.endswith("s)") for line in lines
        ), f"no `drive {name}: exit 0 (Ns)` line"
    assert "selftest: 4 drive(s) green · 0 red · 0 could-not-look" in out


def test_two_red_drives_are_both_named_and_the_leg_is_exit_1(world: World, leg: LegRun) -> None:
    world.plant("1_alpha:0", "2_bravo:1", "3_charlie:0", "4_delta:1", "5_echo:0")
    rc, out = leg()
    assert rc == 1
    for name in ("3_charlie", "4_delta", "5_echo"):
        assert f"drive {name}: exit " in out, f"the leg stopped at the first red — {name}"
    red = next(line for line in out.splitlines() if line.startswith("!! RED:"))
    assert "2_bravo" in red and "4_delta" in red
    assert "selftest: 4 drive(s) green · 2 red · 0 could-not-look" in out


def test_a_red_members_failed_lines_are_printed_beside_its_red(world: World, leg: LegRun) -> None:
    world.plant("1_alpha:0")
    world.failing("2_bravo", 12)
    world.failing("3_charlie", 2)
    rc, out = leg()
    assert rc == 1, out
    tail = out[out.index("!! RED:") :]
    for want in (
        "2_bravo: 12 FAILED line(s), the first 10 below",
        "FAILED   case_1 — planted why 1",
        "FAILED   case_10 — planted why 10",
        "... and 2 more FAILED line(s), above in its own output",
        "3_charlie: 2 FAILED line(s)",
        "FAILED   case_2 — planted why 2",
    ):
        assert want in tail, f"beside the RED the leg does not print {want!r}"
    assert "case_11 — planted why 11" not in tail, "the digest is not capped at ten"
    assert "FAILED   case_12 — planted why 12" in out
    assert "planted drive 1_alpha speaking" in out


KILLED = """
import os, sys
from pathlib import Path
from quality.djb import registry as R
from quality.djb.legs import selftest as st
sys.exit(st.run(R.Ctx(Path(sys.argv[1]), "full", dict(os.environ))))
"""


def kill_mid_run(world: World, sig: signal.Signals) -> tuple[int, str]:
    """The leg in its own process group; `sig` to the group once the slow member has spoken."""
    marker = world.home / f"running-{sig.name}"
    world.plant("1_alpha:0")
    slow = world.drives / "test_2_bravo.sh"
    slow.write_text(
        "#!/bin/sh\n# drives: scripts/tests/drive_preamble.sh\n"
        'echo "partial line from 2_bravo"\necho "a second line from 2_bravo"\n'
        f': >"{marker}"\nsleep 30\necho "never reached"\n'
    )
    slow.chmod(0o755)
    log = world.home / f"killed-{sig.name}.out"
    with log.open("wb") as sink:
        child = subprocess.Popen(
            [sys.executable, "-c", KILLED, str(ROOT)],
            cwd=ROOT,
            env=world.env,
            stdout=sink,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.monotonic() + 60
        while not marker.exists() and time.monotonic() < deadline and child.poll() is None:
            time.sleep(0.1)
        assert marker.exists(), f"the slow member never started: {log.read_text()}"
        os.killpg(child.pid, sig)
        try:
            rc = child.wait(timeout=60)
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGKILL)
    return rc, log.read_text(errors="replace")


def test_a_member_killed_mid_run_reaches_the_log_with_its_output_so_far(world: World) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        for old in world.drives.glob("test_*.sh"):
            old.unlink()
        rc, out = kill_mid_run(world, sig)
        for want in (
            "drive 2_bravo: killed after",
            "its output so far:",
            "partial line from 2_bravo",
            "a second line from 2_bravo",
        ):
            assert want in out, f"{sig.name}: a member killed mid-run left the log without {want!r}"
        assert "never reached" not in out, f"{sig.name}: the member was not killed at all"
        assert rc in (-sig, 128 + sig), f"{sig.name}: the leg exited {rc}, not the signal's own"


def test_a_could_not_look_drive_outranks_a_red_one_and_both_are_named(
    world: World, leg: LegRun
) -> None:
    world.plant("1_alpha:1", "2_bravo:2", "3_charlie:0")
    rc, out = leg()
    assert rc == 2
    assert "drive 3_charlie: exit 0" in out
    lines = out.splitlines()
    assert "2_bravo" in next(x for x in lines if x.startswith("!! COULD NOT LOOK:"))
    assert "1_alpha" in next(x for x in lines if x.startswith("!! and RED:"))
    assert "selftest: 2 drive(s) green · 1 red · 1 could-not-look" in out


def test_a_red_engine_selftest_still_runs_every_drive_and_the_leg_is_exit_2(
    world: World, leg: LegRun
) -> None:
    world.plant("1_alpha:0", "2_bravo:0")
    rc, out = leg(DJB_FAKE_UV_RC="1")
    assert rc == 2
    assert "ENFORCEMENT ITSELF IS BROKEN" in out
    assert "drive 1_alpha: exit 0" in out and "drive 2_bravo: exit 0" in out
    assert "selftest: 2 drive(s) green · 0 red · 1 could-not-look" in out


@pytest.mark.parametrize(
    ("namespace", "ids"),
    [(None, "1 2 3"), ("acme", "1 2 3"), ("acme", "1 2 acme-1 acme-2")],
    ids=["template", "product", "product-with-drawer-rules"],
)
def test_on_a_product_tree_the_engine_selftests_the_drawers_rules_alone(
    world: World, leg: LegRun, monkeypatch: pytest.MonkeyPatch, namespace: str | None, ids: str
) -> None:
    from quality.djb.legs import gate_tests

    monkeypatch.setattr(gate_tests, "product_of", lambda root: namespace)
    world.plant("1_alpha:0")
    argv = world.home / "argv"
    rc, out = leg(DJB_FAKE_ARGV=str(argv), DJB_FAKE_RULE_IDS=ids)
    ran = [line for line in (argv.read_text() if argv.exists() else "").splitlines()]
    engine = [line for line in ran if "quality.gate --selftest" in line]
    assert rc == 0, out
    assert "drive 1_alpha: exit 0" in out
    if namespace is None:
        assert engine == ["run python -m quality.gate --selftest"], ran
        assert st.ENGINE_ON_A_PRODUCT not in out
        return
    assert f"  {st.ENGINE_ON_A_PRODUCT}" in out.splitlines()
    if "acme-" not in ids:
        assert engine == [], ran
        return
    assert engine == [
        "run python -m quality.gate --selftest --member --rule acme-1 --rule acme-2"
    ], ran
    assert "  house-rules-engine acme: the drawer's 2 rule(s) self-tested alone, never banked" in (
        out.splitlines()
    )


def test_every_exit_in_the_leg_body_is_inside_a_drive_subshell() -> None:
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
    assert exits == [], f"selftest.py exits outside its composed verdict at line(s) {exits}"
    assert "compose" in {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}


# --- the gap banner -------------------------------------------------------------------


def unregistered(root: Path) -> list[str]:
    """The drives on disk in either home that the selftest unit does not register."""
    registered = set(R.load(root).unit("selftest")[1])
    found = sorted(
        f"{home}/{p.name}"
        for home in st.HOMES
        for p in (root / home).glob("test_*.sh")
        if p.stem[len("test_") :] not in registered
    )
    return found


def test_the_unregistered_population_is_empty_and_the_gap_banner_is_silent(
    world: World, leg: LegRun
) -> None:
    assert unregistered(ROOT) == [], "a drive is on disk in a home and in no selftest member"
    world.plant("1_alpha:0")
    rc, out = leg()
    assert rc == 0
    assert "NOT RUN BY THIS LEG" not in out


def test_the_not_run_block_names_an_unregistered_drive_in_either_home(scratch: Path) -> None:
    """RED until legs/selftest.py carries the not-run block check.sh prints above the engine leg."""
    not_run = getattr(st, "not_run", None)
    assert callable(not_run), (
        "legs/selftest.py has no not-run block: check.sh's `NOT RUN BY THIS LEG` census of"
        " unregistered drives in scripts/tests/ and deploy/tests/ has no Python home"
    )
    for rel in (
        "scripts/tests/test_wired.sh",
        "scripts/tests/test_loose.sh",
        "deploy/tests/test_wired_deploy.sh",
        "deploy/tests/test_loose_deploy.sh",
    ):
        (scratch / rel).parent.mkdir(parents=True, exist_ok=True)
        (scratch / rel).write_text("")
    said = not_run(scratch, {"wired", "wired_deploy"})
    assert said == ["deploy/tests/test_loose_deploy.sh", "scripts/tests/test_loose.sh"]
    assert not_run(ROOT, set(R.load(ROOT).unit("selftest")[1])) == []


#: A non-shell path a drive may name.
RECIPE = "scripts/dangling_paths.py"


def test_a_named_non_shell_path_selects_its_drive(
    world: World, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, decl in (
        ("recipe", RECIPE),
        ("aside", "scripts/kill_mine.sh"),
    ):
        (world.drives / f"test_{name}.sh").write_text(f"#!/bin/sh\n# drives: {decl}\nexit 0\n")
    ctx = R.Ctx(ROOT, "loop", world.env)
    rows = ao.drives(ctx, None)
    capsys.readouterr()
    picked = ao.touched(ctx, rows, [RECIPE, "apps/example/api.py"], [], [])
    out = capsys.readouterr().out
    assert f"always-on (touched): 1 drives cover {RECIPE}" in out, out
    assert f"always-on (touched): recipe: touched: {RECIPE}" in out, out
    assert picked == ["recipe"], f"the selection is not exactly the named member: {picked}"


# --- the drive verdicts ------------------------------------------------------------


def banked(world: World, ledger: str = "ledger") -> list[list[str]]:
    """The `drive` rows a ledger holds, each split into its words."""
    path = world.home / ledger
    lines = path.read_text().splitlines() if path.is_file() else []
    return [w for w in (line.split() for line in lines) if len(w) > 4 and w[2] == "drive"]


def planted_rows(world: World, ledger: str = "ledger") -> list[list[str]]:
    """The drive rows of the planted members, the engine's left out by name."""
    return [w for w in banked(world, ledger) if w[4] != R.ENGINE_MEMBER]


def reused(out: str) -> list[str]:
    """The planted members a transcript says it REUSED."""
    return [
        line.split(":")[0].split()[-1]
        for line in out.splitlines()
        if line.startswith("  drive ")
        and ": REUSED " in line
        and not line.startswith(f"  drive {R.ENGINE_MEMBER}:")
    ]


def ran(out: str, name: str, rc: str = "0") -> bool:
    """Whether the transcript carries `drive <name>: exit <rc> (Ns)`."""
    return re.search(rf"^  drive {re.escape(name)}: exit {rc} \([0-9]+s\)$", out, re.M) is not None


REUSED = (
    r"REUSED from drive-v1:[0-9a-f]{{64}} "
    r"\(banked [0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}T[0-9:]+Z\) machine={m}$"
)


def test_a_banked_drive_is_reused_and_named(world: World, leg: LegRun) -> None:
    runs = world.home / "runs"
    world.plant("1_alpha:0", "2_bravo:0", body=f'echo "$0" >>"{runs}"\n')
    rc, out = leg()
    assert rc == 0, out
    assert "REUSED" not in out, "the FIRST run reused something — nothing was banked before it"
    assert len(planted_rows(world)) == 2
    first = runs.read_text()
    assert len(first.splitlines()) == 2, first
    rc, out = leg()
    assert rc == 0, out
    for n in ("1_alpha", "2_bravo"):
        want = rf"^  drive {n}: " + REUSED.format(m=r"(host:[0-9a-f]{12}|image:[A-Za-z0-9_.-]+)")
        assert re.search(want, out, re.M), f"no REUSED line for {n}: {out}"
    assert "selftest: 3 drive(s) green · 0 red · 0 could-not-look" in out
    assert runs.read_text() == first, "a leg that reused everything drove something"


def test_a_moved_driven_byte_refuses_the_reuse(world: World, leg: LegRun, checkout: Path) -> None:
    subject = "scripts/scratch_subject.sh"
    (checkout / subject).write_text("# a scratch subject nothing else in this tree reads\n")
    world.plant("1_alpha:0", decl=subject)
    rc, out = leg(checkout)
    assert rc == 0 and len(planted_rows(world)) == 1, out
    first = planted_rows(world)[0][1]
    with (checkout / subject).open("a") as fh:
        fh.write("# one more comment byte\n")
    rc, out = leg(checkout)
    assert reused(out) == [], f"a moved byte in {subject} was REUSED anyway"
    assert ran(out, "1_alpha"), out
    assert f"miss: {subject} moved since {first}" in out, out

    for moved, book in (("test_1_alpha.sh", "ledger-self"), ("drive_preamble.sh", "ledger-pre")):
        env = {"DJB_GATE_LEDGER": str(world.home / book)}
        world.plant("1_alpha:0")
        leg(checkout, **env)
        assert len(planted_rows(world, book)) == 1, f"the {moved} plant did not bank a row first"
        first = planted_rows(world, book)[0][1]
        with (world.drives / moved).open("a") as fh:
            fh.write("# one more comment byte\n")
        rc, out = leg(checkout, **env)
        assert reused(out) == [], f"a moved byte in {moved} was REUSED anyway"
        misses = [line for line in out.splitlines() if "miss:" in line]
        assert any(moved in m and f"moved since {first}" in m for m in misses), misses


# --- the rows that travel ------------------------------------------------------------

FOREIGN = (
    "v1 drive-v1:" + "f0" * 32 + " drive 2026-09-18T09:00:00Z 9_foreign exit=0 took=3"
    " tree=deadbeef parts=x:000000000000"
)


def test_an_ingested_row_reuses_on_the_same_image(world: World, leg: LegRun) -> None:
    image = world.home / "ingest-image-id"
    image.write_text("ami-0ing3st0ing3st000\n")
    world.plant("1_alpha:0", "2_bravo:0")
    rc, out = leg(DJB_DRIVE_MACHINE_FILE=str(image))
    assert rc == 0 and len(planted_rows(world)) == 2, out
    carried = [
        line for line in (world.home / "ledger").read_text().splitlines() if " drive " in line
    ]
    carried.append(FOREIGN)

    box = world.home / "boxside"
    (box / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(box)], check=True)
    for lib in ("gate_ledger.sh", "gate_refuse.sh"):
        (box / "scripts" / lib).write_bytes((ROOT / "scripts" / lib).read_bytes())
    others = [
        "v1 fullkeyaaa full 2026-09-18T08:00:00Z ruff,mypy exit=0 took=900 tree=aaaa",
        "loop-v1 loop-v1:bbb loop 2026-09-18T08:30:00Z caller=unstated tree=bbbb",
    ]
    boxledger = box / ".git/djb-gate-verdicts"
    boxledger.write_text("\n".join([carried[0], *others]) + "\n")
    home = world.home / "boxhome"
    (home / "verify/a-rung").mkdir(parents=True)
    (home / "verify/a-rung/ledger.in").write_text("\n".join(carried) + "\n")
    line = box_ledger_ingest(str(box), "a-rung")
    env = {k: v for k, v in os.environ.items() if k != "DJB_GATE_LEDGER"}

    def ingest() -> None:
        subprocess.run(["bash", "-c", f"cd '{box}' && {line}"], env={**env, "HOME": str(home)})

    ingest()
    lines = boxledger.read_text().splitlines()
    assert len(lines) == len(others) + len(set(carried)), lines
    before = boxledger.read_bytes()
    ingest()
    assert boxledger.read_bytes() == before, "a second ingest changed the box ledger"

    rc, out = leg(DJB_DRIVE_MACHINE_FILE=str(image), DJB_GATE_LEDGER=str(boxledger))
    assert rc == 0, out
    for n in ("1_alpha", "2_bravo"):
        want = rf"^  drive {n}: " + REUSED.format(m=r"image:ami-0ing3st0ing3st000")
        assert re.search(want, out, re.M), f"no REUSED … machine=image line for {n}: {out}"
    other = world.home / "other-image-id"
    other.write_text("ami-0n0tth3sam3imag3\n")
    rc, out = leg(DJB_DRIVE_MACHINE_FILE=str(other), DJB_GATE_LEDGER=str(boxledger))
    assert "REUSED" not in out.replace(f"drive {R.ENGINE_MEMBER}: REUSED", ""), out
    assert re.search(
        r"^  miss: machine moved since drive-v1:[0-9a-f]{64} machine=image:ami-0n0tth3sam3imag3$",
        out,
        re.M,
    ), out


def test_an_unreadable_machine_file_cannot_key(world: World, leg: LegRun) -> None:
    locked = world.home / "locked-image-id"
    locked.write_text("ami-0l0ck3d0l0ck3d000\n")
    locked.chmod(0)
    world.plant("1_alpha:0")
    try:
        rc, out = leg(DJB_DRIVE_MACHINE_FILE=str(locked))
    finally:
        locked.chmod(0o644)
    assert "  drive 1_alpha: could not key — this machine could not be digested" in out, out
    assert rc == 2
    assert banked(world) == [], "a row was banked over a machine nothing could name"


def test_an_unbanked_drive_runs(world: World, leg: LegRun) -> None:
    world.plant("1_alpha:0", "2_bravo:0", "3_charlie:0")
    _, out = leg()
    assert "REUSED" not in out
    missing = [n for n in ("1_alpha", "2_bravo", "3_charlie") if not ran(out, n)]
    assert missing == [], f"against an empty ledger these drives did not run: {missing}"


def unmarked(world: World, name: str) -> None:
    path = world.drives / f"test_{name}.sh"
    path.write_text(f'#!/bin/sh\necho "unmarked drive {name} speaking"\nexit 0\n')
    path.chmod(0o755)


def cannot_key(out: str, name: str) -> str:
    """The `could not key` line for `name`, or empty."""
    return next(
        (x for x in out.splitlines() if x.startswith(f"  drive {name}: could not key — ")), ""
    )


def test_an_undecidable_key_is_exit_2(world: World, leg: LegRun, checkout: Path) -> None:
    world.plant("1_alpha:0")
    unmarked(world, "2_unmarked")
    rc, out = leg(checkout)
    assert rc == 2, out
    assert cannot_key(out, "2_unmarked"), out
    assert "2_unmarked" in next(x for x in out.splitlines() if x.startswith("!! COULD NOT LOOK:"))

    for old in world.drives.glob("test_*.sh"):
        old.unlink()
    world.plant("1_absent:0", decl="scripts/there_is_no_such_file_here.sh")
    rc, out = leg(checkout, DJB_GATE_LEDGER=str(world.home / "ledger-absent"))
    assert rc == 2, out
    assert "there_is_no_such_file_here.sh" in cannot_key(out, "1_absent"), out

    world.drives.joinpath("test_1_absent.sh").unlink()
    (checkout / "scripts/other.sh").write_text("# a scratch subject the marker will not cover\n")
    world.plant("1_uncovered:0", body="# reaches scripts/other.sh without declaring it\n")
    rc, out = leg(checkout, DJB_GATE_LEDGER=str(world.home / "ledger-uncovered"))
    assert rc == 2, out
    assert "scripts/other.sh" in cannot_key(out, "1_uncovered"), out


def test_the_floor_reaches_every_top_level_the_tree_has(world: World, leg: LegRun) -> None:
    for i, spelled in enumerate(
        ("docs/product/build-contract.md", "compose.yaml", ".secrets.baseline")
    ):
        world.plant("1_toplevel:0", body=f"# reaches {spelled} without declaring it\n")
        rc, out = leg(DJB_GATE_LEDGER=str(world.home / f"ledger-top-{i}"))
        assert rc == 2, f"{spelled} spelled undeclared gave exit {rc} — the floor cannot see it"
        assert spelled in cannot_key(out, "1_toplevel"), out
    world.plant(
        "1_toplevel:0",
        body="# reaches docs/product/build-contract.md and says so\n",
        decl="docs/product/build-contract.md",
    )
    rc, out = leg()
    assert rc == 0 and len(planted_rows(world)) == 1, (
        f"a DECLARED top-level path did not bank: {out}"
    )


def test_a_declaration_of_the_gate_carries_its_sourced_libraries(
    world: World, leg: LegRun, checkout: Path
) -> None:
    lib = "scripts/gate_refuse.sh"
    world.plant("1_alpha:0", decl="scripts/check.sh")
    rc, out = leg(checkout)
    assert rc == 0 and len(planted_rows(world)) == 1, out
    parts = next(w for w in planted_rows(world)[0] if w.startswith("parts="))
    assert f"{lib}:" in parts, (
        f"the key of a drive declaring the gate does not carry {lib}: {parts}"
    )
    with (checkout / lib).open("a") as fh:
        fh.write("# one more comment byte, in a scratch checkout\n")
    rc, out = leg(checkout)
    assert reused(out) == [], f"a moved byte in {lib} was REUSED anyway"
    assert any(lib in x for x in out.splitlines() if "miss:" in x), out


def test_two_drives_with_identical_content_do_not_share_a_verdict(
    world: World, leg: LegRun
) -> None:
    for name in ("1_alpha", "2_bravo", "3_charlie"):
        path = world.drives / f"test_{name}.sh"
        path.write_text(
            f'#!/bin/sh\n# drives: {PREAMBLE}\necho "a planted twin speaking"\n'
            'echo "$(basename "$0" .sh): 1 passed · 0 failed · 0 skipped"\nexit 0\n'
        )
        path.chmod(0o755)
    rc, out = leg()
    assert rc == 0, out
    assert reused(out) == [], "a twin was REUSED on the FIRST run"
    rows = planted_rows(world)
    assert len(rows) == 3 and len({w[1] for w in rows}) == 3, rows
    _, out = leg()
    assert sorted(reused(out)) == ["1_alpha", "2_bravo", "3_charlie"], out


def test_a_cited_path_is_subtracted_from_the_floor_and_from_no_key(
    world: World, leg: LegRun, checkout: Path
) -> None:
    subject = "scripts/scratch_cited.sh"
    (checkout / subject).write_text("# a scratch path this drive only talks about\n")
    world.plant("1_cited:0", body=f"# talks about {subject} and neither declares nor cites it\n")
    rc, _ = leg(checkout, DJB_GATE_LEDGER=str(world.home / "ledger-uncited"))
    assert rc == 2, "the valve has widened the floor"

    drive = world.drives / "test_1_cited.sh"

    def cite(*paths: str) -> None:
        world.plant("1_cited:0")
        with drive.open("a") as fh:
            fh.write(f"# cites: {' '.join(paths)}\n")

    cite(subject)
    rc, out = leg(checkout)
    assert rc == 0, out
    assert "1 path(s) CITED, in no key" in out, out
    with (checkout / subject).open("a") as fh:
        fh.write("# one more comment byte\n")
    _, out = leg(checkout)
    assert reused(out) == ["1_cited"], f"a byte in a CITED path refused the reuse: {out}"

    env = {"DJB_GATE_LEDGER": str(world.home / "ledger-cites-moved")}
    cite(subject)
    leg(checkout, **env)
    cite(subject, PREAMBLE)
    leg(checkout, **env)
    keys = [w[1] for w in planted_rows(world, "ledger-cites-moved")]
    assert len(keys) == 2 and keys[0] != keys[1], (
        f"the citation line moved and the key did not: {keys}"
    )


def test_only_a_green_drive_banks(world: World, leg: LegRun) -> None:
    world.plant("1_red:1", "2_cannot:2", "3_green:0")
    rc, _ = leg()
    assert rc == 2
    names = {w[4] for w in planted_rows(world)}
    assert not names & {"1_red", "2_cannot"}, f"a non-green drive banked a row: {names}"
    _, out = leg()
    assert ran(out, "1_red", "[12]") and ran(out, "2_cannot", "[12]"), out
    assert "drive 3_green: REUSED" in out, out


def taken(out: str) -> list[str]:
    """The members a run took — ran or reused; `not in shard` is not membership."""
    return re.findall(r"^  drive ([^:]+): (?:exit |REUSED)", out, re.M)


def held(out: str) -> list[str]:
    """The unit's legs after this one that the plan put in this shard."""
    return re.findall(r"^  leg ([^:]+): in shard ", out, re.M)


def test_a_reused_drive_keeps_its_shard_index(world: World, leg: LegRun, scratch: Path) -> None:
    two = World(scratch / "two")
    two.plant("1_alpha:0", "2_bravo:0")
    world.plant("1_alpha:0", "2_bravo:0", "3_charlie:0", "4_delta:0", "5_echo:0")
    leg(DJB_SELFTEST_DRIVES_DIR=str(two.drives))
    assert len(planted_rows(world)) == 2
    took: list[str] = []
    seen_reused: list[str] = []
    skipped = 0
    for k in (0, 1):
        rc, out = leg(shard=(k, 2))
        assert rc == 0, out
        took += taken(out)
        seen_reused += reused(out)
        skipped += out.count(f": not in shard {k + 1}/2")
    for n in ("1_alpha", "2_bravo", "3_charlie", "4_delta", "5_echo"):
        assert took.count(n) == 1, f"{n} was taken {took.count(n)} time(s): {took}"
    assert {"1_alpha", "2_bravo"} & set(seen_reused), seen_reused
    assert skipped, "no `not in shard` line at all"


def test_no_reuse_runs_everything_and_banks(world: World, leg: LegRun) -> None:
    world.plant("1_alpha:0", "2_bravo:0")
    leg()
    before = len(planted_rows(world))
    assert before == 2
    rc, out = leg(DJB_SELFTEST_NO_REUSE="1")
    assert rc == 0, out
    assert "REUSED" not in out
    assert "== drive verdicts NOT consulted: DJB_SELFTEST_NO_REUSE is set ==" in out
    assert len(planted_rows(world)) > before, "a forced green is newer evidence for the same key"
    assert ran(out, R.ENGINE_MEMBER), "DJB_SELFTEST_NO_REUSE=1 did not run the engine"


# --- the duration-balanced partition --------------------------------------------------

LPT_SET = ("1_alpha", "2_bravo", "3_charlie", "4_delta", "5_echo", "6_foxtrot", "7_golf", "8_hotel")
LPT_TABLE = dict(
    zip((*LPT_SET, R.ENGINE_MEMBER), (100, 90, 80, 70, 60, 50, 40, 30, 20), strict=True)
)
COLUMNS = ("darwin", "ubuntu-latest", "box")


def plant_walls(root: Path, seconds: dict[str, int], columns: tuple[str, ...] = COLUMNS) -> None:
    """The checkout's walls table replaced by `seconds` in each of `columns`; the drawer absent."""
    members = {n: dict.fromkeys(columns, s) for n, s in seconds.items()}
    doc = {"schema": "member-walls/2", "measured_at": dict.fromkeys(columns, "tree:planted")}
    (root / R.WALLS_HOMES[0]).write_text(json.dumps({**doc, "members": members}))
    assert not (root / R.WALLS_HOMES[1]).exists()


def plan_line(out: str, k: int, n: int) -> str:
    """The leg's own plan line for shard `k` (0-based) of `n`, as it prints it."""
    return next(
        (x for x in out.splitlines() if x.startswith(f"  selftest shard {k + 1}/{n}: ")), ""
    )


def lpt_numbers(line: str) -> tuple[int, int] | None:
    """`(members, predicted)` from an LPT plan line; None for the round-robin arm."""
    found = re.search(r": ([0-9]+) members, predicted ([0-9]+) s \(LPT over", line)
    return (int(found[1]), int(found[2])) if found else None


def _priced(weights: dict[str, int], member: str) -> float:
    """A member's planted wall, or a piece's share of its member's wall."""
    if member in weights:
        return weights[member]
    whole = member.partition(R.PIECE)[0]
    return weights[whole] / R.pieces_of(weights, whole, R.load(ROOT).pieces()[whole])


def test_the_partition_balances_by_duration_and_names_the_table_it_read(
    world: World, leg: LegRun, checkout: Path
) -> None:
    world.plant(*(f"{n}:0" for n in LPT_SET))
    weights = {**LPT_TABLE, "gate-tests": 10}
    plant_walls(checkout, weights)
    total, heaviest, s = sum(weights.values()), max(weights.values()), 3
    where: dict[str, int] = {}
    max_lpt = 0
    for k in range(s):
        rc, out = leg(checkout, shard=(k, s))
        assert rc == 0, out
        line = plan_line(out, k, s)
        numbers = lpt_numbers(line)
        assert numbers, f"shard {k + 1}/{s} printed no LPT plan line: {line!r}"
        members = [*taken(out), *held(out)]
        predicted = sum(_priced(weights, m) for m in members)
        assert numbers[0] == len(members) and abs(numbers[1] - predicted) < 1, (line, members)
        assert f"LPT over the walls table, {R._machine()}'s column" in line, line
        max_lpt = max(max_lpt, numbers[1])
        where.update(dict.fromkeys(members, k))
    assert where["1_alpha"] != where["2_bravo"], "the two heaviest members are stacked"
    assert max_lpt <= total / s + heaviest

    (checkout / R.WALLS_HOMES[0]).unlink()
    max_rr = 0
    for k in range(s):
        _, out = leg(checkout, shard=(k, s), DJB_GATE_LEDGER=str(world.home / "ledger-rr"))
        max_rr = max(max_rr, sum(LPT_TABLE[m] for m in taken(out)))
    assert max_lpt < max_rr, f"the partition's heaviest {max_lpt} s, the round-robin's {max_rr} s"


def test_every_member_is_in_exactly_one_shard_and_the_partition_is_deterministic(
    world: World, leg: LegRun, checkout: Path
) -> None:
    world.plant(*(f"{n}:0" for n in LPT_SET))
    plant_walls(checkout, LPT_TABLE)
    passes = []
    for p in ("first", "second"):
        env = {"DJB_GATE_LEDGER": str(world.home / f"ledger-{p}")}
        shards = []
        for k in range(4):
            rc, out = leg(checkout, shard=(k, 4), **env)
            assert rc == 0, out
            shards.append(sorted(taken(out)))
        passes.append(shards)
    union = [m for shard in passes[0] for m in shard]
    assert sorted(union) == sorted(LPT_TABLE), f"not every member exactly once: {passes[0]}"
    assert passes[0] == passes[1], "the same table and the same S assigned differently twice"


def test_an_absent_durations_table_is_the_round_robin_and_says_so(
    world: World, leg: LegRun, checkout: Path
) -> None:
    world.plant(*(f"{n}:0" for n in LPT_SET))
    (checkout / R.WALLS_HOMES[0]).unlink()
    union: list[str] = []
    for k in range(3):
        rc, out = leg(checkout, shard=(k, 3))
        assert rc == 0, f"an absent hint must never be a refusal: {out}"
        line = plan_line(out, k, 3)
        assert "the index round-robin (no durations table" in line, line
        assert lpt_numbers(line) is None
        union += taken(out)
    assert sorted(union) == sorted(LPT_TABLE), union


# --- the engine as members: rule lists that partition the plan -------------------------

#: An engine priced over the ceiling, so the plan cuts it into members.
SPLIT_TABLE = {**LPT_TABLE, R.ENGINE_MEMBER: 3 * R.SHARD_CEILING_S - 100}
SPLIT_IDS = "1 2 3 4 5 6 7"


def engine_argv(path: Path) -> list[list[str]]:
    """Each engine member's argv the stub `uv` recorded, as its words."""
    lines = path.read_text().splitlines() if path.is_file() else []
    return [line.split() for line in lines if "--selftest" in line.split()]


def member_rules(words: list[str]) -> list[str]:
    """The `--rule` ids one engine member was handed."""
    return [words[i + 1] for i, w in enumerate(words[:-1]) if w == "--rule"]


def test_the_engine_members_partition_the_rules_and_one_carries_the_whole_parts(
    world: World, leg: LegRun, checkout: Path
) -> None:
    world.plant(*(f"{n}:0" for n in LPT_SET))
    plant_walls(checkout, SPLIT_TABLE)
    argv = world.home / "argv"
    sink = world.home / "walls.tsv"
    env = {
        "DJB_FAKE_RULE_IDS": SPLIT_IDS,
        "DJB_FAKE_ARGV": str(argv),
        "DJB_MEMBER_WALLS_OUT": str(sink),
    }
    n = R.shard_count(SPLIT_TABLE, [R.ENGINE_MEMBER, *LPT_SET])
    lines = []
    for k in range(n):
        rc, out = leg(checkout, shard=(k, n), **env)
        assert rc == 0, out
        lines.append(plan_line(out, k, n))
    runs = engine_argv(argv)
    held = [r for words in runs for r in member_rules(words)]
    assert sorted(held) == sorted(SPLIT_IDS.split()), f"not every rule exactly once: {runs}"
    assert all("--member" in words for words in runs), runs
    assert sum("--whole" in words for words in runs) == 1, f"the whole parts twice or never: {runs}"
    assert all("the ceiling 600 s bound" in line for line in lines), lines
    names = [row[0] for row in walls_rows(sink) if row[0].startswith(R.ENGINE_MEMBER)]
    from quality.djb.rituals.fold import whole_rows

    rows = [f"member-walls/1\t{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}" for r in walls_rows(sink)]
    folded, gap = whole_rows(rows)
    assert gap == "" and len(names) == len(runs), (names, gap)
    assert sum(1 for row in folded if row.split("\t")[1] == R.ENGINE_MEMBER) == 1, folded
    assert not engine_rows(world), "a member's green was banked as the engine's"


def test_a_dead_canary_reds_exactly_the_shard_holding_its_rule(
    world: World, leg: LegRun, checkout: Path
) -> None:
    plant_walls(checkout, SPLIT_TABLE)
    argv = world.home / "argv"
    n = R.shard_count(SPLIT_TABLE, [R.ENGINE_MEMBER, *LPT_SET])
    for dead in ("2", "6"):
        argv.unlink(missing_ok=True)
        verdicts = []
        for k in range(n):
            env = {"DJB_FAKE_RULE_IDS": SPLIT_IDS, "DJB_FAKE_ARGV": str(argv)}
            rc, out = leg(checkout, shard=(k, n), DJB_FAKE_DEAD_RULE=dead, **env)
            verdicts.append(rc)
        runs = engine_argv(argv)
        holder = [i for i, words in enumerate(runs) if dead in member_rules(words)]
        assert len(holder) == 1, runs
        reds = [k for k, rc in enumerate(verdicts) if rc]
        assert len(reds) == 1 and verdicts[reds[0]] == 2, (dead, verdicts)


def test_rule_lists_that_do_not_partition_the_rules_are_exit_2(
    world: World, leg: LegRun, checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plant_walls(checkout, SPLIT_TABLE)
    real = st.engine_lists

    def lossy(ctx: R.Ctx, ids: list[str], n: int) -> tuple[list[list[str]], str]:
        lists, how = real(ctx, ids, n)
        return [m[1:] if i == 0 else m for i, m in enumerate(lists)], how

    monkeypatch.setattr(st, "engine_lists", lossy)
    n = R.shard_count(SPLIT_TABLE, [R.ENGINE_MEMBER, *LPT_SET])
    said = []
    for k in range(n):
        rc, out = leg(checkout, shard=(k, n), DJB_FAKE_RULE_IDS=SPLIT_IDS)
        said.append((rc, out))
    holding = [(rc, out) for rc, out in said if "do not partition" in out]
    assert holding and all(rc == 2 for rc, _ in holding), said
    assert "in no member: 1" in holding[0][1], holding[0][1]


# --- the walls table, the plan line's k, and the walls rows ----------------------------


def test_the_plan_line_prints_the_flags_k_and_names_the_ci_table_first(
    world: World, leg: LegRun, checkout: Path
) -> None:
    world.plant(*(f"{n}:0" for n in LPT_SET))
    mine = R._machine()
    other = "darwin" if mine == "ubuntu-latest" else "ubuntu-latest"
    doubled = {n: 2 * s for n, s in LPT_TABLE.items()}
    walls = {
        "schema": "member-walls/2",
        "measured_at": {mine: "tree:planted", other: "run:424242 tree:planted"},
        "members": {n: {mine: s, other: doubled[n]} for n, s in LPT_TABLE.items()},
    }
    (checkout / R.WALLS_HOMES[0]).write_text(json.dumps(walls))
    rc, out = leg(checkout, shard=(0, 2))
    line = plan_line(out, 0, 2)
    numbers = lpt_numbers(line)
    assert rc == 0 and numbers, f"no LPT plan line printed 1/2 for --shard 1/2: {line!r}"
    assert numbers[1] == sum(LPT_TABLE[m] for m in taken(out)), "not this machine's column"
    assert "selftest shard 0/2" not in out, "the leg printed the 0-based k"

    plant_walls(checkout, doubled, (other,))
    _, out = leg(checkout, shard=(0, 2), DJB_GATE_LEDGER=str(world.home / "ledger-other"))
    numbers = lpt_numbers(plan_line(out, 0, 2))
    assert numbers and numbers[1] == sum(doubled[m] for m in taken(out)), "no column stood in"

    (checkout / R.WALLS_HOMES[0]).unlink()
    _, out = leg(checkout, shard=(0, 2), DJB_GATE_LEDGER=str(world.home / "ledger-none"))
    assert "the index round-robin (no durations table" in plan_line(out, 0, 2), out


def walls_rows(path: Path) -> list[list[str]]:
    """The `member-walls/1` rows in a file, as `[member, rc, seconds, part]`."""
    if not path.is_file():
        return []
    cells = (line.split("\t") for line in path.read_text().splitlines())
    return [c[1:] for c in cells if len(c) == 5 and c[0] == "member-walls/1"]


def seconds_out(text: str) -> str:
    """A transcript with every measured second replaced."""
    return re.sub(r"\([0-9]+s\)", "(Ns)", text)


def test_every_member_writes_a_walls_row_when_asked_and_none_when_not(
    world: World, leg: LegRun
) -> None:
    world.plant("1_alpha:0", "2_bravo:1", "3_charlie:0")
    sink = world.home / "walls-unsharded.tsv"
    _, unset = leg(DJB_SELFTEST_NO_REUSE="1", DJB_GATE_LEDGER=str(world.home / "l-unset"))
    assert not sink.exists()
    _, said = leg(
        DJB_SELFTEST_NO_REUSE="1",
        DJB_GATE_LEDGER=str(world.home / "l-set"),
        DJB_MEMBER_WALLS_OUT=str(sink),
    )
    rows = walls_rows(sink)
    assert sorted(r[0] for r in rows) == sorted(
        [R.ENGINE_MEMBER, "1_alpha", "2_bravo", "3_charlie"]
    )
    for name, rc, took, part in rows:
        assert rc == ("1" if name == "2_bravo" else "0") and took.isdigit() and part == "1/1", rows
    assert seconds_out(unset) == seconds_out(said), "the transcript moved when rows were asked for"

    sink = world.home / "walls-shard.tsv"
    _, out = leg(
        shard=(1, 2),
        DJB_SELFTEST_NO_REUSE="1",
        DJB_GATE_LEDGER=str(world.home / "l-shard"),
        DJB_MEMBER_WALLS_OUT=str(sink),
    )
    rows = walls_rows(sink)
    assert all(r[3] == "2/2" for r in rows) and len(rows) == len(taken(out)), (rows, out)


def test_a_reused_member_writes_reused_and_no_wall(world: World, leg: LegRun) -> None:
    world.plant("1_alpha:0", "2_bravo:0")
    leg()
    sink = world.home / "walls-reused.tsv"
    _, out = leg(DJB_MEMBER_WALLS_OUT=str(sink))
    assert "REUSED" in out, "the second run reused nothing, so this case has no subject"
    rows = walls_rows(sink)
    for name in ("1_alpha", "2_bravo"):
        assert [name, "reused", "-", "1/1"] in rows, rows


def test_a_new_drive_joins_at_the_median_and_is_measured_after_a_harvest(
    world: World, leg: LegRun, checkout: Path
) -> None:
    world.plant("1_alpha:0", "2_bravo:0", "3_charlie:0", "4_newcomer:0")
    walls = {R.ENGINE_MEMBER: 20, "1_alpha": 100, "2_bravo": 60, "3_charlie": 40}
    plant_walls(checkout, {**walls, "gate-tests": 50})
    sink = world.home / "newdrive-walls.tsv"
    env = {"DJB_SELFTEST_NO_REUSE": "1", "DJB_MEMBER_WALLS_OUT": str(sink)}
    _, out = leg(checkout, shard=(0, 1), **env)
    line = plan_line(out, 0, 1)
    assert "; 1 unmeasured at the median 50 s; the ceiling 600 s bound" in line, line
    ledger.store_durations(checkout / R.WALLS_HOMES[0], R._machine(), "tree:x", member_walls(sink))
    _, out = leg(checkout, shard=(0, 1), **env)
    line = plan_line(out, 0, 1)
    assert "; 0 unmeasured at the median " in line, f"the harvest did not measure it: {line}"


# --- the engine's own verdict ---------------------------------------------------------


def engine_rows(world: World, book: str = "ledger") -> list[list[str]]:
    """The engine member's drive rows."""
    return [w for w in banked(world, book) if w[4] == R.ENGINE_MEMBER]


def test_the_engine_banks_on_its_inputs(world: World, leg: LegRun) -> None:
    world.plant("1_alpha:0")
    rc, out = leg()
    assert rc == 0 and ran(out, R.ENGINE_MEMBER), out
    rows = engine_rows(world)
    assert len(rows) == 1, f"a green engine banked {len(rows)} row(s), wanted exactly 1"
    key = rows[0][1]
    assert re.fullmatch(r"drive-v1:[0-9a-f]{64}", key), key
    assert rows[0][5] == "exit=0" and any(
        w.startswith("parts=") and "docs/product/build-contract.md:" in w for w in rows[0]
    ), rows[0]
    rc, out = leg()
    assert rc == 0, out
    assert re.search(rf"^  drive {R.ENGINE_MEMBER}: REUSED from {key} \(banked ", out, re.M), out
    assert not ran(out, R.ENGINE_MEMBER), "the engine RAN anyway after being reused"
    assert "selftest: 2 drive(s) green · 0 red · 0 could-not-look" in out
    assert len(engine_rows(world)) == 1, "the reusing run banked another engine row"


def test_a_moved_engine_input_refuses_the_reuse(world: World, leg: LegRun, checkout: Path) -> None:
    listed, unlisted = "scripts/scratch_engine_listed.txt", "scripts/scratch_engine_unlisted.txt"
    (checkout / listed).write_text("# a scratch path the engine says it reads\n")
    (checkout / unlisted).write_text("# a scratch path the engine says nothing about\n")
    inputs = world.home / "engine-inputs-moved.txt"
    inputs.write_text(f"{listed}\ndocs/product/build-contract.md\n")
    env = {"DJB_FAKE_INPUTS": str(inputs)}
    world.plant("1_alpha:0")
    rc, out = leg(checkout, **env)
    assert rc == 0 and len(engine_rows(world)) == 1, out
    first = engine_rows(world)[-1][1]
    with (checkout / listed).open("a") as fh:
        fh.write("# one more comment byte\n")
    _, out = leg(checkout, **env)
    assert f"drive {R.ENGINE_MEMBER}: REUSED" not in out, f"a moved byte in {listed} was reused"
    assert ran(out, R.ENGINE_MEMBER), out
    assert f"miss: {listed} moved since {first}" in out, out
    second = engine_rows(world)[-1][1]
    with (checkout / unlisted).open("a") as fh:
        fh.write("# one more comment byte\n")
    _, out = leg(checkout, **env)
    assert f"drive {R.ENGINE_MEMBER}: REUSED from {second} " in out, "a byte outside re-keyed"


REFUSED = """‼ --selftest-inputs COULD NOT LOOK (exit 2). A list that quietly lost a member would key a verdict for a tree nobody measured, so nothing is printed:
  !! rule 9: scope path names 'apps/nowhere/*.py', which expands to nothing on this tree
"""  # noqa: E501


def test_an_unprintable_engine_scope_is_exit_2(world: World, leg: LegRun) -> None:
    refusal = world.home / "engine-inputs-refused.txt"
    refusal.write_text(REFUSED)
    world.plant("1_alpha:0")
    rc, out = leg(DJB_FAKE_INPUTS=str(refusal), DJB_FAKE_INPUTS_RC="2")
    assert rc == 2, out
    line = cannot_key(out, R.ENGINE_MEMBER)
    assert "--selftest-inputs" in line and "exited 2" in line, out
    assert "apps/nowhere/*.py" in out
    assert not re.search(rf"^  drive {R.ENGINE_MEMBER}: (exit|REUSED)", out, re.M), out
    assert engine_rows(world) == []
    assert f"!! COULD NOT LOOK: {R.ENGINE_MEMBER}" in out
    assert ran(out, "1_alpha"), "the drives did not still run after the engine could not be keyed"
    empty = world.home / "engine-inputs-empty.txt"
    empty.write_text("")
    rc, out = leg(DJB_FAKE_INPUTS=str(empty), DJB_GATE_LEDGER=str(world.home / "ledger-empty"))
    assert rc == 2, out
    assert "an engine that reads nothing is not an engine" in out, out


def test_the_engines_declaration_covers_exactly_its_inputs(world: World, leg: LegRun) -> None:
    collapsible = "quality/tests/fixtures/collection_world/apps/world_alpha/nested"
    files = subprocess.run(
        ["git", "ls-files", "--", collapsible], cwd=ROOT, capture_output=True, text=True
    ).stdout.split()
    assert len(files) >= 3, f"the fixture world is too small to falsify anything: {files}"
    inputs = world.home / "engine-inputs-cover.txt"
    inputs.write_text("\n".join(sorted([*files, PREAMBLE, "apps/nowhere/never_written.py"])) + "\n")
    world.plant("1_alpha:0")
    rc, out = leg(DJB_FAKE_INPUTS=str(inputs))
    rows = engine_rows(world)
    assert rc == 0 and rows, out
    words = dict(w.split("=", 1) for w in rows[-1][5:] if "=" in w)
    labels = {pair.rpartition(":")[0] for pair in words["parts"].split(",")}
    assert f"{collapsible}/" in labels, f"{collapsible}/ was not collapsed: {sorted(labels)}"
    assert PREAMBLE in labels and not any("apps/nowhere" in x for x in labels), sorted(labels)
    entries = ledger.listing(ROOT, words["tree"])
    under = {e.split(" ", 1)[1] for e in ledger.expand(entries, f"{collapsible}/")}
    assert under == set(files), "the collapse does not expand to exactly the engine's inputs"


def test_the_engines_inputs_carry_the_products_drawer(checkout: Path) -> None:
    assert not (checkout / "quality/local").exists(), "the checkout already carries a drawer"

    def inputs() -> list[str]:
        done = subprocess.run(
            [sys.executable, "-m", "quality.gate", "--selftest-inputs"],
            cwd=checkout,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stdout + done.stderr
        return done.stdout.splitlines()

    before = inputs()
    planted = (
        "quality/local/rules.yaml",
        "quality/local/canary/acme-1/planted.py",
        "quality/local/runners/acme_probe.py",
    )
    for rel in planted:
        (checkout / rel).parent.mkdir(parents=True, exist_ok=True)
        (checkout / rel).write_text("rule_id_namespace: acme\n" if rel.endswith("yaml") else "#\n")
    subprocess.run(["git", "-C", str(checkout), "add", "-N", "--", "quality/local"], check=True)
    after = inputs()
    assert sorted(set(after) - set(before)) == sorted(planted), "the drawer moved more than itself"
    assert set(before) <= set(after), "a path read before the drawer dropped out of the listing"


# --- the member clock -----------------------------------------------------------------


def test_a_drives_seconds_reach_the_member_durations_reader(world: World, leg: LegRun) -> None:
    world.plant("1_alpha:0", body="sleep 2\n")
    table = world.home / "clock-durations.json"
    table.write_text(
        '{"measured_at": "plantedtree", "machine": "Scratch 0.0", "members": {"1_alpha": 0}}'
    )
    sink = world.home / "clock-walls.tsv"
    env = {"DJB_GATE_MEMBER_DURATIONS": str(table), "DJB_ALWAYS_ON_FLOOR": "1"}
    rc, out = leg(DJB_MEMBER_WALLS_OUT=str(sink), **env)
    assert rc == 0, out
    assert member_walls(sink).get("1_alpha", 0) >= 2, (
        f"the seconds did not reach the reader: {sink}"
    )
    assert "above the loop floor" in out, out
    assert "leaves the always-on set at the next --store-durations" in out, out
    rc, out = leg(DJB_GATE_LEDGER=str(world.home / "ledger-subset"), **env)
    assert "above the loop floor" not in out, "a run that records nothing announced a crossing"


# --- the product's own drive drawer ---------------------------------------------------


def drawer(checkout: Path, name: str, text: str) -> None:
    """A drive in the checkout's `scripts/local/drives/`."""
    home = checkout / R.DRAWERS[1]
    home.mkdir(parents=True, exist_ok=True)
    (home / f"test_{name}.sh").write_text(text)
    (home / f"test_{name}.sh").chmod(0o755)


PRODUCT = '#!/usr/bin/env bash\n. scripts/tests/drive_preamble.sh\necho "planted PRODUCT drive {n} speaking"\nok "the product drive spoke"\ndrive_finished\nexit {rc}\n'  # noqa: E501


def refused(out: str) -> bool:
    """Whether the leg refused the drawer before any member ran."""
    return (
        "!! selftest: the drive population could not be read — product drive " in out
        and not any(line.startswith("  drive ") for line in out.splitlines())
    )


def test_a_product_drive_in_the_drawer_runs_and_is_named_local(
    world: World, leg: LegRun, checkout: Path
) -> None:
    world.plant("1_alpha:0")
    drawer(checkout, "acme", PRODUCT.format(n="acme", rc=0))
    rc, out = leg(checkout)
    assert rc == 0, out
    assert "planted PRODUCT drive acme speaking" in out
    assert "drive local:acme: not consulted — a product drive is not keyed or banked" in out
    assert re.search(r"^  drive local:acme: exit 0 \([0-9]+s\)$", out, re.M), out
    assert "selftest: 3 drive(s) green · 0 red · 0 could-not-look" in out, out


def test_a_red_product_drive_is_named_and_the_leg_is_exit_1(
    world: World, leg: LegRun, checkout: Path
) -> None:
    world.plant("1_alpha:0")
    drawer(checkout, "acme", PRODUCT.format(n="acme", rc=1))
    rc, out = leg(checkout)
    assert rc == 1, out
    assert "!! the local:acme drive is red" in out


def test_a_drawer_drive_without_the_preamble_is_exit_2(
    world: World, leg: LegRun, checkout: Path
) -> None:
    world.plant("1_alpha:0")
    for name, text in (
        ("acme", '#!/usr/bin/env bash\necho "a drive that never heard of the preamble"\nexit 0\n'),
        ("acme", "#!/usr/bin/env bash\n# this drive does not source drive_preamble.sh\nexit 0\n"),
        ("Probe", "#!/usr/bin/env bash\n. scripts/tests/drive_preamble.sh\nexit 0\n"),
    ):
        drawer(checkout, name, text)
        rc, out = leg(checkout, LC_ALL="en_US.UTF-8")
        assert rc == 2 and refused(out), out
        assert "a drive that never heard of the preamble" not in out
        (checkout / R.DRAWERS[1] / f"test_{name}.sh").unlink()


def test_no_drawer_leaves_the_legs_transcript_byte_identical(
    world: World, leg: LegRun, scratch: Path
) -> None:
    world.plant("1_alpha:0", "2_bravo:0")
    _, bare = leg(DJB_GATE_LEDGER=str(world.home / "a"))
    empty = scratch / "empty-drawer"
    empty.mkdir()
    _, pointed = leg(DJB_GATE_LEDGER=str(world.home / "b"), DJB_LOCAL_DRIVES_DIR=str(empty))
    assert seconds_out(bare) == seconds_out(pointed), "a drawer outside the tree moved the leg"
    assert "local:" not in bare
    assert not any((ROOT / d).exists() for d in R.DRAWERS)


# --- the whole run --------------------------------------------------------------------


def test_the_whole_run_drive_is_a_registered_drive() -> None:
    assert st.WHOLE_RUN_DRIVE in R.DRIVE_NAMES, "a sharded whole run would force nothing to run"


def test_a_hand_typed_whole_run_on_an_unsharded_run_is_unset_with_a_line(
    world: World, leg: LegRun
) -> None:
    world.plant("1_alpha:0", body='echo "whole=${DJB_SELFTEST_SHAPES_WHOLE_RUN:-<unset>}"\n')
    _, out = leg(DJB_SELFTEST_SHAPES_WHOLE_RUN="1", DJB_SELFTEST_NO_REUSE="1")
    assert "whole=<unset>" in out, "unsharded: the hand-typed value was honoured"
    assert re.search(r"UNSET.*runs narrowed", out), "no line says the value was unset"
    _, out = leg(
        GATE_LEG_UNIT="selftest", GATE_SHARD_K="1", GATE_SHARD_N="1", DJB_SELFTEST_NO_REUSE="1"
    )
    assert "whole=the selftest unit is sharded (--leg selftest --shard 1/1)" in out, out


def test_a_planted_plan_runs_exactly_its_modules_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI-THIRD-2 2.3: the plan's two modules, whole — no `-m not full_gate` — and no other."""
    from quality.djb import scope
    from quality.djb.legs import gate_tests

    held = ["quality/tests/test_ledger.py", "quality/tests/test_scope.py"]
    plan = tmp_path / "plan.txt"
    plan.write_text(f"selftest-plan/1 gate-tests={','.join(held)} engine=whole\n")
    monkeypatch.setenv(scope.PLAN_ENV, str(plan))
    monkeypatch.delenv("DJB_MEMBER_WALLS_OUT", raising=False)
    calls: list[list[str]] = []

    def tool(ctx: R.Ctx, argv: Sequence[str]) -> int:
        assert scope.PLAN_ENV not in ctx.env, f"{argv[0]} was handed the consumed plan"
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(gate_tests, "tool", tool)
    ctx = R.Ctx(ROOT, "full", {k: v for k, v in os.environ.items() if not k.startswith("GATE_")})
    assert gate_tests.run(ctx) == 0
    mypy, tests = calls
    assert "mypy" in mypy
    assert [a for a in tests if a.startswith("quality/tests")] == held, tests
    assert "not full_gate" not in tests
    assert gate_tests.modules(ROOT) == held
    assert len(gate_tests.modules(ROOT, narrowed=False)) > len(held)


NESTED_WORLD = """
from quality.djb import registry as R
from quality.djb.legs import selftest as st
from quality.tests.test_selftest_compose import ROOT, World


def test_the_world(tmp_path, capfd):
    world = World(tmp_path / "world")
    world.plant("1_alpha:0")
    rc = st.run(R.Ctx(ROOT, "full", world.env), None)
    out = "".join(capfd.readouterr())
    assert rc == 0, out
    assert "selftest plan:" not in out, out
"""


def test_a_plan_exported_in_the_shell_never_narrows_the_worlds_engine(
    nested_pytest: Callable[..., tuple[int, str]], scratch: Path
) -> None:
    """CI-NARROW-ENV-1: the harness strips the plan, so a world's leg runs the engine whole."""
    from quality.djb import scope

    plan = scratch / "plan.txt"
    plan.write_text("selftest-plan/1 gate-tests=whole engine=84,89,90\n")
    rc, out = nested_pytest({"test_world.py": NESTED_WORLD}, env={scope.PLAN_ENV: str(plan)})
    assert rc == 0, out


def test_the_plan_is_the_legs_and_never_its_members(
    world: World, leg: LegRun, scratch: Path
) -> None:
    """CI-NARROW-ENV-1: the leg reads the plan; the members it starts are handed none."""
    from quality.djb import scope

    plan = scratch / "plan.txt"
    plan.write_text("selftest-plan/1 gate-tests=whole engine=whole\n")
    world.plant("1_alpha:0", body=f'echo "plan=${{{scope.PLAN_ENV}:-<unset>}}"\n')
    rc, out = leg(**{scope.PLAN_ENV: str(plan), "DJB_SELFTEST_NO_REUSE": "1"})
    assert rc == 0, out
    assert "selftest plan: selftest-plan/1" in out, "the leg did not read its plan"
    assert "plan=<unset>" in out, "a member inherited the plan the leg had consumed"


@pytest.mark.parametrize("rules", [("8", "13"), ()], ids=["two-rules", "none-re-keyed"])
def test_a_narrowed_engine_runs_its_rules_and_the_whole_parts_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rules: tuple[str, ...]
) -> None:
    """2.3: the re-keyed rules' forms and the whole parts; none re-keyed, one rule carries them."""
    from quality.djb import scope
    from quality.djb.legs import selftest

    plan = tmp_path / "plan.txt"
    plan.write_text(f"selftest-plan/1 gate-tests=whole engine={','.join(rules)}\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GATE_")}
    ctx = R.Ctx(ROOT, "full", {**env, scope.PLAN_ENV: str(plan)})
    ran: list[list[str]] = []

    def member(c: R.Ctx, n: str, argv: Sequence[str], e: object) -> tuple[int, str]:
        ran.append(list(argv))
        return 0, ""

    monkeypatch.setattr(selftest, "run_member", member)
    tally = selftest.Tally()
    selftest.engine_members(ctx, tally, 1, [1], "1/1")
    (argv,) = ran
    assert argv[: len(selftest.ENGINE[0])] == list(selftest.ENGINE[0])
    assert "--member" in argv and "--whole" in argv
    named = [argv[i + 1] for i, a in enumerate(argv) if a == "--rule"]
    assert named == list(rules) if rules else len(named) == 1, named
