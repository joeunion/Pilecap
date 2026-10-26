"""The admin that writes through services: the base class and its action."""

from __future__ import annotations

from apps.core.admin import (
    #: Action — What an admin save did: `"create"`, `"update"` or `"delete"`.
    Action,
    ServiceModelAdmin,
)

__all__ = [
    "Action",
    "ServiceModelAdmin",
]
