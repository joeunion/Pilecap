# ADR comms-9

**ADR comms-9 · context:** the C1-1c residue — opened/clicked
tracking and real SMS/push vendors were deferred *with the tracking rung,
named* (queue C1-1); the status contract and the consent wall now stand
(P2's R2, ADR comms-8: bounce-driven auto-suppression in-transaction,
wall re-run at the transport edge). **decision:** grow `apps/comms` —
no new app (the aggregate is still `Message`; A1 holds). Two halves.
**(a) Engagement:** `MessageEngagement(OrgScopedModel)` —
**`append_only = True`** (rule 20 population, by declaration, no yaml
edit — the ADR core-6 dividend): FK `Message` (`CASCADE` — owned child of
the aggregate, D2), `kind` (`TextChoices`: `OPENED`, `CLICKED`), `url`
(clicked only), `occurred_at`, `provider_event_id`, unique on
`(message, provider_event_id, kind)` (idempotent webhook redelivery, C4);
`derive_org_from = "message"` (C9 — the engagement lands where its message
lives, never where a webhook handler's hat points). Recorded by
`record_engagement` (service, `system` actor — comms-8's A5b shape), fed by
the **existing signed provider webhook receiver** through
`normalize_status`'s sibling `normalize_engagement` on the provider
protocol. **An engagement never mutates `Message.status`** — an "open" is a
provider-attested inference (Apple MPP fires false opens), witnessed
history in one population, delivery truth in another; folding them would
launder an inference into a fact. **(b) Channels:** the `SMS` and `PUSH`
kinds in the existing `Channel` enum get one reference transport each,
riding `ConnectionChannel` (provider = a `connections` row, comms-6's
kind-vs-vendor split intact). Push needs `Device(OrgScopedModel)`: FK
`Recipient` (`CASCADE`), `token`, `platform` (`TextChoices`), `last_seen_at`,
`invalidated_at`; `derive_org_from = "recipient"` (C9). *Rejected:* push
tokens in `Recipient`'s address fields (tokens are plural per person,
rotate, and expire — an address is one and stable); a first-party tracking
pixel/redirect endpoint (BYO-frontend; the ESP does it; trigger: a product
that must not use ESP tracking domains); deriving `DELIVERED` from an open
(the laundering above); OneSignal (its own consent model competes with the
wall — two walls is no wall). **trigger to revisit:** a provider contract
distinguishing per-link click metadata worth modeling → `url` grows
structure then.

**The wall is not a weapon (ADR comms-9, amending comms-8):** a bounce carries a `BounceKind` and only a **hard** one suppresses — `complained` and `rejected` are hard by their event type, an unclassified bounce is hard by the conservative default, and a soft bounce is recorded and acts on nothing; **Amended: complaints are consent news, not delivery news — they suppress without transitioning the message; the soft branch is provider-dependent and declared per adapter.** `complained` still normalises onto `bounced` at the adapter, because *stop mailing this address* is what one suppression rule has to read, but it carries `ProviderStatus.is_complaint` out with it and `record_delivery_status` forks on that above every transition guard: the recipient is suppressed through the same `suppress_recipient`, the fact is announced as `comms.message.complained`, and `Message.status` is left exactly where the provider left it — a complaint by definition follows a delivery, and the collapsed set could only say so by writing `bounced` onto a row that had arrived (`complained@resend.dev` was refused with `Conflict("That message is delivered and can no longer be bounced.")` and suppressed nobody). The settled-row guard itself is untouched: a *bounce* after delivery is still refused. **No column** — the fact is carried by the suppression, the audit row and the event; a `complained_at` waits for a product that must list complaints per message without reading the audit trail, and until then a flood made only of complaints does not open a surge (the tripwire counts the bounce population); the provider message id is **never echoed into the mail we compose**, because it is the key a status webhook suppresses an address against and a forwarded receipt was therefore a weapon; and a **mass-suppression tripwire** (25 addresses per connection per trailing hour) emits `comms.suppression.surged` / `.recovered` on the **transitions only** — the announce-on-transition ruling's first application — without ever halting suppression, since a tripwire that disabled the wall would be the better attack.
