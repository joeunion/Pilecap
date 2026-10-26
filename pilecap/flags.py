"""A tenant's feature flags, read: the declared defaults and what is on for one tenant."""

from __future__ import annotations

from apps.core.flags import (
    defaults,
    enabled_for,
    is_enabled,
    tenant_flags,
)

__all__ = [
    "defaults",
    "enabled_for",
    "is_enabled",
    "tenant_flags",
]
