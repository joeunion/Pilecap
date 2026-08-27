

class NegDigestedCredential(OrgScopedModel):
    """A digest is not a recoverable secret.

    `ApiToken.key_hash` and `Invitation.token_hash` are the tree's two, and both
    are right exactly as they are: the plaintext exists once, in the issuing
    service's return value, and is never stored. Encrypting the digest would
    protect nothing — there is nothing to protect — and would break the unique
    lookup that authenticates every request, because an encrypted column cannot
    be filtered on.

    Excluded by construction rather than by two allow-list entries, because
    allow-list entries breed and a product's third hash column would arrive
    needing a third one.
    """

    name = models.CharField(max_length=200)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
