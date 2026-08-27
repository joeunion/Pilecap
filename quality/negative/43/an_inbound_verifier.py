"""The opposite job, and it must stay silent.

A module that computes an HMAC and hands it to `hmac.compare_digest` is
verifying somebody else's signature, not writing one. Every product that
receives a provider webhook has one of these — `apps/connections/api.py` is this
tree's — and a rule that read "computes an HMAC" as "signs" would make an
inbound receiver a violation, which would leave a product with no way to check a
signature except not to.

The discriminator is the comparison and not a list of module names, so this
stays silent the day a product writes its own, with nothing to add anywhere.
"""

from __future__ import annotations

import hashlib
import hmac


def expected_signature(*, secret: str, body: bytes) -> str:
    """The HMAC an honest sender would have computed."""
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def signature_matches(*, secret: str, body: bytes, provided: str) -> bool:
    """Constant-time comparison, and a refusal when there is no secret."""
    if not secret:
        return False
    offered = provided.strip().lower().removeprefix("sha256=")
    return hmac.compare_digest(expected_signature(secret=secret, body=body), offered)
