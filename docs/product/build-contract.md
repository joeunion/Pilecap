# Build contract — layout and interfaces every layer agrees on

**Status: standing.** The layout tree is kept dedrifted against the live tree
by periodic reconciliation. Builders work in parallel on disjoint
paths; this file is how their work fits together without talking. A builder
that needs to deviate says so in its report; it does not edit this file —
the docs-truth protocol applies (the rung reports its diff, the PM applies
at merge).

## Repository layout

```
Pilecap/
├── pyproject.toml              # uv project; deps; ruff/mypy/pytest/import-linter config
├── uv.lock
├── compose.yaml                # name: djangobootstrap (pinned) — the ONE stack every checkout shares; postgres:18 (the ruled major) · redis · temporal (+ UI) · zitadel · mailpit · minio · meilisearch · the observability pair; app + worker run on the host; compose.yaml itself is the authority on services and pins
├── .env.example                # every variable settings reads, with safe local defaults
├── manage.py
├── config/                     # the Django project package — edited by discovery-laying rungs only
│   ├── settings/{__init__,base,local,test,production}.py
│   ├── urls.py (owns the version segment: API_PREFIX = "api/v1/") · api.py (NinjaAPI; discovers apps/*/api.py; mounts <label>/ or <PREFIX>/ under it; exception handlers) · asgi.py (Channels ProtocolTypeRouter:
│   │   http → Django+ninja, /mcp → MCP server, websocket → discovered consumers) · wsgi.py
│   ├── temporal.py             # client factory, worker assembly (discovers apps/*/workflows.py + activities.py), task queue names
│   └── mcp.py                  # MCP server assembly (discovers apps/*/mcp.py tools), token auth bound to user+tenant
├── apps/                       # every Django app lives here; INSTALLED_APPS is DERIVED from apps/*/apps.py ("apps.<name>")
│   ├── core/                   # BaseModel · Tenant · Organization (materialized path) · Membership · TenantScopedModel /
│   │   │                       #   OrgScopedModel · ScopedQuerySet/Manager · middleware (request.tenant X-Tenant; resolve_org X-Org —
│   │   │                       #   the one hat resolver all doors call) · service.py (@service) · authz · audit (AuditEntry) ·
│   │   │                       #   exceptions (+ the refusal registry/composer) · log · observability · lifecycle/schedules registries ·
│   │   │                       #   api/ (CursorPagination, docs, scopes: FROZEN_FAMILIES) · health (/readyz organs) · admin (ServiceModelAdmin)
│   │   └── management/commands/introspect.py   # real models, routes, consumers, tools, workflows, settings → JSON
│   ├── accounts/               # User (custom, email identifier) · ApiToken · auth.py (API_AUTH, ApiTokenAuth) · oauth.py (resource-server
│   │                           #   validation) · zitadel.py (rule 27's ONE identity-platform door) · lifecycle · services.py · admin ·
│   │                           #   api.py (`/api/v1/users/` deactivate/erase; `/api/v1/tokens/`; `/api/v1/auth/`) · mcp.py twins
│   ├── comms/                  # the ONE sender: send() (rule 25 — consent, quiet hours, suppression inside it) · Message aggregate
│   │                           #   (+ Recipient, ChannelPreference, SuppressionSurge; MessageTemplate/DeliveryPolicy versioned per D9;
│   │                           #   MessageEngagement append-only) · providers.py (channel registry: email + SMS transports) ·
│   │                           #   api.py + mcp.py · delivery workflows/activities · events.py
│   ├── connections/            # Connection (per-tenant, encrypted credentials) · client.py (the httpx factory) · providers registry ·
│   │                           #   OAuth callback pattern · one inbound webhook receiver using events · api.py
│   ├── example/                # one ORG-scoped model end to end: Widget, services, schemas.py, api.py (PREFIX = "widgets"), admin,
│   │                           #   mcp.py, workflows.py + activities.py, tests, migrations/, max_migration.txt
│   ├── events/                 # Event + Outbox + WebhookEndpoint + Delivery; emit(); dispatch workflow (fan-out: signed
│   │                           #   deliveries with retries/dead-letter + realtime push); inbound receiver helper ·
│   │                           #   api.py (endpoints + `/api/v1/event-types/` catalogue) · mcp.py twins
│   ├── exports/                # Export (a tenant's data, out) · census.py (the DERIVED archive population) · build workflow through
│   │                           #   real Temporal; the archive lands through files' `store_stream` under the version-key grammar ·
│   │                           #   api.py (PREFIX = "exports"; download is a 302 onto the presign) · mcp.py · the erasure interlock
│   ├── files/                  # ADR files-2: StoredFile + FileVersion (immutable per-version keys `t/<tenant>/f/<file>/v/<n>`) ·
│   │                           #   storage.py — THE one boto3 seam (MinIO dev / S3 prod; presigns both directions; bytes never transit
│   │                           #   Django) · services (two-phase upload; store_bytes/store_stream need a person-carrying actor) ·
│   │                           #   FinalizeUpload workflow · meters.py (`files.storage.bytes` → usage) · policies · events.py ·
│   │                           #   (REST/MCP doors arrive in a later plan — until then service/workflow callers only)
│   ├── search/                 # NO ORM models (the Meili document is the projection; an ADOPTING app owns its tsvector column) ·
│   │                           #   engine.py — the ONE Meilisearch client (rule 33's fence) · registry.py (SEARCHABLES discovered from
│   │                           #   `apps/<x>/search.py` declarations) · selectors.py the read chokepoint (tenant+org scoping at query
│   │                           #   time) · api.py (PREFIX = "search") + mcp.py · indexer activities off the events spine · rebuild
│   │                           #   workflow with boot reconcile
│   ├── usage/                  # UsageEntry (append-only, org-scoped) · record_usage — THE shared metering seam (idempotent replay;
│   │                           #   corrections supersede, never edit) · meters.py (`<app>.<noun>.<unit>` grammar, import-validated) ·
│   │                           #   api.py (PREFIX = "usage", read-only, MeasuredOut) + mcp.py · no write door BY DESIGN (`# door:` valve)
│   ├── workflows/              # Temporal primitives: WorkflowRun (visibility), start_workflow / start_workflow_on_commit + · api.py (REST `/api/v1/runs/` list/get + `POST {id}/replay/` + `POST {id}/cancel/`) · mcp.py (`list_runs`, `get_run`, `replay_run`, `cancel_run`)
│   │                           #   workflow_id(), context.py (interceptor; current_tenant/current_user_id/workflow_context),
│   │                           #   types.py, the worker entrypoint
│   └── realtime/               # Channels consumer: auth, join tenant group, receive events; the push bridge
│                               #   (no apps/mcp: the token model and service are in accounts, the server in config/mcp.py)
├── quality/                    # house-rules engine: rules.yaml · checks.py · gate.py · canary/ · negative/ ·
│                               #   budgets.yaml (rising ceilings) · proving.yaml + proving_cost.py (what proving costs) ·
│                               #   partition.yaml + partition.py (the platform partition: the lockfile written once at the
│                               #   freeze, the two-part skip key, the canaries — docs/product/partition-closure.md is the design)
├── scripts/                    # EVERY executable here owes a row in docs/product/instruments.md (the gate's goalpost
│   │                           #   census enforces it) — that file is the enumeration; this tree names only the load-bearing few:
│   ├── check.sh                # THE gate: (no arg)=full · --fast · --loop   exit 0/1/2
│   ├── gate_ledger.sh          # verdict ledger keyed on tree hash + the caller field (sourced by check.sh);
│   │                           #   and the partition's verdicts, keyed on <closure hash>:<discovery digest>
│   ├── gate_lease.sh           # the MACHINE-WIDE full-gate lease: a second full gate WAITS, out loud
│   ├── rung_start.sh           # one command to a ready worktree: reset, venv, database, introspect dump
│   ├── test.sh                 # pytest wrapper; owns its exit code; never piped
│   ├── setup.sh                # fresh clone → running: uv sync, hooks, compose up, DB, migrate
│   ├── db.sh                   # per-worktree database name + create/drop helpers (template-clone fast path)
│   ├── serve.sh · worker.sh    # uvicorn · the Temporal worker
│   ├── loop_health.py          # reads docs/product/readouts.md; exit 0/1/2
│   └── githooks/{pre-commit,pre-push}
├── deploy/                     # provisioning, release, teardown, observability — the staging/production posture as code
├── docs/product/               # ledgers (skeletons + one marked worked example each) · cycles/ · architecture.md · build-contract.md
├── docs/runbooks/              # operator procedures (deploy.md — the runbook a stranger follows literally)
├── .claude/skills/product-manager/   # the method (SKILL.md + references/dispatch-briefs.md)
├── .claude/skills/django-architect/  # what the engineering lead loads before decomposing
├── .claude/skills/django-conventions/ # what every builder loads before writing Django
├── .claude/skills/rung-execution/    # how a rung is EXECUTED: baseline, gate discipline, failing-test-first, the report contract
├── .claude/skills/platform-primer/   # the arrival map — a fresh session loads it first
├── CLAUDE.md · README.md · .gitignore
```

## Ownership

> **The dispatch ledger in `docs/product/in-flight.md` is the one authority on
> which rungs ran and returned** — this file stopped tracking rung status in
> cycle 0 and will not resume; a table here and a ledger there answering the
> same question is drift with a countdown. What remains is the *ownership
> principle*: **the app entries in the layout tree above are the ownership
> map** — one app is one rung's territory, one builder at a time (the
> schema/collision discipline in CLAUDE.md); disjoint paths per concurrent
> rung; the only rung that edits `config/` or `pyproject.toml` is one that
> holds the tree alone, and the declared union-at-merge surfaces
> (`quality/budgets.yaml`, `apps/core/api/frozen_families.py`'s
> `FROZEN_FAMILIES` line — deliberately moved out of `scopes.py`,
> and out of the partition's closure with it) are the PM's to reconcile, never a second builder's to hold.


## Discovery conventions (what A2 lays; what every later app relies on)

- **Registration:** by discovery, never by editing `config/` or `pyproject.toml`. **`INSTALLED_APPS` is derived from `apps/*/apps.py`** — a package under `apps/` with an `AppConfig` is installed. An app declares what it may import on its own `AppConfig` (`depends_on`); house rule 7 enforces it; `import-linter` keeps only the fixed layer contract (`core` ← `accounts` ← platform ← domain). `config/settings/discovery.py` derives it today.
- **REST:** `apps/<x>/api.py` exposes `router: ninja.Router`; `config/api.py` imports every installed app's `api` module if present and mounts it under the version segment `config/urls.py` owns (`API_PREFIX = "api/v1/"`) at **`/api/v1/<label>/` unless the module names `PREFIX`**, then `/api/v1/<PREFIX>/` (the example app: `PREFIX = "widgets"` → `/api/v1/widgets/`; OpenAPI at `/api/v1/docs`). **An app never spells the version segment**; moving to `v2` is a change to `config/urls.py`, not a sweep of every app. Auth default on the `NinjaAPI` is `apps.accounts.auth.API_AUTH` (`SessionAuth` + `ApiTokenAuth`); **every route carries an explicit `auth=` — on its router or on the route — never `auth=None` outside the `rules.yaml` allow-list.** Lists are `@paginate`d through the one seam, `apps.core.api.CursorPagination` — cursors, not page numbers (ADR core-18, `apps/core/api/pagination.py`); the envelope is `{"items", "has_more", "next_cursor", "count"}`, `?cursor=` and `?limit=` are the controls, and **`count` is `null` unless the caller sends `?include_count=true`** (`?page=`/`?page_size=` are gone, not deprecated). Exception handlers live once in `config/api.py`: `ValidationError` → 400, `IntegrityError` → 409, `PermissionDenied` → 403, `DoesNotExist` → 404. **One envelope, always: `{"detail", "code"}` plus `"errors"` when the refusal names fields** (`on_domain_error`) — `code` is what a client branches on, and `architecture.md` is the authority the code agrees with.
- **MCP:** `apps/<x>/mcp.py` exposes `register(server)`; `config/mcp.py` builds the server, discovers and calls each. `config.mcp.TokenAuthMiddleware` resolves the bearer token once (the same `authenticate_token` service as `ApiTokenAuth`) and leaves a `Principal(user, tenant)` on the ASGI scope; a tool reads it with `apps.core.mcp.principal(ctx)` and calls services only.
- **Sockets:** `apps/<x>/consumers.py` exposes `websocket_urlpatterns`; `config/asgi.py` concatenates them under `AuthMiddlewareStack` + a tenant middleware.
- **Workflows:** `apps/<x>/workflows.py` exposes `WORKFLOWS: list[type]`, `apps/<x>/activities.py` exposes `ACTIVITIES: list[callable]`; `config/temporal.py` assembles one worker on task queue `settings.TEMPORAL_TASK_QUEUE` (default `djb-main`, per-worktree suffix from `db.sh`'s branch sanitiser so two worktrees' workers never steal each other's tasks). `workflows.py` imports only stdlib dataclasses/`timedelta`, `temporalio.workflow` and the app's `types.py`; activities are invoked **by name**. A service starts a run with `apps.workflows.services.start_workflow_on_commit(*, workflow, arg, tenant, user=None, org=None, id, task_queue=None)` — `id` required and deterministic, built by the keyword-only `workflow_id(*, tenant, app, noun, key)`; the async `start_workflow(..., client=)` is for callers already on the loop. **`org` is the acting hat the run is started under**: omit it and every activity in the run acts for the whole tenant rather than for the branch that asked. Tenant, user **and org** travel as workflow **headers** (repeated in the memo) via `TenantContextInterceptor` and are restored in activities by `current_tenant()` / `current_org()` / `current_user_id()` / `workflow_context() -> tuple[Tenant | None, str | None, Organization | None]` — **three** values. Activities are plain `def` and run in the worker's `activity_executor=ThreadPoolExecutor`; each calls `close_old_connections()` at both ends.
- **Events:** `apps.events.services.emit(*, name: str, tenant, payload: dict, actor=None)` — **keyword-only, the name included**, because it is a `@service` and house rule 13 refuses a positional parameter at import time. It writes `Event` + `Outbox` atomically with the caller's transaction (`transaction.on_commit` starts the dispatch workflow). Subscribers are data (`WebhookEndpoint` rows per tenant) and the realtime bridge; nothing imports `events` except to `emit`.
- **Introspect** carries a section per door: `routes`, `tools`, `consumers`, `workflows`, `activities` — each read from the real discovered registry, never from a list.

## Interfaces

**Gate** — `./scripts/check.sh [--fast|--loop]`
- `--fast`: ruff (lint+format check) · mypy · import-linter · house rules · `makemigrations --check --dry-run` · linear-migrations check · goalpost census (every executable instrument outside `apps/`/`config/` owes a row in `docs/product/instruments.md`; an uncensused one is exit 2) · db-pin (this checkout's .env DATABASE_NAME pin vs the derivation; a disagreement without a `# pinned` marker is exit 1 naming both names). No services needed beyond what mypy/django needs to import settings. Target < 60 s. **Pre-commit runs this.**
- `--loop`: `--fast` + `check --deploy` + the changed-files secret scan + ONE pytest pass over the derived test tier (fast tier + the rung's own app in full, the tier choice printed every run; a shared-test-infra change runs the full suite; Postgres + Redis up; Temporal tests use the SDK's time-skipping test environment, not the dev server). **The builder's per-rung gate.**
- full (no arg): `--loop` + **the platform-partition leg** (self-tests its canaries, computes the two-part skip key — the input closure's hash plus a digest of every discovered population — consults the partition ledger, and SAYS which of the two happened; when a green verdict is banked for the key, both pytest passes run only the product's own tests plus the four always-run frozen nets, and the verdict re-banks only after two green whole-suite passes under an unbent environment. `quality/partition.yaml` is the lockfile, `docs/product/partition-closure.md` is the design and the authority. `--loop` is untouched) + second pytest pass + canary self-test (every canary must fire; every negative must stay silent; the shell-refusal driver `scripts/tests/test_backup_restore.sh` runs in this leg) + anything e2e a product adds. Records a verdict in the ledger keyed on `git rev-parse HEAD^{tree}`. **Pre-push consults the ledger; a measured-green tree passes in ~2 s.**
- Exit: **0 clean · 1 violations · 2 enforcement broken** (dead canary, unbound scope/floor, consistency failure, negative-corpus hit, unknown flag). 2 outranks a pass. A mistyped flag is exit 2, never a silent full run.

**Database** — `scripts/db.sh` derives `DATABASE_NAME` as `djb_<branch>_<8-hex path hash>`, so every checkout — clone or worktree, same branch or not — gets its own database on the one compose Postgres; a `DATABASE_NAME` already in the environment wins over the derivation, and `setup.sh` persists the derived name into `.env` so a bare `manage.py` resolves the same database the scripts do — reconciling a stale pin on every run unless the `.env` line carries `# pinned` (the deliberate-pin marker; `db.sh` prints the disagreement either way). Test DB is `test_` + that name (Django default).

**Compose** — `compose.yaml` pins `name: djangobootstrap`, so every worktree addresses the **one** stack (the organ set is compose.yaml's to enumerate — postgres/redis/temporal/zitadel/mailpit/minio/meilisearch/observability today) rather than a stack per directory; `scripts/setup.sh` reuses a running stack and only starts what is not up. Two worktrees share the containers and never the database.

**Tests** — `pytest-django` + `pytest-asyncio`, pyproject config, `--reuse-db` off by default (honest). Workflow tests run under `temporalio.testing.WorkflowEnvironment.start_time_skipping()`; consumer tests use **`apps.realtime.tests.websocket`** — the in-repo raw-ASGI client, which speaks the websocket protocol to the real application; `channels.testing.WebsocketCommunicator` is deliberately *not* used, because any import under `channels.testing` runs an `__init__` that imports `daphne`, and this repository serves ASGI with uvicorn and does not install it (ruled: keep the client, no daphne dependency). MCP tool tests call the tool functions with a fake context. `scripts/test.sh` exits with pytest's status and is never piped.

**House rules** — `quality/rules.yaml` is the single source of truth: per rule `id · statement · check · doc · scope (derived, never typed) · floors · canaries · negatives · does_not_cover`. `quality/gate.py` runs them; `python -m quality.gate` exits 0/1/2. Canary fixtures live in `quality/canary/<rule-id>/`, negatives in `quality/negative/<rule-id>/`, planted through the real scope at self-test time and removed after.

**Introspection** — `uv run python manage.py introspect` prints JSON: `apps`, `models` (fields, relations, bases), `urls` (name, pattern, the callable), `routes` (pattern, methods, name, `auth`, `paginated` — from the live ninja registry), `tools`, `consumers`, `workflows`, `activities`, and the non-secret `settings`. This is what agents read instead of guessing.

**Skills** — every development brief says: *load `.claude/skills/django-conventions/SKILL.md` before writing code.* The product-manager skill's dispatch-briefs say so too.

## Conventions every layer assumes

- Settings via `environ`/`os.environ` with `.env.example` as the complete list. No secrets in the repo. `config.settings.local` is the default `DJANGO_SETTINGS_MODULE` for `manage.py`; `config.settings.test` for pytest; `production` is what `check --deploy` is run against.
- `AUTH_USER_MODEL = "accounts.User"`, `DEFAULT_AUTO_FIELD` irrelevant because `BaseModel` sets a UUID pk.
- Secrets never in the repo; the Fernet key for `connections` credentials is `CONNECTIONS_ENCRYPTION_KEY` in `.env.example` with a generated dev value and a production-raises-if-missing check.
- Redis: `REDIS_URL`; Temporal: `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE`.
- `apps.<name>` import path; each app's `AppConfig.name = "apps.<name>"`.
- Python 3.12, Django 5.2 LTS, pinned in `pyproject.toml`; `requires-python = ">=3.12"`.
- Commit messages in the repo's register: what changed and why, no counts that will drift.
