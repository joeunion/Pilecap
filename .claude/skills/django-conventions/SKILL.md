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

**One level down, the tenant is a tree.** A row one *part* of the tenant owns
inherits `OrgScopedModel` and is read `.for_tenant(t).visible_to(actor_or_org)` —
both halves, every time; inherited configuration resolves upward through
`governing()` and never widens visibility; a reference handed to a service passes
`core.authz.may_be_named`; a row that inherits its branch declares
`derive_org_from`. All four, wrong form and right form:
`references/hierarchy-and-scoping.md`. A ledger declares `append_only = True` and
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
invisible, which is the thing that costs merge cycles to rediscover. **And every
refusal speaks the three-move grammar** — `code`, `fact`, structured `remedies`,
declared at import beside the class that raises it, composed once by
`core.exceptions.wire_refusal`. Both, in full: `references/services-and-refusals.md`.

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
**the one error envelope** (`{detail, code, errors?, remedies?}` from the single
mapper in `config/api.py`) and **`MeasuredOut`** (a computed number travels with
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

## 7 · Workflows — Temporal

**Anything that must wait or retry is a workflow** — a webhook delivery with
backoff, an integration sync, a wait for a human or a signal, a schedule. Not a
thread, not a task queue, not a command on cron. Two files per app, both
discovered by the worker:

- `workflows.py` — `@workflow.defn(name="…")` classes, exported in `WORKFLOWS`. **Deterministic** (house rule 9): the module imports **only** stdlib `dataclasses` / `datetime.timedelta`, `temporalio.workflow`, and the app's own `types.py`. No ORM, no `httpx`, no `datetime.now()`, no `random`, no `time.sleep`, no settings read that can vary between runs — and **no import of `activities.py`**: activities are invoked **by name**, because importing them would drag the ORM into a module that has to replay identically years from now. `workflow.now()` for the clock; `workflow.random()` if you truly need randomness; `asyncio.sleep` / `workflow.wait_condition` for waiting; `workflow.execute_activity("<name>", …)` for everything that touches the world.
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
