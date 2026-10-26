"""The inbound door: verify → store → hand to a workflow → 202; never processed inline.

`source` is one row, so the tenant and the secret cannot disagree (ADR connections-1).
The raw body is verified with `hmac.compare_digest`; an inbound name is the caller's.
does-not-cover: a provider delivery replayed inside the provider's retention with no delivery id.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from apps.core.actor import system_actor
from apps.core.exceptions import Forbidden, Invalid
from apps.core.log import get_logger
from apps.core.models import Tenant
from apps.core.roads import road
from apps.core.time import UTC, now
from apps.events import services
from apps.events.activities import SIGNATURE_PREFIX, sign_v2
from apps.events.models import Event

log = get_logger("apps.events.receivers")


@runtime_checkable
class SignedSource(Protocol):
    """A row that carries its own tenant and its own signing secret.

    **A protocol rather than a base class or an import**, for the reason every
    seam in this repository is one: the row that satisfies it lives in
    `apps.connections` (`Connection`, whose `webhook_secret` reads out of its
    encrypted credentials), and `apps.events` may not import a sibling platform
    app — `import-linter` holds them independent. Structural typing is what lets
    the callee state its requirement without naming the caller.

    It is also what makes a product's own row work with no ceremony: anything
    with these two attributes is a source, which is the point of ADR
    connections-1. A future second provider table inherits the safety by
    construction rather than by remembering.

    `webhook_secret` and not `secret`: the name says which secret. A row that
    holds several — an API token, a client secret, the shared key a *sender*
    signs with — must not be able to satisfy this protocol by accident with the
    wrong one.
    """

    @property
    def tenant(self) -> Tenant: ...

    @property
    def webhook_secret(self) -> str: ...


def expected_signature(*, secret: str, body: bytes) -> str:
    """What a correctly signed body's `X-Signature` looks like.

    The same computation the outbound side uses (`activities.sign`), so a
    product that signs and receives with this template speaks to itself.
    """
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


@road(
    "inbound_signature",
    example="apps/events/tests/test_receivers.py::test_an_uppercase_hex_digest_is_accepted",
)
def signature_matches(*, secret: str, body: bytes, signature: str) -> bool:
    """Accepts `sha256=<hex>` or the bare hex, either case, over the raw body — the one verifier.

    `apps.connections` reaches it through `core.bridge` rather than keeping a copy.
    An empty secret, an empty signature and a non-ASCII one are `False`, never "skip the check".
    """
    if not secret:
        # Keyed on the empty string, anyone could compute a signature that verifies.
        return False
    offered = signature.strip()
    if not offered or not offered.isascii():
        return False
    if offered.lower().startswith(SIGNATURE_PREFIX):
        offered = offered[len(SIGNATURE_PREFIX) :]
    expected = expected_signature(secret=secret, body=body).removeprefix(SIGNATURE_PREFIX)
    return hmac.compare_digest(expected, offered.lower())


#: How far apart the timestamp in an `X-Signature-V2` header and the verifier's
#: own clock may be before the delivery is refused as stale. Five minutes, the
#: same window Stripe publishes, and symmetric: a delivery five minutes old is
#: accepted and so is one whose sender's clock is five minutes fast, because a
#: subscriber and a sender that disagree about the time by a little are common
#: and a replay a year later is not.
#:
#: **A constant, not a setting, and the trigger to promote it is written down**:
#: the first subscriber whose clock legitimately drifts past this, or the first
#: relay that batches deliveries and cannot present them inside it. Then it
#: becomes a per-endpoint field — the number is a property of one integration,
#: not of the deployment — and not before. A knob nobody has needed is a knob
#: that gets set to a year by whoever first sees a stale-delivery log line.
SIGNATURE_V2_TOLERANCE = timedelta(minutes=5)


def signature_v2_tolerance() -> timedelta:
    """The `X-Signature-V2` window, as a call — the bridge holds callables, not values."""
    return SIGNATURE_V2_TOLERANCE


def parse_signature_v2(signature: str) -> tuple[int, str] | None:
    """Pull `t` and `sha256` out of an `X-Signature-V2` value, or `None`.

    The header is comma-separated `key=value` elements and this reads them as a
    mapping rather than as a fixed pair, deliberately: the whole reason v1 has
    an algorithm prefix is that a scheme grows, and a verifier that insisted on
    exactly two elements in exactly one order would break the day a third one is
    added for somebody else's benefit. Unknown elements are ignored; a duplicate
    key keeps the first, so an attacker cannot append a second `t=` and hope the
    verifier and the signer disagree about which one counts.

    `isdigit` and a length bound rather than a bare `int()`: the header is
    whatever a caller sent, and a million-digit integer is a free CPU burn.
    **A header outside ASCII is `None`**: no element this scheme defines carries
    such a character, `isdigit` says yes to a superscript `int()` refuses, and
    `hmac.compare_digest` raises on a non-ASCII string — either of which would
    turn a forged header into a 500 rather than a refusal.
    """
    if not signature.isascii():
        return None
    elements: dict[str, str] = {}
    for part in signature.split(","):
        key, separator, value = part.strip().partition("=")
        if separator:
            elements.setdefault(key.strip(), value.strip())
    timestamp = elements.get("t", "")
    digest = elements.get(SIGNATURE_PREFIX.rstrip("="), "")
    if not digest or not timestamp.isdigit() or len(timestamp) > 20:
        return None
    return int(timestamp), digest


def signature_v2_matches(*, secret: str, body: bytes, signature: str) -> bool:
    """Constant-time signature check **and** a freshness window. Both, or false.

    This is the house verifier for the scheme this template *sends*
    (`activities.sign_v2`), and the reference a subscriber's own code should
    match. Two things have to be true: the digest is the one this key produces
    over `<timestamp>.<the raw bytes received>`, and that timestamp is within
    `SIGNATURE_V2_TOLERANCE` of now. A delivery captured off the wire and sent
    again tomorrow fails the second even though it passes the first, which is
    the whole difference between this and `signature_matches`.

    The window is checked before the digest, and that is safe in the only
    direction it needs to be: an unverified timestamp can cause a **refusal**
    and never an acceptance, because the digest that is checked next covers the
    timestamp — so editing `t` to be fresh changes the digest and the delivery
    is refused anyway.

    **An empty secret is `False` before anything is computed**, and that is the
    third thing that has to be true. `compare_digest` is honest about bytes and
    says nothing about whether there was a key: with no key, the HMAC is keyed on
    the empty string, which is a key every forger already holds.
    """
    if not secret:
        # The forgery class: a caller who knows this source's secret is empty
        # signs with the empty string and produces a header that verifies.
        return False
    parsed = parse_signature_v2(signature)
    if parsed is None:
        return False
    timestamp, digest = parsed
    signed_at = datetime.fromtimestamp(timestamp, tz=UTC)
    if abs(now() - signed_at) > SIGNATURE_V2_TOLERANCE:
        return False
    expected = sign_v2(secret=secret, body=body, timestamp=timestamp)
    return hmac.compare_digest(expected, f"t={timestamp},{SIGNATURE_PREFIX}{digest}")


def verify_and_store(
    *,
    request_body: bytes,
    signature: str,
    source: SignedSource,
    name: str,
    payload: dict[str, Any] | None = None,
) -> Event:
    """Verify one inbound webhook, store it, and hand it to the dispatch workflow.

    Returns the stored `Event`. Raises `Forbidden` when the signature does not
    verify — the door maps that to 403 — and `Invalid` when the body is not
    JSON. Nothing else here can fail: parsing the *meaning* of the payload is
    the workflow's job, not the door's, which is the whole point of storing it
    first.

    **`source` is the row the caller already resolved**, and both the secret the
    body is verified against and the tenant the event lands in are read off it,
    here, once. The caller cannot pass a tenant that disagrees with the secret
    because it does not pass either (ADR connections-1). The signature is the
    enforcement: this is not a check that refuses a mismatch, it is a shape in
    which a mismatch cannot be written down.

    `payload` overrides the parsed body for a sender that posts form-encoded
    data or something else the caller has already decoded.

    The stored event is dispatched onward like any other, so a product can
    subscribe its own webhook endpoints to inbound events and a socket client
    sees them arrive. That is deliberate: "somebody else told us something" is
    as much an event as "we did something".
    """
    tenant = source.tenant
    if not signature_matches(secret=source.webhook_secret, body=request_body, signature=signature):
        log.warning("events.inbound.rejected", name=name, tenant_id=str(tenant.pk))
        raise Forbidden("That signature does not verify.")

    if payload is None:
        try:
            decoded = json.loads(request_body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Invalid({"body": ["The body is not JSON."]}) from exc
        payload = decoded if isinstance(decoded, dict) else {"body": decoded}

    event = services.record_event(
        tenant=tenant,
        name=name,
        payload=payload,
        occurred_at=now(),
        actor=system_actor(tenant=tenant),
    )
    services.enqueue_dispatch(tenant=tenant, event_id=event.pk)
    log.info("events.inbound.stored", name=name, event_id=str(event.pk))
    return event
