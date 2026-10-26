"""The `queue-index` leg: the generated queue index against its record."""

from __future__ import annotations

from quality.djb.legs._run import CAUSE, callee, checkout_python, could_not_look, say
from quality.djb.registry import Ctx, Leg

ARGV = (("<checkout python>", "scripts/queue_index.py", "--check"),)


def run(ctx: Ctx) -> int:
    """`queue_index.py --check`: 2 carries the script's own `!!` sentence as its cause."""
    py = checkout_python(ctx.root)
    if py is None:
        return could_not_look(
            ctx,
            "the queue index could not be checked: this checkout has no .venv/bin/python",
            "!! the queue index could not be checked: this checkout has no .venv/bin/python",
            "   and scripts/queue_index.py is a file this repository pins at the version",
            "   that venv holds. Run ./scripts/setup.sh (or `uv sync`) first.",
        )
    rc, cause = callee(ctx, (str(py), *ARGV[0][1:]))
    if rc == 2:
        return could_not_look(
            ctx,
            cause,
            "!! the queue index COULD NOT BE CHECKED — see above.",
            CAUSE,
            "   Nothing was judged. An index whose record is gone, or a record beside an",
            "   index somebody replaced by hand, is not a clean ledger — it is a ledger",
            "   nobody can read against its own source.",
        )
    if rc:
        say(
            "!! docs/product/queue.md is not what scripts/queue_index.py generates from",
            "   docs/product/queue-detail.md, or the two disagree about a row, or a",
            "   ratchet was passed. The index is DERIVED: edit the record and run",
            f"   `{py} scripts/queue_index.py --index` — this checkout's own",
            "   interpreter, which is what the generated header names too. A hand-edited",
            "   index is two truths in the one file every other document defers to for",
            "   order.",
        )
    return rc


LEG = Leg(
    "queue-index",
    "static",
    "the queue's index vs its record — the generated index is what queue_index.py generates, "
    "every anchor has one index row and back, both ratchets hold",
    run,
    "goalpost-census",
    argv=ARGV,
)
