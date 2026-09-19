"""Planted: production code asking what ROLE somebody has (clause c).

The shape the whole of Phase W is removing. A role is data a tenant owns — it
can rename `admin`, declare `approver`, or withhold one key from one person in
one branch — and a comparison against the word `owner` is a second opinion
about authority that no tenant can edit and no grant can narrow. The question
this code is really asking is `holds(actor, "<kind>.<verb>", at=...)`.
"""

from apps.core.service import service


@service
def canary_close_the_books(*, tenant, actor, membership) -> None:
    """Planted wrongness: the role, by value."""
    if membership.role == "owner":
        return None
    return None
