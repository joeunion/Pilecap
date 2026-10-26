"""The `full-house-rules` leg: the engine's live scan, diffed against the merge-base on a branch."""

from __future__ import annotations

import subprocess

from quality.djb.legs._run import say, tool
from quality.djb.registry import Ctx, Leg

ARGV = (("uv", "run", "python", "-m", "quality.gate"),)
#: The djb leg already ran; the engine skips its own copy of it.
ENV = {"GATE_SKIP_DJANGO_LEG": "1"}
#: The branch a rung forks from; on it, or detached, the scan diffs against nothing.
MAIN = "main"


def _git(ctx: Ctx, *argv: str) -> str:
    """`git <argv>`'s stdout stripped, or empty when git said no."""
    done = subprocess.run(
        ["git", *argv], cwd=ctx.root, env=dict(ctx.env), capture_output=True, text=True
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def diff_args(ctx: Ctx) -> tuple[str, ...]:
    """`--diff <merge-base>` on a branch that is not main and has one, else nothing."""
    branch = _git(ctx, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    if branch in (MAIN, "HEAD") or not _git(ctx, "rev-parse", "--verify", "-q", MAIN):
        return ()
    base = _git(ctx, "merge-base", "HEAD", MAIN)
    return ("--diff", base) if base else ()


def run(ctx: Ctx) -> int:
    """The engine's exit; a 2 also says enforcement itself is broken."""
    rc = tool(ctx, ARGV[0] + diff_args(ctx), ENV)
    if rc == 2:
        say("!! ENFORCEMENT ITSELF IS BROKEN — this outranks any pass.")
    return rc


LEG = Leg(
    "full-house-rules",
    "full-house-rules",
    "house rules, full (live scan + diff vs merge-base when on a branch)",
    run,
    None,
    frozenset({"full"}),
    ARGV,
)
