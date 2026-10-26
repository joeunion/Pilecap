"""`scripts/backup.sh` and `scripts/restore_drill.sh` driven by a caller: each exit and its words.

does-not-cover: `--to-s3` — no S3 here; `--to-dir` is the same mechanism with the last line changed.
does-not-cover: a real `--stack` dump and its `.origin` — the sidecar is written to its shape.
does-not-cover: a completed restore — the death cases stop the drill before `RESTORE DRILL PASSED`.
does-not-cover: `--into-project`'s death — both death cases run in scratch mode.
does-not-cover: whether a refusal is the RIGHT refusal — only its exit and its words.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured, run_to

pytestmark = pytest.mark.drives(
    "apps/*/apps.py",
    "apps/*/migrations/",
    "config/",
    "deploy/compose.yaml",
    "docs/product/instruments.md",
    "manage.py",
    "scripts/backup.sh",
    "scripts/db.sh",
    "scripts/kill_mine.sh",
    "scripts/queue_cited.sh",
    "scripts/restore_drill.sh",
    "scripts/sweep.sh",
)

ROOT = Path(__file__).resolve().parents[2]


def db(*command: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """One `scripts/db.sh` function, sourced in a bash of its own."""
    return subprocess.run(
        ["bash", "-c", 'source scripts/db.sh >/dev/null 2>&1 && "$@"', "db", *command],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )


def checkout_database() -> str:
    """This checkout's database, which must exist; migrated once, under a lock, if created bare."""
    if shutil.which("docker") is None:
        raise CouldNotLook("no docker on PATH; backup.sh dumps inside the compose container")
    for script in ("backup.sh", "restore_drill.sh"):
        if not os.access(ROOT / "scripts" / script, os.X_OK):
            raise CouldNotLook(f"scripts/{script} is not executable")
    name = db("printenv", "DATABASE_NAME").stdout.strip()
    if not name or db("db_exists", name).returncode != 0:
        raise CouldNotLook(
            f"this checkout's database {name!r} does not exist; run ./scripts/setup.sh"
        )
    lock = Path(tempfile.gettempdir()) / f"djb-migrate-{name}.lock"
    with lock.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        tables = db(
            "db_query",
            "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'",
            "-d",
            name,
            "-tA",
        ).stdout.strip()
        if tables in ("", "0"):
            migrated = subprocess.run(
                ["uv", "run", "python", "manage.py", "migrate", "--no-input"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env={**os.environ, "DATABASE_NAME": name},
            )
            if migrated.returncode != 0:
                said = "\n".join(migrated.stderr.splitlines()[-12:])
                raise CouldNotLook(
                    f"could not migrate {name}; the --to-dir case needs tables"
                    f" — migrate said:\n{said}"
                )
    return name


@pytest.fixture(scope="module")
def database() -> str:
    """This checkout's database name, proven to exist with tables in it."""
    return checkout_database()


@pytest.fixture(scope="module")
def dumped(database: str, tmp_path_factory: pytest.TempPathFactory) -> tuple[Captured, Path, Path]:
    """One `backup.sh --to-dir` run: the capture, dump and copy; the killed drill restores it."""
    work = tmp_path_factory.mktemp("backup")
    out, off = work / "laptop.dump", work / "off"
    ran = run_to(work / "to-dir.out", ["./scripts/backup.sh", "--to-dir", str(off), str(out)], ROOT)
    return ran, out, off / out.name


@pytest.fixture
def victim(database: str) -> Iterator[Callable[[str], str]]:
    """`victim(suffix)`: a DATABASE_NAME whose `_drill` is this test's alone; dropped after."""
    made: list[str] = []

    def name(suffix: str) -> str:
        made.append(f"{database}_f6{suffix}_drill")
        return f"{database}_f6{suffix}"

    yield name
    for drill in made:
        if db("db_exists", drill).returncode == 0:
            db("db_drop", drill)


def test_backup_unknown_flag(capture: Callable[..., Captured]) -> None:
    ran = capture(["./scripts/backup.sh", "--no-such-flag"])
    assert ran.rc == 2, ran.text()
    assert "unknown flag --no-such-flag" in ran.text()


def test_backup_flag_without_value(capture: Callable[..., Captured]) -> None:
    ran = capture(["./scripts/backup.sh", "--to-dir"])
    assert ran.rc == 2, ran.text()
    assert "needs a value" in ran.text()


def test_backup_two_outputs(capture: Callable[..., Captured], scratch: Path) -> None:
    ran = capture(["./scripts/backup.sh", str(scratch / "a.dump"), str(scratch / "b.dump")])
    assert ran.rc == 2, ran.text()
    assert "two output paths given" in ran.text()


def test_backup_absent_database(capture: Callable[..., Captured], scratch: Path) -> None:
    ran = capture(
        ["./scripts/backup.sh", "--to-dir", str(scratch / "off")],
        env={"DATABASE_NAME": "djb_test_no_such_world_deadbeef"},
    )
    assert ran.rc == 2, ran.text()
    assert "does not exist, so there is nothing to back up" in ran.text()


def test_backup_stack_without_env_file(capture: Callable[..., Captured], scratch: Path) -> None:
    ran = capture(
        ["./scripts/backup.sh", "--stack", "djb-nosuch", "--env-file", str(scratch / "absent.env")]
    )
    assert ran.rc == 2, ran.text()
    assert "--stack needs the deployment's own env" in ran.text()


def test_backup_to_dir_produces_an_object(dumped: tuple[Captured, Path, Path]) -> None:
    ran, out, copy = dumped
    assert ran.rc == 0, ran.text()
    for path in (out, copy):
        assert path.is_file(), f"no object at {path}"
        assert path.stat().st_size >= 1024, f"{path} is {path.stat().st_size} bytes"


def test_restore_unknown_flag(capture: Callable[..., Captured]) -> None:
    ran = capture(["./scripts/restore_drill.sh", "--no-such-flag"])
    assert ran.rc == 2, ran.text()
    assert "unknown flag --no-such-flag" in ran.text()


def test_restore_no_origin_at_a_live_stack(capture: Callable[..., Captured], scratch: Path) -> None:
    dump = scratch / "orphan.dump"
    dump.write_text("not really a dump, and this case never gets far enough to read it\n")
    ran = capture(["./scripts/restore_drill.sh", "--into-project", "djb-nosuch", str(dump)])
    assert ran.rc == 2, ran.text()
    assert "refusing to restore into a LIVE stack from a dump with no origin" in ran.text()


def test_restore_origin_without_a_project_line(
    capture: Callable[..., Captured], scratch: Path
) -> None:
    dump = scratch / "blank-origin.dump"
    dump.write_text("not really a dump\n")
    Path(f"{dump}.origin").write_text(
        "# a sidecar that forgot the one line that matters\ndatabase=djb_x\n"
    )
    ran = capture(["./scripts/restore_drill.sh", "--into-project", "djb-nosuch", str(dump)])
    assert ran.rc == 2, ran.text()
    assert "the origin is unreadable" in ran.text()


def test_restore_target_is_the_source(capture: Callable[..., Captured], scratch: Path) -> None:
    dump = scratch / "same.dump"
    dump.write_text("not really a dump\n")
    Path(f"{dump}.origin").write_text(
        f"project=djb-same\ndatabase=djb_same\nenv_file={scratch / 'same.env'}\n"
        "taken_at=19700101T000000Z\n"
    )
    ran = capture(["./scripts/restore_drill.sh", "--into-project", "djb-same", str(dump)])
    assert ran.rc == 2, ran.text()
    assert "the restore target is the source" in ran.text()


def test_restore_target_differs_and_the_check_moves_on(
    capture: Callable[..., Captured], scratch: Path
) -> None:
    dump = scratch / "other.dump"
    dump.write_text("not really a dump\n")
    Path(f"{dump}.origin").write_text("project=djb-source\ndatabase=djb_source\n")
    ran = capture(
        [
            "./scripts/restore_drill.sh",
            "--into-project",
            "djb-target",
            "--env-file",
            str(scratch / "absent.env"),
            str(dump),
        ]
    )
    assert ran.rc == 2, ran.text()
    assert "--into-project needs the target stack's own env" in ran.text()


def test_restore_a_broken_dump_dies_and_says_so(
    capture: Callable[..., Captured], scratch: Path, victim: Callable[[str], str]
) -> None:
    name = victim("a")
    dump = scratch / "broken.dump"
    dump.write_text("not a dump at all\n")
    ran = capture(["./scripts/restore_drill.sh", str(dump)], env={"DATABASE_NAME": name})
    assert ran.rc == 1, ran.text()
    assert "RESTORE DRILL DID NOT FINISH (exit 1)" in ran.text()
    assert db("db_exists", f"{name}_drill").returncode != 0, f"{name}_drill was left behind"


def test_restore_killed_mid_drill_says_so_and_drops_the_scratch(
    dumped: tuple[Captured, Path, Path], scratch: Path, victim: Callable[[str], str]
) -> None:
    _, dump, _ = dumped
    if not dump.is_file():
        raise CouldNotLook(f"no real dump at {dump}; the --to-dir fixture owes it")
    name = victim("b")
    log = scratch / "killed.log"
    with log.open("wb") as sink:
        drill = subprocess.Popen(
            ["./scripts/restore_drill.sh", str(dump)],
            cwd=ROOT,
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env={**os.environ, "DATABASE_NAME": name},
        )
        for _ in range(120):
            if db("db_exists", f"{name}_drill").returncode == 0 or drill.poll() is not None:
                break
            time.sleep(0.25)
        if drill.poll() is None:
            drill.send_signal(signal.SIGTERM)
        rc = drill.wait()
    text = log.read_text(errors="replace")
    assert "RESTORE DRILL PASSED" not in text, "the drill passed before the signal landed"
    assert rc == 143, (rc, text)
    assert "RESTORE DRILL DID NOT FINISH (exit 143)" in text, text
    assert db("db_exists", f"{name}_drill").returncode != 0, f"{name}_drill was left behind"
