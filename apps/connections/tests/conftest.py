"""Fixtures the connections tests share, on top of `apps/conftest.py`.

One thing lives here rather than in each module: a connection with a webhook
secret, because four tests need one and building it by hand four times is four
chances to build it slightly differently.

There used to be an `events_installed` skip marker beside it. `apps/events` was
built concurrently with this app (rungs A3 and A4) and the hand-off assertions
had nowhere to land until it merged; it has, so the marker is gone and the
hand-off is asserted outright. A skip that can no longer fire is a test that
looks like coverage and is not.
"""

from __future__ import annotations

import pytest

from apps.connections.models import Connection
from apps.connections.services import create_connection
from apps.core.actor import Actor
from apps.core.models import Tenant

# The shared secret the signature tests sign with.
WEBHOOK_SECRET = "a-shared-secret-nobody-else-has"  # noqa: S105 — a signing secret the test both signs and verifies with  # pragma: allowlist secret


@pytest.fixture
def connection(tenant: Tenant, owner_actor: Actor) -> Connection:
    """A live connection with a webhook secret that still takes `X-Signature`, as old rows do."""
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="example",
        name="Primary",
        credentials={"webhook_secret": WEBHOOK_SECRET, "access_token": "an-access-token"},
        is_signature_v2_required=False,
    )


@pytest.fixture
def v2_connection(tenant: Tenant, owner_actor: Actor) -> Connection:
    """A live connection made the way a caller makes one today: `X-Signature-V2` only."""
    return create_connection(
        tenant=tenant,
        actor=owner_actor,
        provider="example",
        name="Current",
        credentials={"webhook_secret": WEBHOOK_SECRET, "access_token": "an-access-token"},
    )
