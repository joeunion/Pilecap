

# CANARY (rule 35): the relay's candidate read re-spelt so the pinned index
# cannot serve it — the status equality becomes a case-normalised comparison
# and the clock predicate moves into Python, so `outbox_status_next_attempt`
# has no condition it can serve while the statement count stays 1. This is
# rule 30's reader silently losing its index.
from django.db.models.functions import Upper as _CanaryOutboxUpper

_canary_original_list_stranded_outbox = list_stranded_outbox


def list_stranded_outbox(*, before, limit=None, already_seen=0):  # noqa: F811  # planted
    stranded = (
        Outbox.objects.annotate(_canary_status=_CanaryOutboxUpper("status"))
        .filter(_canary_status="PENDING")
        .select_related("event", "event__tenant")
        .order_by("next_attempt_at")
    )
    if limit is None:
        return stranded[already_seen:] if already_seen else stranded
    return stranded[already_seen : already_seen + limit]
