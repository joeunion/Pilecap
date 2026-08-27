"""The Temporal mount.

The client factory, the task queue and the worker assembly live in
`apps.workflows.client` — an app owns its platform, and **`config` may import
`apps` while an app never imports `config`** (import-linter enforces both
directions). This module is the mount the build contract names, and it is a
re-export: `python -m apps.workflows.worker` and every caller keep working
whichever name they reach for, and nothing below `config` points upward.

Discovery is unchanged: an app joins durable work by exposing
`WORKFLOWS: list[type]` in `workflows.py` and `ACTIVITIES: list[Callable]` in
`activities.py`. Nothing here is edited when an app is added.
"""

from __future__ import annotations

from apps.workflows.client import (
    attach_interceptors,
    build_worker,
    discovered_activities,
    discovered_workflows,
    get_client,
    task_queue,
)

__all__ = [
    "attach_interceptors",
    "build_worker",
    "discovered_activities",
    "discovered_workflows",
    "get_client",
    "task_queue",
]
