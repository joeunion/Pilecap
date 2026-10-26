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

**Before you write a helper:** `uv run python manage.py roads` — one line per
job this platform does exactly one way, with the road that does it, its
contract and a worked example; `roads <job>` prints one, and a job with a road
is called, never re-implemented. `roads --json` is the `roads/1` document a
brief cites and a verifier diffs: the header's `schema`, `tree` and
`platform_apps`; `roads[]`, one per job (`job`, `import`, `path`, `line`,
`contract`, `example`, …); `kept[]`, a product's declared second roads (valved
`rule-84`, never in `roads[]`); `unmarked {measured, reason, total, classes}`,
house rule 84's counted copies by shape.

### The builder's seven

1. **Ask the roads before writing a helper.** `manage.py roads <job>` first,
   and a road that exists is called, never re-implemented. What house rule 84
   SEES is a second marker for one job and the copies of the counted shapes —
   `python -m quality.gate --explain 84` prints the classes and their
   ratchets; a helper that is neither marked nor one of those shapes is
   invisible to it (its own `does_not_cover`). So the door is asked whether
   the gate would notice or not: the rule is a floor under this item, never
   its measure.
2. **The second copy is the moment to make a road.** When another app has what
   you need, lift it into the platform module, mark it, and have both import
   it — two implementations of one thing never coexist, and
   duplicate-then-abstract is for the first copy only.
3. **Derive counts, never type them.** A test asserts over a population it
   derives; a typed number is legal only as a floor or ratchet pinned from a
   printed line, with that line beside it, because a typed count over a
   growing population reds the next honest change.
4. **Refusals go through the registry.** Every refusal is a registered code
   composed by `wire_refusal` (`core.exceptions`, `roads refuse`), because a
   hand-typed sentence or dict is a second refusal grammar and a finding.
5. **No new shell.** A new drive or leg is pytest, and a new `.sh` file needs
   the PM's word in the brief, because the gate's shell is moving to Python and
   every new line of it is one more to move.
6. **One job per function, and its first docstring line is the contract.**
   `manage.py roads` prints that line, so writing it is writing the
   documentation.
7. **Every mechanism ships with its worked example on the golden noun.** A
   mechanism without its `Widget` example in `apps/example` is not done,
   because the example is what a product copies.

**The long form sits beside this file.** What follows is the imperative core —
the rules as commands, and the wrong-form/right-form pair each one turns on.
The arguments, the worked snippets and the lead-tier material live in
`references/`, and each section below points at the one it needs:

| When you need | Load |
|---|---|
| the tenant tree, `visible_to`, `governing()`, `may_be_named`, `derive_org_from` | `references/hierarchy-and-scoping.md` |
| append-only ledgers, versioned config, the snapshot a run judges under | `references/ledgers-and-config.md` |
| the worked `@service`, the five valves and where each must sit, the refusal grammar | `references/services-and-refusals.md` |
| the worked router, tag keys as scope families, the error envelope, `MeasuredOut` | `references/api-door.md` |
| the worked workflow and activity, what a workflow argument may hold, starting a run | `references/workflows.md` |
| the MCP tool snippet, sockets, inbound webhooks, connections | `references/other-doors.md` |
| the worked tests, time skipping, the org-scoping and pagination siblings | `references/testing.md` |
| registering an app · what `mypy` measures and how to stand at the gate · the two gotchas | `references/layout.md`, `references/typing-and-gate.md`, `references/gotchas.md` |

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

**Registering an app is one file.** The `apps.py` that is the whole
registration, how `INSTALLED_APPS` is derived from it, and the three things you
never edit to register anything: `references/layout.md`.

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

**The road is `apps.core.models.ScopedQuerySet` — `manage.py roads
scope_read`**; shared schema + tenant FK, house rule 8. `TenantMiddleware`
sets `request.tenant` from the user's membership (or the one `X-Tenant:
<slug>` names); **none → `None`, every scoped read empty, no superuser
exemption.**

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
  are fields on it, not on `User`. It inherits `BaseModel`, not
  `TenantScopedModel`, so its scoped reads are its own manager's —
  `Membership.objects.for_tenant(t)` and `.of(user)`, both failing closed
  (`apps/core/models.py::MembershipQuerySet` says why it is not the base).
- Every door test that lists or fetches a scoped model has a sibling proving a
  second tenant's rows are absent — the test that cannot pass vacuously.

**Opting out** is recorded once, in the product's `architecture.md`, with the
reason: models inherit `BaseModel`, `TenantMiddleware` comes out, rule 8 is
`enabled: false`. No half-opt-out; schema-per-tenant is not a template option.

**One level down, the tenant is a tree.** A row one *part* of the tenant owns
inherits `OrgScopedModel` and takes both halves of `roads scope_read`, every
time, under the hat whose road is `apps.core.middleware.resolve_org` —
`manage.py roads resolve_hat`; configuration resolves up through
`governing()` and never widens visibility; a reference handed to a service passes
`core.authz.may_be_named`; a row that inherits its branch declares
`derive_org_from`. All four, wrong form and right form:
`references/hierarchy-and-scoping.md`.

**One level out, the host is a surface** (ADR surfaces-1, house rule 85). A
door resolves the request's surface BEFORE its tenant — `manage.py roads
resolve_surface`, and on the socket and MCP doors `roads request_host` for the
host — and the surface then decides which families the door answers and how
the tenant is chosen. That is the whole of its reach: **a service never reads
`actor.surface`** (a branch on the audience would be a second permission
system), and a write's wall is the role's permissions, never the surface. A
product declares its surfaces in its own `apps/<x>/surfaces.py`; the worked
one is `apps/example_portal/surfaces.py`. A ledger declares `append_only = True` and
config a process consumes is versioned rather than edited in place:
`references/ledgers-and-config.md`.

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

The worked service — `@service`, keyword-only, `transaction.atomic()`, the
`emit()` inside it, the object returned: `references/services-and-refusals.md`.

- **Keyword-only arguments**, typed, **return the object** (or a small typed
  result); **`transaction.atomic()` whenever more than one row is touched**,
  with the `emit()` inside it (§8).
- **A field that names a person is marked on its `Out`** —
  `Field(json_schema_extra=personal(example("dana@example.com")))`: the doors
  answer it, `event_payload` strips it at any depth, and `emit` refuses it put
  back; a subscriber that needs the person reads them through the API by id.
- **No business logic in signals — no `signals.py` at all** unless the lead
  rules otherwise and records why. House rule with a canary. If you reach for
  `post_save` you want a service; if you reach for it to notify, `emit()`.
- Something that waits or retries is started with
  `start_workflow_on_commit(...)` (§7), which registers the start on the
  service's transaction; the service never calls the external system.
- Validation at the edge (the schema) or in the service, not both. Services
  raise domain exceptions; doors map them. Tests call services for set-up;
  doors are tested through the door.

**Five valves exist and they differ in WHERE they have to sit** — `# rule-<id>:`,
`# authz:`, `# reach:`, `# door:`, `# role-bound:`; a valve in the wrong place is
invisible (`# rule-<id>:`'s reader: `roads valve`). **Every refusal speaks the
three-move grammar** — `code`, `fact`, `remedies` — declared beside the class
that raises it; the road is `apps.core.exceptions` — `manage.py roads refuse` —
and the one body both doors send is `apps/core/exceptions.py::wire_refusal`'s.
Both, in full: `references/services-and-refusals.md`.

**The actor a door hands a service has no road yet.** Most apps' doors
carry their own `_acting(request)` — the request's actor and tenant — and
house rule 84 counts every copy beyond the first as a `private_twin`; the
ratchet holds the count (`--explain 84`), and it falls when the consolidation
marks the one road. Until then a new app copies the nearest `_acting` rather
than inventing a third shape, and never mints the road in a feature rung.

**A role a declared surface admits holds exactly what its declaration says.**
A predicate that says "any member" opens nothing for it: the platform's own
roles keep the un-swept residue — every key with a predicate and no
declaration — until the consolidation's sweep, and the flat census's
`residue` section (`apps/core/tests/permissions_world.py`) is that count. So a
product whose surface role needs one of those keys DECLARES the pattern in the
role's `roles.py`; nothing grants it by default. Two facts a test of the wall
meets: the vocabulary caches who holds the residue, so a test that swaps the
declared surfaces calls `core.authz.reset_policies()` after the swap (and
`core.surfaces.forget_declarations()`); and **a wall test asserts the
refusal and the absence**, never the outcome the tree happened to produce — a
customer's create at the customer host is a 403 with an `outcome=error` audit
row naming that surface and no new row, because an audit case written against
a successful create pinned the defect as the column's worked example. The
worked wall is `apps/example_portal/tests/test_wall.py`.

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

The worked router and schemas, **choosing a tag key** (the key IS the scope
family a token's ceiling names, and it freezes the day a token could hold it),
**the one error envelope** (its keys are `apps/core/exceptions.py::WIRE_COMMON_KEYS`;
`core.exceptions.wire_refusal` composes it) and **`MeasuredOut`** (a computed number travels with
its basis; the UI never computes one): `references/api-door.md`.

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

The wrong-form/right-form pair for a strict body: `references/api-door.md`.

- **A link to our own host in an `Out` names its surface's builder.** No `Out`
  on the tree carries one today; the first that does builds it with `manage.py
  roads absolute_url` for the surface of the role the link is for (`roads
  surface_for_role`) — or the request's own surface when the reader is the
  caller — so a customer's link lands on the customer host. A bare
  `PUBLIC_BASE_URL` joined to a path outside `core.surfaces` and the settings
  is house rule 84's `hand_url` class: counted, and the ratchet only falls.

## 7 · Workflows — Temporal

**Anything that must wait or retry is a workflow** — a webhook delivery with
backoff, an integration sync, a wait for a human or a signal, a schedule. Not a
thread, not a task queue, not a command on cron. Two files per app, both
discovered by the worker:

- `workflows.py` — `@workflow.defn(name="…")` classes, exported in `WORKFLOWS`. **Deterministic** (house rule 9): the module imports **only** `pilecap.determinism` (and the app's own `types.py`), stdlib `dataclasses` / `datetime.timedelta` and `temporalio.workflow`; the ORM, `pilecap`'s root and the apps are the activities'. No ORM, no `httpx`, no `datetime.now()`, no `random`, no `time.sleep`, no settings read that can vary between runs — and **no import of `activities.py`**: activities are invoked **by name**, because importing them would drag the ORM into a module that has to replay identically years from now. `workflow.now()` for the clock; `workflow.random()` if you truly need randomness; `asyncio.sleep` / `workflow.wait_condition` for waiting; `workflow.execute_activity("<name>", …)` for everything that touches the world.
- `activities.py` — `@activity.defn(name="…")` functions, exported in `ACTIVITIES`, and **plain `def`, not `async def`** (below). **Activities do the I/O, and they call services.** They restore the tenant, the user and the **acting hat** from workflow context (`apps.workflows.context`: the interceptor carries all three as Temporal headers; read them from there, never from a global, never from the payload), are **idempotent** (the same input twice is safe — Temporal retries), and take their retry policy at the call site, not inside.
- `types.py` — the shapes that cross the boundary: plain `@dataclass`es in a module that imports nothing but the standard library. A workflow that took a model instance could not be replayed.

The worked `workflows.py`, `activities.py` and `types.py` — and **what a
workflow argument may hold** (`str`/`int`/`float`/`bool`/`UUID` and nested
dataclasses; three failure modes wearing one error message):
`references/workflows.md`.

- **Never `transaction.on_commit(partial(...), robust=True)` — register a
  named nested `def`.** Django's robust branch formats its error with
  `func.__qualname__`, which a `functools.partial` does not have, so the
  handler whose whole job is to swallow a failing hook raises `AttributeError`
  itself, uncaught, and **every hook queued behind it never runs** — `robust`
  delivering its exact opposite, silently. Proven on this tree (P3 SEC-R3);
  the shape that works is `def x_on_commit(): ...` then
  `transaction.on_commit(x_on_commit, robust=True)`.

**Start anything that waits from a service**, with
`start_workflow_on_commit(*, workflow, arg, tenant, user=None, org=..., id=...)` —
sync, callable inside `transaction.atomic()`, the `id` built by `workflow_id()`
and never random, `org=` the acting hat the run is started under. The full
signature, why each argument is not optional, why **a run row's `error` must name
the cause and not the wrapper**, and why the blessed clock is spelled
`workflow.now()`: `references/workflows.md`.

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

- **Activities are plain `def`**, and every activity in this repository is
  (`apps/events/activities.py`, `apps/example/activities.py`). The ORM is
  synchronous; the worker
  (`apps.workflows.client.build_worker`) is built with an
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

The road is `apps.events.services.emit` — `manage.py roads emit`; after the
commit `events` fans the row out to the tenant's `WebhookEndpoint`s and the
realtime bridge.

- **Emit after the write it describes.** Never from a model's `save()`, a
  signal, or a door.
- Names are `<app>.<resource>.<past-tense verb>`: `orders.order.created`.
  **The payload's road is `apps.core.schemas.event_payload` — `manage.py roads
  event_payload`** — over the `Out` the REST route returns.
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

**Sockets — an app does not write a consumer, it extends the one there is.**
House rule 58. A `consumers.py` dropped into any app is discovered by
`config/asgi.py` and mounted like every other; a consumer written *beside*
`TenantEventsConsumer` rather than under it inherits none of its three refusals
(no principal, no tenant, no self-named group), and a pattern mounted without
`token_auth(...)` is an anonymous door onto a tenant. **Every group name comes
from the bridge's three builders** — `tenant_group`, `org_group`, `user_group` —
never from anything the client sent.

```python
# wrong — discovered, mounted, accepted with no credential, subscribed to a tenant the caller named
class OrderSocket(AsyncJsonWebsocketConsumer):
    async def connect(self):
        query = parse_qs(self.scope["query_string"].decode())
        await self.channel_layer.group_add(f"tenant.{query['tenant'][0]}", self.channel_name)
        await self.accept()

websocket_urlpatterns = [path("ws/orders/", OrderSocket.as_asgi())]

# right — the base's refusals inherited, the credential wrapper on, every group derived
class OrderSocket(TenantEventsConsumer):                       # apps.realtime.consumers
    async def connect(self):
        await super().connect()                                # the three refusals, then the groups

websocket_urlpatterns = [path("ws/orders/", token_auth(OrderSocket.as_asgi()))]
```

The MCP tool snippet, and the other three doors — sockets, inbound webhooks
and connections: `references/other-doors.md`.

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
- **A non-atomic migration (`atomic = False`, e.g. `AddIndexConcurrently`) in
  `core` needs the rewind step-over, and the step-over is LOUD**: a test that
  rewinds `core` inside a transaction cannot run one, so every such migration is
  listed in `_CONCURRENT_ABOVE_0018` (`apps/core/tests/test_roles_are_keys.py`),
  and a new core migration reds `test_0018_is_on_the_one_line_to_the_leaf`
  until it is.
- **Data migrations are separate files**: `RunPython(forward, reverse)` with a
  real reverse (or `RunPython.noop` stated deliberately), using
  `apps.get_model(...)` — never importing the model class. Never edit a
  migration merged to main; add a new one.

## 12 · Tests

**A schedule test asserts about its own ids, never the discovered set.** The
worked tests — the scoped list test, the query-budget pin, the time-skipping
workflow test and why a hand-built handle moves no clock — and the MCP, socket,
org-scoping and pagination siblings — and the standing rules the whole section
turns on (**test the property, not the mechanism**; **no test that cannot
fail**; REST through the mounted API so `TenantMiddleware` runs; one query pin
per list route at seeded scale × k): `references/testing.md`.

- **A test of the template's own shape is DECLARED, never deleted**:
  `@pytest.mark.template_only(reason="…")` (`apps/conftest.py` holds the
  mark). It keys on the tree's fold predicate — the engine's own reading of
  whether `rule_id_namespace:` is declared — never on a file's presence, so a
  product never grows into it by adding a file; where something COULD retire
  the skip, the reason names it. A drive's golden-face copy cases are the
  other kind: they key on the worked face's presence, and retire themselves
  when the face file appears.
- **`accounts`' `instance` fixture homes every tenant** as a worker that is up
  would (`apps/accounts/tests/conftest.py::_home_every_tenant`): the tenants
  that exist get a realm on the fake, and one created later is homed as it
  is asked for. A test whose subject IS a pending home sets it back to
  `pending` itself; a module whose subject is the realm port declares
  `HOMES_ITS_OWN_REALMS = True` and gets no homing at all.

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
#   --loop runs on a verifier box (rung-execution §3; a local one refuses without --here "<rung-id>: <reason>"); the hook runs --fast.
```

`scripts/check.sh` is the gate and it is on main; the legs it runs, and what
each is for, are in `build-contract.md`. Run the script rather than the legs by
hand: the ones you would forget — the house-rules engine, the canary self-test,
the second pytest pass — are the ones that catch the most.

**`mypy` reads `INSTALLED_APPS`, so a disabled app changes what type-checks** —
measured on this tree, with the numbers and what they mean for a rung touching
the optional-app machinery — and the four standing gate facts from the builder's
seat (`--loop` per rung, never the full gate by hand, never piped, your own
database): `references/typing-and-gate.md`.

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
| a `consumers.py` whose consumer extends `AsyncJsonWebsocketConsumer` directly · a `websocket_urlpatterns` entry with no `token_auth(...)` · a group name built at the join | subclass `apps.realtime.consumers.TenantEventsConsumer`, wrap the pattern in `token_auth(...)`, take every group from `tenant_group` / `org_group` / `user_group` (house rule 58) |
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

**Two gotchas, at the site they bite** — a ninja `resolve_` hook dying inside a
`Page`, and mypy narrowing a subscripted expression across statements:
`references/gotchas.md`.

## 16 · Recipes — a family verb adopted on a noun

Each noun-verb family verb is one adoption on the noun's own app, in one
commit, over its road (each recipe opens with `roads <job>`). The worked example of each is on
`Widget` in `apps/example`, **fenced `# golden: <verb> begin` / `# golden:
<verb> end` around every block a product copies**, and
`quality/tests/test_golden_copy.py`'s verb arm copies exactly those blocks
into a throwaway app with the one rename `Widget`→`Gadget` and proves they
still build, check and pass. A block you copied that needed a hand edit beyond
that rename is a finding against the example, not a step.

**A fence holds what a product copies; a word can live outside every fence.**
The worked second surface (`apps/example_portal`, fenced `# golden: portal`)
is the instance: a product renaming the portal noun copies the app and the
customer folder pair whole, and finds the word everywhere else by grep —

```bash
git grep -l -i portal -- . ':!apps/example_portal' ':!frontend/src/screens/customer' ':!frontend/src/app/(customer)' ':!docs' ':!*.md'
```

— which is the list, re-derived on every tree. Among what it prints, the
files measured as needing the rename's edit when the portal landed — each a
declaration, a pinned population or a pinned table, not a passing mention:
`apps/conftest.py`, `apps/core/api/frozen_families.py`, `quality/budgets.yaml`,
`quality/partition.yaml`, `quality/rules.yaml`, `frontend/src/api/client.ts`,
`frontend/src/copy/lexicon.ts`, `frontend/src/kit/routes.test.ts`. The
rest of what it prints is mixed, and each kind is read differently: platform
tests and quality fixtures that drive the worked surface; road `example=`
strings pointing into the portal's own tests (`apps/core/surfaces.py`); the
published document and the generated client (`frontend/openapi.json`,
`frontend/src/api/generated/`), which regenerate rather than edit; the
portal's fenced blocks in shared files (`frontend/src/kit/routes.ts`,
`frontend/src/copy/customer.ts`), which the copy carries; comments and
examples that use the word as a sample key (`deploy/`, `quality/gate.py`);
docstrings that cite the worked portal as the instance of a mechanism
(`apps/core/authz.py::_attach_default_roles`,
`config/settings/discovery.py::switched_off`), which a rename edits as
prose; and
a vendored bundle that merely contains the word (`vendor/`), which nobody
edits.

**Four lines every recipe below shares** (and one about the fences themselves):

- **A fragment two or more verbs share is fenced ONCE, with the verb list** —
  `# golden: version move begin` … `# golden: version move end`: the drive
  (`quality/tests/test_golden_copy.py`) reads a fence as a begin or an end for
  every verb it names, so each verb's copy takes the block when ITS verb is in
  the list. Use it for a block two or more verbs share (the noun's imports, its
  class line, its detail route, a service body several copies need); a block
  ONE verb owns keeps the single-verb form (`# golden: merge begin`). Fences of
  different verbs may overlap but never nest within one verb, and a list names
  only verbs the drive knows — the roads plus `attach` and `import` — or the
  drive refuses it (exit 2) naming the word. The worked example lists the
  verbs in their adoption order (archive, version, move, bulk, history,
  duplicate, attach, merge, import), and a block belongs to its own verb and to
  every verb after it.

- **A fenced import block is followed by `# isort: split`** (`apps/example/api.py`,
  `services.py`): the copy drops the lines outside the fence, and without the
  split the formatter re-sorts the fenced imports into the unfenced ones and
  the copy no longer matches its fence.
- **The migration comes LAST, after the doors** — a marker on the model alone is
  a set of `djb.E074` findings (the road it demands does not exist yet), and
  `makemigrations` runs the system checks. So `makemigrations <app>` is each
  recipe's final step; `--skip-checks` never appears in one.
- **A refusal sentence carries no backticked key.** A registered `fact` (and a
  `detail`) is read by a person: it says the fact in words — "the answer says
  which version it has now" — and the key a machine branches on rides
  `wire_extra`, never the sentence (`apps/core/tests/test_refusal_sentences.py`
  reads the whole registry).
- **Every refusal code declares `status=` at its own `register_refusal` site,
  and nothing else is typed** — template and product alike (ADR core-23). There
  is no code→number table to append to: `CODE_STATUS` is derived from the
  registry, and `apps/core/tests/test_refusal_status.py::test_the_template_publishes_at_least_its_floor`
  holds the template's published codes above `TEMPLATE_PUBLISHED_FLOOR` (the
  template's apps read from `quality/partition.yaml`), so a code that drops
  out of `x-refusal-codes` reds and a new one is admitted by its own
  declaration. The floor only falls by a human reading the count it prints.
- **`allowed_acts` lives on the two viewer doors only** — REST and MCP, which
  rule 17 keeps equal. It is a fact about (row, viewer) and an event has no
  viewer: `roads event_payload` drops it at any depth, and `emit` refuses a
  payload carrying one. A noun names its own example with
  `allowed_acts: list[str] = acts_field("update", "archive")`; an act is offered
  only where its `<noun>-<verb>` door is mounted. A face re-reads the row after
  a socket frame to learn what it may press now.

### Adopt archive in one commit

`roads archive` (`apps.core.verbs.archive_row`).
**An archivable noun carries its whole road** (house rule 74, `roads
family_doors`); **append-only and archivable are disjoint** (house rule 75).
In the noun's app, one commit:

1. **The model** — `class Widget(OrgScopedModel, Archivable)`: the mixin AFTER
   the scoped base (the reverse order is a `TypeError`); its migration — two
   nullable columns, expand-only — is step 8, after the doors. `for_tenant()`
   now hides archived rows everywhere; `.including_archived()` and
   `.archived_only()` are the only widenings.
   **Rule 81: the archive's widenings are the only widenings** — a hand
   `.filter(archived_at__isnull=False)` after `for_tenant()` answers `[]` with
   no error, because the rows it asks for were left out a step earlier.
2. **The policy** — `POLICIES = {"widget.archive": may_archive, "widget.restore":
   may_archive}` in the app's `policies.py` (`core.policies.may_archive`, which
   refuses the system actor). The two keys are DERIVED; write no prose for them
   unless the derived sentence is wrong.
3. **The blockers, if a child holds the noun** — the CHILD app drops
   `archive_blockers.py` exporting `BLOCKERS = {"widget": fn}` answering
   `tuple[Blocker, ...]` (`core.blockers`); the parent never imports the child.
4. **The service pair** — `archive_widget` / `restore_widget`, `@service`,
   keyword-only `tenant`, `actor`, `widget`: `may_be_named` → `NotFound`,
   `require(actor, "widget.archive", widget)`, then
   `core.verbs.archive_row(tenant=…, actor=…, row=widget, noun="widget")` and
   `emit()` the `<app>.<noun>.archived` event (declared in `events.py`) ONLY when
   it answered `changed=True`. Restore mirrors it with `restore_row` and
   `.restored`. Every OTHER write on the noun calls
   `core.verbs.require_live(widget, noun="widget")` first (`archived`, 409).
   **Rule 82: every other write on an archivable row calls `require_live`** — a
   `<verb>_<param>(*, <param>: Noun)` service without it is refused, including
   the writes the noun had before it adopted the mixin.
5. **The schema** — `class WidgetOut(ArchivedOut)`; never re-declare the two
   fields. The events carry `event_payload(WidgetOut.from_orm(widget))`.
6. **The doors** — `POST /widgets/{id}/archive/` (`url_name="widget-archive"`)
   and `/restore/` (`widget-restore`) **taking no body** (the press is the
   whole request; rule 74 refuses a body there, and a bodiless press would
   otherwise answer 422) and answering `WidgetOut`, each with
   `@also_refuses("archive_blocked")` (restore: `"restore_blocked"`) — ADDED to
   the derived set, never re-typing it (`@refuses` is the narrowing form, for a
   route whose derivation is wrong) — a repeat answering 200; the list takes
   `?show=live|archived|all` (default `live`, `archived` the one reader of
   `archived_only()`); the detail widens with `including_archived()` so an
   archived row answers read-only. The MCP twins `archive_widget` /
   `restore_widget` call the same services (rule 17 derives their names).
7. **The tests** — the pair over the wire on both doors (the parity module,
   through `apps.core.tests.doors.assert_four_doors` with a SECOND viewer), a
   blocked archive naming its blocker, a repeat press unchanged, a member
   refused, the archived row read-only and every other write `archived`.
8. **The migration** — `makemigrations <app>`, last.

### Adopt version in one commit

`roads version_row` (`apps.core.concurrency.require_version`).
**A versioned row's writes move `updated_at`** (house rule 76) — the version
IS that stamp, no column. Opt-in; the noun that adopts it makes `version` REQUIRED on
every write that edits it (house rule 74 reads the update body). One commit:

1. **The model** — add `Versioned` (`core.models`) to the bases, after the
   scoped base: `class Widget(OrgScopedModel, Archivable, Versioned)`. No
   migration.
2. **The schemas** — the `Out` adds `VersionedOut` to its bases (`version:
   int`, read off the model's `version` property); the `Patch` inherits
   `VersionedIn` instead of `StrictIn`, so a body without `version` is
   `invalid_body` naming it.
3. **The service** — lock, compare, write, and name the stamp:
   `locked = …select_for_update().get(pk=widget.pk)`,
   `require_version(locked, version)` (409, `current_version` on the wire), then
   `locked.save(update_fields=[…, "updated_at"])`. A queryset `.update()` on
   the noun passes `updated_at=now()`.
4. **The doors** — the update route and its MCP twin take the same `Patch`,
   and the route adds `@also_refuses("stale_version")` to its derived set.
5. **The tests** — a stale save refused with the row unchanged and
   `current_version` on the wire; the current one answering a NEW `version`.

### Adopt move in one commit

`roads move` (`apps.core.verbs.rehome`). **A movable noun carries its move
road** (house rule 74) and **its ledger stays where it was written** —
`rehome` carries every MUTABLE row that derives its organization
from the noun (`derive_org_from`) and refuses `move_blocked` over an
APPEND-ONLY one. One commit:

1. **The model** — add `Movable` after the scoped base; set
   `move_owner_field = "owner"` if the owner is handed over too. No migration.
2. **The policy** — `POLICIES["widget.move"] = may_move`
   (`core.policies`, `@refuses_system`, asked at BOTH ends).
3. **The service** — `move_widget(*, tenant, actor, widget, organization,
   version)`: `may_be_named` on the row (`NotFound`), and the DESTINATION by the
   hat's subtree path — `is_descendant_path(organization.path, actor.org.path)`
   in this tenant, else `NotFound` (`may_be_named(actor, <Organization>)` is
   always False: an organization names no `organization`); an `owner_id` on a
   noun with no `move_owner_field` is refused by `rehome` (`invalid`),
   `require(actor, "widget.move", widget)` and
   `require(actor, "widget.move", organization)`, then
   `widget, changed = core.verbs.rehome(widget, organization)`, and emit
   `<app>.<noun>.moved` (naming both nodes) only when `changed`.
4. **The schemas** — the body is `MoveIn` (`VersionedMoveIn` for a
   `Versioned` noun); the `Out` adds `HomedOut` (`organization_name` — a
   list answering it `select_related("organization")`s).
5. **The doors** — `POST /widgets/{id}/move/` (`widget-move`,
   `@also_refuses("move_blocked")`) and the MCP twin `move_widget`; the sheet's destinations are
   `GET /organizations/?can=widget.move`, never a per-noun read.
6. **The tests** — a move carrying a mutable child, a ledger blocking with
   nothing moved, the same node unchanged, a destination outside the subtree
   `not_found`, a member refused.

### Adopt bulk in one commit

`roads bulk` (`apps.core.bulk.run_bulk`). **A noun declaring `bulk_verbs`
carries `<noun>-bulk`** and the single road of every verb it lists (house rule
74). The items run inside ONE transaction, each a savepoint with its own audit
row: `done`, `unchanged` (so a retry converges) or `refused` (the single
call's body); an unhandled exception rolls back the batch (a 500 the same
`Idempotency-Key` retries). One contract on both doors. One commit:

1. **The model** — `bulk_verbs: ClassVar[tuple[str, ...]] = ("archive",
   "restore", "move")`.
2. **The schemas** — the body is a discriminated union on `verb` of the core
   `BulkArchiveIn` / `BulkRestoreIn` / `BulkMoveIn` the noun lists; the answer
   `BulkOut`, its result's `item` narrowed to the noun's `Out`.
3. **The door** — `POST /widgets/bulk/` (`widget-bulk`), calling `run_bulk`
   from the door and never from inside a service of its own, `resolve=` through
   `core.verbs.resolve_subject`; the MCP twin is `bulk_widgets` (rule 17).
   An `Idempotency-Key` replays the whole answer.
4. **The tests** — a partial batch in order (`done, refused, done`), a
   sibling-branch id `not_found`, a replay answering the identical body.

### Adopt history in one commit

`roads history` (`apps.core.selectors.list_history`) — no table, no migration.
**A noun declaring any family marker beyond archive carries
`<noun>_history-list`** (house rule 74). One commit:

1. **The door** — `GET /widgets/{id}/history/` (`widget_history-list`),
   `@paginate(CursorPagination)` over
   `list_history(tenant=…, actor=…, row=widget)`, answering
   `list[HistoryEntryOut]`; the MCP twin `list_widget_history` answers a
   `HistoryPage` through `cursor_page`.
2. **The tests** — create, update, archive, restore read back as four rows
   newest first, `changed_fields` naming what the update sent; a sibling
   branch's row `not_found`.

### Adopt duplicate in one commit

`roads duplicate` (`apps.core.verbs.duplicate_row`). **A duplicable noun
carries `<noun>-duplicate`** (house rule 74) and **every concrete editable
field is on one side** of its declaration. A duplicate IS a create. One commit:

1. **The model** — add `Duplicable` after the scoped base and declare
   `duplicate = Duplicate(copies=("notes", "policy"), resets=("name", "owner",
   "onboarded_at", "external_ref"))` (`core.models`). **What the copy owns is
   in `resets`**: a NOT NULL owner, and a name a uniqueness (name per owner)
   would otherwise collide on, are reset — never copied — and the service
   fills them. A CASCADE child named in `copies` copies too, an append-only
   child never does (naming one is `ImproperlyConfigured`). **A duplicate
   key's constraint is the model's, not the field's**: the noun's own `Meta`
   declares `constraints = [..., duplicate_key_constraint()]` (`core.models`;
   `core.E001` when it is missing) — a constraint a field added behind the
   migration's back is one a fresh database could not migrate.
2. **The service** — `duplicate_widget(*, tenant, actor, widget,
   idempotency_key="")`: `may_be_named` on the source (`NotFound`),
   `require_live(widget, …)`, `require(actor, "widget.create")` at the hat,
   then `copy, created = core.verbs.duplicate_row(tenant=…, row=widget,
   organization=actor.org, idempotency_key=…, fill={"owner": actor.user,
   "name": f"Copy of {widget.name}"})` — every `fill` key must be in `resets`
   (else `TypeError`), set BEFORE the copy's one save; the copy lands at the
   acting hat and is `full_clean()`ed first, so a clash on a unique constraint
   is `invalid` with nothing written, never a 500 (a clash over several fields
   answers `__all__`; the service may say it as the field it is, as
   `duplicate_widget` says `name`). Emit `<app>.<noun>.duplicated`
   (`event_payload(...)`, which carries `duplicated_from_id`) only when
   `created`. A repeated key answers the FIRST copy (the `(tenant,
   duplicated_from, duplicate_key)` partial unique the mixin's key field
   brings).
3. **The doors** — `POST /widgets/{id}/duplicate/` (`widget-duplicate`) → 201
   the copy's `Out`; the MCP twin `duplicate_widget`. `allowed_acts` offers
   `duplicate` on a live row where the actor may create at the hat.
4. **The tests** — copies carried, resets reset and filled (the presser owns
   the copy), the copy at the hat, a ledger child not copied, a repeated key
   answering the first copy, a clashing second copy `invalid`.
5. **The migration** — `makemigrations <app>`, last.

### Adopt merge in one commit

`roads merge` (`apps.core.verbs.merge_rows`). **A mergeable noun is archivable
first** and carries `<noun>-merge`, its dry run `<noun>_merge-detail` and
`<noun>.merge` (house rule 74); **every foreign key into it is re-pointed or
kept**. The loser survives as a tombstone: archived, with
`merged_into` naming the survivor; its reads answer read-only, its writes
refuse `merged`. One commit:

1. **The model** — add `Mergeable` after `Archivable`; list every FK into the
   noun that STAYS on the loser in `merge_keeps = {"entries": "an append-only
   ledger stays where it was written"}` (reverse accessor, or
   `app.Model.field` for a hidden one). Every other FK's owning app declares
   `REPOINTERS[<noun>]` in its `merge_repointers.py`.
2. **The policy** — `POLICIES["widget.merge"] = may_merge` (`core.policies`,
   `@refuses_system`, asked of BOTH rows).
3. **The service** — `merge_widget(*, tenant, actor, widget, into, version,
   into_version)`: reach and `require(actor, "widget.merge", …)` on both, both
   versions, then `outcome = core.verbs.merge_rows(tenant=…, actor=…,
   loser=widget, into=into, noun="widget")` and emit `<app>.<noun>.merged`
   (the survivor's payload, `loser_id`, and `repoints: [{title, left}]` from
   `outcome.repoints` — the APPLY's answers, never the dry run's) only when
   `outcome.changed`. The dry run is `core.verbs.merge_counts(...)`.
4. **The doors** — `POST /widgets/{id}/merge/` (`widget-merge`, `MergeIn`,
   `@also_refuses("merge_blocked", "merged")`) and
   `GET /widgets/{id}/merge/?into=` (`widget_merge-detail`); the MCP twins.
5. **The tests** — the repointed attachments, the tombstone read-only, a write
   on the loser `merged` naming the survivor, a chain compressed, the same
   pair again unchanged, a blocker with nothing written. A noun with a delete
   service asks `core.verbs.require_no_merged_losers(row, noun=…)` before it
   deletes and its route adds `merge_survivor` to `@also_refuses`: the losers'
   tombstones name the survivor, and PROTECT would otherwise answer a generic
   `conflict`.
6. **The migration** — `makemigrations <app>`, last.

**A repointer keeps seven promises** (`core.verbs.Repointer`'s docstring;
`apps/core/tests/test_repointer_conformance.py` measures every `"*"` one):
(1) `count` answers the rows that will LEAVE the loser (moved, or collapsed
onto a pair the survivor holds) and `repoint` the rows that left — equal on an
unmoved world; (2) `repoint` re-resolves BOTH rows for the actor, an
unreachable one `NotFound` with nothing changed; (3) one `<app>.<kind>.moved`
per moved row, a collapse emitting its own leaving event; (4) the population is
tenant-wide (`for_tenant(t).including_archived()`, a rule-24 valve naming the
merge's two-record authorization); (5) every moving write stamps `updated_at`;
(6) the authorization is the merge's, the repointer's service `# door:`- and
`# authz:`-valved saying so; (7) **a repointer is a no-op for a kind the noun
does not take** — where the noun's `attachments` does not name the owner's
word, `count` and `repoint` answer 0, never a refusal that stops the merge.
Every `"*"` owner ships
`tests/attach_specimen.py::attach(*, tenant, actor, subject)`.

### Adopt import in one commit

`roads import_rows` (`apps.core.verbs.Importer`). **An imported noun has a
create road** (rule 74) — an import applies the noun's OWN services, row by
row. In the noun's app, one commit: an `importers.py` exporting
`IMPORTERS = {"widget": Importer(row=WidgetRow, natural_key=…, apply=…)}`:
`row` a `StrictIn` whose fields are the file's header,
`natural_key(*, tenant, actor, row)` finding the existing row read-only AT
`actor.org` — the run's hat, where the apply will look, so the preview's
`update` is a promise the apply keeps — and `apply(*, tenant, actor, row)`
finding its row by calling that same `natural_key`, then the noun's own
create/update, answering `(obj, "created" | "updated" | "unchanged")`. The imports app finds it; nothing
registers it. The tests drive one file through the import door.

### Adopt attach in one commit

`roads attach` (`apps.core.verbs.resolve_subject`). **A noun takes notes, files
and tags by declaring `attachments = ("notes", "files", "tags")`**; the rows
live in the three owner apps, and a noun listing `tags` answers
`tags` on its detail (rule 74). **The landing law** (measured once across every
owner by `apps/core/tests/test_attach_conformance.py`): an attachment lands at
its SUBJECT's organization; a TENANT-WIDE subject has none, so it lands at the
ACTING HAT — never the root, because visibility is down-only and a branch
author could not read back a root-landed note (rule 55's root-only writes
govern a tenant-wide ROW, never the org-scoped link). Two rulings follow from
it, for the owners to carry:

- **One per pair follows the landing.** A tenant-wide `(tag, subject)`
  uniqueness answers `conflict` to a second hat attaching the same word — a
  refusal that reveals a link the second hat cannot see, which is the
  existence leak reach refusals exist to prevent (not-there and not-yours are
  one answer). The pair is unique per hat: `(tag, subject, organization)`, and
  a reader above two hats sees the word once per hat that said it.
- **A merge does not re-land.** A repoint keeps each moved attachment's
  organization when the survivor is tenant-wide (a repoint changes WHAT the row
  is about, never WHO may read it — re-landing at the merging actor's hat would
  widen a branch's private note to the tenant as a side effect nobody pressed);
  for an org-scoped survivor the attachment moves to the survivor's
  organization, where its subject lives.

