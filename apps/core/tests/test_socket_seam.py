"""The socket seam that every withdrawal goes through, tested where it lives.

`core.services.close_sockets` and `close_sockets_on_commit` are the one way any
app in this tree hangs up on somebody. Two apps call them — `accounts` for a
withdrawn **credential** (a token revoked, a user erased, an identity revoked in
Zitadel) and `core` itself for withdrawn **authorization** (a membership
revoked, a subtree re-parented) — and P3 SEC-R1 promoted the pair into `core`
precisely so there would be one definition rather than two hand-kept copies of
one act on a security seam.

This module tests the seam **as a seam**: no token, no membership, no socket.
Those live with their callers (`apps/accounts/tests/test_socket_kick.py` for the
credential half, `apps/realtime/tests/test_authorization_kick.py` for the
authorization half, both over real sockets). What is here is the property the
callers all inherit and none of them owns.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from django.db import transaction

from apps.core import bridge
from apps.core.services import close_sockets_on_commit


@pytest.fixture
def unreachable_channel_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The channel layer, broken where it really breaks: inside the kick.

    Only the `KICK` name is diverted. Emptying `bridge.find` would take every
    other registration out of the process for whatever this order-randomised
    suite runs next.
    """
    real_find = bridge.find

    def explode(*, user_id: Any, reason: str) -> None:
        raise RuntimeError("planted: the channel layer is unreachable")

    def find(name: str) -> Any:
        return explode if name == bridge.KICK else real_find(name)

    monkeypatch.setattr(bridge, "find", find)


@pytest.mark.django_db(transaction=True)
def test_a_failing_kick_does_not_cancel_the_hooks_queued_behind_it(
    unreachable_channel_layer: None,
) -> None:
    """**What `robust=True` was chosen for — proven, not assumed.**

    The registration used to be a `functools.partial`, and Django's robust
    branch reports a failing hook with
    ``f"Error calling {func.__qualname__} in on_commit() ..."``. A partial has no
    `__qualname__`, so the handler whose whole job is to swallow the exception
    raised `AttributeError` out of `set_autocommit` — uncaught — and Django's
    hook loop stopped: every hook still queued behind the kick was silently
    never run. `robust=True` meant its exact opposite, and only a raising kick
    could reveal it, which is why nothing did until LOW-3's probe.

    So the sibling is the assertion. A second hook is registered after the kick
    inside one transaction, the channel layer is made to raise, and the sibling
    must still run while the caller returns normally.

    **Tested at the seam, and that is deliberate.** SEC-R3 first proved this
    through `revoke_token`, and SEC-R1 then proved the same thing through
    `revoke_membership` — two tests of one mechanism, in two apps, neither of
    which owns it any more. This is the survivor: it needs no token, no
    membership and no socket, so it cannot pass or fail for a reason belonging
    to a caller.
    """
    ran: list[str] = []

    def register_a_kick_and_a_sibling() -> None:
        with transaction.atomic():
            close_sockets_on_commit(user_id=uuid4(), reason="core.test.seam")
            transaction.on_commit(lambda: ran.append("the sibling behind it"))

    register_a_kick_and_a_sibling()

    assert ran == ["the sibling behind it"]


@pytest.mark.django_db(transaction=True)
def test_every_kick_in_one_transaction_is_its_own_hook(
    unreachable_channel_layer: None,
) -> None:
    """One failing channel layer costs one socket, not the rest of the list.

    The re-parent registers a kick **per person losing sight of the moving
    subtree** (`core.services.apply_organization_move`), so this seam is the
    first caller that can queue several kicks on one transaction. Each is its
    own `kick_on_commit` closure, so a failure in the first must not eat the
    ones behind it — the same property as the test above, at the arity the
    authorization half actually uses.
    """
    ran: list[str] = []

    def register_three_kicks_and_a_sibling() -> None:
        with transaction.atomic():
            for _ in range(3):
                close_sockets_on_commit(user_id=uuid4(), reason="core.test.seam")
            transaction.on_commit(lambda: ran.append("the sibling behind them"))

    register_three_kicks_and_a_sibling()

    assert ran == ["the sibling behind them"]
