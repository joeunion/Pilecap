"""The pieces every app's `api.py` builds its routes out of.

A list endpoint in this repository is the same shape in every app — paginated,
filtered, ordered from an allow-list, searchable with `q` — because a client
that has learned one of them has learned all of them, and because each of those
four is a place to get tenancy or an N+1 wrong exactly once instead of once per
app.

The package also carries `core`'s own routes, in `routes.py` — the tenancy and
hierarchy doors. It once held no routes and no `router`, true of a package
that only held helpers; the re-exports below are what `config/api.py`'s
discovery reads, because discovery imports
`apps.<label>.api` and looks for `router`, `PREFIX` and `TAGS` on that module.
Routes live one file down rather than here so the helpers every OTHER app builds
its routes out of stay separable from the routes this app happens to own.
"""

from apps.core.api.pagination import CursorPagination
from apps.core.api.query import ordered_by, searched
from apps.core.api.routes import PREFIX, TAGS, router

__all__ = [
    "PREFIX",
    "TAGS",
    "CursorPagination",
    "ordered_by",
    "router",
    "searched",
]
