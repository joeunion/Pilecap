"""Optimistic concurrency for a `Versioned` noun: the token, and the one comparison.

A person reads a row, edits it for a minute, and saves. Somebody else saved it
in between. Without a token the second save silently wins over the first
(last-write-wins, `architecture.md`'s default for every noun that has not
opted in); with one, the late save is refused `stale_version` and the face
reloads what is there now.

**The token is derived, never stored** (the owner's ruling). `updated_at` is
`auto_now` on `BaseModel`, so every save that names it moves it; the version is
that instant in integer microseconds since the Unix epoch — exact (a datetime
carries microseconds and no more), comparable as an integer, and below 2**53,
so a JSON number carries it into a browser without rounding. No column, no
migration, and nothing a service could forget to bump: rule 76 is what holds
the one way it could go stale — a write that does not move `updated_at`.

**How a service uses it**, inside its own `@service` transaction:

    locked = Widget.objects.for_tenant(tenant).select_for_update().get(pk=widget.pk)
    require_version(locked, version)
    locked.name = name
    locked.save(update_fields=["name", "updated_at"])

The lock is taken first (E8, unchanged): the comparison is made against the
row as it is while nobody else may write it, so two saves carrying the same
version serialize and the second is refused rather than both passing a check
made before either wrote.

DOES NOT COVER — declared: a wall clock that steps backwards between two locked
writes (two saves could share a microsecond only if the clock repeated one); a
write through a variable `update_fields` list, which rule 76 cannot read; a
noun that has not declared `Versioned`, which stays last-write-wins by the
settled row.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from apps.core.exceptions import StaleVersion
from apps.core.roads import road

#: The epoch the version counts from. Aware, UTC, so an aware `updated_at`
#: subtracts cleanly whatever zone the process runs in.
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

#: The unit the version counts in — a datetime's own resolution.
TICK = timedelta(microseconds=1)


def version_of(row: Any) -> int:
    """The row's version: `updated_at` in integer microseconds since the epoch.

    `(row.updated_at - EPOCH) // timedelta(microseconds=1)` — integer division
    of two timedeltas is exact. A row that has never been saved has no
    `updated_at` and so no version; asking for one is a `ValueError` rather than
    a zero that would match a client that sent nothing meaningful.
    """
    stamp = getattr(row, "updated_at", None)
    if not isinstance(stamp, datetime):
        raise ValueError(
            f"{type(row).__name__} has no saved `updated_at`, so it has no version yet. "
            "A version names a save that happened."
        )
    return (stamp - EPOCH) // TICK


@road("version_row", example="apps/example/services.py::update_widget")
def require_version(locked: Any, version: int) -> None:
    """Refuse `stale_version` unless `version` is the locked row's version now.

    Call it on the row as re-read under `select_for_update()` inside the
    service's transaction, BEFORE any write. Equal → return, and the write goes
    ahead; anything else → `StaleVersion` carrying the current version, and
    nothing is written (the service's transaction rolls back whatever came
    before it). A version from the future is as stale as one from the past: it
    names a save this row never had.
    """
    current = version_of(locked)
    if isinstance(version, bool) or not isinstance(version, int) or version != current:
        raise StaleVersion(current_version=current)
