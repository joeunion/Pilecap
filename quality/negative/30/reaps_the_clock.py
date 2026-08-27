

def _neg_list_reapable_jobs(*, before):
    """The genuine read: a `filter()` lookup on the clock, and nothing else.

    No `order_by` and no string argument anywhere — the keyword half of the
    match is on its own here, which is what makes this the negative for LEX-1's
    fix. Restricting keywords to read verbs must leave THIS shape counting, or
    the fix would have traded a silent rule for a noisy one.
    """
    return NegSweptJob.objects.filter(
        status="pending", reaper_retry_at__lt=before
    ).iterator()
