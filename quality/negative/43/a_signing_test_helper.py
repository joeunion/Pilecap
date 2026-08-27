"""A test helper that signs a body to drive a door. Outside the walk, and must be.

This is the shape every signature test in the tree already has — build the bytes,
compute what an honest sender would send, post it — and it computes an HMAC it
never compares, which is the signer discriminator exactly. It is not a second
signer: it is a CALLER, standing where a subscriber or a provider stands.

`tests/` is outside the walk by the same exclusion every AST check in this engine
uses, and this fixture is what proves the exclusion is live rather than assumed.
`scripts/mail_demo.py` is the same argument one directory up, and rule 43's
`does_not_cover` says so.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def signed_post(*, client: Any, url: str, secret: str, payload: dict[str, Any]) -> Any:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return client.post(
        url,
        data=body,
        content_type="application/json",
        headers={"X-Signature": f"sha256={digest}"},
    )
