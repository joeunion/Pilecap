

def _neg_arm_reaper(*, row_id, when):
    """Arm the clock, and later clear it — the writes, kept in the negative.

    They are here so that the selector beside them is demonstrably what makes
    this model silent. A negative that passed because nothing wrote the column
    would prove nothing about a rule whose whole question is whether a WRITE can
    stand in for a read.
    """
    return NegSweptJob(id=row_id, status="pending", reaper_retry_at=when)


def _neg_clear_reaper(*, row_ids):
    return NegSweptJob.objects.filter(id__in=row_ids).update(
        reaper_retry_at=None, status="done"
    )
