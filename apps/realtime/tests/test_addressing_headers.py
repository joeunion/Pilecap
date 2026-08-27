"""The addressing-header law at the socket door (ADR core-21).

The law and the decision table live in
`apps/core/tests/test_addressing_headers.py`, where the seam does. This module
is the socket door's rows of that same table, and it lives here rather than
there because `core` sits below `realtime` in the layer contract and may not
import the socket client or the close codes. The cells are imported from that
module — the legal direction — so neither half can quietly grow or lose a row.

**A websocket handshake has no body to carry a refusal in.** So the law is said
in the only vocabulary this transport has: a sent-and-unhonourable addressing
header resolves NOWHERE, and the handshake closes with `CLOSE_NO_TENANT` —
"this handshake resolved nowhere it may act". Both credentials answer the same
way, which is what `test_credential_parity.py` exists to hold true: the session
stack refuses in `core.asgi_middleware`, the bearer stack in
`realtime.middleware`, and both ask `core.middleware.addressing_refusal`.
"""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.asyncdb import run_db
from apps.core.models import Organization, Tenant
from apps.core.tests.test_addressing_headers import (
    HEADERS,
    OMITTED,
    SOCKET_ROWS,
    VALID,
    _slug_for,
)
from apps.realtime.schemas import CLOSE_NO_TENANT
from apps.realtime.tests.test_consumers import session_headers
from apps.realtime.tests.websocket import open_socket

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

PATH = "/ws/events/"


def _application() -> object:
    from config.asgi import build_application

    return build_application()


@pytest.mark.parametrize(("state", "header"), SOCKET_ROWS)
async def test_a_bearer_handshake_refuses_an_unhonourable_header(
    state: str,
    header: str,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    root_org: Organization,
) -> None:
    """The machine socket: foreign, nonexistent and empty all close the same way.

    The empty cell is the one this door was quietly wrong
    about longest: `_requested_slug` fell through to the query parameter on an
    EMPTY header, so a handshake whose `X-Org` came from a template that did not
    interpolate was answered as though it had named nothing.
    """
    plaintext = str(
        (
            await run_db(
                issue_token,
                user=owner,
                tenant=tenant,
                name="socket",
                actor=actor_for(user=owner, tenant=tenant),
            )
        )[1]
    )
    if header == "X-Tenant":
        value = _slug_for(state, mine=tenant.slug, foreign=other_tenant.slug)
    else:
        value = _slug_for(state, mine=root_org.slug, foreign="no-such-slug-anywhere")
    assert value is not None

    headers = [
        (b"authorization", f"Bearer {plaintext}".encode()),
        (header.lower().encode(), value.encode()),
    ]
    async with open_socket(_application(), PATH, headers) as (_socket, handshake):
        assert not handshake.accepted, (state, header)
        assert handshake.code == CLOSE_NO_TENANT, (state, header, handshake)


@pytest.mark.parametrize(("state", "header"), SOCKET_ROWS)
async def test_a_session_handshake_refuses_an_unhonourable_header(
    state: str,
    header: str,
    tenant: Tenant,
    other_tenant: Tenant,
    owner: User,
    root_org: Organization,
) -> None:
    """The browser socket: the same rows, through the session stack.

    Two middlewares, one law. A door that refused for a token and fell back for
    a cookie would be the disagreement `architecture.md` calls a finding.
    """
    if header == "X-Tenant":
        value = _slug_for(state, mine=tenant.slug, foreign=other_tenant.slug)
    else:
        value = _slug_for(state, mine=root_org.slug, foreign="no-such-slug-anywhere")
    assert value is not None

    headers = [*await session_headers(owner), (header.lower().encode(), value.encode())]
    async with open_socket(_application(), PATH, headers) as (_socket, handshake):
        assert not handshake.accepted, (state, header)
        assert handshake.code == CLOSE_NO_TENANT, (state, header, handshake)


@pytest.mark.parametrize("state", (OMITTED, VALID))
@pytest.mark.parametrize("header", HEADERS)
async def test_an_honoured_header_still_connects(
    state: str,
    header: str,
    tenant: Tenant,
    owner: User,
    root_org: Organization,
) -> None:
    """The half that must NOT move: omitted falls back, valid is honoured.

    Without these rows the six refusals above would pass against a door that
    closed every handshake, which is a test that cannot fail.
    """
    plaintext = str(
        (
            await run_db(
                issue_token,
                user=owner,
                tenant=tenant,
                name="quiet",
                actor=actor_for(user=owner, tenant=tenant),
            )
        )[1]
    )
    if header == "X-Tenant":
        value = _slug_for(state, mine=tenant.slug, foreign="unused")
    else:
        value = _slug_for(state, mine=root_org.slug, foreign="unused")

    headers = [(b"authorization", f"Bearer {plaintext}".encode())]
    if value is not None:
        headers.append((header.lower().encode(), value.encode()))

    async with open_socket(_application(), PATH, headers) as (_socket, handshake):
        assert handshake.accepted, (state, header, handshake)
