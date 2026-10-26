"""The `deploy-check` leg: `check --deploy` under production settings and a throwaway env."""

from __future__ import annotations

from quality.djb.legs._run import tool
from quality.djb.legs._throwaway import production_env
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "python", "manage.py", "check", "--deploy", "--fail-level", "WARNING"),)


def run(ctx: Ctx) -> int:
    """`manage.py check --deploy --fail-level WARNING`; settings only, no connection."""
    return tool(ctx, ARGV[0], production_env())


LEG = Leg(
    "deploy-check",
    "static",
    "check --deploy (production settings, throwaway env)",
    run,
    "collection-census",
    frozenset({"loop", "full"}),
    ARGV,
)
