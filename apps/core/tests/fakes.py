"""The Temporal stand-ins every app's tests share, once (a superset; two copies drift)."""

from __future__ import annotations

from typing import Any

from temporalio.client import Schedule, ScheduleAlreadyRunningError
from temporalio.service import RPCError, RPCStatusCode


class FakeScheduleServer:
    """The client's schedules API, recording every question asked of it.

    Hand-written because the time-skipping test server has no schedules API and
    pointing a test at the dev server is forbidden. It answers `create`,
    `update` and `delete` — `ensure_schedules` is cross-app, so driving it
    drives every installed app's entries, legacy drops included — and it also
    records `start_workflow`, because the central claim of `process` mode is a
    **negative** (no schedule is ever created), and a negative is only worth
    anything beside the positive that replaced it.
    """

    def __init__(self, *, present: set[str] | None = None) -> None:
        self.present: set[str] = set(present or ())
        self.created: list[tuple[str, Schedule]] = []
        self.updated: list[tuple[str, Schedule]] = []
        self.deleted: list[str] = []
        self.started: list[dict[str, Any]] = []
        #: Every question in order: the legacy drop must land BEFORE the suffixed create.
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
