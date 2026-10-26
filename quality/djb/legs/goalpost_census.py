"""The `goalpost-census` leg: every instrument owns a row, and every drive the rung touched keys."""

from __future__ import annotations

from quality.djb.legs._run import checkout_python, library, say, tool
from quality.djb.registry import Ctx, Leg

ARGV = (
    ("<checkout python>", "scripts/goalpost_scan.py", "--census"),
    ("source", "scripts/secrets_scan.sh", "secrets_scan_changed_files"),
    ("source", "scripts/gate_ledger.sh", "drive_keys_of_touched"),
)
NO_VENV = (
    "!! the instrument census COULD NOT BE TAKEN: this checkout has no",
    "   .venv/bin/python, and scripts/goalpost_scan.py is a file this repository",
    "   pins at the version that venv holds. Run ./scripts/setup.sh (or",
    "   `uv sync`) first. Nothing was censused, and a census that did not",
    "   answer is never an empty one.",
)
#: The drive-key clause: the rung's changed files, then `drive_key` per touched drive.
DRIVE_KEYS = r"""
changed=$(mktemp "${TMPDIR:-/tmp}/djb-drive-keys-changed.XXXXXX")
if ! secrets_scan_changed_files "$changed"; then
    gate_cause
    rm -f "$changed"
    echo "!! the drive-key clause could not derive the active rung's changed files — see above." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    exit 2
fi
drive_keys_of_touched "$changed"
rc=$?
rm -f "$changed"
if [ "$rc" != "0" ]; then
    echo "!! a drive the active rung touched COULD NOT KEY — its body spells a checkout" >&2
    echo "   path its \`# drives:\` line does not cover (every such path is named above)." >&2
    echo "   The selftest leg refuses it at exit 2 at the bank; this is that refusal," >&2
    echo "   at commit. Declare what the drive reads, or \`# cites:\` what it only names." >&2
    exit 2
fi
"""


def census(ctx: Ctx) -> int:
    """`goalpost_scan.py --census` under the checkout's python; 2 without one."""
    py = checkout_python(ctx.root)
    if py is None:
        say(*NO_VENV)
        return 2
    return tool(ctx, (str(py), *ARGV[0][1:]))


def run(ctx: Ctx) -> int:
    """The census, then the drive-key clause; any disagreement is 2, never 1."""
    if census(ctx):
        return 2
    rc, _ = library(ctx, DRIVE_KEYS)
    return 2 if rc else 0


LEG = Leg(
    "goalpost-census",
    "static",
    "instrument census (every executable git knows about outside apps/ and config/ owes a row in "
    "instruments.md)",
    run,
    "migrations",
    argv=ARGV,
)
