"""The one reader of what the doors mounted: the API's operations, and the face's route table.

Several readers in core report on the mount — the system checks (rules 3, 17,
32, 74, 83), `introspect`, the family's per-row acts, the MCP scope derivation
and the welcome page — and each used to walk `config.api`'s bound routers its
own way. They agreed, so a severed reader was a red only one caller noticed
(ADR core-24: three private re-derivations of one fact drift apart silently).
`bound_operations()` is the one walk, and every one of them calls it.

`config` mounts `apps` and an app never imports `config`; this module is the
one named exemption for the API mount (as `introspect` and `checks` are for
their own reads), and it imports `config.api` lazily, inside the call, because
a module-level import would run the whole mount while the app registry is
still populating.

`route_table_paths()` is the face's half of the same question — which screens
the route table declares — read through `apps.core.route_table`, pinned equal
to house rule 71's runner, never through `quality/`, which the image does not carry.

DOES NOT COVER — declared: a route mounted outside the NinjaAPI (a plain
Django view — `checks.first_party_plain_views` reads those off the resolver);
a route-table row the runner's pattern does not recognise (rule 71's own
`does_not_cover`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings

from apps.core import route_table, script_source
from apps.core.roads import road


@road("mount_read", example="apps/core/tests/test_mount_reader.py::test_one_cut_reds_every_reader")
def bound_operations() -> list[tuple[str, str, Any]]:
    """Every operation the live API mounts: `(path, url_name, operation)`, in mount order.

    The path is relative to the API's own mount and spelled the way the
    document shows it — segments in, one slash between, a trailing slash when
    the route had one — because the raw join of a prefix that has its slashes
    to a path that has its own reads `//connections///`, a correct answer
    nobody can search for. A route that ends in a slash keeps it, and so does
    one mounted AT its prefix (`""` under `widgets/` is `/widgets/`) — the URL
    a caller types. The `url_name` is `""` for an operation that carries none.
    """
    from config.api import api

    out: list[tuple[str, str, Any]] = []
    for bound in api._get_bound_routers():
        for path, path_view in bound.path_operations.items():
            joined = f"{bound.prefix}/{path}"
            segments = [part for part in joined.split("/") if part]
            trailing = "/" if joined.endswith("/") or not segments else ""
            full = "/" + "/".join(segments) + trailing
            for operation in path_view.operations:
                out.append((full, str(operation.url_name or ""), operation))
    return out


def route_table_paths() -> frozenset[str] | None:
    """Every row `path` of the face's route table, by rule 71's reader; `None` with no table."""
    table = Path(settings.BASE_DIR) / route_table.TABLE
    if not table.is_file():
        return None
    source = script_source.read(table)
    if source is None:
        return None
    paths: set[str] = set()
    for row in route_table.ROW.finditer(source.code):
        found = route_table.PATH.search(row.group(0))
        if found is not None:
            paths.add(str(found.group(2)))
    return frozenset(paths)
