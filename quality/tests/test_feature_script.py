"""`./scripts/feature.sh`: the road's block, its `next:`, and the first red line with its file."""

# does-not-cover: the gate's own verdicts — the steps are stubbed with the gate's printed shapes.

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import pytest

from quality.djb.rituals import feature

pytestmark = pytest.mark.drives(
    "quality/djb/rituals/feature.py",
    "scripts/feature.sh",
    "scripts/setup.sh",
    "scripts/rung_start.sh",
)

ROOT = Path(__file__).resolve().parents[2]
RUFF_RED = """\
- ruff (lint + format check)
F401 [*] `os` imported but unused
 --> apps/zzzk9s/services.py:3:8
  |
3 | import os
"""
LOOP_RED = """\
- house rules
  x rule 91: apps/zzzk9s/apps.py:0: rule 91 ratchet: class zzzk9s.block-tail is at 37
- every red leg: house-rules exit 1 · fe exit 1
"""


def _app(tmp_path: Path) -> Path:
    (tmp_path / "apps/zzzk9s").mkdir(parents=True)
    (tmp_path / "apps/zzzk9s/apps.py").write_text("")
    return tmp_path


def _runner(answers: dict[str, tuple[int, str]], ran: list[str]) -> feature.Runner:
    def run(root: Path, step: feature.Step, tag: str) -> feature.Ran:
        ran.append(step.name)
        code, text = answers.get(step.name, (0, "ok\n"))
        return feature.Ran(code, 1, root / f"{tag}-{step.name}.log", text)

    return run


def test_a_green_road_prints_its_block_and_names_the_loop_next(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []
    assert feature.main(["zzzk9s"], _app(tmp_path), _runner({}, ran)) == 0
    lines = capsys.readouterr().out.splitlines()
    assert ran == ["makemigrations", "tidy", "gate", "migrate", "tests"]
    assert lines[0] == "== feature zzzk9s"
    assert lines[3] == "- ./scripts/rung_tidy.sh --client --budgets"
    assert lines[5] == "- ./scripts/check.sh --fast"
    assert lines[7] == "- manage.py migrate --noinput"
    assert lines[9] == "- ./scripts/test.sh apps/zzzk9s"
    assert lines[-2].startswith("green: this checkout's database is migrated and apps/zzzk9s's")
    assert lines[-1] == 'next: ./scripts/feature.sh zzzk9s --loop --here "zzzk9s: <why>"'


UNAPPLIED = (
    "Traceback (most recent call last):\n"
    'django.db.utils.ProgrammingError: relation "zzzk9s_packet" does not exist\n'
)
APP_TEST_RED = """\
E       AssertionError: Extra items in the left set: 'packet_id'
FAILED apps/zzzk9s/tests/test_doors.py::test_the_two_doors_agree - AssertionError
========================= 2 failed, 232 passed in 19.45s =========================
"""


def test_green_waits_for_this_checkouts_database_to_migrate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DRIVE-3 journal 17: the worker met an unmigrated table after a green road."""
    ran: list[str] = []
    runner = _runner({"migrate": (1, UNAPPLIED)}, ran)
    assert feature.main(["zzzk9s"], _app(tmp_path), runner) == 1
    lines = capsys.readouterr().out.splitlines()
    assert ran == ["makemigrations", "tidy", "gate", "migrate"]
    assert lines[-2] == (
        'red: migrate — django.db.utils.ProgrammingError: relation "zzzk9s_packet" does not exist'
    )
    assert not any(line.startswith("green:") for line in lines)


def test_green_waits_for_the_apps_own_tests(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """DRIVE-3 journal 9: `--fast` runs no app test, so a red parity test followed green."""
    ran: list[str] = []
    runner = _runner({"tests": (1, APP_TEST_RED)}, ran)
    assert feature.main(["zzzk9s"], _app(tmp_path), runner) == 1
    lines = capsys.readouterr().out.splitlines()
    assert ran == ["makemigrations", "tidy", "gate", "migrate", "tests"]
    assert lines[-2].startswith("red: ") and "test_the_two_doors_agree" in lines[-2], lines
    assert lines[-1] == "next: fix it there, then ./scripts/feature.sh zzzk9s"


@pytest.mark.parametrize("loop", [False, True])
def test_the_printed_next_is_the_laptop_form_and_parses_as_a_loop(loop: bool) -> None:
    """The green road's `next:` is runnable on a laptop: a `--loop` carrying its `--here` reason."""
    said = feature.finish("zzzk9s", loop, "").removeprefix("next: ./scripts/feature.sh ")
    argv = shlex.split(said.partition(",")[0])
    assert feature.parse(argv) == ("zzzk9s", True, "<Noun>" if loop else "", "zzzk9s: <why>")


def test_a_ruff_red_stops_the_road_its_file_and_line_first(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []
    runner = _runner({"gate": (1, RUFF_RED)}, ran)
    assert feature.main(["zzzk9s", "--drive", "Gear"], _app(tmp_path), runner) == 1
    lines = capsys.readouterr().out.splitlines()
    assert ran == ["preflight", "makemigrations", "tidy", "gate"]
    assert lines[-2] == "red: apps/zzzk9s/services.py:3:8 — F401 [*] `os` imported but unused"
    assert lines[-1] == "next: fix it there, then ./scripts/feature.sh zzzk9s --drive Gear"


def test_the_loop_names_every_red_and_the_first_one_located(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner({"gate": (1, LOOP_RED)}, [])
    assert feature.main(["zzzk9s", "--loop"], _app(tmp_path), runner) == 1
    said = capsys.readouterr().out
    assert "  - every red leg: house-rules exit 1 · fe exit 1" in said
    assert (
        "red: apps/zzzk9s/apps.py:0 — x rule 91 rule 91 ratchet: class zzzk9s.block-tail is at 37"
        in said
    )


def test_a_census_violation_line_is_the_red_located() -> None:
    log = (
        "  0 pointer site(s) and 1 path site(s) in the changed set\n"
        "  VIOLATION  dangling-paths: scripts/zzz_gone.json does not exist in the tree"
        " — spelled in pyproject.toml:156\n"
    )
    assert feature.first_red(log) == (
        "pyproject.toml:156 — VIOLATION  dangling-paths: scripts/zzz_gone.json does not exist"
        " in the tree — spelled in"
    )


def test_a_green_loop_with_a_drive_names_the_pr_road(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []
    runner = _runner({}, ran)
    assert feature.main(["zzzk9s", "--loop", "--drive", "Gear"], _app(tmp_path), runner) == 0
    assert ran[-1] == "doors"
    assert capsys.readouterr().out.splitlines()[-1].startswith("next: ./scripts/pm_push.sh --pr")


@pytest.mark.parametrize(
    ("noun", "order"),
    [
        ("Gear", ["preflight", "makemigrations", "tidy", "gate", "migrate", "tests", "doors"]),
        ("", ["makemigrations", "tidy", "gate", "migrate", "tests"]),
    ],
)
def test_the_drive_migrates_the_checkout_right_before_the_doors(
    tmp_path: Path, noun: str, order: list[str]
) -> None:
    road = feature.steps(tmp_path, "zzzk9s", False, noun)
    assert [step.name for step in road] == order
    migrate = next(step for step in road if step.name == "migrate")
    assert migrate.argv[1:] == ("manage.py", "migrate", "--noinput")
    assert [s.name for s in feature.steps(tmp_path, "zzzk9s", True, noun)][-1] == (
        "doors" if noun else "migrate"
    )


def test_a_migrate_that_fails_names_itself_and_its_error_before_any_drive(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ran: list[str] = []
    raised = (
        "Traceback (most recent call last):\n"
        '  File "manage.py", line 22, in <module>\n'
        'django.db.utils.OperationalError: connection to server at "localhost" failed\n'
    )
    runner = _runner({"migrate": (1, raised)}, ran)
    assert feature.main(["zzzk9s", "--drive", "Gear"], _app(tmp_path), runner) == 1
    lines = capsys.readouterr().out.splitlines()
    assert ran == ["preflight", "makemigrations", "tidy", "gate", "migrate"]
    assert lines[-2] == (
        'red: migrate — django.db.utils.OperationalError: connection to server at "localhost" '
        "failed"
    )


def test_a_missing_database_outranks_the_pool_timeout_wrapped_around_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    said = (
        "WARNING error connecting in 'pool-1': connection failed: connection to server at "
        '"127.0.0.1", port 5432 failed: FATAL:  database "djb_pm_f1_bookings_d7819f18" '
        "does not exist\n"
        "Traceback (most recent call last):\n"
        "django.db.utils.OperationalError: couldn't get a connection after 10.00 sec\n"
    )
    runner = _runner({"migrate": (1, said)}, [])
    assert feature.main(["zzzk9s", "--drive", "Gear"], _app(tmp_path), runner) == 1
    assert capsys.readouterr().out.splitlines()[-2] == (
        "red: migrate — the database djb_pm_f1_bookings_d7819f18 does not exist; "
        "this checkout's .env pin or scripts/db.sh's derivation named it "
        "(./scripts/setup.sh creates it)"
    )


def test_a_step_that_could_not_look_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner({"tidy": (2, "!! rung_tidy refuses pipes\n")}, [])
    assert feature.main(["zzzk9s"], _app(tmp_path), runner) == 2
    assert "could not look: !! rung_tidy refuses pipes" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("stuck", "what", "remedy"),
    [
        (
            "nothing serves at http://127.0.0.1:21643 (ConnectError) — the server is not running "
            "— next: ./scripts/serve.sh and ./scripts/worker.sh in another shell",
            "nothing serves at http://127.0.0.1:21643 (ConnectError) — the server is not running",
            "./scripts/serve.sh and ./scripts/worker.sh in another shell",
        ),
        (
            "no seed rows (no tenant `acme` or no person `owner@example.com`) "
            "— next: uv run python manage.py seed",
            "no seed rows (no tenant `acme` or no person `owner@example.com`)",
            "uv run python manage.py seed",
        ),
    ],
)
def test_a_drive_that_could_not_look_names_its_own_remedy_in_one_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], stuck: str, what: str, remedy: str
) -> None:
    said = f"== drive_doors Gear · http://127.0.0.1:21643 · tenant acme\ncould not drive: {stuck}\n"
    runner = _runner({"doors": (2, said)}, [])
    assert feature.main(["zzzk9s", "--drive", "Gear"], _app(tmp_path), runner) == 2
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2] == f"could not look: {what}"
    assert lines[-1] == f"next: {remedy}, then ./scripts/feature.sh zzzk9s --drive Gear"


def test_a_green_drive_says_its_verdict_on_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner(
        {"doors": (0, "== drive_doors Gear\n…\ndoors agree: Gear over REST and MCP\n")}, []
    )
    assert feature.main(["zzzk9s", "--drive", "Gear"], _app(tmp_path), runner) == 0
    assert "  doors agree: Gear over REST and MCP" in capsys.readouterr().out.splitlines()


@pytest.mark.parametrize("argv", [[], ["Gears"], ["zzzk9s", "--drive"], ["nothere"]])
def test_a_wrong_ask_is_refused_before_any_step(tmp_path: Path, argv: list[str]) -> None:
    ran: list[str] = []
    assert feature.main(argv, _app(tmp_path), _runner({}, ran)) == 2
    assert ran == []


def test_the_shim_runs_the_module(tmp_path: Path) -> None:
    log = tmp_path / "help.log"
    with log.open("w") as sink:
        done = subprocess.run(
            ["./scripts/feature.sh", "--help"], cwd=ROOT, stdout=sink, stderr=subprocess.STDOUT
        )
    assert done.returncode == 0, log.read_text()
    assert log.read_text().startswith("usage: feature.sh <app>")


@pytest.mark.parametrize(
    ("script", "foot"),
    [
        ("scripts/setup.sh", "next: uv run python manage.py scaffold --list"),
        ("scripts/rung_start.sh", "next: uv run python manage.py roads shape <shape>"),
    ],
)
def test_the_day_begins_with_a_next_line(script: str, foot: str) -> None:
    assert foot in (ROOT / script).read_text(), f"{script} prints no `{foot}`"
    assert os.access(ROOT / script, os.X_OK)


def test_the_loop_valve_flag_reaches_the_gate_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    said = "zzzk9s: the laptop loop"
    road = feature.steps(tmp_path, "zzzk9s", True, "", said)
    assert road[2].argv == ("./scripts/check.sh", "--loop", "--here", said)
    seen: list[feature.Step] = []

    def runner(root: Path, step: feature.Step, tag: str) -> feature.Ran:
        seen.append(step)
        return feature.Ran(1 if step.name == "gate" else 0, 1, root / "x.log", LOOP_RED)

    assert feature.main(["zzzk9s", "--loop", "--here", said], _app(tmp_path), runner) == 1
    assert seen[-1].argv == ("./scripts/check.sh", "--loop", "--here", said)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "== feature zzzk9s --loop --here 'zzzk9s: the laptop loop'"
    assert lines[-1] == (
        "next: fix it there, then ./scripts/feature.sh zzzk9s --loop --here "
        "'zzzk9s: the laptop loop'"
    )


def test_the_valve_flag_without_the_loop_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _app(tmp_path)
    assert feature.main(["zzzk9s", "--here", "zzzk9s: why"], root, _runner({}, [])) == 2
    assert "!! --here says why a --loop runs on this machine" in capsys.readouterr().err
    assert feature.main(["zzzk9s", "--loop", "--here"], root, _runner({}, [])) == 2


SERVED_ELSEWHERE = (
    "could not drive: the server on :21643 serves djb_pm_old_1a2b3c4d; this checkout derives "
    "djb_pm_new_5e6f7a8b — next: ./scripts/kill_mine.sh --kill, then ./scripts/serve.sh"
)


def test_preflight_is_the_first_step(tmp_path: Path) -> None:
    road = feature.steps(tmp_path, "zzzk9s", False, "Gear")
    assert [step.name for step in road][0] == "preflight"
    assert road[0].argv == ("./scripts/drive_doors.sh", "Gear", "--preflight")
    assert "preflight" not in [step.name for step in feature.steps(tmp_path, "zzzk9s", False, "")]


def test_a_dead_stack_costs_no_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ran: list[str] = []
    said = f"== drive_doors Gear --preflight · http://127.0.0.1:21643\n{SERVED_ELSEWHERE}\n"
    runner = _runner({"preflight": (2, said)}, ran)
    assert feature.main(["zzzk9s", "--drive", "Gear"], _app(tmp_path), runner) == 2
    assert ran == ["preflight"]
    lines = capsys.readouterr().out.splitlines()
    assert lines[-2] == (
        "could not look: the server on :21643 serves djb_pm_old_1a2b3c4d; this checkout derives "
        "djb_pm_new_5e6f7a8b"
    )
    assert lines[-1] == (
        "next: ./scripts/kill_mine.sh --kill, then ./scripts/serve.sh, then "
        "./scripts/feature.sh zzzk9s --drive Gear"
    )


@pytest.mark.parametrize("code", [1, 2])
def test_a_drive_refusal_is_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], code: int
) -> None:
    said = (
        "== drive_doors Gear · http://127.0.0.1:21643 · tenant acme\n"
        "could not drive: POST /api/v1/gears/ answered 401: That bearer token is not valid\n"
        "-- revoked `drive-doors-20261020T162600Z`, this drive's token\n"
    )
    runner = _runner({"doors": (code, said)}, [])
    assert feature.main(["zzzk9s", "--drive", "Gear"], _app(tmp_path), runner) == 2
    lines = capsys.readouterr().out.splitlines()
    assert not any("no red line located" in line for line in lines)
    assert lines[-2] == (
        "could not look: POST /api/v1/gears/ answered 401: That bearer token is not valid"
    )
    assert lines[-1] == "next: fix it there, then ./scripts/feature.sh zzzk9s --drive Gear"


def _lower(rule: int, klass: str, held: int, now: int) -> str:
    """One rule-91-form headroom line as the house-rules leg prints it."""
    return (
        f"  x rule {rule}: apps/zzzk9s/apps.py:0: rule {rule} ratchet: class 'zzzk9s.{klass}' is"
        f" recorded at {held} and this tree holds {now} — headroom in an app this change"
        f" touches. Lower it to {now} in apps/zzzk9s/apps.py\n"
    )


THREE_LOWERS = (
    "- house rules\n"
    + _lower(91, "block-tail", 37, 30)
    + _lower(91, "inline", 9, 4)
    + _lower(84, "private_twin", 3, 2)
    + "- every red leg: house-rules exit 1\n"
)


def test_every_lower_it_line_is_summarised(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    runner = _runner({"gate": (1, THREE_LOWERS)}, [])
    assert feature.main(["zzzk9s"], _app(tmp_path), runner) == 1
    reds = [line for line in capsys.readouterr().out.splitlines() if line.startswith("red: ")]
    assert [red.split("Lower it to ")[1] for red in reds] == [
        "30 in apps/zzzk9s/apps.py",
        "4 in apps/zzzk9s/apps.py",
        "2 in apps/zzzk9s/apps.py",
    ]
    assert all(red.startswith("red: apps/zzzk9s/apps.py:0 — ") for red in reds)
