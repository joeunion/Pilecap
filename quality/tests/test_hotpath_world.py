"""Rule 35's `_hp` world is rebuilt when a removed app left it stale; a dead probe names a cure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from quality.checks.rule_35 import hot_path_sargability

ROOT = Path(__file__).resolve().parents[2]

#: An index core's 0009 migration creates; Postgres index names are schema-global.
COLLIDING_INDEX = "organization_path_prefix"
GONE_LABEL = "zzzhpgone"


#: The harness runs without Django settings, so SQL runs through the probe's `connect` in a child.
_RUN_SQL = (
    "import sys, django; django.setup()\n"
    "from quality.hotpath_probe import connect\n"
    "with connect(sys.argv[1]) as db:\n"
    "    for statement in sys.argv[2:]:\n"
    "        db.execute(statement)\n"
)
_ENV = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"}


def _sql(dbname: str, *statements: str) -> None:
    subprocess.run(
        [sys.executable, "-c", _RUN_SQL, dbname, *statements],
        cwd=ROOT,
        env=_ENV,
        check=True,
        capture_output=True,
        timeout=120,
    )


@pytest.fixture
def stale_world() -> Iterator[tuple[str, str]]:
    """A scratch `_hp` world holding a removed app's table, index and migration row."""
    base = f"djb_hpstale_{uuid.uuid4().hex[:8]}"
    name = f"{base}_hp"
    _sql("postgres", f'CREATE DATABASE "{name}"')
    try:
        _sql(
            name,
            "CREATE TABLE django_migrations (id bigserial PRIMARY KEY, app varchar(255) "
            "NOT NULL, name varchar(255) NOT NULL, applied timestamptz NOT NULL)",
            "INSERT INTO django_migrations (app, name, applied) "  # noqa: S608 — a fixed INSERT whose values are bound parameters
            f"VALUES ('{GONE_LABEL}', '0001_initial', now())",
            f"CREATE TABLE {GONE_LABEL}_gear (id integer)",
            f"CREATE INDEX {COLLIDING_INDEX} ON {GONE_LABEL}_gear (id)",
        )
        yield base, name
    finally:
        _sql("postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_a_stale_world_is_rebuilt_and_the_probe_binds(stale_world: tuple[str, str]) -> None:
    base, name = stale_world
    proc = subprocess.run(
        [sys.executable, str(ROOT / "quality" / "hotpath_probe.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**_ENV, "DATABASE_NAME": base},
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    assert report["probed"] > 0
    assert report["rebuilt"] == (
        f"hot-path world {name} was stale ({GONE_LABEL} is no longer in the tree) — rebuilt"
    )
    assert report["rebuilt"] in proc.stderr


def test_a_probe_that_cannot_run_names_the_cure(tmp_path: Path) -> None:
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality" / "hotpath_probe.py").write_text("import sys\nsys.exit(1)\n")
    result = hot_path_sargability(tmp_path, {"registry": []})
    [finding] = result.findings
    assert "probed_paths" not in result.targets_matched
    assert finding.msg.startswith(
        "the hot-path probe could not run (exit 1) — ./scripts/db_sweep.sh --sweep "
        "--hot-path, then re-run"
    )
