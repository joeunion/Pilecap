"""The machine door onto accounts: deactivate or erase a member, and nothing else.

Token minting and SSO configuration stay behind the session door (rule 17's `accounts` exemption).
No tool takes an email address: a fuzzy name resolved to the wrong person is not undoable.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.accounts.api import deactivate_user_route, erase_user_route
from apps.accounts.schemas import UserOut
from apps.accounts.selectors import get_member
from apps.accounts.services import deactivate_user, erase_user
from apps.core.api.docs import contract_of
from apps.core.mcp import acting_tenant, tool_call


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="deactivate_user",
        description=contract_of(deactivate_user_route),
    )
    def deactivate_user_tool(ctx: Context[Any], user_id: UUID) -> UserOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            user = get_member(tenant=tenant, user_id=user_id, actor=actor)
            return UserOut.from_orm(deactivate_user(user=user, actor=actor, tenant=tenant))

    @server.tool(
        name="erase_user",
        description=contract_of(erase_user_route),
    )
    def erase_user_tool(ctx: Context[Any], user_id: UUID) -> UserOut:
        with tool_call(ctx) as acting:
            tenant, actor = acting_tenant(acting), acting.actor()
            user = get_member(tenant=tenant, user_id=user_id, actor=actor)
            return UserOut.from_orm(erase_user(user=user, actor=actor, tenant=tenant))
