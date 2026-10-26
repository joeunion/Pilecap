"""The `import-linter` leg: the layer contracts."""

from __future__ import annotations

from quality.djb.legs._run import tool
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "lint-imports"),)


def run(ctx: Ctx) -> int:
    """`lint-imports` over the declared contracts; its exit."""
    return tool(ctx, ARGV[0])


LEG = Leg("import-linter", "static", "import-linter (layer contracts)", run, "mypy", argv=ARGV)
