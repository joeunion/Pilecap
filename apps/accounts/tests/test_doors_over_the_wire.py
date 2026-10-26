"""The accounts doors on the wire: one press, one body on REST and MCP (rule 46)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import system_actor
from apps.core.exceptions import refusal_message
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership
from apps.core.tests.doors import canonical, first_difference
from apps.core.tests.wire import MCP_HEADERS, MCP_URL, initialize, rpc, wire
from apps.core.tests.wire import bearer as issue_bearer

#: House rule 46: the door pair this module answers for `apps/accounts`.
DOOR_PAIR = ("rest", "mcp")

# No write both doors reach emits an event, so the four-door driver has no payload to hold here.

JSON = "application/json"
PASSWORD = "a-long-enough-password"  # noqa: S105 — a throwaway password a test user is made with  # pragma: allowlist secret

# The person's read shape, written out rather than derived from the schema.
USER_KEYS = frozenset(
    {"id", "email", "is_active", "is_staff", "date_joined", "created_at", "updated_at"}
)


async def _call_tool(
    client: httpx.AsyncClient, headers: dict[str, str], name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    await initialize(client, headers, who="accounts-parity")
    called = await client.post(
        MCP_URL,
        headers={**MCP_HEADERS, **headers},
        json=rpc("tools/call", {"name": name, "arguments": arguments}, 2),
    )
    assert called.status_code == 200, called.text
    answered: dict[str, Any] = called.json()
    assert "error" not in answered, answered
    result: dict[str, Any] = answered["result"]
    return result


@pytest.fixture
def colleague(tenant: Tenant) -> User:
    user = create_user(email="colleague@example.com", password=PASSWORD)
    add_membership(
        user=user,
        tenant=tenant,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    return user


# `transaction=True`: the transport runs a tool body on a worker thread with its own connection.
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_one_deactivation_is_one_body_on_rest_and_mcp(
    tenant: Tenant, owner: User, colleague: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner switches a colleague off once per door; the second press answers the first."""
    token = await sync_to_async(issue_bearer)(user=owner, tenant=tenant, name="accounts-parity")
    auth = {"authorization": f"Bearer {token}"}
    # The clock held still: each press stamps `updated_at`, and the instant is not a door's fact.
    instant = timezone.now()
    monkeypatch.setattr(timezone, "now", lambda: instant)

    async with wire() as client:
        over_http = await client.post(
            f"/api/v1/users/{colleague.pk}/deactivate/", headers={**auth, "accept": JSON}
        )
        assert over_http.status_code == 200, over_http.text
        result = await _call_tool(client, auth, "deactivate_user", {"user_id": str(colleague.pk)})

    rest_body = over_http.json()
    over_mcp = result["structuredContent"]
    assert set(rest_body) == USER_KEYS
    assert rest_body["is_active"] is False
    assert first_difference(rest_body, over_mcp) is None, first_difference(rest_body, over_mcp)
    assert canonical(rest_body) == canonical(over_mcp)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_member_erasing_a_colleague_is_refused_alike_on_both_doors(
    tenant: Tenant, member: User, colleague: User
) -> None:
    """Two ordinary members: both doors answer the one `forbidden` refusal, and nothing moves."""
    token = await sync_to_async(issue_bearer)(user=member, tenant=tenant, name="accounts-parity")
    auth = {"authorization": f"Bearer {token}"}

    async with wire() as client:
        over_http = await client.post(
            f"/api/v1/users/{colleague.pk}/erase/", headers={**auth, "accept": JSON}
        )
        result = await _call_tool(client, auth, "erase_user", {"user_id": str(colleague.pk)})

    assert over_http.status_code == 403, over_http.text
    assert over_http.json()["code"] == "forbidden"
    assert result.get("isError") is True, result
    over_mcp = result["content"][0]["text"]
    assert refusal_message(over_http.json()) in over_mcp, (over_mcp, over_http.json())

    await sync_to_async(colleague.refresh_from_db)()
    assert (colleague.email, colleague.is_active) == ("colleague@example.com", True)
