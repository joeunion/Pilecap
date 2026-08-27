

class CanaryPlainSigner(OrgScopedModel):
    """The exact defect W6a fixed, planted back.

    An outbound signing secret as a plain `CharField`, sitting in the clear
    beside neighbours that are all encrypted. Nobody decides this — it is what
    happens when a field is added in a hurry and the reviewer is reading the
    logic. A database dump, a replica, a backup and a traceback are four ways it
    leaves.
    """

    endpoint = models.URLField()
    secret = models.CharField(max_length=255)
