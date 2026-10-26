"""The `plant-collisions` leg: no plant carries a name the tree serves, undeclared."""

from __future__ import annotations

from quality.djb.legs._run import say, tool
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "python", "-m", "quality.gate", "--plant-collisions"),)


def run(ctx: Ctx) -> int:
    """The engine's plant-collision census; any non-zero answer is 2, never a finding."""
    rc = tool(ctx, ARGV[0])
    if rc:
        say(
            f"!! plant-collisions: the census answered exit {rc} — the refusals above name each "
            f"plant, its",
            "   name and the real site; an undeclared collision is broken enforcement (exit 2), "
            "never a finding.",
        )
        return 2
    return 0


LEG = Leg(
    "plant-collisions",
    "static",
    "plant-collision census — no plant carries a name the tree serves (introspect + an @service "
    "walk) unless it declares the collision on the plant",
    run,
    "deploy-check",
    frozenset({"loop", "full"}),
    ARGV,
)
