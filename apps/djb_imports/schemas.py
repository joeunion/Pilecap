"""The wire shapes, shared by the REST door, the MCP door and the events.

No `Field(alias=...)` anywhere (ADR example-3): computed values are model
properties (`counts`, `apply_writes`, `expires_at`), found under one name by both
doors.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import ListPage, StrictIn, example


def _declared_kinds(schema: dict[str, Any]) -> None:
    """`kind`'s allowed values: every declared importer's key, **at generation time**.

    Derived from the same walk the service reads (`selectors.list_importers`),
    when the document is generated rather than when this module is imported —
    so a product's `importers.py` is in the enum the moment its app is
    installed, and a document generated with no importer at all says so with an
    empty list rather than one frozen at import.
    """
    from apps.djb_imports.selectors import list_importers

    schema["enum"] = sorted(list_importers())
    schema["example"] = "widget"


class DjbImportIn(StrictIn):
    """What a client sends to stage a file. The organization is the acting hat's."""

    kind: str = Field(
        max_length=64,
        json_schema_extra=_declared_kinds,
        description="Which kind of row the file makes — one of the declared importers.",
    )
    file_id: UUID = Field(
        json_schema_extra=example("6f1b1f9c-1d3e-4a5b-8c7d-2e9f0a1b2c3d"),
        description="The document to import; its current version is the one read.",
    )
    idempotency_key: str = Field(
        default="",
        max_length=255,
        json_schema_extra=example("crm-migration-batch-1"),
        description="Your own name for this request. Sending it again returns the same run.",
    )


class DjbImportFilter(FilterSchema):
    """The narrowings a client may ask the list for. `status` is an exact match."""

    status: Annotated[str | None, FilterLookup(q="status__iexact")] = Field(
        default=None, json_schema_extra=example("previewed")
    )
    kind: Annotated[str | None, FilterLookup(q="kind__iexact")] = Field(
        default=None, json_schema_extra=example("widget")
    )


class DjbImportCountsOut(Schema):
    """What the dry run found, and then what the apply did."""

    create: int = Field(json_schema_extra=example(4))
    update: int = Field(json_schema_extra=example(0))
    unchanged: int = Field(json_schema_extra=example(0))
    refused: int = Field(json_schema_extra=example(1))


class DjbImportOut(Schema):
    """One import run."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("6f1b1f9c-1d3e-4a5b-8c7d-2e9f0a1b2c3d"))
    kind: str = Field(json_schema_extra=example("widget"))
    status: str = Field(json_schema_extra=example("previewed"))
    tenant_id: UUID = Field(json_schema_extra=example("1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f"))
    organization_id: UUID = Field(json_schema_extra=example("2d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f60"))
    #: `null` once the document the run read has been deleted; `digest` and
    #: `file_name` still say what it was.
    file_version_id: UUID | None = Field(
        default=None, json_schema_extra=example("3e4f5a6b-7c8d-4e9f-8a1b-2c3d4e5f6071")
    )
    file_name: str = Field(json_schema_extra=example("widgets.csv"))
    digest: str = Field(json_schema_extra=example("deadbeef" * 8))
    requested_by_id: UUID | None = Field(
        default=None, json_schema_extra=example("4f5a6b7c-8d9e-4f0a-9b1c-2d3e4f5a6b7c")
    )
    applied_by_id: UUID | None = Field(default=None, json_schema_extra=example(None))
    idempotency_key: str = Field(json_schema_extra=example(""))
    counts: DjbImportCountsOut
    apply_writes: int = Field(json_schema_extra=example(4))
    #: The refusal a failed run ended with (`import_invalid` or `run_failed`); `{}` for a cancel.
    failure: dict[str, Any] = Field(default_factory=dict, json_schema_extra=example({}))
    applied_at: datetime | None = Field(default=None, json_schema_extra=example(None))
    cancelled_at: datetime | None = Field(default=None, json_schema_extra=example(None))
    created_at: datetime = Field(json_schema_extra=example("2026-09-27T09:30:00Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-09-27T09:31:12Z"))
    expires_at: datetime = Field(json_schema_extra=example("2026-10-27T09:31:12Z"))


class DjbImportStagedOut(DjbImportOut):
    """The answer to staging: the run, and whether this call made it."""

    # does-not-cover: `created` repeats the 201/200 status; dropping it is breaking (rule 17).
    created: bool = Field(json_schema_extra=example(True))


class DjbImportPage(ListPage):
    """A page of runs — the list envelope, for the machine door."""

    items: list[DjbImportOut]


class DjbImportRowOut(Schema):
    """One line of the file: its values, the preview, and what the apply did."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d"))
    run_id: UUID = Field(json_schema_extra=example("6f1b1f9c-1d3e-4a5b-8c7d-2e9f0a1b2c3d"))
    organization_id: UUID = Field(json_schema_extra=example("2d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f60"))
    row_no: int = Field(json_schema_extra=example(3))
    data: dict[str, Any] = Field(json_schema_extra=example({"name": "", "notes": "third"}))
    outcome_preview: str = Field(json_schema_extra=example("refused"))
    outcome: str = Field(json_schema_extra=example(""))
    refusal: dict[str, Any] = Field(
        default_factory=dict,
        json_schema_extra=example({"code": "invalid", "detail": "…", "errors": {"name": ["…"]}}),
    )
    object_id: UUID | None = Field(default=None, json_schema_extra=example(None))


class DjbImportRowPage(ListPage):
    """A page of one run's rows, for the machine door."""

    items: list[DjbImportRowOut]
