"""The shape a periodic machine is declared in — and nothing that runs one.

Two apps in this tree declare periodic machinery (`apps.events`' purge and
outbox relay, `apps.workflows`' run sweep) and `import-linter` holds the
platform apps **independent of one another**, so neither may own the shape the
other declares in. It sits below both, here, for the same reason
`apps.core.bridge` does: a seam every layer can reach without anybody reaching
sideways.

**It is data, not behaviour.** A declaration says *what* a machine is — the id
it takes on a given task queue, and the `Schedule` value that describes the
work and its cadence — and says nothing about how that becomes real. Who
creates it, whether it is created at all, and what happens instead is the
engine's business (`apps.workflows.client`), which is the whole of ADR
platform-lifecycle-1: **machinery durability follows the identity's declared
lifetime class**, and an app must not have to know which class it is running
under.

Both builders take the task queue rather than reading it, because
`TEMPORAL_TASK_QUEUE` is derived per checkout and a test that could not vary it
could not prove the derivation matters (ADR events-2).

Stdlib and `temporalio` types only: no ORM, no client, no settings read. A
declaration is safe to build at import.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from apps.core.roads import road


@dataclass(frozen=True)
class ScheduleDeclaration:
    """One declared periodic machine, as data.

    `name` is the stable handle a log line, a census or a report uses to say
    *which* machine — it is not the schedule id, which varies by task queue.

    `log_prefix` is the app's own logging namespace, so that generalising the
    engine did not silently rename every app's log events out from under
    whoever greps for them. The engine composes `<log_prefix>.schedule.<verb>`.

    `legacy_ids` are ids an **older build of this app** created and that this
    one must clean up wherever it finds them, in every lifetime class. They are
    constants rather than builders because that is what a legacy id is: a name
    from before the id was derived from anything (`events-purge-expired`, the
    un-suffixed schedule that ADR events-2 replaced).
    """

    name: str
    schedule_id: Callable[[str], str]
    schedule: Callable[[str], Schedule]
    log_prefix: str
    legacy_ids: tuple[str, ...] = ()


# --- the factory: one id shape, one cadence, one signature --------------------
#
# Every periodic machine the platform owns used to spell its own ids — thirteen
# prefixes, five `platform:` and eight `system:`, two machines spelled both ways
# in one tree — and `apps.workflows.services.check_workflow_id` accepts only
# `platform:` for a run no tenant owns (house rule 18). The factory mints the one
# shape for the schedule and for the run it starts, so a `system:` id cannot be
# declared through it. The grammar is restated below, beside the minting, because
# `core` may not import `apps.workflows` (the fixed layer direction);
# `apps/core/tests/test_schedules.py` holds the two equal by asking
# `check_workflow_id` itself to accept every id the factory mints.

#: The first segment of a run no tenant owns (`apps.workflows.services.PLATFORM_SEGMENT`).
PLATFORM_SEGMENT = "platform"

#: Between the id's four segments — `apps.workflows.services.ID_SEPARATOR`'s value.
ID_SEPARATOR = ":"

#: A sweep's cadence: daily, the cadence every purge in the tree already ran at.
DAILY = timedelta(days=1)


def platform_id(*, app: str, noun: str, key: str) -> str:
    """`platform:<app>:<noun>:<key>` — four non-empty segments, none holding the separator."""
    parts = {"app": app, "noun": noun, "key": key}
    for name, part in parts.items():
        text = str(part).strip()
        if not text or ID_SEPARATOR in text:
            raise ValueError(
                f"A platform id segment must be non-empty and contain no {ID_SEPARATOR!r}; "
                f"{name} was {part!r}."
            )
    return ID_SEPARATOR.join((PLATFORM_SEGMENT, *(str(p).strip() for p in parts.values())))


def platform_schedule(
    *,
    app: str,
    noun: str,
    workflow: str,
    every: timedelta,
    name: str,
    arg: Any = None,
    log_prefix: str | None = None,
    legacy_ids: tuple[str, ...] = (),
) -> ScheduleDeclaration:
    """A periodic platform machine: one `platform:<app>:<noun>:<queue>` id, schedule and run.

    Keyed by the task queue, because two deployments sharing a Temporal
    namespace must never fight over one execution; `SKIP` on overlap, because
    two of one sweep at once read the same rows. The run's id is the PREFIX
    Temporal is given — the server appends the scheduled time.
    """

    def schedule_id(task_queue: str) -> str:
        return platform_id(app=app, noun=noun, key=task_queue)

    def schedule(task_queue: str) -> Schedule:
        run_id = platform_id(app=app, noun=noun, key=task_queue)
        args = () if arg is None else (arg,)
        return Schedule(
            action=ScheduleActionStartWorkflow(workflow, *args, id=run_id, task_queue=task_queue),
            spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=every)]),
            policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
        )

    return ScheduleDeclaration(
        name=name,
        schedule_id=schedule_id,
        schedule=schedule,
        log_prefix=log_prefix or app,
        legacy_ids=legacy_ids,
    )


# No Widget example: Widget does not adopt this road yet, so the example is a core test.
@road(
    "daily_purge",
    example="apps/core/tests/test_schedules.py::test_the_factory_mints_one_platform_id",
)
def daily_purge(
    *,
    app: str,
    noun: str,
    workflow: str,
    arg: Any,
    name: str | None = None,
    log_prefix: str | None = None,
    legacy_ids: tuple[str, ...] = (),
) -> ScheduleDeclaration:
    """An app's daily sweep, declared once: `platform:<app>:<noun>:<queue>`, `SKIP`, every day.

    The retention rides on `arg` — the workflow's input — so an operator reads
    the window off the schedule in the Temporal UI rather than out of the
    source. The sweep the workflow runs has ONE signature,
    `(*, before: datetime, tenant: None) -> core.types.Swept`: a cut-off, the
    platform population, and the population-shaped answer its audit row files.
    """
    return platform_schedule(
        app=app,
        noun=noun,
        workflow=workflow,
        every=DAILY,
        arg=arg,
        name=name or f"{app}.{noun}",
        log_prefix=log_prefix,
        legacy_ids=legacy_ids,
    )
