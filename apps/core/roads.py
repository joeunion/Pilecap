"""The marker a road carries: `@road("<job>", example="<path>::<symbol>")`.

A job is a thing this platform does exactly one way; a road is the one
mechanism that does it; this decorator is how a road in importable Python says
which job it does. It stores `__road__ = {"job": ..., "example": ...}` on the
target, appends `(job, target)` to `REGISTRY`, and returns the target
unchanged. A module that IS the road marks itself once, after its imports:
`ROAD = road("<job>", example=...)(sys.modules[__name__])`.

It refuses at import — `ValueError`, naming the target and the missing part —
a job key outside `[a-z][a-z0-9_]{1,31}`, an empty example, a target defined
inside a function (a road is a module-level definition, the only kind a static
reader can see), or a target with no docstring, because the docstring's first
line is the road's contract and a contract typed a second time beside it would
be two sentences about one thing.

Standard library only: the quality engine imports this without a settings
module. The static reader of these markers, and `manage.py roads`, read the
files; `REGISTRY` exists to prove a marker the files show really imports.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

JOB_KEY = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

REGISTRY: list[tuple[str, object]] = []


def road(job: str, *, example: str) -> Callable[[T], T]:
    """Mark the decorated object as the one road for `job`, citing its worked example."""
    if not isinstance(job, str) or not JOB_KEY.match(job):
        raise ValueError(
            f"road({job!r}): the job key must match {JOB_KEY.pattern} — one "
            "lowercase word or noun_verb, never a medium, a file name or an app label"
        )
    if not isinstance(example, str) or not example.strip():
        raise ValueError(
            f"road({job!r}): the example is empty — name a worked instance as <path>::<symbol>"
        )

    def mark(target: T) -> T:
        name = getattr(target, "__qualname__", None) or getattr(target, "__name__", repr(target))
        if "<locals>" in str(getattr(target, "__qualname__", "")):
            raise ValueError(f"road({job!r}): a road is a module-level definition: {name}")
        doc = getattr(target, "__doc__", None)
        if not isinstance(doc, str) or not doc.strip():
            raise ValueError(
                f"road({job!r}) on {name}: the target has no docstring — "
                "its first line is the road's contract"
            )
        # A marker attribute on any object — a function, a class or a module.
        target.__road__ = {"job": job, "example": example}  # type: ignore[attr-defined]
        REGISTRY.append((job, target))
        return target

    return mark
