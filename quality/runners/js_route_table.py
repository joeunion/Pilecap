"""The route table, censused against the pages — the runner half. (patterns.md §0)

    python3 quality/runners/js_route_table.py <root> [<root> …]

THE CLOSED QUESTION: does the route table — `frontend/src/kit/routes.ts`,
the head of the book — name exactly the routes the app router draws? The
router discovers a route from a file (`frontend/src/app/**/page.tsx`), so a
page can land with nobody having said what the route is FOR; the table is
where every route's one job, the seat of its primary act and the operation it
draws are written down, and every surface that needs "which page draws this"
(the nav, a remedy's link) reads it instead of keeping a list of its own.

BOTH DIRECTIONS, and the row's form:

* a page with no row — a route nobody said the job of;
* a row with no page — a door onto a 404;
* a row missing a column (`path` · `job` · `primarySeat` · `operation`) — the
  operation column is how a remedy naming an operation finds the page that
  draws it, so a row without it is a row that cannot answer;
* two rows for one path.

A route is its page's directory under `frontend/src/app/`, with route groups
`(…)` and parallel slots `@…` dropped and dynamic segments (`[id]`) kept
verbatim: `app/page.tsx` is `/`, `app/(shop)/cart/page.tsx` is `/cart`. A row
is an object literal in the table file carrying a `path:` string.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import (  # noqa: E402
    _css,
    _kindscope,  # noqa: E402
    _source,
)

TABLE = "frontend/src/kit/routes.ts"
APP = ("frontend", "src", "app")
PAGE_STEM = "page"
COLUMNS = ("path", "job", "primarySeat", "operation")

ROW = re.compile(r"\{[^{}]*\}")
PATH = re.compile(r"\bpath\s*:\s*([\"'`])([^\"'`\n]*)\1")


def route_of(page: Path) -> str:
    parts = [
        p
        for p in page.parts[len(APP) : -1]
        if not (p.startswith("(") and p.endswith(")")) and not p.startswith("@")
    ]
    return "/" + "/".join(parts)


def main(argv: list[str]) -> int:
    findings: list[dict] = []
    pages: dict[str, str] = {}
    for root in argv:
        for path in _kindscope.files_under(Path(root), _css.SUFFIXES, under=_css.SRC_ROOT):
            if path.parts[: len(APP)] != APP or path.suffix not in _source.SCRIPT_SUFFIXES:
                continue
            if path.stem != PAGE_STEM:
                continue
            pages.setdefault(route_of(path), str(path))

    tables = 0
    rows: dict[str, int] = {}
    table = Path(TABLE)
    src = _source.read(table) if table.is_file() else None
    if src is None:
        findings.append(
            {
                "path": TABLE,
                "line": 1,
                "msg": (
                    f"the route table `{TABLE}` is not in this tree — every page the app router "
                    "draws owes a row saying its one job, where its primary act sits and the "
                    "operation it draws (patterns.md §0)"
                ),
                "klass": "table-missing",
            }
        )
    else:
        tables = 1
        for m in ROW.finditer(src.code):
            body = m.group(0)
            found = PATH.search(body)
            if not found:
                continue
            route = found.group(2)
            line = src.line_of(m.start() + found.start())
            missing = [c for c in COLUMNS if not re.search(rf"(?<![\w$]){c}\s*:", body)]
            if missing:
                findings.append(
                    {
                        "path": TABLE,
                        "line": line,
                        "msg": (
                            f"the row for `{route}` has no "
                            + ", ".join(f"`{c}`" for c in missing)
                            + " column — a row is path · job · primarySeat · operation, and "
                            "`null` is an answer where a route has no act or draws no operation"
                        ),
                        "klass": "row-form",
                    }
                )
            if route in rows:
                findings.append(
                    {
                        "path": TABLE,
                        "line": line,
                        "msg": (
                            f"`{route}` has a second row (the first is line {rows[route]}) "
                            "— one route, one job"
                        ),
                        "klass": "row-duplicate",
                    }
                )
                continue
            rows[route] = line
        for route, line in rows.items():
            if route not in pages:
                findings.append(
                    {
                        "path": TABLE,
                        "line": line,
                        "msg": (
                            f"the route table has a row for `{route}` and no page under "
                            "`frontend/src/app/` draws it — a row with no page is a door onto a 404"
                        ),
                        "klass": "row-unpaged",
                    }
                )

    for route, page in sorted(pages.items()):
        if route not in rows:
            findings.append(
                {
                    "path": page,
                    "line": 1,
                    "msg": (
                        f"the page `{page}` draws the route `{route}` and the route table "
                        f"(`{TABLE}`) has no row for it — write its one job, the seat of its "
                        "primary act and the operation it draws (patterns.md §0)"
                    ),
                    "klass": "page-unrowed",
                }
            )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(pages) + tables,
                    "pages": len(pages),
                    "route_tables": tables,
                    "rows": len(rows),
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
