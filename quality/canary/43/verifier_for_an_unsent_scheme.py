

# Planted: a house verifier seam for a scheme no delivery sends. The shape is
# the one that gets written when a scheme is designed and half-landed — the
# parser arrives first, the signer is "next rung", and the branch sits there
# reading to every later reviewer as support for `X-Signature-V3`. Nothing can
# reach it; nothing fails; the document says nothing about it either way.
def parse_signature_v3(signature: str) -> tuple[int, str] | None:
    """Pull `t` and `sha256` out of an `X-Signature-V3` value, or `None`."""
    elements: dict[str, str] = {}
    for part in signature.split(","):
        key, separator, value = part.strip().partition("=")
        if separator:
            elements.setdefault(key.strip(), value.strip())
    timestamp = elements.get("t", "")
    digest = elements.get("sha256", "")
    if not digest or not timestamp.isdigit():
        return None
    return int(timestamp), digest
