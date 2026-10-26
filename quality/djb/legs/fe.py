"""The `fe` leg: the face's four states over `frontend/`, run by `fe_gate.sh`."""

from __future__ import annotations

from quality.djb.legs._run import library
from quality.djb.registry import Ctx, Leg

ARGV = (
    ("source", "scripts/secrets_scan.sh", "secrets_scan_changed_files"),
    ("source", "scripts/fe_gate.sh", "fe_leg_run"),
)
#: The rung's changed files, then the four-state leg over them under this run's mode.
BODY = r"""
changed=$(mktemp "${TMPDIR:-/tmp}/djb-fe-changed.XXXXXX")
if ! secrets_scan_changed_files "$changed"; then
    gate_cause
    echo "!! the fe leg could not derive the active rung's changed files — see above." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    rm -f "$changed"
    exit 2
fi
fe_leg_run "$changed" "$MODE"
rc=$?
rm -f "$changed"
exit "$rc"
"""


def run(ctx: Ctx) -> int:
    """`fe_leg_run` over the rung's changed files: 0 clean or skipped, 1 a finding, 2 no look."""
    return library(ctx, BODY)[0]


LEG = Leg(
    "fe",
    "static",
    "the fe leg — four states (absent/untouched/suspect/full) over frontend/; full runs the "
    "frozen-lockfile install, the face's declared typecheck, lint and test scripts and the byte "
    "pin; the full gate and its --leg shards always run it full",
    run,
    "plant-collisions",
    frozenset({"loop", "full"}),
    ARGV,
)
