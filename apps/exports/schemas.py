"""The wire shapes. Pydantic, and therefore the same shapes every door uses.

One schema language across REST, MCP tools, webhook bodies and socket payloads
is why there is no second serializer system in this repository. Schemas are
thin: shape in, shape out. No writes happen here.

**Nothing here carries a `Field(alias=...)`, and that is a rule rather than an
accident** (ADR example-3): an alias is a NAME, REST renders by field name and
the MCP transport renders `structuredContent` by alias, so an alias makes the
two doors describe one row with two key sets and every value equal — the class
of finding a value-by-value test is blind to. Relations and computed strings are
walked by a **property on the model** instead, which `from_attributes` finds
under one name at both doors. `tests/test_doors_over_the_wire.py` compares the
two key sets and is what keeps this true.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import ListPage, StrictIn, example


class ExportIn(StrictIn):
    """What a client may send to ask for an archive.

    There is no `organization` on this list and its absence is the enforcement:
    an export lands at the organization the request was made under — the `X-Org`
    header, or your default one — so no body can put one somewhere the caller is
    not a member.

    There is no `models` list either, and that is deliberate rather than
    unfinished. An export is "everything you can see", derived from the model
    registry (`apps/exports/census.py`), and a client that could name the tables
    would be a client whose archive silently stops covering the table somebody
    added on Thursday — which is the exact failure the derived census exists to
    prevent, moved from the server to the caller.
    """

    scope: str = Field(
        default="organization",
        json_schema_extra=example("organization"),
        description=(
            "How much to export: `organization` for everything the organization you "
            "are acting as can see, `tenant` for the whole account."
        ),
    )
    idempotency_key: str = Field(
        default="",
        max_length=255,
        json_schema_extra=example("nightly-2026-08-24"),
        description=(
            "Your own name for this request. Sending the same one twice returns the "
            "first export instead of building a second archive."
        ),
    )


class ExportFilter(FilterSchema):
    """The narrowings a client may ask for, declared rather than improvised.

    A `FilterSchema` is how ninja turns query parameters into a `Q` without any
    route reading `request.GET` — which is where filtering usually goes wrong,
    because a hand-rolled filter reaches into `.filter(**request.GET)` and lets
    a client query any column and traverse any relation.

    `status` is an exact match: it is a word from a closed vocabulary, and a
    substring match on it would make `?status=fail` quietly mean `failed`.
    """

    status: Annotated[str | None, FilterLookup(q="status__iexact")] = Field(
        default=None, json_schema_extra=example("completed")
    )


class ExportOut(Schema):
    """What a client gets back for one export.

    **The two download fields are a pair and a client reads them as one.**
    `download_url` is a short-lived presigned link straight to object storage;
    `download_path` is this API's own authenticated route, which answers `302`
    with that same link. Both are present whenever there is an archive and both
    are `null` until then, so `download_url or download_path` is right as it
    always was — which is why there is still no third field saying which kind of
    deployment this is. (Before XPr the pair really did vary: `download_url` was
    absent where `default_storage` could not sign. The archive now lives in the
    files seam, which refuses a deployment that has named no bucket, so the
    signing branch is the only one left and the pair has become a redundancy a
    client already handles rather than a fork it has to.)

    `manifest` is deliberately on the read shape rather than behind a second
    request: it is how a client knows what the archive contains — which tables,
    how many rows each, which columns were left out and why, and which tables a
    subtree export could not carry. A client that had to download a multi-
    gigabyte zip to find out it was missing a table would find out too late.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("6f1b1f9c-1d3e-4a5b-8c7d-2e9f0a1b2c3d"))
    status: str = Field(json_schema_extra=example("completed"))
    scope: str = Field(json_schema_extra=example("organization"))
    tenant_id: UUID = Field(json_schema_extra=example("1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f"))
    organization_id: UUID = Field(json_schema_extra=example("2d3e4f5a-6b7c-4d8e-9f0a-1b2c3d4e5f60"))
    # `Export.organization_slug` — the property, not a traversal (ADR example-3).
    organization_slug: str = Field(json_schema_extra=example("northern-branch"))
    requested_by_id: UUID | None = Field(
        default=None, json_schema_extra=example("3e4f5a6b-7c8d-4e9f-8a1b-2c3d4e5f6071")
    )
    manifest: dict = Field(  # type: ignore[type-arg]  # an open document, by contract
        default_factory=dict,
        json_schema_extra=example(
            {
                "version": 1,
                "models": [{"label": "example.Widget", "rows": 128}],
                "skipped_models": [],
            }
        ),
    )
    artifact_bytes: int = Field(json_schema_extra=example(41_238))
    error: str = Field(json_schema_extra=example(""))
    created_at: datetime = Field(json_schema_extra=example("2026-08-24T09:30:00Z"))
    updated_at: datetime = Field(json_schema_extra=example("2026-08-24T09:31:12Z"))
    completed_at: datetime | None = Field(
        default=None, json_schema_extra=example("2026-08-24T09:31:12Z")
    )
    # `Export.expires_at` — derived from `created_at` and the retention window,
    # so the window lives in one place and no row carries a stale copy of it.
    expires_at: datetime = Field(json_schema_extra=example("2026-09-23T09:30:00Z"))
    # `Export.download_url` / `Export.download_path` — both model properties.
    download_url: str | None = Field(
        default=None,
        json_schema_extra=example("https://files.example.com/tenants/acme/…?X-Amz-Signature=…"),
    )
    download_path: str | None = Field(
        default=None,
        json_schema_extra=example("/api/v1/exports/6f1b1f9c-1d3e-4a5b-8c7d-2e9f0a1b2c3d/download/"),
    )


class ExportPage(ListPage):
    """A page of exports — the list envelope, for the door with no query string.

    REST gets this shape from ninja's `@paginate` and never has to name it. The
    MCP tool returns a value rather than a response, so the same envelope has to
    be a schema it can declare — and it is deliberately the *same* envelope,
    inherited from `core.schemas.ListPage`, because a machine client that has
    learned to unwrap the REST list should not have to learn a second shape.
    """

    items: list[ExportOut]


class ExportDownloadOut(Schema):
    """Where to fetch an archive from, for a door that cannot carry bytes.

    The machine door's answer to the same capability the HTTP `/download/` route
    serves. A tool result has no equivalent of a response body streaming forty
    megabytes, so it says **where** rather than **what** — the same move
    `delete_widget` makes when the HTTP door answers `204` and the tool answers
    with the row that went (ADR example-3's neighbour). Nothing here is a
    capability REST does not have, which is why this app takes no door-parity
    exemption.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID = Field(json_schema_extra=example("6f1b1f9c-1d3e-4a5b-8c7d-2e9f0a1b2c3d"))
    download_url: str | None = Field(
        default=None,
        json_schema_extra=example("https://files.example.com/tenants/acme/…?X-Amz-Signature=…"),
    )
    download_path: str | None = Field(
        default=None,
        json_schema_extra=example("/api/v1/exports/6f1b1f9c-1d3e-4a5b-8c7d-2e9f0a1b2c3d/download/"),
    )
    artifact_bytes: int = Field(json_schema_extra=example(41_238))
    expires_at: datetime = Field(json_schema_extra=example("2026-09-23T09:30:00Z"))
