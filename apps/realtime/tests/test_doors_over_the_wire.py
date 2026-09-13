"""The socket door on the channel layer a deployment actually runs.

Every other test in this app runs on `InMemoryChannelLayer`, which
`config/settings/test.py` substitutes so that the suite needs no Redis to
import settings. That substitution is the second blind spot the cycle-0
verifier fell into: the in-memory layer has no sockets, no blocking
read and no timeout, so a **real** connection that died at exactly five seconds
of idle — `channels_redis` calls `BZPOPMIN` with `brpop_timeout=5`, and
redis-py 8 defaults `socket_timeout` to 5 seconds, so the client tore its own
connection down before the server's own timeout could answer — passed the whole
suite green.

So this module overrides the layer back to Redis and drives the real thing: a
real `ApiToken` on a real handshake against the application `config/asgi.py`
builds, then **an idle longer than the blocking-read window**, then a push. It
is skipped rather than failed where no Redis is listening, because a laptop
with no compose stack up is not a broken tree — and the skip names the address
it tried, so a skip nobody meant is visible.

Kept deliberately short of the wall-clock budget a test suite can afford: one
idle window of seven seconds, once, in one test.
"""

from __future__ import annotations

import asyncio
import socket as socketlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlparse

import pytest
from channels_redis.core import RedisChannelLayer
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.models import Tenant
from apps.realtime.bridge import push_event
from apps.realtime.schemas import EventMessage
from apps.realtime.tests.websocket import Handshake, Socket, open_socket
from config.settings.base import (
    CHANNEL_LAYER_BLOCKING_READ_SECONDS,
    CHANNEL_LAYER_SOCKET_TIMEOUT,
    REDIS_CHANNEL_LAYER,
)

# The marks are per test rather than module-wide: the configuration pin below
# is synchronous and touches no database, and a module-wide `asyncio` mark on a
# plain function is a pytest-asyncio error rather than a skipped mark.

PATH = "/ws/events/"

# Past `channels_redis.core.RedisChannelLayer.brpop_timeout` (5s), which is the
# window a connection used to die in, with enough margin that a loaded machine
# does not make this test lie either way.
#
# **The one duration SENT-1 deliberately left alone.** Every other wait
# in this app became an ordering fact; this one is genuinely temporal — the
# claim IS that the socket outlives a blocking-read window, so the number is the
# property rather than a bet on the machine, and the header above says why.
IDLE = 7.0

# `PUSH_TIMEOUT = 5.0` was here, and SENT-1 deleted it rather than widening it.
# It was margin, not meaning: it bought the push five seconds instead of the
# harness default's two, which is the same bet at a different price. The push
# now waits on the application task's own sentinel — `receive_json()` returns
# the frame or names why nothing is coming — so a Redis round trip that is slow
# is no longer a failure and a bridge that is broken is no longer a wait.

REDIS_CONNECT_TIMEOUT = 0.5

# The deployment's own layer, read from `base` rather than copied: a test that
# rebuilt the configuration by hand would prove a configuration nothing runs.
REDIS_LAYER = {"default": REDIS_CHANNEL_LAYER}


def redis_is_listening() -> bool:
    """Whether anything answers on `REDIS_URL`'s host and port."""
    parsed = urlparse(settings.REDIS_URL)
    try:
        with socketlib.create_connection(
            (parsed.hostname or "127.0.0.1", parsed.port or 6379),
            timeout=REDIS_CONNECT_TIMEOUT,
        ):
            return True
    except OSError:
        return False


needs_redis = pytest.mark.skipif(
    not redis_is_listening(),
    reason=f"no Redis listening on {settings.REDIS_URL}; start the compose stack",
)


def an_event() -> EventMessage:
    return EventMessage(
        name="example.widget.created",
        v=1,
        payload={"id": "8f14e45f-ea1e-7c2b-8000-000000000001", "name": "A widget"},
        correlation_id="c0ffee",
        occurred_at=timezone.now(),
    )


@asynccontextmanager
async def opened(headers: list[tuple[bytes, bytes]]) -> AsyncIterator[tuple[Socket, Handshake]]:
    from config.asgi import build_application

    async with open_socket(build_application(), PATH, headers) as pair:
        yield pair


async def bearer_headers(*, user: User, tenant: Tenant) -> list[tuple[bytes, bytes]]:
    _, plaintext = await run_db(
        issue_token,
        user=user,
        tenant=tenant,
        name="idle-socket",
        actor=actor_for(user=user, tenant=tenant),
    )
    return [(b"authorization", f"Bearer {plaintext}".encode())]


def test_the_read_timeout_is_longer_than_the_blocking_read_it_guards() -> None:
    """The number that was turned on, pinned to the library it has to outlive.

    Not a style assertion: redis-py raises when a read exceeds `socket_timeout`,
    and `channels_redis` blocks for `brpop_timeout` on every poll. Whenever the
    first is the smaller of the two, every idle socket in the deployment dies on
    a timer. A `channels_redis` upgrade that raises its own number fails here
    rather than in production.
    """
    assert CHANNEL_LAYER_BLOCKING_READ_SECONDS == RedisChannelLayer.brpop_timeout
    assert CHANNEL_LAYER_SOCKET_TIMEOUT > CHANNEL_LAYER_BLOCKING_READ_SECONDS
    host = REDIS_CHANNEL_LAYER["CONFIG"]["hosts"][0]
    assert host["socket_timeout"] == CHANNEL_LAYER_SOCKET_TIMEOUT


@needs_redis
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_socket_on_the_real_channel_layer_survives_an_idle_window(
    tenant: Tenant, owner: User
) -> None:
    """Join with a token, say nothing for longer than the blocking read, get the push.

    The three assertions are three different failures:

    * the handshake is the door;
    * `socket.alive` after the idle is the channel layer's blocking read — this
      is what went down at +5.0s, and `socket.failure()` is the reason it did;
    * the frame is the bridge still reaching a connection that waited.
    """
    with override_settings(CHANNEL_LAYERS=REDIS_LAYER):
        async with opened(await bearer_headers(user=owner, tenant=tenant)) as (socket, handshake):
            assert handshake.accepted is True

            await asyncio.sleep(IDLE)
            assert socket.alive, f"the socket died while idle: {socket.failure()!r}"

            await push_event(tenant_id=tenant.pk, event=an_event())
            received = await socket.receive_json()

    assert received["name"] == "example.widget.created"
    assert received["payload"]["name"] == "A widget"
