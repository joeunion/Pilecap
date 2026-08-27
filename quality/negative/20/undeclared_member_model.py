

class CanaryOrdinaryEntry(OrgScopedModel):
    """A row that LOOKS like a ledger and never declared itself append-only.

    The declaration is the population. A rule that guessed from the name would
    be the name list all over again, with worse manners.
    """

    amount = models.DecimalField(max_digits=19, decimal_places=4)
