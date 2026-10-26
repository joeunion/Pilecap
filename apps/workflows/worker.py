"""The Temporal worker process: `python -m apps.workflows.worker`.

It is a second process beside the web one, polling the task queue this worktree
owns. Django is set up first, because activities use the ORM.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress

import django

# The worker is the second service in the deployment, and the sink has to be
# able to tell the two apart. Set before `django.setup()`, because that is what
# builds the OTel resource.
os.environ.setdefault("DJB_SERVICE_NAME", "worker")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
django.setup()

from django.conf import settings  # noqa: E402

from apps.core.log import get_logger  # noqa: E402
from apps.workflows.client import (  # noqa: E402
    build_worker,
    ensure_schedules,
    get_client,
    machinery_lifetime,
    run_declared_machinery,
    task_queue,
)

log = get_logger(__name__)


async def run() -> None:
    client = await get_client()
    worker = build_worker(client)
    # The declared machinery is made real here, once, before the worker starts
    # polling: a periodic machine is part of the deployment, and a worker that is
    # up while its housekeeping is not is a deployment that quietly stopped
    # tidying up. What "made real" means is the deployment's declared lifetime
    # class (ADR platform-lifecycle-1), and this process does not decide it:
    #
    # * `deployment` — durable Temporal Schedules, created or rewritten,
    #   idempotently, so a restart converges rather than duplicating. `ensured`
    #   names them.
    # * `process` — no Schedule object is created at all; the durable ones an
    #   earlier build of THIS checkout left behind are deleted, `ensured` is
    #   empty, and the sweeps run from the loop below for as long as this worker
    #   lives.
    ensured = await ensure_schedules(client)
    lifetime = machinery_lifetime()
    log.info(
        "workflows.worker.started",
        task_queue=task_queue(),
        workflows=len(worker.config()["workflows"]),
        activities=len(worker.config()["activities"]),
        schedules=len(ensured),
        machinery_lifetime=lifetime,
    )
    if lifetime != str(settings.MACHINERY_PROCESS):
        await worker.run()
        return

    # Process-mode machinery is not background work in the sense the house rules
    # forbid — it starts the very workflows a Temporal Schedule would have
    # started, standing exactly where the schedule stands in the other class, and
    # it dies with this process by design. It is cancelled the moment the poll
    # loop returns, so a worker that has stopped polling is not still starting
    # sweeps nobody will run.
    machinery = asyncio.create_task(run_declared_machinery(client))
    try:
        await worker.run()
    finally:
        machinery.cancel()
        with suppress(asyncio.CancelledError):
            await machinery


def main() -> None:
    # Logging is configured by `CoreConfig.ready` during `django.setup()` above;
    # `core/observability.py` is the only module that does that (house rule 19).
    asyncio.run(run())


if __name__ == "__main__":
    main()
