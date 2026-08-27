

class NegOrdinaryStamps(OrgScopedModel):
    """`_at` is the house grammar for EVERY timestamp in the product.

    Reading them all as retry clocks would demand a relay for `created_at` and
    a sweep for `archived_at`, and the rule would be noise inside a week. The
    retry-clock grammar is deliberately narrow, and that narrowness is declared
    rather than pretended away.
    """

    approved_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
