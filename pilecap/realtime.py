"""Pushing an event to a tenant's open sockets."""

from __future__ import annotations

from apps.realtime.bridge import (
    push_event,
)
from apps.realtime.schemas import (
    EventMessage,
)

__all__ = [
    "EventMessage",
    "push_event",
]
