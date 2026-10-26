"""The `db-pin` leg: this checkout's `.env` database pin against the derivation."""

from __future__ import annotations

from quality.djb.legs._run import CAUSE, could_not_look, library
from quality.djb.registry import Ctx, Leg

ARGV = (("source", "scripts/db.sh", "db_pin_leg"),)


def run(ctx: Ctx) -> int:
    """`db_pin_leg <mode>`: 1 a stale pin, 2 an unread `.env` with the recorded cause."""
    rc, cause = library(ctx, f"db_pin_leg {ctx.mode}")
    if rc == 2:
        return could_not_look(
            ctx,
            cause,
            "!! the db-pin leg COULD NOT LOOK — see above. An unread .env is not an",
            "   absent one: nothing was compared, so this is neither a finding nor a pass.",
            CAUSE,
        )
    return rc


LEG = Leg(
    "db-pin",
    "static",
    "DATABASE_NAME: this checkout's .env pin vs the derivation",
    run,
    None,
    argv=ARGV,
)
