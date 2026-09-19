"""The machine door onto accounts: taking a person's access away, and nothing else.

**This app's MCP surface is deliberately narrow, and `quality/rules.yaml` holds
the reason** (house rule 17's `accounts` exemption). Minting a token over MCP is
circular — the machine door authenticates *with* a token — and the SSO
configuration surface is an identity-provider credential surface that stays
behind the session door. What is left, and what this module adds, is the pair of
acts an agent has a legitimate reason to perform on behalf of the person holding
the token: deactivate them, or erase them.

**Same service, same wall, same words.** Each tool below calls the very service
its REST twin calls, and takes `description=contract_of(<the REST route>)` — the
contract half of the docstring the OpenAPI document describes that route with
(ADR api-1, house rule 41). One capability cannot be explained two ways, because
there is only one text.

**And the same refusals, byte for byte.** Neither tool catches anything.
`core.mcp.tool_call` renders `wire_refusal(exc)` through `refusal_message`, which
is the same body `config/api.py` sends as JSON — so a member who may not erase a
colleague is told the same true thing here as there, with the same code leading
and the same remedies. `tests/test_user_doors.py` string-compares the two.

The **self-serve** halves of the REST door (`/users/me/…`) have no tool of their
own: a tool taking `user_id` covers the case by being handed the caller's own id,
and a second pair of tools whose whole difference is an omitted argument is a
second place for an agent to guess wrong. That is a judgment about *shape*, not
a parity gap — the pair of capabilities is here in full.

**No tool erases somebody by email address**, and that is a wall rather than an
omission: an agent given a fuzzy name is exactly the caller who would resolve it
to the wrong person, and the refusal for the wrong id is one an operator can
read afterwards while an erasure of the wrong person is not undoable at all.
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
            tenant = acting_tenant(acting)
            return UserOut.from_orm(
                deactivate_user(
                    user=get_member(tenant=tenant, user_id=user_id, actor=acting.actor()),
                    actor=acting.actor(),
                    tenant=tenant,
                )
            )

    @server.tool(
        name="erase_user",
        description=contract_of(erase_user_route),
    )
    def erase_user_tool(ctx: Context[Any], user_id: UUID) -> UserOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            return UserOut.from_orm(
                erase_user(
                    user=get_member(tenant=tenant, user_id=user_id, actor=acting.actor()),
                    actor=acting.actor(),
                    tenant=tenant,
                )
            )
