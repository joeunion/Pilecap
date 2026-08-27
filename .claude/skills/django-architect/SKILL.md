---
name: django-architect
description: >-
  Load when acting as the engineering lead — decomposing a job into rungs,
  drawing or changing the app map, writing acceptance criteria, deciding where
  logic lives, adding an app, adding a door, adding a workflow. It is the long
  form of house rules 11–26 in docs/product/architecture.md: what shape each
  thing takes, why, and how the gate or the criteria enforce it. NOT for
  writing the code (load django-conventions for that) and NOT for deciding
  what gets built (that is product-manager's). The architect says what shape
  and why; the builder's skill says how to write it.
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

Every rule below is stated as **statement · why · enforced · wrong → right**.
"Enforced" names the house rule id the gate runs, or says *criterion* (you
write it into the rung) or *review* (the lead checks it before returning
criteria; nothing automatic catches it yet). **Every module this file marks
`[main]` or `[A7a]` is on main today** — `core.service`, `core.authz`,
`core.audit`, `core.context`, `core.exceptions`, `core.actor`, `core.log`,
`core.observability`, and `selectors.py` / `policies.py` / `events.py` per app
all exist. The two markers now mean only *which shape a snippet shows*:
`[A7a]` is the contract's form, which is what the code does; `[main]` beside an
older snippet is kept where it names a real file, and where the snippet itself
predates the contract it says so. **Read the module, not this file** — the
markers are provenance, and the tree is the authority.

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

- **Cost of getting it wrong safely** (org-scoping something everyone may see):
  every read carries `.visible_to(root)`. Recoverable in one rung.
- **Cost of getting it wrong the other way** (tenant-scoping something a seller
  owns): every member of the tenant reads every seller's rows, and the fix is a
  migration plus a rewrite of every door. Not recoverable in one rung.
- **So the default under uncertainty is `OrgScopedModel`.** A flat product pays
  nothing for it: the tenant is a depth-one tree, every membership sits on the
  root, and `visible_to(root)` is the whole table.

**A5a — The direction of visibility is fixed: down only.** A membership sees
its own node and everything beneath it; roles inherit downwards
(`core.authz.effective_role`). Upward or sideways visibility — a sub-seller
seeing its parent's rows, a branch seeing a sibling's — is **not** a
configuration flag and is never added by widening `visible_to`. It is a
**named policy with a recorded reason** in the product's `architecture.md`
(context · what business fact demands it · what is exposed · trigger to
revisit), implemented as an explicit predicate in the owning app's
`policies.py` and a selector that says so in its name. *Why:* every deviation
anybody has ever wanted turns out to be one report for one role, and a
selector for that report is a hole with edges; widening the primitive is a hole
without any. *Enforced:* review — house rule 24 sees the shape of the read, not
its direction, and says so in its `does_not_cover`.

**A5b — A grant is bounded by the granter.** No membership may be created or
promoted above the granter's own effective role, or outside their subtree
(`core.services._refuse_escalation`, house rule 24). A product that needs a
support agent to act above that line does it as a **`system` actor through a
service**, which is audited and named, never by exempting a person.

**A5c — Inherited configuration resolves upward through `governing()`;
nothing else ever looks up.** A model whose rows are configuration a parent
sets for its descendants — a policy, a template choice, a quiet-hours window —
declares **`InheritedDownward`** (`apps.core.models`), and only then is
`Model.objects.for_tenant(t).governing(org)` legal: the rows on `org`'s
**ancestor chain**, nearest first, in one query — the chain is decomposed out
of `org.path` in Python (`ancestor_paths`), never a tree walk. *Why:* "the
nearest ancestor's policy wins" is one algorithm that repeats per product (ADR
core-3 counted three identical call sites in the product this was lifted
from), and the alternative — widening `visible_to` — is A5a's hole without
edges. **Upward config resolution, never upward visibility**: `visible_to` is
untouched and stays downward-only; a branch *resolves* the policy it was
already governed by whether it could see it or not, and it still cannot list
its parent's rows. `governing()` on an unmarked model raises `TypeError`
naming the marker; `governing(None)` returns nothing — the same fail-closed
shape as `for_tenant(None)` and `visible_to(None)`. The declaration also
widens `core.authz.may_be_named` by exactly the marked population — the **link
gate** (§C8): a branch may *name* ancestor config it could never list,
because the edge on the hole is that the caller must already hold the
reference, so it discovers nothing. Sideways is not this and never becomes
this — a sibling share is A5a's named policy with a recorded reason.
*Enforced:* the model refuses (`TypeError`); house rule **24** as amended — a
`governing()` on a model that has not declared `InheritedDownward` is a
violation, so the widening and its fence are born together; the marker
decision itself is review's, made in the app map beside the A5 choice.
*Wrong:* `visible_to` widened to "and ancestors" for one resolver. *Right:*
`class WidgetPolicy(InheritedDownward, OrgScopedModel)`, a `get_` selector
calling `.for_tenant(t).governing(actor.org).first()` — and the **list**
selector still `visible_to`: a list never widens upward.

### The app-map template

One table in the product's `architecture.md`, owned by the lead, edited only
by the lead, one row per app. A rung's brief carries the delta to this table.

| app | noun (aggregate) | depends_on | doors exposed | workflows owned | events emitted / consumed |
|---|---|---|---|---|---|
| `<label>` | `<Noun>` (+ children) | `core, accounts, …` | REST `/api/v1/<prefix>/` · MCP `<nouns>.*` · socket · webhook in/out | `<WorkflowName>` | `<app>.<noun>.<past-verb>` / consumed ones |

A worked example for a generic domain (never any real product):

| app | noun (aggregate) | depends_on | doors exposed | workflows owned | events emitted / consumed |
|---|---|---|---|---|---|
| `orders` | `Order` (+ `OrderLine`) | `core, accounts, events, workflows` | REST `/api/orders/` · MCP `orders.create`, `orders.cancel` · socket push | `FulfilOrder` | emits `orders.order.placed`, `orders.order.cancelled` |
| `invoices` | `Invoice` (+ `InvoiceLine`) | `core, accounts, events, workflows, orders` | REST `/api/v1/invoices/` · MCP `invoices.issue` · webhook out | `CollectInvoice` | emits `invoices.invoice.issued`, `invoices.invoice.paid`; consumes `orders.order.placed` |

The `orders` entry in `invoices.depends_on` is an ADR line: *context:* an
invoice is built from an order's lines · *decision:* `invoices` reads `orders`
through its selectors · *rejected:* duplicating the lines onto `Invoice` at
placement (two truths), an event carrying every line (a payload that grows
with the order) · *trigger to revisit:* `orders` needs to read `invoices` back.

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

```python
# the shape before the decorator existed — kept as the WRONG form; nothing on
# main looks like this any more (apps/example/services.py is @service today)
@transaction.atomic
def create_widget(*, tenant: Tenant, owner: User, name: str, notes: str = "") -> Widget: ...

# [A7a] the same service under the contract — @service opens the span, writes
# the AuditEntry, logs .called/.failed with the bound context
@service
def create_widget(*, tenant: Tenant, actor: Actor, name: str, notes: str = "") -> Widget:
    authz.require(actor, "widget.create", tenant)
    with transaction.atomic():
        ...
```

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

**C3 — A service calls another app's *services and selectors*, never its
models.** *Why:* the other app's invariants live in its services; writing its
table from outside is the sideways import with a worse failure mode.
*Enforced:* house rule **10** (the door side), **7** (the import side); review.

**C4 — A service reachable from a workflow, a webhook or an MCP tool is
idempotent, keyed on `idempotency_key`.** *Why:* Temporal retries activities,
webhook senders redeliver, agents repeat calls; a second identical call must
return the first result, not a second row. *Enforced:* criterion ("calling `X`
twice with the same key yields one row and the same return"); the REST side
is E7.

**C5 — Services raise `core.exceptions.*`; `HttpError`, `Http404` and status
codes never appear in `services.py` or `selectors.py`; the one mapper is
`config/api.py`.** *Why:* the service serves five doors; a status code is one
door's vocabulary. *Enforced:* house rule **14**. **[main]** `config/api.py`
maps `ValidationError` → 400, `IntegrityError` → 409, `PermissionDenied` →
403, `ObjectDoesNotExist` / `Http404` → 404, body
**`{detail, code, errors?, remedies?}`** — `code` is always present, and the
body is not composed there: `core.exceptions.wire_refusal` builds it and
`on_domain_error` sends it (§E9), so `core.exceptions` is the hierarchy *and*
the composer both doors share.

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

```python
# [A7a] apps/invoices/policies.py — the code half; the role comes from Membership.role
def can(actor: Actor, action: str, obj: object) -> bool:
    if action == "invoice.void":
        return (isinstance(obj, Invoice)
                and obj.status == Invoice.Status.ISSUED
                and actor.role in {"owner", "admin"})
    ...
```

**C8 — A reference handed to a service must have been reachable:
`may_be_named`, and the `# reach:` valve.** `require` answers "may you do this
kind of thing here"; the scoped manager answers "whose rows are these";
neither answers **"could you have got hold of *that* reference"** — the FK
handed over by id that resolves to a row in a branch the caller holds no
membership over. A `@service` that writes an `OrgScopedModel` passes each
FK-target keyword argument through **`core.authz.may_be_named(actor, obj)`**:
True only downward (the actor's hat covers `obj.organization`'s subtree — the
same direction `visible_to` reads in) or through the **link gate** (`obj`'s
model declared `InheritedDownward` and `obj.organization` is on the hat's
ancestor chain — §A5c); everything else is False, including everything
unresolved — no hat, no tenant, another tenant's row — and there is **no
`system` exemption** inside the helper. The refusal is `NotFound()`, never
`Forbidden`: not-there and not-yours are one answer on purpose (§E9). A call
site that genuinely acts tenant-wide — a platform workflow holding no hat —
writes a **`# reach: <reason>`** comment on the line it excuses: a sentence a
reviewer can disagree with, which the gate counts and prints — a backlog that
may shrink and never grow. *Enforced:* house rule **26** — AST over
`services.py`, gate-tier, ratcheted over the measured backlog; whether a
`# reach:` reason is a *good* one is review's and the surveyor's, a declared
`does_not_cover`. *Wrong:* `set_preference(recipient=recipient, ...)` writing
against whatever row the client's id resolved to. *Right:* the form in
`apps/core/authz.py`'s own docstring — `if not may_be_named(actor, recipient):
raise NotFound()` — or the recorded `# reach:` line.

**C9 — An org-scoped row that inherits its organization declares it:
`derive_org_from`.** Some rows do not *choose* their branch — a preference
belongs wherever its recipient belongs, a line wherever its order does. The
model says so (`derive_org_from = "<fk-name>"`, a `ClassVar` on
`core.models.OrgScopedModel`), and `clean()` then refuses a **final**
`organization` that disagrees with the FK-target's, on insert and on update
alike. *Why:* the class this closes is a write that derived the organization
from the *actor's hat* while the row it hangs off belongs somewhere else — the
row lands in a branch its own parent cannot see, silently, a leak in whichever
direction the mismatch went, and no read afterwards can tell you it happened.
It is an invariant on the row's own fields-by-reference, which is the kind of
rule `clean()` is for — D3 stands: a database constraint cannot reach across a
row to read the parent's column, and a service that remembers to check is a
service somebody will one day write without. *Enforced:* the landing gate runs
where a service calls `full_clean()` (house style:
`with as_invalid(): row.full_clean()` — conv §4), which is a **declared blind
spot**, with rule **26** the belt; the declaration itself is review's, placed
when the lead places the model. *Wrong:* `organization=actor.org` stamped on
a child row whose parent lives elsewhere. *Right:* the declaration, and an
`organization` left to agree with the target's.

## D · Models

**D1 — Every concrete model inherits `BaseModel`; everything a tenant owns
inherits `TenantScopedModel`; the pk is UUIDv7.** *Why:* time-sortable ids
index well and leak no count; the scoped base is what house rule 8 can see.
*Enforced:* house rules **2**, **8**. **[main]** `apps.core.models` ships both
bases, and the pk default is UUIDv7 today (`apps/core/models.py` via
`apps/core/ids.py`) — the ruling landed. Form: conv §2.

**D1a — An org-scoped model inherits `OrgScopedModel`, which is
`TenantScopedModel` plus an `organization` FK.** Uniqueness on one still names
`tenant` (a slug is unique per tenant, not per branch) unless the product means
"unique within this branch", which is a decision worth a comment. Services take
the acting organization from **`actor.org`** and never as a parameter — a
service with an `organization=` argument is a door that can write into a branch
it holds no membership over, which is the tenancy hole one level down.
*Enforced:* house rule **24** (the read); review (the write's shape). Form:
conv §2.

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

**D8 — A ledger declares itself: `append_only = True`; mistakes are
superseded, never edited.** A model whose rows are witnessed history — an
audit entry, a witnessed fact, an accrual, a stage-transition log — declares
`append_only: ClassVar[bool] = True` (`apps.core.models`;
`is_append_only` / `append_only_models` read the population off the registry;
`core.audit.AuditEntry` is the first member). A service may `.create()` a
member's rows; nothing anywhere updates or deletes one. **The correction
convention is a superseding row**: a wrong entry is answered by a new row that
names the row it supersedes (an FK or a recorded id) and states why — the
ledger then holds the mistake *and* the correction, which is what makes it
evidence rather than a table someone tidied. *Why:* the promise used to be a
rule about one model's *name*, and a promise about a name does not survive a
product; discovered off the registry, a product adds a member by declaring it
and the rule covers it in the same commit with no gate edit. A base class was
rejected (ADR core-6): MRO churn to buy a property the attribute already has.
*Enforced:* house rule **20**, generalized over the declaring population;
criterion (introspect shows no update or delete door for a member). Trigger:
first production deploy → DB-grant enforcement (revoke UPDATE/DELETE) as the
belt. *Wrong:* `entry.amount = corrected; entry.save()`. *Right:* a `record_*`
service creating the superseding row.

**D9 — Config a process consumes is versioned: create / revise / retire,
never edited in place.** A template, a policy, a rule set: `name` + `version`,
unique per `(tenant, name, version)`; `revise_*` writes a **new row at
`version + 1`**; `retire_*` moves `is_active` and nothing else; resolution
picks the latest active row; a retired version stays readable because every
row that ran under it points at it. **[main]** `apps/comms/models.py`
(`MessageTemplate`, `DeliveryPolicy`) is the worked shape and
`revise_template` / `retire_policy` in `apps/comms/services.py` the services.
*Why:* config edited in place rewrites history — every row that recorded "sent
under v2" now points at different words — and changes the rules under
processes mid-flight (D11 is that half). A shared versioned-config base class
is **deferred, with its trigger recorded** (the second template-side
consumer); the shape is doctrine now. *Enforced:* review + criterion
("revising yields a new row; rows that ran under the old version still render
it"). *Wrong:* `template.body = new_body; template.save()`. *Right:*
`revise_template(...)` → v+1.

**D10 — Immutable keys under renamable names.** A config row that a snapshot,
a ledger or another row will reference carries an immutable **`key`** slug,
separate from any display name; references — snapshots, event payloads,
foreign records — hold the key (plus the version where D9 applies), and the
display name is free to change without rewriting anybody's history. *Why:*
reference-by-display-name makes every rename either a migration of other
people's data or a silent break of it; reference-by-pk alone loses the
human-legible answer to "what was this sent under" months later. A model may
let one column serve both jobs — comms' `name` does — but then that column is
**immutable by contract** and a renamable label is a separate field added the
day somebody wants renames. *Enforced:* review (the lead names the key column
when placing a referenced config model); criterion ("renaming the config
changes no stored reference and breaks no replay"). *Wrong:* a snapshot
storing `policy="Gold tier escalation"` that a rename orphans. *Right:*
`key="gold-escalation"` immutable, `label` renamable, the snapshot holding
the key.

**D11 — A process judges against the snapshot it started under; moving to
current rules is an explicit service.** When a long-running process starts
under a policy, the policy's material content is **snapshotted into the run's
input** — **[main]** `apps/comms/types.py`: the run carries the *steps*, not
the policy id — and the run finishes under that snapshot; revising the policy
never reaches into a run already waiting (comms proved the semantics over the
wire; this line promotes them to doctrine). A run that *should* pick up the
new rules is moved by a **named, audited service that says so** — never by the
revision silently re-judging in-flight work. *Why:* judging in-flight work
against the live row turns every config edit into an unreviewed bulk action
over everything currently waiting — invisible in the diff, unanswerable in
the audit trail; the snapshot makes "which rules was this decided under" a
recorded fact. It is also what rule 9 already requires: a workflow that
re-read the live row would have history that no longer explains its own
decisions. *Enforced:* house rule **9** (the workflow half); criterion ("a
policy revised mid-wait does not change the waiting run; the mover service
exists and is audited"). *Wrong:* an activity re-reading the policy row at
each step. *Right:* the plan in the run's input, and an explicit `move_*`
service for the deliberate case.

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

**E3 — Events are `<app>.<noun>.<past-verb>`, declared in the app's
`events.py`, carry `v` in the payload, and are emitted only from services,
inside the transaction; payloads are the `Out` schema.** *Why:* a name
declared once is greppable and reviewable; a version lets a subscriber survive
the next field; an emit from anywhere but a service is a write nobody audited.
*Enforced:* house rule **16** (name + declaration); **4** (no signal emits);
criterion (the event row exists after the write, with `v`). Form: conv §8.
*Wrong:* `emit("OrderCreated", ...)` from a `post_save`. *Right:* **[A7a]**
`events.py`: `ORDER_PLACED = "orders.order.placed"  # v=1`, and in the service
`emit(name=ORDER_PLACED, tenant=tenant, payload={"v": 1,
**OrderOut.from_orm(order).model_dump(mode="json")}, actor=actor)`.

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
`{detail, code, errors?, remedies?}` — additive on a body that already
carried the first three keys — and both mappers call it: `config/api.py`
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

**G2 — What every service, door and workflow carries.** Every door binds
context (`request_id`, `session_id`, `tenant_id`, `user_id`, `correlation_id`,
`causation_id`, `trace_id`) **before** calling a service (**[A7a]**
`core.context`); `@service` opens a span `<app>.<service>`, logs `.called` /
`.failed` with the bound context and writes the **[A7a]**
`core.audit.AuditEntry` — actor (`actor_user`, `actor_token`, `actor_kind` =
human|agent|system), action (the service name), object type + id, door
(rest|mcp|socket|workflow|webhook|admin|shell), outcome, redacted input per
`LOG_KEYS`, and the three ids. `correlation_id` is minted at the door and
never below it; `causation_id` is the immediate parent; both ride every
`Event`, `WorkflowRun`, `Delivery` and `AuditEntry`, the Temporal memo and
`X-Correlation-Id`; `traceparent` propagates into outbound webhook headers.
`AuditEntry` is append-only — the first member of the declared `append_only`
population (§D8) — no update or delete path anywhere. *Enforced:*
house rule **20**; **13** (the decorator is what writes it). *Wrong:* a
service that mints a `correlation_id`; an admin action that updates an
`AuditEntry`. *Right:* the door binds, the service inherits.

**G3 — What the lead specifies per rung.** For every rung: *which events* it
emits (names from `events.py`, with `v`); *which audit actions* must exist
afterwards (service names and expected `door` values — a rung touching MCP
produces `door=mcp` rows); *which metrics matter* (route latency/status for
the new routes, service count/duration/failures, workflow/activity outcomes,
outbox lag, delivery failures) and which one the criterion reads. The shape of
such a criterion: "an `AuditEntry` with `action=issue_invoice, door=rest`
exists for the created row, and none exists for the refused one."

## H · Platform decisions the lead applies

From "The platform the template ships" in `architecture.md`. When a rung
touches the area, the rule is applied and cited; none is re-argued.

- **Email** — sent from a workflow activity (retries), never from a service or
  a route; Mailpit in compose for dev; a provider via `connections` in
  production.
- **Invitations & tenant lifecycle** — `core.services.invite_member(email,
  tenant, role)`; `create_tenant / suspend_tenant / close_tenant` are
  services; allauth signup joins the membership.
- **Rate limiting** — ninja throttling per token and per tenant, defaults in
  settings; MCP tools share the same limiter; a new door names its limit.
- **CORS / CSRF / CSP** — `django-cors-headers` with an env allow-list;
  session + CSRF for a same-site front end, token auth for everything else;
  `django-csp` in production settings; a route is never `@csrf_exempt`.
- **MCP auth** — bearer tokens now; the MCP OAuth 2.1 flow is the recorded
  upgrade when a third-party client must connect; sockets gain the same
  bearer path.
- **File storage** — `apps/files` (ADR files-2, which supersedes the
  django-storages design that used to sit here): the **boto3-backed storage
  seam** — `apps/files/storage.py` is the one module under `apps/` that
  imports boto3, names a bucket setting, signs a URL or reads an object's
  bytes (MinIO in dev, S3 in production, one seam; **not**
  django-storages) — keys immutable per version, shaped
  `t/<tenant_pk>/f/<file_pk>/v/<n>` (pks only, never tenant slugs or
  filenames); bytes never transit Django (presigned URLs both directions,
  TTLs declared in settings); uploads two-phase through services, and
  "replace" is a new `FileVersion`, never an overwrite.
- **Tenant settings & flags** — `Tenant.settings` JSON (schema-validated) +
  `core.flags.is_enabled(tenant, name)`; no third-party flag service; a flag
  is named in the rung that adds it and removed by a named later rung.
- **Events** — `v` on every payload; the outbox is retained;
  `manage.py replay_events` is the recovery path, so a consumer must be
  replay-safe.
- **Erasure & retention** — `accounts.services.erase_user`; audit/outbox
  archival is a dated residual with a trigger in the product's queue.
- **Seed, backup, restore** — `manage.py seed` is dev data only (the method
  still drives from zero); `scripts/backup.sh`, `scripts/restore_drill.sh`
  exist so the restore tripwire has something to fire.
- **Runtime** — `/healthz` (liveness) and `/readyz` (db, redis, temporal); a
  rung that adds a runtime dependency adds it to `/readyz`.
- **CI** — GitHub Actions runs `./scripts/check.sh` (full) on every PR; the
  gate is the only CI; a rung never adds a second pipeline.
- **i18n** — off by default (`USE_I18N=False`); `Tenant.timezone` / `locale`
  are present for display; a product turns i18n on as a recorded decision.
- **Template updates** — no sync tooling yet: `TEMPLATE_VERSION` +
  `CHANGELOG.md`; products cherry-pick system-layer commits.

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

### The ADR line

```
ADR <app>-<n> · <date> · context: <one sentence> · decision: <one sentence> ·
rejected: <alt 1> (<why>), <alt 2> (<why>) · trigger to revisit: <the observable event>
```

It lives in the product's `architecture.md` under the app map. An ADR without
a rejected alternative is a note, not a decision; one without a trigger is a
decision nobody can reopen honestly.

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

## J · Rejected shapes

Each is settled in `architecture.md` ("Rejected, and why", and the stack
table); a brief that proposes one is returned, not argued.

- **Fat models only** — logic scatters into 2,000-line models and signals; an
  explicit services layer is the one that can be house-ruled (rules **4**,
  **13**).
- **Signals for events** — logic nobody finds; `emit()` from the service,
  inside the transaction (rule **4**; §E3).
- **DRF beside ninja** — two API layers drift with a countdown; ninja's
  schemas serve every door (stack table, "API layer").
- **Celery (+ beat, + an FSM on a model)** — a queue with retries; state,
  resumption and "where is this process" rebuilt per product; Temporal
  replaces it rather than joining it (stack table, "Background work &
  workflows").
- **Schema-per-tenant** — not a template option; a heavily-considered
  exception only for a named business requirement (stack table, "Tenancy").
- **Authorization only at the door** — a new door forgets the check; a
  service cannot be called without it (§C7; rule **13**).
- **`dict` across doors** — no contract, no OpenAPI, no parity check; one
  schema per shape (§E1; rule **16**; conv §13).
- **Random workflow ids** — a retried service starts a second run;
  `workflow_id()` (rule **18**; `apps.workflows.services` on main refuses
  anything else).
- **Inbound webhooks processed inline** — a slow or failing handler loses the
  event; verify → store → workflow (stack table, "Webhooks & events").
- **SQLite anywhere** — hides the Postgres behaviour the product depends on
  ("Rejected, and why").
