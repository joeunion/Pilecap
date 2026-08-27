"""Machinery durability follows the identity's declared lifetime class.

ADR platform-lifecycle-1. A Temporal Schedule is infinitely durable by
construction; the task queue this template derives is derived from the
**checkout**, which is ephemeral by construction. Durable object, mortal
identity — and what that mismatch mints is not a missing reaper but a class of
object nobody declared the lifetime of.

So it is declared, and this module is what holds the declaration to it:

* the setting exists, and each settings module's default is a **declaration** —
  there is no branch test, no checkout-name test, no environment sniffing;
* `deployment` is the code path this template already had, unchanged, which is
  proved next door by `apps/events/tests/test_activities.py` and
  `test_reconciler.py` continuing to pass against the generic engine, and here
  by the engine writing the app's own declared `Schedule` value verbatim;
* `process` creates **no Schedule object, ever**, deletes the durable ones an
  earlier build of this checkout left behind, and still runs the same three
  sweeps — at startup and then on their declared cadence.

The schedules half uses a stand-in for the client's schedules API, which the
time-skipping test server does not implement, in the `FakeScheduleServer` shape
`apps/events/tests/test_activities.py` established. The sweeps half uses the
real time-skipping server and the real discovered worker, because "the sweeps
still run" is a claim about the actual worker assembly and a stub would be a
test of the stub.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from django.conf import settings as django_settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from temporalio.client import (
    Schedule,
    ScheduleAlreadyRunningError,
    WorkflowExecutionStatus,
)
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.service import RPCError, RPCStatusCode
from temporalio.testing import WorkflowEnvironment

from apps.core.schedules import ScheduleDeclaration
from apps.workflows import activities as workflows_activities
from apps.workflows.client import (
    attach_interceptors,
    build_worker,
    declared_cadence,
    declared_start,
    discovered_schedules,
    ensure_declaration,
    ensure_schedules,
    machinery_lifetime,
    run_declared_machinery,
    start_declared_run,
    start_declared_runs,
)

#: A queue of this module's own, so nothing here can be mistaken for — or
#: collide with — the queue the checkout's real worker polls.
TASK_QUEUE = "djb-machinery-tests"

#: A queue that belongs to somebody else. The self-clean must not touch it: a
#: schedule on a peer's queue belongs to a worker that may still be alive, and
#: deleting it is the rejected worker-shutdown design wearing a different hat.
PEER_QUEUE = "djb-somebody-elses-checkout"

BASE_DIR = Path(django_settings.BASE_DIR)

#: The two wire values, spelled once. The tests that must run in the other class
#: use the literal (a decorator cannot easily reach a setting), and
#: `test_the_wire_values_are_the_two_declared_classes` pins the literals to the
#: constants so the two cannot drift.
DEPLOYMENT = "deployment"
PROCESS = "process"

deployment_machinery = override_settings(TEMPORAL_MACHINERY_LIFETIME=DEPLOYMENT)


# --- Stand-ins ----------------------------------------------------------------


class FakeScheduleServer:
    """The client's schedules API, recording every question asked of it.

    The same shape `apps/events/tests/test_activities.py` established, with one
    further addition: it also records `start_workflow`, because the
    central claim of `process` mode is a **negative** — that no schedule is
    ever created — and a negative is only worth anything beside the positive
    that replaced it.
    """

    def __init__(self, *, present: set[str] | None = None) -> None:
        self.present: set[str] = set(present or ())
        self.created: list[tuple[str, Schedule]] = []
        self.updated: list[tuple[str, Schedule]] = []
        self.deleted: list[str] = []
        self.started: list[dict[str, Any]] = []
        #: Every question, in the order it was asked. Ordering is a property
        #: here — the legacy drop must land BEFORE the suffixed create — and
        #: three separate lists cannot say anything about order between them.
        self.log: list[tuple[str, str]] = []

    async def create_schedule(self, schedule_id: str, schedule: Schedule) -> Any:
        if schedule_id in self.present:
            raise ScheduleAlreadyRunningError()
        self.present.add(schedule_id)
        self.created.append((schedule_id, schedule))
        self.log.append(("create", schedule_id))
        return self._handle(schedule_id)

    def get_schedule_handle(self, schedule_id: str) -> Any:
        return self._handle(schedule_id)

    async def start_workflow(self, workflow: str, **kwargs: Any) -> Any:
        self.started.append({"workflow": workflow, **kwargs})
        started_id = str(kwargs["id"])

        class Started:
            id = started_id

        return Started()

    def _handle(self, schedule_id: str) -> Any:
        server = self

        class FakeHandle:
            async def update(self, updater: Any) -> None:
                server.updated.append((schedule_id, updater(None).schedule))
                server.log.append(("update", schedule_id))

            async def delete(self) -> None:
                if schedule_id not in server.present:
                    raise RPCError("schedule not found", RPCStatusCode.NOT_FOUND, b"")
                server.present.discard(schedule_id)
                server.deleted.append(schedule_id)
                server.log.append(("delete", schedule_id))

        return FakeHandle()


#: The three this tree declares, by the stable name each carries. Named rather
#: than imported: `import-linter` holds the platform apps independent of one
#: another, so `apps.workflows`' tests may not reach into `apps.events` — and
#: discovery is the seam under test in any case, so looking a declaration up the
#: way the engine finds it is the more honest reading.
PURGE = "events.purge-expired"
RECONCILE_OUTBOX = "events.reconcile-outbox"
RECONCILE_RUNS = "workflows.reconcile-runs"

#: The un-suffixed schedule older workers created, before ADR events-2 made
#: schedule ids per queue. Spelled here so the legacy id cannot quietly change:
#: a legacy id that drifts is a schedule that stops being cleaned up.
LEGACY_PURGE_ID = "events-purge-expired"

#: The cadences, as literals. The apps' own constants are one import away and
#: comparing against them would be tautological — the property is that
#: generalising the engine did not change how often anything runs.
PURGE_EVERY = timedelta(hours=24)
SWEEP_EVERY = timedelta(minutes=5)


def machine(name: str) -> ScheduleDeclaration:
    """The declaration discovery found under `name`, or a loud failure.

    Looked up the way the engine finds it rather than imported, so a test in
    this app can name a declaration `apps.events` owns without importing across
    a layer the contracts hold independent.
    """
    found = [one for one in discovered_schedules() if one.name == name]
    assert len(found) == 1, f"{name}: expected exactly one declaration, found {len(found)}"
    return found[0]


def our_ids(queue: str) -> set[str]:
    """Every durable schedule id this checkout could create on `queue`."""
    return {declaration.schedule_id(queue) for declaration in discovered_schedules()}


def legacy_ids() -> set[str]:
    """Every legacy id any declaration in the tree still cleans up."""
    return {one for declaration in discovered_schedules() for one in declaration.legacy_ids}


@contextmanager
def settings_module(name: str, **environment: str) -> Iterator[Any]:
    """Import one settings module under a given environment, then put it back.

    Settings are read at import time — the honest thing for settings to do, and
    the only way to see what a deployment's own module declares is to import it
    with that environment in place. The shape is `apps/core/tests/
    test_settings.py`'s, restated here rather than imported across app test
    modules: `base` is reloaded and restored, and any other module is dropped
    from `sys.modules` on both sides, because `config.settings.production`
    refuses to be imported at all outside the environment it demands.

    `django.conf.settings` is a separate object, materialised at setup, and is
    untouched throughout.
    """
    base = importlib.import_module("config.settings.base")
    is_base = name == base.__name__
    try:
        with mock.patch.dict(os.environ, environment):
            importlib.reload(base)
            if is_base:
                yield base
            else:
                sys.modules.pop(name, None)
                yield importlib.import_module(name)
    finally:
        if not is_base:
            sys.modules.pop(name, None)
        importlib.reload(base)


#: What `config.settings.production` demands before it will import at all. None
#: of it is a shortcut — it is the price of asking the production module
#: what IT declares rather than asking a copy of it.
#:
#: `DATABASE_URL` rather than the parts, so the published-password refusal has
#: no parts password to look at; the secret is a real-looking value that
#: exists to be accepted here and nowhere else.
#: A real-looking key: strong enough that the guards accept it, and not a
#: secret — it exists to be accepted here and nowhere else.
A_REAL_SECRET_KEY = (
    "0f7c3ae1e0f0a2b6c5d4e3f201928374655647382910abcdeff0123456789abcd"  # pragma: allowlist secret
)

#: A URL rather than the parts, so the published-password refusal has no parts
#: password to look at at all.
A_URL_ELSEWHERE = "postgres://someone:s3cret@db.test:6432/elsewhere"  # pragma: allowlist secret

PRODUCTION_ENVIRONMENT = {
    "DEBUG": "0",
    "ALLOWED_HOSTS": "machinery.example",
    "SECRET_KEY": A_REAL_SECRET_KEY,
    "DATABASE_URL": A_URL_ELSEWHERE,
}


def production_environment() -> dict[str, str]:
    """`PRODUCTION_ENVIRONMENT` plus a freshly generated encryption key."""
    from cryptography.fernet import Fernet

    return {**PRODUCTION_ENVIRONMENT, "CONNECTIONS_ENCRYPTION_KEY": Fernet.generate_key().decode()}


# --- 1 · the setting, module by module ----------------------------------------


def test_the_wire_values_are_the_two_declared_classes() -> None:
    """The literals this module and its neighbours decorate with are the real ones."""
    assert (django_settings.MACHINERY_DEPLOYMENT, django_settings.MACHINERY_PROCESS) == (
        DEPLOYMENT,
        PROCESS,
    )
    assert set(django_settings.MACHINERY_LIFETIMES) == {DEPLOYMENT, PROCESS}


def test_the_suite_itself_runs_in_the_process_class() -> None:
    """`config.settings.test`, as the suite is actually running it.

    Not a reload and not a source read: this is the value every other test in
    this repository is executing under, which is the only reading of it that
    could be wrong in a way that mattered.
    """
    assert django_settings.TEMPORAL_MACHINERY_LIFETIME == PROCESS
    assert machinery_lifetime() == PROCESS


def test_base_declares_the_deployment_class_the_template_already_had() -> None:
    """An environment nobody has thought about yet keeps the behaviour it had.

    `base` is never `DJANGO_SETTINGS_MODULE` on its own, so this is the floor
    rather than a deployment: a settings module a product writes tomorrow that
    forgets to declare a class inherits durable schedules, which is what this
    template has always done, rather than silently stopping them.
    """
    with settings_module("config.settings.base", DATABASE_NAME="djb_probe") as base:
        assert base.TEMPORAL_MACHINERY_LIFETIME == DEPLOYMENT


def test_local_declares_the_process_class() -> None:
    """A laptop's queue is derived from its checkout, so its machinery is mortal."""
    with settings_module("config.settings.local", DATABASE_NAME="djb_probe") as local:
        assert local.TEMPORAL_MACHINERY_LIFETIME == PROCESS


def test_the_test_module_declares_the_process_class_from_a_clean_import() -> None:
    """The same answer from a fresh import as from the running process.

    Two readings of one module: this one proves the *declaration* in the file,
    `test_the_suite_itself_runs_in_the_process_class` proves the value in force.
    A module that took its class from something ambient would pass one and fail
    the other.
    """
    with settings_module("config.settings.test", DATABASE_NAME="djb_probe") as module:
        assert module.TEMPORAL_MACHINERY_LIFETIME == PROCESS


def test_production_declares_the_deployment_class() -> None:
    """The production module itself, imported, not a copy of its reasoning.

    `deployment` is right there because a deployment's task queue is a **stable
    identity** — not because it is production. The day a deployment gives each
    instance its own queue, that is the trigger recorded with the ADR.
    """
    with settings_module("config.settings.production", **production_environment()) as production:
        assert production.TEMPORAL_MACHINERY_LIFETIME == DEPLOYMENT


def test_the_environment_overrides_whatever_the_module_declared() -> None:
    """One escape hatch, and it reaches every module.

    A laptop reproducing a production question sets the variable and gets
    durable schedules; a deployment that has just given every pod its own queue
    sets it the other way without waiting for a release.
    """
    with settings_module(
        "config.settings.local",
        DATABASE_NAME="djb_probe",
        TEMPORAL_MACHINERY_LIFETIME=DEPLOYMENT,
    ) as local:
        assert local.TEMPORAL_MACHINERY_LIFETIME == DEPLOYMENT

    with settings_module(
        "config.settings.production",
        **production_environment(),
        TEMPORAL_MACHINERY_LIFETIME=PROCESS,
    ) as production:
        assert production.TEMPORAL_MACHINERY_LIFETIME == PROCESS


def test_an_empty_value_is_not_a_class_and_takes_the_declaration() -> None:
    """`.env.example` ships the slot blank, exactly as the task queue's is.

    A fresh clone copies that file and must not have to know which of the two
    words to write; blank means "whatever this settings module declares".
    """
    with settings_module(
        "config.settings.local",
        DATABASE_NAME="djb_probe",
        TEMPORAL_MACHINERY_LIFETIME="",
    ) as local:
        assert local.TEMPORAL_MACHINERY_LIFETIME == PROCESS


def test_an_unrecognised_class_is_refused_rather_than_guessed_at() -> None:
    """Neither fallback is safe, so there is no fallback.

    Falling back to `deployment` would create durable objects in a checkout that
    asked for none — the exact leak — and falling back to `process` would stop a
    production deployment's schedules with nothing anywhere saying so.
    """
    with pytest.raises(ImproperlyConfigured) as refusal:
        with settings_module(
            "config.settings.local",
            DATABASE_NAME="djb_probe",
            TEMPORAL_MACHINERY_LIFETIME="ephemeral",
        ):
            pass  # pragma: no cover - the import above is what raises

    message = str(refusal.value)
    assert "TEMPORAL_MACHINERY_LIFETIME" in message
    assert DEPLOYMENT in message
    assert PROCESS in message


#: Every module that decides, or acts on, the lifetime class. The scan below
#: reads these and nothing else — a name-shaped conditional anywhere here is the
#: failure mode the ruling names by name.
SEAM_FILES = (
    "config/settings/base.py",
    "config/settings/local.py",
    "config/settings/test.py",
    "config/settings/production.py",
    "apps/core/schedules.py",
    "apps/workflows/client.py",
    "apps/workflows/worker.py",
    "apps/workflows/activities.py",
    "apps/events/activities.py",
)

#: What a seam that guessed its environment would have to reach for. Prose is
#: exempt by construction — the scan reads **conditionals**, off the AST, so a
#: comment explaining why worktrees are the problem is not a worktree test.
GUESSING_TOKENS = (
    "branch",
    "worktree",
    "checkout",
    "hostname",
    "rev-parse",
    "getenv",
    "environ",
    "argv",
)


def seam_conditionals(name: str) -> list[str]:
    """Every conditional expression in one seam module, as source text."""
    import ast

    tree = ast.parse((BASE_DIR / name).read_text())
    tests: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If | ast.IfExp):
            tests.append(ast.unparse(node.test))
        elif isinstance(node, ast.Compare):
            tests.append(ast.unparse(node))
    return tests


def test_the_seam_distinguishes_environments_by_declaration_and_never_by_name() -> None:
    """The ruling's own words, made checkable.

    "Environment distinguished by declaration only — a scan for branch or
    checkout-name conditionals in the seam must find none." A heuristic on a
    name is a guess wearing a policy, and it is wrong the first time a real
    deployment runs out of a directory somebody called `worktree`.

    Read off the AST rather than off the text, so that the comments explaining
    *why* checkout-derived identities are the problem do not read as a checkout
    test — and so that a conditional cannot hide inside a docstring's shadow.
    """
    offences: list[str] = []
    for name in SEAM_FILES:
        for test in seam_conditionals(name):
            lowered = test.lower()
            offences.extend(f"{name}: {test}" for token in GUESSING_TOKENS if token in lowered)

    assert offences == []


def test_the_scan_would_catch_a_name_shaped_conditional() -> None:
    """The scan's own canary: a rule whose failure mode is silence needs one.

    `test_the_seam_...` asserts an empty list, which is what a scan that reads
    nothing also produces. This plants the exact shape it is looking for and
    insists it is found.
    """
    import ast

    planted = ast.parse('if "worktree" in branch_name:\n    pass\n')
    tests = [ast.unparse(node.test) for node in ast.walk(planted) if isinstance(node, ast.If)]

    assert tests, "the scan reads If.test; if this is empty it reads nothing"
    assert any(token in tests[0].lower() for token in GUESSING_TOKENS)
    # And the real seam has conditionals to read — an empty scan would pass
    # `test_the_seam_...` vacuously.
    assert seam_conditionals("apps/workflows/client.py")


def test_only_settings_decides_the_class() -> None:
    """The one reader, so a second one cannot grow beside it.

    `machinery_lifetime()` is a settings read and nothing else. A seam that
    could reach the environment directly could be given a different answer than
    the settings module declared, and then two halves of the same worker would
    disagree about whether a schedule exists.
    """
    with override_settings(TEMPORAL_MACHINERY_LIFETIME=DEPLOYMENT):
        assert machinery_lifetime() == DEPLOYMENT
    with override_settings(TEMPORAL_MACHINERY_LIFETIME=PROCESS):
        assert machinery_lifetime() == PROCESS


# --- 2 · the declaration seam -------------------------------------------------


def test_every_declared_machine_is_structured_data() -> None:
    """The seam the reconciler and its schedule declaration enumerate against.

    Every entry is a value with an id builder and a `Schedule` builder, and an
    app declares nothing about how either becomes real. Previously the
    entries were `async` functions that took a client and did the creating
    themselves — which is where each app kept its own copy of create-or-update
    and, fatally, its own unexamined assumption that a declared machine is
    always a durable server object.
    """
    declared = discovered_schedules()

    assert declared, "the tree declares periodic machinery; discovery found none"
    for declaration in declared:
        assert isinstance(declaration, ScheduleDeclaration), declaration
        assert isinstance(declaration.schedule_id(TASK_QUEUE), str)
        assert isinstance(declaration.schedule(TASK_QUEUE), Schedule)
        assert declaration.log_prefix
        assert declaration.name


def test_the_three_this_tree_declares_are_discovered_by_name() -> None:
    """Containment, never equality (the conventions' schedule-test rule).

    These three are this tree's; a product's fourth must not turn this red.
    """
    declared = discovered_schedules()

    assert {one.name for one in declared} >= {PURGE, RECONCILE_OUTBOX, RECONCILE_RUNS}
    assert workflows_activities.RECONCILE_RUNS in declared
    assert machine(PURGE).legacy_ids == (LEGACY_PURGE_ID,)


def test_an_id_is_a_function_of_the_queue_and_of_nothing_else() -> None:
    """ADR events-2, restated at the new seam: two queues, two ids.

    A schedule id is global to the Temporal namespace, so a declaration whose id
    did not vary with the queue would make every worker's startup a silent fight
    over where the sweep runs, as observed live.
    """
    for declaration in discovered_schedules():
        mine = declaration.schedule_id(TASK_QUEUE)
        theirs = declaration.schedule_id(PEER_QUEUE)
        assert mine != theirs, declaration.name
        assert TASK_QUEUE in mine and PEER_QUEUE in theirs, declaration.name


def test_both_classes_read_the_same_workflow_out_of_the_same_value() -> None:
    """Why `process` mode cannot drift from `deployment` mode.

    The workflow name, its argument, its deterministic id and its task queue are
    all read off the one `Schedule` the app declared — the same value the
    durable path hands the server. There is no second description of the machine
    anywhere for the two to disagree about.
    """
    for declaration in discovered_schedules():
        schedule = declaration.schedule(TASK_QUEUE)
        action = declared_start(declaration, queue=TASK_QUEUE)

        assert action == schedule.action
        assert action.task_queue == TASK_QUEUE
        assert action.id
        assert declared_cadence(declaration, queue=TASK_QUEUE) == schedule.spec.intervals[0].every


def test_the_declared_cadences_are_the_ones_the_apps_have_always_had() -> None:
    """The numbers, pinned where the engine now reads them.

    Generalising the seam must not have quietly changed how often anything runs.
    """
    cadence = {
        declaration.name: declared_cadence(declaration, queue=TASK_QUEUE)
        for declaration in discovered_schedules()
    }

    assert cadence[PURGE] == PURGE_EVERY
    assert cadence[RECONCILE_OUTBOX] == SWEEP_EVERY
    assert cadence[RECONCILE_RUNS] == SWEEP_EVERY
    assert cadence[RECONCILE_RUNS] == workflows_activities.RECONCILE_EVERY


def test_a_declaration_the_engine_cannot_honestly_run_is_refused() -> None:
    """Exit-2 thinking at the seam: could-not-run outranks ran-something-else.

    A declaration with two intervals, or a calendar, is a machine `process` mode
    cannot reproduce. It is refused by name rather than approximated, because an
    approximated cadence is a sweep that runs at the wrong time in exactly one
    environment and nowhere else.
    """
    from temporalio.client import ScheduleIntervalSpec, ScheduleSpec

    original = machine(PURGE).schedule(TASK_QUEUE)
    two_intervals = ScheduleDeclaration(
        name="events.two-intervals",
        schedule_id=machine(PURGE).schedule_id,
        schedule=lambda queue: Schedule(
            action=original.action,
            spec=ScheduleSpec(
                intervals=[
                    ScheduleIntervalSpec(every=PURGE_EVERY),
                    ScheduleIntervalSpec(every=SWEEP_EVERY),
                ]
            ),
        ),
        log_prefix="events",
    )

    with pytest.raises(TypeError, match="two-intervals"):
        declared_cadence(two_intervals, queue=TASK_QUEUE)


# --- 3 · deployment mode: what the template already had -----------------------


@deployment_machinery
@pytest.mark.asyncio
async def test_deployment_mode_writes_the_apps_own_declared_value_verbatim() -> None:
    """Byte-equal, at the one place a generic engine could have changed it.

    The engine composes nothing and defaults nothing: what reaches the server is
    the `Schedule` the app declared, under the id the app declared, and the test
    compares the two objects rather than describing them.
    """
    server = FakeScheduleServer()
    client: Any = server

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        for declaration in discovered_schedules():
            await ensure_declaration(client, declaration)

        expected = [
            (declaration.schedule_id(TASK_QUEUE), declaration.schedule(TASK_QUEUE))
            for declaration in discovered_schedules()
        ]

    assert server.created == expected
    assert server.updated == []


@deployment_machinery
@pytest.mark.asyncio
async def test_deployment_mode_creates_every_declared_machine_and_converges() -> None:
    """Startup, and then a restart: three schedules, never six."""
    server = FakeScheduleServer()
    client: Any = server

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        first = await ensure_schedules(client)
        second = await ensure_schedules(client)
        expected = our_ids(TASK_QUEUE)

    assert set(first) == expected
    assert set(second) == expected
    assert server.present == expected
    assert [schedule_id for schedule_id, _ in server.created] == first
    assert [schedule_id for schedule_id, _ in server.updated] == second


@deployment_machinery
@pytest.mark.asyncio
async def test_deployment_mode_still_drops_the_legacy_id_first() -> None:
    """The upgrade path ADR events-2 opened, now the engine's and still first.

    Dropped **before** the suffixed one exists, so a server holding the legacy
    schedule never briefly holds both and a worker that dies between the two
    leaves no purge rather than two.
    """
    legacy = LEGACY_PURGE_ID
    server = FakeScheduleServer(present={legacy})
    client: Any = server

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        await ensure_schedules(client)
        purge = machine(PURGE).schedule_id(TASK_QUEUE)

    assert server.deleted == [legacy]
    assert legacy not in server.present
    assert purge in server.present
    # The ordering, which is the whole of it: the old id is gone before the new
    # one exists, so no server ever holds both.
    assert server.log.index(("delete", legacy)) < server.log.index(("create", purge))


# --- 4 · process mode: no Schedule object, ever -------------------------------


@pytest.mark.asyncio
async def test_process_mode_registers_no_schedule_objects() -> None:
    """The central negative, and the positive it is worth something beside.

    Startup, a restart, and a catch-up pass: at no point does anything ask the
    server to create or update a Schedule. The same three machines are still
    driven — they are just driven by this process, which is what makes the
    machinery exactly as mortal as the identity it is keyed to.
    """
    server = FakeScheduleServer()
    client: Any = server

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        assert await ensure_schedules(client) == []
        assert await ensure_schedules(client) == []
        started = await start_declared_runs(client)

    assert server.created == []
    assert server.updated == []
    assert server.present == set()
    # ...and the machines are running all the same.
    assert len(started) == len(discovered_schedules())


@pytest.mark.asyncio
async def test_process_mode_deletes_this_checkouts_own_durable_schedules() -> None:
    """The self-clean: what an earlier build of THIS checkout left behind.

    Seeded exactly as a real upgrade finds a server — this checkout's three ids
    from when it ran in `deployment` mode, plus the legacy un-suffixed purge —
    and a peer's schedule beside them that must survive untouched.
    """
    peer = machine(PURGE).schedule_id(PEER_QUEUE)
    planted = our_ids(TASK_QUEUE) | legacy_ids() | {peer}
    server = FakeScheduleServer(present=set(planted))
    client: Any = server

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        assert await ensure_schedules(client) == []

    assert set(server.deleted) == our_ids(TASK_QUEUE) | legacy_ids()
    assert server.present == {peer}, "a peer's schedule is a live worker's, not ours to delete"
    assert server.created == []


@pytest.mark.asyncio
async def test_the_self_clean_says_what_it_removed(caplog: pytest.LogCaptureFixture) -> None:
    """A durable object removed with nothing saying so is indistinguishable from
    one that was never there — the reasoning that put a line on the legacy drop,
    now covering every id the self-clean touches, in the declaring app's own
    logging namespace."""
    planted = our_ids(TASK_QUEUE) | legacy_ids()
    server = FakeScheduleServer(present=set(planted))
    client: Any = server

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        with caplog.at_level(logging.INFO):
            await ensure_schedules(client)

    assert "events.schedule.deleted" in caplog.text
    assert "workflows.schedule.deleted" in caplog.text
    for schedule_id in planted:
        assert schedule_id in caplog.text


@pytest.mark.asyncio
async def test_a_clean_server_is_swept_quietly_and_more_than_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The common case and the idempotence: a checkout that never ran in
    `deployment` mode takes the `NOT_FOUND` branch for every id, says nothing,
    and says nothing again on the next restart."""
    server = FakeScheduleServer()
    client: Any = server

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        with caplog.at_level(logging.INFO):
            await ensure_schedules(client)
            await ensure_schedules(client)

    assert server.deleted == []
    assert "schedule.deleted" not in caplog.text


@pytest.mark.asyncio
async def test_a_delete_that_fails_for_any_other_reason_is_not_swallowed() -> None:
    """`NOT_FOUND` is the only answer that means "already clean".

    Any other RPC failure is the server telling us something, and a worker that
    started anyway would leave a durable schedule firing at a queue that is
    about to go away — which is the whole leak, survived.
    """

    class RefusingServer(FakeScheduleServer):
        def _handle(self, schedule_id: str) -> Any:
            class Handle:
                async def delete(self) -> None:
                    raise RPCError("no", RPCStatusCode.PERMISSION_DENIED, b"")

            return Handle()

    client: Any = RefusingServer(present=our_ids(TASK_QUEUE))

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        with pytest.raises(RPCError):
            await ensure_schedules(client)


# --- 5 · the catch-up property ------------------------------------------------


@pytest.mark.asyncio
async def test_startup_runs_each_declared_sweep_once_immediately() -> None:
    """The catch-up property: what a durable Schedule buys, bought differently.

    After downtime the first thing that happens is one run of each sweep, now,
    rather than a wait of up to a full cadence with the backlog the downtime
    created sitting there untouched. Each start carries the declaration's own
    workflow, argument, deterministic id and queue.
    """
    server = FakeScheduleServer()
    client: Any = server

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        started = await start_declared_runs(client)
        expected = [
            declared_start(declaration, queue=TASK_QUEUE) for declaration in discovered_schedules()
        ]

    assert started == [action.id for action in expected]
    assert [call["workflow"] for call in server.started] == [action.workflow for action in expected]
    assert [call["task_queue"] for call in server.started] == [TASK_QUEUE] * len(expected)
    assert [call["args"] for call in server.started] == [list(a.args) for a in expected]
    # Exactly once each: a catch-up pass is one run per machine, not a burst.
    assert len(server.started) == len(discovered_schedules())


@pytest.mark.asyncio
async def test_the_cadence_loop_fires_immediately_and_then_waits() -> None:
    """The loop the worker runs beside its poll loop, driven for real.

    Fire-then-sleep, not sleep-then-fire: every declared sweep has started once
    within milliseconds, and none has started twice, because the shortest
    declared cadence in this tree is five minutes. That ordering IS the
    catch-up property — a loop that slept first would leave a just-restarted
    worker sitting out a cadence before noticing the backlog it came up to
    clear.
    """
    server = FakeScheduleServer()
    client: Any = server
    wanted = len(discovered_schedules())

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        machinery = asyncio.create_task(run_declared_machinery(client))
        try:
            for _ in range(500):
                if len(server.started) >= wanted:
                    break
                await asyncio.sleep(0.01)
        finally:
            machinery.cancel()
            with pytest.raises(asyncio.CancelledError):
                await machinery

    assert len(server.started) == wanted
    assert sorted(call["id"] for call in server.started) == sorted(
        declared_start(declaration, queue=TASK_QUEUE).id for declaration in discovered_schedules()
    )


@pytest.mark.asyncio
async def test_every_start_asks_to_supersede_rather_than_to_fail_or_skip() -> None:
    """The conflict policy, read off the call rather than off the outcome.

    `TERMINATE_EXISTING` is the client-side spelling of the ruling's
    TERMINATE_IF_RUNNING: a run still open under this id when the next tick
    comes round is stale by construction — this worker started it and this
    worker has just decided the sweep should run again.
    """
    server = FakeScheduleServer()
    client: Any = server

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        await start_declared_runs(client)

    assert {call["id_conflict_policy"] for call in server.started} == {
        WorkflowIDConflictPolicy.TERMINATE_EXISTING
    }


# --- 6 · against a real server ------------------------------------------------

#: These two drive the real time-skipping server and the real discovered worker.
#: The sweeps touch the database from worker threads on their own connections,
#: which is what `transaction=True` is for — and it is marked per test rather
#: than per module, because everything above this line proves its property
#: against a stand-in and has no business paying for a truncation.
real_server = pytest.mark.django_db(transaction=True)


#: How long ONE declared machine may take to complete under the time-skipping
#: server. Generous — a healthy pass is milliseconds, because skipped time races
#: past every timer these workflows set — and its only job is to fail with a
#: NAME instead of hanging until the client gives up.
MACHINE_DEADLINE_SECONDS = 60.0


async def _completes(client: Any, workflow_id: str) -> None:
    """Await one machine, and **say which one** when it does not finish.

    Awaiting the whole set in a bare loop is what this replaces, and the reason
    is a defect this test found and could not describe.
    A workflow that never completed made the client give up with

        RuntimeError: No completion event found

    which names no machine, no activity and no cause — so the failure said only
    that *something* in a growing set of declared machines had hung, and finding
    which one cost a bisect. The set grows every time an app declares a
    schedule, so the cost of that anonymity grows with the product.

    **Every failure is attributed, not only a slow one**, and that is the half
    measured rather than assumed: a first version bounded the await with
    `asyncio.wait_for` alone and changed nothing, because under the
    time-skipping server the CLIENT gives up first — skipped time races past the
    retry backoff and `result()` raises its own anonymous `RuntimeError` at
    ~22s, well inside any honest deadline. So the bound is the belt (it catches
    the other shape, an activity scheduled and never picked up, which hangs for
    ever) and the `except Exception` is the brace. Both re-raise with the id.

    The id is house-shaped — `platform:<app>:<noun>`, house rule 18 — so the
    message names the app that owns the machine and a reader knows where to look
    before opening anything.

    The bound is **per machine and not for the whole set**, deliberately: a
    single bound around the loop would name the first machine that had not yet
    finished, which is not the same thing as the machine that is stuck.
    """
    try:
        await asyncio.wait_for(
            client.get_workflow_handle(workflow_id).result(),
            timeout=MACHINE_DEADLINE_SECONDS,
        )
    except TimeoutError as never_finished:
        raise AssertionError(_stuck(workflow_id, "did not complete")) from never_finished
    except Exception as failed:
        raise AssertionError(
            _stuck(workflow_id, f"did not complete: {type(failed).__name__}: {failed}")
        ) from failed


def _stuck(workflow_id: str, what: str) -> str:
    """The sentence a reader gets instead of `No completion event found`."""
    return (
        f"the declared machine {workflow_id!r} {what}. Under the time-skipping server a "
        "healthy machine finishes in milliseconds, so this is a run waiting on something "
        "the suite is not going to give it — an activity retrying without bound against an "
        "unreachable external service is the shape this has taken before. Look "
        "at that workflow's retry policy and its schedule_to_close_timeout first, and at "
        "whether the service it reaches is pinned in config/settings/test.py."
    )


@real_server
@pytest.mark.asyncio
async def test_the_sweeps_still_run_from_a_live_worker() -> None:
    """No Schedule object anywhere, and all three machines still run to completion.

    The whole claim of `process` mode in one test: the real worker assembly the
    worker process builds — discovered workflows, discovered activities, the
    tenant interceptor — started by this process rather than by a durable
    server object, against a real Temporal server.
    """
    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            client = attach_interceptors(env.client)
            async with build_worker(client, queue=TASK_QUEUE):
                started = await start_declared_runs(client)
                for workflow_id in started:
                    await _completes(client, workflow_id)

                descriptions = [
                    await client.get_workflow_handle(workflow_id).describe()
                    for workflow_id in started
                ]

        expected = [
            declared_start(declaration, queue=TASK_QUEUE).id
            for declaration in discovered_schedules()
        ]

    assert started == expected, "one run per declared machine, under its declared id"
    assert [one.status for one in descriptions] == [WorkflowExecutionStatus.COMPLETED] * len(
        expected
    )


@real_server
@pytest.mark.asyncio
async def test_a_stale_open_sweep_is_superseded_not_duplicated() -> None:
    """The tick that finds the last one still open, against a real server.

    Deliberately with **no worker polling**, because that is the state a stale
    sweep is actually in: an execution the server is holding open with nothing
    working on it. The next tick must not fail (the run stops for ever), must
    not skip (the sweep stops for ever), and must not duplicate under a second
    id (house rule 18, and two sweeps reading the same rows). It supersedes:
    same id, new run, old run terminated.
    """
    declaration = workflows_activities.RECONCILE_RUNS

    with override_settings(TEMPORAL_TASK_QUEUE=TASK_QUEUE):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            client = attach_interceptors(env.client)
            expected_id = declared_start(declaration, queue=TASK_QUEUE).id

            first_id = await start_declared_run(client, declaration)
            stale = await client.get_workflow_handle(first_id).describe()

            second_id = await start_declared_run(client, declaration)
            current = await client.get_workflow_handle(second_id).describe()

            superseded = await client.get_workflow_handle(first_id, run_id=stale.run_id).describe()

    assert first_id == second_id == expected_id, "one deterministic id, not two"
    assert stale.run_id != current.run_id, "a new run, not the same one re-read"
    assert superseded.status == WorkflowExecutionStatus.TERMINATED
    assert current.status == WorkflowExecutionStatus.RUNNING
