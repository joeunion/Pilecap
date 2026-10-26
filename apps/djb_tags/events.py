"""The names of the things this app says happened (`<app>.<noun>.<past-tense verb>`, rule 16).

A `tag_link` event carries its branch on the payload (`organization_id`, rule 59).
"""

from __future__ import annotations

#: A word was coined. Payload: `schemas.DjbTagOut`.
TAG_CREATED = "djb_tags.tag.created"

#: A word was respelled. Payload: `schemas.DjbTagOut`, with the new name and slug.
TAG_RENAMED = "djb_tags.tag.renamed"

#: A word left the vocabulary. Payload: `schemas.DjbTagOut`, `archived_at` set.
#: Its links stay on their subjects; a subscriber may not conclude they went.
TAG_ARCHIVED = "djb_tags.tag.archived"

#: A word came back. Payload: `schemas.DjbTagOut`, `archived_at` cleared.
TAG_RESTORED = "djb_tags.tag.restored"

#: A subject now carries a tag. Payload: `schemas.DjbTagLinkOut`. A repeated
#: request for a link that already exists says nothing — nothing happened.
TAG_LINK_CREATED = "djb_tags.tag_link.created"

#: A subject no longer carries a tag. Payload: `schemas.DjbTagLinkOut` of the row
#: that went, id included, so a subscriber can match it.
TAG_LINK_DELETED = "djb_tags.tag_link.deleted"

#: A link followed a merged subject to its survivor. Payload:
#: `schemas.DjbTagLinkOut` as the link now reads — the survivor's pointer and
#: branch. A loser's link the survivor already carried is deleted instead, and
#: says `djb_tags.tag_link.deleted`.
TAG_LINK_MOVED = "djb_tags.tag_link.moved"

#: The nouns are the short words and the kinds carry the `djb_` prefix, so neither noun is a kind:
#: `core.authz.kind_of_event` reads these two lines.
EVENT_KINDS: dict[str, str | None] = {
    "tag": "djb_tag",
    "tag_link": "djb_tag_link",
}
