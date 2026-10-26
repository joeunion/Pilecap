"""The `ledger-check` leg: the dispatch ledger's shape."""

from __future__ import annotations

from quality.djb.legs._run import CAUSE, callee, checkout_python, could_not_look, say
from quality.djb.registry import Ctx, Leg

ARGV = (("<checkout python>", "scripts/ledger_check.py", "--check"),)


def run(ctx: Ctx) -> int:
    """`ledger_check.py --check`: 1 names each refused row, 2 carries its own `!!` sentence."""
    py = checkout_python(ctx.root)
    if py is None:
        return could_not_look(
            ctx,
            "the dispatch ledger could not be checked: this checkout has no .venv/bin/python",
            "!! the dispatch ledger could not be checked: this checkout has no .venv/bin/python",
            "   Run ./scripts/setup.sh (or `uv sync`) first.",
        )
    rc, cause = callee(ctx, (str(py), *ARGV[0][1:]))
    if rc == 2:
        return could_not_look(
            ctx, cause, "!! the dispatch ledger COULD NOT BE CHECKED — see above.", CAUSE
        )
    if rc:
        say(
            "!! the dispatch ledger refused: each `!! ledger-check:` line above names a row of",
            "   docs/product/in-flight.md (or an armed archive row) and what it lacks. The PM "
            "fixes the row.",
        )
    return rc


LEG = Leg(
    "ledger-check",
    "static",
    "the derived ledger's inputs — every brief's header block, no orphan report, no hand table "
    "in the live file, every armed archive row seven cells, stamped on dated clocks and pointed",
    run,
    "queue-index",
    argv=ARGV,
)
