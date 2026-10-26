"""The verifier box client: `scripts/verifier_box.sh`'s subcommands, one module per family."""

from __future__ import annotations

from typing import Any

from quality.djb.box.core import Box, Config, commands, load_config
from quality.djb.box.transport import Refused, Transport

__all__ = ["Box", "Config", "Refused", "Transport", "commands", "load_config"]


def __getattr__(name: str) -> Any:
    """Every module's `cmd_*` by its name, found through the registry; no module is listed here."""
    for command in commands().values():
        if command.__name__ == name:
            return command
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """The names above and every registered `cmd_*`."""
    return sorted({*globals(), *(command.__name__ for command in commands().values())})
