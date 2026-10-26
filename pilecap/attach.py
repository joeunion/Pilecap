"""Notes and tags on any noun that declares them: the writes, the reads and the tag model."""

from __future__ import annotations

from apps.djb_notes.events import (
    NOTE_ARCHIVED,
    NOTE_CREATED,
    NOTE_MOVED,
    NOTE_RESTORED,
    NOTE_UPDATED,
)
from apps.djb_notes.selectors import (
    get_note,
    get_subject,
    list_notes,
    list_notes_pointing_at,
)
from apps.djb_notes.services import (
    archive_note,
    create_note,
    move_notes,
    restore_note,
    update_note,
)
from apps.djb_tags.events import (
    TAG_ARCHIVED,
    TAG_CREATED,
    TAG_LINK_CREATED,
    TAG_LINK_DELETED,
    TAG_LINK_MOVED,
    TAG_RENAMED,
    TAG_RESTORED,
)
from apps.djb_tags.models import (
    Tag,
)
from apps.djb_tags.schemas import (
    DjbTagOut,
)
from apps.djb_tags.selectors import (
    get_tag,
    get_tag_link,
    list_tag_links,
    list_tags,
)
from apps.djb_tags.services import (
    archive_tag,
    create_tag,
    create_tag_link,
    delete_tag_link,
    move_tag_links,
    rename_tag,
    restore_tag,
)

__all__ = [
    "DjbTagOut",
    "NOTE_ARCHIVED",
    "NOTE_CREATED",
    "NOTE_MOVED",
    "NOTE_RESTORED",
    "NOTE_UPDATED",
    "TAG_ARCHIVED",
    "TAG_CREATED",
    "TAG_LINK_CREATED",
    "TAG_LINK_DELETED",
    "TAG_LINK_MOVED",
    "TAG_RENAMED",
    "TAG_RESTORED",
    "Tag",
    "archive_note",
    "archive_tag",
    "create_note",
    "create_tag",
    "create_tag_link",
    "delete_tag_link",
    "get_note",
    "get_subject",
    "get_tag",
    "get_tag_link",
    "list_notes",
    "list_notes_pointing_at",
    "list_tag_links",
    "list_tags",
    "move_notes",
    "move_tag_links",
    "rename_tag",
    "restore_note",
    "restore_tag",
    "update_note",
]
