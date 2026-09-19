

from apps.core.models import TenantScopedModel as _CanaryScopedBase13


class CanaryLedgerBook(_CanaryScopedBase13):
    # The kindless aggregate again — see `scoped_no_policy.py`. Declared here
    # too rather than shared, so this form plants its own victim whatever order
    # the batch puts the fixtures in.
    authz_kind = None
    authz_kind_reason = (
        "planted by rule 13's self-test: the aggregate half of a kindless pair, so the "
        "canary below it reaches the policy-noun question rather than the derived one."
    )

    label2 = models.CharField(max_length=32)


class CanaryLedger(_CanaryScopedBase13):
    # Planted: kindless, and the app's policies.py names a DIFFERENT noun. A
    # policy for something else is not a capability over this row, which is the
    # half a bare "does the app have any policies at all" test would miss.
    authz_kind_of = "book"

    book = models.ForeignKey(CanaryLedgerBook, on_delete=models.CASCADE, related_name="+")
    label3 = models.CharField(max_length=32)
