"""The inbound door: **verify → store → hand to a workflow → 202.**

An inbound webhook is never processed inline (`architecture.md`, "Rejected, and
why"): a slow or failing handler loses the event, and the sender's retry policy
is not something this product controls. So the receiving route does three things
and returns — and all three of them are here, once, so that
`apps.connections`' provider receivers (rung A4) and any product's own receiver
share one implementation rather than three subtly different ones.

    from apps.events.receivers import verify_and_store

    @router.post("/inbound/{provider}/", auth=None)   # on the rules.yaml allow-list
    def receive(request, provider: str):
        event = verify_and_store(
            request.body,
            request.headers.get("X-Signature", ""),
            source=connection,                        # the ROW, not a pair of values
            name=f"{provider}.{payload['type']}.received",
        )
        return 202, {"id": str(event.pk)}

**`source` is a row, and that is the whole of ADR connections-1.** This used to
take `secret` and `tenant` as two loose parameters, which asked every caller to
keep them matched by hand — and a caller that verified against connection A's
secret while storing into tenant B would have written a *forged* event into
somebody else's tenant, silently, with no refusal anywhere to catch it. The
pairing is not checked now; it is **unrepresentable**, because both values come
off the one object the caller already resolved.

Four properties, and each is a bug somebody has shipped:

* **The signature is compared with `hmac.compare_digest`**, never with `==`. A
  byte-by-byte comparison that returns early leaks, over enough requests, how
  much of a forged signature was right.
* **The raw body is what is verified**, not a re-serialised parse of it. Two
  JSON documents can mean the same thing and hash differently.
* **The name is the caller's**, and it is deliberately *not* checked against the
  declared registry the way `emit` checks an outbound name: an inbound event is
  somebody else's vocabulary. It is namespaced by the provider at the call site
  so it cannot collide with this product's own names.
* **The tenant and the secret come off one row**, so they cannot disagree.

## The timestamp window: whose contract has one, and whose does not

An HMAC over a body says *who* signed it and never *when*, so bytes captured
off the wire once verify for as long as the key lives. That is not a flaw in
HMAC, it is what HMAC is; the fix is to sign a timestamp too and refuse one that
is old. This module now holds both halves, and which one applies depends on
whose scheme is being verified:

* **The scheme this template sends** (`X-Signature-V2`, from
  `activities.sign_v2`) carries a signed timestamp, and `signature_v2_matches`
  refuses a delivery outside `SIGNATURE_V2_TOLERANCE`. A product that points
  this template's webhooks at this template's receiver gets the window.
* **A provider's scheme** is the provider's, and `signature_matches` — bytes
  only, no window — is still what `verify_and_store` uses, because there is
  nothing to check a window against in a contract that signs no timestamp.
  Inventing one would refuse legitimate deliveries and stop nothing.

So the residual, stated honestly, is now only about inbound providers:

* a replayed provider delivery **within** the provider's retention — the same
  bytes, the same valid signature, sent again by anyone who captured them —
  still verifies, and lands **once**, because `apps.connections`'
  `(connection, delivery_id)` dedup answers a redelivery with the row it
  already stored (ADR connections-1);
* a replay **older than** that, or one from a provider that sends no delivery
  id, is **out of scope**, and the trigger to close it is unchanged: the first
  provider contract that carries a signed timestamp gets a window checked
  against it, and not before — a window checked against a timestamp nobody
  signed is a comfort, not a control. `signature_v2_matches` is the shape that
  check takes when that day comes.

This is recorded here rather than left implicit because a reader who assumes an
HMAC alone defeats replay will build on that assumption.

This module is a door helper, not a service: the write it does is
`services.record_event`, and the workflow hand-off is `services.enqueue_dispatch`.
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


def signature_matches(*, secret: str, body: bytes, signature: str) -> bool:
    """Constant-time comparison, tolerating a missing algorithm prefix.

    Senders differ: some send `sha256=<hex>`, some send the bare hex. Both are
    accepted; anything else is not.

    **An empty secret is `False`, never "skip the check"** — see
    `signature_v2_matches` for the forgery class both clauses refuse.
    """
    if not secret:
        # A source with no key: anyone who knows the secret is empty can compute
        # the HMAC keyed on the empty string and forge a signature that verifies.
        return False
    if not signature:
        return False
    expected = expected_signature(secret=secret, body=body)
    offered = signature.strip()
    if not offered.startswith(SIGNATURE_PREFIX):
        offered = f"{SIGNATURE_PREFIX}{offered}"
    return hmac.compare_digest(expected, offered)


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
    """
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
    request_body: bytes,
    signature: str,
    *,
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
