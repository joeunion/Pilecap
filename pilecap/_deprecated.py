"""The deprecation shim: an old spelling served through a module `__getattr__`, logged once."""

# A facade module declares `DEPRECATED = {"old": Deprecation(...)}`, `__getattr__ = shim(...)`.

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from apps.core.log import get_logger

#: The three ways a public name leaves the SDK (rule 97).
KINDS = ("removed", "renamed", "signature")
#: The structured event every served old spelling logs, once per process per name.
EVENT = "pilecap.deprecated"

log = get_logger(__name__)
_logged: set[str] = set()

__all__: list[str] = []


@dataclass(frozen=True)
class Deprecation:
    """One name on its way out: since and until are releases, `instead` the name to use."""

    since: str
    until: str
    instead: str
    kind: Literal["removed", "renamed", "signature"]
    #: A `signature` entry's old→new text; a `removed` entry's dotted path to the object served.
    change: str = ""


def target(module: str, dotted: str) -> Any:
    """The object `dotted` names: `pilecap.<m>.<name>`, `apps.<…>.<name>`, or a name in `module`."""
    home, _, name = dotted.rpartition(".") if "." in dotted else (module, "", dotted)
    return getattr(importlib.import_module(home), name)


def shim(module: str, table: Mapping[str, Deprecation]) -> Callable[[str], Any]:
    """The module `__getattr__` that serves each deprecated spelling and logs it once."""

    def __getattr__(name: str) -> Any:
        entry = table.get(name)
        if (
            entry is None
            or entry.kind == "signature"
            or (entry.kind == "removed" and not entry.change)
        ):
            raise AttributeError(f"module {module!r} has no attribute {name!r}")
        key = f"{module}.{name}"
        if key not in _logged:
            _logged.add(key)
            log.warning(
                EVENT, name=key, since=entry.since, until=entry.until, instead=entry.instead
            )
        return target(module, entry.change if entry.kind == "removed" else entry.instead)

    return __getattr__
