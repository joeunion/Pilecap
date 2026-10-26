# ADR core-21

**ADR core-21 · the addressing-header law: a header that was SENT
and cannot be honoured refuses; an OMITTED header falls back.** *Context*: the lead's ruling. `X-Tenant` and `X-Org` are **addressing** headers —
they say WHERE a caller is acting, where `Authorization` says WHO — and the
platform said three different things about one unhonourable value. The document
promised every authenticated route that "a tenant you hold no membership in
reads as empty rather than as forbidden"; the token-mint route promised a pinned
token "can only ever act in that tenant, whatever `X-Tenant` a later request
sends"; and the wire answered **401 `unauthenticated`** — "we could not tell who
is making this request" — over a live, unrevoked token belonging to a real
active user, `200 []` for an unpinned one, and the ROOT bill
for an `X-Org` that was sent empty (curl's `X-Org;` form). Three answers to
one question, and the 401's fact was simply false, which E9's grammar refuses.
*Decision*: **the pin promise's substance wins, generalized as the direction
already ruled for `X-Org` and driven green across six hat shapes.** A
SENT addressing header that cannot be honoured for this credential is refused —
authenticated, **then** refused, with the registered code
`addressing_header_not_honoured` at 403. An OMITTED header still falls back to
the default membership, untouched, so a well-behaved client sees no change.
**Sent means sent, empty included**: `""` and whitespace are values a caller put
on the request, not an absence, and the trim-and-lower boundary is declared in
the header's own published description. **Foreign, nonexistent and unreachable
are one byte-identical answer** — the refusal fires because the slug is not one
this credential can act in, never because of what exists, and it names the
header and never the slug, so it is no oracle over the estate. Not-there ≡
not-yours governs resource identifiers; a caller's own addressing header is the
caller's assertion, and refusing it leaks nothing they did not assert. *Where it
lives*: `core.middleware.addressing_refusal` — one function, asked by every
door, after resolution and before anything is read. `resolve_tenant` and
`resolve_org` stay resolution and answer `None`; `authenticate_token` answers WHO
and returns a pinned token's own tenant whatever was asked for, because a door
cannot say "authenticated, then refused" about a credential that failed. The
REST seam is the `_run_checks` wrap that already holds the token ceiling, the
MCP seam is `TokenAuthMiddleware`, and **both compose the same body through
`wire_refusal`**, so the two doors cannot come to disagree. The socket doors
refuse by closing the handshake (`CLOSE_NO_TENANT`), because a websocket
handshake has no body to carry a refusal in. **Zero per-app door edits**: the
population is every authenticated operation, derived, and the published
`x-refusal-codes` follows the same `authenticated` fact the two header
parameters do. *Rejected*: **empty-read** (the other direction — it would reopen
what was already closed and keep the misconfiguration-masking class this platform refuses); **the quiet pin** (a pinned token silently answered as its pin, which is
"somebody else's data under a different name" with extra steps); **two codes,
one per header** (the failure is one failure and a client would write the
handler twice; which header is in `detail`, the half that varies per request);
**echoing the sent slug in the body** (harmless in itself, since it is the
caller's own assertion, but it would make the foreign and the nonexistent
refusal two different bodies and lose the anti-oracle pin); **a per-app guard**
(what `apps/usage` had, and it stripped before it checked — exactly the
defect one app's copy of a platform law produces). trigger to revisit: a door
that must accept an addressing header it cannot honour (none is known); or a
product whose clients genuinely cannot stop sending a stale header, which is a
migration conversation and not a change to the law.
