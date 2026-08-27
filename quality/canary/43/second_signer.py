"""Planted: the second outbound signer, in the gate's own scaffold.

Both halves of the shape in one module, because either alone is a shape and
together they are the finding: an HMAC computed over a body and never compared
with anything, and the result written into a header dict that goes out on a
request. It agrees with `apps/events/activities.py` today — that is why somebody
would write it — and it is a second place for a prefix, an encoding or a
timestamp to drift, months later, inside a subscriber's verifier.

Planted in `zzz_canary` and not a product app: a canary whose liveness depends
on a real app never growing a feature dies the day the tree gets healthier
('s lesson, rule 5's recorded repair).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from apps.connections.client import http_client


def notify(*, url: str, secret: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Signature": f"sha256={digest}",
    }
    with http_client() as client:
        client.post(url, content=body, headers=headers)
