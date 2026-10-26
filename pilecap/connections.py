"""A product's providers and inbound webhooks: registration, connections and their credentials."""

from __future__ import annotations

from apps.connections.events import (
    CONNECTION_CREATED,
    CONNECTION_CREDENTIALS_UPDATED,
    CONNECTION_REVOKED,
    CONNECTION_SIGNATURE_SCHEME_UPDATED,
    WEBHOOK_RECEIVED,
)
from apps.connections.providers import (
    InboundHandler,
    Provider,
    WebhookVerifier,
    get_provider,
    register,
    register_inbound_handler,
    register_webhook_verifier,
)
from apps.connections.selectors import (
    get_connection,
    get_connection_for_webhook,
    list_connections,
    list_inbound_webhooks,
)
from apps.connections.services import (
    create_connection,
    record_inbound_webhook,
    revoke_connection,
    set_signature_scheme,
    update_credentials,
)

__all__ = [
    "CONNECTION_CREATED",
    "CONNECTION_CREDENTIALS_UPDATED",
    "CONNECTION_REVOKED",
    "CONNECTION_SIGNATURE_SCHEME_UPDATED",
    "InboundHandler",
    "Provider",
    "WEBHOOK_RECEIVED",
    "WebhookVerifier",
    "create_connection",
    "get_connection",
    "get_connection_for_webhook",
    "get_provider",
    "list_connections",
    "list_inbound_webhooks",
    "record_inbound_webhook",
    "register",
    "register_inbound_handler",
    "register_webhook_verifier",
    "revoke_connection",
    "set_signature_scheme",
    "update_credentials",
]
