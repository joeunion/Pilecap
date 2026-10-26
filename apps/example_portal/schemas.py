"""The wire shapes of a portal request — the same shapes every door uses."""

from __future__ import annotations

# golden: portal begin
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field

from pilecap import ListPage, StrictIn, example, personal

REQUEST_ID = "4c1e7a2b-9d3f-4e5a-8b6c-7d8e9f0a1b2c"
WIDGET_ID = "3f0c2a8e-54b1-4c5e-9d7a-1b2c3d4e5f60"
REQUESTER_ID = "5b7c9d1e-3f5a-4b7c-8d9e-0f1a2b3c4d5e"
TENANT_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
ORGANIZATION_ID = "6e7f8a9b-0c1d-4e2f-9a3b-4c5d6e7f8a9b"
NOTE_EXAMPLE = "The left mount arrived scratched; can you send another?"
#: `PortalRequest.Priority`'s values, inline: a referenced enum component reads as a lax body.
Priority = Literal["low", "normal", "high"]


class PortalRequestIn(StrictIn):
    """What a customer sends to ask about a widget.

    There is no `organization` here: the request lands where the customer is
    acting, and there is nothing for a caller to forge.
    """

    widget_id: UUID = Field(json_schema_extra=example(WIDGET_ID))
    note: str = Field(min_length=1, max_length=4000, json_schema_extra=example(NOTE_EXAMPLE))
    priority: Priority | None = Field(default=None, json_schema_extra=example("high"))


class PortalRequestFilter(FilterSchema):
    """The narrowings a client may ask of the request list, declared, never read off the query."""

    widget_id: Annotated[UUID | None, FilterLookup(q="widget_id")] = Field(
        default=None, json_schema_extra=example(WIDGET_ID)
    )
    priority: Annotated[Priority | None, FilterLookup(q="priority")] = Field(
        default=None, json_schema_extra=example("high")
    )


class PortalRequestOut(Schema):
    """A portal request as every door answers it.

    `organization_id` is the node the customer was acting at when they asked —
    where the request lives, and whose readers can see it.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example(REQUEST_ID))
    widget_id: UUID = Field(json_schema_extra=example(WIDGET_ID))
    note: str = Field(json_schema_extra=example(NOTE_EXAMPLE))
    priority: Priority = Field(json_schema_extra=example("normal"))
    requester_id: UUID = Field(json_schema_extra=example(REQUESTER_ID))
    requester_email: str = Field(json_schema_extra=personal(example("pat@customer.example")))
    tenant_id: UUID = Field(json_schema_extra=example(TENANT_ID))
    organization_id: UUID = Field(json_schema_extra=example(ORGANIZATION_ID))
    created_at: datetime = Field(json_schema_extra=example("2026-09-30T09:12:00Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-09-30T09:12:00Z"))


class PortalRequestPage(ListPage):
    """A page of portal requests — the list envelope, for the door with no query string."""

    items: list[PortalRequestOut]


# golden: portal end
