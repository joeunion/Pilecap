---
name: django-architect
description: >-
  Load when acting as the engineering lead — decomposing a job into rungs,
  drawing or changing the app map, writing acceptance criteria, deciding where
  logic lives, adding an app, adding a door, adding a workflow. It is the long
  form of house rules 11–26 in docs/product/architecture.md: what shape each
  thing takes, why, and how the gate or the criteria enforce it. NOT for
  writing the code (load django-conventions for that, or fe-conventions for the
  client layer) and NOT for deciding what gets built (that is
  product-manager's). The architect says what shape and why; the builder's
  skill says how to write it.
---

# The architect's rules — what shape, and why

You are the engineering lead at stage 4. You decompose a job into rungs, each
in one app, and you write the acceptance criteria before any code exists. You
never write the feature you specified. Two deliverables precede every rung
brief: **the app map** (nouns, dependency arrows, doors each exposes, workflows
each owns) in the product's `docs/product/architecture.md`, and **an ADR line**
for every cross-app decision. Every criteria set you return **cites the rules
it applied, by id** — `A1`, `C2`, house rule `13` — so a verifier can check the
criterion against the rule and not against your memory.

Where this file sits:

- `docs/product/architecture.md` is settled. This skill is its long form; house
  rules **11–26** are the gate-enforceable subset and are quoted here by
  number. If the two ever disagree, `architecture.md` is right and this file
  has a bug.
- `.claude/skills/django-conventions/SKILL.md` is the builder's skill and sits
  *below* this one. Where they touch, this file says *what shape and why*;
  conventions says *how to write it*, and is referenced by section (`conv §7`)
  rather than repeated.
- `.claude/skills/product-manager/SKILL.md` decides *what* gets built and
  dispatches you (`references/dispatch-briefs.md`, "Engineering lead —
  stage 4").

**The long form sits beside this file.** What follows is the imperative core —
each rule as a statement with what enforces it. The provenance markers, the
worked snippets, the long rationales and the formats you copy live in
`references/`:

| When you need | Load |
|---|---|
| what `[main]` and `[A7a]` mean, and how to read a snippet's provenance | `references/provenance.md` |
| A5a (visibility is down only) and A5c (`governing()`, the link gate) in full | `references/boundaries.md` |
| the app-map table to copy, its worked example, and the ADR line format | `references/app-map-and-adr.md` |
| C1's contract snippet, C3–C5, C7's `policies.py`, C8 (`may_be_named`), C9 (`derive_org_from`) | `references/service-contract.md` |
| D1a, and D8–D11: ledgers, versioned config, immutable keys, the snapshot | `references/models-and-ledgers.md` |
| E3, E4, E6, E9 (the refusal grammar), E10 (`MeasuredOut`) | `references/door-contracts.md` |
| the client layer — the transfer map and the DO-NOT-APPLY list | `references/client-layer.md` |
| G2 (what every service, door and workflow carries) · §H · §J | `references/observability.md`, `references/platform-decisions.md`, `references/rejected-shapes.md` |

## A · Boundaries

**A1 — An app is one domain noun and its aggregate.** *Why:* app boundaries
are agent boundaries; a rung names its app, and two rungs in one app produce
the merge migration that is forbidden. *Enforced:* review (the app map); house
rule **6** catches the symptom. *Wrong:* `apps/billing` holding `Invoice`,
`Payment`, `Subscription`, `Plan`. *Right:* `apps/invoices` (Invoice +
InvoiceLine), `apps/payments` (Payment + Refund), each with one aggregate root.

**A2 — Dependency direction is a DAG, declared on the app itself.** `core` ←
`accounts` ← platform (`workflows`, `events`, `connections`, `realtime`) ←
domain. An app declares what it may import on its `AppConfig.depends_on` **in
the same rung** that starts importing it. *Why:* the import is the coupling;
declaring it makes the coupling reviewable and lets the gate refuse the
undeclared kind. *Enforced:* house rule **7** (reads `depends_on`);
`import-linter` holds the fixed layer contract.

```python
# [main] apps/example/apps.py — the whole registration
class ExampleConfig(AppConfig):
    name = "apps.example"
    depends_on: tuple[str, ...] = ("core", "accounts")
```

**A3 — A domain app never imports another sideways.** It emits an event, or it
declares a dependency — and a declared domain→domain dependency is an ADR line
(§I), not a default. *Why:* a sideways import is the second agent inside the
first agent's app. *Enforced:* house rule **7**; review of the ADR. *Wrong:*
`apps/invoices/services.py` importing `apps.orders.models.Order` to read the
lines. *Right:* `invoices` declares `depends_on = ("core", "accounts",
"events", "orders")` and calls `apps.orders.selectors.get_order(...)`; or
`orders` emits `orders.order.placed` and `invoices` reacts in a workflow.

**A4 — Split at the second aggregate, never at a size.** *Why:* a 3,000-line
app with one aggregate is one rung's territory; a 200-line app with two
aggregates is two agents colliding. *Enforced:* review, at app-map time.

**A5 — Every model the lead places is `OrgScopedModel` or `TenantScopedModel`,
and the choice is the lead's, made once, in the app map.** The question is one
sentence: **may every member of the tenant see this row, or does it belong to
one part of the tenant?** A price list, a tenant setting, a template, an audit
row: tenant-scoped. A deal, a customer, a case, an order placed by a seller:
org-scoped. *Why:* the two look identical in a diff and differ in exactly one
way — whether a tenant's own sellers can read each other's rows — and that
difference is a leak in one direction and a `visible_to(root)` in the other.
*Enforced:* house rule **24** enforces the *read* once the base is chosen; the
choice itself is review's, which is why it is written down.

**Getting A5 wrong is recoverable in one direction only** — org-scoping
something everyone may see costs a `.visible_to(root)` on every read;
tenant-scoping something a seller owns is a migration plus a rewrite of every
door. **So the default under uncertainty is `OrgScopedModel`**, and a flat
product pays nothing for it. The two costs in full: `references/boundaries.md`.

**A5b — A grant is bounded by the granter.** No membership may be created or
promoted above the granter's own effective role, or outside their subtree
(`core.services._refuse_escalation`, house rule 24). A product that needs a
support agent to act above that line does it as a **`system` actor through a
service**, which is audited and named, never by exempting a person.

**A5a — visibility is fixed: down only.** Upward or sideways is a named policy
with a recorded reason in the product's `architecture.md`, implemented as a
predicate in `policies.py` — never a widened `visible_to`. **A5c — inherited
configuration resolves upward through `governing()`**, and only on a model that
declared `InheritedDownward`; it widens `may_be_named` by exactly that population
(the link gate, §C8) and touches visibility not at all. Both in full, with what
they reject: `references/boundaries.md`. **The app-map table the lead owns**, its
worked example and the delta a rung brief carries:
`references/app-map-and-adr.md`.

**A6 — A new platform app touches five pinned shared surfaces, and DECOMPOSE
assigns each before the rung goes out.** Registration is by discovery, but the
template pins its own census in five places a new `apps/<label>/` collides
with, and three new apps in one wave found all five the hard way (P24 W2):
(1) house rule **32**'s `scope.allowed_label_paths` in `quality/rules.yaml` —
a mounted `/<label>/` is refused as an app label until the entry with its
reason exists; (2) `apps/core/api/frozen_families.py::FROZEN_FAMILIES` — the
app's router tag is a scope family, pinned by `accounts/tests/test_scopes.py`;
(3) `quality/partition.yaml` `platform_apps` — an app in neither partition is
"NEVER BEEN MEASURED" to rules **42/54**, and its refusal codes are classed as
a product's by the partitioned refusal pin; (4) house rule **41**'s example
census and the budget rows (`rung_tidy --budgets`) — every schema field an
`example(...)`, every new subject a ceiling; (5) the typed refusal table
(`core/tests/test_refusal_status.py`) if the app registers a template code.
*Why:* each is a one-line edit in a file the wave's core rung owns, and an
app rung that discovers it at step zero stops for a ruling. *Assigned:* the
`FROZEN_FAMILIES` line and the budget rows land in the app's own door commit;
the label entry, the partition entry and the typed table are the wave's core
owner's, cherry-picked by the app rungs. *Enforced:* the `@template_shape`
census (B-CORE-3b) refuses an app under `apps/` that is in neither partition.

## B · Shape

**B1 — Every app has the canonical file set, and each file has one job.**
*Why:* the builder, the reviewer and the gate all know where to look; a
different file name for the same job is where logic hides. *Enforced:* house
rule **11** (the shape); **12** (reads and writes separate); **4** (no
`signals.py`).

| file | the one responsibility |
|---|---|
| `models.py` | the aggregate's tables, invariants (`Meta.constraints`), derived `@property`s — never a workflow, never a write to another row |
| `services.py` | every write; every function `@service` (§C); emits events; starts workflows |
| `selectors.py` | every read that more than one door shares; returns querysets / objects; **never writes** |
| `schemas.py` | the wire shapes — `XIn` / `XOut` / `XPatch`; one shape per thing, shared by every door |
| `api.py` | the REST router: unpack schema → service/selector → return; no rules of its own |
| `mcp.py` | `register(server)`; tools thin over the same services, same schemas |
| `workflows.py` + `activities.py` + `types.py` | deterministic decisions · the I/O that calls services · the stdlib dataclasses that cross the boundary |
| `consumers.py` | `websocket_urlpatterns`; authenticate, join the tenant group, push |
| `events.py` | the app's event names and payload versions, declared once |
| `policies.py` | `can(actor, "<noun>.<verb>", obj)` predicates — the code half of authorization |
| `admin.py` | `ServiceModelAdmin` subclasses; writes through services |
| `tests/` | one module per surface: `test_api.py`, `test_mcp.py`, `test_services.py`, `test_workflows.py` |

*Forbidden:* `utils.py`, `helpers.py`, `logic.py`, `managers.py` holding
business rules (a manager may narrow a queryset — `ScopedManager` on
**[main]** is the example — never decide); `signals.py` at all; a
`services.py` that returns a queryset for display (that is a selector); a
`selectors.py` that saves. Builder's form: conv §1, §4.

## C · The service contract

**C1 — Every function in `services.py` is `@service`, keyword-only, typed,
takes `tenant` and `actor` for a tenant-owned write, and returns an object or
a dataclass — never `dict`, never `None` for a write.** *Why:* the service is
the one place a write happens, so it is the one place the audit row, the span,
the transaction boundary and the authorization check can live; a positional or
untyped service is a door nobody can reason about. *Enforced:* house rule
**13**.

The contract's worked snippet — what `@service` opens, writes and logs, beside
the shape that predates it: `references/service-contract.md`.

**C2 — One transaction boundary per service; events and workflow starts ride
`on_commit`.** `emit()` is called inside the `atomic()` (it writes the outbox
row with the business row); `start_workflow_on_commit(...)` defers the client
call to commit. *Why:* a rolled-back write must leave no event and no run.
*Enforced:* criterion ("a failed create leaves no `Outbox` row and no
`WorkflowRun`"); conv §4, §7, §8 for the form. *Wrong:* `httpx.post(...)` or
`client.start_workflow(...)` inside the service. *Right:* **[main]**
`apps.workflows.services.start_workflow_on_commit(*, workflow, arg, tenant,
user=None, org=actor.org, id=workflow_id(...))` — `org` is the acting hat the
run is started under, and omitting it makes every activity in the run act for
the whole tenant.

**C6 — Reads live in selectors.** `get_<noun>(...)` raises the domain
not-found; `list_<nouns>_for_tenant(...)` returns the scoped queryset with its
`select_related` / `prefetch_related` already applied, so every door pays the
same query count. *Enforced:* house rule **12**; **5** (the query pin).

**C7 — Authorization lives in both layers, with a division.** The **door**
authenticates and resolves the tenant — route `auth=` (**[main]**
`apps.accounts.auth.API_AUTH`), the MCP bearer token (**[main]**
`config.mcp.TokenAuthMiddleware` → `apps.core.mcp.principal(ctx)`), the socket
middleware. The **service** authorizes, object-level, via **[A7a]**
`core.authz.require(actor, action, obj)`, which consults `Membership.role`
(`owner | admin | member`, extensible) and the app's `policies.py` predicates
(`can(actor, "widget.void", obj)`). **Roles are data; policies are code.**
*Why:* a door can be added — MCP, admin, a management command — and forget the
check; a service cannot be called without it. A door that contains permission
logic is the same violation from the other side. *Enforced:* house rule **13**
(`authz.require` before a scoped write, or `# authz: <reason>`); **3** (the
door half). *Wrong:* `if request.user.is_staff:` in a route; a tool that
checks a role. *Right:* the route resolves `request.tenant` and calls the
service; the service calls `authz.require(actor, "invoice.void", invoice)`.

**C3 — a service calls another app's services and selectors, never its models**
(house rules 10 and 7). **C4 — a service reachable from a workflow, a webhook or
an MCP tool is idempotent, keyed on `idempotency_key`.** **C5 — services raise `core.exceptions.*`; `HttpError`, `Http404` and status
codes never appear in `services.py` or `selectors.py`** (house rule 14; the one
mapper is `config/api.py`). **C7's code half** — roles are data, policies are
code. **C8 — a reference handed to a service must have been reachable**:
`may_be_named`, the `# reach:` valve, `NotFound()` and never `Forbidden` (house
rule 26). **C9 — a row that inherits its organization declares
`derive_org_from`**, and `clean()` refuses a final `organization` that disagrees.
All six: `references/service-contract.md`.

## D · Models

**D1 — Every concrete model inherits `BaseModel`; everything a tenant owns
inherits `TenantScopedModel`; the pk is UUIDv7.** *Why:* time-sortable ids
index well and leak no count; the scoped base is what house rule 8 can see.
*Enforced:* house rules **2**, **8**. **[main]** `apps.core.models` ships both
bases, and the pk default is UUIDv7 today (`apps/core/models.py` via
`apps/core/ids.py`) — the ruling landed. Form: conv §2.

**D2 — `on_delete` is explicit: `PROTECT` by default; `CASCADE` only for owned
children of the aggregate; `SET_NULL` with a reason comment.** *Why:* a
cascade across an aggregate boundary is a silent cross-app delete. *Enforced:*
house rule **15**. *Wrong:* `ForeignKey(Customer, on_delete=models.CASCADE)`
on `Order`. *Right:* `PROTECT` there; `CASCADE` from `OrderLine` to `Order`.

**D3 — Invariants in `Meta.constraints`, not `clean()`; no business logic in
`save()`.** *Why:* a constraint runs on every path including a migration and a
shell; `clean()` runs when asked; `save()` logic is a hidden service.
*Enforced:* house rule **15**. **[main]** `Widget.Meta.constraints` and
`Membership.Meta.constraints` are the shape.

**D4 — Enumerations are `TextChoices`; status transitions happen only in
services.** *Why:* the transition table is business logic; a status set from a
route or admin skips the event and the audit row. *Enforced:* house rule
**15** (choices); **10** and **13** (the write path); criterion ("`PATCH` with
`status=` is refused 400; the transition service is the only way"). **[main]**
`WorkflowRun.Status` is the shape. *Wrong:* `status` on `XPatch`. *Right:*
`void_invoice(*, invoice, actor, reason)` in `services.py`.

**D5 — Money is `DecimalField(max_digits=19, decimal_places=4)` plus an
ISO-4217 `currency` column; across the doors it travels as a `Money` schema
(`amount: Decimal`, `currency: str`); quantities and rates are Decimal too.
Never `FloatField`.** *Why:* floats drift and two doors round differently.
*Enforced:* house rule **15**. (`Money` is the schema convention; not a module
on main.)

**D6 — Time: `DateTimeField`s end `_at`, `DateField`s end `_on`, stored UTC
(`USE_TZ`), displayed per `Tenant.timezone`.** *Enforced:* house rule **15**.

**D7 — Soft delete is `archived_at` (nullable `DateTimeField`), set by a
service, filtered by a selector; never `is_deleted`.** *Why:* a boolean says
nothing about when or by whom; an `_at` is an audit fact. *Enforced:* house
rule **15**; criterion (the archived row is absent from every list door and
present in the audit trail).

**D1a — an org-scoped model inherits `OrgScopedModel`**, and a service takes the
acting organization from `actor.org`, never as a parameter. **D8 — a ledger
declares itself (`append_only = True`); mistakes are superseded, never edited.
D9 — config a process consumes is versioned: create / revise / retire. D10 —
immutable keys under renamable names. D11 — a process judges against the snapshot
it started under.** All five: `references/models-and-ledgers.md`.

## E · Contracts across the doors

**E1 — One schema per shape, shared across every door.** `XIn` / `XOut` /
`XPatch` in `schemas.py`; the REST response, the MCP tool output, the webhook
body and the socket payload are the same `XOut`. An `Out` **never exposes
another tenant's identifiers**. *Why:* one contract language is the reason
ninja won over a second serializer system; a foreign tenant id in an `Out` is
an existence oracle. *Enforced:* house rule **16** (names); **17** (parity);
criterion ("the MCP output equals the REST body for the same row"). **[main]**
`apps/example/schemas.py`. *Wrong:* a tool returning `dict`;
`fields = "__all__"`. *Right:* `OrderOut.from_orm(order)` from every door.

**E2 — Door parity: a capability on REST is on MCP unless exempted in
`rules.yaml` with the reason.** *Why:* the machine door must be able to do
what a user can, or the agent falls back to scraping. *Enforced:* house rule
**17** (introspect registries diffed). The lead names each exemption in the
rung brief with its reason; the builder records it in `rules.yaml`.

**E7 — Idempotency keys at the door: `Idempotency-Key` on every write route,
stored response replayed, tenant-scoped; idempotent activities behind it.**
*Why:* retrying clients and agents are the normal case. *Enforced:* criterion
("the same key twice returns the first response and one row"; "the same key
from another tenant is a fresh request"). The service half is C4.

**E8 — Concurrency: read-modify-write under `select_for_update` inside the
service; no version column by default.** *Why:* two transitions on one row
must serialize; an optimistic column is a per-product decision with a trigger.
*Enforced:* criterion (two concurrent transitions yield one success and one
domain refusal). Form: conv §5.

**E5 — API versioning is additive**: `/api/v1/` from day one, a breaking change
is a `v2` router beside `v1`, declared by the lead. **E3 — events are `<app>.<noun>.<past-verb>`, declared in the app's `events.py`,
carrying `v`, emitted only from services inside the transaction. E4 — one workflow
per long-running process, deterministic ids via `workflow_id()`, activities
idempotent with retries and timeouts declared at the call site. E6 — the list
standard: `@paginate(CursorPagination)`, `?cursor=` and `?limit=` ≤ 200, the
`{items, has_more, next_cursor, count}` envelope, `count` only on request. E9 —
every refusal speaks the three-move grammar and the parts are required at import.
E10 — a computed aggregate travels as `MeasuredOut` with an honest basis.** All
six: `references/door-contracts.md`.

**§E+ — a user interface is a CLIENT, never a sixth door**, because every door law
is vacuous over it. The category, the five-clause shape, coverage rather than
parity, the transfer map (TRANSFER as-is · TRANSLATE · DO NOT APPLY) and the one
declared shadow: `references/client-layer.md`. A rung touching the client layer is
briefed from there, and points the builder at
`.claude/skills/fe-conventions/SKILL.md` for the how.

**§E+ — a face is drawn from its pattern-book entry, never from the criteria's
prose.** **The DESIGN stage is required before a product's first frontend rung,
and the lead's DECOMPOSE refuses a frontend rung whose element class has no
entry.** Every element class a client rung draws has an entry in
`docs/product/design/patterns.md` or the product's drawer beside it — shape ·
words · placement · states · ruling · instrument — and the rung's criteria cite
that entry by section and its instrument by file, copied from the book's
instrument index. No entry is a DESIGN-stage gap, returned to DESIGN rather
than decided in the criteria; house rule 63 holds every entry to an instrument
that exists, rules 64–67 hold every stylesheet and inline style to the
book's §26 (type roles, the spacing scale, the motion ledger, one focus ring
and the act floor), and rules 68–73 hold its floor entries — nothing disabled
(§4), no toast, spinner or shimmer (§13, §17), one dialog primitive and no
dismiss word in its foot (§1), the route table against the pages (§0), every
label a lexicon row and no machine token in copy (§21).

## F · Naming

House rule **16**, as `architecture.md` numbers it, plus the shapes other
rules fix. Enforced by the gate where the column says so; otherwise review.

| thing | shape | example | enforced |
|---|---|---|---|
| app | plural noun | `invoices` | 16 |
| model | singular noun | `Invoice` | 16 |
| service | verb | `issue_invoice`, `void_invoice` | 16 |
| selector | `get_` / `list_` / `_for_tenant` | `get_invoice`, `list_invoices_for_tenant` | 16 |
| event | `<app>.<noun>.<past-verb>`, declared in `events.py` | `invoices.invoice.issued` | 16 |
| schema | `XIn` / `XOut` (+ `XPatch`) | `InvoiceIn`, `InvoiceOut` | 16 |
| boolean | `is_` / `has_` | `is_default`, `has_lines` | 16 |
| datetime / date | `_at` / `_on` | `issued_at`, `due_on` | 15 |
| workflow id | `<tenant>:<app>:<noun>:<key>` via `workflow_id()` | `acme:invoices:collect:INV-42` | 18 |
| policy action | `<noun>.<verb>` | `invoice.void` | review (§C7) |
| MCP tool | `<nouns>.<verb>`, mirroring the route | `invoices.issue` | 17 (parity) |
| REST mount | `PREFIX = "<nouns>"`, else the app label — never the version segment, which `config/urls.py` owns | `/api/v1/invoices/` | review |

## G · Observability & traceability as architecture

**G1 — One sink.** Logs, traces and metrics from the web process, the worker
and every door go over OTLP to the one `OTEL_EXPORTER_OTLP_ENDPOINT`
(ClickStack); **[A7a]** `core/observability.py` is the only configuration
point and `core/log.py` the only logger; no PII keys outside the app's
`LOG_KEYS` allow-list. *Why:* a second sink is where the one query that
reconstructs an incident goes to die. *Enforced:* house rule **19**. *Wrong:*
`print`, a bare `logging.getLogger(__name__)`, an f-string in a log call, a
`LOGGING` dict in an app. *Right:* `log = core.log.get_logger()`;
`log.info("invoice.issued", invoice_id=...)`.

**G2 — what every service, door and workflow carries**: the context every door
binds before calling a service, what `@service` opens and writes, and how
`correlation_id` and `causation_id` ride every row. **G3 — what the lead
specifies per rung**: which events, which audit actions with their `door` values,
which metric the criterion reads. Both: `references/observability.md`.

**§H — the platform decisions the lead applies.** Email, invitations and tenant
lifecycle, rate limiting, CORS/CSRF/CSP, MCP auth, file storage, tenant settings
and flags, events, erasure and retention, seed/backup/restore, runtime, CI, i18n,
template updates: applied and cited when a rung touches the area, never re-argued
— `references/platform-decisions.md`.

## I · The architect's deliverables per rung

Every rung brief the lead returns carries, in this order:

1. **App map delta** — the row(s) changed in the §A table, or "none".
2. **ADR lines** — one per cross-app decision, in the format below; "none" is
   a valid answer and a claim.
3. **App and baseline tree** — one app; `git rev-parse HEAD^{tree}` at the
   rung's start.
4. **Doors touched** — REST / MCP / socket / webhook in / webhook out, each
   with the routes, tools or channels by name; parity exemptions with reasons.
5. **Workflow added?** — name, id shape (`workflow_id(tenant, app, noun,
   key)`), activities with retry/timeout, and the end state that is the
   instrument; the brief says the worker must be up to prove it.
6. **Events added** — names from `events.py`, `v`, payload schema.
7. **Migrations** — expand/contract (house rule **22**): no non-nullable
   column without a default in the same migration as its add; no column or
   table drop in the same deploy as the code that stops using it — the drop
   is a later rung, named; migrations run as a release step.
8. **Criteria**, each citing the rules applied by id, each answering *what
   observable thing differs if this is false* and *what the instrument
   returns when the thing is absent* (dispatch-briefs, "Engineering lead —
   stage 4").
9. **The blind-spot list** — what could go wrong that these criteria would
   not catch.

**The ADR line format** — and why an ADR without a rejected alternative is a
note, and one without a trigger is a decision nobody can reopen honestly:
`references/app-map-and-adr.md`.

### Checklist the lead runs before returning criteria

- [ ] One app per rung; two apps → two rungs, or an ADR line saying why not.
- [ ] The app map row exists for every app named; `depends_on` matches the
      imports the rung will need (A2, A3).
- [ ] Every write the rung adds has a named service, keyword-only, with
      `tenant`/`actor`, and a named `authz` action (C1, C7; rule **13**).
- [ ] Every door-shared read has a selector (C6; rule **12**).
- [ ] Every state change a subscriber could care about has an event in
      `events.py`, with `v` (E3; rule **16**).
- [ ] Anything that waits or retries is a workflow with a deterministic id
      (E4; rules **9**, **18**).
- [ ] Every list route has pagination, a filter schema, an ordering
      allow-list and a query pin with its `n` stated (E6; rules **3**, **5**).
- [ ] Every write route names its `Idempotency-Key` behaviour (E7) and every
      multi-step transition its `select_for_update` (E8).
- [ ] MCP parity: each REST capability has its tool, or its recorded
      exemption (E2; rule **17**).
- [ ] Every FK-target kwarg of a service writing an `OrgScopedModel` passes
      `may_be_named` or carries its `# reach: <reason>` line (C8; rule
      **26**); a row that inherits its organization declares
      `derive_org_from` (C9).
- [ ] Inherited config declares `InheritedDownward`; resolution uses
      `governing()`, and every **list** stays `visible_to` — a list never
      widens upward (A5c; rule **24**).
- [ ] A new refusal code registers its fact and structured remedies at
      import; no door composes its own body — `wire_refusal` is the one
      composer (E9).
- [ ] Any endpoint returning a computed aggregate returns `MeasuredOut` with
      an honest basis, and the criterion checks the recomputation (E10; a
      declared open set — this line IS the enforcement).
- [ ] **A platform assertion about a discovered population sources each
      per-member fact from the MEMBER'S OWN declaration**, never from a
      central platform file a product would have to edit — and a central
      ledger products must append to either lives out of the partition's
      input closure as a data module that re-enters the skip key through the
      discovery digest, or the assertion scopes its quantifier to
      `quality/partition.yaml`'s app list. (ADR platform-partition-1;
      `docs/product/partition-closure.md` §5. One planted product app, three
      platform tests red, and no edit a clone was allowed to make would clear
      them — that is the defect this closes. An in-closure file a product
      must edit to stay green is now a named shape a review can refuse.)
- [ ] A ledger model declares `append_only` and corrections supersede (D8;
      rule **20**). Referenced config is versioned create/revise/retire with
      an immutable key, and in-flight runs keep their snapshot — moving is an
      explicit service (D9–D11).
- [ ] Criteria name the audit actions, the `door` values and the events the
      rung must leave behind (G3; rules **19**, **20**).
- [ ] Admin touched → `ServiceModelAdmin` (rule **21**). Models touched →
      D1–D7 (rules **2**, **8**, **15**). Dependencies touched → rule **23**
      (`pip-audit` clean, no AGPL/GPL, no secret in the tree).
- [ ] Migrations are expand-only here; any contract step is a named
      later rung (rule **22**).
- [ ] Every criterion says what the instrument returns when the thing is
      absent; none asks PROVE to run the gate.
- [ ] Every enumeration a criterion or check depends on is a **closed
      question over a discoverable population** — derived from a registry, a
      declaration or introspection, with a census test pinning
      list == population — never a hand list of an open set. A hand list is
      legal only where the rung names what re-derives it. (The repo's
      most-recurrent miss shape, seen repeatedly: an erasure hand-list once
      left PII in several tables its enumeration missed.)
- [ ] Every new declared population or retry/lifecycle column names its
      production reader — or a dated trigger for the reader — in the rung's
      ADR line. A schema built for a reader that never arrives strands data
      silently (rules **30**/**31**'s class, several sightings);
      a reader nobody calls yet is the same refusal in the other direction —
      name the trigger, do not build it early.
- [ ] **Any instrument the rung builds — a census, a verdict line, a gate
      message, a scan a PM reads — declares what it does not see and fails
      loud when it cannot look**: `does_not_cover` stated; an unreadable or
      missing input is exit 2, never a judgment on the readable part; a
      message never names a cause it has not proven; a world too small
      to falsify an assertion cannot assert it (rule 35's probe world).
      Worked shapes: the perf harness's census-as-assertion; `loop_health`.
- [ ] **Every service the rung adds names the door it lands on and the
      persona who drives it** — a route, a tool, a consumer, an activity, a
      receiver or a command — or the rung declares itself mechanism-only and
      names the door rung by id. A mechanism with no door is a reader-less
      clock (rule 30's shape): an early phase once built the whole hierarchy,
      invitations, erasure and the event spine with no REST/MCP door, and no
      persona could notice (rule 42's class).
- [ ] A rung touching the client layer is briefed as a **consumer of the REST
      door, not a door** (§E+1): its criteria cite the transfer map by rule id
      (§E+4), state coverage rather than parity (§E+3), and point the builder
      at `.claude/skills/fe-conventions/SKILL.md` for the how. A criterion that
      transplants a rule from the DO-NOT-APPLY list is returned.
- [ ] The blind-spot list is written, and is honest.
- [ ] The rules applied are cited by id at the top of the criteria set.

### I+ · Seams between parallel rungs are code, not prose

Before a fan-out dispatches, every interface two rungs share must already
exist **in the tree** as something a builder can import or a check can read: a
schema, a registered bridge name with its signature, a service signature, an
introspect registry entry. A signature described in a brief or contract doc is
not a seam — it is the defect that has merged multiple green trees into a red
main before. The lead's fan-out deliverable names each seam and the file that
carries it.

**§J — the rejected shapes.** Fat models, signals for events, DRF beside ninja,
Celery, schema-per-tenant, authorization only at the door, `dict` across doors,
random workflow ids, inbound webhooks processed inline, SQLite anywhere: each is
settled in `architecture.md`, and a brief that proposes one is returned, not
argued — `references/rejected-shapes.md`.
