"""The wire shapes of a note — the same shapes every door uses."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import ArchivedOut, ListPage, Show, StrictIn, example, personal

SUBJECT_EXAMPLE = "widget:3f0c2a8e-54b1-4c5e-9d7a-1b2c3d4e5f60"
NOTE_ID = "8d2e6f10-7a3b-4c1d-9e0f-2a4b6c8d0e12"
AUTHOR_ID = "5b7c9d1e-3f5a-4b7c-8d9e-0f1a2b3c4d5e"
TENANT_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"
ORGANIZATION_ID = "6e7f8a9b-0c1d-4e2f-9a3b-4c5d6e7f8a9b"


class DjbNoteFilter(Schema):
    """The two query parameters a note list reads: whose notes, and which cut."""

    subject: str = Field(
        min_length=3,
        max_length=128,
        json_schema_extra=example(SUBJECT_EXAMPLE),
        description="Whose notes, as `<kind>:<id>` — for example `widget:<id>`.",
    )
    show: Show = Field(
        default="live",
        json_schema_extra=example("live"),
        description="`live` (the default), `archived`, or `all`.",
    )


class DjbNoteIn(StrictIn):
    """What a client may send to write a note.

    `subject` names what the note is about, as `<kind>:<id>`. There is no
    `organization` here: the note lands where its subject lives.
    """

    subject: str = Field(
        min_length=3,
        max_length=128,
        json_schema_extra=example(SUBJECT_EXAMPLE),
        description="What the note is about, as `<kind>:<id>` — for example `widget:<id>`.",
    )
    body: str = Field(
        min_length=1,
        max_length=20000,
        json_schema_extra=example("Called the site lead; the mount ships Tuesday."),
    )


class DjbNotePatch(StrictIn):
    """A change to a note's words. The subject never moves by an edit."""

    body: str | None = Field(
        default=None,
        min_length=1,
        max_length=20000,
        json_schema_extra=example("Called the site lead; the mount now ships Wednesday."),
    )


class DjbNoteOut(ArchivedOut):
    """A note as every door answers it.

    `subject` is the pointer exactly as it was written (`<kind>:<id>`);
    `organization_id` is the subject's organization, where the note lives.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example(NOTE_ID))
    subject: str = Field(json_schema_extra=example(SUBJECT_EXAMPLE))
    body: str = Field(json_schema_extra=example("Called the site lead; the mount ships Tuesday."))
    author_id: UUID = Field(json_schema_extra=example(AUTHOR_ID))
    author_email: str = Field(json_schema_extra=personal(example("dana@example.com")))
    tenant_id: UUID = Field(json_schema_extra=example(TENANT_ID))
    organization_id: UUID = Field(json_schema_extra=example(ORGANIZATION_ID))
    created_at: datetime = Field(json_schema_extra=example("2026-09-27T09:12:00Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-09-27T09:12:00Z"))


class DjbNotePage(ListPage):
    """A page of notes — the list envelope, for the door with no query string."""

    items: list[DjbNoteOut]
