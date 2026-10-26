# ADR attach-1

**ADR attach-1 · the landing law: an attachment lands at its subject's
organization, and a tenant-wide subject lands it at the acting hat.**
*Accepted 2026-09-28 (P24 LEAD-W3 R6, over the owner's polymorphic ruling of
2026-09-27; the tags app moved to it; B-CORE-3's attach conformance measures
every owner).* *Context*: attachments are polymorphic `(subject_kind,
subject_id)` across three platform owners — notes, tags and the files app's
stored file — resolved and authorized at every write; the first two owners
disagreed on where a row lands for a tenant-wide subject: notes at the
subject's node, tags at the tenant root, which only root hats can read.
*Decision*: an attachment lands at its subject's organization; for a
tenant-wide subject (a `TenantScopedModel`, such as a tag) it lands at the
acting hat — down-only visibility decides it, because a branch author must be
able to read back what they wrote, and rule 55's root-only writes govern the
tenant-wide ROW, never the org-scoped link. The subject is resolved by
`core.verbs.resolve_subject` (the kind registry, `for_tenant(t).including_archived()`,
`visible_to`, `may_be_named`), and attachments are read only through their
subject (`?subject=<kind>:<id>`, which resolves the subject first), so a
dangling pointer is unreachable, never wrong. **The noun declares
`attachments = ("notes", "files", "tags")` inside its golden fence**, so a
product copies the declaration with the noun and the adopters' test plants —
additive, never replacing — become no-ops the day it lands; a kind the subject
does not declare is refused naming `subject`; a noun that lists tags answers
`tags` on its detail (rule 74's attach clause; the detail door only, to spare
a per-row query on lists). **Each owner ships `tests/attach_specimen.py::attach`**,
the hook core's conformance test imports, so the law is measured once across
every owner rather than asserted per app. *Rejected*: root landing (the reason
above); real foreign keys per noun (half a session per noun, and a link table
cannot mean "anything"); a conformance test per owner (three readings of one
law). *Declared and booked*: the tenant-wide one-per-pair constraint against
per-hat landing (a second branch pressing a word already on a tenant-wide
subject answers `conflict` with no row and no event), and a merge re-landing
links at the merging actor's hat. trigger to revisit: universal homing —
when the tenant-wide class dissolves, the second clause goes with it.
