"""`pool_budget.py workers <class>`: the worker processes a database class holds (ADR config-1)."""

from __future__ import annotations

import sys

#: max_connections and the server's own: micro measured (RATIO-1), larger classes a k × 79 floor.
CLASSES: dict[str, tuple[int, int]] = {
    "compose": (100, 3),
    "db.t4g.micro": (79, 7),
    "db.t4g.small": (158, 7),
    "db.t4g.medium": (316, 7),
}
#: Temporal's four roles at SQL_MAX_CONNS 4 + SQL_VIS_MAX_CONNS 2.
TEMPORAL = 4 * (4 + 2)
#: Zitadel's MAXOPENCONNS 20 plus the two its job queue holds.
ZITADEL = 20 + 2
OPERATOR_HEADROOM = 8
#: `config/settings/base.py::_POOL_MAX_SIZE_BY_SERVICE`.
WEB, WORKER = 10, 8
#: The ruled count (ADR config-1 as amended).
RULED_WORKERS = 2


class OffTheTable(LookupError):
    """A class the table does not know: refused, never guessed."""


def app_ceiling(db_class: str) -> int:
    """The connections left for web and the workers once every neighbour's bound is spent."""
    if db_class not in CLASSES:
        known = ", ".join(sorted(CLASSES))
        raise OffTheTable(
            f"{db_class!r} is not in deploy/pool_budget.py CLASSES ({known}). Add the class with "
            "its measured max_connections, or name one the table knows in DJB_RDS_CLASS."
        )
    max_connections, own = CLASSES[db_class]
    return max_connections - TEMPORAL - ZITADEL - own - OPERATOR_HEADROOM


def workers(db_class: str) -> int:
    """The ruled count, lowered to what the class holds; refuses a class that holds none."""
    held = (app_ceiling(db_class) - WEB) // WORKER
    if held < 1:
        raise OffTheTable(f"{db_class!r} cannot hold web {WEB} and one worker {WORKER}")
    return min(RULED_WORKERS, held)


def main(argv: list[str]) -> int:
    """`workers <class>` prints the count; anything else is a usage refusal."""
    if len(argv) != 2 or argv[0] != "workers":
        print("usage: pool_budget.py workers <class>", file=sys.stderr)
        return 2
    try:
        print(workers(argv[1]))
    except OffTheTable as error:
        print(f"!! pool_budget: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
