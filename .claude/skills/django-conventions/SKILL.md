---
name: django-conventions
description: >-
  Load before writing or changing any Python in apps/, config/ or tests — every
  development rung, every fix, every migration. It exists because agents emit
  plausible-but-wrong Django: outdated APIs, logic hidden in signals, N+1 queries,
  guessed schemas, hand-made merge migrations, I/O inside a workflow, a door that writes
  to a model. Each rule below shows the wrong form and the right one, for Django 5.2 /
  django-ninja / Temporal / Channels / Python 3.12 as this repo pins them. Do NOT use it
  to decide what gets built (that is the PM's), to write acceptance criteria (the
  engineering lead's), or to judge whether a rung is done (the field test's). It is how
  to write the code, not whether to.
---

# Django conventions for this repository

You are writing into a template shaped around **parallel agents sharing one
schema**, with **one set of services behind several doors** — REST, MCP,
sockets, webhooks, workflows. Most rules here exist because something about
that collides: a guessed model, a migration made outside its rung, a write in a
signal, a door that bypasses the service, a workflow that reads the clock.

**Before you write a line:** `uv run python manage.py introspect` — the real
models, fields, relations, routes, tools, consumers, workflows, activities and
non-secret settings as JSON. The schema is read, never guessed.

## 1 · Layout, discovery, imports

```
config/settings/{base,local,test,production}.py   # split by environment; no single settings.py
config/api.py · asgi.py · temporal.py · mcp.py    # the mounts — they DISCOVER apps/*; a rung never edits them
apps/<name>/                                      # every app; its AppConfig.name is "apps.<name>"
  apps.py · models.py · services.py · selectors.py · schemas.py · types.py · api.py · mcp.py
  workflows.py · activities.py · consumers.py · admin.py · migrations/ · max_migration.txt · tests/
apps/core/ accounts/   # BaseModel · Tenant · Organization · Membership · TenantScopedModel · OrgScopedModel ·
                       #   ScopedQuerySet (for_tenant + visible_to) · TenantMiddleware ·
                       #   TenantRequest · principal(ctx) · introspect · the User · API_AUTH / ApiTokenAuth · tokens
apps/workflows/        # start_workflow / start_workflow_on_commit · workflow_id() · the tenant-context interceptor ·
                       #   current_tenant() / current_user_id() / workflow_context() · WorkflowRun · the worker
apps/example/          # one ORG-scoped model end to end: Widget, services, schemas, a router under PREFIX = "widgets"
apps/events/ connections/ realtime/   # emit()/Outbox/deliveries · Connection + httpx factory · the one consumer per
                                      #   tenant group — the spine apps, on main; read them, do not re-derive them
quality/rules.yaml · .env.example     # the house rules (canary + blind spot each), run by quality/gate.py · EVERY variable settings reads
```

- **Registration is by discovery, never by editing `config/`.** Drop a file
  with the conventional name and the mount finds it: `api.py` exposes
  `router`; `mcp.py` exposes `register(server)`; `consumers.py` exposes
  `websocket_urlpatterns`; `workflows.py` exposes `WORKFLOWS: list[type]`;
  `activities.py` exposes `ACTIVITIES: list[Callable]`. A rung that edits
  `config/` to register something touches a shared file and collides.
- Import path is `apps.<name>` (`from apps.example.models import Order`, never
  `from example.models …`); `AppConfig.name = "apps.<name>"`.
- Domain apps never import each other sideways; `core` imports nothing above
  it; nothing imports `events` except to `emit`. `import-linter` enforces the
  fixed layer contract (`core` ← `accounts` ← platform ← domain) in `--fast`;
  what an app may import beyond that it declares itself (`depends_on`, below),
  and house rule 7 holds it to that. A needed cross-app call is a lead
  decision to record, not an import to sneak in.

### Registering an app

```python
# apps/orders/apps.py — the whole registration; nothing else is edited
class OrdersConfig(AppConfig):
    name = "apps.orders"
    depends_on = ("core", "accounts", "events")   # what this app may import; rule 7 reads it
```

- **`INSTALLED_APPS` is derived from `apps/*/apps.py`** — every package under
  `apps/` with an `AppConfig` is installed, in dependency order. Creating the
  package *is* registering it.
- An `AppConfig` declares `depends_on`: the app labels it may import from.
  `core` depends on nothing; a domain app names `core`, `accounts` and the spine
  apps it uses (`events` to `emit`, `workflows` to start a run). A sideways
  import between two domain apps is refused unless the lead has recorded it.
- **Never edit `config/` or `pyproject.toml` to register anything** — not
  `INSTALLED_APPS`, not a router, not a worker list, not an import-linter
  contract. Every one of those is read from the app. (Ruled after an
  alignment review found registration was hand-listed;
  `config/settings/discovery.py` derives `INSTALLED_APPS` today.)
- Settings come from the environment; a new variable lands in `.env.example`
  with a safe local default in the same commit. `DJANGO_SETTINGS_MODULE`:
  `config.settings.local` for `manage.py`, `.test` for pytest, `.production`
  for `check --deploy`.
- Dependencies live in `pyproject.toml` via `uv add` / `uv sync` / `uv run …`;
  never `pip install`, never `requirements.txt`.

## 2 · Models

**Every concrete model inherits `apps.core.models.BaseModel`** (UUID pk,
`created_at`, `updated_at`) — directly for the few things no tenant owns, or
through `TenantScopedModel` for everything a tenant owns, which in a product is
nearly everything. House rule; the canary fires on a bare `models.Model`.

```python
class Order(models.Model): id = models.AutoField(primary_key=True)   # wrong
class Order(TenantScopedModel):                                      # right — from apps.core.models
    number = models.CharField(max_length=32)
    total = models.DecimalField(max_digits=12, decimal_places=2)
```

- **Do not edit timestamps by hand.** `updated_at` is `auto_now`; a test that
  needs a specific time uses `time_machine` or `QuerySet.update()`.
- **Invariants as `Meta.constraints`, not `clean()`**, wherever the database
  can hold them — `CheckConstraint(condition=Q(total__gte=0), name=…)`,
  `UniqueConstraint(fields=["tenant", "number"], name=…)`. `clean()` runs only
  when something calls it; a constraint runs always.
- Models carry **invariants and derived properties**, not workflows: a
  `@property` over its own fields belongs here; anything that writes another
  row belongs in `services.py`; anything that waits or retries, `workflows.py`.
- Choices are `TextChoices`/`IntegerChoices` classes on the model, never bare
  tuples. `__str__` returns something a human can read in admin and logs.

### Tenancy — ON by default; a product opts out

One shape: **shared schema + tenant FK, read through a scoped manager, enforced
by house rule 8.** `apps.core` ships `Tenant`, `Membership` (user × tenant ×
organization × role), the abstract `TenantScopedModel(BaseModel)` with a `tenant` FK, a
`ScopedQuerySet.for_tenant(tenant)` manager, and `TenantMiddleware`, which sets
`request.tenant` from the user's membership (the default one, or the one an
`X-Tenant: <slug>` header names, if the user belongs to it). **No membership →
`request.tenant = None` and every scoped read returns nothing. Fails closed; no
superuser exemption.**

```python
# wrong — a bare manager on a scoped model; rule 8 refuses this in api, services, activities, tools, consumers, config
orders = Order.objects.filter(status=Order.Status.OPEN)
# right — in a door: the request's tenant; in a service: an explicit keyword argument, never a global
orders = Order.objects.for_tenant(request.tenant).filter(status=Order.Status.OPEN)
def create_order(*, tenant: Tenant, actor: Actor, customer: Customer, lines: list[LineIn]) -> Order: ...
```

- Every product model a tenant owns inherits `TenantScopedModel`; uniqueness
  is per tenant (`tenant` in the constraint).
- **Every read in a door or a service is `Model.objects.for_tenant(...)`.**
  The bare manager is for tests (set-up and proving isolation) and migrations.
- Services take `tenant` as a keyword argument; routes pass `request.tenant`
  (type the request as `apps.core.requests.TenantRequest`), MCP tools
  `principal(ctx).tenant` (§9), activities the tenant restored from workflow
  context (`workflow_context()`, §7). Nothing reads it from thread-local state.
- `Membership` is the only source of who belongs where; roles within a tenant
  are fields on it, not on `User`.
- Every door test that lists or fetches a scoped model has a sibling proving a
  second tenant's rows are absent — the test that cannot pass vacuously.

**Opting out** is recorded once, in the product's `architecture.md`, with the
reason: models inherit `BaseModel`, `TenantMiddleware` comes out, rule 8 is
`enabled: false`. No half-opt-out; schema-per-tenant is not a template option.

### Hierarchy — the tenant is a tree, and reads have two halves

Every tenant owns a tree of `core.Organization` — a **materialized path** of
fixed-width base36 segments (`0000`, `0000.0001`, …), so "everything under this
node" is one indexed prefix scan and never a recursion. `create_tenant` makes
the **root**; a flat product is a depth-one tree and pays nothing.

**A row one *part* of the tenant owns inherits `OrgScopedModel`** (which is
`TenantScopedModel` plus an `organization` FK). Whether a model is org-scoped or
merely tenant-scoped is the architect's call, made in the app map — see
`django-architect` § A5. If you are writing the model and it has not been
decided, ask; do not guess downward.

```python
# wrong — half a read: this hands a sub-seller the whole tenant. Rule 24 refuses it.
rows = Deal.objects.for_tenant(tenant).filter(status="open")

# right — both halves, in this order, every time
rows = Deal.objects.for_tenant(tenant).visible_to(actor_or_org).filter(status="open")
```

- **`for_tenant` answers "whose data"; `visible_to` answers "which part of their
  network".** Both fail closed: `for_tenant(None)` and `visible_to(None)` each
  return nothing, so an unresolved tenant or an unresolved hat reads an empty
  table rather than the table. There is no superuser exemption at either level.
- **Visibility flows down only.** A seller sees its own rows and its
  sub-sellers'; never its parent's, never a sibling's. Upward or sideways is a
  named policy with a recorded reason, never a wider `visible_to`.
- `visible_to` takes an `Organization`, or anything carrying one on `.org` — an
  `Actor`, an MCP `Principal`. Selectors take `org=` and pass it through; a
  selector that takes only `tenant` on an org-scoped model is the violation
  house rule 24 exists for.

**The acting hat.** `X-Org: <slug>`, resolved **after** the tenant by
`core.middleware.resolve_org` — the one function the HTTP door, the bearer-token
auth, the socket middleware and the MCP mount all call, which is what makes the
four doors answer with the same rows for the same header. It resolves to a node
the user holds a membership **on or above**, or to `None`; the default is their
default membership's own node. It is revalidated every request, from rows.

```python
# right — the door passes what the middleware resolved; nothing reads it from a global
rows = list_deals(tenant=request.tenant, org=request.org)          # REST
rows = list_deals(tenant=acting.tenant, org=acting.org)            # MCP tool
tenant, user_id, org = workflow_context()                          # activity
```

**Writes take the hat from the actor, never from an argument.**

```python
# wrong — a caller that can name an organization can write into one it has no membership over
def create_deal(*, tenant: Tenant, actor: Actor, organization: Organization, name: str) -> Deal: ...

# right — the hat the door resolved, refused when there is none
def create_deal(*, tenant: Tenant, actor: Actor, name: str) -> Deal:
    require(actor, "deal.create")
    if actor.org is None:
        raise Invalid({"organization": ["This request resolved no acting organization."]})
    ...
```

**The escalation wall.** Memberships are person × tenant × org × role, and a
role is granted only through `core.services.add_membership` / `set_role`, which
refuse two things: a grant **outside the granter's subtree**, and a grant
**above the granter's own effective role**. Pass the granting `actor`; that is
what turns the wall on.

```python
# wrong — the wall is skipped, and an admin has just made an owner
Membership.objects.create(user=user, tenant=tenant, organization=branch, role="owner")

# right — refused with Forbidden when the granter is only an admin, or is elsewhere in the tree
add_membership(user=user, tenant=tenant, organization=branch, role="admin", actor=acting)
```

**Effective role** is `core.authz.effective_role(user, tenant, org)`: the best
role among the memberships whose organization is that node or an ancestor of it.
Roles inherit downwards; nothing inherits up or sideways.

**Re-parenting is a service plus a workflow** — `move_organization` authorizes
(ancestor-admin of **both** the old and the new parent) and starts a durable
run; `apply_organization_move` takes `select_for_update` over the whole subtree
and rewrites its paths in batches. Never write `Organization.path` or `.parent`
anywhere else: house rule 24 refuses it, and a path edited by hand is a subtree
that silently vanishes from every read in the product.

Every audit row carries `acting_org`, and the acting org rides on the workflow's
Temporal headers, so "which hat was this done under" is answerable months later.

### Inherited config — `governing()`, and the model that declares it

Configuration a parent sets for its descendants — a policy, a template choice,
a quiet-hours window — is resolved **upward**, and only on a model that has
said so by declaring `InheritedDownward` (`apps.core.models`):

```python
# wrong — resolving "which policy governs me" by widening a list read, or by
# walking parents in Python with one query per level
policies = WidgetPolicy.objects.for_tenant(tenant).filter(...)   # ...then climb

# right — the model declares it; resolution is one query, nearest ancestor first
from apps.core.models import InheritedDownward, OrgScopedModel

class WidgetPolicy(InheritedDownward, OrgScopedModel): ...

policy = WidgetPolicy.objects.for_tenant(tenant).governing(actor.org).first()
```

- **Upward config resolution, never upward visibility.** `governing(org)`
  returns the rows on `org`'s ancestor chain, nearest first — the chain is
  decomposed out of `org.path` in Python (`ancestor_paths`), so it costs no
  extra query. `visible_to` is untouched: a branch may *resolve* the policy
  that governs it and still cannot *list* its parent's rows. A `get_` selector
  resolves with `governing()`; every `list_` selector stays `visible_to` — a
  list never widens upward.
- `governing()` on a model that has not declared `InheritedDownward` raises
  `TypeError` naming the marker; `governing(None)` returns nothing — the same
  fail-closed shape as `for_tenant(None)` and `visible_to(None)`.
- Whether a model is inherited-downward is the architect's call
  (`django-architect` §A5c), made in the app map. If it has not been decided,
  ask; do not declare it to make a read compile.

### Reachability — `may_be_named`, and the `# reach:` grammar

A service takes `recipient=`, `policy=`, `parent=`; the caller hands an id;
the id resolves to a row in a branch the caller holds no membership over —
and nothing in tenancy or in `require` catches it, because the row *is* in
the tenant and the policy is about the verb. `core.authz.may_be_named(actor,
obj)` answers that third question, and house rule 26 reads every FK-target
keyword argument of a `@service` that writes an `OrgScopedModel`:

```python
# wrong — the write lands against whatever row the client's id resolved to
@service
def set_preference(*, tenant: Tenant, actor: Actor, recipient: Recipient, ...) -> ChannelPreference:
    require(actor, "preference.set")
    ...

# right — reachability checked, refused as not_found (not-there ≡ not-yours)
    require(actor, "preference.set")
    if not may_be_named(actor, recipient):
        raise NotFound()

# right — the recorded valve, for a caller that genuinely holds no hat
    # reach: the dispatch workflow acts tenant-wide and holds no hat
    services.record_delivery(recipient=recipient, ...)
```

- True two ways only: **downward** (the hat covers `obj.organization`'s
  subtree — the direction `visible_to` reads in), or the **link gate** (the
  model declared `InheritedDownward` and `obj.organization` is on the hat's
  ancestor chain — a branch may *name* the policy its parent set for it).
  Everything else is False, including everything unresolved; there is no
  `system` exemption.
- Refuse with `NotFound()`, never `Forbidden` — a refusal that told
  not-there from not-yours apart would confirm the row exists.
- The `# reach:` comment is not a disable: it sits on the line it excuses,
  the gate counts and prints every one, and the backlog may shrink and never
  grow. Write the reason as a sentence a reviewer can disagree with.

### Where a derived row lands — `derive_org_from`

An org-scoped row that inherits its branch from something it points at says
so, and the landing gate in `OrgScopedModel.clean()` then refuses a final
`organization` that disagrees with the target's, on insert and update alike:

```python
# wrong — the org stamped from the acting hat while the parent lives elsewhere;
# the row lands in a branch its own parent cannot see, silently
entry = WidgetEntry(tenant=tenant, organization=actor.org, widget=widget, ...)

# right — the model declares where its organization comes from
# (the marked worked example: apps/example/models.py, WidgetEntry)
class WidgetEntry(OrgScopedModel):
    derive_org_from = "widget"
```

The gate runs where the service calls `full_clean()` — which the house style
already does (`with as_invalid(): row.full_clean()`, §4) — and that is a
declared blind spot, not a closed question; rule 26 is the belt.

**A service never trusts that the caller resolved its object correctly.** A
service that takes a scoped-model instance was handed a row somebody else
fetched. Today every door fetches through `for_tenant(request.tenant)` (rule
8), which is why the pattern holds — but a policy predicate that inspects the
object, or any future non-door caller resolving by pk, stands outside that
fence. Either re-assert the boundary in the service (`obj.tenant_id ==
tenant.pk`, refuse with `NotFound`), or state in the service's docstring that
only door fetches reach it. Silence is the wrong third option.

### Ledgers and config — append-only, versioned, snapshotted

**A ledger declares itself.** Rows that are witnessed history — audit
entries, witnessed facts, accruals, transition logs — set
`append_only = True` (discovered off the registry by
`apps.core.models.append_only_models`; `core.audit.AuditEntry` is the first
member). House rule 20 covers every declaring model: services `.create()`,
nothing updates or deletes.

```python
# wrong — history edited in place
entry.amount = corrected
entry.save()

# right — the declaration, and a correction as a new row naming what it supersedes
class WidgetEntry(OrgScopedModel):
    append_only = True
```

**Config a process consumes is versioned — create / revise / retire, never
edited in place.** `name` + `version`, unique per `(tenant, name, version)`;
`revise_*` writes a new row at `version + 1`; `retire_*` moves `is_active`
and nothing else; a retired version stays readable because rows that ran
under it point at it. `apps/comms/models.py` (`MessageTemplate`,
`DeliveryPolicy`) and `revise_template` / `retire_policy` in
`apps/comms/services.py` are the worked shape. There is no shared base class
yet — the shape is the doctrine, the base class is deferred with a recorded
trigger.

**References hold immutable keys, not display names.** A config row that a
snapshot, a ledger or another row will reference carries an immutable `key`
slug separate from anything renamable; references store the key (and the
version). A single column may serve both jobs — comms' `name` does — but then
it is immutable by contract, and a renamable label is a separate field.

**A process judges against the snapshot it started under.** A run's input
carries the policy's material content (`apps/comms/types.py`: the run holds
the *steps*, not the policy id) and the run finishes under it — revising a
policy never reaches into a run mid-wait, and a workflow that re-read the
live row would violate rule 9 anyway. Moving in-flight work to current rules
is an explicit, audited service that says so — never a side effect of the
revision.

## 3 · The user

```python
from django.contrib.auth.models import User                                     # wrong — never; house rule with a canary
owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)   # right, in models
User = get_user_model()                                                         # right, once apps are loaded
```
`accounts.User`: email as the identifier, no product fields — a product adds a
profile model in its own app.

## 4 · Services own writes; every door calls them

Business logic lives in `apps/<name>/services.py`; read-only composition that
several doors share lives in `selectors.py`. **Every door — API route, MCP
tool, socket consumer, activity, webhook receiver — imports services,
selectors and schemas; never `models` for a write, never `.save()` /
`.delete()` / `.create()` directly.** House rule 10, canaried.

```python
# wrong — a write in a route, and a side effect in a signal nobody will find
def create_order(request, body: OrderIn): return Order.objects.create(tenant=request.tenant, **body.dict())
@receiver(post_save, sender=Order)
def send_receipt(sender, instance, created, **kwargs): ...

# right — one service: @service, keyword-only, atomic, emits its event inside the transaction, returns the object
from django.db import transaction

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.service import service
from apps.events.services import emit
from apps.orders.events import ORDER_CREATED           # rule 16: the name is a constant, never a literal here

@service
def create_order(*, tenant: Tenant, actor: Actor, customer: Customer, lines: list[LineIn]) -> Order:
    require(actor, "order.create")                     # rule 13: a service that resolves an actor authorizes
    with transaction.atomic():
        order = Order.objects.create(tenant=tenant, customer=customer, placed_by=actor.user, total=sum(l.amount for l in lines))
        OrderLine.objects.bulk_create([OrderLine(order=order, **l.model_dump()) for l in lines])
        emit(name=ORDER_CREATED, tenant=tenant, payload=OrderOut.from_orm(order).model_dump(mode="json"), actor=actor)
    return order
```

- **Keyword-only arguments**, typed, **return the object** (or a small typed
  result); **`transaction.atomic()` whenever more than one row is touched**,
  with the `emit()` inside it (§8).
- **No business logic in signals — no `signals.py` at all** unless the lead
  rules otherwise and records why. House rule with a canary. If you reach for
  `post_save` you want a service; if you reach for it to notify, `emit()`.
- Something that waits or retries is started with
  `start_workflow_on_commit(...)` (§7), which registers the start on the
  service's transaction; the service never calls the external system.
- Validation at the edge (the schema) or in the service, not both. Services
  raise domain exceptions; doors map them. Tests call services for set-up;
  doors are tested through the door.

### The valves — the cheap way out, and where each one has to be written

A house-rule finding on a service usually has two remedies, and violation
messages tend to name only the expensive one. Rule 16's message, for instance,
says "add the verb to `service_verbs` in rules.yaml"
(`quality/checks.py:1576-1578`) — which widens the lexicon for the whole
template, forever, to excuse one function. The two cheap roads it does not
mention: a **counted override** on the line, and, when the thing is not a
capability at all, the **underscore-prefix road** — rule 16 skips a
`services.py` function whose name starts with `_` outright
(`quality/checks.py:1569-1570`, "a private helper is the inside of a service,
not a capability"). A private helper called only by services in the same module
should be `_`-prefixed and is then not the rule's subject at all. Reach for the
lexicon only when the verb genuinely names something a product DOES.

Every valve is a comment somebody wrote and a reviewer can disagree with. Four
of the five are **counted and printed** (a suppressed finding is never a silent
one) and need **≥ 12 characters of reason** — a bare marker becomes its own
finding rather than an off switch. What differs, and what costs merge cycles to
rediscover, is **where each has to sit**:

| Valve | Whose | Where it counts | Where it is invisible |
|---|---|---|---|
| `# rule-<id>: <reason>` | any rule, the universal override (`quality/gate.py:70`, `override_at` `:91-110`) | on the **flagged line itself**, or in the **contiguous `#` block directly above it** | anywhere a non-comment line intervenes. Rule 13 reports at the `def` line, so a valve **above the `@service` decorator is invisible** — the decorator breaks the block — while one **between the decorator and `def` counts** |
| `# authz: <reason>` | rule 13, a `@service` taking `actor` that never calls `authz.require` (`quality/checks.py:1221`; rule 41's refusal census reads it the same way, `:5978-5997`) | **anywhere inside the function**, `def` line through its last line (the check reads `ast.get_source_segment` of the `FunctionDef`) | above the decorator, **and** between the decorator and `def` — `FunctionDef.lineno` is the `def` line, so neither is in the segment |
| `# reach: <reason>` | rule 26, an org-scoped parameter not passed through `may_be_named` (`quality/checks.py:3359`, `_reach_reason` `:3391-3410`) | on the **parameter's own line** (or the block above it) for that one parameter; or, for the whole function, on the **`def` line or the first decorator line** — either with its contiguous block above (`:3536-3537`) | anywhere else |
| `# door: <reason>` | rule 42 — and since R6 (P15) the valve carries **two claims, told apart by the finding class it suppresses**: *no door reaches this service* (the original), or *only this tree's own hands reach it* (a service called by management commands/admin only); write the reason to say WHICH (`quality/checks.py:5215`, `_door_reason` `:5231-5248`) | on the **`def` line or the first decorator line**, each with its contiguous block above (`:5453-5454`) | anywhere else |
| `# role-bound: <reason>` | rule 29, a role value written without bounding it against the granter's ceiling (`quality/checks.py:2018`, `_role_bound_reason` `:2022`) | on the **`def` line**, or on **any parameter's line**, each with its contiguous block above (`:2114-2118`) | anywhere else |

Three of the five read the decorator line and two do not, which is the whole
reason this table exists: if a valve you wrote did not take, check its position
before you conclude the rule is broken.

**`# authz:` is the exception to the counting, and knowing that is the point.**
The other four carry a 12-character reason floor
(`quality/gate.py:71`, `quality/checks.py:2019`, `:3361`, `:5216`), count their
uses (`reach_overrides`, `door_overrides`, `role_bound_comments`, and the
gate's own override census) and turn a bare marker into a finding of its own.
Rule 13's `# authz:` does neither: `quality/checks.py:1221` is a substring test,
so a bare `# authz:` with no sentence after it silently suppresses. Write the
sentence anyway. It is the only thing standing between "this service does not
authorize" and nobody ever asking why again.

### Refusals — the three-move grammar, spoken once

A refusal is a `code` (what a client branches on), a **`fact`** (what is
*true*, said to whoever is refused), and **`remedies`** (what they can *do*,
structured). All of it is declared at import, beside the class that raises it,
and `core.exceptions.register_refusal` refuses a malformed declaration at that
same import — the strongest tier there is:

```python
# wrong — an unregistered code; DomainError.__init_subclass__ refuses this at import
class QuotaExceeded(DomainError):
    code = "quota_exceeded"

# wrong — remedies as prose; register_refusal raises ValueError at import
register_refusal(code="quota_exceeded", boundary="service",
                 remedy="...", fact="...", remedies=("upgrade your plan",))

# right — all four parts, the remedies structured, declared before the class body
from apps.core.exceptions import DomainError, Remedy, register_refusal

register_refusal(
    code="quota_exceeded",
    boundary="service",
    remedy="Raise the tenant's quota row or shed the batch.",   # internal; never on the wire
    fact="This tenant's quota is spent; the request was not partially applied.",
    remedies=(Remedy("See your current usage", "introspect:refusals"),),
)

class QuotaExceeded(DomainError):
    code = "quota_exceeded"
    default_detail = "Quota exceeded."
```

- **One composer.** `core.exceptions.wire_refusal(exc)` builds
  `{detail, code, errors?, remedies?}`; `config/api.py` sends it as JSON and
  `core.mcp.tool_call` renders it through `refusal_message` as one line, code
  first. Never catch a domain exception in a route or a tool to shape your own
  body — that is the fourth copy of a rule with one home, and it is how the
  screen and the assistant come to offer different ways out.
- The internal `remedy` prose is for whoever is holding the refusal and never
  reaches a client; the `fact` is what the registry says the *code* means, and
  stays off the wire too. What travels is `detail`, `code`, `errors` when the
  refusal names fields, and `remedies` as `{label, destination}` objects.
- `destination` is an opaque `<kind>:<name>` token (`header:X-Org`,
  `docs:openapi`, `introspect:refusals`) — the template validates nothing
  about it; a product with a navigation manifest grows that rule itself.
- A raise site that knows better than the registry passes contextual
  `remedies=` (typed — `Remedy` tuples, refused otherwise), which **replaces**
  the default list rather than appending to it.
- Not-there and not-yours are one answer, deliberately: refuse an unreachable
  reference with `NotFound()`, never `Forbidden` (§2, reachability).

## 5 · Queries

```python
for o in Order.objects.all(): print(o.customer.name, len(o.lines.all()))      # wrong — N+1, unbounded, len() to count
orders = (Order.objects.for_tenant(tenant).filter(status=Order.Status.OPEN)  # right
          .select_related("customer").prefetch_related("lines").order_by("-created_at"))
if orders.exists(): ...; count = orders.count()
```

- `select_related` for FK/O2O reads; `prefetch_related` for M2M and reverse
  relations. A loop that touches a relation without one of them is an N+1.
- **Lists are always paginated** (`@paginate`, §6), and **every list route has
  a query pin**: `django_assert_num_queries(n)` at seeded scale × k, n from a
  measurement, not a guess. The pin is what makes the N+1 fail the gate.
- `.exists()` / `.count()` over `len()` / `bool()`; `.only()` / `.values()`
  when a list needs three columns; `.iterator(chunk_size=…)` to walk a table;
  `F()` for updates that should not race; `select_for_update()` inside
  `atomic()` when a service reads then writes the same row. **No raw SQL
  without a comment saying why**; parameterised, never formatted.

## 6 · API — django-ninja

One `Router` per app in `apps/<x>/api.py`, discovered by `config/api.py` and
mounted under the **version segment `config/urls.py` owns** — today
`API_PREFIX = "api/v1/"` — at **`/api/v1/<label>/`, unless the module names
`PREFIX`** — then at `/api/v1/<PREFIX>/` (the example app names
`PREFIX = "widgets"`, so its routes are at `/api/v1/widgets/`: a URL says what
the resource is, not which app holds it). **An app never writes the version
segment**; it names its own label or `PREFIX` and `config/urls.py` decides
where that hangs, which is what makes a `v2` mount a config change and not a
sweep of every app. Schemas are Pydantic v2
(`ninja.Schema`, `from_attributes` on) in `apps/<x>/schemas.py`, named `XIn` /
`XOut` / `XPatch`; **the same schema serves REST, MCP, the webhook body and the
socket payload.** OpenAPI is at `/api/v1/docs` — the field test's map; a wrong
schema is a wrong map.

```python
# wrong — "__all__" leaks the next column; auth=None; unpaginated; bare manager
class OrderSchema(ModelSchema):
    class Meta: model = Order; fields = "__all__"
@router.get("/", auth=None)
def list_orders(request): return Order.objects.all()

# right — schemas.py
class OrderIn(Schema):
    customer_id: UUID
    lines: list[LineIn]
class OrderOut(Schema):
    model_config = ConfigDict(from_attributes=True)
    id: UUID; number: str; total: Decimal; status: Order.Status; created_at: datetime

# right — api.py
from ninja import Router, Status
from ninja.pagination import paginate
from apps.core.api import CursorPagination     # the ONE seam — cursors, not page numbers (ADR core-18)
from apps.core.api.docs import Tag                 # a tag key's display name and description
from apps.accounts.auth import API_AUTH            # [SessionAuth(), ApiTokenAuth()] — the one auth, restated by name
from apps.core.actor import actor_from_request     # who is calling: user OR token, plus the acting hat
from apps.core.requests import TenantRequest       # HttpRequest + .tenant, after TenantMiddleware

PREFIX = "orders"                                  # optional; without it the mount is /api/v1/<label>/

TAGS = {"orders": Tag("Orders", "Placing an order, and following one.")}   # key = scope family; see below

router = Router(tags=["orders"], auth=API_AUTH)    # explicit here, or on every route; never None

@router.get("/", response=list[OrderOut], url_name="order-list")
@paginate(CursorPagination)                        # {"items": [...], "has_more": ..., "next_cursor": ..., "count": null}
def list_orders(request: TenantRequest, status: Order.Status | None = None) -> ScopedQuerySet[Order]:
    return selectors.orders(tenant=request.tenant, status=status)

@router.post("/", response={201: OrderOut}, url_name="order-create")
def create_order(request: TenantRequest, payload: OrderIn) -> Status[Order]:
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")     # a write with no tenant is refused, not guessed
    actor = actor_from_request(request)             # apps.core.actor — user OR token, plus the acting hat
    customer = get_object_or_404(Customer.objects.for_tenant(request.tenant), pk=payload.customer_id)
    return Status(201, services.create_order(tenant=request.tenant, actor=actor, customer=customer, lines=payload.lines))
```

- **Choosing a tag key — because the key IS the scope family.** A router's tag
  is not a label on a page. `apps/core/api/scopes.py` derives every scope name
  from it (`<tag>:read` / `<tag>:write`), so the string you type in
  `Router(tags=[...])` is the string a bearer token's ceiling names, and it goes
  out on the wire. **Default: the plural noun of the section's primary
  resource** — `orders`, `widgets`, `connections`. **Exception: name the
  MEANING, when the noun would mislead a reader who meets the string with no
  API around it** — a scope travels alone, in somebody's runbook and somebody
  else's agent config, and `messages:write` reads like "may write a message
  row" where `messaging:write` says what is being trusted. Record the reason
  where the tag is declared. The three invocations so far: **`messaging`**
  (comms — the capability is contacting a person, not editing rows),
  **`tenant-settings`** (core — `settings:write` is the most powerful string in
  the API and says nothing about whose settings), and **`org-structure` +
  `roles`** (core — `memberships:write` names a join table, and the
  owner's reason for `roles` is a domain one: under ONC certification the
  access-control vocabulary IS role-based, so `roles:write` maps one-to-one onto
  the language the product is audited in).
  **Either way the key is not the path** — `/organizations/`, `/memberships/`
  and `/invitations/` are three resources under two families, because a URL says
  what the resource is and a tag key says what a credential is trusted with.
  **And the key FREEZES the day a token could name it.** Renaming it kills every
  ceiling that holds it, silently — the token authenticates exactly as before
  and is refused at every door with nothing saying why. `FROZEN_FAMILIES` in
  `apps/core/api/scopes.py` is the census, and a departure from it is a finding.
  So: get the key right the first time; a new one is free, a rename is a
  deprecation with two live keys and a window.
- **Every route carries an explicit `auth=` — on its router or on the route —
  never `auth=None` outside the `rules.yaml` allow-list.** The API-level
  default on the `NinjaAPI` is a floor, not a reason to omit it; the house-rule
  canary looks for the declaration. `API_AUTH` is `[SessionAuth(),
  ApiTokenAuth()]` from `apps.accounts.auth` — session for the human door,
  `Authorization: Bearer <token>` for the machine door; `ApiTokenAuth` resolves
  the tenant from the token (honouring `X-Tenant`) and sets `request.tenant`.
  A route may narrow (`auth=ApiTokenAuth()`), never drop; the one legitimate
  `auth=None` is a signature-verifying inbound webhook receiver, and it is on
  the allow-list.
- **`@paginate(CursorPagination)` on every list**, under the route decorator,
  returning the queryset — never a list you built in Python. The envelope is
  `{"items": [...], "has_more": ..., "next_cursor": ..., "count": ...}`, and
  the paginator is the one in `apps/core/api/pagination.py`: **no app writes
  cursor code of its own** (ADR core-18). `?cursor=` and `?limit=` are the
  controls; **`count` is `null` unless the caller sends `?include_count=true`**,
  because a total costs a second statement and most callers never render one.
  The MCP twin calls `cursor_page(...)` from the same module and returns a
  `*Page` schema inheriting `core.schemas.ListPage`, so the two doors cannot
  come to disagree about the envelope. `get_object_or_404` on the **scoped**
  queryset, never on the bare manager.
- Writes go through a service; the route unpacks the schema, calls, returns.
  `response={201: OrderOut, 409: Error}` declares every status the route can
  return, so the OpenAPI contract is the real one. Explicit field lists;
  **never `"__all__"`**; `ModelSchema` only for a read-shape that truly mirrors
  the model, and still with a list.
- Errors: `ninja.errors.HttpError(status, detail)` for the route's own
  refusals. A service's domain exception is mapped **once**, by the exception
  handlers in `config/api.py` — `ValidationError` → 400, `IntegrityError` →
  409, `PermissionDenied` → 403, `ObjectDoesNotExist` → 404 — never caught and
  reshaped per route. **The envelope is `{"detail": …, "code": …}` plus
  `"errors"` when the refusal names fields and `"remedies"` for every
  registered code** — `code` is always present, and the body comes from
  `core.exceptions.wire_refusal`, the one composer both doors render
  (`config/api.py:on_domain_error`; §4, "Refusals"); `architecture.md` is the
  authority and the code agrees with it. **There is no second shape.** Ninja's
  own schema errors used to be blessed as one (`{"detail": [{"loc", "msg",
  "type"}]}`, 422, no `code`); the owner's ruling folded them in,
  so `config/api.py:on_schema_validation` recomposes pydantic's list into the
  same envelope with the registered code **`invalid_body`** at 422 (RFC 9110 §15.5.21 — config/api.py::STATUS_FOR carries the argument) — a
  plain-language `detail`, the field errors under `errors` in the caller's own
  field names, and the registry's remedies. Never a bare string.
  **Never `@csrf_exempt`.**
- **Request bodies are STRICT: every `In`/`Patch` schema inherits
  `apps.core.schemas.StrictIn`** (`extra="forbid"`), never `ninja.Schema`
  directly. An unknown field is a refusal naming the field, never a silent
  drop — `POST /webhook-endpoints/` with `event_types` instead of `event_names`
  used to answer 201 with a signing secret for an endpoint subscribed to
  nothing (FT-1′ F6), which is the worst failure shape a platform whose callers
  are agents can have. `Out` schemas stay open on purpose: strictness is for
  the direction where silence cannot be told from success. The population is a
  census off the live OpenAPI document, so a new lax request schema fails by
  name (`apps/core/tests/test_strict_bodies.py`) rather than waiting to be
  noticed.

```python
# wrong — pydantic drops what it does not recognise, and the 201 says nothing
class WebhookEndpointIn(Schema):
    url: str
    event_names: list[str] = []

# right — the one seam; an unknown field is `invalid_body`, naming the field
from apps.core.schemas import StrictIn

class WebhookEndpointIn(StrictIn):
    url: str
    event_names: list[str] = []
```

### Computed aggregates — `MeasuredOut`

A number the server computed travels with its basis attached, and **the UI
never computes one**:

```python
# wrong — a naked number; every door that wants context re-adds the parts, differently
class WidgetStatsOut(Schema):
    count: int

# right — the value and how it was arrived at, Decimal at both levels (rule 15)
from apps.core.schemas import MeasuredBasisOut, MeasuredOut

class WidgetStatsOut(Schema):
    count: MeasuredOut

WidgetStatsOut(count=MeasuredOut(
    value=Decimal("42"),
    basis=MeasuredBasisOut(formula="onboarded + pending", inputs={"onboarded": Decimal("30"), "pending": Decimal("12")}),
))
```

The basis is **honest**: `value` equals what `formula` evaluates to over
`inputs`, and the rung's test recomputes it. Pydantic renders `Decimal` as a
string on the wire, so the value that arrives is the value that was computed.
The MCP twin returns the same fields byte-equal (rule 17) — **including the
timestamps**: one encoder in `config/api.py` renders both doors
and `config/mcp.py` puts every machine-door answer through it, so a client
may compare two renderings of a row for equality. There is no gate
rule recognising "a computed aggregate" — it is an open set, enforced through
the lead's criteria (`django-architect` §E10) — so do not wait to be caught:
if a route sums, counts or divides, it ships `MeasuredOut`.

## 7 · Workflows — Temporal

**A run row's `error` names the cause, not the wrapper.** Temporal wraps an
activity's own exception in an `ActivityError` whose `str()` is
`"Activity task failed"` — true, and useless to whoever reads the
`WorkflowRun` row six weeks later. Walk `__cause__` a bounded number of links
(three: wrapper → activity error → the activity's own complaint) and join
them; `apps/workflows/workflows.py::_reason` is the worked form.

```python
# WRONG — the row says "Activity task failed" and the reason is gone
except Exception as error:
    await self._finish(status=RUN_FAILED, error=str(error))
    raise

# RIGHT — the row carries the activity's own complaint
except Exception as failure:
    await self._finish(status=RUN_FAILED, error=_reason(failure))
    raise
```

Bounded because a cause chain is somebody else's data structure; deterministic
because it reads nothing but the exception it was handed. Rule 28 sees that
the finish seam is *reached*; it cannot see what you put in it.

**Anything that must wait or retry is a workflow** — a webhook delivery with
backoff, an integration sync, a wait for a human or a signal, a schedule. Not a
thread, not a task queue, not a command on cron. Two files per app, both
discovered by the worker:

- `workflows.py` — `@workflow.defn(name="…")` classes, exported in `WORKFLOWS`. **Deterministic** (house rule 9): the module imports **only** stdlib `dataclasses` / `datetime.timedelta`, `temporalio.workflow`, and the app's own `types.py`. No ORM, no `httpx`, no `datetime.now()`, no `random`, no `time.sleep`, no settings read that can vary between runs — and **no import of `activities.py`**: activities are invoked **by name**, because importing them would drag the ORM into a module that has to replay identically years from now. `workflow.now()` for the clock; `workflow.random()` if you truly need randomness; `asyncio.sleep` / `workflow.wait_condition` for waiting; `workflow.execute_activity("<name>", …)` for everything that touches the world.
- `activities.py` — `@activity.defn(name="…")` functions, exported in `ACTIVITIES`, and **plain `def`, not `async def`** (below). **Activities do the I/O, and they call services.** They restore the tenant, the user and the **acting hat** from workflow context (`apps.workflows.context`: the interceptor carries all three as Temporal headers; read them from there, never from a global, never from the payload), are **idempotent** (the same input twice is safe — Temporal retries), and take their retry policy at the call site, not inside.
- `types.py` — the shapes that cross the boundary: plain `@dataclass`es in a module that imports nothing but the standard library. A workflow that took a model instance could not be replayed.

```python
# wrong — ORM, network and clock inside the workflow; importing the activity; a thread for "background" work
with workflow.unsafe.imports_passed_through():
    from apps.example.activities import send_welcome          # drags the ORM into the sandbox
async def run(self, tenant_id: UUID) -> None: httpx.post(url, json={"at": datetime.now().isoformat()})
threading.Thread(target=send_welcome, args=(Tenant.objects.get(pk=tenant_id).pk,)).start()

# right — types.py: stdlib only
@dataclass
class OnboardIn:  email: str
@dataclass
class OnboardOut: confirmed_at: datetime | None

# right — workflows.py: stdlib dataclasses/timedelta + temporalio.workflow + types; nothing else
from datetime import timedelta
from temporalio import workflow
from apps.example.types import OnboardIn, OnboardOut

@workflow.defn(name="OnboardTenant")
class OnboardTenant:
    def __init__(self) -> None:
        self.confirmed = False

    @workflow.run
    async def run(self, input: OnboardIn) -> OnboardOut:
        await workflow.execute_activity(
            "send_welcome", input,                                   # by NAME — never the imported function
            start_to_close_timeout=timedelta(seconds=30),            # retry policy, when not the default, here too
        )
        await workflow.wait_condition(lambda: self.confirmed, timeout=timedelta(days=7))
        return OnboardOut(confirmed_at=workflow.now())

    @workflow.signal
    def confirm(self) -> None:
        self.confirmed = True

WORKFLOWS: list[type] = [OnboardTenant]

# right — activities.py: plain def in the worker's thread pool, the principal from context, a service does the work
from collections.abc import Callable
from typing import Any

from django.db import close_old_connections
from temporalio import activity

from apps.core.actor import system_actor
from apps.example import services
from apps.example.types import OnboardIn
from apps.workflows.context import workflow_context

@activity.defn(name="send_welcome")
def send_welcome(payload: OnboardIn) -> None:
    close_old_connections()                                    # both ends: no request cycle out here
    try:
        tenant, _user_id, org = workflow_context()             # THREE — tenant, user id, acting hat
        services.send_welcome(                                 # idempotent; the service does the write
            tenant=tenant,
            actor=system_actor(tenant, org),                   # nobody clicked this; the hat still rides
            to=payload.email,
        )
    finally:
        close_old_connections()

ACTIVITIES: list[Callable[..., Any]] = [send_welcome]
```

Read `apps/example/activities.py` before writing your first one — it is the
shape above, in full, with the reasons in its docstring.

**What a workflow argument may hold.** *A workflow argument may hold only what
survives the sandbox's import wall — `str`/`int`/`float`/`bool`/`UUID`/nested
dataclasses; never a type from a module `temporalio` restricts (today:
`datetime`); `date`/`Decimal`/`timedelta` refused by the writer everywhere.
Three failure modes, one error message.* That sentence is the settled boundary,
and it is worth knowing why the three modes look alike, because two agents
already read the same error two different ways:

- **The converter is innocent.** On the pinned `temporalio` 1.31.0
  `value_to_type` handles `hint is datetime`
  (`converter/_payload_converter.py:852`) and `UUID` (`:1048`), and
  `AdvancedJSONEncoder.default` writes both (`:678`, `:691`). A plain
  round-trip through the converter passes for both types. Do **not** write a
  doc line saying `datetime` cannot be serialised: on this library it can.
- **The sandbox is where `datetime` dies.** `datetime` is a restricted module
  inside the workflow sandbox
  (`worker/workflow_sandbox/_restrictions.py:604-608` — the entry that lets
  `datetime.datetime.now()` be refused), so the class a workflow ARGUMENT is
  decoded against is a `_RestrictedProxy` and the converter's identity dispatch
  (`hint is datetime`) falls through. The proxy forwards `__repr__`, so the
  error names the very class it failed to recognise — which is exactly why the
  message reads as a converter bug and is not one. `sandboxed=False` decodes
  the identical shape.
- **`date` / `Decimal` / `timedelta` die at the writer**, in the client,
  loudly: `AdvancedJSONEncoder.default` (`:672-693`) has no branch for any of
  them and `json` raises `TypeError: Object of type date is not JSON
  serializable` before anything is dispatched. Note the asymmetry in what the
  two modes cost you: the writer's refusal is immediate and named, while
  `datetime` fails on the argument decode *inside* the worker — a workflow-task
  failure Temporal retries forever, silently, with the `WorkflowRun` row still
  reading `running`.

The practical rule that falls out: keep `types.py` dataclasses to
`str`/`int`/`float`/`bool`/`UUID` and nested dataclasses. An instant crosses as
an ISO `str` the activity parses, or as an `int` epoch; money crosses as an
integer of minor units or a decimal `str` the activity re-reads — never a
`float`, which house rule 15 already forbids on the field it came from; a
duration crosses as `int` seconds and becomes a `timedelta` inside the
workflow, where `timedelta` is an allowed import.

- **`system_actor(...)` is the right actor for an activity's own writes — but
  the files seam refuses it: `store_bytes`/`store_stream` need a
  person-carrying actor** (`actor.user` set), because a document records who
  filed it (`uploaded_by`, non-null, `PROTECT`) and a credential with no user
  behind it cannot file one. An activity storing bytes on somebody's behalf
  restores that person off the workflow headers and passes them for the file
  while keeping `system_actor` for its own rows — the `_actor_for` /
  `_person_for` split in `apps/exports/activities.py` is the worked shape,
  with the argument for why that pair is honest in its docstrings.

- **Never `transaction.on_commit(partial(...), robust=True)` — register a
  named nested `def`.** Django's robust branch formats its error with
  `func.__qualname__`, which a `functools.partial` does not have, so the
  handler whose whole job is to swallow a failing hook raises `AttributeError`
  itself, uncaught, and **every hook queued behind it never runs** — `robust`
  delivering its exact opposite, silently. Proven on this tree (P3 SEC-R3);
  the shape that works is `def x_on_commit(): ...` then
  `transaction.on_commit(x_on_commit, robust=True)`.
- **Start a workflow from a service** with
  `apps.workflows.services.start_workflow_on_commit(*, workflow, arg, tenant,
  user=None, org=None, id, task_queue=None)` — sync, callable inside
  `transaction.atomic()`; it registers
  the start with `transaction.on_commit` and records the `WorkflowRun` row. The
  **`id` is required and deterministic**: build it with `workflow_id(*, tenant,
  app, noun, key)` — keyword-only, like every other service here (e.g.
  `workflow_id(tenant=tenant, app="orders", noun="onboard", key=str(order.pk))`
  — one id per tenant, app, noun and key, the same every time) so a retried
  service does not start a second run. Never from a model, a signal or a route
  directly. `arg` is one dataclass from `types.py`, not positionals. **`org=` is
  the acting hat the run is started under** and it is not optional in spirit:
  omit it and every activity in the run acts for the whole tenant instead of
  for the branch that asked, which is the leak the hat exists to close. Pass
  `actor.org`; a tenant-wide run (a platform workflow — email, dispatch) is the
  deliberate `None`. The async
  form, `await start_workflow(..., client=)`, exists for callers already on the
  event loop (an activity starting a child, the worker, a test); a sync service
  does not build a client.
- `tenant`, `user` **and `org`** — the acting hat — are set on the workflow's
  **headers** by the `TenantContextInterceptor` and repeated in the memo for
  the Temporal UI; in an activity, `current_tenant()` (a row — database read,
  activities only), `current_org()` (likewise), `current_user_id()` (a string),
  or all three at once as
  `workflow_context() -> tuple[Tenant | None, str | None, Organization | None]`
  — **three** values, `tenant, user_id, org = workflow_context()`. Inside a
  workflow only the id accessors are safe.
- **Schedules**, not cron or beat: periodic work is a Temporal Schedule that
  starts a workflow; where schedules are declared is `apps/workflows`' business.
- **A workflow that needs one instant spells it `workflow.now()`** — the
  `workflow` in `from temporalio import workflow`, which is the blessed
  spelling and not a workaround. Rule 9's allow-list already carries
  `temporalio` (`quality/rules.yaml:626`, `quality/checks.py:915`), and the
  determinism check treats a call whose chain ROOT is the literal name
  `workflow` as sanctioned (`quality/checks.py:948-956`), so `workflow.now()`,
  `workflow.uuid4()`, `workflow.random().randint(...)` and `workflow.time()`
  all pass while the bare `now`/`uuid4`/`random`/`time`/`hash` they replace are
  banned outright (`quality/checks.py:917-935`). Two traps, both the rule's own
  declared blind spots: **the receiver has to be spelled `workflow`** — `from
  temporalio import workflow as wf` then `wf.now()` is read as a clock and
  reported, correct code and all; and what you USE the instant for is review's
  job, not the gate's. Anything the clock is only *carried* for — a timestamp
  a row wants — belongs in an activity, where the real clock lives.
- **Activities are plain `def`**, and every activity in this repository is
  (`apps/events/activities.py`, `apps/example/activities.py`). The ORM is
  synchronous; the worker
  (`apps.workflows.client.build_worker`, re-exported as
  `config.temporal.build_worker`) is built with an
  `activity_executor=ThreadPoolExecutor(...)`, so Temporal runs a sync activity
  on a worker thread where a synchronous query belongs — nothing is blocking
  the event loop. What a sync activity owes that thread is
  `close_old_connections()` at **both** ends: there is no request cycle out
  here to close what it opened, and a connection left open per thread is a
  connection leaked forever.
- An `async def` activity is legal too, and then every ORM touch goes through
  `apps.core.asyncdb.run_db(fn, *args, **kwargs)` (which does the
  `close_old_connections()` pair for you). It is the exception, not the house
  form: reach for it when the activity's own work is genuinely async I/O.
- The worker runs on `scripts/worker.sh` against a per-worktree task queue
  (`db.sh`); a rung that adds a workflow says so in its report — the field test
  needs a worker up to drive it. Tests: §12, the time-skipping environment.

## 8 · Events

`apps.events.services.emit(*, name, tenant, payload, actor=None)` — keyword-only,
the name included, because it is a `@service` (house rule 13) — writes the
`Event` and its `Outbox` row **in the caller's transaction**; `events` itself
starts the dispatch workflow on commit, which fans out to the tenant's
`WebhookEndpoint`s (signed, retried, dead-lettered) and to the realtime bridge.

- **Emit inside the service's `transaction.atomic()`**, after the write it
  describes. Never from a model's `save()`, a signal, or a door.
- Names are `<app>.<resource>.<past-tense verb>`: `orders.order.created`.
  **Payloads are schemas** — `OrderOut.from_orm(order).model_dump(mode="json")`,
  the shape the REST route returns, so webhook and socket clients see what a
  REST client sees.
- Nothing imports `events` except to `emit`; nothing subscribes in code —
  subscribers are data (`WebhookEndpoint` rows) and the realtime bridge.
  `emit()` is the whole of a service's responsibility; delivery is the
  dispatch workflow's.

## 9 · The other doors

**MCP** — `apps/<x>/mcp.py` exposes `register(server)`; `config/mcp.py`
discovers it and mounts the server at `/mcp` (Streamable HTTP, stateless).
`config.mcp.TokenAuthMiddleware` resolves the bearer token **once, at the
edge** — the same `authenticate_token` service `ApiTokenAuth` uses — and leaves
a `Principal(user, tenant)` on the ASGI scope; `apps.core.mcp.principal(ctx)`
is how a tool reads it. Tools are **thin over services**, take user and tenant
**from the principal** (no tenant → refuse, fail closed), never see a token,
and share the API's schemas. A tool that does something a REST route cannot,
or returns a different shape for the same thing, is a door-parity finding.

```python
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from apps.core.mcp import principal                 # Principal(user: AbstractBaseUser, tenant: Tenant | None)

def register(server: MCPServer[Any]) -> None:       # config.mcp discovers and calls this
    @server.tool(name="orders.create", description="Create an order for the caller's tenant")
    def create_order(ctx: Context[Any], body: OrderIn) -> OrderOut:
        acting = principal(ctx)                     # from the scope the middleware filled; never the payload
        if acting.tenant is None:
            raise ToolError("No tenant for this call.")
        customer = get_object_or_404(Customer.objects.for_tenant(acting.tenant), pk=body.customer_id)
        return OrderOut.from_orm(services.create_order(tenant=acting.tenant, actor=acting.actor(),
                                                       customer=customer, lines=body.lines))
```

**Sockets** — `apps/realtime` ships the one consumer: authenticate, **join the
tenant's group only**, receive pushes from the event bridge. A product app that
needs its own channel exposes `websocket_urlpatterns` in `apps/<x>/consumers.py`
with the same shape: no unauthenticated connect (`close(code=4401)`), join by
`scope["tenant"]`, never a user-supplied group name. **Push via events**; never
query the database per message — a consumer that needs a row uses
`database_sync_to_async` once, at connect.

**Webhooks inbound** — `verify → store → hand to a workflow → 202`. The
receiver (the `connections` helper, or a route on the allow-list) checks the
signature with `hmac.compare_digest`, stores the raw body, starts a workflow,
returns. **Never processed inline**: a slow or failing handler loses the event.
**Outbound** — via `emit()` (§8); never `httpx.post` from a service or a route.

**Connections** — `apps.connections` holds the per-tenant `Connection`
(provider, **encrypted credentials**, status) and the **`httpx` client factory**
(timeouts, retries, idempotency keys). External calls happen **inside
activities**, through that factory, the connection read through `for_tenant`.
Never `requests`; never a bare `httpx.Client()`; never a credential in a log
line or an exception message.

## 10 · Async

ASGI (`uvicorn`) is the default server; **the CRUD path stays on the sync
ORM** — ninja runs a sync route in a thread, and that is the normal case.
`async def` routes **only when the route awaits I/O** (an upstream call, a long
poll).

- ORM in an async context: `await Model.objects.for_tenant(t).aget(pk=pk)`,
  `async for`, or `sync_to_async(service)(…)` — never a sync query inside
  `async def`. **No transaction across an `await`**: `atomic()` wraps sync code.
- Never `asyncio.run()` inside Django; never `async_to_sync` inside a running
  loop; never `asyncio.create_task` for "background" work — that is a workflow.

## 11 · Migrations — made inside the rung

```bash
uv run python manage.py makemigrations example -n order_status_field
uv run python manage.py makemigrations --check        # must be clean before commit
git add apps/example/migrations/0007_*.py apps/example/migrations/max_migration.txt apps/example/models.py
```

- **One app per rung**; **`makemigrations` is run by the builder, inside the
  rung**, from the models it changed, and committed with the code.
- **Never `makemigrations --merge`.** A merge migration means two rungs touched
  one app — the PM's ordering failure. Stop, report, do not patch. A conflict
  in `max_migration.txt` (`django-linear-migrations`) is the same finding
  earlier; never hand-edit it.
- **Data migrations are separate files**: `RunPython(forward, reverse)` with a
  real reverse (or `RunPython.noop` stated deliberately), using
  `apps.get_model(...)` — never importing the model class. Never edit a
  migration merged to main; add a new one.

## 12 · Tests

**A schedule test asserts about its own ids, never the discovered set.**
`ensure_schedules()` returns the **cross-app** result of discovery. A test
asserting `ensured == [...]` is asserting about every other app's schedules
and breaks the day a sibling app declares one — a green suite turned red by a
module it never mentions. Assert **containment** of your own ids
(`assert "ensure_purge_schedule" in ensured`), never equality with the set.
Same reasoning as `INSTALLED_APPS` being derived: discovery is what lets one
agent per app run in parallel, and a test that pins the discovered set takes
that back.

```python
def test_orders(): assert Order.objects.filter(status="nope").count() == 0   # wrong — cannot fail

# right — the property, through the door a user uses, with the tenant sibling
# (fixtures from apps/conftest.py: api, tenant, other_tenant, owner, stranger, nomad, root)
@pytest.mark.django_db
def test_list_orders_is_scoped_to_tenant(api, tenant, other_tenant, owner, stranger):
    mine = services.create_order(tenant=tenant, actor=actor_for(user=owner, tenant=tenant),
                                 customer=customer(tenant), lines=[line()])
    services.create_order(tenant=other_tenant, actor=actor_for(user=stranger, tenant=other_tenant),
                          customer=customer(other_tenant), lines=[line()])
    api.force_login(owner)                         # owner's default membership is `tenant`
    resp = api.get("/api/v1/orders/")
    assert resp.status_code == 200
    assert [o["id"] for o in resp.json()["items"]] == [str(mine.pk)]   # items + has_more + next_cursor

@pytest.mark.django_db
def test_list_orders_query_budget(api, owner, django_assert_num_queries, seeded_orders):
    api.force_login(owner)
    with django_assert_num_queries(LIST_QUERY_BUDGET):     # measured at seeded scale; the comment says how
        api.get("/api/v1/orders/")            # and one more with ?include_count=true: the count is a choice

@pytest.mark.django_db(transaction=True)        # the activity writes from another thread, on another connection
@pytest.mark.asyncio
async def test_onboard_waits_for_confirmation(tenant, owner):
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)                  # config.temporal: the tenant has to ride along
        async with build_worker(client, queue="t"):               # the real discovery, not a hand-built list
            run = await start_workflow(workflow="OnboardTenant", arg=OnboardIn(email="a@b.c"),
                                       tenant=tenant, user=owner, id="onboard-1", client=client, task_queue="t")
            handle = client.get_workflow_handle(run.workflow_id)  # NOT auto-skipping — see below
            await handle.signal("confirm")                        # this test finishes because the signal preempts
            result = await handle.result()                        # the wait, not because the clock moved
            assert result.confirmed_at is not None
```

**Auto-skip rides only on a handle `start_workflow` RETURNED.** The environment
installs a client interceptor whose `start_workflow` re-classes the handle it
returns into a `_TimeSkippingWorkflowHandle`
(`temporalio/testing/_workflow.py:600-605`), and it is *that* class's `result()`
that unlocks time skipping (`:610-620`). A handle you build yourself with
`client.get_workflow_handle(...)` — which is what you must do when the run was
started by a service's on-commit hook, as it is here — is a plain
`WorkflowHandle`: awaiting its `result()` moves no clock at all. The snippet
above survives only because the signal arrives before the seven-day timer
matters; take the signal away and it waits seven real days.

The tree's worked example is the shape to copy when nothing preempts the wait —
`apps/example/tests/test_workflows.py:119-131` says it in its own comment and
advances the clock explicitly, in day-sized steps rather than one leap, because
the timer is created a moment after the first activity finishes and a single
jump can land before it exists:

```python
handle = client.get_workflow_handle(onboarding_id(tenant, widget), result_type=WidgetOnboarded)
for _ in range(APPROVAL_DAYS + 3):
    if (await handle.describe()).status is not WorkflowExecutionStatus.RUNNING:
        break
    await env.sleep(timedelta(days=1))          # the clock the hand-built handle does not move for you
result = await handle.result()
```

- pytest-django + pytest-asyncio; `@pytest.mark.django_db` (`transaction=True`
  only when the code under test commits — `on_commit` hooks and activities on
  another connection need it). Set-up through the shared fixtures in
  `apps/conftest.py` or `services.create_*`, not raw `Model.objects.create`.
- **Test the property, not the mechanism.** "The signal fired" is a mechanism;
  "the receipt row exists" is a property. **No test that cannot fail.**
- **REST through the mounted API** with the pytest-django `client`, so
  `TenantMiddleware` runs and `request.tenant` is real.
  `ninja.testing.TestClient(router)` skips middleware — only for a router with
  no tenant dependence, and say so. Assert status code **and** body.
- **MCP** tools are called as functions with a fake `Context` whose
  `request_context.request.scope[SCOPE_KEY]` is a `Principal(user, tenant)`
  (`apps.core.mcp`); assert the output equals the REST route's for the same row
  (door parity).
- **Sockets** with `apps.realtime.tests.websocket` — the in-repo raw-ASGI
  client, **not** `channels.testing.WebsocketCommunicator`, whose package
  `__init__` imports `daphne` and this repository serves with uvicorn:
  connect as a user, emit through a service, assert the push arrives; connect
  as a user in another tenant, assert it does not.
- **Workflows** under `WorkflowEnvironment.start_time_skipping()`, the worker
  from `config.temporal.build_worker` (the real discovery) on a client with
  `attach_interceptors` applied, so the tenant rides along (a seven-day wait
  takes milliseconds — on a handle `start_workflow` returned, or on `env.sleep`
  when you built the handle yourself; the snippet above says why);
  decision logic with fake activities; activities awaited
  directly against the database. Never point a test at the dev server.
- **An org-scoped model needs the sibling test, not just the second-tenant
  one.** "Another tenant's rows are absent" no longer proves the scoping: build
  a small tree (root → seller A → sub A1, root → seller B) and assert that A1
  sees only its own, A sees A's and A1's, A cannot see B, A1 cannot see A, and
  that switching `X-Org` on one person who is a member of both changes the set.
  `apps/example/tests/test_network.py` is the worked example. Actor fixtures
  name their hat (`actor_for(user=…, tenant=…, org=…)`) for the same reason they
  name their role: an actor with `org=None` reads nothing, so a test that forgot
  would pass or fail for a reason it never stated.
- **A test that reads a paginated door to assert about a whole POPULATION owes
  `assert body["has_more"] is False`, or it walks the cursor.** A list route
  answers one page — `API_PAGE_SIZE`, 50 by default
  (`config/settings/base.py:1041`) — and `{items, has_more, next_cursor, count}`
  is the whole envelope (`apps/core/api/pagination.py:203`, `:661`). A test that
  derives a population from `body["items"]` and never looks at `has_more` is
  asserting about the first 50 rows while claiming to assert about all of them:
  it passes, and then it goes quietly vacuous on the 51st row somebody adds —
  no failure, no red, just a claim that stopped being true. Assert the flag
  when you expect one page (`apps/core/tests/test_pagination.py:158` is the
  worked line), and walk `next_cursor` when you do not
  (`test_pagination.py:110-120`, the `_walk` helper, is the worked loop — note
  its hop bound, so a broken walk fails rather than hangs). The same applies to a test
  pinning a whole response body: `apps/core/tests/test_resource_first_urls.py`
  pins `"has_more": false` inside the bodies it fixes, which is what makes those
  pins mean what they say.
- One query pin per list route at seeded scale × k. `settings` via the
  `settings` fixture, never by mutating `django.conf.settings`. Tests live in
  `apps/<name>/tests/`, one module per surface (`test_api.py`, `test_mcp.py`,
  `test_workflows.py`, `test_services.py`).

## 13 · Typing, and the gate from the builder's seat

`mypy --strict` with django-stubs is a blocking gate leg. Annotate every
service, route, tool, activity and consumer method; `QuerySet[Model]` for
querysets (`ScopedQuerySet[Model]` for a scoped one; a paginated list returns
one); `-> Status[Order]` for a status-plus-object; a `Schema` for a door's
input and output and a `dataclass` in `types.py` for a workflow payload — never
a `dict[str, Any]` crossing a door. `# type: ignore` carries a reason code and
a comment, or it does not land.

```bash
./scripts/check.sh --loop          # per rung. Never piped. Exit 0 clean · 1 violations · 2 enforcement broken.
```

`scripts/check.sh` is the gate and it is on main; the legs it runs, and what
each is for, are in `build-contract.md`. Run the script rather than the legs by
hand: the ones you would forget — the house-rules engine, the canary self-test,
the second pytest pass — are the ones that catch the most.

- **`mypy` reads `INSTALLED_APPS`, so a disabled app changes what type-checks.**
  django-stubs' plugin builds its model knowledge from the resolved app
  registry, and the `<fk>_id` shadow attributes it synthesises for a foreign key
  exist only for models in that registry. Disable an app and every reference to
  one of its `_id` attributes — from inside the app itself included — becomes
  an `[attr-defined]` error. Measured on this tree: `mypy --strict` clean is
  **exit 0, "Success: no issues found in 495 source files"**; the same command
  under `DJB_DISABLED_APPS=example` is **exit 1, 5 `[attr-defined]` errors in 5
  files** (`apps/example/models.py:441` on `WidgetEntry.widget_id`, and
  `Widget.owner_id` in `test_services.py:71`, `test_admin.py:85`,
  `test_mcp.py:268`, `test_api.py:105`). Nothing is wrong with that code; the
  app it belongs to is simply not installed in the world mypy was pointed at.
  So: **a rung that touches the optional-app machinery states which world it
  measured in**, because "mypy is green" is a claim about a configuration and
  not about the tree. `apps/example` is the one app a deployment may leave out
  and it says so itself (`apps/example/apps.py:19`, `optional = True`);
  everything else is non-optional by omission.
- Run `--loop` per rung. **Do not run the full gate by hand** — pre-push
  consults the verdict ledger and runs it once, on the tree you push.
- **Never pipe it** — you replace its exit status with the pipe's. **Exit 2
  means the enforcement is broken, not your code**: stop and report; do not
  "fix" a rule to make it pass. Pre-commit runs `--fast`; `--no-verify` is
  never the answer.
- Your worktree has its own database and task queue (`scripts/db.sh`); nothing
  you run touches anyone else's tree. Stage explicit paths.

## 14 · The outdated-API blacklist

Still emitted by agents; wrong on Django 5.2 / ninja / Temporal / this repo.
If you find yourself typing one, stop.

| Wrong | Right |
|---|---|
| `rest_framework` anything — `ModelSerializer`, `ViewSet`, `APIView`, `permission_classes`, `@action`, `drf-spectacular` | `ninja.Router`, `Schema` in `schemas.py`, `auth=`, `@paginate`, `response=` |
| `celery`, `@shared_task`, `.delay()`, beat, `django.tasks`, a cron entry | a Temporal workflow + activities; `start_workflow_on_commit` from a service; a Schedule |
| `requests` | the `connections` `httpx` client factory, inside an activity |
| `threading.Thread`, `asyncio.create_task`, `BackgroundTasks` for background work | a workflow |
| `post_save` / `pre_save` receivers for business logic or notifications | `services.py` + `emit()` |
| `datetime.now()`, `time.sleep`, `random`, ORM, `httpx`, `settings.X` inside `workflows.py` | `workflow.now()`, `asyncio.sleep`, `workflow.random()`, an activity |
| `auth=None` on a route · `@csrf_exempt` on an API function | an explicit `auth=` on the router or the route — `API_AUTH` or a narrowing of it (the `rules.yaml` allow-list for the signed inbound receiver); never the decorator |
| `fields = "__all__"` · `on_delete` omitted | an explicit field list · always explicit (`PROTECT` by default) |
| `django.contrib.auth.models.User` | `settings.AUTH_USER_MODEL` / `get_user_model()` |
| `models.Model` as a concrete base | `apps.core.models.BaseModel` / `TenantScopedModel` |
| `ScopedModel.objects.all()` / `.filter()` in a door or service | `ScopedModel.objects.for_tenant(tenant)` |
| `Model.objects.create(...)` / `.save()` in a route, tool, consumer or activity | a service |
| editing `config/api.py` / `asgi.py` / `temporal.py` / `mcp.py` / `settings` / `pyproject.toml` to register an app | an `apps.py` with `depends_on`; drop `api.py` / `consumers.py` / `workflows.py` / `mcp.py` in the app — discovery |
| `from apps.<x>.activities import …` inside `workflows.py` (even under `imports_passed_through`) | `workflow.execute_activity("<name>", …)` — by name |
| an `async def` activity reached for by default · `sync_to_async(...)` in an activity, tool or consumer | a plain `def` activity with `close_old_connections()` at both ends (§7 — every activity in this tree is one); `async def` + `apps.core.asyncdb.run_db(fn, …)` is the exception, for work that is genuinely async I/O |
| `makemigrations --merge` | stop; it is an ordering failure |
| `CheckConstraint(check=…)` · `index_together` · `unique_together` | `CheckConstraint(condition=…)` · `Meta.indexes` · `Meta.constraints` |
| `from django.conf.urls import url` · `ugettext*` · `force_text` · `django.utils.timezone.utc` | `django.urls.path` · `gettext*` · `force_str` · `datetime.timezone.utc` |
| one `settings.py` · `requirements.txt` · bare `python manage.py` · `runserver` | `config/settings/*` · `pyproject.toml` + `uv` · `uv run python manage.py` · `./scripts/serve.sh` |

## 15 · Before you report

- `./scripts/check.sh --loop` is green in your worktree, unpiped;
  `makemigrations --check` is clean; `max_migration.txt` is committed.
- Every new route carries an explicit `auth=` — on its router or on the route —
  and nothing is `auth=None` outside the `rules.yaml` allow-list; every list is
  `@paginate`d with a query pin.
- Every write, from every door, goes through a service; there is no `signals.py`;
  every state change a subscriber could care about is an `emit()` inside the
  service's transaction. Nothing in a `workflows.py` touches the ORM, the
  network, the clock or randomness; every activity is idempotent.
- Every read of a scoped model in a door, service or activity goes through
  `for_tenant`; every list test has a sibling proving another tenant's rows are
  absent; every MCP tool has a parity test against its REST twin.
- Nothing in §14 appears in your diff
  (`git diff | grep -E "rest_framework|shared_task|import requests|csrf_exempt|auth.models import User|__all__|datetime.now"` is a cheap check).
- If the rung added a workflow, consumer or tool, the report says so — the field
  test needs the worker up and `introspect` shows the new entry. Its first line
  says whether you are still working.

## Two gotchas, at the site they bite

**A ninja `resolve_` hook dies inside a `Page`.** A resolver is consulted
before attribute access on whatever object is being validated — re-validating
an `Out` as an item of a `Page` hands the resolver the wrong object and it
finds nothing: it works at the HTTP door and fails at the machine one. Wrong
form: `resolve_event_name` on the schema. Right form: a model `@property` —
found by both doors, no resolver timing.

**mypy narrows a subscripted expression across statements.** After
`assert x[-1]["verified"] is False`, every later read of that same expression
is `Literal[False]` and `--strict` marks the rest of the test `[unreachable]`.
Right form: read through a small function (`verified(receiver)`) — narrowing
cannot see through a call.
