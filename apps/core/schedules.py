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

from temporalio.client import Schedule


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
