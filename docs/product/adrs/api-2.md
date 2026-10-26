# ADR api-2

**ADR api-2 · resource-first URLs — the first path segment names a
resource, never an app.** *Context*: the owner's ruling (design-agreements.md) —
an app label in a path is **internal taxonomy on the
wire**, the URL twin of the sidebar-tag finding, and it asks every caller to
learn which module of ours happens to serve a thing in order to type it and then
ignore it. A census — measured before enforced —
found 43 of 66 mounted paths under an app label that was not a resource, and 5
paths with no trailing slash. *Decision*: **`PREFIX = ""` for the four platform
groups** (`core`, `comms`, `events`, `workflows`) — each of their routers already
carried its resource as the first segment inside itself, so the flatten is four
lines and not fifty; **three renames, resolving by better names rather than by
prefixes** — `policies` → **`delivery-policies`** (`policies` alone says nothing
on a wire that also has authorization policies), `endpoints` →
**`webhook-endpoints`** (likewise beside OAuth endpoints), `catalogue` →
**`event-types`** (a catalogue is a document, this is a collection, and
`event_type` is the noun its own `url_name` stem already used); **the five
slashless routes gain the slash** (`auth/realm` and the four user actions) —
one convention, no exceptions; **`me/` stays** and action verbs stay POST
subresources. **`url_name`s do not move, anywhere**: they are internal joins —
rule 17 derives the expected MCP tool names from them, rule 3's route-test
clause greps them, and the frozen nets pin them — so **tool names do not change
when paths do** and door parity survives by construction. Enforced by **house
rule 32**, whose two populations are both closed (app labels off the app
registry, paths off the live mount) with **one valve**,
`scope.allowed_label_paths`: a label with its reason, seeded with
`connections`, because A1 names an app as the plural of its aggregate and a
domain app's label legitimately **coincides** with its best resource name. The
valve declares the coincidence instead of refusing it, and the refusal keeps
catching the leak class — `core`, `comms`, `events` and `workflows` are
infrastructure names and never resources. *Rejected*: dual-registration
transition windows (two operations per route in the contract, parity noise —
pre-T0 there is no client to transition); keeping the prefixes with redirect
aliases (the leak persists in the document, and a redirect is dual-serving with
extra steps); renaming the MCP tools to match (nothing derives a tool name from
a path and no consumer exists — recorded residual, trigger to revisit: the first external
MCP consumer confused by the noun mismatch). This is a **breaking URL change on
v1**, which E5 normally forbids; the license is the empty consumer register and
the ruling's own sentence — *after the first external consumer this is a
versioning event*. trigger to revisit: that first external consumer.
