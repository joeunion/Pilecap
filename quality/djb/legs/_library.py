"""A leg whose body is one function of a sourced shell library, its cause carried out on 2."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from quality.djb.legs._run import could_not_look, library
from quality.djb.registry import Ctx


def library_leg(call: str, banner: Sequence[str]) -> Callable[[Ctx], int]:
    """A body running `call` over the libraries; 2 prints `banner` with the recorded cause."""

    def run(ctx: Ctx) -> int:
        rc, cause = library(ctx, call)
        if rc == 2:
            return could_not_look(ctx, cause, *banner)
        return rc

    run.__doc__ = (
        f"`{call.split()[0]}` from its library; 2 is could-not-look with the cause it recorded."
    )
    return run
