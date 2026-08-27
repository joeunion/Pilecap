

class NegRelayedJob(OrgScopedModel):
    """A retry clock WITH a relay — `Outbox.next_attempt_at`'s shape after W5.

    The clock is only half of the mechanism; the selector planted beside it is
    the other half, and the rule is satisfied by the half that was missing. The
    name is this fixture's own so that the planted reader is the ONLY thing that
    can satisfy it — borrowing `next_attempt_at` would let the real Outbox relay
    answer for it, and a negative that passes for the wrong reason is
    decoration.
    """

    status = models.CharField(max_length=16, default="pending")
    dispatch_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
