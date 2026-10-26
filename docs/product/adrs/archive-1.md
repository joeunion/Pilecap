# ADR archive-1

**ADR archive-1 · a noun leaves the book one way, and the consumer's build is
adopted where it can be.** *Accepted 2026-09-27 (P24 B-CORE-1).* *Context*:
the consumer's `Archivable` — fields `archived_at`/`archived_by`, the manager
hiding archived rows in `for_tenant()` with `.including_archived()` and
`.archived_only()` as the only widenings, `ArchivedOut`, blockers by discovery,
`@refuses_system` predicates and their rule — was built, driven and folded on
a real product; the comms and files apps here carried two hand-built halves
of the same idea that disagreed (no restore, no event, a `?archived=` bool).
*Decision*: the consumer's mechanism, names kept, lifted into `core` as the
family's first member: archived rows are hidden by the manager and never
purged; `archive`/`restore` are a service pair that emits inside the
transaction and refuses with `archive_blocked`/`restore_blocked`/`archived`
(409, each naming its remedy); a system actor is refused by the predicate
(`may_archive` asks `organization.update` at the node — rule 54 (c)'s form,
the consumer's `may_administer` semantics — because the default roles offer
every predicate-bearing key back, so asking `<kind>.archive` narrows nothing);
`Archivable` and `append_only` are disjoint (rule 75); the two hand-built
halves become the mixin in the same cycle (COMMS-A, FILES-A). *Consequences*:
`?archived=` becomes `?show=` (a 400 naming `show` — a loud break the merge
note carries at a MINOR, the owner's ruling); `for_tenant`'s hide is invisible
to raw SQL and `_base_manager` reads (declared); a custom role holding
`organization.update` can archive (declared cost). trigger to revisit: a
product that needs a purge (a data-safety act the family does not carry) or an
archive that must not hide by default.
