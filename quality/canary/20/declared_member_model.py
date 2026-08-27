

class CanaryLedgerEntry(OrgScopedModel):
    """A second append-only member, declared exactly the way a product declares one.

    Nothing in rules.yaml names it. If rule 20 covers it, the population is read
    off the declaration; if rule 20 misses it, the rule is still a name list
    wearing a generalisation.
    """

    append_only: ClassVar[bool] = True

    amount = models.DecimalField(max_digits=19, decimal_places=4)
