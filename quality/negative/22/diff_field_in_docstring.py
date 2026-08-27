

CANARY_NEGATIVE_PROSE = """
The conventions here are taught by example, and the examples live in prose:

    class ChannelPreference(OrgScopedModel):
        recipient = models.ForeignKey(Recipient, on_delete=models.CASCADE)
        muted_until_on = models.DateField(null=True)

None of that is a field on anything. A diff layer that reads it as a schema
change demands a migration for a paragraph — which is what it did, once.
"""
