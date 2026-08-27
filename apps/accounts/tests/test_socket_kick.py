"""The socket dies with the credential — the reviewer's probe, made permanent.

P3-R0's MEDIUM, in one sentence: **socket auth is resolved once, at the
handshake.** That is the right design for a channel that then stays open for
hours and the wrong one the moment the credential behind it is withdrawn — a
revoked token's connection kept receiving until the client happened to hang up,
and an erased person's did too. RT2 built the primitive that closes them
(`realtime.kick_user`, reachable from below through `core.bridge`'s `KICK` name
and deliberately left with **zero** production callers); this module is where
the callers arrive and where the probe that found the hole becomes a
regression.

**Driven over a real socket, against the real application.** The chain under
test is `revoke_token` → `transaction.on_commit` → `core.bridge` → the channel
layer → the consumer → the wire, and the hops between those arrows are exactly
where a rename goes unnoticed until a customer notices first. Nothing here is
stubbed but Zitadel.

**Why this module may name `apps.realtime`.** `apps.accounts` sits *below* it in
the layer contract, and the production code obeys that absolutely: the kick is
reached by registry name, never by import (`services.close_sockets`). A test
that proves a socket closed has to open one, and `apps/realtime/tests/websocket`
is the socket client `build-contract.md` names for the whole repository. The
exemption is on the *test* modules only, exactly as
`apps.accounts.tests.* -> apps.workflows.*` already is and for the same reason:
drive the real thing rather than a copy of it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from django.conf import settings
from django.db import transaction
from django.test import Client

from apps.accounts.activities import apply_identity_config
from apps.accounts.models import ApiToken, User
from apps.accounts.services import (
    KICK_TOKEN_REVOKED,
    close_sockets,
    deactivate_user,
    erase_user,
    issue_token,
    record_zitadel_identity,
    revoke_token,
)
from apps.accounts.types import KIND_IDENTITY_REVOCATION, IdentityConfigSync
from apps.core import bridge
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.realtime.schemas import CLOSE_KICKED
from apps.realtime.tests.websocket import Handshake, Socket, open_socket

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

PATH = "/ws/events/"

# What a socket that is still up answers a ping with. The pre-fix probe's whole
# point: after the credential was revoked the connection was not merely open,
# it was *working*.
PING = {"type": "ping"}
PONG = {"type": "pong"}


async def session_headers(user: User) -> list[tuple[bytes, bytes]]:
    """A real signed-in session, as a cookie header on the handshake."""

    def sign_in() -> str:
        client = Client()
        client.force_login(user)
        return str(client.cookies[settings.SESSION_COOKIE_NAME].value)

    cookie = await run_db(sign_in)
    return [(b"cookie", f"{settings.SESSION_COOKIE_NAME}={cookie}".encode())]


def bearer_headers(plaintext: str) -> list[tuple[bytes, bytes]]:
    return [(b"authorization", f"Bearer {plaintext}".encode())]


@asynccontextmanager
async def opened(
    headers: list[tuple[bytes, bytes]] | None = None,
) -> AsyncIterator[tuple[Socket, Handshake]]:
    """Open a socket against the real mounted application and always close it."""
    from config.asgi import build_application

    async with open_socket(build_application(), PATH, headers) as pair:
        yield pair


async def assert_kicked(socket: Socket) -> None:
    """The close frame this socket must have received, and its code."""
    closed = await socket.output()
    assert closed["type"] == "websocket.close", closed
    assert closed["code"] == CLOSE_KICKED, closed


# --- A1-2: revocation reaches the socket --------------------------------------


async def test_revoking_a_token_closes_every_socket_that_person_has(
    tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    """Two of the owner's sockets die; a third person's lives. **A1-2.**

    Two connections for one person because a revocation that closed *a* socket
    rather than *every* socket would pass a single-socket test and leave the
    second tab receiving — the user group exists precisely so the withdrawal is
    about the person, not about one connection.

    The stranger's socket is the control, and it is what stops this passing
    vacuously: "everything closed" and "the right things closed" are told apart
    only by something that must stay open through the same kick.

    One of the owner's two sockets is authenticated by the very token being
    revoked and the other by a session. Both die, and that is the contract
    rather than an accident: the fact that fired the kick is *this person's
    credential is gone*, and RT2's `user_group` is deliberately not scoped by
    tenant or by how the socket signed in.
    """
    token, plaintext = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="doomed",
        actor=actor_for(user=owner, tenant=tenant),
    )

    async with (
        opened(headers=bearer_headers(plaintext)) as (machine, machine_handshake),
        opened(headers=await session_headers(owner)) as (human, human_handshake),
        opened(headers=await session_headers(stranger)) as (bystander, bystander_handshake),
    ):
        assert [
            machine_handshake.accepted,
            human_handshake.accepted,
            bystander_handshake.accepted,
        ] == [True, True, True]

        await run_db(
            revoke_token,
            token=token,
            tenant=tenant,
            actor=actor_for(user=token.user, tenant=token.tenant),
        )

        await assert_kicked(machine)
        await assert_kicked(human)

        assert await bystander.received_nothing() is True
        assert bystander.alive is True


async def test_the_revocation_still_revokes_and_still_keeps_its_row(
    tenant: Tenant, owner: User
) -> None:
    """The kick is an addition, not a replacement.

    A seam wired into an existing service is a chance to change what that
    service already did. This says it did not: the row survives (the audit trail
    is why), and `revoked_at` is set.
    """
    token, _ = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="doomed",
        actor=actor_for(user=owner, tenant=tenant),
    )

    await run_db(
        revoke_token,
        token=token,
        tenant=tenant,
        actor=actor_for(user=token.user, tenant=token.tenant),
    )

    def reread() -> ApiToken:
        return ApiToken.objects.get(pk=token.pk)

    stored = await run_db(reread)
    assert stored.revoked_at is not None


# --- A1-3: erasure kicks the same way -----------------------------------------


async def test_erasing_a_person_closes_their_sockets(
    tenant: Tenant, owner: User, member: User, owner_actor: Actor
) -> None:
    """**A1-3.** The erased person's connection dies; the eraser's does not.

    The assertion lives here and not in the A9 erasure matrix on purpose: the
    matrix is one of this cycle's four frozen nets, so a new fact about erasure
    is a new file, never a line added to a net.
    """
    async with (
        opened(headers=await session_headers(member)) as (erased, erased_handshake),
        opened(headers=await session_headers(owner)) as (eraser, eraser_handshake),
    ):
        assert [erased_handshake.accepted, eraser_handshake.accepted] == [True, True]

        await run_db(erase_user, user=member, actor=owner_actor, tenant=tenant)

        await assert_kicked(erased)

        assert await eraser.received_nothing() is True
        assert eraser.alive is True


async def test_deactivating_a_person_closes_their_sockets(
    tenant: Tenant, owner: User, member: User, owner_actor: Actor
) -> None:
    """**B-ACCT-1's half of the seam, re-driven.** The reversible act kicks too.

    Everything `deactivate_user` does stops the *next* request — the session is
    re-checked against `is_active`, and so is every token — and none of it
    reaches a connection that was authenticated an hour ago. Until P5-B-ACCT
    this service had no kick and no door, so nobody could have noticed: giving
    it a door is what made "a deactivated person keeps receiving" a thing a
    person could actually do.

    The deactivator's own socket is the control, and it is what stops this
    passing vacuously — "a socket closed" and "the right socket closed" are told
    apart only by one that must stay open through the same kick.
    """
    async with (
        opened(headers=await session_headers(member)) as (locked_out, locked_out_handshake),
        opened(headers=await session_headers(owner)) as (admin, admin_handshake),
    ):
        assert [locked_out_handshake.accepted, admin_handshake.accepted] == [True, True]

        await run_db(deactivate_user, user=member, actor=owner_actor, tenant=tenant)

        await assert_kicked(locked_out)

        assert await admin.received_nothing() is True
        assert admin.alive is True


async def test_the_identity_revocation_run_kicks_too(
    instance: Any, tenant: Tenant, member: User
) -> None:
    """The durable half of the same withdrawal. **The retrying caller.**

    `erase_user`'s own kick is fire-and-forget inside the erasing request: it
    happens once, on commit, and if the channel layer is unreachable at that
    instant nothing closes and nothing notices. The platform run that takes the
    person's Zitadel account out of use is the caller that gets to *retry* —
    which is why the kick is also asked for there, from the **activity** and
    never from `workflows.py` (house rule 9: the bridge lookup and the
    `group_send` behind it are I/O, and a workflow module may not do I/O).

    It is safe to ask twice because RT2 made the primitive idempotent: a
    `group_send` to an empty group is a no-op, so kicking a person who has
    nothing open closes nothing rather than failing.
    """
    await run_db(
        record_zitadel_identity,
        user=member,
        subject="9001",
        tenant=None,
        actor=system_actor(tenant=None),
    )
    instance.users["9001"] = {"id": "9001", "userName": member.email}

    async with opened(headers=await session_headers(member)) as (socket, handshake):
        assert handshake.accepted is True

        await run_db(
            apply_identity_config,
            IdentityConfigSync(kind=KIND_IDENTITY_REVOCATION, key=str(member.pk)),
        )

        await assert_kicked(socket)


# --- A1-4: the kick is honest about rollback ----------------------------------


async def test_a_revocation_that_does_not_commit_kicks_nobody(tenant: Tenant, owner: User) -> None:
    """**A1-4.** A refused write must not announce itself by hanging the user up.

    The failure is planted *inside* the transaction the service's `@service`
    joined, so the whole thing rolls back: `revoked_at` is never written, and
    the socket must be exactly as it was. A kick registered anywhere but
    `transaction.on_commit` would fire here — a side effect outside the
    transaction, which is the class this criterion exists to catch — and the
    user would be disconnected by a revocation that never happened.

    The socket answering a ping with a pong afterwards is what makes "still
    open" a claim about a *working* connection rather than about a task that has
    not noticed it is dead yet.
    """
    token, _ = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="survivor",
        actor=actor_for(user=owner, tenant=tenant),
    )

    async with opened(headers=await session_headers(owner)) as (socket, handshake):
        assert handshake.accepted is True

        def revoke_then_fail() -> None:
            with transaction.atomic():
                revoke_token(
                    token=token,
                    tenant=token.tenant,
                    actor=actor_for(user=token.user, tenant=token.tenant),
                )
                raise RuntimeError("planted: the surrounding write failed after the revocation")

        with pytest.raises(RuntimeError):
            await run_db(revoke_then_fail)

        assert await socket.received_nothing() is True
        assert socket.alive is True
        await socket.send_json(PING)
        assert await socket.receive_json() == PONG

        def reread() -> ApiToken:
            return ApiToken.objects.get(pk=token.pk)

        stored = await run_db(reread)
        assert stored.revoked_at is None


# --- The seam itself ----------------------------------------------------------


async def test_close_sockets_is_a_no_op_where_the_socket_app_is_not_installed(
    owner: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployment without `apps.realtime` still revokes.

    `find()` and not `get()`, which is the difference between "optional" and
    "required" on the bridge and is what `core/bridge.py` documents this name
    as. A template checkout that dropped the socket app must not have its
    erasures start failing in production, so the absence is a no-op and the
    call site says so.

    The lookup is made to answer `None` rather than the registry being emptied:
    `bridge.clear()` would take `realtime.push` and every workflow name out of
    the process for whatever test runs next, and the suite is deliberately
    order-randomised.
    """
    monkeypatch.setattr(bridge, "find", lambda name: None)

    await run_db(close_sockets, user_id=owner.pk, reason="nobody-is-listening")


async def test_a_dropped_kick_says_so_through_our_own_logging(
    tenant: Tenant,
    owner: User,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**P3-SEC-1's LOW-3.** The swallowed kick is no longer also silent.

    `close_sockets_on_commit` registers with `robust=True` on purpose — a
    failing channel layer must not cancel the hooks queued behind it — and the
    price is that a kick which raises is caught by Django's own hook handler and
    reported through `django.db.backends.base`. That is not this platform's
    logging: everything an operator watches goes through `core.log`, so a
    revoked person whose socket survived looked exactly like a clean revocation.

    The channel layer is made to raise where it really breaks — inside the
    registered callable, after the write has committed — and the two halves of
    the finding are asserted together: the structured line exists, on our own
    name, carrying the person and the reason; and the revocation it failed
    behind still stands, because the whole point of `robust=True` is that it
    does.

    Only the `KICK` name is diverted. Emptying `bridge.find` would take every
    other registration out of the process for whatever this order-randomised
    suite runs next.
    """
    token, _ = await run_db(
        issue_token,
        user=owner,
        tenant=tenant,
        name="doomed",
        actor=actor_for(user=owner, tenant=tenant),
    )

    real_find = bridge.find

    def unreachable_channel_layer(*, user_id: Any, reason: str) -> None:
        raise RuntimeError("planted: the channel layer is unreachable")

    def find(name: str) -> Any:
        return unreachable_channel_layer if name == bridge.KICK else real_find(name)

    monkeypatch.setattr(bridge, "find", find)

    with caplog.at_level(logging.ERROR):
        # It does not raise here: the hook is robust, so the revocation returns
        # normally and the kick is dropped. That is the behaviour under test.
        await run_db(
            revoke_token,
            token=token,
            tenant=tenant,
            actor=actor_for(user=token.user, tenant=token.tenant),
        )

    structured = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.getMessage().startswith("{")
    ]
    failed = [line for line in structured if line.get("event") == "core.socket.kick_failed"]
    assert len(failed) == 1, structured
    assert failed[0]["user_id"] == str(owner.pk)
    assert failed[0]["reason"] == KICK_TOKEN_REVOKED
    assert "planted: the channel layer is unreachable" in failed[0]["exception"]

    def reread() -> ApiToken:
        return ApiToken.objects.get(pk=token.pk)

    stored = await run_db(reread)
    assert stored.revoked_at is not None
