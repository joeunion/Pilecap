"""The deployment's first-retry interval, read on the Django side for a workflow's argument."""

from __future__ import annotations

from django.conf import settings

from apps.core.roads import road


@road("retry_floor", example="apps/djb_imports/services.py::create_import")
def retry_floor_seconds() -> float:
    """The deployment's first-retry interval in seconds; a workflow reads it from its argument."""
    return float(settings.TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS)
