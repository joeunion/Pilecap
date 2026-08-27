

class CanaryClearedByUpdate(OrgScopedModel):
    """A retry clock whose only life outside this module is being WRITTEN.

    LEX-1's finding, planted. The clock is set by a constructor keyword and
    cleared by a queryset `.update()`, both in another module — and under a
    callee-blind keyword match each of those counted as its own reader, so this
    model passed rule 30 while being in precisely the state rule 30 exists to
    find: written from everywhere, queried by nothing. A product that closes its
    clock in a second module got the rule's pass for free.

    Its clock is spelled `sweep_retry_at` for the same reason every fixture here
    spells its own: readers are matched by field NAME, so borrowing
    `next_attempt_at` would let the real Outbox relay answer for this plant.
    """

    status = models.CharField(max_length=16, default="pending")
    sweep_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
