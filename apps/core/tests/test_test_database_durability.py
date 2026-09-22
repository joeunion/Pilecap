"""The test database does not pay for durability — and the dev database still does.

**What this pins.** `config/settings/test.py` puts `-c synchronous_commit=off`
into the libpq `options` of every connection the suite opens, because a test
database is a throwaway and the per-test `TRUNCATE … RESTART IDENTITY CASCADE`
flush was measured at 529 of the suite's 1733 serial seconds (SCOUT-TESTS,
2026-09-21). The argument, and the two settings deliberately NOT taken, are
written beside the line in that module.

**Why both halves are asserted here, in one test.** The dangerous way to get
this speed-up is to take it from the SERVER or from a DATABASE: one compose
Postgres (`compose.yaml`, service `db`) holds this checkout's dev database,
every other checkout's, Zitadel's identity database and the test clones, so a
`fsync=off` in `postgresql.conf` or an `ALTER DATABASE … SET` that landed on
the wrong name would buy the same seconds by removing a durability guarantee
from real data. A test that only asserted "the suite's connection says off"
would be green in every one of those worlds. So the same test also asserts:

* `pg_settings.source` for the suite's own connection is **`client`** — the
  value arrived on the connection string. `configuration file` would mean the
  server was changed; `database` would mean an `ALTER DATABASE` was used;
  `default` would mean the option never arrived at all.
* a connection assembled the way a DEPLOYMENT assembles one — from
  `config.settings.base`, not from the suite's settings — reports **`on`**,
  against the same server and against this checkout's real dev database.

Either half alone can pass in a world the other refuses, which is the whole
point of them being one test.

**Declared blind spots.** This says nothing about whether `synchronous_commit
= off` is fast (that is the rung's before/after wall, not an assertion), and
nothing about `fsync` or `full_page_writes`, which are `sighup`-context GUCs
this tree deliberately leaves alone — if somebody turns those off in
`compose.yaml` the suite gets faster and every assertion here stays green.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from django.conf import settings as live_settings
from django.db import connection

import config.settings.base as deployment_settings

# The maintenance database every Postgres has, so the deployment half of the
# test has somewhere to land on a machine whose derived dev database has not
# been created yet. It is still a NON-test database on the same server, so the
# assertion is the same one either way and is never skipped.
FALLBACK_DATABASE = "postgres"


def _deployment_connection_kwargs() -> tuple[dict[str, Any], str]:
    """psycopg keyword arguments for the connection a DEPLOYMENT would open.

    Read off `config.settings.base` — the module `local` and `production` both
    build on and the module `test` overrides — rather than off
    `django.conf.settings`, which in this process IS the overridden one. No
    reload and no environment patch: the question is what this checkout's own
    `.env` assembles, which is what the module already holds.

    `pool` is dropped because `psycopg.connect` is not `psycopg_pool`; nothing
    else is touched, and in particular OPTIONS is otherwise passed through, so
    an `options` string that had leaked into the deployment config would arrive
    here and fail the assertion, which is the direction that matters.
    """
    assembled = deployment_settings.DATABASES["default"]
    options = {
        key: value for key, value in (assembled.get("OPTIONS") or {}).items() if key != "pool"
    }
    kwargs: dict[str, Any] = {
        "dbname": assembled["NAME"],
        "user": assembled.get("USER") or None,
        "password": assembled.get("PASSWORD") or None,
        "host": assembled.get("HOST") or None,
        "port": assembled.get("PORT") or None,
        **options,
    }
    return {key: value for key, value in kwargs.items() if value is not None}, str(
        assembled["NAME"]
    )


@pytest.mark.django_db
def test_the_suite_skips_the_commit_wait_and_the_deployment_does_not() -> None:
    # --- half one: the suite's own connection, and where the value came from --
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), current_setting('synchronous_commit'), "
            "(SELECT source FROM pg_settings WHERE name = 'synchronous_commit')"
        )
        suite_database, suite_value, suite_source = cursor.fetchone()

    assert suite_database.startswith("test_"), (
        f"the suite is connected to {suite_database!r}, which is not a Django test database — "
        "this test is measuring the wrong connection and its verdict means nothing"
    )
    assert suite_value == "off", (
        f"the suite's connection reports synchronous_commit={suite_value!r}; "
        "config/settings/test.py is supposed to send `-c synchronous_commit=off` on every "
        f"connection (its OPTIONS here are {live_settings.DATABASES['default']['OPTIONS']!r})"
    )
    assert suite_source == "client", (
        f"synchronous_commit=off reached the suite from {suite_source!r}, not from the "
        "connection string. 'configuration file' means the shared Postgres was changed and "
        "every dev database on it lost its durability guarantee; 'database' means an "
        "ALTER DATABASE landed somewhere — neither is what config/settings/test.py does"
    )

    # --- half two: the same server, the way a deployment connects to it -------
    kwargs, configured_name = _deployment_connection_kwargs()
    assert not any("synchronous_commit" in str(value) for value in kwargs.values()), (
        "config.settings.base — the module every deployment reads — has grown a "
        f"synchronous_commit override: {kwargs!r}. The suite's speed-up must not leak into "
        "the settings a real deployment assembles"
    )

    try:
        dev_connection = psycopg.connect(**kwargs)
    except psycopg.OperationalError:
        dev_connection = psycopg.connect(**{**kwargs, "dbname": FALLBACK_DATABASE})

    with dev_connection:
        with dev_connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_setting('synchronous_commit'), "
                "(SELECT source FROM pg_settings WHERE name = 'synchronous_commit')"
            )
            row = cursor.fetchone()
    assert row is not None, "the deployment connection answered no row at all"
    dev_database, dev_value, dev_source = row

    assert dev_database != suite_database, (
        f"the deployment half opened {dev_database!r}, the same database the suite is using — "
        "it would report the suite's own setting and prove nothing"
    )
    assert dev_value == "on", (
        f"{dev_database!r} (configured as {configured_name!r}) reports "
        f"synchronous_commit={dev_value!r}, source {dev_source!r}. A non-test database on this "
        "server must still wait for its commits to reach the disk — the suite's speed-up is "
        "bought on throwaway data only"
    )
