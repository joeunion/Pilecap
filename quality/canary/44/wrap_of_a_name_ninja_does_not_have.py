"""Planted: a third wrap of a ninja private that does not exist.

The shape `config/api.py` already uses twice — read the inner through
`getattr`, rebind the attribute with a wrapper — aimed at a name the installed
django-ninja does not define. This is what a ninja rename looks like from the
inside once somebody has written against the new name by hand, and it is the
predicate the census exists to answer: the attribute we hold is still there.
"""

from typing import Any


def _guard_the_dispatch(operation: Any) -> None:
    inner = getattr(operation, "_dispatch_the_request", None)
    if inner is None:
        raise RuntimeError("this ninja Operation has no `_dispatch_the_request`")

    def dispatch(request: Any) -> Any:
        return inner(request)

    operation._dispatch_the_request = dispatch
