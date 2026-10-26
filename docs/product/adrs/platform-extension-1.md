# ADR platform-extension-1

**ADR platform-extension-1 · a product extends the system layer by DECLARING
beside it, never by editing it.** *SIGNED by the owner 2026-09-22 (proposed 2026-09-21 — the owner chose this
shape; the signature lands at CLOSE.)* *Context*: the first
consumer's fold of v2.1.0 cost 94 merge conflicts, 21 of them inside
`scripts/ quality/ .github/`, and twelve commits whose entire content was
re-applying local edits to template-owned files; the worst was silent in the
wrong direction — an 1800-line template file fast-forwarded byte-identical and
took 1826 product lines with it, with no conflict to read. Every one of those
edits was a product-owned CONCERN with no seam to land in. *Decision*: every
extensible template directory has a `local/` sibling the template's own reader
discovers and the template NEVER ships (`publish.sh` § R0, which refuses a
tracked `**/local/**` or `*.local.md` at exit 2) —
`scripts/local/{legs,drives,fold.d,lifecycle.d,hooks}/`, `quality/local/`, and
a `.local.md` sibling beside a template document that carries a per-product
list. A declaration carries a versioned header; ABSENT is byte-identical
behaviour and MALFORMED is exit 2, never a quiet skip. The per-path ownership
classes land in `docs/product/build-contract.md` § Ownership, and an edit to a
template-owned path is a divergence `scripts/divergence_census.sh` refuses
unless the product's own `architecture.md` names it. *Rejected*: a
`pyproject.toml` registry of legs (a shared file no rung may edit, and the
declaration would live away from the thing it declares) · fork-and-rebase
doctrine (it re-pays the conflicts every release, grows with the product's age,
and git's worst case here was the SILENT one) · a `ci.local.yml` (not a GitHub
primitive; a second workflow file is already conflict-free) · a sourced
`check.local.sh` that may redefine functions (a judge, not an instrument —
check-v1's law) · a `template_sync.sh` now (its trigger, three products, has
not fired). trigger to revisit: a second product's fold shows a seam these
six miss, or three products exist.
*AS BUILT 2026-09-21*: house rule 60 carries the decision in three
canary classes, and the fenced `drawers` block in
`docs/product/build-contract.md` is its ONE reader. **(a)** a product edit in a
template-owned path → `scripts/divergence_census.sh`'s exit-1 finding, by path.
**(b)** the table against the tree: a drawer the template's own code opens with
no row, a row whose reader is not here, a row whose case its drive does not
define — each a finding at every gate, the population of drawers DERIVED from
the `local/` paths the code spells rather than typed beside the table. **(c)**
at `--selftest`, one planted item per drawer, run through the drive case the
row names (`--case`, the seam every drive under `scripts/tests/` now carries),
so a reader that opens its drawer and ignores what is in it is exit 2 naming
the drawer and the reader. A `held` row reserves a name for a rung that has not
landed and is printed as held; it becomes a finding the day a template-owned
file opens it.
