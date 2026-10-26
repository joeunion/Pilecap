"""The Temporal client, the task queue and the worker assembly.

This lives in `apps.workflows` rather than in `config/` because of the one-way
rule: **`config` may import `apps`; an app never imports `config`.** A service
that had to reach up into `config/` to start a workflow was a cycle waiting to
happen and an import-linter contract that could not be written, so the worker
assembly is here and `scripts/worker.sh` runs it.

Settings are read directly (`settings.TEMPORAL_*`), which is what every other
app does with its own configuration.

Discovery: an app joins durable work by exposing `WORKFLOWS: list[type]` in
`workflows.py` and `ACTIVITIES: list[Callable]` in `activities.py`. Nothing here
is edited when an app is added, and the walk is `apps.core.discovery.declared` —
the same road `introspect` reads the population through, so the worker and the
schema dump cannot disagree about what is registered.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import ModuleType
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.common import WorkflowIDConflictPolicy
from temporalio.contrib.opentelemetry import TracingInterceptor
from temporalio.service import RPCError, RPCStatusCode
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions

from apps.core.discovery import declared
from apps.core.log import get_logger
from apps.core.schedules import ScheduleDeclaration
from apps.workflows.context import TenantContextInterceptor

log = get_logger(__name__)

# Both interceptors, always, in this order: the tenant one carries who and which
# chain, the OTel one carries the trace across the process boundary between the
# service that started a workflow and the worker that ran it. Without the
# second, a trace stops at `start_workflow` and the work it caused looks
# unrelated — which is exactly the question a workflow exists to answer.
INTERCEPTORS: tuple[type, ...] = (TenantContextInterceptor, TracingInterceptor)

# Activities in this repository are plain `def` (the convention: sync ORM work,
# run off the workflow's event loop). Temporal needs an executor to run them in
# and refuses a pool smaller than the concurrency it is allowed to schedule, so
# the two numbers are declared together, here, once.
MAX_CONCURRENT_ACTIVITIES = 20

#: Modules the workflow sandbox takes from the worker process instead of importing fresh per run.
SANDBOX_PASSTHROUGH: tuple[str, ...] = (
    #: A finalizer's import, not a workflow's: a leaked pool's `__del__` run by GC in an activation.
    "redis",
)


def task_queue() -> str:
    """The queue this deployment's worker polls."""
    return str(settings.TEMPORAL_TASK_QUEUE)


async def get_client(*, target_host: str | None = None, namespace: str | None = None) -> Client:
    """Connect to Temporal with the interceptors attached."""
    return await Client.connect(
        target_host or str(settings.TEMPORAL_ADDRESS),
        namespace=namespace or str(settings.TEMPORAL_NAMESPACE),
        interceptors=[cls() for cls in INTERCEPTORS],
    )


def attach_interceptors(client: Client) -> Client:
    """The same connection, with the interceptors attached.

    `get_client` builds one that already has them. A client somebody else built
    — the workflow test environment's, for instance — needs this applied
    explicitly, or the tenant and the trace never leave the process that started
    the workflow. The worker picks the same interceptors up off its client, so
    attaching them here covers both sides.
    """
    config = client.config()
    interceptors = list(config.get("interceptors") or [])
    missing = [
        cls() for cls in INTERCEPTORS if not any(isinstance(one, cls) for one in interceptors)
    ]
    if not missing:
        return client
    config["interceptors"] = [*interceptors, *missing]
    return Client(**config)


def _discover(module_suffix: str, attribute: str) -> list[Any]:
    """Collect one exported list from every installed `apps.*` that has it.

    A caller of the one discovery walk (`apps.core.discovery.declared`), never
    a second walk: `introspect` reads `WORKFLOWS` and `ACTIVITIES` through the
    same road with the same list shape, so what the worker registers and what
    the schema dump reports are one answer.
    """
    return [
        entry
        for _config, declared_list in declared(module_suffix, attribute, predicate=_is_list)
        for entry in declared_list
    ]


def _is_list(value: Any) -> bool:
    """The shape a discovered `WORKFLOWS`, `ACTIVITIES` or `SCHEDULES` takes."""
    return isinstance(value, list)


def discovered_workflows() -> list[type]:
    """Every `WORKFLOWS` entry in the installed apps."""
    return list(_discover("workflows", "WORKFLOWS"))


def discovered_activities() -> list[Callable[..., Any]]:
    """Every `ACTIVITIES` entry in the installed apps."""
    return list(_discover("activities", "ACTIVITIES"))


def discovered_schedules() -> list[ScheduleDeclaration]:
    """Every `SCHEDULES` entry in the installed apps, as declarations.

    Periodic work is declared with the code, never as cron and never as beat
    (`architecture.md`): the machine ships with the app and its last run is
    visible where the runs are. An app declares one by exposing
    `SCHEDULES: list[ScheduleDeclaration]` in its `activities.py`, and that
    entry is **data** — an id builder and a `Schedule` value
    (`apps.core.schedules`). Discovery, like everything else: no app edits the
    worker to add one.

    It used to be a list of `async` functions that took a client and did the
    creating themselves, which meant every app carried its own copy of
    create-or-update, its own legacy-drop, and — fatally for ADR
    platform-lifecycle-1 — its own unexamined assumption that a declared machine
    becomes a durable server object. **The apps now declare what; this module
    decides how**, and the how is the lifetime class.
    """
    return list(_discover("activities", "SCHEDULES"))


def machinery_lifetime() -> str:
    """This deployment's declared lifetime class for periodic machinery.

    Read from settings and from nothing else. There is no branch test here, no
    checkout-name test, no "does this look like a worktree" heuristic: the class
    is declared in a settings module or in the environment (ADR
    platform-lifecycle-1), and a seam that guessed from a name would be wrong
    the first time a real deployment ran out of a directory called `worktree`.
    """
    return str(settings.TEMPORAL_MACHINERY_LIFETIME)


def _schedule_event(declaration: ScheduleDeclaration, verb: str) -> str:
    """`<app>.schedule.<verb>` — the declaring app's own logging namespace.

    Built one line above the log call rather than inside it, so the call's first
    argument stays a name and never becomes an f-string (house rule 19). The
    prefix comes off the declaration because generalising this engine must not
    quietly rename every app's log events out from under whoever greps them.
    """
    return ".".join((declaration.log_prefix, "schedule", verb))


async def delete_schedule(client: Client, schedule_id: str) -> bool:
    """Delete one schedule if it is there. Returns whether there was one.

    **Only `NOT_FOUND` is swallowed.** Any other RPC failure is the server
    telling us something, and a worker that started anyway would leave the
    schedule running against a queue that is about to go away — which is the
    whole leak. Generalised from `events.drop_legacy_purge_schedule`, whose
    reasoning this is.
    """
    try:
        await client.get_schedule_handle(schedule_id).delete()
    except RPCError as error:
        if error.status is RPCStatusCode.NOT_FOUND:
            return False
        raise
    return True


async def put_schedule(client: Client, *, schedule_id: str, schedule: Schedule) -> bool:
    """Create one schedule, or bring the one already there up to date.

    Returns whether it was **created** — false means it was already there and
    has just been rewritten — so the caller can say which happened without
    asking the server a second question it already answered.

    Idempotent in both directions, which is what lets the worker run it at every
    startup: a fresh server gets a schedule, a restarted one gets this build's
    definition written over the last build's, and neither ends with two.
    """
    try:
        await client.create_schedule(schedule_id, schedule)
        return True
    except ScheduleAlreadyRunningError:
        pass

    def _replace(_input: ScheduleUpdateInput) -> ScheduleUpdate:
        return ScheduleUpdate(schedule=schedule)

    await client.get_schedule_handle(schedule_id).update(_replace)
    return False


async def ensure_declaration(client: Client, declaration: ScheduleDeclaration) -> str:
    """One declaration, made real as a durable Schedule. Returns its id.

    The `deployment` half of the engine, and byte-for-byte what the two apps
    used to do for themselves: drop the legacy ids **first**, so a server
    holding one never briefly has both, then create-or-update under the
    queue-suffixed id.
    """
    queue = task_queue()
    for legacy in declaration.legacy_ids:
        if await delete_schedule(client, legacy):
            log.info(_schedule_event(declaration, "deleted"), schedule_id=legacy)
    schedule_id = declaration.schedule_id(queue)
    created = await put_schedule(
        client, schedule_id=schedule_id, schedule=declaration.schedule(queue)
    )
    log.info(
        _schedule_event(declaration, "created" if created else "updated"),
        schedule_id=schedule_id,
    )
    return schedule_id


async def drop_declaration(client: Client, declaration: ScheduleDeclaration) -> list[str]:
    """One declaration, unmade: every durable id it could have created, gone.

    The `process` half's self-cleaning startup. It deletes **this checkout's
    own** ids — the one this declaration takes on this task queue, and the
    legacy ones this app has always dropped — and nobody else's: a schedule on a
    peer's queue belongs to a worker that may be alive, and deleting it is the
    rejected worker-shutdown design wearing a different hat (ADR
    platform-lifecycle-1).

    Idempotent and quiet in the common case: a checkout that has never run in
    `deployment` mode takes the `NOT_FOUND` branch for every id and logs
    nothing. A deletion that did happen is logged, because a durable object
    removed with nothing saying so is indistinguishable from one that was never
    there — the same reasoning that put a log line on the legacy purge drop.
    """
    dropped: list[str] = []
    for schedule_id in (declaration.schedule_id(task_queue()), *declaration.legacy_ids):
        if await delete_schedule(client, schedule_id):
            log.info(_schedule_event(declaration, "deleted"), schedule_id=schedule_id)
            dropped.append(schedule_id)
    return dropped


def declared_start(declaration: ScheduleDeclaration, *, queue: str) -> ScheduleActionStartWorkflow:
    """What the declaration's `Schedule` says to start — read off the value.

    This is what makes `process` mode run **the same sweeps** rather than a
    parallel set that can drift: the workflow name, its argument, its
    deterministic id and its task queue are all read out of the one `Schedule`
    the app declared, so the two lifetime classes cannot come to disagree about
    what the machine is.
    """
    action = declaration.schedule(queue).action
    if not isinstance(action, ScheduleActionStartWorkflow):
        raise TypeError(
            f"{declaration.name} declares a schedule whose action is not a workflow start; "
            "a declared machine is a workflow, and this engine can run nothing else."
        )
    return action


def declared_cadence(declaration: ScheduleDeclaration, *, queue: str) -> timedelta:
    """How often the declaration says to run — read off the same value.

    One interval, because that is the only spec shape this repository declares
    (`ScheduleIntervalSpec`, in both apps). A declaration that grew a calendar
    or a cron expression would be a machine `process` mode cannot honestly
    reproduce, so it is refused here rather than approximated: an approximated
    cadence is a sweep that runs at the wrong time in exactly one environment.
    """
    intervals = declaration.schedule(queue).spec.intervals
    if len(intervals) != 1:
        raise TypeError(
            f"{declaration.name} declares {len(intervals)} intervals; process-mode machinery "
            "runs one interval per declaration and will not guess at a calendar."
        )
    return intervals[0].every


async def start_declared_run(client: Client, declaration: ScheduleDeclaration) -> str:
    """Start one declared sweep now, under its own deterministic id.

    **`TERMINATE_EXISTING`**, which is the client-side spelling of the
    `TERMINATE_IF_RUNNING` behaviour the ruling names: a run still open under
    this id when the next tick comes round is a *stale* one — the worker that
    started it is this worker, and it has just decided the sweep should run
    again — so it is superseded rather than duplicated or skipped. The id is the
    one the declaration already carries (house rule 18: nothing here constructs
    a new one).

    In `deployment` mode the server appends the scheduled time to that id, so an
    actual run is `<id>-2026-08-24T14:13:48Z`; here the id is used bare, which
    is what makes the supersede possible at all. Both are the same declared
    prefix, and neither is random.
    """
    queue = task_queue()
    action = declared_start(declaration, queue=queue)
    handle = await client.start_workflow(
        action.workflow,
        args=list(action.args),
        id=action.id,
        task_queue=action.task_queue,
        id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
    )
    log.info("workflows.machinery.started", workflow_id=handle.id, declaration=declaration.name)
    return str(handle.id)


async def start_declared_runs(client: Client) -> list[str]:
    """Every declared sweep, started once, now. **The catch-up pass.**

    What a `deployment` schedule buys and a live worker otherwise would not:
    after downtime, the first thing that happens is one run of each sweep,
    immediately, rather than a wait of up to a full cadence with the backlog the
    downtime created sitting there untouched.

    `run_declared_machinery` performs the same pass as the first move of each
    declaration's own loop — fire, then sleep — so the catch-up is the loop's
    opening rather than a separate step somebody could forget to call. This
    function is that pass on its own, for a caller that wants one round and no
    cadence.
    """
    started: list[str] = []
    for declaration in discovered_schedules():
        started.append(await start_declared_run(client, declaration))
    return started


async def run_declared_machinery(client: Client) -> None:
    """Run every declared sweep on its own cadence, for as long as this lives.

    The `process` half of ADR platform-lifecycle-1: no durable object is created
    anywhere, and the machinery is exactly as mortal as the worker that declared
    it — which is the honest lifetime class for an identity derived from a
    checkout that will be deleted.

    Catch-up first, then wait: each declaration fires immediately and then on
    its declared interval, so a worker that has just come up does not sit out a
    cadence before noticing the backlog it came up to clear.

    An `asyncio` task per declaration and not a workflow, deliberately, and it
    is not the exception to "anything that waits or retries is a workflow": this
    IS the thing that starts the workflows, standing exactly where the Temporal
    Schedule stands in the other class. It does no work of its own and it owns
    no state — it starts a run and sleeps.

    A failure to start one sweep is logged and the cadence continues. The
    alternative is a worker whose machinery loop died on one bad tick and whose
    other two sweeps stopped with it, silently: the failure mode this whole
    rung exists to remove, reintroduced one layer in.
    """
    queue = task_queue()

    async def tick(declaration: ScheduleDeclaration) -> None:
        every = declared_cadence(declaration, queue=queue).total_seconds()
        while True:
            try:
                await start_declared_run(client, declaration)
            except Exception as failure:  # noqa: BLE001 - one bad tick is not the end of the loop
                log.warning(
                    "workflows.machinery.tick_failed",
                    declaration=declaration.name,
                    error=str(failure),
                )
            await asyncio.sleep(every)

    declarations = discovered_schedules()
    if not declarations:
        return
    await asyncio.gather(*(tick(declaration) for declaration in declarations))


async def ensure_schedules(client: Client) -> list[str]:
    """Make the declared machinery real, in this deployment's lifetime class.

    Called by the worker at startup, and the one entry point either class goes
    through. Returns the **schedule ids** it created or updated — which is the
    empty list in `process` mode, because that class creates no Schedule object
    ever, and the worker's log line says so honestly instead of counting
    functions it called.

    * **`deployment`** — every declaration becomes a durable Schedule, created
      or rewritten, exactly as before this seam existed. Idempotent by
      construction, so every restart converges on the same set.
    * **`process`** — nothing is created. Every id this checkout could have
      created durably is deleted first (the self-clean), and the sweeps
      themselves are started by `run_declared_machinery`, which the worker runs
      beside its poll loop.
    """
    declarations = discovered_schedules()
    if machinery_lifetime() == settings.MACHINERY_PROCESS:
        for declaration in declarations:
            await drop_declaration(client, declaration)
        return []
    return [await ensure_declaration(client, declaration) for declaration in declarations]


#: The two keywords that bound one activity attempt at its call site. An
#: attempt is bounded by `start_to_close_timeout` when the call names one, and
#: by `schedule_to_close_timeout` only when it names nothing narrower.
_ATTEMPT_BOUNDS = ("start_to_close_timeout", "schedule_to_close_timeout")


def _timeout_value(module: ModuleType, node: ast.expr, where: str) -> timedelta:
    """Resolve one call-site timeout expression without executing anything new.

    Three shapes are read: a module-level name (`start_to_close_timeout=X`, the
    house form), a dotted attribute off one (`types.X`), and a literal
    `timedelta(...)` whose arguments are constants. Anything else is refused,
    naming the site — a graceful window derived from a timeout it could not
    read would be a number that only looks derived.
    """
    if isinstance(node, ast.Name | ast.Attribute):
        path: list[str] = []
        cursor: ast.expr = node
        while isinstance(cursor, ast.Attribute):
            path.insert(0, cursor.attr)
            cursor = cursor.value
        if isinstance(cursor, ast.Name) and hasattr(module, cursor.id):
            value: Any = getattr(module, cursor.id)
            for attribute in path:
                value = getattr(value, attribute, None)
            if isinstance(value, timedelta):
                return value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name | ast.Attribute)
        and (node.func.id if isinstance(node.func, ast.Name) else node.func.attr) == "timedelta"
    ):
        try:
            args = [ast.literal_eval(arg) for arg in node.args]
            kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords if kw.arg}
            return timedelta(*args, **kwargs)
        except (ValueError, TypeError, SyntaxError):
            pass
    raise ImproperlyConfigured(
        f"{where}: an activity timeout the worker's graceful shutdown cannot read "
        f"({ast.unparse(node)}). Declare it as a module-level timedelta constant and "
        "pass the name — the worker waits for the longest declared attempt on shutdown, "
        "and a timeout it cannot read is one it would not wait for."
    )


def activity_timeouts_declared_in(module: ModuleType) -> dict[str, timedelta]:
    """Every activity-attempt bound one module's call sites declare, by `file:line`.

    Read from the module's source (the call sites), resolved against the
    module's own namespace (the constants), so the number is the one the
    workflow really passes — never a copy of it.
    """
    filename = inspect.getsourcefile(module) or getattr(module, "__file__", "") or module.__name__
    with open(filename, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=filename)
    found: dict[str, timedelta] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        named = {kw.arg: kw.value for kw in node.keywords if kw.arg in _ATTEMPT_BOUNDS}
        for bound in _ATTEMPT_BOUNDS:
            if bound in named:
                where = f"{filename}:{named[bound].lineno}"
                found[where] = _timeout_value(module, named[bound], where)
                break
    return found


def declared_activity_timeouts() -> dict[str, timedelta]:
    """The attempt bound at every activity call site of every discovered workflow."""
    modules = {sys.modules[cls.__module__] for cls in discovered_workflows()}
    found: dict[str, timedelta] = {}
    for module in sorted(modules, key=lambda one: one.__name__):
        found.update(activity_timeouts_declared_in(module))
    return found


def worker_graceful_shutdown() -> timedelta:
    """How long a stopping worker waits for in-flight activities. DERIVED, never typed.

    The longest single attempt any discovered workflow allows an activity
    (`declared_activity_timeouts`). Temporal's own default is zero
    (`temporalio/worker/_worker.py`, `graceful_shutdown_timeout=timedelta()`),
    which cancels every running activity the instant a worker is asked to stop
    — a SIGTERM mid-delivery, or every `async with build_worker(...)` exit in a
    test. Waiting as long as the longest declared attempt means no attempt
    that could legitimately still be running is cut off; a product that
    declares a longer one moves this with it and edits nothing here
    (ADR workflows-8). No call site at all is zero: nothing can be in flight.
    """
    return max(declared_activity_timeouts().values(), default=timedelta())


def activity_slots() -> int:
    """How many activities run at once: the pool less one, for the main loop's record_run_id."""
    if not settings.DATABASE_POOL_ENABLED:
        return MAX_CONCURRENT_ACTIVITIES
    return max(1, min(MAX_CONCURRENT_ACTIVITIES, int(settings.DATABASE_POOL_MAX_SIZE) - 1))


def workflow_runner() -> SandboxedWorkflowRunner:
    """Temporal's default sandbox, with `SANDBOX_PASSTHROUGH` taken from the worker process."""
    return SandboxedWorkflowRunner(
        restrictions=SandboxRestrictions.default.with_passthrough_modules(*SANDBOX_PASSTHROUGH)
    )


class _PoolClosingWorker(Worker):
    """A `Worker` that shuts down the executor it was handed. **Temporal does not.**

    `Worker.__aexit__` shuts the worker down and leaves an externally supplied
    `activity_executor` running — reasonably, since it never owned it — so the
    pool's threads survive the `async with` and are only reaped when the garbage
    collector gets to them. Each of those threads holds a Django database
    connection, and under `pytest-xdist` (ADR gate-1) that GC now races the test
    database teardown of the worker's own process: `database
    "test_..._gwN" is being accessed by other users`, a warning attached to
    whichever test happened to finish last.

    Closing the pool where the worker closes itself makes the lifetime explicit
    instead of leaving it to the collector. `shutdown()` is documented safe for
    repeated invocation and `Executor.shutdown()` is idempotent, so the pair
    still is.
    """

    def __init__(self, *args: Any, activity_executor: ThreadPoolExecutor, **kwargs: Any) -> None:
        super().__init__(*args, activity_executor=activity_executor, **kwargs)
        self._activity_pool = activity_executor

    async def shutdown(self) -> None:
        await super().shutdown()
        self._activity_pool.shutdown(wait=True)


def build_worker(client: Client, *, queue: str | None = None) -> Worker:
    """One worker, holding everything every app declared.

    It waits `worker_graceful_shutdown()` for in-flight activities when asked
    to stop, instead of Temporal's zero-second default.
    """
    return _PoolClosingWorker(
        attach_interceptors(client),
        task_queue=queue or task_queue(),
        workflows=discovered_workflows(),
        activities=discovered_activities(),
        workflow_runner=workflow_runner(),
        activity_executor=ThreadPoolExecutor(
            max_workers=activity_slots(),
            thread_name_prefix="temporal-activity-",
        ),
        max_concurrent_activities=activity_slots(),
        graceful_shutdown_timeout=worker_graceful_shutdown(),
    )
