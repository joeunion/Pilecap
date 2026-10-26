"""The shapes tags travel in — one set for REST, MCP and the event payload.

A subject is spelled `<kind>:<id>` on every door (`widget:0196…`), in a body
and in a query alike: one string a person can paste, and the kind is the
authorization kind the product already publishes (`introspect` → `policies`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import ArchivedOut, ListPage, StrictIn, example

TAG_ID = "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"
SUBJECT = "widget:0196a1f2-6b1c-7a30-8e4f-1a2b3c4d5e6f"


class DjbTagIn(StrictIn):
    """A word to coin. Its slug is derived from the name and is the identity."""

    name: str = Field(min_length=1, max_length=100, json_schema_extra=example("Urgent"))


class DjbTagPatch(StrictIn):
    """A new spelling for a word. The slug follows the name."""

    name: str = Field(min_length=1, max_length=100, json_schema_extra=example("Very urgent"))


class DjbTagOut(ArchivedOut):
    """One word in the tenant's vocabulary, live or archived."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example(TAG_ID))
    name: str = Field(json_schema_extra=example("Urgent"))
    slug: str = Field(json_schema_extra=example("urgent"))
    tenant_id: UUID = Field(json_schema_extra=example("0196a1f2-0000-7000-8000-000000000001"))
    created_at: datetime = Field(json_schema_extra=example("2026-09-27T08:24:00Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-09-27T08:24:00Z"))


class DjbTagPage(ListPage):
    """A page of tags."""

    items: list[DjbTagOut]


class DjbTagLinkIn(StrictIn):
    """Put a tag on a subject. Sending the same pair twice answers the same link."""

    tag_id: UUID = Field(json_schema_extra=example(TAG_ID))
    subject: str = Field(min_length=3, max_length=128, json_schema_extra=example(SUBJECT))


class DjbTagLinkOut(Schema):
    """One tag on one subject, in the branch the subject lives in."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("0196a1f2-8d4e-7f52-ac3b-6e7f8a9b0c1d"))
    tag_id: UUID = Field(json_schema_extra=example(TAG_ID))
    tag_name: str = Field(json_schema_extra=example("Urgent"))
    tag_slug: str = Field(json_schema_extra=example("urgent"))
    subject: str = Field(json_schema_extra=example(SUBJECT))
    subject_kind: str = Field(json_schema_extra=example("widget"))
    subject_id: UUID = Field(json_schema_extra=example("0196a1f2-6b1c-7a30-8e4f-1a2b3c4d5e6f"))
    tenant_id: UUID = Field(json_schema_extra=example("0196a1f2-0000-7000-8000-000000000001"))
    organization_id: UUID = Field(json_schema_extra=example("0196a1f2-0000-7000-8000-000000000002"))
    created_at: datetime = Field(json_schema_extra=example("2026-09-27T08:24:00Z"))


class DjbTagLinkPage(ListPage):
    """A page of one subject's tags."""

    items: list[DjbTagLinkOut]
