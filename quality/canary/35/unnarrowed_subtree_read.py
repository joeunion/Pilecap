

# CANARY (rule 35, the subject-column form): 's plant, verbatim —
# the socket door's subtree read re-spelt case-insensitively. `iexact` and
# `istartswith` return EXACTLY the same rows for a base36 materialized path, so
# every equality pin in the repository stays green and the statement count stays
# 1; what moves is the plan. `upper(path)` is unsargable, so the path predicate
# drops out of the index condition into a `Filter` and the scan is served by the
# `for_tenant` leg's `Index Cond` alone — which the any-Index-Cond form of
# `index_served` called index-served. That is the blindness this fixture exists
# to prove is over: planted on the baseline it fired NOTHING.
from django.db.models import Q  # noqa: E402

from apps.core.models import PATH_SEPARATOR, Organization  # noqa: E402


def list_subtree_org_ids(*, tenant, org):  # noqa: F811 # planted violation
    if tenant is None or org is None:
        return []
    return list(
        Organization.objects.for_tenant(tenant)
        .filter(Q(path__iexact=org.path) | Q(path__istartswith=org.path + PATH_SEPARATOR))
        .order_by()
        .values_list("pk", flat=True)
    )
