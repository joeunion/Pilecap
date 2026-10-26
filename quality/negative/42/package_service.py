"""A service in a `services/` package module, reached by a door through the package."""

from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.core.service import service


@service
def enrol_probe_person(*, tenant: Tenant, actor: Actor, email: str) -> str:
    """Enrol a person. The route beside this package calls it through the package."""
    return email
