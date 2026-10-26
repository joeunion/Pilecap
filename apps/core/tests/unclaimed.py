"""A scratch key no app on this tree declares — a template case's word a product may have taken."""

from __future__ import annotations

from collections.abc import Iterable


def unclaimed(stem: str, taken: Iterable[str]) -> str:
    """`stem`, lengthened by `x` until nothing in `taken` holds it."""
    held = set(taken)
    key = stem
    while key in held:
        key += "x"
    return key


def unclaimed_role(stem: str) -> str:
    """A role key no `roles.py` on this tree declares, `stem` on the template."""
    from apps.core.authz import role_declarations

    return unclaimed(stem, role_declarations())


def unclaimed_surface(stem: str) -> str:
    """A surface key no `surfaces.py` on this tree declares, `stem` on the template."""
    from apps.core import surfaces

    return unclaimed(stem, surfaces.declared())
