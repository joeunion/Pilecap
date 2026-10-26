"""The `archaeology` leg: the census over the active rung's changed ship-bucket files."""

from __future__ import annotations

from quality.djb.legs._library import library_leg
from quality.djb.legs._run import CAUSE
from quality.djb.registry import Leg

ARGV = (("source", "scripts/archaeology_lib.sh", "archaeology_loop"),)

LEG = Leg(
    "archaeology",
    "static",
    "archaeology-census over THE ACTIVE RUNG'S CHANGED SHIP-BUCKET FILES ONLY — publish.sh's "
    "full-artifact scan stays the belt at release",
    library_leg(
        "archaeology_loop",
        (
            "!! the archaeology-census leg COULD NOT DERIVE the changed-file set, or a",
            "   scan could not read them — see above. Nothing was judged.",
            CAUSE,
        ),
    ),
    "ledger-check",
    argv=ARGV,
)
