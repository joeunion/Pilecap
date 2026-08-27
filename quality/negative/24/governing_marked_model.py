

class CanaryWidgetPolicy(InheritedDownward, OrgScopedModel):
    """Configuration inherited downwards — the one population governing() is for.

    A branch reads the nearest policy on its ancestor chain and never learns of
    any row it was not handed. Upward config resolution, never upward
    visibility.
    """

    kind = models.CharField(max_length=32)
