"""The export's object axis for core's flat census (`permissions_world.object_census`)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from apps.accounts.services import create_user
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.exports.models import Export


def export_rows(tenant: Tenant) -> Mapping[str, Any]:
    """One export of each scope at the root, asked for by a person who holds no role."""
    stranger = create_user(
        email=f"census-requester-{uuid.uuid4().hex[:8]}@example.com", password=None
    )
    root = root_organization(tenant=tenant)
    return {
        scope.value: Export.objects.create(
            tenant=tenant, organization=root, requested_by=stranger, scope=scope
        )
        for scope in (Export.Scope.ORGANIZATION, Export.Scope.TENANT)
    }


OBJECTS: dict[str, Callable[[Tenant], Mapping[str, Any]]] = {"export": export_rows}
