"""Planted: a public read that never asks (clause d).

A `list_` returning rows of a kind, with no `require(actor, "gadget.read")` in
it — which is a read every door inherits for free, including the ones nobody
has written yet. The valve for a machine read is `# read-open: <reason>`; this
one is a door read and has neither.
"""

from django.db.models import QuerySet

from .models import Gadget


def list_gadgets(*, tenant, actor) -> QuerySet[Gadget]:
    """Planted wrongness: rows out, nothing asked."""
    return Gadget.objects.for_tenant(tenant)
