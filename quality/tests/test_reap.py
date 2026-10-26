"""The sweep, its frame and the reaper driven by a caller over machinery this module plants.

does-not-cover: a machine-wide sweep — every destroy is narrowed to an identity derived here.
does-not-cover: a live `DescribeTaskQueue` poller — no worker is started on the shared server.
does-not-cover: the poller world of the exemption and the remedy, unless a worker already polls.
does-not-cover: `test-server-process` — planting one would orphan a real test server.
does-not-cover: whether a refusal is the RIGHT refusal — only its exit and its words.
does-not-cover: a defect two checkouts meet only outside the chain the concurrency case runs.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured, run_to

pytestmark = pytest.mark.drives(
    "**.sh",  # the shell-change floor: any shell file changed selects this module
    ".github/workflows/ci.yml",
    "scripts/check.sh",
    "scripts/db.sh",
    "scripts/db_sweep.sh",
    "scripts/kill_mine.sh",
    "scripts/lifecycle.sh",
    "scripts/lifecycle_temporal.py",
    "scripts/queue_cited.sh",
    "scripts/setup.sh",
    "scripts/sweep.sh",
    "scripts/temporal_sweep.sh",
)

ROOT = Path(__file__).resolve().parents[2]
SWEEP = "./scripts/sweep.sh"
DB_SWEEP = "./scripts/db_sweep.sh"
TEMPORAL_PY = "scripts/lifecycle_temporal.py"
NEVER = "NOTHING THIS RUN COULD EVER HAVE PRINTED"
CHAIN = (
    "the_dead_queue_sibling_is_required_empty_before_anything_is_planted",
    "new_classes_are_censused_as_foreign",
    "sweep_alone_leaves_foreign_alone",
    "force_foreign_prints_then_acts",
    "the_scratch_machinery_is_actually_gone",
)
CLASSES = (
    "migration-template checkout-database test-database hot-path-cache perf-world"
    " grants-pass-database restore-drill-database identity-home-drive-database task-queue"
    " schedule open-execution test-server-process"
)
GOOD_CLASS = """#!/usr/bin/env bash
# A product's own machinery class. Declaration only.
lc_class "lc2-local-world" "database" \\
    "the derived base + _lc2acme (a product's seeded world)" \\
    "pg_catalog: datname LIKE djb\\\\_%\\\\_lc2acme" \\
    "pg_stat_activity sessions on it" \\
    "scripts/db_sweep.sh --sweep --name <n>" \\
    "no" \\
    "yes: the product's own seeder rebuilds it" \\
    "glob:djb_*_lc2acme"
"""
REMEDY_PLACEHOLDER = "<an id above>"
INJ = 'lc_class "lc2-inj" "database"'
BACKEND = "SELECT pg_backend_pid()"
SOURCED = "set -o pipefail; source scripts/lifecycle.sh >/dev/null 2>&1 || exit 2; "
READER = "awk -F'\\t' -v want=\"$1\" '${field} == want {{ found = 1 }} END {{ exit !found }}'"


def dot_env_keys() -> tuple[str, ...]:
    """The names `.env` declares: the settings import loaded them, and no shell caller has them."""
    path = ROOT / ".env"
    if not path.is_file():
        return ()
    names = (line.split("=", 1)[0].strip() for line in path.read_text().splitlines())
    return tuple(n for n in names if n and not n.startswith("#")) + ("DATABASE_NAME_SOURCE",)


def frame(program: str, *args: str, live: bool = False, env: dict[str, str] | None = None) -> str:
    """`program` in a bash that sourced the frame (and loaded the live bases); its stdout."""
    load = "lc_load_live_bases; " if live else ""
    done = subprocess.run(
        [
            "bash",
            "-c",
            f"{SOURCED}{load}{program}",
            "reap",
            *args,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    return done.stdout.strip()


def frame_ok(program: str, *args: str) -> bool:
    """Whether `program` over the sourced frame exits 0."""
    done = subprocess.run(
        [
            "bash",
            "-c",
            f"{SOURCED}lc_load_live_bases; {program}",
            "reap",
            *args,
        ],
        cwd=ROOT,
        capture_output=True,
    )
    return done.returncode == 0


def query(sql: str, **variables: str) -> str:
    """One `db_query` with `-v name=value` per keyword, its `-tA` answer."""
    flags = " ".join(f'-v {k}="${i + 2}"' for i, k in enumerate(variables))
    return frame(f'db_query "$1" -tA {flags}', sql, *variables.values())


def create(name: str) -> None:
    """`CREATE DATABASE` the named victim; a failure is the caller's to read."""
    query('CREATE DATABASE :"name"', name=name)


def drop(name: str) -> None:
    """`DROP DATABASE IF EXISTS` the named victim."""
    query('DROP DATABASE IF EXISTS :"name"', name=name)


def present(name: str) -> bool:
    """Whether the server holds a database of exactly this name."""
    return query("SELECT count(*) FROM pg_database WHERE datname = :'name'", name=name) == "1"


def temporal(*args: str) -> None:
    """One `lc_temporal` call against the compose Temporal, its answer discarded."""
    frame('lc_temporal "$@"', *args)


def schedule_present(schedule: str) -> bool:
    """The schedule probe: one reader, no early exit, field one."""
    return frame_ok(
        f"lc_scan_schedules | {READER.format(field=1)}",
        schedule,
    )


def execution_present(workflow: str) -> bool:
    """The open-execution probe: one reader, no early exit, field two."""
    return frame_ok(
        f"lc_scan_open_executions | {READER.format(field=2)}",
        workflow,
    )


def execution_appears(workflow: str, tries: int = 15) -> bool:
    """`execution_present`, polled once a second up to `tries`: visibility trails a start."""
    for _ in range(tries):
        if execution_present(workflow):
            return True
        time.sleep(1)
    return False


def pollers_on(queue: str) -> int:
    """`lc_queue_pollers` on `queue`, 0 when it answers no number."""
    said = frame('lc_queue_pollers "$1"', queue)
    return int(said) if said.isdigit() else 0


def sessions_on(name: str) -> str:
    """`lc_sessions_on` the named database, as the frame prints it."""
    return frame('lc_sessions_on "$1" || echo 1', name)


@dataclass
class World:
    """The scratch identity this module plants and destroys, derived per checkout and worker."""

    hash: str
    base: str
    our_base: str
    work: Path
    planted_ours: bool = False
    decoys: list[str] = field(default_factory=list)

    @property
    def queue(self) -> str:
        return f"djb-lc2scratch_{self.hash}"

    @property
    def test_db(self) -> str:
        return f"test_{self.base}_gw0"

    @property
    def hp_db(self) -> str:
        return f"{self.base}_hp"

    @property
    def fake_db(self) -> str:
        return f"djb_zzz_{self.hash}_lc2fake"

    @property
    def foreign_db(self) -> str:
        return f"djb_zzz_{self.hash}"

    @property
    def grants_db(self) -> str:
        return f"{self.foreign_db}_grants"

    @property
    def idhome_db(self) -> str:
        return f"{self.foreign_db}_idhome"

    @property
    def local_db(self) -> str:
        return f"{self.base}_lc2acme"

    @property
    def schedule(self) -> str:
        return f"lc2scratch-probe:{self.queue}"

    @property
    def execution(self) -> str:
        return f"lc2scratch:probe:open:{self.hash}"

    @property
    def underived_schedule(self) -> str:
        return f"lc2scratch-probe-{self.hash}:djb-lc2scratchnohash"

    @property
    def strand(self) -> str:
        return f"lc2scratch:probe:strand:{self.hash}"

    @property
    def our_queue(self) -> str:
        return f"djb-{self.our_base.removeprefix('djb_')}"

    def probe(self, kind: str) -> str:
        """An id on this checkout's own queue, attributable to this module on a shared server."""
        return f"lc2probe:{kind}:{self.hash}"

    @property
    def root(self) -> Path:
        """The empty directory every `--force-foreign` names as its scanned evidence."""
        return self.work / "scratch-root"

    @property
    def drawer(self) -> Path:
        return self.work / "lifecycle.d"


def require_no_residue(world: World) -> None:
    """`CouldNotLook` naming the broom when the scratch base already stands (a killed run's)."""
    if present(world.base):
        raise CouldNotLook(
            f"a database named {world.base} already exists and no checkout derives it; this module "
            "will not drop a database it did not plant. The broom is:  "
            f"./scripts/db_sweep.sh --name {world.base}"
        )


def teardown_scratch_temporal(world: World) -> None:
    """The Temporal half of the teardown, reused by the required-empty case to repair residue."""
    temporal("schedule", "delete", "--schedule-id", world.schedule)
    temporal("schedule", "delete", "--schedule-id", world.underived_schedule)
    for workflow in (world.execution, world.strand):
        temporal(
            "workflow", "terminate", "--workflow-id", workflow, "--reason", "test_reap teardown"
        )


@pytest.fixture(scope="module", autouse=True)
def without_dot_env() -> Iterator[None]:
    """Every child here runs with the names `.env` declares unset, as a shell caller does."""
    with pytest.MonkeyPatch.context() as patch:
        for name in dot_env_keys():
            patch.delenv(name, raising=False)
        yield


@pytest.fixture(scope="module")
def world(without_dot_env: None, tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    """The scratch identity; refused when owned, already standing, or the servers are silent."""
    if shutil.which("docker") is None or shutil.which("python3") is None:
        raise CouldNotLook(
            "no docker or no python3 on PATH; both servers live in the compose stack"
        )
    if (
        not os.access(ROOT / "scripts" / "sweep.sh", os.X_OK)
        or not (ROOT / "scripts" / "lifecycle.sh").is_file()
    ):
        raise CouldNotLook("scripts/sweep.sh is not executable or scripts/lifecycle.sh is missing")
    if not (ROOT / ".venv" / "bin" / "python").is_file():
        raise CouldNotLook("this checkout has no .venv/bin/python; run ./scripts/setup.sh first")
    if frame("db_query 'SELECT 1' -tA") != "1":
        raise CouldNotLook(
            "the compose Postgres did not answer; the database classes cannot be censused"
        )
    if not frame_ok(
        "lc_temporal operator cluster health >/dev/null 2>&1"
        " || lc_temporal schedule list -o json >/dev/null 2>&1"
    ):
        raise CouldNotLook(
            "the compose Temporal did not answer; schedules and executions cannot be censused"
        )
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    digest = frame('db_path_hash "$(git rev-parse --show-toplevel)|test_reap_f6$1"', worker)
    if not re.fullmatch(r"[0-9a-f]{8}", digest):
        raise CouldNotLook(
            f"db_path_hash returned {digest!r}, not eight hex digits; every destroy is aimed by it"
        )
    made = World(
        digest, f"djb_lc2scratch_{digest}", frame("db_name"), tmp_path_factory.mktemp("reap")
    )
    if int(frame('printf "%s" "${#LC_LIVE_BASES[@]}"', live=True) or 0) == 0:
        raise CouldNotLook("git worktree list named no checkout, so the frame itself would exit 2")
    if frame_ok('lc_owning_checkout "$1" >/dev/null', made.base):
        raise CouldNotLook(
            f"a checkout this run can see derives {made.base}; no --force-foreign at an owned name"
        )
    require_no_residue(made)
    made.root.mkdir()
    print(f"scratch identity {made.base} (created and torn down by this module)")
    yield made
    for name in (
        made.base,
        made.test_db,
        made.hp_db,
        made.fake_db,
        made.foreign_db,
        made.grants_db,
        made.idhome_db,
        made.local_db,
        *made.decoys,
    ):
        drop(name)
    teardown_scratch_temporal(made)
    for kind in ("live", "stray", "workingset", "remedystrand"):
        temporal(
            "workflow",
            "terminate",
            "--workflow-id",
            made.probe(kind),
            "--reason",
            "test_reap teardown",
        )
    if made.planted_ours:
        drop(made.our_base)


@pytest.fixture
def sweep(scratch: Path) -> Callable[..., Captured]:
    """`sweep(argv, env=…)` runs one command from the checkout root into the next scratch file."""
    count = 0

    def run(argv: list[str], env: dict[str, str] | None = None) -> Captured:
        nonlocal count
        count += 1
        return run_to(scratch / f"run-{count}.out", argv, ROOT, {**os.environ, **(env or {})})

    return run


def plant_databases(world: World) -> None:
    """The scratch base, its test database and its hot-path cache."""
    for name in (world.base, world.test_db, world.hp_db):
        if not present(name):
            create(name)


def require_dead_scratch_queue(world: World) -> None:
    """The dead-queue premise, asked: nothing may poll the scratch sibling in any world."""
    pollers = pollers_on(world.queue)
    assert pollers == 0, f"premise: {world.queue} has {pollers} poller(s) and must have none"


def plant_temporal(world: World) -> None:
    """A paused year-long schedule and one open run, both on the dead scratch queue."""
    require_dead_scratch_queue(world)
    if not schedule_present(world.schedule):
        temporal(
            "schedule",
            "create",
            "--schedule-id",
            world.schedule,
            "--interval",
            "8760h",
            "--paused",
            "--workflow-id",
            f"lc2scratch:probe:noun:{world.hash}",
            "--task-queue",
            world.queue,
            "--type",
            "Lc2ScratchNeverRuns",
        )
    if not execution_present(world.execution):
        temporal(
            "workflow",
            "start",
            "--workflow-id",
            world.execution,
            "--task-queue",
            world.queue,
            "--type",
            "Lc2ScratchNeverRuns",
        )


def plant_our_checkout_database(world: World) -> None:
    """This checkout's derived database, created only when absent and then dropped at teardown."""
    if not present(world.our_base):
        create(world.our_base)
        world.planted_ours = present(world.our_base)


def no_server_bin(work: Path) -> Path:
    """A PATH head whose `docker` and `python3` cannot run: the belt before every server."""
    belt = work / "no-server-bin"
    if not belt.is_dir():
        belt.mkdir()
        for tool in ("docker", "python3"):
            (belt / tool).write_text(
                f'#!/bin/sh\necho "test_reap belt: {tool} is shimmed unreachable" >&2\nexit 127\n'
            )
            (belt / tool).chmod(0o755)
    return belt


def drawer_with(world: World, good: bool = False) -> Path:
    """A drawer holding exactly what the case writes, built fresh."""
    shutil.rmtree(world.drawer, ignore_errors=True)
    world.drawer.mkdir()
    if good:
        (world.drawer / "40-scratch-world.sh").write_text(GOOD_CLASS)
    return world.drawer


def in_drawer(world: World) -> dict[str, str]:
    """The frame pointed at the scratch drawer for one command."""
    return {"DJB_LIFECYCLE_LOCAL_DIR": str(world.drawer)}


def destroy_scratch(world: World, sweep: Callable[..., Captured]) -> Captured:
    """Plant the scratch machinery, then `--force-foreign` it with the empty root as evidence."""
    plant_databases(world)
    plant_temporal(world)
    return sweep(
        [
            SWEEP,
            "--sweep",
            "--force-foreign",
            "--roots",
            str(world.root),
            "--hot-path",
            "--only",
            world.base,
        ]
    )


def stamp_ago(seconds: int) -> str:
    """A stamp `seconds` in the past as Temporal writes one: nine fractional digits and a `Z`."""
    return (datetime.now(UTC) - timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


def parse(mode: str, document: str) -> subprocess.CompletedProcess[str]:
    """`scripts/lifecycle_temporal.py <mode>` over `document`, under the checkout's interpreter."""
    return subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), TEMPORAL_PY, mode],
        cwd=ROOT,
        input=document,
        capture_output=True,
        text=True,
    )


def process_census(
    schedule: int, pollers: str, open_execution: int
) -> tuple[int, str, list[list[str]], list[str]]:
    """`pytest_x2.process_lifetime` over planted sweep exits; its exit, words, argvs and scripts."""
    from quality.djb import registry as R
    from quality.djb.legs import pytest_x2

    argvs: list[list[str]] = []
    scripts: list[str] = []
    answers = {"schedule": schedule, "open-execution": open_execution}

    def captured(ctx: object, argv: list[str], env: object = None) -> tuple[int, str]:
        argvs.append(list(argv))
        return answers[argv[argv.index("--class") + 1]], ""

    def bash(ctx: object, script: str, env: object = None) -> tuple[int, str]:
        scripts.append(script)
        return 0, pollers

    said = io.StringIO()
    with (
        mock.patch.object(pytest_x2, "_captured", captured),
        mock.patch.object(pytest_x2, "_bash", bash),
        contextlib.redirect_stdout(said),
        contextlib.redirect_stderr(said),
    ):
        rc = pytest_x2.process_lifetime(R.Ctx(ROOT, "full", {}), "djb_probe_name")
    return rc, said.getvalue(), argvs, scripts


def gate_strand_remedy() -> str:
    """The first indented command the strand arm of `pytest_x2` prints, never retyped."""
    _, said, _, _ = process_census(0, "0", 1)
    seen = False
    for line in said.splitlines():
        if "THIS TREE STRANDED A RUNNING TEMPORAL EXECUTION" in line:
            seen = True
        elif seen and re.match(r"^ {5}[^ ]", line):
            return line.lstrip(" ")
    return ""


def test_an_empty_capture_is_could_not_look(scratch: Path) -> None:
    empty = scratch / "empty-capture.out"
    empty.write_text("")
    for path in (empty, scratch / "absent.out"):
        with pytest.raises(CouldNotLook, match="nothing was captured"):
            Captured(0, path).text()
    readable = scratch / "non-empty-capture.out"
    readable.write_text("the subject said something\n")
    assert NEVER not in Captured(0, readable).text()


@pytest.mark.parametrize("scan", ["lc_scan_open_executions", "lc_scan_schedules"])
def test_a_temporal_read_that_fails_keeps_the_clis_own_words(tmp_path: Path, scan: str) -> None:
    cli = tmp_path / "temporal"
    cli.write_text("#!/usr/bin/env bash\necho 'Error: context deadline exceeded' >&2\nexit 1\n")
    cli.chmod(0o755)
    done = subprocess.run(
        ["bash", "-c", f"{SOURCED}{scan}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "DJB_TEMPORAL_CLI": str(cli), "LC_TEMPORAL_RETRY_SLEEP": "0"},
    )
    assert done.returncode != 0
    assert "Error: context deadline exceeded" in done.stderr


CENSUS_OURS = "djb_censusprobe_0badc0de"
CENSUS_FOREIGN_QUEUE = "djb-someoneelse_5ca1ab1e"


def census_cli(tmp_path: Path, failures: int) -> Path:
    """A stub `temporal`: logs argv, fails `workflow list` `failures` times, then a mixed list."""
    queue = f"djb-{CENSUS_OURS.removeprefix('djb_')}"
    runs = [
        {"execution": {"workflowId": "ours-1"}, "taskQueue": queue, "type": {"name": "W"}},
        {"execution": {"workflowId": "theirs-1"}, "taskQueue": CENSUS_FOREIGN_QUEUE},
    ]
    (tmp_path / "answer.json").write_text(json.dumps(runs))
    (tmp_path / "failures").write_text(str(failures))
    cli = tmp_path / "temporal"
    cli.write_text(
        "#!/usr/bin/env bash\n"
        f'here="{tmp_path}"\n'
        'printf "%s\\n" "$*" >>"$here/argv"\n'
        'if [ "$1 $2" = "workflow list" ]; then\n'
        '    left="$(cat "$here/failures")"\n'
        '    if [ "$left" -gt 0 ]; then\n'
        '        echo "$((left - 1))" >"$here/failures"\n'
        "        echo 'Error: context deadline exceeded' >&2\n"
        "        exit 1\n"
        "    fi\n"
        '    cat "$here/answer.json"\n'
        "    exit 0\n"
        "fi\n"
        "echo '{}'\n"
    )
    cli.chmod(0o755)
    return cli


def census_run(sweep: Callable[..., Captured], cli: Path) -> tuple[int, str]:
    """`--class open-execution --only <probe> --assert-none` over the stub; exit and words."""
    ran = sweep(
        [SWEEP, "--class", "open-execution", "--only", CENSUS_OURS, "--assert-none"],
        env={"DJB_TEMPORAL_CLI": str(cli), "LC_TEMPORAL_RETRY_SLEEP": "0"},
    )
    return ran.rc, ran.text()


def test_the_open_execution_census_retries_a_failed_read_once(
    tmp_path: Path, sweep: Callable[..., Captured]
) -> None:
    rc, said = census_run(sweep, census_cli(tmp_path, failures=1))
    assert rc != 2, said
    assert "ours-1" in said
    assert "retried" in said and "context deadline exceeded" in said


def test_the_open_execution_refusal_names_the_clis_words_and_exit(
    tmp_path: Path, sweep: Callable[..., Captured]
) -> None:
    rc, said = census_run(sweep, census_cli(tmp_path, failures=2))
    assert rc == 2, said
    headline = next(line for line in said.splitlines() if line.startswith("!! "))
    assert "context deadline exceeded" in headline and "exit 1" in headline, headline
    assert "twice" in headline, headline
    assert (tmp_path / "argv").read_text().count("workflow list") == 2


def test_the_open_execution_census_asks_the_server_for_this_checkouts_queue_only(
    tmp_path: Path, sweep: Callable[..., Captured]
) -> None:
    census_run(sweep, census_cli(tmp_path, failures=0))
    lists = [ln for ln in (tmp_path / "argv").read_text().splitlines() if "workflow list" in ln]
    queue = f"djb-{CENSUS_OURS.removeprefix('djb_')}"
    assert lists and all(f'TaskQueue STARTS_WITH "{queue}"' in ln for ln in lists), lists


def test_a_census_that_never_read_does_not_say_it_read_twice(
    tmp_path: Path, sweep: Callable[..., Captured]
) -> None:
    cli = census_cli(tmp_path, failures=0)
    real = shutil.which("mktemp")
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "mktemp").write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in *djb-lc-executions*) echo "mktemp: refused" >&2; exit 1 ;; esac\n'
        f'exec {real} "$@"\n'
    )
    (stub / "mktemp").chmod(0o755)
    ran = sweep(
        [SWEEP, "--class", "open-execution", "--only", CENSUS_OURS, "--assert-none"],
        env={
            "DJB_TEMPORAL_CLI": str(cli),
            "LC_TEMPORAL_RETRY_SLEEP": "0",
            "PATH": f"{stub}:{os.environ['PATH']}",
        },
    )
    said = ran.text()
    assert ran.rc == 2, said
    headline = next(line for line in said.splitlines() if line.startswith("!! "))
    assert "twice" not in headline and "before any read" in headline, headline
    assert not (tmp_path / "argv").exists()


def test_another_checkouts_executions_are_not_counted_as_ours(
    tmp_path: Path, sweep: Callable[..., Captured]
) -> None:
    _, said = census_run(sweep, census_cli(tmp_path, failures=0))
    assert "ours-1" in said
    assert "theirs-1" not in said and CENSUS_FOREIGN_QUEUE not in said


def test_registry_is_the_declared_population(world: World, sweep: Callable[..., Captured]) -> None:
    ran = sweep([SWEEP, "--list-classes"])
    assert " ".join(ran.text().split()) == CLASSES


def test_registry_declares_all_seven_columns(world: World) -> None:
    assert frame_ok("lc_registry_check >/dev/null 2>&1"), (
        "lc_registry_check refuses its own declarations"
    )
    blank = frame(
        "n=0; for c in $(lc_classes); do for i in 3 4 5 6 7 8; do"
        ' [ -n "$(lc_field "$c" "$i")" ] || n=$((n+1)); done; done; echo $n'
    )
    assert blank == "0"


def test_registry_claims_every_planted_shape(world: World) -> None:
    claims = {
        world.base: "checkout-database",
        world.test_db: "test-database",
        f"{world.base}_hp": "hot-path-cache",
        f"{world.base}_perf": "perf-world",
        f"{world.base}_grants": "grants-pass-database",
        f"{world.base}_drill": "restore-drill-database",
        f"{world.base}_idhome": "identity-home-drive-database",
    }
    for name, want in claims.items():
        assert frame('lc_class_of database "$1"', name) == want, name
    assert frame('lc_class_of schedule "$1"', world.schedule) == "schedule"
    assert frame('lc_class_of open-execution "$1"', world.queue) == "open-execution"
    assert frame('lc_class_of database "$1" || true', world.fake_db) == ""


def test_a_local_lifecycle_class_is_censused_and_verdicted_like_a_built_in(
    world: World, sweep: Callable[..., Captured]
) -> None:
    drawer_with(world, good=True)
    listed = sweep([SWEEP, "--list-classes"], env=in_drawer(world))
    assert "lc2-local-world" in listed.text().split()
    assert (
        frame('lc_class_of database "$1"', world.local_db, env=in_drawer(world))
        == "lc2-local-world"
    )
    assert (
        frame('lc_class_of database "$1"', world.base, env=in_drawer(world)) == "checkout-database"
    )
    create(world.local_db)
    if not present(world.local_db):
        raise CouldNotLook(f"could not plant {world.local_db}; the verdict half cannot be asked")
    try:
        ran = sweep([SWEEP, "--class", "lc2-local-world"], env=in_drawer(world))
        assert ran.rc == 0, ran.text()
        for needle in ("class: lc2-local-world", world.local_db, "FOREIGN"):
            assert needle in ran.text()
        assert "UNRECOGNIZED" not in ran.text()
    finally:
        drop(world.local_db)


def test_a_local_class_with_an_empty_field_is_refused_naming_its_file(
    world: World, sweep: Callable[..., Captured]
) -> None:
    drawer = drawer_with(world)
    (drawer / "41-no-destroy.sh").write_text(
        'lc_class "lc2-no-destroy" "database" "an identity" "a scan" "a liveness" ""'
        ' "no" "yes" "glob:djb_*_lc2nod"\n'
    )
    ran = sweep([SWEEP, "--list-classes"], env=in_drawer(world))
    assert ran.rc == 2, ran.text()
    assert "declares nothing in column 6" in ran.text()
    assert f"{drawer}/41-no-destroy.sh" in ran.text()


def test_the_lifecycle_drawer_is_declaration_only(
    world: World, sweep: Callable[..., Captured]
) -> None:
    drawer = drawer_with(world, good=True)
    with (drawer / "40-scratch-world.sh").open("a") as file:
        file.write("lc_verdict() { printf 'REFUSED'; }\n")
    ran = sweep([SWEEP, "--list-classes"], env=in_drawer(world))
    assert ran.rc == 2, ran.text()
    assert "is not declaration-only" in ran.text()
    assert "lc_verdict()" in ran.text()
    assert frame('lc_verdict "$1" 0', world.our_base, live=True, env=in_drawer(world)) == "live"
    assert frame("lc_field lc2-local-world 1 || true", env=in_drawer(world)) == ""


def test_an_absent_lifecycle_drawer_is_byte_identical(
    world: World, sweep: Callable[..., Captured]
) -> None:
    shutil.rmtree(world.drawer, ignore_errors=True)
    absent = sweep([SWEEP, "--list-classes"], env=in_drawer(world)).text()
    world.drawer.mkdir()
    empty = sweep([SWEEP, "--list-classes"], env=in_drawer(world)).text()
    populated = sweep([SWEEP, "--list-classes"]).text()
    assert absent == populated
    assert empty == populated
    shutil.rmtree(world.drawer, ignore_errors=True)


def test_the_lifecycle_drawer_refuses_what_could_still_run(
    world: World, sweep: Callable[..., Captured]
) -> None:
    for shape in ("semicolon", "command-substitution", "and-list"):
        drawer = drawer_with(world)
        victim = drawer / f"pwned-{shape}"
        tail = '"e" "l" "d" "no" "yes" "glob:djb_*_lc2inj"'
        body = {
            "semicolon": f'{INJ} "i" {tail}; lc_verdict() {{ printf OVERRIDDEN; }}',
            "command-substitution": f'{INJ} "$(touch {victim})" {tail}',
            "and-list": f'{INJ} "i" {tail} && touch {victim}',
        }[shape]
        (drawer / "42-injected.sh").write_text(f"#!/usr/bin/env bash\n{body}\n")
        ran = sweep([SWEEP, "--list-classes"], env=in_drawer(world))
        assert ran.rc == 2, f"{shape}: {ran.text()}"
        assert "is not declaration-only" in ran.text()
        assert not victim.exists(), f"{victim} exists, so the {shape} file WAS sourced"
        assert frame("lc_field lc2-inj 1 || true", env=in_drawer(world)) == ""
    drawer_with(world, good=True)
    assert frame("lc_field lc2-local-world 1", env=in_drawer(world)) == "lc2-local-world"
    shutil.rmtree(world.drawer, ignore_errors=True)


def test_verdict_grammar_answers_all_four(world: World) -> None:
    grid = (
        ("lc_verdict djb_main 0", "REFUSED"),
        ('lc_verdict "${LC_LIVE_BASES[0]}" 0', "live"),
        (f'lc_verdict "{world.base}" 3', "IN USE"),
        (f'lc_verdict "{world.base}" 0', "FOREIGN"),
        ("lc_verdict postgres 7", "REFUSED"),
    )
    for program, want in grid:
        assert frame(program, live=True) == want, program


def test_one_enumerator_two_consumers(world: World, sweep: Callable[..., Captured]) -> None:
    plant_our_checkout_database(world)
    census = sweep([SWEEP, "--class", "checkout-database"])
    live = [line.split()[1] for line in census.text().splitlines() if line.startswith("  live ")]
    assert live, f"the frame named no live checkout database to compare:\n{census.text()}"
    reaper = sweep([DB_SWEEP, "--all-checkouts", "--orphans"])
    assert (
        sum(1 for line in reaper.text().splitlines() if line.startswith(f"  live     {live[0]} "))
        == 1
    )


def test_sweep_refuses_an_unknown_flag(sweep: Callable[..., Captured]) -> None:
    ran = sweep([SWEEP, "--no-such-flag"])
    assert ran.rc == 2, ran.text()
    assert "unknown argument '--no-such-flag'" in ran.text()


def test_sweep_refuses_force_foreign_without_sweep(sweep: Callable[..., Captured]) -> None:
    ran = sweep([SWEEP, "--force-foreign"])
    assert ran.rc == 2, ran.text()
    assert "licence to DESTROY and means nothing without --sweep" in ran.text()


def test_sweep_refuses_an_empty_only(sweep: Callable[..., Captured]) -> None:
    ran = sweep([SWEEP, "--only"])
    assert ran.rc == 2, ran.text()
    assert "--only needs an identity prefix" in ran.text()


def test_sweep_refuses_a_root_that_is_not_there(
    sweep: Callable[..., Captured], scratch: Path
) -> None:
    ran = sweep([SWEEP, "--roots", str(scratch / "absent")])
    assert ran.rc == 2, ran.text()
    assert "is not a directory" in ran.text()


def test_sweep_refuses_an_unknown_class(sweep: Callable[..., Captured]) -> None:
    ran = sweep([SWEEP, "--class", "no-such-class"])
    assert ran.rc == 2, ran.text()
    assert "no class named 'no-such-class'" in ran.text()


def test_the_dead_queue_sibling_is_required_empty_before_anything_is_planted(
    world: World, sweep: Callable[..., Captured]
) -> None:
    ran = sweep([SWEEP, "--only", world.base, "--assert-none"])
    if ran.rc != 0:
        print(
            f"the sibling scope held a killed run's residue (exit {ran.rc}); removing it, re-asking"
        )
        teardown_scratch_temporal(world)
        for name in (world.base, world.test_db, world.hp_db):
            drop(name)
        ran = sweep([SWEEP, "--only", world.base, "--assert-none"])
    assert ran.rc == 0, ran.text()
    require_dead_scratch_queue(world)


def test_new_classes_are_censused_as_foreign(world: World, sweep: Callable[..., Captured]) -> None:
    plant_databases(world)
    plant_temporal(world)
    ran = sweep([SWEEP, "--only", world.base])
    assert ran.rc == 0, ran.text()
    for needle in (
        f"FOREIGN  {world.schedule}",
        f"FOREIGN  {world.execution} (queue {world.queue})",
        f"FOREIGN  {world.base}",
        f"FOREIGN  {world.test_db}",
        f"warm     {world.hp_db}",
    ):
        assert needle in ran.text()


def test_sweep_alone_leaves_foreign_alone(world: World, sweep: Callable[..., Captured]) -> None:
    plant_databases(world)
    plant_temporal(world)
    ran = sweep([SWEEP, "--sweep", "--only", world.base])
    assert ran.rc == 0, ran.text()
    assert "--sweep --force-foreign to destroy" in ran.text()
    assert "DESTROYED" not in ran.text()
    assert schedule_present(world.schedule)
    assert execution_present(world.execution)
    assert present(world.base)


def test_force_foreign_without_roots_is_refused_and_drops_nothing(
    world: World, sweep: Callable[..., Captured]
) -> None:
    plant_databases(world)
    belt = no_server_bin(world.work)
    ran = sweep([SWEEP, "--sweep", "--force-foreign"], env={"PATH": f"{belt}:{os.environ['PATH']}"})
    assert ran.rc == 2, ran.text()
    for needle in ("REFUSED: --force-foreign needs --roots <dir>", "Nothing was destroyed"):
        assert needle in ran.text()
    for needle in ("the checkout-machinery census", "pg_catalog could not be read", "DESTROYED"):
        assert needle not in ran.text()
    assert present(world.base)


def test_only_does_not_license_force_foreign_without_roots(
    world: World, sweep: Callable[..., Captured]
) -> None:
    plant_databases(world)
    ran = sweep([SWEEP, "--sweep", "--force-foreign", "--only", world.base])
    assert ran.rc == 2, ran.text()
    for needle in ("REFUSED: --force-foreign needs --roots <dir>", "narrowing is not evidence"):
        assert needle in ran.text()
    assert "DESTROYED" not in ran.text()
    assert present(world.base)


def test_db_sweep_force_foreign_without_roots_is_refused(
    world: World, sweep: Callable[..., Captured]
) -> None:
    plant_databases(world)
    belt = no_server_bin(world.work)
    ran = sweep(
        [DB_SWEEP, "--all-checkouts", "--orphans", "--sweep", "--force-foreign"],
        env={"PATH": f"{belt}:{os.environ['PATH']}"},
    )
    assert ran.rc == 2, ran.text()
    for needle in ("REFUSED: --force-foreign needs --roots <dir>", "Nothing was dropped"):
        assert needle in ran.text()
    for needle in ("scope: every derived-shaped name", "DROPPING"):
        assert needle not in ran.text()
    assert present(world.base)


def test_force_foreign_prints_then_acts(world: World, sweep: Callable[..., Captured]) -> None:
    ran = destroy_scratch(world, sweep)
    assert ran.rc == 0, ran.text()
    for needle in (
        "--force-foreign given: DESTROYING it on the operator's word",
        f"DESTROYED {world.schedule}",
        f"DESTROYED {world.execution} (queue {world.queue})",
    ):
        assert needle in ran.text()
    lines = ran.text().splitlines()
    claim = next((i for i, line in enumerate(lines) if f"FOREIGN  {world.schedule}" in line), None)
    consequence = next(
        (i for i, line in enumerate(lines) if f"DESTROYED {world.schedule}" in line), None
    )
    assert claim is not None and consequence is not None and claim < consequence, (
        claim,
        consequence,
    )


def test_the_scratch_machinery_is_actually_gone(
    world: World, sweep: Callable[..., Captured]
) -> None:
    ran = destroy_scratch(world, sweep)
    assert ran.rc == 0, ran.text()
    assert not schedule_present(world.schedule)
    assert not execution_present(world.execution)
    for name in (world.base, world.test_db, world.hp_db):
        assert not present(name), name


def test_a_refused_shape_survives_force_foreign(
    world: World, sweep: Callable[..., Captured]
) -> None:
    temporal(
        "schedule",
        "create",
        "--schedule-id",
        world.underived_schedule,
        "--interval",
        "8760h",
        "--paused",
        "--workflow-id",
        f"lc2scratch:probe:noun:underived:{world.hash}",
        "--task-queue",
        "djb-lc2scratchnohash",
        "--type",
        "Lc2ScratchNeverRuns",
    )
    try:
        ran = sweep(
            [
                SWEEP,
                "--class",
                "schedule",
                "--sweep",
                "--force-foreign",
                "--roots",
                str(world.root),
                "--only",
                "djb_lc2scratchnohash",
            ]
        )
        assert ran.rc == 0, ran.text()
        assert f"REFUSED  {world.underived_schedule}" in ran.text()
        assert "DESTROYED" not in ran.text()
        assert schedule_present(world.underived_schedule)
    finally:
        temporal("schedule", "delete", "--schedule-id", world.underived_schedule)


def derive_inside(checkout: Path) -> str:
    """The name `scripts/db.sh` derives standing inside `checkout`, with no exported pin."""
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_NAME"}
    return subprocess.run(
        ["bash", "-c", ". scripts/db.sh >/dev/null 2>&1 && db_name"],
        cwd=checkout,
        capture_output=True,
        text=True,
        env=env,
    ).stdout.strip()


def shared_clone(into: Path) -> None:
    """A clone borrowing this checkout's objects; `CouldNotLook` when git refuses."""
    done = subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-hardlinks", str(ROOT), str(into)],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise CouldNotLook(f"could not clone this repository into {into}: {done.stderr.strip()}")


def test_a_rooted_clones_linked_worktree_database_reads_live(
    world: World, sweep: Callable[..., Captured], scratch: Path
) -> None:
    roots, elsewhere = scratch / "roots", scratch / "elsewhere"
    clone, linked = roots / "clone-a", elsewhere / "wt-b"
    roots.mkdir()
    elsewhere.mkdir()
    shared_clone(clone)
    added = subprocess.run(
        ["git", "-C", str(clone), "worktree", "add", "--quiet", "-b", "o2decoy", str(linked)],
        capture_output=True,
        text=True,
    )
    assert added.returncode == 0, added.stderr
    base = derive_inside(linked)
    assert frame_ok('db_valid_name "$1"', base), (
        f"db.sh derived no name inside the linked worktree ({base!r})"
    )
    world.decoys.append(base)
    create(base)
    try:
        assert present(base)
        control = sweep([SWEEP, "--class", "checkout-database", "--only", base])
        assert control.rc == 0, control.text()
        assert f"FOREIGN  {base}" in control.text()
        rooted = sweep(
            [SWEEP, "--class", "checkout-database", "--only", base, "--roots", str(roots)]
        )
        assert rooted.rc == 0, rooted.text()
        assert f"live     {base}" in rooted.text()
        assert f"FOREIGN  {base}" not in rooted.text()
        spared = sweep(
            [
                SWEEP,
                "--sweep",
                "--force-foreign",
                "--roots",
                str(roots),
                "--class",
                "checkout-database",
                "--only",
                base,
            ]
        )
        assert spared.rc == 0, spared.text()
        assert "DESTROYED" not in spared.text()
        assert present(base)
    finally:
        drop(base)
        subprocess.run(
            ["git", "-C", str(clone), "worktree", "remove", "--force", str(linked)],
            capture_output=True,
        )


def test_two_roots_are_both_scanned_and_printed(
    world: World, sweep: Callable[..., Captured], scratch: Path
) -> None:
    roots_a, roots_b = scratch / "roots-a", scratch / "roots-b"
    roots_a.mkdir()
    roots_b.mkdir()
    shared_clone(roots_b / "clone-b")
    base = derive_inside(roots_b / "clone-b")
    assert frame_ok('db_valid_name "$1"', base), (
        f"db.sh derived no name inside the second root's clone ({base!r})"
    )
    assert base != world.our_base and not frame_ok('lc_owning_checkout "$1" >/dev/null', base), (
        f"{base} is derived by a checkout this run can see; nothing was touched"
    )
    world.decoys.append(base)
    create(base)
    try:
        assert present(base)
        control = sweep(
            [SWEEP, "--class", "checkout-database", "--only", base, "--roots", str(roots_a)]
        )
        assert control.rc == 0, control.text()
        assert f"scanned         {roots_a}" in control.text()
        assert f"FOREIGN  {base}" in control.text()
        both = sweep(
            [
                SWEEP,
                "--class",
                "checkout-database",
                "--only",
                base,
                "--roots",
                str(roots_a),
                "--roots",
                str(roots_b),
            ]
        )
        assert both.rc == 0, both.text()
        for needle in (
            f"scanned         {roots_a}",
            f"scanned         {roots_b}",
            f"live     {base}",
        ):
            assert needle in both.text()
        assert f"FOREIGN  {base}" not in both.text()
    finally:
        drop(base)


def test_an_unrecognized_shape_is_exit_2(world: World, sweep: Callable[..., Captured]) -> None:
    create(world.fake_db)
    try:
        ran = sweep([SWEEP, "--only", world.foreign_db])
        assert ran.rc == 2, ran.text()
        for needle in (
            f"UNRECOGNIZED database: {world.fake_db}",
            "Declare the class there",
            "machinery class N+1 exists and the registry",
        ):
            assert needle in ran.text()
    finally:
        drop(world.fake_db)


def test_a_declared_shape_is_not_unrecognized(world: World, sweep: Callable[..., Captured]) -> None:
    create(world.foreign_db)
    try:
        ran = sweep([SWEEP, "--only", world.foreign_db])
        assert ran.rc == 0, ran.text()
        assert "UNRECOGNIZED" not in ran.text()
        assert f"FOREIGN  {world.foreign_db}" in ran.text()
    finally:
        drop(world.foreign_db)


def test_a_grants_pass_database_is_censused_foreign_and_dropped_by_force_foreign(
    world: World, sweep: Callable[..., Captured]
) -> None:
    assert frame_ok('lc_derived_shape "$1"', world.grants_db)
    assert frame('lc_class_of database "$1" || true', world.grants_db) == "grants-pass-database"
    create(world.grants_db)
    try:
        census = sweep([SWEEP, "--only", world.foreign_db])
        assert census.rc == 0, census.text()
        assert "UNRECOGNIZED" not in census.text()
        for needle in ("class: grants-pass-database", f"FOREIGN  {world.grants_db}"):
            assert needle in census.text()
        assert "DESTROYED" not in census.text()
        assert present(world.grants_db)
        swept = sweep(
            [
                SWEEP,
                "--sweep",
                "--force-foreign",
                "--roots",
                str(world.root),
                "--only",
                world.grants_db,
            ]
        )
        assert swept.rc == 0, swept.text()
        assert f"DESTROYED {world.grants_db}" in swept.text()
        assert not present(world.grants_db)
    finally:
        drop(world.grants_db)


def test_an_identity_home_drive_database_is_censused_foreign_and_dropped_by_force_foreign(
    world: World, sweep: Callable[..., Captured]
) -> None:
    assert frame_ok('lc_derived_shape "$1"', world.idhome_db)
    assert (
        frame('lc_class_of database "$1" || true', world.idhome_db)
        == "identity-home-drive-database"
    )
    assert frame("lc_field identity-home-drive-database 8").startswith("yes")
    create(world.idhome_db)
    try:
        census = sweep([SWEEP, "--only", world.foreign_db])
        assert census.rc == 0, census.text()
        assert "UNRECOGNIZED" not in census.text()
        for needle in ("class: identity-home-drive-database", f"FOREIGN  {world.idhome_db}"):
            assert needle in census.text()
        assert "DESTROYED" not in census.text()
        swept = sweep(
            [
                SWEEP,
                "--sweep",
                "--force-foreign",
                "--roots",
                str(world.root),
                "--only",
                world.idhome_db,
            ]
        )
        assert swept.rc == 0, swept.text()
        assert f"DESTROYED {world.idhome_db}" in swept.text()
        assert not present(world.idhome_db)
    finally:
        drop(world.idhome_db)


def test_assert_none_is_silent_on_an_empty_scope(
    world: World, sweep: Callable[..., Captured]
) -> None:
    teardown_scratch_temporal(world)
    ran = sweep([SWEEP, "--class", "schedule", "--only", world.base, "--assert-none"])
    assert ran.rc == 0, ran.text()
    assert "census: 0 found" in ran.text()


def test_assert_none_fails_on_a_populated_scope(
    world: World, sweep: Callable[..., Captured]
) -> None:
    plant_temporal(world)
    try:
        ran = sweep([SWEEP, "--class", "schedule", "--only", world.base, "--assert-none"])
        assert ran.rc == 1, ran.text()
        for needle in (
            "instance(s) are in scope and none should be",
            world.schedule,
            "a finding about",
        ):
            assert needle in ran.text()
    finally:
        teardown_scratch_temporal(world)


def test_assert_none_refuses_to_be_a_broom(world: World, sweep: Callable[..., Captured]) -> None:
    ran = sweep([SWEEP, "--class", "schedule", "--only", world.base, "--assert-none", "--sweep"])
    assert ran.rc == 2, ran.text()
    assert "--assert-none and --sweep are opposites" in ran.text()


@dataclass
class Session:
    """A connection to this checkout's database, held by a child, dropped by its backend pid."""

    process: subprocess.Popen[bytes]
    backend: str = ""


@pytest.fixture
def hold_a_session(world: World, scratch: Path) -> Iterator[Callable[[], Session | None]]:
    """`hold()` answers a held session once `pg_stat_activity` shows it, or None within 20 s."""
    held: list[Session] = []

    def hold() -> Session | None:
        pidfile = scratch / "held_session.pid"
        with pidfile.open("wb") as sink:
            process = subprocess.Popen(
                [
                    "bash",
                    "-c",
                    f'{SOURCED}db_psql -d "$1" -tAc "{BACKEND}" -c "SELECT pg_sleep(25)"',
                    "reap",
                    world.our_base,
                ],
                cwd=ROOT,
                stdout=sink,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        session = Session(process)
        held.append(session)
        for _ in range(40):
            session.backend = "".join(ch for ch in pidfile.read_text() if ch.isdigit())
            if session.backend and sessions_on(world.our_base) != "0":
                return session
            time.sleep(0.5)
        return None

    yield hold
    for session in held:
        release(world, session)


def release(world: World, session: Session) -> bool:
    """Terminate the backend, then the client by its process group; True once no session is left."""
    if session.backend:
        query("SELECT pg_terminate_backend(:'pid'::int)", pid=session.backend)
    if session.process.poll() is None:
        os.killpg(session.process.pid, signal.SIGTERM)
    session.process.wait()
    session.backend = ""
    for _ in range(40):
        if sessions_on(world.our_base) == "0":
            return True
        time.sleep(0.5)
    return False


def test_assert_none_exempts_this_checkouts_own_working_set_in_use(
    world: World, sweep: Callable[..., Captured], hold_a_session: Callable[[], Session | None]
) -> None:
    plant_our_checkout_database(world)
    session = hold_a_session()
    if session is None:
        print(
            f"SKIPPED the session half: no session on {world.our_base} became visible within 20 s"
        )
        return
    ran = sweep([SWEEP, "--class", "checkout-database", "--only", world.our_base, "--assert-none"])
    assert ran.rc == 0, ran.text()
    for needle in (
        "(THIS CHECKOUT)",
        "it is a working set, not a leftover",
        "exempt from --assert-none — in use right now",
        "instance(s) EXEMPT — this checkout's own working set",
        "session(s) on it",
        "is declared NOT disposable",
    ):
        assert needle in ran.text()
    release(world, session)
    pollers = pollers_on(world.our_queue)
    if pollers == 0:
        print(f"SKIPPED the poller half: no poller on {world.our_queue}; no worker is started here")
        return
    probe = world.probe("workingset")
    temporal(
        "workflow",
        "start",
        "--workflow-id",
        probe,
        "--task-queue",
        world.our_queue,
        "--type",
        "N466WorkingSetProbeNeverRuns",
    )
    try:
        assert execution_appears(probe)
        polled = sweep(
            [SWEEP, "--class", "open-execution", "--only", world.our_base, "--assert-none"]
        )
        assert polled.rc == 0, polled.text()
        for needle in (
            probe,
            "exempt from --assert-none — in use right now",
            f"poller(s) on {world.our_queue}",
        ):
            assert needle in polled.text()
    finally:
        temporal(
            "workflow",
            "terminate",
            "--workflow-id",
            probe,
            "--reason",
            "test_reap: working-set probe teardown",
        )


def test_assert_none_keeps_its_teeth_on_an_owned_instance_nothing_is_using(
    world: World, sweep: Callable[..., Captured]
) -> None:
    plant_our_checkout_database(world)
    if sessions_on(world.our_base) != "0":
        print(f"SKIPPED: something else on this machine still holds a session on {world.our_base}")
        return
    ran = sweep([SWEEP, "--class", "checkout-database", "--only", world.our_base, "--assert-none"])
    assert ran.rc == 1, ran.text()
    for needle in (
        "NOT exempt from --assert-none",
        "is a strand, not a working set",
        "instance(s) are in scope and none should be",
    ):
        assert needle in ran.text()


def test_assert_none_still_fails_on_a_stray_run_this_checkout_owns(
    world: World, sweep: Callable[..., Captured]
) -> None:
    if pollers_on(world.our_queue) != 0:
        print(
            f"SKIPPED: a worker polls {world.our_queue}; a run planted there is work, not a strand"
        )
        return
    probe = world.probe("stray")
    temporal(
        "workflow",
        "start",
        "--workflow-id",
        probe,
        "--task-queue",
        world.our_queue,
        "--type",
        "N466StrayProbeNeverRuns",
    )
    try:
        assert execution_appears(probe)
        ran = sweep([SWEEP, "--class", "open-execution", "--only", world.our_base, "--assert-none"])
        assert ran.rc == 1, ran.text()
        for needle in (
            probe,
            "NOT exempt from --assert-none",
            "instance(s) are in scope and none should be",
        ):
            assert needle in ran.text()
    finally:
        temporal(
            "workflow",
            "terminate",
            "--workflow-id",
            probe,
            "--reason",
            "test_reap: teeth probe teardown",
        )


def test_a_dot_env_pin_does_not_decide_who_owns_what(world: World) -> None:
    derived = frame("db_name")
    resolved = frame(
        'unset DATABASE_NAME; . scripts/db.sh >/dev/null 2>&1; printf "%s" "$DATABASE_NAME"'
    )
    assert resolved == derived
    exported = frame(
        "DATABASE_NAME=djb_exported_wins; export DATABASE_NAME;"
        ' . scripts/db.sh >/dev/null 2>&1; printf "%s" "$DATABASE_NAME"'
    )
    assert exported == "djb_exported_wins"


def test_an_exported_pin_does_not_move_this_checkouts_identity(
    world: World, sweep: Callable[..., Captured]
) -> None:
    plant_our_checkout_database(world)
    ran = sweep(
        [SWEEP, "--class", "checkout-database", "--only", world.our_base],
        env={"DATABASE_NAME": "djb_pinned_by_the_environment"},
    )
    assert ran.rc == 0, ran.text()
    for needle in (
        f"this checkout   {world.our_base}",
        "DATABASE_NAME is pinned to djb_pinned_by_the_environment",
        "(THIS CHECKOUT)",
    ):
        assert needle in ran.text()


def test_owning_is_not_a_licence_to_destroy(world: World) -> None:
    grid = (
        ("checkout-database", "live", "1", "none"),
        ("open-execution", "live", "1", "none"),
        ("test-database", "live", "0", "none"),
        ("test-database", "IN USE", "1", "none"),
        ("test-database", "REFUSED", "1", "none"),
        ("test-database", "live", "1", "own"),
        ("schedule", "live", "1", "own"),
        ("checkout-database", "FOREIGN", "0", "foreign"),
    )
    for klass, verdict, mine, want in grid:
        decided = frame('lc_destroy_decision "$1" "$2" "$3"', klass, verdict, mine)
        assert decided.split("|")[0] == want, (klass, verdict, mine, decided)
    assert "declared NOT disposable" in frame("lc_destroy_decision checkout-database live 1")


def test_this_checkouts_running_work_survives_force_foreign(
    world: World, sweep: Callable[..., Captured]
) -> None:
    probe = world.probe("live")
    temporal(
        "workflow",
        "start",
        "--workflow-id",
        probe,
        "--task-queue",
        world.our_queue,
        "--type",
        "LiveProbeNeverRuns",
    )
    try:
        ran = sweep(
            [
                SWEEP,
                "--sweep",
                "--force-foreign",
                "--roots",
                str(world.root),
                "--class",
                "open-execution",
                "--only",
                world.our_base,
            ]
        )
        assert ran.rc == 0, ran.text()
        for needle in ("(THIS CHECKOUT)", "declared NOT disposable"):
            assert needle in ran.text()
        assert f"DESTROYED {probe}" not in ran.text()
        assert execution_present(probe)
    finally:
        temporal(
            "workflow",
            "terminate",
            "--workflow-id",
            probe,
            "--reason",
            "test_reap: live probe teardown",
        )


def test_the_gate_census_asserts_open_executions_too() -> None:
    schedule = [SWEEP, "--class", "schedule", "--only", "djb_probe_name", "--assert-none"]
    opened = [SWEEP, "--class", "open-execution", "--only", "djb_probe_name", "--assert-none"]
    rc, said, argvs, scripts = process_census(0, "0", 1)
    assert rc == 1 and argvs == [schedule, opened], said
    assert scripts and 'lc_queue_pollers "djb-probe_name"' in scripts[0]
    assert "THIS TREE STRANDED A RUNNING TEMPORAL EXECUTION" in said
    assert "--sweep --class open-execution --only" not in said
    rc, said, _, _ = process_census(0, "0", 2)
    assert rc == 2 and "THE OPEN-EXECUTION CENSUS COULD NOT BE TAKEN" in said
    rc, said, argvs, _ = process_census(0, "3", 1)
    assert rc == 0 and argvs == [schedule], said
    rc, said, argvs, _ = process_census(1, "0", 0)
    assert rc == 1 and argvs == [schedule] and "--sweep --class schedule --only" in said


def test_the_gate_census_remedy_actually_clears_a_strand(
    world: World, sweep: Callable[..., Captured], scratch: Path
) -> None:
    workflow, scope, queue = world.probe("remedystrand"), world.our_base, world.our_queue
    if pollers_on(world.our_queue) != 0:
        print(
            f"SKIPPED the strand world on {world.our_queue}: it is polled; proving on the sibling"
        )
        workflow, scope, queue = world.strand, world.base, world.queue
        require_dead_scratch_queue(world)
    temporal(
        "workflow",
        "start",
        "--workflow-id",
        workflow,
        "--task-queue",
        queue,
        "--type",
        "GateStrandProbeNeverRuns",
    )
    try:
        assert execution_appears(workflow)
        red = sweep([SWEEP, "--class", "open-execution", "--only", scope, "--assert-none"])
        assert red.rc == 1, red.text()
        assert workflow in red.text()
        remedy = gate_strand_remedy()
        assert remedy, "the leg prints no command"
        assert "workflow terminate" in remedy
        remedy = remedy.replace(REMEDY_PLACEHOLDER, workflow)
        assert "<" not in remedy
        ran = run_to(scratch / "remedy.out", ["bash", "-c", 'eval "$1"', "remedy", remedy], ROOT)
        assert ran.rc == 0, ran.path.read_text()
        for _ in range(15):
            if not execution_present(workflow):
                break
            time.sleep(1)
        assert not execution_present(workflow)
        green = sweep([SWEEP, "--class", "open-execution", "--only", scope, "--assert-none"])
        assert green.rc == 0, green.text()
    finally:
        temporal(
            "workflow", "terminate", "--workflow-id", workflow, "--reason", "test_reap teardown"
        )


def test_the_redis_answer_is_recorded() -> None:
    lifecycle = (ROOT / "scripts" / "lifecycle.sh").read_text().splitlines()
    assert sum("REDIS: DECLARED EXEMPT" in line for line in lifecycle) == 1
    assert sum("N-ROW CANDIDATE" in line for line in lifecycle) == 1


def test_the_parser_reads_both_of_temporals_time_formats() -> None:
    action = {
        "actualTime": stamp_ago(7230),
        "startWorkflowStatus": "WORKFLOW_EXECUTION_STATUS_RUNNING",
    }
    info = {
        "workflowType": {"name": "ProbeWorkflow"},
        "recentActions": [action],
        "futureActionTimes": [stamp_ago(-5430)],
    }
    document = json.dumps([{"scheduleId": "probe:djb-clock_00000000", "info": info}])
    row = parse("schedules", document).stdout.rstrip("\n").split("\t")
    assert frame('lc_duration "$1"', row[1]) == "2h0m"
    assert frame('lc_duration "$1"', row[2]) == "1h30m"
    assert row[4] == "RUNNING"


def test_a_stamp_the_parser_cannot_read_is_unknown_and_never_zero() -> None:
    document = (
        '[{"execution": {"workflowId": "probe:unreadable"}, "taskQueue": "djb-clock_00000000",'
        ' "type": {"name": "ProbeWorkflow"}, "startTime": "the day before yesterday"}]'
    )
    age = parse("executions", document).stdout.rstrip("\n").split("\t")[2]
    assert age == "-1"
    assert frame('lc_duration "$1"', age) == "unknown"
    assert frame("lc_duration 0") == "0s"


def test_a_backlog_is_evidence_of_harm_and_never_of_liveness(world: World) -> None:
    stats = [
        {
            "taskQueueType": "workflow",
            "approximateBacklogCount": 3,
            "approximateBacklogAge": "7h52m3s",
        },
        {"taskQueueType": "activity", "approximateBacklogCount": 1, "approximateBacklogAge": "12m"},
    ]
    document = json.dumps({"pollers": None, "stats": stats})
    pollers, backlog, age = parse("queue", document).stdout.strip().split("|")
    assert backlog == "4"
    assert frame('lc_duration "$1"', age) == "7h52m"
    assert pollers == "0"
    assert frame('lc_verdict "$1" "$2"', world.base, pollers, live=True) == "FOREIGN"


def test_the_parser_refuses_what_it_cannot_read() -> None:
    assert parse("schedules", "").returncode == 2
    assert parse("executions", "Error: connection refused").returncode == 2
    unknown = parse("pollers", "[]")
    assert unknown.returncode == 2
    assert "takes exactly one of" in unknown.stdout + unknown.stderr


def test_a_presence_probe_survives_a_long_scan() -> None:
    found = (
        "set -o pipefail; { printf 'djb-q\\tHEAD-OF-LIST\\t1\\tT\\n';"
        ' awk \'BEGIN { for (i = 1; i <= 20000; i++) print "djb-q\\tfiller" i "\\t1\\tT" }\'; }'
        " | awk -F'\\t' -v want=\"$1\" '$2 == want { found = 1 } END { exit !found }'"
    )
    assert subprocess.run(["bash", "-c", found, "probe", "HEAD-OF-LIST"]).returncode == 0
    assert subprocess.run(["bash", "-c", found, "probe", "NOT-IN-THE-LIST"]).returncode != 0


def test_the_frame_has_exactly_one_temporal_parser() -> None:
    lifecycle = (ROOT / "scripts" / "lifecycle.sh").read_text().splitlines()
    assert sum("python3 -c '" in line for line in lifecycle) == 0


@pytest.fixture(scope="module")
def schedule_census(world: World, tmp_path_factory: pytest.TempPathFactory) -> Captured:
    """One `--class schedule --only <scratch>` run over a planted world, read by two cases."""
    plant_databases(world)
    plant_temporal(world)
    return run_to(
        tmp_path_factory.mktemp("census") / "schedule.out",
        [SWEEP, "--class", "schedule", "--only", world.base],
        ROOT,
    )


def test_the_census_says_what_a_schedule_is_doing(schedule_census: Captured) -> None:
    assert schedule_census.rc == 0, schedule_census.text()
    for needle in ("starts Lc2ScratchNeverRuns", "NOTHING POLLING"):
        assert needle in schedule_census.text()


def test_the_graveyard_rollup_counts_what_nothing_polls(
    world: World, sweep: Callable[..., Captured]
) -> None:
    plant_databases(world)
    plant_temporal(world)
    ran = sweep([SWEEP, "--class", "task-queue", "--only", world.base])
    assert ran.rc == 0, ran.text()
    for needle in (
        "stranded: queues NOTHING IS POLLING that no visible checkout owns",
        "1 schedule(s) still aimed at it · 1 open run(s)",
        "This census TOUCHED NOTHING",
    ):
        assert needle in ran.text()
    assert "DESTROYED" not in ran.text()


def test_the_rollup_is_silent_about_what_it_did_not_look_at(schedule_census: Captured) -> None:
    assert "stranded: queues NOTHING IS POLLING" not in schedule_census.text()


def test_the_ownership_of_the_machine_state_layer_is_argued() -> None:
    header = (ROOT / "scripts" / "sweep.sh").read_text().splitlines()
    assert sum("WHO OWNS THE MACHINE-STATE LAYER" in line for line in header) == 1
    assert sum("a deleted checkout cannot self-clean" in line for line in header) == 1


def test_a_leftover_plant_from_a_killed_run_is_a_refusal_naming_the_broom(world: World) -> None:
    create(world.base)
    try:
        with pytest.raises(CouldNotLook) as refused:
            require_no_residue(world)
    finally:
        drop(world.base)
    assert "already exists and no checkout derives it" in str(refused.value)
    assert f"./scripts/db_sweep.sh --name {world.base}" in str(refused.value)


def test_two_checkouts_run_the_sweep_drive_concurrently_and_both_stay_green(
    world: World, scratch: Path
) -> None:
    clones = (scratch / "clone-a", scratch / "clone-b")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "DJB_GATE_"))}
    for clone in clones:
        done = subprocess.run(
            ["git", "clone", "--quiet", "--local", str(ROOT), str(clone)],
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            raise CouldNotLook(f"git clone --local refused: {done.stderr.strip()}")
        shutil.copytree(ROOT / "scripts", clone / "scripts", dirs_exist_ok=True)
        shutil.copy2(Path(__file__), clone / "quality" / "tests" / Path(__file__).name)
        (clone / ".venv").symlink_to(ROOT / ".venv")
        if (ROOT / ".env").is_file():
            (clone / ".env").symlink_to(ROOT / ".env")
    selection = " or ".join(f"test_{name}" for name in CHAIN)
    children = []
    for clone in clones:
        sink = (scratch / f"concurrent-{clone.name}.out").open("wb")
        argv = [
            str(clone / ".venv" / "bin" / "python"),
            "-m",
            "pytest",
            "quality/tests/test_reap.py",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "-q",
            "-s",
            "-k",
            selection,
        ]
        children.append(
            (
                clone,
                sink,
                subprocess.Popen(argv, cwd=clone, stdout=sink, stderr=subprocess.STDOUT, env=env),
            )
        )
    logs = {}
    for clone, sink, child in children:
        rc = child.wait()
        sink.close()
        logs[clone.name] = (
            rc,
            (scratch / f"concurrent-{clone.name}.out").read_text(errors="replace"),
        )
    identities = {
        name: next(iter(re.findall(r"^scratch identity (\S+) ", text, re.MULTILINE)), "")
        for name, (_, text) in logs.items()
    }
    assert all(identities.values()), f"a child printed no scratch identity: {identities}"
    assert identities["clone-a"] != identities["clone-b"], identities
    for name, (rc, text) in logs.items():
        other = identities["clone-b" if name == "clone-a" else "clone-a"]
        if rc == 2:
            raise CouldNotLook(
                f"the nested run in {name} could not look:\n" + "\n".join(text.splitlines()[-30:])
            )
        assert rc == 0, f"{name} exited {rc}:\n" + "\n".join(text.splitlines()[-40:])
        assert other not in text, f"{name} named the OTHER run's identity {other}"
