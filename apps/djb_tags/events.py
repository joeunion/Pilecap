"""The names of the things this app says happened.

Names only. `services.py` publishes them with `emit(name=..., ...)` inside the
write's own transaction; the grammar is `<app>.<noun>.<past-tense verb>` (house
rule 16), and `apps/events` refuses a name it does not find here. Both nouns are
authorization kinds already (`tag`, `tag_link`), so no `EVENT_KINDS` line is
owed: a `tag` event is tenant-wide like the word itself, and a `tag_link`
event carries its branch on the payload (`organization_id`, rule 59), so the
socket fan-out reaches only the branch the subject lives in.
"""

from __future__ import annotations

#: A word was coined. Payload: `schemas.TagOut`.
TAG_CREATED = "djb_tags.tag.created"

#: A word was respelled. Payload: `schemas.TagOut`, with the new name and slug.
TAG_RENAMED = "djb_tags.tag.renamed"

#: A word left the vocabulary. Payload: `schemas.TagOut`, `archived_at` set.
#: Its links stay on their subjects; a subscriber may not conclude they went.
TAG_ARCHIVED = "djb_tags.tag.archived"

#: A word came back. Payload: `schemas.TagOut`, `archived_at` cleared.
TAG_RESTORED = "djb_tags.tag.restored"

#: A subject now carries a tag. Payload: `schemas.TagLinkOut`. A repeated
#: request for a link that already exists says nothing — nothing happened.
TAG_LINK_CREATED = "djb_tags.tag_link.created"

#: A subject no longer carries a tag. Payload: `schemas.TagLinkOut` of the row
#: that went, id included, so a subscriber can match it.
TAG_LINK_DELETED = "djb_tags.tag_link.deleted"

#: A link followed a merged subject to its survivor. Payload:
#: `schemas.TagLinkOut` as the link now reads — the survivor's pointer and
#: branch. A loser's link the survivor already carried is deleted instead, and
#: says `djb_tags.tag_link.deleted`.
TAG_LINK_MOVED = "djb_tags.tag_link.moved"

#: The event grammar's nouns are the short words; the models' authorization
#: kinds carry the template's `djb_` prefix (so a product's own `Tag` or
#: `TagLink` keeps the kind its class name derives). This maps the one to the
#: other, so a socket can still ask who may hear each event.
EVENT_KINDS: dict[str, str | None] = {
    "tag": "djb_tag",
    "tag_link": "djb_tag_link",
}
