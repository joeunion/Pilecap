# census: cross-app population=quality/runners/**,frontend/src/kit/routes.ts rule 71's reader
"""The customer surface's declared `screens` and the face's route rows name the same pages."""

from __future__ import annotations

# why-not fenced: it pairs the app with the face's rows; a Python-only copy has no rows.
import re
from importlib import import_module
from pathlib import Path

from django.conf import settings

from apps.example_portal.surfaces import SURFACES
from pilecap.testing import named

#: Rule 71's runner, by name: mypy's `apps/` check must not walk into the engine.
RUNNER = import_module("quality.runners.js_route_table")

CUSTOMER = "customer"
#: A row's `surfaces` column: the list of keys it names (a `"*"` row names none).
SURFACES_COLUMN = re.compile(r"\bsurfaces\s*:\s*\[([^\]]*)\]")
KEY = re.compile(r"[\"'`]([^\"'`]+)[\"'`]")


def _rows_on(key: str) -> set[str]:
    """The paths of the route-table rows whose `surfaces` column names `key`."""
    text = (Path(str(settings.BASE_DIR)) / RUNNER.TABLE).read_text(encoding="utf-8")
    found: set[str] = set()
    for row in RUNNER.ROW.finditer(text):
        path, column = RUNNER.PATH.search(row.group(0)), SURFACES_COLUMN.search(row.group(0))
        if path is not None and column is not None and key in KEY.findall(column.group(1)):
            found.add(path.group(2))
    return found


def test_the_route_rows_and_the_declared_screens_name_the_same_pages() -> None:
    declared = named(SURFACES[CUSTOMER].screens)

    assert declared, "the customer surface declares its screens"
    assert _rows_on(CUSTOMER) == declared
