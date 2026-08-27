"""THE CONTRACTION, first of three files: the delivery activity after v1 is gone.

`X-Signature` is recorded-not-taken in the real module: it goes when the first
product's subscribers have migrated, which is a fact about somebody else's
integrations and not something this repository can observe. The day it goes must
be ONE green commit, and this negative is what proves rule 43 will not be the
thing standing in its way.

A whole-module replacement rather than an append, because the contraction is a
REMOVAL and nothing appended can take a header out of a dict. What is planted is
the post-contraction shape, minimal: one scheme, sent through the one signer.
If this fixture ever fires, the rule has become an obstacle to a change this
repository has already decided to make.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

SIGNATURE_PREFIX = "sha256="
SIGNATURE_V2_HEADER = "X-Signature-V2"


def sign_v2(*, secret: str, body: bytes, timestamp: int) -> str:
    """`t=<unix>,sha256=<hex over timestamp.body>` — the one scheme that remains."""
    digest = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},{SIGNATURE_PREFIX}{digest}"


def deliver(*, url: str, secret: str, envelope: dict[str, Any], signed_at: int) -> dict[str, str]:
    body = json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return {
        "Content-Type": "application/json",
        SIGNATURE_V2_HEADER: sign_v2(secret=secret, body=body, timestamp=signed_at),
        "X-Event-Name": str(envelope.get("name", "")),
    }
