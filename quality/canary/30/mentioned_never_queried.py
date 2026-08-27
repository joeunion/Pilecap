

class CanaryMentionedClock(OrgScopedModel):
    """The near-miss that must still fire, and the reason this check is AST.

    Its clock is WRITTEN in another module and named in that module's prose —
    and neither is a read. This is the exact state `Outbox.next_attempt_at` was
    in for the whole of P0: written, indexed, documented in three modules, and
    queried by nothing. A grep-shaped rule would have been green through all of
    it, which is the same as having no rule.
    """

    escalation_retry_at = models.DateTimeField(null=True, blank=True)
