

from apps.core.models import TenantScopedModel


class CanaryAggregate(TenantScopedModel):
    # Planted: an aggregate that is deliberately NOT a kind, so the row below it
    # has no kind to inherit. The opt-out is legal and silent on its own (rule
    # 13's second clause); it exists here only to make the child kindless.
    authz_kind = None
    authz_kind_reason = (
        "planted by rule 13's self-test: the aggregate half of a kindless pair, so the "
        "canary below it reaches the policy-noun question rather than the derived one."
    )

    label = models.CharField(max_length=32)


class CanaryScoped(TenantScopedModel):
    # Planted: a scoped model NOBODY CAN BE GIVEN A CAPABILITY OVER. It is
    # authorized under an aggregate that is not a kind, so it derives no
    # `<kind>.create` of its own, and no policies.py names its noun — the two
    # halves rule 13 exists to refuse together.
    authz_kind_of = "aggregate"

    aggregate = models.ForeignKey(CanaryAggregate, on_delete=models.CASCADE, related_name="+")
    label = models.CharField(max_length=32)
