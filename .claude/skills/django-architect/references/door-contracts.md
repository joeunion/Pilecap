# Contracts across the doors — the long form

The long form of `django-architect` § E.

**E3 — Events are `<app>.<noun>.<past-verb>`, declared in the app's
`events.py`, carry `v` in the payload, and are emitted only from services,
inside the transaction; payloads are the `Out` schema through `event_payload`,
with no field marked `personal`.** *Why:* a name
declared once is greppable and reviewable; a version lets a subscriber survive
the next field; an emit from anywhere but a service is a write nobody audited.
*Enforced:* house rule **16** (name + declaration); **4** (no signal emits);
criterion (the event row exists after the write, with `v`). Form: conv §8.
*Wrong:* `emit("OrderCreated", ...)` from a `post_save`. *Right:* **[A7a]**
`events.py`: `ORDER_PLACED = "orders.order.placed"  # v=1`, and in the service
`emit(name=ORDER_PLACED, tenant=tenant,
payload=event_payload(OrderOut.from_orm(order)), actor=actor)` — `emit` adds `v`.

**E4 — Workflows: one workflow per long-running process; deterministic ids via
`workflow_id()`; activities idempotent, with retries and timeouts declared at
the call site; workflow code deterministic.** *Why:* a process that waits or
retries must survive a restart and be findable by name; a random id makes a
retried service start a second run. *Enforced:* house rules **9**
(determinism), **18** (ids — `<tenant>:<app>:<noun>:<key>`;
`start_workflow_on_commit` never receives a random id); criterion (the run's
end state, read in the Temporal UI or `WorkflowRun`, is the instrument).
**[main]** `apps.workflows.services.workflow_id(*, tenant, app, noun, key)`;
`start_workflow_on_commit(..., id=)` refuses any other shape. Form: conv §7.
*Wrong:* one `ProcessOrder` workflow that fulfils, invoices and collects.
*Right:* `FulfilOrder` in `orders`, `CollectInvoice` in `invoices`, joined by
events.

**E5 — API versioning is additive: `/api/v1/` from day one
(`NinjaAPI(version="1")`); a breaking change is a `v2` router beside `v1`,
declared by the lead.** *Why:* a renamed field breaks every client at once;
two routers let clients move. *Enforced:* review; criterion ("`v1` responses
unchanged for the fixture set"). **[main]** `config/api.py` carries
`version="1"`. A new field, a new route, a new optional filter: additive. A
removed field, a changed type, a changed status: `v2`.

**E6 — The list standard.** Every list `@paginate(CursorPagination)` —
`?cursor=` and `?limit=` ≤ 200, envelope `{items, has_more, next_cursor,
count}`, `count` computed only for `?include_count=true` (ADR core-18;
`page`/`page_size` retired outright, and the cursor
lives in ONE seam that no app duplicates); filters via a `FilterSchema`;
`ordering=` from a per-route allow-list; `q=` for search; errors `{detail,
code, errors?}` from the single mapper; UUIDs in paths. *Why:* the field test
and the MCP client learn one list shape once — and an offset page silently
skips or repeats a row under a concurrent write, which a cursor cannot.
*Enforced:* house rule **3** (`auth=`, `@paginate`); **5** (query pin at seeded
scale — the default list issues no `COUNT`, and the pin is what makes that
observable); criterion (each filter, ordering and `q` named, with its
absent-case result). **[main]** the example router, `apps/core/api/pagination.py`
and `API_PAGE_SIZE` in settings. Form: conv §6.

**E9 — Every refusal speaks the three-move grammar — fact, structured
remedies, one composer — and the parts are required at import.** A refusal
code is declared beside the class that raises it with
`core.exceptions.register_refusal(code=, boundary=, remedy=, fact=,
remedies=)`, and the declaration is refused **at import time** — the
strongest tier the tree has — when the `fact` is missing or a remedy is a
string rather than a `Remedy`; `DomainError.__init_subclass__` refuses an
unregistered `code` the same way. The moves: **`fact`** is what is *true*,
said to whoever is refused (`not_found`'s fact states that not-there and
not-yours are one answer on purpose — a refusal that told them apart would
confirm the row exists); **`remedies`** are what they can *do*, as frozen
`Remedy(label, destination)` — a label a screen puts on a button and an
assistant says out loud; the internal `remedy` prose survives for whoever
holds the refusal and **never reaches the wire**. `destination` is **opaque
in the template** (`<kind>:<name>` tokens — `header:X-Org`,
`introspect:refusals`): there is no navigation manifest to validate it
against here, so the first product that grows one grows the rule that checks
its remedies name real destinations — the product validates, never this
layer. **One composer**: `core.exceptions.wire_refusal(exc)` builds
the body over `apps/core/exceptions.py::WIRE_COMMON_KEYS` — and both mappers call it: `config/api.py`
sends it as JSON, `core.mcp.tool_call` renders it through `refusal_message`
as one line, code first. A raise site that knows something better than the
registry may pass contextual `remedies=` (typed; overriding the default
entirely, never appended). *Why:* remedies composed per door are how the
screen and the assistant come to offer different ways out of the same
refusal — the drift the grammar exists to close; parts enforced at import
are the difference between a grammar and a set of optional parameters.
*Enforced:* import-time (`register_refusal`,
`DomainError.__init_subclass__`); criterion (the MCP rendering
string-compares against the REST body's fields — one composer, two doors,
rule **17**'s spirit); `introspect`'s refusals section shows every code's
fact and remedies. *Wrong:* a route catching `NotFound` and shaping its own
body; a remedy as a sentence. *Right:* `raise NotFound()` anywhere, and the
composer speaks for every door.

**E10 — A computed aggregate travels as `MeasuredOut`: a number the UI never
computes, with its basis attached.** `core.schemas.MeasuredOut`
(`value: Decimal`,
`basis: MeasuredBasisOut(formula: str, inputs: dict[str, Decimal])`): the
server ships the number *and how it was arrived at*, so a person can check
the arithmetic without a second request and no door ever adds the parts up
for itself. `Decimal` at both levels (rule **15**), rendered as strings on
the wire, so the value that arrives is the value that was computed. ADR
core-7 writes the pair unsuffixed in prose; the classes carry the suffix
every schema carries (rule **16**) — cite them suffixed. *Why:* ship the
parts and let each door sum them, and the dashboard, the export and the
assistant disagree about revenue while reading the same rows; the contract
was honored 104 times by convention in the product this was lifted from,
which is a convention worth a type. *Enforced:* **criteria-tier, honestly**
(ADR core-7): "any endpoint returning a computed aggregate" is an open set no
closed question can scope, so there is no AST rule pretending to recognise an
aggregate — this checklist carries the line, and the blind spot is declared
rather than disguised as a rule. The criterion's shape: the value equals the
recomputation from `inputs` (the basis is honest, *checked*), and the MCP
twin's fields are byte-equal (rule **17**). *Wrong:* `{"count": 42}`.
*Right:* a `*StatsOut` whose aggregate field is `MeasuredOut`, with a
`formula` and `inputs` a reader can re-add.
