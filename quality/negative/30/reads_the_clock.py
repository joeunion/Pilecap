

def _neg_list_stranded_jobs(*, before):
    """The reader the clock was written for — `list_stranded_outbox`'s shape.

    A filter lookup and an order_by: overdue first, so a sweep after an outage
    heals in the order the promises were made.
    """
    return (
        NegRelayedJob.objects.filter(status="pending", dispatch_retry_at__lt=before)
        .order_by("dispatch_retry_at")
        .iterator()
    )
