"""The `house-rules` leg: the engine's live scan and its diff against HEAD, its exit unmapped."""

from __future__ import annotations

import re

from quality.djb.legs._run import captured, say
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "python", "-m", "quality.gate", "--diff", "HEAD"),)
#: The djb leg already ran; the engine skips its own copy of it.
ENV = {"GATE_SKIP_DJANGO_LEG": "1"}
#: The engine's sentence that a budget moved, the one condition the offer is printed under.
BUDGET = re.compile(r"^[ \t]*(x )?budget: ", re.MULTILINE)
OFFER = (
    "",
    "  offer: ./scripts/rung_tidy.sh --budgets",
    "    It writes the ceiling(s) the line(s) above named into quality/budgets.yaml,",
    "    in the working tree, staging nothing. A RAISE is a decision and stays in",
    "    the caller's own diff where a reviewer reads it; a LOWERING note is not",
    "    applied here — that one is the fold's, at the bank, under its own subject.",
)


def argv_for(ctx: Ctx) -> tuple[str, ...]:
    """The engine's argv under `ctx`'s mode: `--terse` in `--loop`."""
    return ARGV[0] + (("--terse",) if ctx.mode == "loop" else ())


def run(ctx: Ctx) -> int:
    """The engine's verdict; a red carrying a `budget:` line also prints the tidy's offer."""
    rc, text = captured(ctx, argv_for(ctx), ENV)
    if rc and BUDGET.search(text):
        print("\n".join(OFFER), flush=True)
    if rc == 2:
        say("!! ENFORCEMENT ITSELF IS BROKEN — this outranks any pass.")
    return rc


LEG = Leg(
    "house-rules",
    "static",
    "house rules (quality/rules.yaml — live scan + diff vs HEAD)",
    run,
    "djb-checks",
    argv=ARGV,
)
