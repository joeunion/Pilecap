"""The `mypy` leg: the strict type check over what `pyproject.toml` names."""

from __future__ import annotations

from quality.djb.legs._run import tool
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "mypy"),)


def run(ctx: Ctx) -> int:
    """`mypy --strict` over `[tool.mypy] files`; its exit."""
    return tool(ctx, ARGV[0])


LEG = Leg("mypy", "static", "mypy --strict ([tool.mypy] files)", run, "sdk-reference", argv=ARGV)
