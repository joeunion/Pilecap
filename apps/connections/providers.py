"""What a provider has to be able to do, and the registry that finds one.

**Providers are product work** (`architecture.md`): this app ships the shape,
not Stripe. A product adds a module with a class satisfying `Provider` and calls
`register()` from its `AppConfig.ready()`; nothing here is edited, and nothing
in `config/` is either.

The protocol is deliberately two methods and no base class. `Provider` is a
`typing.Protocol`, so a product's class satisfies it by having the right shape
rather than by inheriting from this module — which matters because the
alternative, an abstract base, is an import from every provider back into this
app and a version of this app every provider is pinned to.

    class StripeProvider:
        slug = "stripe"
        base_url = "https://api.stripe.com"

        def authorization_url(self, *, connection, state, redirect_uri): ...
        def exchange_code(self, *, connection, code, redirect_uri): ...

    register(StripeProvider())

`exchange_code` is the one place in this app that may make an outbound call
from inside a request rather than from an activity, and the reason is the
protocol's, not ours: an OAuth authorization code is single-use and expires in
seconds, with the user's browser sitting on the callback waiting. Everything
else external goes through `client.http_client` inside a Temporal activity.

**The second registry, and why this app has one (ADR comms-4).** An inbound
delivery arrives at one route — the signature-verified receiver in `api.py` —
whatever it is about, because a second `auth=None` route is a second signature
scheme to get wrong. But this app must not *interpret* a payload: it has no
idea what an ESP's bounce means, and the app that does must not own a webhook
door. So the receiver hands the stored delivery on, by provider slug, to a
handler the owning app registered from its own `AppConfig.ready()` —
`register_inbound_handler("comms-email", …)` is the worked case. This app calls
a function it knows nothing about; the other app never writes a route. Neither
imports the other's door.

A handler is **not** where a slow job goes. It runs inside the receiver's
request, after the store, and everything it does is on the clock a sender's
timeout is watching. The one in `apps/comms` is a row update, an event and a
signal registered on commit — anything heavier is what a workflow is for.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from apps.connections.models import ACCESS_TOKEN_KEY, Connection, InboundWebhook
from apps.core.actor import Actor
from apps.core.exceptions import NotFound


class Provider(Protocol):
    """One external system, as far as this app needs to know about it."""

    slug: str
    base_url: str

    def authorization_url(self, *, connection: Connection, state: str, redirect_uri: str) -> str:
        """Where to send the user's browser to start the handshake.

        `state` is opaque and must be echoed back to the callback unchanged —
        it is what makes the callback verifiable (`api.py` mints it, stores it
        in the cache, and consumes it once).
        """
        ...

    def exchange_code(
        self, *, connection: Connection, code: str, redirect_uri: str
    ) -> dict[str, Any]:
        """Trade the authorization code for the credentials to store.

        Returns the mapping `services.update_credentials` will merge into the
        connection's encrypted credentials — `access_token`, whatever refresh
        token and expiry the provider gives, and nothing that is not a
        credential.
        """
        ...


_registry: dict[str, Provider] = {}


def register(provider: Provider) -> None:
    """Add a provider.

    A product's own providers register from its `AppConfig.ready()`, which is the
    one place Django guarantees the app registry is complete. The bundled
    `ExampleProvider` at the foot of this module is the exception and can afford
    to be: it lives in the same module as the registry, so there is no import to
    order and nothing to be half-loaded.
    """
    _registry[str(provider.slug).strip().lower()] = provider


def unregister(slug: str) -> None:
    """Take one out again. For a test that planted one."""
    _registry.pop(str(slug).strip().lower(), None)


def registered() -> dict[str, Provider]:
    """Every provider this deployment knows how to speak to."""
    return dict(_registry)


def get_provider(slug: str) -> Provider:
    """The provider for a slug, or the domain's not-found.

    `NotFound` rather than `KeyError`, because the caller is a door: a
    connection naming a provider this deployment has no adapter for is
    indistinguishable, to a client, from a connection that is not there.
    """
    provider = _registry.get(str(slug).strip().lower())
    if provider is None:
        raise NotFound(f"No provider is registered for {slug!r}.")
    return provider


# --- The inbound-handler registry ---------------------------------------------


class InboundHandler(Protocol):
    """What the receiver calls once a delivery for this provider is stored.

    Keyword-only, like everything else that crosses a boundary here, and it
    returns nothing: a handler acts, and the receiver's answer to the sender is
    `202` whatever it did. A handler that raises is caught and logged by
    `services.record_inbound_webhook` — the store is the durability and the
    sender's retry is the recovery, so one bad payload never costs the receipt.
    """

    def __call__(self, *, received: InboundWebhook, actor: Actor) -> None: ...


_inbound: dict[str, InboundHandler] = {}


def register_inbound_handler(provider: str, handler: InboundHandler) -> None:
    """Say which function interprets deliveries for one provider slug.

    Called from the *receiving* app's `AppConfig.ready()` — the one place
    Django guarantees the app registry is complete — and never from this app.
    One handler per slug: registering twice replaces, so a reload in the dev
    server does not stack two.
    """
    _inbound[str(provider).strip().lower()] = handler


def unregister_inbound_handler(provider: str) -> None:
    """Take one out again. For a test that planted one."""
    _inbound.pop(str(provider).strip().lower(), None)


def inbound_handler(provider: str) -> InboundHandler | None:
    """The handler for a provider slug, or `None`.

    `None` rather than a raise, and the asymmetry with `get_provider` is
    deliberate: a connection naming an unknown *provider* is a broken
    connection, but a provider with no inbound handler is the ordinary case —
    most integrations are outbound only, and their deliveries are stored, handed
    to the event spine, and nothing more.
    """
    return _inbound.get(str(provider).strip().lower())


def registered_inbound_handlers() -> dict[str, InboundHandler]:
    """Every provider slug some app has claimed the inbound deliveries of."""
    return dict(_inbound)


# --- The third registry: how a sender proves it is the sender ---------------------
#
# ADR comms-3 gave this app one inbound route because a second `auth=None` route
# is a second signature scheme to get wrong. It did not, and could not, give the
# world one signature *scheme*: an ESP signs the way its own vendor decided, and
# `api.py`'s HMAC-over-body-in-`X-Signature` is the shape this template ships and
# not a standard anyone else implements. The receiver's own docstring has always
# said "a product whose provider uses a different header overrides both on the
# provider"; until E1′ there was nowhere to put the override, so the sentence was
# an intention rather than a seam.
#
# This is that seam, and it is deliberately the *same shape* as the inbound
# handler registry above: the app that knows what a provider is registers a
# function from its own `ready()`, this app calls something it knows nothing
# about, and neither imports the other's door. What travels is **one bool or
# `None`**, and the three answers are the whole contract — see below.


class WebhookVerifier(Protocol):
    """Whether this request really came from the sender the connection names.

    Keyword-only, and the answer is **three-valued** on purpose:

    * `True` — this verifier recognised the scheme and the signature is good;
    * `False` — this verifier recognised the scheme and the signature is bad.
      The receiver answers 401 and stores nothing;
    * `None` — *this verifier has no opinion about this request.* The receiver
      falls back to its own HMAC, unchanged.

    `None` is what keeps the seam fail-safe. A verifier is registered against a
    provider slug once, at start-up, but whether it can actually check anything
    may depend on configuration that is read per request — which ESP
    `EMAIL_BACKEND` names, whether that ESP's vendor library is installed, and
    whether the connection is carrying a secret at all. The alternative designs
    both fail open: a verifier that returned `True` when it could not check
    would open the door to anyone who learned the URL, and one that refused to
    register unless configured would leave the deployment silently on the
    fallback with nothing saying so. A verifier that cannot check says so, and
    the door's own credential — which is always present and always checked —
    stands.

    It receives the **raw body**, because a signature is over bytes and any
    re-encoding is a different message, and the request's headers, because that
    is where every scheme in the world puts the signature.
    """

    def __call__(
        self, *, connection: Connection, body: bytes, headers: Mapping[str, str]
    ) -> bool | None: ...


_verifiers: dict[str, WebhookVerifier] = {}


def register_webhook_verifier(provider: str, verifier: WebhookVerifier) -> None:
    """Say which function checks the signature on deliveries for one provider slug.

    Called from the *receiving* app's `AppConfig.ready()`, like
    `register_inbound_handler`, and never from this app. One verifier per slug:
    registering twice replaces, so a reload in the dev server does not stack two.
    """
    _verifiers[str(provider).strip().lower()] = verifier


def unregister_webhook_verifier(provider: str) -> None:
    """Take one out again. For a test that planted one."""
    _verifiers.pop(str(provider).strip().lower(), None)


def webhook_verifier(provider: str) -> WebhookVerifier | None:
    """The verifier for a provider slug, or `None`.

    `None` here means *nobody claimed this slug's signatures*, which is the
    ordinary case and the template's own: the receiver checks its HMAC and that
    is the whole credential.
    """
    return _verifiers.get(str(provider).strip().lower())


def registered_webhook_verifiers() -> dict[str, WebhookVerifier]:
    """Every provider slug some app has claimed the signature checking of."""
    return dict(_verifiers)


class ExampleProvider:
    """The worked provider: a complete handshake with nothing on the other end.

    It exists for the same reason `apps/example` does — so the pattern is
    exercised by the test suite from an empty database, with no network, no
    credentials and no account anywhere. A product registers its own and may
    delete this one; the tests that drive it are the template's, not the
    product's.

    `exchange_code` mints a token from the code deterministically. That is what
    makes the OAuth test an assertion about the stored credentials rather than
    about a mock's call count.
    """

    slug = "example"
    base_url = "https://example.invalid"
    authorize_endpoint = "https://example.invalid/oauth/authorize"

    def authorization_url(self, *, connection: Connection, state: str, redirect_uri: str) -> str:
        from urllib.parse import urlencode

        query = urlencode(
            {
                "client_id": f"example-client-{connection.tenant_id}",
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "state": state,
                "scope": "read write",
            }
        )
        return f"{self.authorize_endpoint}?{query}"

    def exchange_code(
        self, *, connection: Connection, code: str, redirect_uri: str
    ) -> dict[str, Any]:
        return {
            ACCESS_TOKEN_KEY: f"example-access-token-for-{code}",
            "refresh_token": f"example-refresh-token-for-{code}",
            "token_type": "bearer",
        }


register(ExampleProvider())
