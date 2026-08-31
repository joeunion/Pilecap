

class CanaryStrandedJob(OrgScopedModel):
    """A row with a retry clock and no relay — the HIGH finding, planted back.

    The column will be written the moment a job is enqueued, and the index will
    make the query fast. There is no query. A job whose dispatch dies holds its
    promise for ever and nothing anywhere will notice.

    Its clock is spelled `queue_retry_at` rather than `next_attempt_at` on
    purpose: readers are found by field NAME, so a canary borrowing the real
    Outbox column's name would be rescued by the real Outbox relay and would
    prove nothing about this plant. (That name-sharing is declared on the rule.)
    """

    status = models.CharField(max_length=16, default="pending")
    queue_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
