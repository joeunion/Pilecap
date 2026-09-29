# collides: create_endpoint_route — a replace-mode stand-in for the real route module: the post-contraction route under its real name
"""THE CONTRACTION, third of three: the contract prose after v1 is gone.

One scheme documented, and the sentence that promised v1 would not be withdrawn
without notice is gone with it — because by the time this lands, the notice has
been given and the subscribers have moved. That is the whole reason the
contraction is a judgement about somebody else's integrations and not a date.
"""

from __future__ import annotations


def create_endpoint_route(request: object, payload: object) -> object:
    """Create a webhook endpoint

    Register a URL to receive webhooks. **The signing secret is returned once, here.**

    **Verifying a delivery.** `X-Signature-V2: t=<seconds>,sha256=<hex>` — read
    the number after `t=` (Unix seconds). Join it to the **exact bytes of the
    request body** with a single `.` between them, compute HMAC-SHA256 of that,
    hex-encode it, and compare it with the value after `sha256=` using a
    constant-time comparison. Then check that `t` is within **five minutes** of
    your own clock, and reject the delivery if it is not. Both checks must pass.

    Hash the bytes you received. Do not parse the JSON and re-encode it, or the
    signature will not match.

    Refusals you can get here:

    * `400 invalid` — a malformed URL. Nothing is created.
    """
    raise NotImplementedError
