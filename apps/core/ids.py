"""The identifier every row gets, and the one place it is minted.

**UUIDv7, not v4** (ruled 2026-08-19). A v4 primary key is random, so rows land
all over a B-tree index: inserts dirty a new page every time, and "the hundred
most recent widgets" is a sort over the whole table. A v7 is a 48-bit
millisecond timestamp followed by randomness, so ids sort by creation time,
inserts append to the right-hand edge of the index, and `ORDER BY id` is
`ORDER BY created_at` without reading a second column.

It stays a `uuid.UUID`. `uuid6.uuid7()` returns a subclass, which Django and
Pydantic both handle, but a subclass leaking into every model default means
every annotation in the tree has to decide which one it means. One conversion
here costs nothing and keeps the type in `models.py`, `schemas.py` and every
service the standard-library one.
"""

from __future__ import annotations

import uuid

import uuid6


def uuid7() -> uuid.UUID:
    """A time-sortable UUID version 7, as a standard-library `uuid.UUID`."""
    return uuid.UUID(int=uuid6.uuid7().int)
