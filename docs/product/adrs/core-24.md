# ADR core-24

**ADR core-24 · one predicate answers "does this route answer the cursor
envelope", and every instrument reads it.** *Context*: three
instruments answered "is this route paginated?" for themselves off two
different private ninja attributes — rule 3's census, the docs derivation and
`introspect` — and all three were wrong about the same three direct-cursor
routes, because every marker they read says "`@paginate` was applied", not
what a caller experiences. The failure that matters is not the wrong column:
it is that fixing one leaves two blind — three private re-derivations of one
fact drift apart silently and nothing fails when they do. *Decision*: one
predicate in `apps/core/api/pagination.py`, beside the envelope it is about,
reads the RESPONSE MODEL; the census, the docs derivation and `introspect`
all read it — sever it and all three go red at once
(`apps/core/tests/test_pagination_seam.py` plants and proves this).
*Rejected*: fixing `introspect` alone (leaves rule 3 and the docs blind — the
carried criterion's exact ban); declaring the blind spot in three places
(three declarations of one fact drift). trigger to revisit: a fourth reader
appears.
