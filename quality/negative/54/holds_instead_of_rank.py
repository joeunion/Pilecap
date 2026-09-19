"""The right form, kept forever: the question asked of the DATA.

This is what clause (c) is pushing every predicate towards, so it has to be
silent here or the rule would be telling people to write something it also
flags. `holds` reads the same three layers the role editor writes — the
declared role, the tenant's own rows, the grants — at the node the row belongs
to, and a tenant that renames `admin` or withholds one key from one person gets
the answer it configured.
"""

from apps.core import authz


def can_approve(actor, obj=None):
    """The row half and the capability, and no word for a role anywhere."""
    if obj is None:
        return False
    return authz.holds(actor, "widget.approve", at=obj.organization)
