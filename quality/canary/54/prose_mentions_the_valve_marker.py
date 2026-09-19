"""Planted: a public read that never asks, whose docstring SPELLS the valve.

The marker is a comment, not a phrase. A docstring paragraph explaining why a
selector needs no valve — quoting the marker inside backticks to name it — is
prose, and prose that silenced clause (d) would be an off switch anybody could
write by accident while explaining that they had not written one.

The shape is real: `apps/usage/selectors.py::list_thresholds` carries exactly
this sentence, honestly, about a read that is outside the population by
annotation. The day the valve census started reading every public `get_`/`list_`
by name, that sentence was counted as a valve — so this file is the direction
that matters, a read of a KIND with the same sentence, which must still fire.
"""

from django.db.models import QuerySet

from .models import Gadget


def list_gadgets(*, tenant, actor) -> QuerySet[Gadget]:
    """Planted wrongness: rows out, nothing asked, and the marker only named.

    A `# read-open:` line here would be a valve, and this paragraph is not one:
    it mentions the marker rather than opening a comment with it.
    """
    return Gadget.objects.for_tenant(tenant)
