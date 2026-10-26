"""Making a noun searchable and reading the search page a viewer may see."""

from __future__ import annotations

from apps.search.events import (
    SEARCH_ENGINE_DEGRADED,
    SEARCH_ENGINE_RECOVERED,
)
from apps.search.selectors import (
    get_search_page,
    list_readable_kinds,
)
from apps.search.types import (
    ScopeFilter,
    Searchable,
    SearchKind,
)

__all__ = [
    "SEARCH_ENGINE_DEGRADED",
    "SEARCH_ENGINE_RECOVERED",
    "ScopeFilter",
    "SearchKind",
    "Searchable",
    "get_search_page",
    "list_readable_kinds",
]
