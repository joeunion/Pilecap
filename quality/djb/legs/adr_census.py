"""The `adr-census` leg: every ADR id the rung's changed files cite resolves."""

from __future__ import annotations

from quality.djb.legs._library import library_leg
from quality.djb.legs._run import CAUSE
from quality.djb.registry import Leg

ARGV = (("source", "scripts/docs_legs.sh", "docs_adr_census_loop"),)

LEG = Leg(
    "adr-census",
    "static",
    "every ADR id cited in THE ACTIVE RUNG'S CHANGED FILES resolves to its file in the tree's "
    "ADR directory "
    "— publish.sh's whole-artifact scan stays the belt",
    library_leg(
        "docs_adr_census_loop",
        (
            "!! the adr-census leg COULD NOT LOOK — see above. The changed-file set, an",
            "   ADR directory or the citation scan was unreadable, so nothing was judged: this",
            "   is neither a finding nor a pass.",
            CAUSE,
        ),
    ),
    "archaeology",
    argv=ARGV,
)
