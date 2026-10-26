# ADR connections-2

**ADR connections-2 · the inbound door gets the freshness half, and
it is the scheme we already send.** *Context*: the one
signature-verified inbound receiver (`apps/connections/api.py`) checked an HMAC
over the body bytes and nothing else, so a delivery captured off the wire
verified for as long as the connection's secret lived; `scripts/mail_demo.py`
leg 6 reported the replay question `n/a` because there was nothing in the scheme
to answer it with. An earlier ruling had already closed exactly this on the way *out*
(`X-Signature-V2`, a signed timestamp and a window), which left this door as the
half of the round trip with no clock. *Decision*: the door verifies **the same
exact envelope the outbound signer uses** — `X-Signature-V2: t=<unix seconds>,sha256=<hex HMAC-SHA256
over "<t>.<body>">`, keyed on `connection.webhook_secret` — and **does not
re-implement it**: the tolerance (`SIGNATURE_V2_TOLERANCE`), the element grammar
(`parse_signature_v2`) and the comparison (`signature_v2_matches`) are
`apps.events.receivers`', so one implementation decides for a product that
points this template's webhooks at this template's receiver. **Expand without
downgrade**: a sender that only knows `X-Signature` is untouched, but when
`X-Signature-V2` is present it is the *only* header consulted — a correct
`X-Signature` beside a stale or forged `X-Signature-V2` is refused, because a
scheme a sender can be stepped down from buys nothing (the replayer would simply
drop the header carrying the window). The wire refusal is **unchanged** —
`401 "Invalid signature."`, with digest, staleness, secret and existence all
withheld — and the route's docstring is where an honest sender learns the
grammar, which scheme wins, and the window in minutes (pinned to the constant by
a test). The empty-secret fail-closed clause covers the new scheme, stated in
this door rather than borrowed from over the border. *How the constant is
reached*: a **runtime lookup through the bridge** —
`core.bridge.get(bridge.SIGNATURE_V2_TOLERANCE)()`, the name `apps/events/apps.py`
registers at `ready()` — never an import. `import-linter` holds the
platform apps independent of one another, `apps/connections/apps.py` promises
this app keeps working in a tree where `apps/events` never landed, and
`test_nothing_in_this_app_imports_apps_events` enforces both by AST — so the
dispatch brief's "import the constant" is not available, and copying it was the
one thing the brief ruled out. The header *name* is the single literal (a door
cannot ask "is this header present" without one) and a test pins it to the
signer's own constant. *Rejected*: **a per-connection tolerance flag** (a knob
nobody has needed is a knob somebody sets to a year the first time they see a
stale-delivery log line; the promotion trigger is already recorded on the
constant); **a local tolerance constant in `connections`** (two five-minute
numbers agree the day the second is typed and disagree six months later inside
somebody's verifier — the drift this design exists to prevent); **a nonce or
delivery-id cache as the replay control** (it makes replay a storage problem
with a retention window and an eviction policy, refuses nothing older than the
cache, and the `(connection, delivery_id)` dedup we already have is a
*provider's* claim about identity, not a proof of freshness); **fixing it in
`apps/comms`' provider-verifier registry** (that seam is for schemes a *vendor*
decided — an ESP signs the way its vendor signs — and this scheme is ours, so
putting it there would make the house scheme optional and per-provider);
**a static import of `apps.events.receivers`** (above). trigger to revisit:
the contraction of `X-Signature` on this door — dated **2027-02-24** in a comment
beside the v1 branch, or earlier at the first of (a) every provider a product
here receives from sending `X-Signature-V2`, and (b) `scripts/mail_demo.py`
moving off v1, which this ADR deliberately does not touch (follow-on: the
demo's leg 6 gains the replay assertion when it signs v2). *Numbering*:
`connections-2` is the next free number — `connections-1` is cited in
`apps/connections/services.py`, `apps/events/receivers.py` and the connections
tests but was never written into this file, and that gap is left as a hand-up
rather than renumbered here. *(Hand-up closed by the bookkeeping
entry, `connections-1.md`: the number is reserved and its ruling is cited to the docstrings
that hold it. Nothing renumbered.)*
