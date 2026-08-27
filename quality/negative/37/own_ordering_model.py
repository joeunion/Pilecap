"""Negative: the Organization / SsoDomain shape — its own non-recency ordering.

Out of edge 1's population entirely (nothing here is read by recency), and its
own index leads on `tenant`, so edge 2 has nothing to say either.
"""


class Canary37OwnOrdering(OrgScopedModel):
    name = models.CharField(max_length=64)

    class Meta(OrgScopedModel.Meta):
        ordering: ClassVar[list] = ["name"]
        indexes: ClassVar[list] = [
            models.Index(fields=["tenant", "name"], name="canary37_own_ordering"),
        ]
