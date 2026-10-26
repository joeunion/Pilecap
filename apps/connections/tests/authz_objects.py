"""The connection's object axis for core's flat census (`permissions_world.object_census`)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from apps.connections.models import Connection
from apps.core.models import Tenant


def connection_rows(tenant: Tenant) -> Mapping[str, Any]:
    """One `Connection` of this tenant, written raw: the `row` state.

    Tenant-scoped, so asked at the acting hat like `obj=None`; a model that grows a node moves it.
    """
    row = Connection.objects.create(
        tenant=tenant,
        provider="census",
        name=f"census-{uuid.uuid4().hex[:8]}",
        status=Connection.Status.CONNECTED,
    )
    return {"row": row}


OBJECTS: dict[str, Callable[[Tenant], Mapping[str, Any]]] = {"connection": connection_rows}
