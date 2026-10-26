"""The session floor under the app's row locks: no lock wait or open transaction is unbounded."""

from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db

#: Postgres reports an unset timeout as the string "0".
UNSET = "0"


def _show(name: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(f"SHOW {name}")
        row = cursor.fetchone()
    assert row is not None
    return str(row[0])


def test_the_session_carries_both_timeouts() -> None:
    """The connection the app opens bounds a lock wait and an idle open transaction."""
    lock = _show("lock_timeout")
    idle = _show("idle_in_transaction_session_timeout")
    assert lock != UNSET, f"lock_timeout is {lock!r}: a queued row-lock waiter waits forever"
    assert idle != UNSET, (
        f"idle_in_transaction_session_timeout is {idle!r}: a parked holder keeps its locks forever"
    )


def test_the_session_bounds_a_statement() -> None:
    """A statement that runs past its bound is cancelled by the server, not by the pool."""
    bound = _show("statement_timeout")
    assert bound != UNSET, f"statement_timeout is {bound!r}: one runaway statement holds a slot"
