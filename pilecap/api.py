"""The REST door's roads: the acting pair, pagination, ordering, search, tags and refusals."""

from __future__ import annotations

from apps.accounts.auth import (
    #: API_AUTH — Every route's `auth=`: the API token first, then the session cookie.
    API_AUTH,
)
from apps.core.api.acting import (
    Acting,
    acting,
)
from apps.core.api.docs import (
    Tag,
    also_refuses,
    contract_of,
    refuses,
)
from apps.core.api.pagination import (
    ActsPagination,
    CursorPagination,
    cursor_page,
)
from apps.core.api.query import (
    ordered_by,
    searched,
)
from apps.core.requests import (
    TenantRequest,
)

__all__ = [
    "API_AUTH",
    "Acting",
    "ActsPagination",
    "CursorPagination",
    "Tag",
    "TenantRequest",
    "acting",
    "also_refuses",
    "contract_of",
    "cursor_page",
    "ordered_by",
    "refuses",
    "searched",
]
