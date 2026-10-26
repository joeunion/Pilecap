# ADR usage-1

**ADR usage-1 · context:** the platform is about to spend
money on behalf of tenants (ING-3 tokens; later SMS, storage), and a
number that surfaces on an invoice or a dashboard months later must be a
ledger, not a counter someone can bump. **decision:** a new platform app
`apps/usage`, **metering only** — invoicing stays product-layer until a
product asks (the scope ruling, recorded here). Aggregate:
`UsageEntry(OrgScopedModel)` with **`append_only = True`** (rule 20
population, by declaration): `meter` (charfield, grammar
`<app>.<noun>.<unit>` — e.g. `completions.tokens.input`), `quantity`
`Decimal(19,4)` (rule 15 — never Float, even for counts), `occurred_at`,
`ref` (source model label + id), `idempotency_key` (unique per tenant —
C4: a retried activity never double-meters), and the D8 correction pair:
`supersedes` FK (self, `PROTECT`) + `superseded_because` — a wrong entry
is answered, never edited. Meter names are **declared vocabulary**:
`apps/<x>/meters.py` (discovered, the `events.py` pattern — a literal at a
call site is a violation the same way an event literal is), validated
against the grammar at import time. The write door is one service:
`record_usage(*, tenant, actor, meter, quantity, ref, idempotency_key,
occurred_at=None)` — callable from activities under the run's actor;
`# authz: recording is the platform's witnessed side-effect of an
already-authorized action; the actor is carried for audit, not asked for
permission` (rule 13's escape hatch, used with its reason). The read is
`get_usage(*, tenant, actor, period, meters=None)` returning per-meter
**`MeasuredOut`** (E10): `value` = the period total, `basis.formula` =
`"sum(day_totals)"`, `basis.inputs` = ISO-date → Decimal day subtotals —
**re-addable by a reader**, the honest basis, checked by criterion.
**rejected:** stored per-tenant counter rows (see stack ruling); per-entry
events (an outbox row per LLM call doubles the write volume of the
hottest path for zero subscribers; the ledger IS the record; trigger:
a quota/threshold feature → threshold events then — **the trigger has since fired**,
see § events below: the crossing gets an event, the entry still never
does); a `Meter` model
(meters are code-declared vocabulary like events, not tenant data).
**trigger to revisit:** a product asks for invoicing → a product-layer
app reading this ledger (the ledger's shape — Decimal, ref, supersedes —
is designed so that day needs no migration here).

**TRIGGER — buffered ingestion (ratified alongside this ADR's criteria
amendments): the first per-REQUEST meter.** Every meter this ADR names
is **per-activity** — a completion that ran, an upload that finalised — so one
`record_usage` per unit of durable work, at the rate a worker does work. The
day a meter is recorded **per request** (an API call counted, a page served, a
tool invocation billed), the arithmetic changes shape: U1 measured one recording
at **13 statements** on a tenant with no thresholds configured
(`apps/usage/tests/test_services.py::RECORD_QUERY_BUDGET`, and nine of the
thirteen are `full_clean` plus the transaction and audit machinery every
`@service` pays), which is unremarkable per activity and is a second write
transaction on every request in the product. That is when buffered ingestion
gets its own ADR — a batched or queued write path in front of this ledger, with
the durability question answered out loud, because a buffer that loses rows is a
bill that is wrong in the customer's favour and a buffer that blocks is an
outage. **Nothing is built for it now**, deliberately: the shape of the buffer
depends on which per-request meter arrives first and what it may lose.
