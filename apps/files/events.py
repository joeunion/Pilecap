"""The names of the things this app says happened. **Two, and both are true now.**

Names only. `services.py` publishes them with `emit(name=FILE_STORED, ...)` inside
the write's own transaction, and the grammar is `<app>.<noun>.<past-tense verb>`
(house rule 16). `apps/events/events.py` discovers this module and `emit` refuses
a name it does not find here.

`files.file.archived` arrives in the rung that ships `archive_file` — the door
rung, because a route that archives needs a service that archives — rather than
being declared ahead of its emitter. A declared name with no emitter is a
published contract nobody publishes, which reads as a subscriber's missing feature
rather than as an unbuilt one. The app map's row
(`docs/product/architecture.md`) says the app emits exactly two; this file now
holds exactly two.

**What a subscriber may conclude from `files.file.stored`, and what it may not.**
It may conclude that one version of one document is now readable: the object is in
the bucket, this platform has streamed it, and the digest and size on the payload
are what WE measured rather than what an uploader declared. It may NOT conclude
that the version it names is the current one — a version finalizing out of order
does not promote (`record_stored` advances `current_version` only upward), so the
payload carries both and a subscriber that cares reads `current_version`.

**What a subscriber may conclude from `files.file.archived`, and what it may
not.** It may conclude that the document has left everybody's working set: it is
gone from every list, and nothing new can be filed into it. It may NOT conclude
that anything was deleted — archive is soft, every version stays readable by
id and presignable by the audited door, and **the objects stay in the bucket**
until purge lands. `StoredFile.lifecycle` carries that residual out loud, and this
sentence is the wire-facing half of it.

*Rejected, and kept rejected:* `files.file.download_issued`. An issuance is
already a witnessed fact — the `AuditEntry` `issue_download_url` writes — and an
event exists for subscribers, of which there are none. Trigger: the first one.
*Rejected, kept:* `files.version.superseded`. Promotion rides `stored`'s own
payload; a second name for the same commit would let the two disagree.
"""

from __future__ import annotations

#: One version's bytes are in the store, measured and recorded. Payload:
#: `schemas.FileStoredOut` — the document as every read door reports it, plus
#: the version that just landed with its digest and its size. Emitted inside
#: `record_stored`'s transaction, so a finalize that rolled back said nothing.
FILE_STORED = "files.file.stored"

#: A document has been taken out of the working set. Payload:
#: `schemas.StoredFileOut` — the document as every read door reports it, with
#: `archived_at` now set, so a subscriber can see WHEN as well as THAT. Emitted
#: inside `archive_file`'s transaction, so an archive that rolled back said
#: nothing.
FILE_ARCHIVED = "files.file.archived"


#: Which authorization kind each noun above is about, for the socket door's read
#: check (`apps.realtime.bridge.kind_of_event`, ADR core-27).
EVENT_KINDS: dict[str, str | None] = {
    # `file` is the grammar's short word for the `StoredFile` row both events are
    # about, and `stored_file` is that model's derived kind. P7.6 gives the model
    # `authz_kind = "file"`, at which point the noun is a kind and this line is
    # deleted rather than edited.
    "file": "stored_file",
}
