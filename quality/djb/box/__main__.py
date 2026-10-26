"""`python -m quality.djb.box <subcommand> [args…]`: the dispatcher over every module's `cmd_*`."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Sequence

from quality.djb.box.core import Box, load_config, run_command, usage
from quality.djb.box.transport import Refused, die, warn


def refuse_if_piped(env: dict[str, str]) -> None:
    """Refuse a piped stdout outside CI: the exit status is the verdict."""
    if env.get("CI"):
        return
    try:
        piped = stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        piped = False
    if piped:
        die(
            "verifier_box refuses pipes — run it bare or redirect to a file.\n"
            "   The exit status is the verdict, and a filter replaces it."
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch one subcommand: 0, the remote's own status, or 2 for a refusal."""
    args = list(sys.argv[1:] if argv is None else argv)
    env = dict(os.environ)
    try:
        refuse_if_piped(env)
        cfg = load_config(env)
        sub = args[0] if args else ""
        if sub in ("", "-h", "--help"):
            return usage()
        return run_command(Box(cfg), sub, args[1:])
    except Refused as refused:
        if not refused.printed:
            warn(f"!! {refused}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
