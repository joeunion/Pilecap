"""Every events test resolves a subscriber's host through a stand-in, never through DNS."""

from __future__ import annotations

import pytest

from apps.events import targets
from apps.events.tests.stand_in import PUBLIC_ADDRESS


@pytest.fixture(autouse=True)
def resolved_hosts(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[str]]:
    """Host -> addresses the door and the delivery see; an unlisted host is public."""
    answers: dict[str, list[str]] = {}

    def resolve(host: str) -> list[str]:
        return answers.get(host, [PUBLIC_ADDRESS])

    monkeypatch.setattr(targets, "resolve_host", resolve)
    return answers


@pytest.fixture
def no_dns(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A resolver that records every host it is asked about; the test asserts it stays empty."""
    asked: list[str] = []

    def record(host: str) -> list[str]:
        asked.append(host)
        return [PUBLIC_ADDRESS]

    monkeypatch.setattr(targets, "resolve_host", record)
    return asked
