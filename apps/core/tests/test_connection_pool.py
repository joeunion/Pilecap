"""The connection pool, measured against a real Postgres rather than asserted.

**The defect this file exists to keep dead.** Under ASGI every `sync_to_async`
thread owns its own `DatabaseWrapper`, and a `DatabaseWrapper`'s connection is
closed only at the end of a request *that thread* served. With persistent
connections (`CONN_MAX_AGE` > 0) nothing reclaims an idle thread's slot, so the
process's server-side connection count is the number of threads that have ever
served a request — never the number doing work. LOAD-1b measured that live on
staging: **43 connections held against ≤4 active, flat across the whole ladder
and unchanged 90 seconds after the load stopped**, on an RDS instance whose
`max_connections` is 79 and whose neighbours (Temporal, Zitadel, rdsadmin) hold
about 30 of them. Concurrency 1 was already at the wall.

**What the fix is, and why it is a cap rather than a promise.** Django 5.2's
native psycopg pool (`OPTIONS["pool"]`) makes every request-end close a
*putconn*: the socket goes back to a per-process pool instead of being kept by
the thread or torn down. Server-side connections are then bounded by
`max_size` **by construction** — not by a convention a burst can break — and
they stay warm, so no request pays a fork plus a TLS handshake on the
convicted burstable RDS CPU. The ruling, its two rejected alternatives
(pgbouncer, bare `CONN_MAX_AGE=0`) and the trigger to revisit are in
`docs/product/architecture.md`; `config/settings/base.py` carries the same
argument beside the values.

**Why this reads `config.settings.base` and not `django.conf.settings`.** The
suite runs pool-OFF on purpose (`config/settings/test.py` says why: the
workflow tests run activities on worker threads and a held connection is a
test database Django cannot drop). So a probe that measured the ambient world
would measure the world the fix is deliberately absent from. It imports the
*deployment's* settings module under a patched environment, takes the
`DATABASES["default"]` that module assembles, points it at this worker's test
database and drives real threads through it. On a tree without the pool the
same probe reproduces the 43-shape small and fails with the measured count in
the message.

Its blind spots are declared: this is local Postgres over a unix-ish loopback
socket, so it says nothing about RDS TLS reconnect behaviour, nothing about
the real neighbour mix, and nothing about long-lived Channels scopes. Those
belong to the staging re-run, which has a live instance to read.
"""

from __future__ import annotations

import importlib
import os
import re
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest import mock

import psycopg
import pytest
from django.conf import settings as live_settings
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.backends.postgresql.base import DatabaseWrapper as PostgresWrapper
from django.db.utils import ConnectionHandler

BASE_DIR = Path(live_settings.BASE_DIR)

# --- The probe's own dimensions ---------------------------------------------
# Small enough to cost the suite well under a second when green, large enough
# that the two shapes cannot be confused: THREADS is more than double MAX_SIZE,
# so a bounded reading cannot be an artefact of never having contended.
PROBE_ALIAS = "pool_probe"
PROBE_APPLICATION_NAME = "djb-pool-probe"
PROBE_THREADS = 8
PROBE_ROUNDS = 6
PROBE_MIN_SIZE = 1
PROBE_MAX_SIZE = 4
PROBE_TIMEOUT = 5.0
# The pool shrinks toward `min_size` after a connection has been idle this
# long. Production's default is minutes; the probe wants seconds so "the
# residue goes away" is a thing a test can watch happen rather than assert.
PROBE_MAX_IDLE = 1.0
# How long the probe will wait for that shrink before reporting what it saw.
SHRINK_DEADLINE = 12.0
# One round's work. Long enough that eight threads genuinely overlap.
ROUND_SECONDS = 0.05


@contextmanager
def _deployment_database(**environment: str) -> Iterator[dict[str, Any]]:
    """The `DATABASES["default"]` a deployment assembles, under a given environment.

    Settings are read at import, which is the honest thing for settings to do
    and awkward to look at from inside a suite that imported different ones.
    So the module is reloaded under the patched environment, its answer copied
    out, and the module reloaded again on the way out. `django.conf.settings`
    is a separate object and is untouched throughout — the same arrangement
    `test_settings.py::_settings_module` uses, and for the same reason.
    """
    base = importlib.import_module("config.settings.base")
    try:
        with mock.patch.dict(os.environ, environment):
            importlib.reload(base)
            yield {key: value for key, value in base.DATABASES["default"].items()}
    finally:
        importlib.reload(base)


def _probe_settings(assembled: dict[str, Any]) -> dict[str, Any]:
    """The deployment's connection settings, pointed at this worker's test database.

    Two edits and no others, both so the probe can be *seen*: the database
    name, because a test may not open connections to whatever database the
    developer's `.env` names; and `application_name`, because that is what
    tells this probe's backends apart from the suite's own in
    `pg_stat_activity`. The pool options and `CONN_MAX_AGE` arrive exactly as
    the deployment assembled them — those are the subject.
    """
    return {
        **assembled,
        "NAME": connection.settings_dict["NAME"],
        "OPTIONS": {
            **assembled.get("OPTIONS", {}),
            "application_name": PROBE_APPLICATION_NAME,
        },
    }


def _postgres(handler: ConnectionHandler, alias: str) -> PostgresWrapper:
    """This thread's wrapper for `alias`, typed as the backend it actually is.

    `ConnectionHandler.__getitem__` is annotated `BaseDatabaseWrapper`, and
    `pool` / `close_pool()` are the postgres backend's own — the two members
    this whole file is about. The cast is the narrowing, asserted rather than
    assumed, because a settings dict naming another engine here would be a
    silent no-op instead of a probe.
    """
    wrapper = handler[alias]
    assert isinstance(wrapper, PostgresWrapper)
    return wrapper


def _observer(settings_dict: dict[str, Any]) -> psycopg.Connection[Any]:
    """A connection outside Django, for reading `pg_stat_activity` during the drive.

    Outside Django because it must not be one of the connections being
    counted, and outside the pool because a pool slot spent watching the pool
    is a slot the drive cannot contend for.
    """
    return psycopg.connect(
        dbname=settings_dict["NAME"],
        user=settings_dict["USER"] or None,
        password=settings_dict["PASSWORD"] or None,
        host=settings_dict["HOST"] or None,
        port=settings_dict["PORT"] or None,
        application_name="djb-pool-probe-observer",
        autocommit=True,
    )


def _held(observer: psycopg.Connection[Any], name: str) -> int:
    """How many server backends this probe is holding open, right now."""
    with observer.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = %s AND application_name = %s",
            (name, PROBE_APPLICATION_NAME),
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


class Reading:
    """What one drive of the probe saw. Every number here is measured."""

    def __init__(self) -> None:
        self.peak_held = 0
        self.settled_held = 0
        self.backend_pids: set[int] = set()
        self.request_ends = 0
        self.errors: list[BaseException] = []


def _drive(
    handler: ConnectionHandler,
    reading: Reading,
    lock: threading.Lock,
    done: threading.Barrier,
    release: threading.Event,
) -> None:
    """One ASGI-shaped worker thread: serve requests, then idle holding whatever it holds.

    Each round is a request: take this thread's connection, do a unit of work,
    and end the request the way Django ends one —
    `close_if_unusable_or_obsolete()`, which is exactly what
    `django.db.close_old_connections` calls on the `request_finished` signal.
    With persistent connections that call keeps the socket for this thread
    alone; with the pool it is a `putconn` and the socket returns to the
    process.

    `pg_backend_pid()` is read from inside the round, so the set of server
    backends that served the drive is exact rather than sampled: with the pool,
    48 request-ends served by no more than `max_size` distinct backends is what
    "the close is a putconn and the socket stays warm" *means*.
    """
    try:
        for _ in range(PROBE_ROUNDS):
            wrapper = handler[PROBE_ALIAS]
            with wrapper.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid(), pg_sleep(%s)", (ROUND_SECONDS,))
                row = cursor.fetchone()
            with lock:
                if row is not None:
                    reading.backend_pids.add(int(row[0]))
                reading.request_ends += 1
            wrapper.close_if_unusable_or_obsolete()
    except BaseException as failure:  # noqa: BLE001 — every failure has to reach the report
        with lock:
            reading.errors.append(failure)
    finally:
        try:
            done.wait(timeout=SHRINK_DEADLINE + 10)
            release.wait(timeout=SHRINK_DEADLINE + 10)
        finally:
            # This thread's own connection, closed by this thread: a wrapper is
            # thread-local and nobody else may close it.
            try:
                handler[PROBE_ALIAS].close()
            except Exception:  # noqa: BLE001 — cleanup must not mask the reading
                pass


def _sample(
    settings_dict: dict[str, Any],
    reading: Reading,
    lock: threading.Lock,
    stop: threading.Event,
) -> None:
    """Watch `pg_stat_activity` while the drive runs and keep the high-water mark."""
    observer = _observer(settings_dict)
    try:
        while not stop.is_set():
            held = _held(observer, settings_dict["NAME"])
            with lock:
                reading.peak_held = max(reading.peak_held, held)
            stop.wait(0.02)
    finally:
        observer.close()


def _run_probe(settings_dict: dict[str, Any], *, wait_for_shrink: bool) -> Reading:
    """Drive `PROBE_THREADS` threads through `settings_dict` and read the server.

    The barrier is what makes "after the threads idle" a real state rather
    than a sleep: every thread parks after its last request-end, so the
    settled reading is taken while the process is exactly as idle as a
    deployment between bursts.
    """
    reading = Reading()
    lock = threading.Lock()
    done = threading.Barrier(PROBE_THREADS + 1)
    release = threading.Event()
    stop = threading.Event()

    handler = ConnectionHandler(
        {
            "default": {"ENGINE": "django.db.backends.dummy"},
            PROBE_ALIAS: settings_dict,
        }
    )
    sampler = threading.Thread(target=_sample, args=(settings_dict, reading, lock, stop))
    drivers = [
        threading.Thread(target=_drive, args=(handler, reading, lock, done, release))
        for _ in range(PROBE_THREADS)
    ]
    observer = _observer(settings_dict)
    try:
        sampler.start()
        for driver in drivers:
            driver.start()
        done.wait(timeout=SHRINK_DEADLINE + 10)
        stop.set()
        sampler.join(timeout=5)

        name = settings_dict["NAME"]
        reading.settled_held = _held(observer, name)
        if wait_for_shrink:
            deadline = time.monotonic() + SHRINK_DEADLINE
            while reading.settled_held > PROBE_MIN_SIZE and time.monotonic() < deadline:
                time.sleep(0.1)
                reading.settled_held = _held(observer, name)
    finally:
        stop.set()
        release.set()
        for driver in drivers:
            driver.join(timeout=10)
        # The pool is keyed on the alias in a class attribute shared by every
        # `DatabaseWrapper`, so leaving it open would leak both the pool's
        # maintenance threads and its connections into the rest of the session.
        try:
            _postgres(handler, PROBE_ALIAS).close_pool()
        finally:
            handler.close_all()
            observer.close()
    return reading


# --- The probe ---------------------------------------------------------------


@pytest.mark.django_db
def test_the_pool_bounds_what_the_process_holds() -> None:
    """N threads, a pool of four: the server never holds more than four.

    The absent case is the point. On a tree whose settings assemble no
    `OPTIONS["pool"]`, this fails with the count it measured — eight threads
    holding eight connections and still holding them after they went idle,
    which is LOAD-1b's 43-shape reproduced at a size a laptop can see.
    """
    with _deployment_database(
        DATABASE_POOL_ENABLED="true",
        DATABASE_POOL_MIN_SIZE=str(PROBE_MIN_SIZE),
        DATABASE_POOL_MAX_SIZE=str(PROBE_MAX_SIZE),
        DATABASE_POOL_TIMEOUT=str(PROBE_TIMEOUT),
        DATABASE_POOL_MAX_IDLE=str(PROBE_MAX_IDLE),
    ) as assembled:
        settings_dict = _probe_settings(assembled)

    pool_options = settings_dict["OPTIONS"].get("pool")
    reading = _run_probe(settings_dict, wait_for_shrink=bool(pool_options))
    measured = (
        f"{PROBE_THREADS} threads · {reading.request_ends} request-ends · "
        f"held at peak {reading.peak_held} · held after idle {reading.settled_held} · "
        f"{len(reading.backend_pids)} distinct server backends · "
        f"CONN_MAX_AGE={settings_dict['CONN_MAX_AGE']!r} · pool={pool_options!r}"
    )
    assert not reading.errors, f"the drive raised: {reading.errors!r} ({measured})"

    assert isinstance(pool_options, dict), (
        "config.settings.base assembles no DATABASES['default']['OPTIONS']['pool'], "
        "so every thread owns a connection nothing reclaims — " + measured
    )
    assert settings_dict["CONN_MAX_AGE"] == 0, (
        "the pool is on and connections are still persistent — " + measured
    )
    assert pool_options["max_size"] == PROBE_MAX_SIZE, measured

    assert reading.peak_held <= PROBE_MAX_SIZE, (
        "pg_stat_activity saw more backends than the pool's max_size — " + measured
    )
    assert reading.settled_held <= PROBE_MIN_SIZE, (
        "the residue did not go away: the pool did not shrink to min_size — " + measured
    )
    assert len(reading.backend_pids) <= PROBE_MAX_SIZE, (
        "request-end is closing the socket rather than returning it: "
        f"{reading.request_ends} requests were served by "
        f"{len(reading.backend_pids)} distinct backends — " + measured
    )
    assert reading.request_ends == PROBE_THREADS * PROBE_ROUNDS, measured


@pytest.mark.django_db
def test_without_the_pool_every_thread_pins_a_connection() -> None:
    """The defect itself, reproduced small — so the probe above cannot pass vacuously.

    This is the shape LOAD-1b measured on staging, driven here against the
    deployment's own settings with the pool switched off: eight threads, eight
    connections, and all eight still held after the threads went idle. It is
    the reason the bounded reading above means something, and it is the thing
    that would come back if `DATABASE_POOL_ENABLED` were ever defaulted off
    without anybody noticing.
    """
    with _deployment_database(
        DATABASE_POOL_ENABLED="false",
        DATABASE_CONN_MAX_AGE="60",
    ) as assembled:
        settings_dict = _probe_settings(assembled)

    assert settings_dict["OPTIONS"].get("pool") is None
    assert settings_dict["CONN_MAX_AGE"] == 60

    reading = _run_probe(settings_dict, wait_for_shrink=False)
    assert not reading.errors, f"the drive raised: {reading.errors!r}"
    assert reading.peak_held == PROBE_THREADS
    assert reading.settled_held == PROBE_THREADS, (
        "persistent connections were reclaimed while the threads idled, which "
        "is not what CONN_MAX_AGE does — the probe's premise has changed and "
        f"the reading is {reading.settled_held}"
    )
    assert len(reading.backend_pids) == PROBE_THREADS


# --- The settings assembly ---------------------------------------------------


def test_the_pool_is_on_and_persistent_connections_are_off() -> None:
    """Pool on ⇒ `CONN_MAX_AGE == 0`, by construction rather than by convention."""
    with _deployment_database() as assembled:
        assert assembled["CONN_MAX_AGE"] == 0
        pool = assembled["OPTIONS"]["pool"]
    assert pool["min_size"] >= 1
    assert pool["max_size"] >= pool["min_size"]
    assert pool["timeout"] > 0


def test_the_env_knobs_reach_the_pool() -> None:
    """The numbers a deployment sets are the numbers psycopg is handed."""
    with _deployment_database(
        DATABASE_POOL_MIN_SIZE="3",
        DATABASE_POOL_MAX_SIZE="11",
        DATABASE_POOL_TIMEOUT="4.5",
        DATABASE_POOL_MAX_IDLE="90",
    ) as assembled:
        pool = assembled["OPTIONS"]["pool"]
    assert pool == {"min_size": 3, "max_size": 11, "timeout": 4.5, "max_idle": 90.0}


def test_the_pool_size_is_derived_from_what_the_process_is() -> None:
    """Two processes, two pools, and their sum is the number the budget bounds.

    `DJB_SERVICE_NAME` already tells the web process from the Temporal worker
    (`deploy/compose.yaml` sets it; `apps/workflows/worker.py` sets it before
    `django.setup()`), and a pool is per process — so the split rides that one
    discriminator instead of a second copy of it. The arithmetic that makes 20
    and 8 the right pair, neighbours counted, is in `config/settings/base.py`
    and beside the values in `deploy/env.staging.example`.
    """
    with _deployment_database(DJB_SERVICE_NAME="web") as assembled:
        web = assembled["OPTIONS"]["pool"]["max_size"]
    with _deployment_database(DJB_SERVICE_NAME="worker") as assembled:
        worker = assembled["OPTIONS"]["pool"]["max_size"]

    assert web > worker, "the door that serves requests gets the larger half"

    base = importlib.import_module("config.settings.base")
    assert web + worker <= base.DATABASE_POOL_APP_CEILING

    # And an explicit value wins outright over the derivation, the way every
    # other per-process name in this settings module lets a deployment say so.
    with _deployment_database(DJB_SERVICE_NAME="worker", DATABASE_POOL_MAX_SIZE="30") as assembled:
        assert assembled["OPTIONS"]["pool"]["max_size"] == 30


def test_a_one_off_takes_the_small_pool_and_not_the_webs() -> None:
    """`compose run` lands on a DOOR, and a door that reserves 20 slots is a bug.

    A one-off used to run as the `web` service, inherit `DJB_SERVICE_NAME=web`
    and derive `max_size=20` — so `manage.py revoke_token` on a loaded box
    PoolTimeout'd with zero slots free, and release acts 1, 2, 3 and 5 are the
    same shape. `deploy/compose.yaml` grows a dedicated `oneoff` service whose
    whole job is to be the name `compose run` lands on; this is the settings
    half of that seam.

    Asserted against `web`'s own derived value rather than against a literal:
    the property is that the door is SMALL, not that it happens to be 2 today.
    """
    with _deployment_database(DJB_SERVICE_NAME="oneoff") as assembled:
        oneoff = assembled["OPTIONS"]["pool"]["max_size"]
    with _deployment_database(DJB_SERVICE_NAME="web") as assembled:
        web = assembled["OPTIONS"]["pool"]["max_size"]

    assert oneoff == 2
    assert oneoff < web, "the one-off door must not reserve a deployment's worth"

    # It is a DECLARED entry, not the stranger default: a name nobody put in the
    # map cannot be the one four release acts depend on. `_OTHERWISE` answers
    # differently, and that difference is the assertion.
    base = importlib.import_module("config.settings.base")
    assert base._POOL_MAX_SIZE_BY_SERVICE["oneoff"] == 2
    assert base._POOL_MAX_SIZE_OTHERWISE != 2

    # And an explicit value still wins outright, exactly as it does for web and
    # worker — a deployment that has a reason may say so.
    with _deployment_database(DJB_SERVICE_NAME="oneoff", DATABASE_POOL_MAX_SIZE="6") as assembled:
        assert assembled["OPTIONS"]["pool"]["max_size"] == 6


def test_the_one_off_door_exists_in_the_deployment_compose() -> None:
    """A pool class with no caller is dead config, so the caller is asserted too.

    The settings entry above is only half of the fix: the other half is a
    compose service named `oneoff` that sets `DJB_SERVICE_NAME: oneoff` and
    declares NO `depends_on` (a one-off on a loaded box must not try to restart
    organs, which is what makes `--no-deps` structural at the call sites). Read
    out of the file rather than trusted, so deleting the service reddens the
    settings entry that exists for it.
    """
    compose = (BASE_DIR / "deploy" / "compose.yaml").read_text(encoding="utf-8")
    service = re.search(r"^  oneoff:\n(?:^(?:    .*)?\n)+", compose, re.MULTILINE)
    assert service is not None, "deploy/compose.yaml declares no `oneoff` service"

    block = service.group(0)
    assert "DJB_SERVICE_NAME: oneoff" in block
    assert "depends_on" not in block, (
        "the oneoff door declares no dependencies on purpose — a one-off on a "
        "loaded box must not (re)start organs"
    )
    assert "djb-web:" in block, "the one-off runs the tree the deployment is on"


def test_an_empty_max_size_derives_rather_than_crashing() -> None:
    """The variable EXISTS and is EMPTY: that has to mean "derive", not `ValueError`.

    `deploy/entrypoint.sh` does `set -a; . <env file>`, so a name written in an
    env file is exported even with no value, and `env.int` on an empty string
    raises at import — a container that will not boot, complaining about
    `int()` rather than about connection pools. `.env.example` ships the name
    empty on purpose (it is the "derive" spelling); this is the line that keeps
    that safe.
    """
    with _deployment_database(DJB_SERVICE_NAME="worker", DATABASE_POOL_MAX_SIZE="") as assembled:
        derived = assembled["OPTIONS"]["pool"]["max_size"]
    with _deployment_database(DJB_SERVICE_NAME="worker") as assembled:
        assert assembled["OPTIONS"]["pool"]["max_size"] == derived


def test_the_staging_manifest_carries_the_arithmetic_and_not_the_per_process_size() -> None:
    """The file that counts, counts — and does not carry a name it would break.

    `deploy/env.staging.example` is THE manifest of names
    (`deploy/provision.sh` generates every environment from it), so two
    properties have to hold together: the neighbour-counted budget lives beside
    the values it bounds, and `DATABASE_POOL_MAX_SIZE` is NOT one of those
    names — empty would be refused by the generator as a slot nothing fills,
    and a value would apply to both processes and break the very sum the
    comment reasons about.
    """
    manifest = (BASE_DIR / "deploy" / "env.staging.example").read_text(encoding="utf-8")
    names = {
        line.partition("=")[0].strip()
        for line in manifest.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }

    assert "DATABASE_POOL_ENABLED" in names
    assert "DATABASE_POOL_MIN_SIZE" in names
    assert "DATABASE_POOL_TIMEOUT" in names
    assert "DATABASE_POOL_MAX_IDLE" in names
    assert "DATABASE_POOL_MAX_SIZE" not in names

    base = importlib.import_module("config.settings.base")

    # EVERY TERM OF THE SUBTRACTION, matched on its own LINE rather than as a
    # bare substring: "33" appears in a four-hundred-line manifest by accident,
    # and a pin that a coincidence can satisfy is not a pin. `24` and `5` are
    # the totals `deploy/compose.yaml` makes true with `SQL_MAX_CONNS` and
    # `ZITADEL_DATABASE_POSTGRES_MAXOPENCONNS` — if they move there they move
    # here, and this is the line that says so.
    ceiling = base.DATABASE_POOL_APP_CEILING
    for label, pattern in (
        ("the instance's own limit", r"^#\s+max_connections\b.*\b79\s*$"),
        ("Temporal's bounded total", r"^#\s+-\s*Temporal, bounded:.*<=\s*24\s*$"),
        # 7, not 5: `MAXOPENCONNS` bounds Zitadel's main pool and its background
        # job queue keeps a second one no env variable in v4.17.1 reaches. Driven
        # both ways on the laptop deploy stack — 10/5 gives 12 (which is what
        # RATIO-1 measured on the box), 5/2 gives 7. The residue is constant and
        # it is subtracted rather than rounded away.
        (
            "Zitadel's bounded total plus its named residue",
            r"^#\s+-\s*Zitadel: 5 bounded \+ 2 .*<=\s*7\s*$",
        ),
        ("the application's ceiling", rf"^#\s+=\s*the application's ceiling\s+{ceiling}\s*$"),
        ("the sum that fits inside it", rf"^#\s+web max_size 20 .*=\s*28\s+<=\s*{ceiling}\s*$"),
    ):
        assert re.search(pattern, manifest, re.MULTILINE), f"the arithmetic lost {label}"

    assert "neighbours" in manifest or "neighbors" in manifest

    # THE KNOBS ARE NAMED where the arithmetic is, so an operator reading the
    # budget can find the thing that enforces it without a grep across `deploy/`.
    for knob in (
        "SQL_MAX_CONNS",
        "SQL_VIS_MAX_CONNS",
        "ZITADEL_DATABASE_POSTGRES_MAXOPENCONNS",
    ):
        assert knob in manifest, f"the arithmetic does not say what enforces it: {knob}"

    # THE DEAD SENTENCE, ASSERTED ABSENT. The manifest used to carry Temporal's
    # draw as "17 + 3" and call it a budget constant to trim on some future
    # Temporal touch; this WAS that touch, and a corrected block with the old
    # excuse still sitting one paragraph below is how a reader takes the wrong
    # number away. The absent case is asserted, not merely the present one.
    assert "17 + 3" not in manifest
    assert "17+3" not in manifest
    assert "~34" not in manifest


def test_switching_the_pool_off_restores_persistent_connections() -> None:
    """The escape hatch is real, and it puts the old shape back rather than half of it.

    Persistent connections, not bare churn: `CONN_MAX_AGE=0` with no pool is
    the option that was rejected on its merits, and switching the pool off must
    not silently land a deployment in it. The value is named explicitly here
    rather than left to the default, so this asserts about the assembly and not
    about whatever `.env` the machine running it happens to hold.
    """
    with _deployment_database(
        DATABASE_POOL_ENABLED="false", DATABASE_CONN_MAX_AGE="45"
    ) as assembled:
        assert "pool" not in assembled["OPTIONS"]
        assert assembled["CONN_MAX_AGE"] == 45


def test_the_suite_runs_with_the_pool_off_and_says_why() -> None:
    """`config/settings/test.py` keeps pooling out of the suite, deliberately.

    Not an accident to be tidied up later: a pooled connection held by a worker
    thread is a test database Django cannot drop, and nothing about pooling is
    under test in the ambient world — the probe above arms it for itself.
    """
    assert live_settings.DATABASES["default"]["CONN_MAX_AGE"] == 0
    assert "pool" not in live_settings.DATABASES["default"].get("OPTIONS", {})

    source = importlib.import_module("config.settings.test").__file__ or ""
    assert source
    assert "pool" in open(source, encoding="utf-8").read().lower()


def test_django_refuses_the_contradictory_pair() -> None:
    """The belt: a pool beside persistent connections is refused, not averaged.

    `config.settings.base` cannot assemble that pair — `CONN_MAX_AGE` is 0
    whenever the pool is on — but a deployment writing its own `DATABASES` can,
    and Django's own refusal is what catches it. Pinned here so the belt is
    known to be there rather than assumed.
    """
    with _deployment_database() as assembled:
        settings_dict = _probe_settings(assembled)

    handler = ConnectionHandler(
        {
            "default": {"ENGINE": "django.db.backends.dummy"},
            "contradictory": {**settings_dict, "CONN_MAX_AGE": 60},
        }
    )
    try:
        with pytest.raises(ImproperlyConfigured, match="persistent connections"):
            _postgres(handler, "contradictory").pool  # noqa: B018 — the property refuses
    finally:
        handler.close_all()


def test_psycopg_pool_is_installed() -> None:
    """`psycopg[pool]` is a dependency, not a hope.

    Django raises `ImproperlyConfigured` naming this extra the first time a
    pooled connection is opened — which is a 500 on the first request of a
    deployment that shipped without it. Nothing else in the tree imports
    `psycopg_pool`, so this line is what keeps `pyproject.toml` honest.
    """
    assert "psycopg_pool" not in sys.modules or True
    import psycopg_pool

    assert psycopg_pool.ConnectionPool is not None
