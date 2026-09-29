"""Which live children hold a noun where it is — asked of core, answered by the children.

An archive, a restore, a move and a merge can each be held by a row in ANOTHER
app: a policy is held in the book by the live widgets that name it; a widget
with ledgered entries cannot change node. Every one of those arrows points UP
the app map — the child depends on the parent, never the other way (A2/A3) —
so a parent's `archive_<noun>` cannot import the child's selector to ask. It
does not have to.

**A child app registers; a parent asks core; no parent imports a child.** Any
installed app may drop a `<verb>_blockers.py` exporting

    BLOCKERS: dict[str, Callable[..., tuple[Blocker, ...]]] = {
        "widget_policy": policy_archive_blockers,
    }

keyed by the PARENT noun — the lower-snake kind the parent's `Blocked`
refusal carries. Each function is called keyword-only as `fn(tenant=…, obj=…)`
and answers the live children it knows of as `Blocker`s, or `()`. The parent's
service calls `blockers_for("archive", "widget_policy", tenant=…, obj=policy)`
and raises its verb's `Blocked` refusal over whatever came back.

The modules walked are `core.verbs.HOOK_MODULES`' blocker members and nothing
else: `blockers_for` takes the VERB, and a verb with no blocker module in the
closed tuple is `ValueError` before anything is imported.

**Refused loudly, naming the app**, when a module exports the wrong shape: a
`BLOCKERS` that is not a dict, a key that is not a noun word, a value that is
not callable, or a function that answers anything but a tuple of `Blocker`. A
malformed declaration that quietly counted for nothing would be a blocker that
never blocks — the silent success over a live child the family forbids.

DOES NOT COVER — declared: an app that holds a live child of a noun and
declares no function for it. The walk can only ask the apps that answer; which
children ought to block is the adopting noun's decision, and its own tests
prove its rows.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from apps.core import verbs
from apps.core.exceptions import Blocker

#: The verbs a child may hold, each walked through its `<verb>_blockers` module.
BLOCKER_VERBS: tuple[str, ...] = tuple(
    module.removesuffix("_blockers")
    for module in verbs.HOOK_MODULES
    if module.endswith("_blockers")
)

#: The attribute every blocker module exports.
ATTRIBUTE = "BLOCKERS"

_NOUN = re.compile(r"^[a-z][a-z0-9_]*$")

BlockerFn = Callable[..., tuple[Blocker, ...]]


def _module(verb: str) -> str:
    if verb not in BLOCKER_VERBS:
        raise ValueError(
            f"blockers_for takes a family verb that can be held — one of "
            f"{', '.join(BLOCKER_VERBS)}; got {verb!r}."
        )
    return f"{verb}_blockers"


def declared_blockers(verb: str) -> list[tuple[str, dict[str, BlockerFn]]]:
    """Every installed app's `<verb>_blockers.BLOCKERS`, in app order, with its label.

    Not cached, for `lifecycle`'s reason: a held verb is a rare press, and a
    cache here would be a stale answer in the one process that reloads modules
    for a living — the test suite.
    """
    module = _module(verb)
    found: list[tuple[str, dict[str, BlockerFn]]] = []
    for config, declared in verbs.hook(module):
        where = f"apps/{config.label}/{module}.py"
        for noun, fn in declared.items():
            if not isinstance(noun, str) or not _NOUN.match(noun):
                raise ImproperlyConfigured(
                    f"{where}: `{ATTRIBUTE}` key {noun!r} is not a noun word — the parent's "
                    "kind in lower snake case, as its `Blocked` refusal spells it."
                )
            if not callable(fn):
                raise ImproperlyConfigured(
                    f"{where}: `{ATTRIBUTE}[{noun!r}]` is not callable; it answers "
                    "`fn(tenant=…, obj=…) -> tuple[Blocker, ...]`."
                )
        found.append((config.label, declared))
    return found


def blockers_for(verb: str, noun: str, *, tenant: Any, obj: Any) -> tuple[Blocker, ...]:
    """Every live child any installed app says holds `obj` (a `noun`) against `verb`.

    Calls every registered function for `noun`, in app order, and concatenates.
    `()` means nothing holds it — the verb may go ahead.
    """
    if not _NOUN.match(noun):
        raise ValueError(f"blockers_for takes the parent's noun word; got {noun!r}.")
    module = _module(verb)
    held: list[Blocker] = []
    for label, declared in declared_blockers(verb):
        fn = declared.get(noun)
        if fn is None:
            continue
        answer = fn(tenant=tenant, obj=obj)
        if not isinstance(answer, tuple) or not all(isinstance(entry, Blocker) for entry in answer):
            raise ImproperlyConfigured(
                f"apps/{label}/{module}.py: `{ATTRIBUTE}[{noun!r}]` answered "
                f"{type(answer).__name__}, not a tuple of Blocker."
            )
        held.extend(answer)
    return tuple(held)
