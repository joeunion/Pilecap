"""An object's own state, and the interpreter's protocol. Neither is a wrap.

`self._cache = ...` is what a private attribute is FOR, and `__module__` /
`__wrapped__` are names Python itself defines on every object — censusing
either would turn a rule about somebody else's internals into a rule against
ordinary Python, which is how a check comes to be worked around instead of
read.
"""

from typing import Any


class Ledger:
    def __init__(self) -> None:
        self._entries: list[str] = []
        self._closed = False

    def close(self) -> None:
        self._closed = True


def relabel(view: Any, source: Any) -> None:
    view.__module__ = source.__module__
    view.__wrapped__ = source
