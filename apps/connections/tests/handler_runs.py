"""The receipt's handler run, done where the receiver asks for it: for tests that drive the door."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from apps.connections.services import apply_inbound_webhook
from apps.connections.types import HANDLE_WORKFLOW
from apps.core import bridge
from apps.core.actor import system_actor


def run_handlers_at_the_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each handler run the receiver starts is its activity's service, called at once."""
    start = bridge.get(bridge.START_WORKFLOW_ON_COMMIT)

    def started(**kw: Any) -> Any:
        if kw["workflow"] != HANDLE_WORKFLOW:
            return start(**kw)
        tenant = kw["tenant"]
        return apply_inbound_webhook(
            tenant=tenant,
            actor=system_actor(tenant),
            inbound_webhook_id=UUID(kw["arg"].inbound_webhook_id),
        )

    monkeypatch.setitem(bridge._registry, bridge.START_WORKFLOW_ON_COMMIT, started)
