# ADR core-27

**ADR core-27 · a read is a permission.** *Accepted 2026-09-15 (P20, Phase R).*
*Context*: through v2.0 a `<kind>.read` key was free to any membership in the
tenant — `allows` step 3 short-circuited it and `visible_to` was the whole read
gate. That answered "which rows" and never "whether this kind at all", so a
role could say nothing about what a person may see, a custom role could not be
narrowed to a subject area, and a `withhold` had no effect on a read.
*Decision*: a `<kind>.read` resolves through the same three layers as every
other key — `owner` holds it (the vocabulary), `admin` holds it (`*`), `member`
holds it (`*.read`), a custom role holds what its collection names, an `allow`
grant adds it and a `withhold` subtracts it. **The check lives in the selector,
once** (§C6), and every door pays it: a `list_` asks at the acting hat
(`obj=None` → `where_of`) before it builds the queryset; a `get_` asks after
the scoped fetch with `obj=row`. **`visible_to`/`for_tenant` still decide WHICH
rows and `require` decides WHETHER this kind, here** (rule 24, BVB-4) — a
selector never filters rows by permission. A `system` actor passes at step 1.
*The grammar* (§C8): outside your subtree → `not_found` (the scoped fetch,
unchanged) · inside it without the key → `forbidden` with
`refusal_sentence("<kind>.read")` · a list without the key → `forbidden`,
because a list has no row to hide. Reach before capability. *Consequences*: a
membership with **no role reads nothing**; a **custom role reads nothing until
its collection names reads**, so the role services accept `"*.read"` as a
pattern and expand it at write time; **the socket narrows per HAT, not per
org** — a connection's read set is the read half of `effective_permissions` at
the acting hat, computed once at connect and checked per frame (a per-org set
would disagree with the REST list, which rule 46 forbids); a write that shrinks
somebody's read set at any node they hold a membership on closes their sockets
on commit (`core.permissions.narrowed`), a widening kicks nobody; the token
echo drops the read half when no read is held; `READ_VERBS` and `is_read()`
remain as deprecated shims read by nothing until v3.0; **a tenant-wide kind — one
whose model names no organization — is READ at the acting hat and WRITTEN at the
root** (PR5.5, 2026-09-17), which is the v2.1 stopgap and is declared as one: it
makes this door agree with the socket, the search and the admin today, every such
site wears a dated `hat-scoped` valve that house rule 55 counts, and universal
homing replaces it in v2.2 by giving those kinds a home (the universal-homing
proposal, 2026-09-17 — every record homed at a node). *A flat product observes
nothing* — the 288-cell census in `apps/core/tests/flat_product_baseline.json`
is the proof, and 0 write cells moved when it was re-derived. *Trigger to
revisit*: the first product that wants per-FAMILY read precision in the token
echo, or the first family-shaped withhold.
