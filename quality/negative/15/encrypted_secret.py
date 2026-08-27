

class NegEncryptedSigner(OrgScopedModel):
    """`WebhookEndpoint.secret`'s shape after W6a.

    IN the population — the name is `secret` and the rule looked straight at it
    — and silent because the field type is encrypted. That is the distinction
    worth proving: silent because judged, not silent because unexamined.
    """

    endpoint = models.URLField()
    secret = EncryptedCharField(max_length=255)
