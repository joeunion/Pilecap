"""The valve, with a reason: a permission row written outside the six services.

The allow-list is BY FUNCTION and lives in `quality/rules.yaml`, which is where
a judgement about who may hand out a capability belongs — a file somebody reads
in one place rather than a comment in somebody's app. Where a genuine exception
does turn up, it takes the generic override and says why, and the gate counts
it in the standing override census like every other one.

TWO comments and not one, because the valve is PER LINE and this function
writes on two of them: the constructor and the manager call are separate sites,
and a reason sitting above one of them excuses exactly that one. That is not an
inconvenience — it is the property that keeps a valve from quietly covering a
line nobody was thinking about when they wrote it.
"""

from apps.core.models import RolePermission


def canary_backfill_the_collection(*, tenant, role_key, permissions):
    """A migration-shaped backfill, and the sentences that make it visible."""
    # rule-24: a one-off backfill for a role whose collection predates the
    # tenant's own rows; the rows it builds are the ones set_role_collection
    # would have built, and nobody gains a capability the role did not carry.
    rows = [RolePermission(tenant=tenant, role_key=role_key, permission=p) for p in permissions]
    # rule-24: the same act, on the line that performs it — the write of the
    # rows assembled above, under the same one-off backfill reason.
    return RolePermission.objects.for_tenant(tenant).bulk_create(rows)
