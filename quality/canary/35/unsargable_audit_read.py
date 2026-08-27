

# CANARY (rule 35): 's innocent "improvement" — the audit trail's
# tenant read re-spelt case-normalised. upper(cast(tenant_id)) is unsargable:
# no index can serve it, the scan stops being a lookup and becomes a walk of
# whatever index survives enable_seqscan = off, and only the plan can see it —
# the query count stays exactly 1 (FINDING A's whole lesson).
from django.db.models import CharField as _CanaryCharField
from django.db.models.functions import Cast as _CanaryCast
from django.db.models.functions import Upper as _CanaryUpper


def _canary_unsargable_for_tenant(self, tenant):  # planted violation
    if tenant is None:
        return self.none()
    return self.annotate(
        _canary_tenant_text=_CanaryUpper(_CanaryCast("tenant", _CanaryCharField()))
    ).filter(_canary_tenant_text=str(getattr(tenant, "pk", "")).upper())


AuditEntryQuerySet.for_tenant = _canary_unsargable_for_tenant
