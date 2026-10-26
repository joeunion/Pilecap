# golden: webhook-in onboarding begin
"""The onboarding provider's inbound webhook, registered from this app's `ready()`."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any, Protocol
from uuid import UUID

from apps.example.selectors import get_widget
from apps.example.services import confirm_widget_onboarding
from pilecap import Actor, Invalid, NotFound

# Never a bare `register` here: the integrations census calls one by that name.
from pilecap.connections import register as register_provider
from pilecap.connections import register_inbound_handler, register_webhook_verifier
from pilecap.tenancy import root_organization

#: The slug a connection to this provider names, and the one its deliveries are claimed by.
ONBOARDING_SLUG = "onboarding"
#: What every delivery this provider sends carries: the timestamped signature and its id.
ONBOARDING_REQUIRED_HEADERS = ("x-signature-v2", "x-delivery-id")


class OnboardingDelivery(Protocol):
    """The stored delivery as the handler reads it: the raw body the sender signed."""

    @property
    def body(self) -> str: ...


class OnboardingProvider:
    """The onboarding system as `pilecap.connections` knows it: a slug, no OAuth."""

    slug = ONBOARDING_SLUG
    base_url = "https://onboarding.invalid"

    def authorization_url(self, *, connection: object, state: str, redirect_uri: str) -> str:
        """Refused: a connection to this provider holds its webhook secret, not an OAuth grant."""
        raise Invalid({"provider": ["This provider is connected by its webhook secret."]})

    def exchange_code(self, *, connection: object, code: str, redirect_uri: str) -> dict[str, Any]:
        """Refused, as `authorization_url` is: there is no code to exchange."""
        raise Invalid({"provider": ["This provider is connected by its webhook secret."]})


def verify_onboarding_delivery(
    *, connection: object, body: bytes, headers: Mapping[str, str]
) -> bool | None:
    """True/False replaces the receiver's HMAC check, None defers; another scheme rewrites this."""
    sent = {name.lower() for name in headers}
    if not all(name in sent for name in ONBOARDING_REQUIRED_HEADERS):
        return False
    return None


def handle_onboarding_delivery(*, received: OnboardingDelivery, actor: Actor) -> None:
    """Confirm the widget a delivery names, through its service, at the root."""
    tenant = actor.tenant
    if tenant is None:
        raise NotFound()
    at_root = replace(actor, org=root_organization(tenant=tenant))
    widget_id = UUID(str(json.loads(received.body)["widget_id"]))
    widget = get_widget(tenant=tenant, widget_id=widget_id, org=at_root.org, actor=at_root)
    confirm_widget_onboarding(tenant=tenant, actor=at_root, widget=widget)


def register_onboarding_webhooks() -> None:
    """Claim the onboarding slug: the provider, its verifier and its handler."""
    register_provider(OnboardingProvider())
    register_webhook_verifier(ONBOARDING_SLUG, verify_onboarding_delivery)
    register_inbound_handler(ONBOARDING_SLUG, handle_onboarding_delivery)


# golden: webhook-in onboarding end
