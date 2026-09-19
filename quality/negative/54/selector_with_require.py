"""The right form, kept forever: the read asks, for the kind it returns.

The shape every read sweep is driving towards — the capability asked once,
inside the selector, so every door pays it by construction rather than by each
door's author remembering. A list asks at the acting hat, before the queryset,
because a list has no row to hide.
"""

from django.db.models import QuerySet

from apps.core.authz import require

from .models import Gadget


def list_gadgets(*, tenant, actor) -> QuerySet[Gadget]:
    """The ordinary shape."""
    require(actor, "gadget.read")
    return Gadget.objects.for_tenant(tenant)
