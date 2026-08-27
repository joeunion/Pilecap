

class CanaryPlainIntegration(OrgScopedModel):
    """`credentials` — the name the grammar was widened to include.

    It is here to earn the `Connection.credentials` negative. Had the grammar
    stopped at `secret|*_secret|*_token`, that negative would have been silent
    because the rule never LOOKED at it, and every future `credentials` column
    would have been unwatched. This canary is what proves the name is really in
    the population.
    """

    provider = models.CharField(max_length=64)
    credentials = models.JSONField(default=dict, blank=True)
