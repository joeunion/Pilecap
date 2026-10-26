"""The compose floor: what both compose files carry, asserted over the render, never the source.

does-not-cover: whether the sink writes where upstream says — a version bump can move a path.
does-not-cover: retention on a namespace that already exists; that property is the box's.
does-not-cover: whether any of it boots — a render proves shape; boot and health are staging's.
does-not-cover: backup — a named volume is findable and durable, not a copy.
does-not-cover: an overlay beyond `deploy/compose.second.yaml`, a third `-f` on a command line.
does-not-cover: whether the daemon honours the log cap, or whether 50m × 5 is the right size.
does-not-cover: whether the privilege split boots, or the UID an image picks with no `user:`.
"""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.deploy_scaffold import DeployScaffold, environ_without_dotenv
from quality.tests.fixtures.env_strip import STRIPPED
from quality.tests.fixtures.scratch import require_scratch
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "compose.yaml",
    "deploy/compose.yaml",
    "deploy/compose.second.yaml",
    "deploy/provision.sh",
    "deploy/envfile.py",
    "deploy/tests/scaffold.sh",
    "deploy/env.staging.example",
    "deploy/env.prod.example",
    "deploy/pool_budget.py",
    "deploy/entrypoint.sh",
    "Dockerfile",
    ".env.example",
    "manage.py",
    "scripts/tests/drive_preamble.sh",
)

ROOT = Path(__file__).resolve().parents[3]
BOX_FILE = ROOT / "deploy" / "compose.yaml"
LAPTOP_FILE = ROOT / "compose.yaml"
SECOND_FILE = ROOT / "deploy" / "compose.second.yaml"
STAGING_MANIFEST = ROOT / "deploy" / "env.staging.example"
DOCKERFILE = ROOT / "Dockerfile"
ENTRYPOINT = ROOT / "deploy" / "entrypoint.sh"
POOL_BUDGET = ROOT / "deploy" / "pool_budget.py"
EDGE = "10.213.7.0/24"
FORWARDED_FLAG = "--forwarded-allow-ips"
HASH_STUB = "$2a$14$" + "stub" * 5 + "stuO" + "stub" * 7 + "stu"
DOCKER_STUB = f"""#!/usr/bin/env bash
case "$*" in *hash-password*) echo '{HASH_STUB}' ;; esac
exit 0
"""

SINK_PATHS = ("/data/db", "/var/lib/clickhouse", "/var/log/clickhouse-server")
LOG_CAP = ("json-file", "50m", "5")
LOG_SERVICE_FLOOR = 10
ZITADEL_RUNNING = "zitadel"
ADMIN_PREFIX = "ZITADEL_DATABASE_POSTGRES_ADMIN_"
FIRST_PREFIX = "ZITADEL_FIRSTINSTANCE_"
BOOTSTRAP_TARGET = "/zitadel/bootstrap"
BOOTSTRAP_VOLUME = "zitadel_bootstrap"
PAT_KEY = "ZITADEL_FIRSTINSTANCE_PATPATH"
PAT_PATH = "/zitadel/bootstrap/machine.pat"
COLD_START_WORDS = ("start-from-init", "start-from-setup")
ROOT_USERS = ("0", "root", "0:0", "root:root")
ORG_KEY = "ZITADEL_FIRSTINSTANCE_ORG_NAME"
MACHINE_KEY = "ZITADEL_FIRSTINSTANCE_ORG_MACHINE_MACHINE_NAME"
ZITADEL_MAX_OPEN = "ZITADEL_DATABASE_POSTGRES_MAXOPENCONNS"
ZITADEL_MAX_IDLE = "ZITADEL_DATABASE_POSTGRES_MAXIDLECONNS"
RDS_MAX_CONNECTIONS, RDS_OWN, OPERATOR_HEADROOM = 79, 7, 8
#: postgres:18's own `max_connections` and reserved slots: the compose db sets neither.
COMPOSE_PG_MAX_CONNECTIONS, COMPOSE_PG_OWN = 100, 3
WEB_BOX_SERVICES = ("web", "worker", "frontend", "caddy")
TEMPORAL_ROLES, ZITADEL_UNBOUNDED = 4, 2
SURFACE_STAFF, SURFACE_OTHER, SURFACE_UNKEYED_KEY = "a.example", "b.example", "customer"
SURFACE_ADAPT_HASH = "$2a$14$abcdefghijklmnopqrstuuabcdefghijklmnopqrstuvwxyz01234"
SLOT = re.compile(r"\$\{([A-Z0-9_]*):\?")
PLANT = '  {name}:\n    image: busybox:1.37.0\n    command: ["true"]\n'


@pytest.fixture(scope="module")
def pool_budget() -> ModuleType:
    """`deploy/pool_budget.py`, loaded by path: `deploy/` holds scripts, not a package."""
    spec = importlib.util.spec_from_file_location("pool_budget_under_test", POOL_BUDGET)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def environ(*unset: str) -> dict[str, str]:
    """The environment a render runs under: no `.env` name, no stripped name, none of `unset`."""
    gone = set(STRIPPED) | set(unset)
    return {k: v for k, v in environ_without_dotenv(ROOT).items() if k not in gone}


def derive_env(compose_file: Path, out: Path, *extra: str) -> Path:
    """Every `${NAME:?…}` slot in the file answered with a dummy, then `extra` lines."""
    names = sorted(set(SLOT.findall(compose_file.read_text())))
    lines = [f"{name}=compose-floor-dummy" for name in names] + list(extra)
    out.write_text("".join(f"{line}\n" for line in lines))
    return out


def profiles(files: list[Path], env_file: Path) -> list[str]:
    """`--profile <p>` for every profile compose says the files declare."""
    args = [a for f in files for a in ("-f", str(f))]
    listed = subprocess.run(
        ["docker", "compose", *args, "--env-file", str(env_file), "config", "--profiles"],
        capture_output=True, text=True, env=environ(),
    ).stdout  # fmt: skip
    return [a for p in listed.split() for a in ("--profile", p)]


def render(files: list[Path], env_file: Path, out: Path, *more: str) -> int:
    """`docker compose … config --format json` into `out` (stderr beside it); its exit."""
    args = [a for f in files for a in ("-f", str(f))]
    with out.open("wb") as sink, Path(f"{out}.err").open("wb") as err:
        done = subprocess.run(
            ["docker", "compose", *args, "--env-file", str(env_file), *more, "config", "--format",
             "json"],
            stdout=sink, stderr=err, env=environ(),
        )  # fmt: skip
    return done.returncode


def load(path: Path) -> dict[str, Any]:
    """A render, as JSON."""
    data: dict[str, Any] = json.loads(path.read_text())
    return data


def services(rendered: Mapping[str, Any]) -> dict[str, Any]:
    """The render's services."""
    found: dict[str, Any] = rendered.get("services", {})
    return found


def env_value(rendered: Mapping[str, Any], service: str, key: str) -> str:
    """One env value off the render, or a word saying what was missing."""
    block = services(rendered).get(service)
    if block is None:
        return "MISSING-SERVICE"
    return str((block.get("environment") or {}).get(key, "MISSING-KEY"))


def sink_missing(rendered: Mapping[str, Any], service: str) -> list[str]:
    """The sink paths NOT mounted as a declared named volume on `service`."""
    declared = set(rendered.get("volumes") or {})
    mounts = services(rendered).get(service, {}).get("volumes") or []
    held = {
        m.get("target") for m in mounts if m.get("type") == "volume" and m.get("source") in declared
    }
    return [path for path in SINK_PATHS if path not in held]


def log_census(rendered: Mapping[str, Any]) -> tuple[int, list[str]]:
    """(every service in the render, the names of those not asking for the whole cap)."""
    uncapped = []
    for name in sorted(services(rendered)):
        block = services(rendered)[name].get("logging") or {}
        options = block.get("options") or {}
        got = (block.get("driver", "-"), str(options.get("max-size", "-")),
               str(options.get("max-file", "-")))  # fmt: skip
        if got != LOG_CAP:
            uncapped.append(name)
    return len(services(rendered)), uncapped


def env_keys(rendered: Mapping[str, Any], service: str, prefix: str) -> list[str]:
    """The env keys of `service` under `prefix`, sorted."""
    env = services(rendered).get(service, {}).get("environment") or {}
    return sorted(key for key in env if key.startswith(prefix))


def plant_service(source: Path, copy: Path, name: str) -> None:
    """A copy of `source` with a service `name` and no `logging:` after its `services:` line."""
    lines, planted = [], False
    for line in source.read_text().splitlines(keepends=True):
        lines.append(line)
        if not planted and line.rstrip("\n") == "services:":
            lines.append(PLANT.format(name=name))
            planted = True
    if not planted:
        raise CouldNotLook(f"{source} has no top-level 'services:' line — nothing to plant into")
    copy.write_text("".join(lines))


@dataclass(frozen=True)
class Renders:
    """The three renders the cases read, taken once: box, laptop (observability), box (all)."""

    work: Path
    box_env: Path

    def box(self) -> dict[str, Any]:
        """The box file, bare."""
        return load(self.work / "box.json")

    def laptop(self) -> dict[str, Any]:
        """The laptop file under `--profile observability`."""
        return load(self.work / "laptop.json")

    def box_all(self) -> dict[str, Any]:
        """The box file under every profile it declares."""
        return load(self.work / "box-all.json")


@pytest.fixture(scope="module")
def renders(tmp_path_factory: pytest.TempPathFactory) -> Renders:
    """The renders every case reads; could-not-look when docker or a file cannot render."""
    if shutil.which("docker") is None:
        raise CouldNotLook("no docker on PATH — the render is docker compose's own")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        raise CouldNotLook("docker is on PATH but 'docker compose' does not answer")
    for needed in (BOX_FILE, LAPTOP_FILE, STAGING_MANIFEST):
        if not needed.is_file():
            raise CouldNotLook(f"{needed.relative_to(ROOT)} is not in this tree")
    work = require_scratch(tmp_path_factory.mktemp("compose-floor"), ROOT).resolve()
    box_env = derive_env(BOX_FILE, work / "box.env")
    laptop_env = derive_env(LAPTOP_FILE, work / "laptop.env")
    for files, env_file, out, more in (
        ([BOX_FILE], box_env, "box.json", []),
        ([LAPTOP_FILE], laptop_env, "laptop.json", ["--profile", "observability"]),
        ([BOX_FILE], box_env, "box-all.json", profiles([BOX_FILE], box_env)),
    ):
        rc = render(files, env_file, work / out, *more)
        if rc != 0:
            said = Path(f"{work / out}.err").read_text()
            raise CouldNotLook(f"{files[0].name} does not render ({out}, exit {rc}): {said}")
    return Renders(work, box_env)


@pytest.fixture
def work(scratch: Path) -> Path:
    """The case's own directory for copies and renders, resolved."""
    return scratch.resolve()


def test_the_sink_persists_clickhouse_data_and_logs_on_the_box(renders: Renders) -> None:
    assert sink_missing(renders.box(), "clickstack") == []


def test_the_sink_persists_clickhouse_data_and_logs_on_the_laptop(renders: Renders) -> None:
    assert sink_missing(renders.laptop(), "clickstack") == []


def test_a_copy_with_the_column_store_unmounted_reds_the_census(
    renders: Renders, work: Path
) -> None:
    source = BOX_FILE.read_text().splitlines(keepends=True)
    assert any("/var/lib/clickhouse" in line for line in source), "nothing to remove"
    copy = work / "copy-compose.yaml"
    copy.write_text(
        "".join(x for x in source if not x.rstrip("\n").endswith("/var/lib/clickhouse"))
    )
    assert render([copy], renders.box_env, work / "copy.json") == 0
    assert sink_missing(load(work / "copy.json"), "clickstack") == ["/var/lib/clickhouse"]


def test_namespace_retention_defaults_to_thirty_days(renders: Renders) -> None:
    assert env_value(renders.box(), "temporal", "DEFAULT_NAMESPACE_RETENTION") == "720h"


def test_namespace_retention_reads_the_manifest_slot(renders: Renders, work: Path) -> None:
    env_file = derive_env(BOX_FILE, work / "box-48h.env", "TEMPORAL_NAMESPACE_RETENTION=48h")
    assert render([BOX_FILE], env_file, work / "box-48h.json") == 0
    assert (
        env_value(load(work / "box-48h.json"), "temporal", "DEFAULT_NAMESPACE_RETENTION") == "48h"
    )


def test_the_manifest_carries_the_retention_slot() -> None:
    lines = [x for x in STAGING_MANIFEST.read_text().splitlines()
             if x.startswith("TEMPORAL_NAMESPACE_RETENTION=")]  # fmt: skip
    assert lines == ["TEMPORAL_NAMESPACE_RETENTION=720h"], lines


def test_both_compose_files_still_validate(renders: Renders) -> None:
    assert renders.box() and renders.laptop()


def test_every_service_on_the_box_rotates_its_logs(renders: Renders) -> None:
    total, uncapped = log_census(renders.box_all())
    assert total >= LOG_SERVICE_FLOOR, f"{total} services, below the floor {LOG_SERVICE_FLOOR}"
    assert uncapped == [], f"uncapped: {uncapped}"
    anchors = [x for x in BOX_FILE.read_text().splitlines() if x.startswith("x-logging:")]
    assert len(anchors) == 1


def test_a_planted_service_without_logging_reds_the_census(renders: Renders, work: Path) -> None:
    copy = work / "planted-compose.yaml"
    plant_service(BOX_FILE, copy, "planted-without-logging")
    rc = render([copy], renders.box_env, work / "planted.json", *profiles([copy], renders.box_env))
    assert rc == 0
    total, uncapped = log_census(load(work / "planted.json"))
    assert (total - len(uncapped), uncapped) == (total - 1, ["planted-without-logging"])


def overlay(renders: Renders, second: Path, out: Path) -> tuple[dict[str, Any], list[str]]:
    """The pair rendered under its own profiles, and the services the overlay adds."""
    pair = [BOX_FILE, second]
    rc = render(pair, renders.box_env, out, *profiles(pair, renders.box_env))
    assert rc == 0, Path(f"{out}.err").read_text()
    rendered = load(out)
    return rendered, sorted(set(services(rendered)) - set(services(renders.box_all())))


def test_the_overlay_adds_no_uncapped_service(renders: Renders, work: Path) -> None:
    if not SECOND_FILE.is_file():
        return
    rendered, _added = overlay(renders, SECOND_FILE, work / "overlay-base.json")
    total, uncapped = log_census(rendered)
    assert total >= LOG_SERVICE_FLOOR
    assert uncapped == [], f"uncapped in the pair: {uncapped}"


def test_a_planted_service_in_the_overlay_reds_the_census(renders: Renders, work: Path) -> None:
    assert SECOND_FILE.is_file(), "no overlay in this tree to plant into"
    copy = work / "planted-overlay.yaml"
    plant_service(SECOND_FILE, copy, "planted-overlay-service")
    rendered, added = overlay(renders, copy, work / "overlay-planted.json")
    _total, uncapped = log_census(rendered)
    assert "planted-overlay-service" in added
    assert "planted-overlay-service" in uncapped


def test_the_running_zitadel_holds_service_creds_only_and_is_not_root(renders: Renders) -> None:
    block = services(renders.box()).get(ZITADEL_RUNNING)
    assert block is not None, f"no {ZITADEL_RUNNING!r} service in the render"
    command = block.get("command")
    command = " ".join(str(p) for p in command) if isinstance(command, list) else command or "-"
    assert command == "start" or command.startswith("start "), command
    assert not [w for w in COLD_START_WORDS if f" {w} " in f" {command} "], command
    assert block.get("user", "-") not in ROOT_USERS
    assert env_keys(renders.box(), ZITADEL_RUNNING, ADMIN_PREFIX) == []
    assert env_keys(renders.box(), ZITADEL_RUNNING, FIRST_PREFIX) == []
    assert "ZITADEL_MASTERKEY" in (block.get("environment") or {})


def chain_to(rendered: Mapping[str, Any], running: str) -> list[str]:
    """Back from `running`, one `service_completed_successfully` edge at a time."""
    chain: list[str] = []
    cursor, seen = running, set()
    while True:
        deps = services(rendered).get(cursor, {}).get("depends_on") or {}
        done = "service_completed_successfully"
        nxt = [n for n, d in deps.items() if isinstance(d, dict) and d.get("condition") == done]
        if len(nxt) != 1 or nxt[0] in seen:
            return chain
        cursor = nxt[0]
        seen.add(cursor)
        chain.append(cursor)


def test_init_and_setup_are_one_shots_and_start_waits_for_them(renders: Renders) -> None:
    rendered = renders.box()
    every = services(rendered)
    assert ZITADEL_RUNNING in every
    image = every[ZITADEL_RUNNING].get("image")
    population = sorted(
        n for n, b in every.items() if n != ZITADEL_RUNNING and b.get("image") == image
    )
    assert population, "no service runs the long-lived service's image under another name"
    wanted = sorted({k for b in every.values() for k in (b.get("environment") or {})
                     if k.startswith(FIRST_PREFIX)})  # fmt: skip
    for name in population:
        block = every[name]
        targets = {m.get("target") for m in block.get("volumes") or []}
        assert str(block.get("restart", "-")) == "no", name
        assert str(block.get("user", "-")) == "0", name
        assert env_keys(rendered, name, ADMIN_PREFIX), name
        assert env_keys(rendered, name, FIRST_PREFIX), name
        assert env_keys(rendered, name, FIRST_PREFIX) == wanted, name
        assert BOOTSTRAP_TARGET in targets, name
    assert sorted(chain_to(rendered, ZITADEL_RUNNING)) == population


def test_the_bootstrap_pat_path_is_unchanged(renders: Renders) -> None:
    rendered = renders.box()
    declared = set(rendered.get("volumes") or {})
    holders = [n for n in sorted(services(rendered))
               if PAT_KEY in (services(rendered)[n].get("environment") or {})]  # fmt: skip
    assert holders, f"no service in the render names {PAT_KEY}"
    for name in holders:
        mounts = services(rendered)[name].get("volumes") or []
        assert any(
            m.get("target") == BOOTSTRAP_TARGET
            and m.get("source") == BOOTSTRAP_VOLUME
            and m.get("source") in declared
            for m in mounts
        ), f"{name} names {PAT_KEY} and does not mount {BOOTSTRAP_VOLUME} at {BOOTSTRAP_TARGET}"
    assert env_value(rendered, holders[0], PAT_KEY) == PAT_PATH


def test_the_zitadel_pool_default_is_the_one_a_login_answered_on(renders: Renders) -> None:
    rendered = renders.box()
    assert env_value(rendered, ZITADEL_RUNNING, ZITADEL_MAX_OPEN) == "20"
    assert env_value(rendered, ZITADEL_RUNNING, ZITADEL_MAX_IDLE) == "5"


def worker_processes(rendered: Mapping[str, Any]) -> int:
    """The worker's process count, read off the render's `deploy.replicas` — never defaulted."""
    return int(services(rendered)["worker"]["deploy"]["replicas"])


def app_ceiling(rendered: Mapping[str, Any], max_connections: int, own: int) -> int:
    """`max_connections` less Temporal's and Zitadel's bounds, the server's own and the headroom."""
    temporal = TEMPORAL_ROLES * sum(
        int(env_value(rendered, "temporal", k)) for k in ("SQL_MAX_CONNS", "SQL_VIS_MAX_CONNS")
    )
    zitadel = int(env_value(rendered, ZITADEL_RUNNING, ZITADEL_MAX_OPEN)) + ZITADEL_UNBOUNDED
    return max_connections - temporal - zitadel - own - OPERATOR_HEADROOM


def app_budget(rendered: Mapping[str, Any]) -> int:
    """web + processes × worker, the per-process sizes read off the settings."""
    from config.settings import base

    sizes = base._POOL_MAX_SIZE_BY_SERVICE
    return sizes["web"] + worker_processes(rendered) * sizes["worker"]


def test_the_worker_runs_as_two_processes_on_one_queue(renders: Renders) -> None:
    """Two replicas, no hostname — temporalio's identity is pid@hostname (temporalio/service.py)."""
    worker = services(renders.box())["worker"]
    assert worker_processes(renders.box()) == 2
    assert "hostname" not in worker and "container_name" not in worker
    assert worker["command"] == ["python", "-m", "apps.workflows.worker"]
    assert "TEMPORAL_TASK_QUEUE" not in (worker.get("environment") or {})


def test_the_web_box_weights_are_weights_never_caps(renders: Renders) -> None:
    every = services(renders.box())
    capped = [name for name in WEB_BOX_SERVICES if "cpus" in every[name]]
    assert capped == [], f"a cpus: cap on {capped}"
    shares = {name: int(every[name]["cpu_shares"]) for name in WEB_BOX_SERVICES}
    assert shares["worker"] > shares["web"] > max(shares["caddy"], shares["frontend"]), shares


def test_the_production_budget_fits_the_compose_postgres(renders: Renders) -> None:
    """The arithmetic `deploy/env.staging.example` states for the production shape's database."""
    rendered = renders.box_all()
    db = services(rendered)["db"]
    assert "max_connections" not in str(db.get("command") or ""), "the ceiling is no longer 100"
    app = app_budget(rendered)
    ceiling = app_ceiling(rendered, COMPOSE_PG_MAX_CONNECTIONS, COMPOSE_PG_OWN)
    assert app <= ceiling, f"web + processes × worker {app} > ceiling {ceiling}"


def generate(
    work: Path, stub_path: StubPath, name: str, **exported: str
) -> subprocess.CompletedProcess[str]:
    """`provision.sh env-file <work/name> staging` with docker stubbed and `exported` set."""
    if "docker" not in stub_path.planted:
        stub_path.plant("docker", DOCKER_STUB)
    env = {
        **environ("DJB_RDS_CLASS", "DJB_WORKER_PROCESSES", "FORWARDED_ALLOW_IPS"),
        "PATH": f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}",
        "DJB_DOMAIN": "example.test",
        **exported,
    }
    return subprocess.run(
        ["./deploy/provision.sh", "env-file", str(work / name), "staging"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )  # fmt: skip


def generated(path: Path, key: str) -> str:
    """One key off a generated env file, unquoted; `MISSING-KEY` when it is not written."""
    found = [
        x.split("=", 1)[1].strip("'")
        for x in path.read_text().splitlines()
        if x.startswith(f"{key}=")
    ]
    return found[-1] if found else "MISSING-KEY"


def day_one(work: Path, env_file: Path, label: str) -> dict[str, Any]:
    """The box file over a generated env file; a slot it leaves to a later step, a dummy."""
    over = work / f"{label}-render.env"
    filled = [x for x in env_file.read_text().splitlines(keepends=True) if not x.endswith("=''\n")]
    over.write_text(derive_env(BOX_FILE, over).read_text() + "".join(filled))
    assert render([BOX_FILE], over, work / f"{label}.json") == 0, label
    return load(work / f"{label}.json")


def test_the_env_file_derives_the_worker_count_from_the_class(
    work: Path, stub_path: StubPath, pool_budget: ModuleType
) -> None:
    """`db.t4g.micro` (the class `infra` creates by default) holds 1; a larger class the ruled 2."""
    micro = generate(work, stub_path, "micro.env")
    assert micro.returncode == 0, micro.stdout + micro.stderr
    assert generated(work / "micro.env", "DJB_RDS_CLASS") == "db.t4g.micro"
    assert generated(work / "micro.env", "DJB_WORKER_PROCESSES") == "1"
    small = generate(work, stub_path, "small.env", DJB_RDS_CLASS="db.t4g.small")
    assert small.returncode == 0, small.stdout + small.stderr
    want = str(pool_budget.workers("db.t4g.small"))
    assert generated(work / "small.env", "DJB_WORKER_PROCESSES") == want == "2"
    off = generate(work, stub_path, "off.env", DJB_RDS_CLASS="db.r6g.large")
    assert off.returncode == 2, off.stdout + off.stderr
    assert "deploy/pool_budget.py CLASSES" in off.stderr, off.stderr
    assert not (work / "off.env").exists()


def test_the_literal_day_one_deploy_fits_the_smallest_instance(
    work: Path, stub_path: StubPath, pool_budget: ModuleType
) -> None:
    """The env file `env-file` writes at the default class, rendered: web + n × worker ≤ 18."""
    made = generate(work, stub_path, "day-one.env")
    assert made.returncode == 0, made.stdout + made.stderr
    rendered = day_one(work, work / "day-one.env", "day-one")
    assert worker_processes(rendered) == pool_budget.workers("db.t4g.micro")
    app = app_budget(rendered)
    ceiling = app_ceiling(rendered, RDS_MAX_CONNECTIONS, RDS_OWN)
    assert app <= ceiling, f"web + processes × worker {app} > ceiling {ceiling}"


def test_the_pool_table_restates_the_render_and_the_settings(
    renders: Renders, pool_budget: ModuleType
) -> None:
    """Every bound `deploy/pool_budget.py` sums is the one the render and the settings carry."""
    from config.settings import base

    rendered = renders.box()
    temporal = TEMPORAL_ROLES * sum(
        int(env_value(rendered, "temporal", k)) for k in ("SQL_MAX_CONNS", "SQL_VIS_MAX_CONNS")
    )
    zitadel = int(env_value(rendered, ZITADEL_RUNNING, ZITADEL_MAX_OPEN)) + ZITADEL_UNBOUNDED
    sizes = base._POOL_MAX_SIZE_BY_SERVICE
    assert (pool_budget.TEMPORAL, pool_budget.ZITADEL) == (temporal, zitadel)
    assert pool_budget.OPERATOR_HEADROOM == OPERATOR_HEADROOM
    assert (pool_budget.WEB, pool_budget.WORKER) == (sizes["web"], sizes["worker"])
    assert pool_budget.RULED_WORKERS == worker_processes(rendered)
    assert pool_budget.CLASSES["db.t4g.micro"] == (RDS_MAX_CONNECTIONS, RDS_OWN)
    assert pool_budget.CLASSES["compose"] == (COMPOSE_PG_MAX_CONNECTIONS, COMPOSE_PG_OWN)
    for db_class, (max_connections, own) in pool_budget.CLASSES.items():
        held = pool_budget.WEB + pool_budget.workers(db_class) * pool_budget.WORKER
        assert held <= app_ceiling(rendered, max_connections, own), db_class


def trust_problems(rendered: Mapping[str, Any]) -> list[str]:
    """Why web would believe X-Forwarded-For from a peer other than this stack's network."""
    problems = []
    trusted = env_value(rendered, "web", "FORWARDED_ALLOW_IPS")
    subnets = [
        c.get("subnet")
        for c in (rendered.get("networks") or {}).get("default", {}).get("ipam", {}).get("config")
        or []
    ]
    if "*" in trusted or trusted.startswith("MISSING"):
        problems.append(f"web's FORWARDED_ALLOW_IPS is {trusted!r}")
    if subnets != [trusted]:
        problems.append(
            f"the network's declared subnets {subnets} are not web's trusted {trusted!r}"
        )
    else:
        try:
            ipaddress.ip_network(trusted)
        except ValueError:
            problems.append(f"{trusted!r} is not a network")
    web_cmd = " ".join(services(rendered)["web"].get("command") or [])
    image_cmd = next(
        (x for x in DOCKERFILE.read_text().splitlines() if x.startswith("CMD") and "uvicorn" in x),
        "",
    )
    for where, line in (
        ("deploy/compose.yaml web command", web_cmd),
        ("Dockerfile CMD", image_cmd),
    ):
        if FORWARDED_FLAG in line:
            problems.append(f"{where} types {FORWARDED_FLAG}, which outranks the env's one value")
    if not image_cmd:
        problems.append("the Dockerfile has no uvicorn CMD to read")
    return problems


def test_uvicorn_trusts_only_the_proxy(work: Path) -> None:
    """One declared value — the network's subnet — both web and the network read; never `*`."""
    good = derive_env(BOX_FILE, work / "edge.env", f"FORWARDED_ALLOW_IPS={EDGE}")
    assert render([BOX_FILE], good, work / "edge.json") == 0
    assert trust_problems(load(work / "edge.json")) == []
    star = derive_env(BOX_FILE, work / "star.env", "FORWARDED_ALLOW_IPS=*")
    assert render([BOX_FILE], star, work / "star.json") == 0
    assert trust_problems(load(work / "star.json")) != []
    unset = derive_env(BOX_FILE, work / "unset.env")
    lines = [
        x
        for x in unset.read_text().splitlines(keepends=True)
        if not x.startswith("FORWARDED_ALLOW_IPS=")
    ]
    unset.write_text("".join(lines))
    rc = render([BOX_FILE], unset, work / "unset.json")
    assert (
        rc != 0
        and "FORWARDED_ALLOW_IPS is required" in Path(f"{work / 'unset.json'}.err").read_text()
    )


def boot(work: Path, label: str, *lines: str) -> subprocess.CompletedProcess[str]:
    """`deploy/entrypoint.sh true` over a file source holding `lines`, in a bare environment."""
    source = work / f"{label}.env"
    source.write_text("".join(f"{line}\n" for line in lines))
    env = {"PATH": os.environ["PATH"], "HOME": str(work), "DJB_SECRETS_SOURCE": f"file:{source}"}
    return subprocess.run(
        ["bash", str(ENTRYPOINT), "true"], capture_output=True, text=True, env=env
    )


def test_the_boot_refuses_a_proxy_it_would_not_believe(work: Path) -> None:
    """BEHIND_PROXY=1 travels with FORWARDED_ALLOW_IPS, and `*` is refused."""
    if shutil.which("bash") is None:
        raise CouldNotLook("no bash on PATH — the entrypoint is bash")
    bare = boot(work, "bare", "BEHIND_PROXY=1")
    assert bare.returncode == 2 and "FORWARDED_ALLOW_IPS is unset" in bare.stderr, bare.stderr
    star = boot(work, "star", "BEHIND_PROXY=1", "FORWARDED_ALLOW_IPS='*'")
    assert star.returncode == 2 and "never '*'" in star.stderr, star.stderr
    edge = boot(work, "edge", "BEHIND_PROXY=1", f"FORWARDED_ALLOW_IPS={EDGE}")
    assert edge.returncode == 0, edge.stderr
    off = boot(work, "off", "BEHIND_PROXY=0")
    assert off.returncode == 0, off.stderr


def test_a_copy_with_the_master_credential_back_on_the_long_lived_zitadel_reds_the_census(
    renders: Renders, work: Path
) -> None:
    admin, first = f"{ADMIN_PREFIX}PASSWORD", f"{FIRST_PREFIX}ORG_HUMAN_PASSWORD"
    env = services(renders.box()).get(ZITADEL_RUNNING, {}).get("environment") or {}
    assert admin not in env and first not in env, "already held — this control cannot speak"
    out, inside, done = [], False, False
    for line in BOX_FILE.read_text().splitlines(keepends=True):
        bare = line.rstrip("\n")
        if bare == f"  {ZITADEL_RUNNING}:":
            inside = True
        elif re.match(r"^  [a-zA-Z]", bare):
            inside = False
        out.append(line)
        if inside and not done and bare.startswith("    environment:"):
            out.append(f"      {admin}: planted-master-credential\n")
            out.append(f"      {first}: planted-console-credential\n")
            done = True
    assert done, f"no '  {ZITADEL_RUNNING}:' service with an 'environment:' block to plant into"
    copy = work / "mastercred-compose.yaml"
    copy.write_text("".join(out))
    assert render([copy], renders.box_env, work / "mastercred.json") == 0
    planted = load(work / "mastercred.json")
    assert admin in env_keys(planted, ZITADEL_RUNNING, ADMIN_PREFIX)
    assert first in env_keys(planted, ZITADEL_RUNNING, FIRST_PREFIX)


def test_the_product_name_reaches_the_first_instance(work: Path) -> None:
    named = {
        "acme": (("PRODUCT_NAME=Acme", "ZITADEL_ORG_NAME="), "Acme"),
        "legal": (("PRODUCT_NAME=Acme", "ZITADEL_ORG_NAME=Legal"), "Legal"),
    }
    for label, (extra, want_org) in named.items():
        env_file = derive_env(BOX_FILE, work / f"box-name-{label}.env", *extra)
        out = work / f"box-name-{label}.json"
        assert render([BOX_FILE], env_file, out) == 0, label
        assert "Pilecap" not in out.read_text(), label
        rendered = load(out)
        holders = [n for n, b in services(rendered).items()
                   if ORG_KEY in (b.get("environment") or {})]  # fmt: skip
        assert holders, label
        for service in holders:
            got = (env_value(rendered, service, ORG_KEY), env_value(rendered, service, MACHINE_KEY))
            assert got == (want_org, "Acme platform service account"), (label, service, got)

    env_file = work / "box-name-neither.env"
    lines = derive_env(BOX_FILE, env_file).read_text().splitlines(keepends=True)
    env_file.write_text("".join(x for x in lines if not x.startswith("PRODUCT_NAME=")))
    out = work / "box-name-neither.json"
    rc = render([BOX_FILE], env_file, out)
    assert rc != 0 and "PRODUCT_NAME is required" in Path(f"{out}.err").read_text(), rc


def settings_product_name(value: str) -> str:
    """The settings' `PRODUCT_NAME` with the name exported as the generated file carries it."""
    done = subprocess.run(
        ["uv", "run", "python", "manage.py", "shell", "-c",
         'from django.conf import settings; print("product=" + settings.PRODUCT_NAME)'],
        cwd=ROOT, capture_output=True, text=True,
        env={**environ("ZITADEL_ORG_NAME", "ZITADEL_PROJECT_NAME"), "PRODUCT_NAME": value},
    )  # fmt: skip
    found = [
        x.removeprefix("product=") for x in done.stdout.splitlines() if x.startswith("product=")
    ]
    return found[0] if found else ""


def test_the_generator_leaves_the_names_to_product_name(work: Path) -> None:
    if shutil.which("uv") is None:
        raise CouldNotLook("no uv on PATH — the settings half of this case could not look")
    unset = ("PRODUCT_NAME", "ZITADEL_ORG_NAME", "ZITADEL_PROJECT_NAME")
    generated = work / "generated-staging.env"
    gen = subprocess.run(
        ["./deploy/provision.sh", "env-file", str(generated), "staging"],
        cwd=ROOT, capture_output=True, text=True,
        env={**environ(*unset), "DJB_DOMAIN": "example.test"},
    )  # fmt: skip
    assert gen.returncode == 0, gen.stdout + gen.stderr
    example = subprocess.run(
        ["python3", "deploy/envfile.py", "get", ".env.example", "PRODUCT_NAME"],
        cwd=ROOT, capture_output=True, text=True, env=environ(*unset),
    ).stdout.strip()  # fmt: skip
    lines = generated.read_text().splitlines()
    for key in ("ZITADEL_ORG_NAME", "ZITADEL_PROJECT_NAME"):
        assert f"{key}=''" in lines, key
    assert example and f"PRODUCT_NAME='{example}'" in lines, example
    org_line = next(x for x in lines if x.startswith("ZITADEL_ORG_NAME="))
    for label, name in (("generated", example), ("acme", "Acme")):
        env_file = derive_env(
            BOX_FILE, work / f"gen-{label}.env", f"PRODUCT_NAME='{name}'", org_line
        )
        assert render([BOX_FILE], env_file, work / f"gen-{label}.json") == 0, label
        rendered = load(work / f"gen-{label}.json")
        got = (
            env_value(rendered, "zitadel-setup", ORG_KEY),
            env_value(rendered, "zitadel-setup", MACHINE_KEY),
            settings_product_name(name),
        )
        assert got == (name, f"{name} platform service account", name), (label, got)


def test_the_generator_refuses_a_product_with_no_name(
    work: Path, deploy_scaffold: DeployScaffold
) -> None:
    tree = work / "nameless"
    (tree / "bin").mkdir(parents=True)
    shutil.copytree(ROOT / "deploy", tree / "deploy", symlinks=True)
    (tree / "deploy" / ".env").unlink(missing_ok=True)
    deploy_scaffold.into(tree)
    (tree / ".env.example").write_text("PRODUCT_NAME=\n")
    stub = tree / "bin" / "docker"
    stub.write_text(
        '#!/bin/sh\necho "$2a$14$stubstubstubstubstubstuOstubstubstubstubstubstubstubstu"\n'
    )
    stub.chmod(0o755)
    gen = subprocess.run(
        [str(tree / "deploy" / "provision.sh"), "env-file", str(tree / "out.env"), "laptop"],
        capture_output=True, text=True,
        env={**environ(), "PATH": f"{tree / 'bin'}:{os.environ['PATH']}"},
    )  # fmt: skip
    said = gen.stdout + gen.stderr
    assert gen.returncode != 0, said
    assert "PRODUCT_NAME" in said
    assert not (tree / "out.env").exists()


def test_two_surface_addresses_render_one_site_block_and_the_hosts_map(work: Path) -> None:
    unset = ("SURFACE_ADDRESSES", "SURFACE_HOSTS", "SURFACE_SITE_ADDRESSES", "SITE_ADDRESS")
    site = f"SITE_ADDRESS={SURFACE_STAFF}"
    two = derive_env(BOX_FILE, work / "surfaces-two.env", site,
                     f"SURFACE_ADDRESSES={SURFACE_STAFF},{SURFACE_OTHER}")  # fmt: skip
    none = derive_env(BOX_FILE, work / "surfaces-none.env", site, "SURFACE_ADDRESSES=")
    never = derive_env(BOX_FILE, work / "surfaces-never.env", site)
    for env_file in (two, none):
        done = subprocess.run(
            ["./deploy/provision.sh", "surfaces", str(env_file)],
            cwd=ROOT, capture_output=True, text=True, env=environ(*unset),
        )  # fmt: skip
        assert done.returncode == 0, done.stdout + done.stderr
    want_map = f"staff={SURFACE_STAFF},{SURFACE_UNKEYED_KEY}={SURFACE_OTHER}"
    assert f"SURFACE_HOSTS='{want_map}'" in two.read_text().splitlines()
    assert "SURFACE_HOSTS=''" in none.read_text().splitlines()

    for env_file in (two, none, never):
        assert render([BOX_FILE], env_file, work / f"{env_file.stem}.json") == 0, env_file.name
    rendered = load(work / "surfaces-two.json")
    names = env_value(rendered, "caddy", "SITE_ADDRESS")
    assert names == f"{SURFACE_STAFF}, {SURFACE_OTHER}"
    probe = " ".join(services(rendered)["web"]["healthcheck"]["test"])
    assert f"Host: {SURFACE_STAFF} " in probe, probe
    assert (work / "surfaces-none.json").read_bytes() == (work / "surfaces-never.json").read_bytes()

    image = next(
        x.split()[1] for x in BOX_FILE.read_text().splitlines() if re.match(r"^\s+image: caddy:", x)
    )
    adapt = subprocess.run(
        ["docker", "run", "--rm", "-e", f"SITE_ADDRESS={names}",
         "-e", f"AUTH_ADDRESS=auth.{SURFACE_STAFF}", "-e", f"O11Y_ADDRESS=o11y.{SURFACE_STAFF}",
         "-e", "CADDY_TLS=internal", "-e", "O11Y_USER=observer",
         "-e", f"O11Y_PASSWORD_HASH={SURFACE_ADAPT_HASH}",
         "-v", f"{ROOT / 'deploy' / 'Caddyfile'}:/etc/caddy/Caddyfile:ro", image,
         "caddy", "adapt", "--config", "/etc/caddy/Caddyfile"],
        capture_output=True, text=True, env=environ(*unset),
    )  # fmt: skip
    assert adapt.returncode == 0, adapt.stderr[-500:]
    config = json.loads(adapt.stdout)
    hosts = [
        " ".join(match["host"])
        for server in config["apps"]["http"]["servers"].values()
        for route in server.get("routes", [])
        for match in route.get("match", [])
        if SURFACE_STAFF in match.get("host", [])
    ]
    assert hosts == [f"{SURFACE_STAFF} {SURFACE_OTHER}"], hosts
    offered = {
        name: server.get("protocols") for name, server in config["apps"]["http"]["servers"].items()
    }
    assert all(p == ["h1", "h2"] for p in offered.values()), (
        f"h3 offered on a tcp-only SG: {offered}"
    )


def test_no_registered_deploy_drive_calls_itself_hand_run() -> None:
    from quality.djb.drive_table import DRIVES

    registered = [d.path for d in DRIVES if d.path.startswith("deploy/tests/")]
    offenders = []
    for drive in registered:
        path = ROOT / drive
        if not path.is_file():
            continue
        head = path.read_text().splitlines()[:40]
        if any(re.search(r"HAND-RUN|No gate moment", line) for line in head):
            offenders.append(drive)
    assert offenders == [], offenders
