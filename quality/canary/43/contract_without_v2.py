

# Planted: the contraction attempted at ONE site of three. The wire still sends
# `X-Signature-V2` on every delivery and the reference receiver still checks it;
# the prose a subscriber reads no longer mentions it. Nothing errors, no test
# fails, and the next person to write a verifier against this document writes
# one that ignores the only header with a freshness window in it.
#
# A redefinition rather than an edit, because that is what an append can be and
# what Python does with it: the second definition of a name is the one the
# module answers with, so this IS the route's docstring as far as anything
# reading the module is concerned.
def create_endpoint_route(request: object, payload: object) -> object:
    """Create a webhook endpoint

    Register a URL to receive webhooks. **The signing secret is returned once, here.**

    **Verifying a delivery.** `X-Signature: sha256=<hex>` — HMAC-SHA256 of the
    exact bytes of the request body, hex-encoded and prefixed with `sha256=`.
    Hash the bytes you received; do not parse the JSON and re-encode it.

    Refusals you can get here:

    * `400 invalid` — a malformed URL. Nothing is created.
    """
    raise NotImplementedError
