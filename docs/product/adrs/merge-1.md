# ADR merge-1

**ADR merge-1 · the repointer contract, and the loser as a tombstone.**
*Accepted 2026-09-28 (P24 LEAD-W3 R15 over the owner's tombstone ruling of
2026-09-27; B-CORE-3's conformance test measures it over every attach owner;
R-SEAMS-W5 closed the two seams its first consumer found).* *Context*: three
attach owners implemented `Repointer` in one wave with three readings of its
count — one counted three, moved two and collapsed one — and the seam's first
mergeable consumer found a repointer that refused a noun without attachments,
and a survivor whose delete surfaced the database's protect as `conflict`.
*Decision*: **one contract, asserted once across every declared repointer**
(`apps/core/tests/test_repointer_conformance.py`): `count(*, tenant, loser)`
answers the rows that will LEAVE the loser — moved or collapsed — and
`repoint(*, tenant, actor, loser, survivor)` the rows that left; the safety
re-resolves both rows for the actor (`may_be_named`, `resolve_subject`), so
an unreachable loser or survivor is `NotFound` with nothing moved; one
`<app>.<noun>.moved` per moved row and the owner's own leaving event for a
collapse (a duplicate link folds onto the survivor's and emits its `deleted`);
`updated_at` stamped on every re-pointed row (rule 76's form now, so a later
`Versioned` adoption changes nothing); a repointer for a kind the noun does
not take is a no-op counted zero on every owner, so a mergeable noun without
attachments merges. **The loser survives as a tombstone**: `Mergeable` requires
`Archivable` and carries `merged_into` (a self-FK, `PROTECT`) — the merging
person archives the loser, its reads answer 200 read-only with `merged_into`,
its writes refuse `merged` (409) naming the survivor's door, a chain is
compressed in the merge transaction so a loser is never two hops from its
survivor, the survivor's aggregate reads that must include kept children widen
with `Mergeable.lineage(survivor)`, and every foreign key into the noun is
either re-pointed by its owning app's `merge_repointers.py` or declared kept on
the loser in `merge_keeps` with its reason (an append-only ledger stays where
it was written — rule 20) — rule 74's merge clause is that closed question over
`_meta.related_objects`. Deleting a survivor that still carries merged losers
refuses `merge_survivor` (409, both doors byte for byte, naming the noun's
archive), where the protect surfaced as the wrong word. The dry run
(`<noun>_merge-detail`, `?into=`) answers the sentence, the repoints by title
and count, and the blockers, and writes nothing; the apply takes both versions
where the noun is `Versioned`; locks are taken in pk order. **One `.moved`
outbox row per moved attachment is kept** (the owner's question, answered
KEEP): one event per merge carrying counts would leave an attachment's own
webhook subscribers deaf to the repoint. *Rejected*: `count` answering
`(moved, collapsed)` exactly (the honest split, but a signature change on a
seam three merged apps already implement — trigger to revisit: a receipt needs the
split); count equals moved (unknowable without the survivor); a separate
redirect table (a second owner of a fact the loser row already carries,
principle 9); a 3xx on the loser's detail (a client follows it silently and
then writes to a row it did not name, and the MCP door has no redirect); an
unmerge road (the merge is admin-only and confirmed on the face precisely
because it is not undone, principle 6); a cross-noun merge. *Trigger to
revisit*: a merge measured past the request budget, which becomes an
import-shaped run; a receipt that needs moved and collapsed told apart.
