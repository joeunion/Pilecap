"""The flat permission census's document and the one command that re-derives it."""

from __future__ import annotations

#: The document, re-derived in place on the template whenever a role moves.
BASELINE = "apps/core/tests/flat_product_baseline.json"
BASELINE_COMMAND = (
    "uv run python manage.py shell -c "
    '"from apps.core.tests.permissions_world import write_flat_product_baseline as w; '
    "w('apps/core/tests/flat_product_baseline.json')\""
)

#: A noun's own sweep, inside the noun golden; it writes the noun's baseline only when asked.
NOUN_SWEEP = "tests/test_noun_authz.py"
#: The variable that asks it to: set, the sweep writes; unset, a missing file is red.
BASELINE_WRITE = "DJB_BASELINE_WRITE"
#: The red a missing file is without the variable.
BASELINE_MISSING = (
    "baseline missing: {path} — run " + BASELINE_WRITE + "=1 uv run pytest {sweep} once from "
    "your checkout and commit the file it writes"
)
#: The line the first run prints beside the file it wrote.
BASELINE_WRITTEN = (
    "baseline written: {path} — read it, commit it; a later change in a role's answer is a "
    "finding here"
)


def noun_baseline(label: str, noun: str) -> str:
    """The baseline path the noun sweep reads off `_meta`: `<model_name>_authz_baseline.json`."""
    return f"apps/{label}/tests/{noun.lower()}_authz_baseline.json"
