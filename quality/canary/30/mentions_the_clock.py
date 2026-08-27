

def _canary_schedule_escalation(*, row, when):
    """Set `escalation_retry_at` so the escalation sweep can pick this up later.

    The docstring above names the column twice and this function writes it. A
    rule that counted either as a reader would be counting the defect as its own
    cure — the promise is made here and kept nowhere.
    """
    row.escalation_retry_at = when
    row.save(update_fields=["escalation_retry_at", "updated_at"])
    return row
