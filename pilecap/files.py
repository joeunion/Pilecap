"""The one door to the store: documents, versions, uploads and download addresses."""

from __future__ import annotations

from apps.files.events import (
    FILE_ARCHIVED,
    FILE_MOVED,
    FILE_RESTORED,
    FILE_STORED,
)
from apps.files.selectors import (
    get_downloadable_version,
    get_file,
    get_subject,
    get_version,
    list_files,
    list_versions,
)
from apps.files.services import (
    add_version,
    archive_file,
    confirm_upload,
    create_file,
    issue_download_url,
    move_attached_files,
    restore_file,
)

__all__ = [
    "FILE_ARCHIVED",
    "FILE_MOVED",
    "FILE_RESTORED",
    "FILE_STORED",
    "add_version",
    "archive_file",
    "confirm_upload",
    "create_file",
    "get_downloadable_version",
    "get_file",
    "get_subject",
    "get_version",
    "issue_download_url",
    "list_files",
    "list_versions",
    "move_attached_files",
    "restore_file",
]
