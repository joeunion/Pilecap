"""The `ruff` leg: lint, then the format check."""

from __future__ import annotations

from quality.djb.legs._run import tool
from quality.djb.registry import Ctx, Leg

ARGV = (
    ("uv", "run", "ruff", "check", "."),
    ("uv", "run", "ruff", "format", "--check", "--quiet", "."),
)


def run(ctx: Ctx) -> int:
    """Lint the tree, then check its formatting; the first non-zero exit."""
    for argv in ARGV:
        rc = tool(ctx, argv)
        if rc:
            return rc
    return 0


LEG = Leg("ruff", "static", "ruff (lint + format check)", run, "db-pin", argv=ARGV)
