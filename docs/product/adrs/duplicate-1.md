# ADR duplicate-1

**ADR duplicate-1 · a duplicate is a create, filled before its one save, and
its key constraint is the model's own.** *Accepted 2026-09-28 (P24 — the
worked example's step-zero finding, ruled 16:59 and landed under a narrow core
sanction; R-SEAMS-W5 for the constraint).* *Context*: the seam's first consumer
could not use it — `duplicate_row` built the copy, set `copies` and saved once
before the service could set anything, so a `resets` field that is NOT NULL
(the owner) and a unique constraint over copied fields (the name per owner)
were each a 500, and the planted stencil the seam was measured against carried
neither; then a `Duplicable` noun declaring `Meta.constraints` could not
migrate from scratch, because the key field's render made `CreateModel` create
the constraint and the autodetector's `AddConstraint` failed on it — the worked
example migrated only because its table already existed. *Decision*:
`Duplicable` (`duplicated_from`, a self-FK that nulls when the source goes —
lineage is a courtesy, not a claim — and `duplicate_key`) with
`Duplicate(copies=…, resets=…)` closed over every concrete editable field
(rule 74's duplicate clause); `duplicate_row(..., fill=)` takes a value for
every key named in `resets`, refuses `TypeError` for one missing, and sets them
on the copy before its one save; the copy's `full_clean()` runs under
`as_invalid()` before the save, so a clash is `invalid` naming the field and
never a 500; a duplicate IS a create — `<kind>.create` at the acting hat (ADR
core-20's placement) plus `<kind>.read` on the source — so it lands at the
presser's hat, owned by the presser, named as a copy, with the source's
ledger left behind and its tags carried by the noun's own service calling the
tags app's service inside its transaction; and **the key constraint is the
model's own**, declared in its `Meta`, checked by the field rather than
conjured by its render, and a duplicable noun that forgets the declaration
fails `core.E001` before it can migrate. *Rejected*: a core hook for copying
attachments (one consumer, principle 11); a `duplicate_blocked` code (a copy's
refusals are `forbidden` and `invalid`); copying append-only children (a ledger
is the source's history, not the copy's) or notes and files; a plant without
the example's shape (the criteria finding — a seam is measured against the
shape its first consumer has). trigger to revisit: a product noun whose copy
must carry an attachment kind other than tags.
