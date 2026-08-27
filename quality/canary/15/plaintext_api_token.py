

class CanaryPlainVendorLink(OrgScopedModel):
    """The same defect under a SUFFIX name and a different plaintext type.

    `TextField` rather than `CharField`, `vendor_token` rather than `secret`:
    the clause is neither one name's habit nor one type's, and a rule that was
    would be a rule about the one field somebody already fixed.
    """

    vendor = models.CharField(max_length=64)
    vendor_token = models.TextField(blank=True)
