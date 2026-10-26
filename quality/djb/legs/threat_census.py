"""The `threat-census` leg: every door and noun owns a threat-model row, every citation resolves."""

from __future__ import annotations

from quality.djb.legs._run import CAUSE, callee, checkout_python, could_not_look
from quality.djb.registry import Ctx, Leg

ARGV = (("<checkout python>", "scripts/threat_census.py"),)


def run(ctx: Ctx) -> int:
    """`threat_census.py`: 0 the ledger closes; 2 it does not, or it could not be read."""
    py = checkout_python(ctx.root)
    if py is None:
        return could_not_look(
            ctx,
            "the threat model could not be censused: this checkout has no .venv/bin/python",
            "!! the threat model could not be censused: this checkout has no .venv/bin/python",
            "   Run ./scripts/setup.sh (or `uv sync`) first.",
        )
    rc, cause = callee(ctx, (str(py), *ARGV[0][1:]))
    if rc:
        return could_not_look(
            ctx,
            cause,
            "!! the threat model DOES NOT CLOSE — each `!! threat-census:` line above names the",
            "   door, noun, HIPAA row or citation; write the row in docs/product/threat-model.md.",
            CAUSE,
        )
    return 0


LEG = Leg(
    "threat-census",
    "static",
    "threat-model census (every door and noun owns a row in docs/product/threat-model.md, every "
    "HIPAA 164.312 row is filled, every file:line it cites resolves)",
    run,
    "collectstatic",
    frozenset({"full"}),
    ARGV,
)
