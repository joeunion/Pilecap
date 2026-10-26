"""The search engine seam, replaced for one test: the one factory answers the test's engine."""

from __future__ import annotations

from typing import Any

import pytest

from apps.search import engine as factory


def replace_search_engine(monkeypatch: pytest.MonkeyPatch, engine: Any) -> None:
    """The one engine factory every search write and the chokepoint call answers `engine`."""
    monkeypatch.setattr(factory, "engine", lambda: engine)
