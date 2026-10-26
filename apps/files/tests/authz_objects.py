"""The document's object axis for core's flat census (`permissions_world.object_census`)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any

from apps.accounts.services import create_user
from apps.core.models import Tenant
from apps.core.services import root_organization
from apps.files.models import StoredFile


def file_rows(tenant: Tenant) -> Mapping[str, Any]:
    """One document at the root, uploaded by a person who holds no role: the `row` state."""
    stranger = create_user(
        email=f"census-uploader-{uuid.uuid4().hex[:8]}@example.com", password=None
    )
    row = StoredFile.objects.create(
        tenant=tenant,
        organization=root_organization(tenant=tenant),
        uploaded_by=stranger,
        filename="census.pdf",
        purpose=StoredFile.Purpose.UPLOAD,
    )
    return {"row": row}


OBJECTS: dict[str, Callable[[Tenant], Mapping[str, Any]]] = {"file": file_rows}
