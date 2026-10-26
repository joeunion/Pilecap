"""Every pooled connection names its process class in `pg_stat_activity` (ADR config-1)."""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook

ROOT = Path(__file__).resolve().parents[3]
PY = ROOT / ".venv/bin/python"

# A child sets Django up (this member runs `-p no:django`) and asks the server's own `postgres`.
SHOW = """\
import django
django.setup()
from config.settings import base
from django.db import connection
from django.db.utils import ConnectionHandler
assembled = base.DATABASES["default"]
assert "pool" in assembled["OPTIONS"], "the deployment's assembly is not pooled"
handler = ConnectionHandler({
    "default": {"ENGINE": "django.db.backends.dummy"},
    "probe": {**assembled, "NAME": "postgres"},
})
wrapper = handler["probe"]
try:
    with wrapper.cursor() as cursor:
        cursor.execute("SHOW application_name")
        print("pooled=" + str(cursor.fetchone()[0]))
finally:
    wrapper.close()
    wrapper.close_pool()
with connection._nodb_cursor() as cursor:
    cursor.execute("SHOW application_name")
    print("suite=" + str(cursor.fetchone()[0]))
"""


def _show(service: str) -> dict[str, str]:
    """`SHOW application_name` on a pooled deployment connection and the suite's own."""
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DJB_SERVICE_NAME": service,
        "DATABASE_POOL_ENABLED": "true",
        "DATABASE_URL": "",
        "DJB_DISABLED_APPS": "example",
    }
    done = subprocess.run(
        [str(PY), "-c", SHOW], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120
    )
    if done.returncode != 0:
        raise CouldNotLook(f"no database answered (docker compose up -d db): {done.stderr[-800:]}")
    return dict(line.split("=", 1) for line in done.stdout.splitlines() if "=" in line)


@pytest.mark.parametrize("service", ["web", "worker"])
def test_every_pooled_connection_carries_its_service_name(service: str) -> None:
    named = _show(service)
    expected = f"{service}@{socket.gethostname()}"[:63]
    assert named["pooled"].startswith(f"{service}@"), named
    assert named["pooled"] == expected
    assert named["suite"] == expected
