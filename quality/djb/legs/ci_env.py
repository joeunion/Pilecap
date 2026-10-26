"""The `ci-env` leg: every name the settings read and the stack sets is in each gate env."""

from __future__ import annotations

from quality.djb.legs._library import library_leg
from quality.djb.legs._run import CAUSE
from quality.djb.registry import Leg

ARGV = (("source", "scripts/docs_legs.sh", "docs_ci_env_leg"),)

LEG = Leg(
    "ci-env",
    "static",
    "every name config/ reads from the environment and the dev stack sets is a key in every "
    "gate-running workflow's env — the runner's stack is the one the settings describe",
    library_leg(
        "docs_ci_env_leg",
        (
            "!! the ci-env leg COULD NOT LOOK — see above. The settings file, the",
            "   development stack's own values or the workflow's indentation was",
            "   unreadable, or the derived population came out empty.",
            CAUSE,
            "   A green over nothing is the one verdict this leg may never print.",
        ),
    ),
    "dangling-docs",
    argv=ARGV,
)
