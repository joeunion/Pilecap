# ADR verbs-2

**ADR verbs-2 · an event payload never carries a per-viewer field.** *Accepted
2026-09-28 (P24 LEAD-W3 R1; built by B-CORE-3 under the owner's principle-20
sanction, recorded in its commit).* *Context*: `allowed_acts` is a property of
(row, viewer) — the vocabulary answers it per hat, and an event has no viewer.
The family's first adopter put it on the `Out` and so into the outbox, and its
verifier read the archiver's `["restore"]` in `archived` and the owner's five
acts in `created`, broadcast to every member: a permission fact about one
person published to the tenant, wrong for every other reader. The second
adopter left it off for byte-equality with the outbox — a door disagreement,
which is a finding. *Decision*: `allowed_acts` lives on the two viewer doors
(REST and MCP, which rule 17 keeps equal) through `ActsOut`, the page-level
`ActsPage` and `with_allowed_acts`; `Event.payload` is the `Out` minus
`core.schemas.PER_VIEWER_FIELDS` (derived from `ActsOut`, never typed), built
by `event_payload()`, which strips at any depth; and
`apps/events/services.py::emit` refuses a payload carrying a per-viewer key at
any depth, naming the path. **The refusal on the spine is the owner's
principle-20 exception**: the spine is the one chokepoint through which every
adopter's payload passes, a source rule cannot see into a dict a service
dumped, and the alternative was per-engineer memory in every adopter — so a
core rung was sanctioned one edit outside its territory. The webhook body and
the socket frame carry the envelope; a frame is a signal to re-read, never a
decision. The four-door measure, restated: for one viewer REST equals MCP; for
any viewer `event_payload(REST)` equals `Event.payload`; a second viewer
differs only in the per-viewer fields — `assert_four_doors` is the assertion
every adopter's wire test calls, and it held only when driven through a second
viewer (one person pressing both doors cannot see the difference). *Rejected*:
the emitter's own acts in the payload (the broadcast above, and a wire break
for every subscriber to undo); acts on an envelope beside a pure `Out` (the
detail route has no envelope, so every detail door re-wraps — a break across
five apps); `allowed_acts: list | None` with `null` meaning nobody asked (a
subscriber cannot tell `null` from "you may do nothing", every `Out` widens,
and the measure still needs the amendment). *Reversal cost*: stripping now and
carrying later is additive — a key appears and no subscriber breaks; the other
direction breaks every subscriber that read the key. trigger to revisit: a
subscriber that needs a viewer's acts in a broadcast — which is a
per-subscriber door, not an event.
