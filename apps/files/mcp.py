"""The machine door onto documents — the same eight capabilities the REST door has.

Door parity (house rule 17): every capability `api.py` offers a person, this
offers a machine, over the *same* selectors, the *same* services and the *same*
schemas. And it **says** the same thing out of one docstring (house rule 41):
every `description=` below is `contract_of(<the REST route>)`, so the two doors
cannot come to describe one capability differently — prose drifts long before
behaviour does.

**This app takes no door-parity exemption, and the one place it could have is
worth naming.** The bytes are not a capability either door has: an upload is a
`PUT` the caller makes to storage on a signed URL, and a download is a `GET` the
caller makes to storage on another. Both doors hand out the *place* and neither
hands out the *stream*, so there is nothing asymmetric to exempt — which is what
ADR files-2 means by "the bytes are deliberately door-less". An agent uploading a
document does exactly what a browser does, in the same three steps, and
`upload_url` is a real answer to it rather than a hint that it should have used
HTTP.

What a tool is allowed to be is thin: it takes **who is calling** from the
principal the token middleware left on the ASGI scope (never from an argument), it
calls services and selectors, and it maps no refusals of its own — `tool_call`
turns a domain exception into a `ToolError` once, the way `config/api.py` turns
one into a status code once.

The bodies are plain `def` rather than `async def`: the transport runs a
synchronous tool on a worker thread, which is where the synchronous ORM belongs,
and `tool_call` closes the connection that thread borrowed.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from django.db.models import QuerySet
from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from apps.core.api import ordered_by
from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.mcp import acting_tenant, tool_call
from apps.files.api import (
    ORDERING,
    VERSION_ORDERING,
    add_version_route,
    archive_file_route,
    confirm_upload_route,
    create_file_route,
    document_of,
    download_body,
    downloadable,
    issue_download_url_route,
    list_files_route,
    list_versions_route,
    retrieve_file,
)
from apps.files.models import FileVersion, StoredFile
from apps.files.schemas import (
    FileDownloadOut,
    FileFilter,
    FilePage,
    FileVersionOut,
    FileVersionPage,
    StoredFileOut,
    UploadTicketOut,
)
from apps.files.selectors import get_version, list_versions
from apps.files.selectors import list_files as list_files_selector
from apps.files.services import add_version, archive_file, confirm_upload, create_file


def _ticket(ticket: Any) -> UploadTicketOut:
    """The upload ticket's wire shape, built the same way `api.py` builds it."""
    return UploadTicketOut(
        file=StoredFileOut.model_validate(ticket.file),
        version=FileVersionOut.model_validate(ticket.version),
        upload_url=ticket.upload_url,
        expires_in=ticket.expires_in,
    )


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="list_files",
        description=contract_of(list_files_route),
    )
    def list_files_tool(
        ctx: Context[Any],
        purpose: str | None = None,
        filename: str | None = None,
        ordering: str = "-created_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> FilePage:
        with tool_call(ctx) as acting:
            # Scoped first and only narrowed after — the type widens from
            # `ScopedQuerySet` to `QuerySet` for the same reason it does in
            # `api.py`: filtering returns the plain one, and narrowing a queryset
            # cannot widen its tenant.
            files: QuerySet[StoredFile] = FileFilter(purpose=purpose, filename=filename).filter(
                list_files_selector(tenant=acting.tenant, org=acting.org, actor=acting.actor())
            )
            files = ordered_by(files, ordering, allowed=ORDERING, default="-created_at")
            page = cursor_page(
                files,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return FilePage(
                items=[StoredFileOut.model_validate(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="get_file",
        description=contract_of(retrieve_file),
    )
    def get_file_tool(ctx: Context[Any], file_id: UUID) -> StoredFileOut:
        with tool_call(ctx) as acting:
            # A document in another tenant, or in a branch this hat cannot see, is
            # `not_found` exactly as it is over HTTP: a refusal that distinguished
            # the two would tell the caller the document exists.
            return StoredFileOut.model_validate(
                document_of(
                    tenant=acting_tenant(acting),
                    org=acting.org,
                    file_id=file_id,
                    actor=acting.actor(),
                )
            )

    @server.tool(
        name="create_file",
        description=contract_of(create_file_route),
    )
    def create_file_tool(
        ctx: Context[Any],
        filename: str,
        content_type: str,
        size_bytes: int,
        purpose: str = "upload",
    ) -> UploadTicketOut:
        with tool_call(ctx) as acting:
            return _ticket(
                create_file(
                    tenant=acting_tenant(acting),
                    actor=acting.actor(),
                    filename=filename,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    purpose=purpose,
                )
            )

    @server.tool(
        name="add_version",
        description=contract_of(add_version_route),
    )
    def add_version_tool(
        ctx: Context[Any],
        file_id: UUID,
        content_type: str,
        size_bytes: int,
    ) -> UploadTicketOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            return _ticket(
                add_version(
                    tenant=tenant,
                    actor=acting.actor(),
                    file=document_of(
                        tenant=tenant, org=acting.org, file_id=file_id, actor=acting.actor()
                    ),
                    content_type=content_type,
                    size_bytes=size_bytes,
                )
            )

    @server.tool(
        name="confirm_upload",
        description=contract_of(confirm_upload_route),
    )
    def confirm_upload_tool(
        ctx: Context[Any],
        file_id: UUID,
        version: int,
        idempotency_key: str,
    ) -> FileVersionOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            document = document_of(
                tenant=tenant, org=acting.org, file_id=file_id, actor=acting.actor()
            )
            row = get_version(
                tenant=tenant, file=document, version=version, org=acting.org, actor=acting.actor()
            )
            return FileVersionOut.model_validate(
                confirm_upload(
                    tenant=tenant,
                    actor=acting.actor(),
                    version=row,
                    idempotency_key=idempotency_key,
                )
            )

    @server.tool(
        name="list_versions",
        description=contract_of(list_versions_route),
    )
    def list_versions_tool(
        ctx: Context[Any],
        file_id: UUID,
        ordering: str = "-version",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> FileVersionPage:
        with tool_call(ctx) as acting:
            document = document_of(
                tenant=acting.tenant, org=acting.org, file_id=file_id, actor=acting.actor()
            )
            versions: QuerySet[FileVersion] = list_versions(
                tenant=acting.tenant, file=document, org=acting.org, actor=acting.actor()
            )
            versions = ordered_by(versions, ordering, allowed=VERSION_ORDERING, default="-version")
            page = cursor_page(
                versions,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return FileVersionPage(
                items=[FileVersionOut.model_validate(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(
        name="issue_download_url",
        description=contract_of(issue_download_url_route),
    )
    def issue_download_url_tool(
        ctx: Context[Any], file_id: UUID, version: int | None = None
    ) -> FileDownloadOut:
        with tool_call(ctx) as acting:
            # The same gate the HTTP route goes through, imported rather than
            # restated, so the four refusals cannot come apart: no such document,
            # no such version, no bytes at it yet, and nothing current.
            return download_body(
                downloadable(
                    tenant=acting_tenant(acting),
                    actor=acting.actor(),
                    file_id=file_id,
                    version=version,
                )
            )

    @server.tool(
        name="archive_file",
        description=contract_of(archive_file_route),
    )
    def archive_file_tool(ctx: Context[Any], file_id: UUID) -> StoredFileOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            return StoredFileOut.model_validate(
                archive_file(
                    tenant=tenant,
                    actor=acting.actor(),
                    file=document_of(
                        tenant=tenant, org=acting.org, file_id=file_id, actor=acting.actor()
                    ),
                )
            )
