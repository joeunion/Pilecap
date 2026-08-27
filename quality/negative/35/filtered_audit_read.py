# NEGATIVE (rule 35): an extra per-row Filter riding an index-served scan is
# NOT a violation — the tenant lookup keeps its Index Cond and the new
# predicate rides beside it as a Filter, which is M4 FINDING 1's legitimate
# shape. The rule must fire on a lookup becoming a walk, never on a walk-shaped
# Filter beside a lookup.
#
# REWRITTEN BY (c). The first version filtered on `created_at__isnull` and
# was silent for the wrong reason: the planner folded that predicate away
# entirely, so no `Filter:` line was ever produced and this fixture exempted a
# shape it did not create. A negative that is silent because nothing was there
# proves the rule ignores something nobody wrote. `action` is a column no
# `lookup_columns` entry declares and no index on this table covers, so
# `startswith` on it cannot become an index condition and the plan carries a
# real `Filter:` beside the tenant `Index Cond:` — which is the shape claimed.
# The rule's own `plan_shape` self-test holds that: the marker below tells the
# check the fixture is planted, and the plan is then required to contain what
# this comment says it contains.
#
# n107-plan-shape-marker: filter-on-an-undeclared-column
_negative_original_for_tenant = AuditEntryQuerySet.for_tenant


def _negative_filtered_for_tenant(self, tenant):
    return _negative_original_for_tenant(self, tenant).filter(action__startswith="widget.")


AuditEntryQuerySet.for_tenant = _negative_filtered_for_tenant
