# ADR api-1

**ADR api-1 · the OpenAPI document is the contract, complete.**
*Context*: the owner read staging's Swagger and ruled the API documentation
standard a prerequisite before any product code lands. A census — measured
before enforced — found 51 of 51 summaries were
prettified function names, 11 routes carried no description at all, not one
route documented a header or a refusal, not one of 57 schemas carried an
example, there was no `tags` section and no overview — and all 36 MCP twins
described their capability in words of their own. Five cycles of code review had
read every one of those routes. *Decision*: every route carries a summary and a
description **derived from the same docstring its MCP twin renders**, so the
doors cannot drift; every tag carries a description declared by the app that owns
it; `X-Tenant`, `X-Org`, `Idempotency-Key` and `Idempotent-Replayed` are
documented once as parameters, with the hierarchy explained; every route's error
responses **enumerate the refusal codes it can raise, with the registry's own
fact and remedy text** (`introspect`'s refusals section is the source); every
schema carries an example; an overview — auth flow, token minting, the MCP
door's address, versioning — opens the document; and the TS client regenerates
clean. It is applied **once and derived**, in `apps/core/api/docs.py` and
`config/api.py`, so a route born in any app carries the whole standard with it.
House rule 41 is the census that keeps it true, ceiling zero, pinned at birth.
*Rejected*: summaries-only (an earlier quick fix the owner superseded);
per-door doc strings (the drift rule 17 exists to refuse, one surface over);
hand-written `summary=`/`description=`/example arguments per route (51 places for
the annotation and the behaviour to part company); doc coverage as review-only
(51 routes and five cycles of review missed it — a census is what holds).
trigger to revisit: a client generator the TS one cannot serve.

*Amended* — **the bar for what goes above the divider**. The
contract half speaks **to the caller, about the wire, in plain language**: what
the operation does, what to send, what comes back, what each refusal means and
what to do about it, written for a developer who has never seen this codebase.
The test is one sentence: **if a stranger with an API key cannot act on it, it
goes below the divider.** Never above it: internal function names, queue-row
numbers, fix history, module comparisons, or house idiom ("the house list
shape", "doors", "the machine door"). Four of those symptoms are *shapes* and
are therefore gated — `N\d+`, an underscore-prefixed identifier, `@service`,
`manage.py` — and the rest is review's, declared as such in rule 41's
`does_not_cover`. The same bar reaches **runtime refusal prose**: `authz.require`
answers with the app's declared `ACTION_PROSE` sentence, never with the internal
action name.

*Amended* — **the contract reads like Stripe's**. The
mechanism was right and the output was not: because `summary` was the
docstring's opening sentence, the rendered navigation was a column of sentences,
some carrying literal `**`. Four elements, all derived, nothing hand-annotated:
**(1) a title is not a sentence.** The docstring's first line is a nav-safe
title — a short noun or verb phrase, no Markdown, no full stop, at most **60
characters** (`docs.TITLE_MAX_LENGTH`, `rules.yaml`'s `title_max_length`, and
this paragraph, which agree by review). It becomes `summary`; the paragraph
below it becomes `description`, and the title is not repeated there. The MCP
twin renders the whole contract half, title line included, so the doors still
cannot drift. **(2) Real examples.** A field declares its own realistic value
with `core.schemas.example(...)`, which the synthesiser prefers over the
shape-grade value it would otherwise derive; the persona arc's schemas were
declared and the rest is a **ratchet** rather than a retroactive fail, so a new
field must declare and an old one may be improved at leisure. **(3) Guides and
reference are separate layers.** The overview is a short shelf of `##` guides —
quickstart, authentication, tenants and organizations, pages and filters,
idempotency, errors, events, versioning — each a concept read once and linked by
anchor, above a reference that stays per-operation. `/llms.txt` demotes those
headings by one when it embeds them. **(4) Tags are named for humans.** `TAGS`
maps a wire name to `Tag(display, description)`; `display` reaches the document
as `x-displayName` and no URL, label or client namespace moves.
**(5) One operation, one section.** An operation carries **exactly one tag**,
and a tag with no operations is deleted rather than left as an empty heading. A
renderer lists an operation under every tag it carries, and ninja *accumulates*
a nested router's tags onto everything beneath it — so `accounts`' mount tag
over three tagged child routers printed all eleven of that app's operations
twice, once in their real section and once under an umbrella that was a copy of
the other three. Gated; the orphan-tag half is a test, and rule 41 says which is
which.
*Also rejected here*: a hand-written `summary=` per route to get titles (the
same second copy this ADR rejected at birth); a title derived by prettifying the
function name (the earlier, replaced approach); examples as a fixtures file beside
the schemas (a second copy of the shape, which is what `add_examples` exists to
avoid); renaming tags to make them readable (it would move every route's
namespace in every generated client to change a label); keeping an umbrella tag
and asking renderers not to duplicate (a document that needs a renderer's
cooperation to be readable is a document with a second contract).

*What the sweep to this bar is, in one line, because a product will do it
again*: **write the caller's sentence, then check it against the service — and
where the service is ambiguous, drive the wire.** Applied across 86 operations
it found six defects in prose five cycles of review had read, and two of them
this time were provable only by calling the endpoint: a duplicate slug
documented as `409 conflict` that is a `400 invalid`, and a last-owner
protection documented into existence that does not exist. Every operation now
closes with the same block — the refusal codes with their status and what the
caller does about each — because a caller who has read one operation should not
have to learn a second grammar to read the next.
