"""The harness for `quality/tests`: the plugin's hooks, and every fixture module in `fixtures/`."""

from __future__ import annotations

import os
from pathlib import Path

from quality.tests.harness import (  # noqa: F401
    fixtures_in,
    pytest_addoption,
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_report_teststatus,
    pytest_runtest_logreport,
    pytest_runtest_makereport,
    pytest_sessionfinish,
    pytest_terminal_summary,
    pytest_testnodedown,
)

#: The fixture worlds are data a test copies or reads, never modules this harness collects.
collect_ignore = ["fixtures"]

#: The real-time ceiling on a step a timeout bounds: CI's 4 cores under xdist, not the Mac's.
REAL_TIME_CEILING_S = 60 if os.environ.get("GITHUB_ACTIONS") == "true" else 20

globals().update(
    fixtures_in(
        Path(__file__).parent / "fixtures", f"{__package__}.fixtures" if __package__ else None
    )
)
