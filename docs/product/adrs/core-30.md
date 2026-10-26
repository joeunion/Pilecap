# ADR core-30

**ADR core-30 · a field that names a person is declared `personal` on its `Out`;
`event_payload` strips marked fields at any depth and `emit` refuses one.**
*PROPOSED by the engineering lead (LEAD-REMAINDER-DAY3, 2026-10-06) under the
owner's ruling of 2026-10-04 22:44 ("agreed no pii" — no personal data in a
published event payload; a subscriber reads the person through the API);
SIGNED by the owner 2026-10-08 12:48 ("1. ok", recorded by the PM; rule 93 is its census).* *Decision*: the member's own declaration —
`Field(json_schema_extra=personal(example(...)))` beside `example()` — marks the
field; `event_payload()` walks the `Out`'s declarations (nested `Out`s and lists
of them included) and strips every marked field; `events.services.emit` refuses
a payload that still carries one; OpenAPI shows `x-personal: true` for free; a
house rule censuses the lexicon-shaped fields (`email|phone|*_name|*handle`,
exemptions closed-listed, and a bare `name` on a shape whose noun is a person —
rule 93's reach) for the mark or a `# not-personal:` valve. *Rejected*:
per-event projection classes (two shapes per noun forever; the CORE-EVENTS rider's
`MembershipEventOut` is unwound by EVENT-PII-CORE with its seven-key pin kept); a
central list of personal field NAMES stripped by `event_payload` (`name` is a
role's and a person's, `display_name` a recipient's and an organization's — a hand
list of an open set every product would edit). *Trigger to revisit*: a subscriber
that needs a person's field on the wire (then it reads the person through the API
by id, or this ADR is reopened); free text (`subject`, `error`, `body`) is outside
any field-level mechanism and is review's.
