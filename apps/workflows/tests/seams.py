"""The workflow client seam, replaced for one test: every dial the platform makes is the test's."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from apps.workflows import client


def replace_workflow_client(
    monkeypatch: pytest.MonkeyPatch, connect: Callable[[], Awaitable[Any]]
) -> None:
    """Every Temporal client the platform dials, the on-commit start's included, is `connect`'s."""
    monkeypatch.setattr(client, "get_client", connect)
