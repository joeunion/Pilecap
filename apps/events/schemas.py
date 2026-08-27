"""The wire shape of an event — one definition, every door.

`EventOut` is the **webhook body**: it is what the delivery activity signs and
sends, and it is what the realtime bridge pushes into a tenant's socket group
the moment `apps.realtime` is installed. One contract language
(`architecture.md`, "API layer"), so a subscriber that has learned the shape on
one door has learned it on the others — and, because the delivery activity dumps
this schema rather than assembling a dictionary of its own, there is no second
definition to drift from it.

`WebhookEndpointOut` and `DeliveryOut` arrived with the door that needed them:
until then the spine was managed through the admin and the shell, and a
schema with no door is a contract nobody is holding to.

**The one thing to read this file for is the pair of endpoint Out shapes.**
`WebhookEndpointOut` — what get, list, update, pause and resume answer with —
has **no secret field at all**, and that absence is the contract rather than an
omission: a signing key that can be read a second time is a key that leaks
twice. `WebhookEndpointSecretOut` is the only shape that carries one, it is
returned by exactly two acts (registering an endpoint, and issuing it a new
key), and each of those acts is the one moment the plaintext exists outside the
encrypted column. A caller that loses it issues a new one; nothing reads the old
one back.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import ListPage, StrictIn, example


class EventOut(Schema):
    """One event, as a subscriber receives it.

    `payload` is the emitting app's own `Out` shape plus its `v` — the same
    body a REST client would have seen for the row that changed.

    `organization_id` is **which part of the tenant the row belongs to**, and it
    is optional in both senses: absent from an event about something no branch
    owns in particular, and additive to a contract subscribers already read
    (ADR realtime-2a). It is on the envelope rather than on a second payload
    because the envelope is the one serialisation both the webhook door and the
    socket door are handed — the fan-out cannot narrow on a field it cannot see,
    and inventing a second body for the socket is how the two doors start
    disagreeing.

    **It narrows sockets, not webhooks.** A `WebhookEndpoint` subscribes per
    tenant and keeps receiving every event it asked for; narrowing deliveries by
    organization is a product decision nobody has made.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    v: int
    occurred_at: datetime
    correlation_id: str
    causation_id: str
    organization_id: UUID | None = None
    payload: dict[str, Any]


def envelope(event: Any) -> dict[str, Any]:
    """The JSON-safe body for one `Event`. The bytes that get signed.

    A function rather than a method on the model, so the wire shape lives with
    the other wire shapes and a model does not have to know what JSON is.
    """
    return dict(EventOut.from_orm(event).model_dump(mode="json"))


# --- Subscribers -------------------------------------------------------------


class WebhookEndpointIn(StrictIn):
    """Where a tenant wants its events delivered.

    There is **no secret field**, deliberately: the signing key is minted by the
    server so that the only copy a client ever holds is the one the create
    response hands back. A key a client chose is a key a client can have chosen
    badly, and a key a client can send twice is a key that can be re-sent by
    whoever read the first request.

    `event_names` empty means every event — the honest default for "tell me what
    happens here". A name that no installed app declares is refused against the
    catalogue (`GET /catalogue/`), because a subscription to an event that does
    not exist is a subscription that silently never fires.
    """

    url: str = Field(json_schema_extra=example("https://hooks.example.com/djb"))
    event_names: list[str] = Field(
        default=[], json_schema_extra=example(["example.widget.created"])
    )
    description: str = Field(default="", json_schema_extra=example("Ops alerting"))


class WebhookEndpointPatch(StrictIn):
    """Change an endpoint's address, subscription or label. Omitted fields stay.

    `is_active` is not here and never will be: pausing and resuming are verbs
    on their own sub-paths, because a column a door can set is a column a door
    can set back by accident. The signing key is not here either — it is issued,
    never assigned.
    """

    url: str | None = Field(
        default=None, json_schema_extra=example("https://hooks.example.com/djb")
    )
    event_names: list[str] | None = Field(
        default=None, json_schema_extra=example(["example.widget.created"])
    )
    description: str | None = Field(default=None, json_schema_extra=example("Ops alerting"))


class WebhookEndpointFilter(FilterSchema):
    """The narrowings a client may ask for over its endpoints."""

    is_active: Annotated[bool | None, FilterLookup(q="is_active")] = None


class WebhookEndpointOut(Schema):
    """One endpoint, as every door reports it — **with no secret on it**.

    The absence is the contract. Every read of an endpoint answers this shape,
    so there is no route, tool, page or export anywhere that can hand a signing
    key back: it is not that the key is filtered out, it is that no reader has a
    field for it. `WebhookEndpointSecretOut` is the only shape that carries one.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    url: str = Field(json_schema_extra=example("https://hooks.example.com/djb"))
    is_active: bool = Field(json_schema_extra=example(True))
    event_names: list[str] = Field(json_schema_extra=example(["example.widget.created"]))
    description: str = Field(json_schema_extra=example("Ops alerting"))
    created_at: datetime
    updated_at: datetime


class WebhookEndpointSecretOut(Schema):
    """An endpoint **and the signing key, said once**.

    Answered by exactly two acts — registering an endpoint and issuing it a new
    key — and by nothing else, ever. The subscriber computes
    `X-Signature: sha256=<hmac>` over the raw body it receives with this value;
    we keep it encrypted at rest because a signature cannot be computed from a
    hash, and we never read it back out through a door because a key that can be
    read twice has leaked twice.
    """

    endpoint: WebhookEndpointOut
    secret: str = Field(json_schema_extra=example("whsec_5tYq2ZbN8xR1mK4vD7pL0jH3gS6cF9wA"))


class WebhookEndpointPage(ListPage):
    """A page of endpoints — the list envelope, for a door with no query string.

    The same `{items, has_more, next_cursor, count}` ninja's `@paginate` gives
    the HTTP list, declared as a schema because a tool returns a value rather
    than a response.
    """

    items: list[WebhookEndpointOut]


# --- The catalogue -----------------------------------------------------------


class EventTypeOut(Schema):
    """One event name this deployment can emit, and the app that declares it.

    **Derived, never listed.** The population is read off the installed apps'
    own `events.py` modules at request time (`events.declared_names()`), which
    is the same registry `emit` validates against and the same one `introspect`
    prints — so a subscriber picks from what actually exists, and the catalogue
    cannot rot the day another app declares an event.
    """

    name: str = Field(json_schema_extra=example("example.widget.created"))
    app: str = Field(json_schema_extra=example("example"))


class EventTypePage(ListPage):
    """A page of the catalogue, in the list envelope both doors use."""

    items: list[EventTypeOut]


# --- Deliveries --------------------------------------------------------------


class DeliveryFilter(FilterSchema):
    """The narrowings a client may ask for over its deliveries."""

    status: Annotated[str | None, FilterLookup(q="status")] = None
    endpoint_id: Annotated[UUID | None, FilterLookup(q="endpoint_id")] = None


class DeliveryOut(Schema):
    """One endpoint's attempt at one event — including the one that never landed.

    `attempts` is the lineage: it counts every HTTP attempt this pair has had,
    across the first dispatch and every replay, on the one row that is unique on
    (endpoint, event). So a dead letter that has been replayed reads as a higher
    `attempts` than the one that dead-lettered it, against the same
    `dead_lettered_at` — which is what makes "was this ever sent again, and did
    it land" a query rather than a log search.

    `event_name` is a **property on `Delivery`** rather than a `resolve_` hook on
    this schema, and the distinction is load-bearing. A ninja resolver is
    consulted *before* plain attribute access on whatever object is being
    validated — including a `DeliveryOut` instance being re-validated as an item
    of `DeliveryPage`, which has no `event` to read through. So a resolver here
    would work at the HTTP door and fail at the machine one, which is the
    door-parity break this whole app is against. A property is found by both.
    Comms' `MessageOut` avoids aliases for the same family of reason.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    endpoint_id: UUID
    event_id: UUID
    event_name: str = Field(json_schema_extra=example("example.widget.created"))
    status: str = Field(json_schema_extra=example("delivered"))
    attempts: int = Field(json_schema_extra=example(1))
    last_code: int | None = Field(default=None, json_schema_extra=example(200))
    last_error: str = Field(json_schema_extra=example(""))
    delivered_at: datetime | None = None
    dead_lettered_at: datetime | None = None
    correlation_id: str = Field(json_schema_extra=example("0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21"))
    created_at: datetime
    updated_at: datetime


class DeliveryPage(ListPage):
    """A page of deliveries, in the list envelope both doors use."""

    items: list[DeliveryOut]
