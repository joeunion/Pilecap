

def _canary_schedule_sweep(*, row_id, when):
    """Arm the sweep clock — a WRITE through a constructor keyword.

    `sweep_retry_at=` here names the field on a model constructor. Nothing is
    being looked up: the keyword is the column's new value.
    """
    return CanaryClearedByUpdate(id=row_id, status="pending", sweep_retry_at=when)


def _canary_clear_sweep(*, row_ids):
    """Disarm it — a WRITE through a queryset `.update()`.

    The `filter()` above the update selects rows by id and never names the
    clock; the only keyword naming it belongs to `.update()`, which SETS the
    column. Counting that as a read is counting the defect as its own cure.
    """
    return CanaryClearedByUpdate.objects.filter(id__in=row_ids).update(
        sweep_retry_at=None, status="done"
    )
