"""The `engine_share` fixture: a test's engine scans on its xdist worker's share of the cores."""

from __future__ import annotations

import os

import pytest

from quality import scan_ahead

#: xdist's own count of the session's workers, exported into every worker.
WORKER_COUNT = "PYTEST_XDIST_WORKER_COUNT"


def share(cores: int, workers: int) -> int:
    """The scan processes one worker's engine may start: its share of the cores, at least one."""
    return max(1, cores // max(1, workers))


@pytest.fixture(autouse=True)
def engine_share(monkeypatch: pytest.MonkeyPatch) -> str | None:
    """`DJB_RULES_WORKERS` at this worker's share under xdist; a typed value or no xdist is kept."""
    workers = os.environ.get(WORKER_COUNT, "")
    if os.environ.get(scan_ahead.WORKERS_ENV) or not workers.isdigit():
        return os.environ.get(scan_ahead.WORKERS_ENV)
    value = str(share(os.cpu_count() or 1, int(workers)))
    monkeypatch.setenv(scan_ahead.WORKERS_ENV, value)
    return value
