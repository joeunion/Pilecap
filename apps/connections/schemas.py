"""The wire shapes — the same ones for REST, MCP, the webhook body and a socket.

**`ConnectionOut` has no `credentials` field, and that absence is the
enforcement.** Not a serializer that filters, not a `to_representation` that
pops a key, not `exclude` — a field that is not on the schema cannot be added
back by a route, a tool or a `.model_dump()` somebody wrote in a hurry.
`has_credentials` is what a client is owed: whether the connection is set up.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import StrictIn, example


class ConnectionIn(StrictIn):
    """Open a connection. `credentials` goes in and never comes back out.

    A static API key can be supplied here; an OAuth connection is created with
    no credentials and gains them through the callback.
    """

    provider: str = Field(min_length=1, max_length=64, pattern=r"^[-a-zA-Z0-9_]+$")
    name: str = Field(min_length=1, max_length=200)
    credentials: dict[str, Any] = Field(default_factory=dict)
    is_signature_v2_required: bool = Field(default=True, json_schema_extra=example(True))


class CredentialsIn(StrictIn):
    """New credentials for a connection. Merged into what is already stored."""

    credentials: dict[str, Any] = Field(min_length=1)


class SignatureSchemeIn(StrictIn):
    """Whether the connection's inbound webhook refuses a body-only signature."""

    is_signature_v2_required: bool = Field(json_schema_extra=example(True))


class RevokeIn(StrictIn):
    """Why a connection was revoked, for whoever reads the row afterwards."""

    reason: str = Field(default="", max_length=500)


class ConnectionFilter(FilterSchema):
    """The narrowings a client may ask for, declared rather than improvised."""

    provider: str | None = None
    status: str | None = None
    name: Annotated[str | None, FilterLookup(q="name__icontains")] = None


class ConnectionOut(Schema):
    """What a client gets back. Note what is not here."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    provider: str
    name: str
    status: str
    has_credentials: bool
    is_signature_v2_required: bool = Field(json_schema_extra=example(True))
    last_error: str
    connected_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OAuthStartIn(StrictIn):
    """Where the provider should send the browser back to.

    Optional: a client that says nothing gets this API's own callback route,
    which is the case the template proves end to end.
    """

    redirect_uri: str | None = Field(default=None, max_length=500)


class OAuthStartOut(Schema):
    """Where to send the user, and the state that makes the return trip checkable."""

    connection_id: UUID
    authorization_url: str
    state: str
    expires_in: int


class InboundWebhookOut(Schema):
    """The receipt for a delivery — deliberately not the delivery.

    `body` is absent for the same reason `credentials` is absent from
    `ConnectionOut`: this shape is what an event payload fans out to every
    subscribed endpoint, and an inbound body is somebody else's customer data
    that this product is only the custodian of. Whoever needs the body reads the
    stored row, inside the tenant, through a selector.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    connection_id: UUID
    event_type: str
    status: str
    handed_off_to: str
    handed_off_at: datetime | None
    created_at: datetime


class WebhookAcceptedOut(Schema):
    """What the sender gets: an acknowledgement, and nothing about the tenant.

    202 and an id. Not 200, because nothing has been processed; not a body that
    says which tenant or which provider, because the sender is unauthenticated
    and the only thing it has proved is that it holds this connection's secret.
    """

    id: UUID
    status: str
