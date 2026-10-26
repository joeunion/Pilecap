"""The widget's object axis for core's flat census (`permissions_world.object_census`)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from apps.example.models import Widget
from pilecap.accounts import create_user
from pilecap.tenancy import Tenant, root_organization


def widget_rows(tenant: Tenant) -> Mapping[str, Any]:
    """One widget at the root, owned by a person who holds no role: the `row` state."""
    stranger = create_user(email=f"census-owner-{uuid.uuid4().hex[:8]}@example.com", password=None)
    row = Widget.objects.create(
        tenant=tenant,
        organization=root_organization(tenant=tenant),
        owner_id=stranger.pk,
        name="census-widget",
    )
    return {"row": row}


OBJECTS: dict[str, Callable[[Tenant], Mapping[str, Any]]] = {"widget": widget_rows}
