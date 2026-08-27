

class NegEncryptedIntegration(OrgScopedModel):
    """`Connection.credentials`' shape — the field the PM asked to see silent.

    It is silent for the right reason. `credentials` is in the name grammar, so
    the rule examined this field and found it encrypted; the canary beside it
    (`plaintext_credentials.py`) is what proves the examination is real.
    """

    provider = models.CharField(max_length=64)
    credentials = EncryptedJSONField(default=dict, blank=True)
