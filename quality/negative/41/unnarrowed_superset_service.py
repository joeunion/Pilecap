"""The callee for both negatives: a read that refuses `not_found`, and a dispatcher.

`get_gizmo` is the ordinary shape — a selector-style read whose refusal is a
code the door-shape derivation already produces, so an unnarrowed route
documents it and there is nothing to say.

`run_handler` is the other half: a callee reached through a registry lookup. Its
raises are unreadable by construction, and a clause that treated "I could not
read it" as "it cannot raise that" would turn its own blind spot into findings.
"""

from typing import Any
from uuid import UUID

from apps.core.exceptions import NotFound
from apps.core.models import Tenant

HANDLERS: dict[str, Any] = {}


def get_gizmo(*, tenant: Tenant, gizmo_id: UUID) -> dict[str, str]:
    """One gizmo, or a refusal that is not-there and not-yours at once."""
    raise NotFound("No gizmo with that id.")


def run_handler(*, tenant: Tenant, kind: str) -> Any:
    """Whatever the registry holds for this kind. What it raises is its own."""
    handler = HANDLERS[kind]
    return handler(tenant=tenant)
