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
│   │   │                       #   the one hat resolver all doors call) · service.py (@service) · authz (the vocabulary: kinds and
│   │   │                       #   CRUD derived, verbs declared, `tenant.own` reserved) · roles.py (the declared roles — THE ONE
│   │   │                       #   PRODUCT-EDITABLE FILE IN core) · audit (AuditEntry) ·
│   │   │                       #   exceptions (+ the refusal registry/composer) · log · observability · lifecycle/schedules registries ·
│   │   │                       #   api/ (CursorPagination, docs, scopes: FROZEN_FAMILIES) · health (/readyz organs) · admin (ServiceModelAdmin)
│   │   ├── management/commands/introspect.py   # real models, routes, consumers, tools, workflows, settings → JSON
│   │   └── management/commands/newapp.py + management/app_template/   # the app generator: Django's startapp with THIS
│   │                                           #   house's template — the canonical file set and nothing else, apps.py with
│   │                                           #   depends_on, a door-parity stub that skips until a door exists. Green under
│   │                                           #   --fast with nothing but the label filled in; refuses a label that would red
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
│   │                           #   mcp.py, workflows.py + activities.py, tests, migrations/, max_migration.txt (once the first migration exists — linear-migrations skips a migration-less app, so a freshly generated one has none)
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
│   ├── gate_refuse.sh          # the refusal seam (sourced by check.sh and by every library a banner stands
│   │                           #   behind): `gate_refuse` prints a callee's first `!!` line AND records it, so each
│   │                           #   `— see above.` banner prints `cause:` as its second line. A callee under
│   │                           #   `$(...)` sets nothing — `gate_capture` is the caller-side form. A banner
│   │                           #   whose callee recorded nothing SAYS so and is exit 2. The banners still
│   │                           #   standing behind a callee outside this seam are the SEPARATE-PROCESS ones
│   │                           #   (`queue_index.py`, two `sweep.sh --assert-none`) and they print that
│   │                           #   sentence by design until those callees join it. EVERY db-pin refusal in
│   │                           #   `db.sh` is INSIDE the seam — it sources `gate_refuse.sh` from its own
│   │                           #   directory, best-effort and guarded (`scripts/db.sh:365-394`), and both
│   │                           #   `db_pin_leg` (no mode, unknown mode, an unreadable `.env`, an inline
│   │                           #   comment, a pin that DISAGREES) and `db_pin_existence` (a Postgres that
│   │                           #   would not answer, and the three absent-database shapes) refuse through
│   │                           #   `gate_refuse`, so the `db-pin` banner names its cause on every path. A
│   │                           #   copy of db.sh with no seam beside it is exit 2 AT THE LEG, never a
│   │                           #   refusal nothing can attribute (`scripts/db.sh:501-505`).
│   ├── rung_start.sh           # one command to a ready worktree: reset, venv, database, introspect dump
│   ├── rung_tidy.sh            # the bookkeeping the gate's own refusals prescribe, applied by one command:
│   │                           #   --budgets writes the ceilings a `budget:` line named, --client regenerates
│   │                           #   through frontend/scripts/pin_client.sh --write, --secrets re-scans through
│   │                           #   pm_fold.sh --only secrets --no-commit. It OWNS NO WRITER: every subject goes
│   │                           #   through the instrument that already owns it, which is why the baseline is
│   │                           #   safe — one legal `detect-secrets` writer, and this is not it. It never
│   │                           #   commits, never stages and never runs the gate; a subject this checkout has
│   │                           #   not got is `skipped`, printed, at exit 0. The three refusals print
│   │                           #   `offer: ./scripts/rung_tidy.sh --<flag>` at their own site (check.sh's
│   │                           #   house-rules leg, fe_gate.sh's suspect block, pm_fold.sh's BASELINE SHIFTED).
│   │                           #   THE COMMAND IS THE SAME EITHER WAY a consumer's fe leg behaves: ours
│   │                           #   DISCLOSES where theirs refuses, and `--client` is what both are told to run.
│   ├── budget_notes.sh         # sourced, not executable: the ONE reader of quality/gate.py's budget sentences.
│   │                           #   pm_fold.sh applies the LOWERINGS through it and rung_tidy.sh the two
│   │                           #   PASTEABLE shapes; a second copy of the parser is a parser that drifts in one
│   │                           #   of them silently, and each caller's count cross-check against the engine's
│   │                           #   own `notes=`/`problems=` is what makes a reworded sentence could-not-look.
│   ├── verify_start.sh         # one command to a ready VERIFY clone: clone, union-merge main, .env + derived
│   │                           #   database name, uv sync, seed the builder's banked --loop rows, verdict-key
│   │                           #   guard. It then PREDICTS the verifier's first consult — `consult: EXPECTED HIT`
│   │                           #   when the union is the branch tip and a seeded row carries this tree, else
│   │                           #   `consult: WILL RUN` naming the reason (commits on main since the fold, no row,
│   │                           #   --no-sync) — and prints the `fold point` the builder's report's `fold:` line is
│   │                           #   compared against. The prediction reads the TREE half of the key only; the
│   │                           #   environment and scope halves are measured when the loop runs.
│   ├── verifier_box.sh         # a throwaway EC2 box per verification:
│   │                           #   up/down/pool/census/run/loop/leg/wait/fetch/harvest/push/bake.
│   │                           #   Every name it mints derives from DJB_DEPLOY_NAMESPACE and carries djb:namespace,
│   │                           #   so one deployment's census never lists another's boxes. The transport is SSH over
│   │                           #   Session Manager — no key pair, no ingress rule; the image it launches and the
│   │                           #   identity it uses are deploy/verifier/ and deploy/iam/'s.
│   │                           #   `leg <id> --unit U [--shard k/N] --log NAME` is `loop` for ONE unit of the FULL
│   │                           #   gate — the seam `pm_push.sh --bank --on-boxes N` calls, same detach idiom, same
│   │                           #   pidfile `wait` reads, no scope basis (a unit is not scoped).
│   │                           #   `pool --want N [--idle M]` keeps N warm boxes tagged djb:for=pool + djb:price
│   │                           #   (read once at launch, so nothing computes a price afterwards); it trims only
│   │                           #   UNCLAIMED boxes oldest first and refuses above DJB_VERIFIER_MAX_BOXES before any
│   │                           #   AWS call. `up --for R` CLAIMS a warm box first — same image, key on this machine,
│   │                           #   `mkdir` as the lock and the tag as the record — so the pool is PER MACHINE by
│   │                           #   construction: the private half never leaves the machine that launched it.
│   │                           #   `census` prints that pool and its $/h from the tags. `harvest <id> <name>` brings
│   │                           #   a box-banked `--loop` row home — the row VERBATIM + ` box=<id>`, appended through
│   │                           #   gate_ledger.sh's own `loop_ledger_path`, twice is one row, a log with no `banked:`
│   │                           #   line is exit 2. No interpreter: its date arithmetic is idle_reaper.sh's shape.
│   ├── test.sh                 # pytest wrapper; owns its exit code; never piped
│   ├── setup.sh                # fresh clone → running: uv sync, hooks, compose up, DB, migrate
│   ├── db.sh                   # per-worktree database name + create/drop helpers (template-clone fast path)
│   ├── serve.sh · worker.sh    # uvicorn · the Temporal worker
│   ├── loop_health.py          # reads docs/product/readouts.md; exit 0/1/2
│   └── githooks/{pre-commit,pre-push}
├── deploy/                     # provisioning, release, teardown, observability — the environment posture as code
│   ├── verifier/               # the verifier box IMAGE: the bake recipe, the idle/lifetime reaper and its
│   │                           #   systemd unit + timer, and the two cloud-config seams a launch renders.
│   │                           #   Everything here is per-deployment by derivation, never by name: the
│   │                           #   machinery ships in the template and the identities are the product's.
│   └── iam/                    # the one hand a human performs: the verifier-ops policy document, the box
│                               #   role's trust document, and the idempotent `--confirm`-gated bootstrap
│                               #   that creates them. Every name derives from DJB_DEPLOY_NAMESPACE.
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

> **Every dispatch row carries its stamps, and a reader derives the velocity
> numbers from them rather than from anybody's memory.** The last cell of a row
> carries `stamps: sent=<t> done=<t> met=<t> merged=<sha8> <t> pushed=<t>
> staged=<t>`, where `<t>` is `YYYY-MM-DD HH:MM`, a bare `HH:MM` inheriting the
> date of the dated stamp before it in the same cell, or an em dash for a stage
> not reached — **one clock, PDT**, because two clocks in one ledger cannot be
> normalised afterwards without guessing which rows were written under which.
> `pushed` and `staged` are the WAVE's, written once on its own `| WAVE-<n> |`
> row and inherited by the rungs that merged before it, which is why stage 3
> (`done → met`) is measured per rung and stages 4 and 5 per wave: the push is
> per wave, and charging its wait to the rung that was ready first reports a
> batching decision as a regression. `scripts/loop_metrics.py` is the only
> reader of that grammar and it writes nothing — it prints the row for the PM
> to paste under `readouts.md` § COST BASELINE, reads that table's header from
> the file rather than carrying a copy, refuses a malformed stamp at exit 2
> naming the row and the field, and COUNTS and NAMES every row that carries no
> stamps at all instead of taking a median over the stamped half.


## Discovery conventions (what A2 lays; what every later app relies on)

- **Registration:** by discovery, never by editing `config/` or `pyproject.toml`. **`INSTALLED_APPS` is derived from `apps/*/apps.py`** — a package under `apps/` with an `AppConfig` is installed. An app declares what it may import on its own `AppConfig` (`depends_on`); house rule 7 enforces it; `import-linter` keeps only the fixed layer contract (`core` ← `accounts` ← platform ← domain). `config/settings/discovery.py` derives it today.
- **REST:** `apps/<x>/api.py` exposes `router: ninja.Router`; `config/api.py` imports every installed app's `api` module if present and mounts it under the version segment `config/urls.py` owns (`API_PREFIX = "api/v1/"`) at **`/api/v1/<label>/` unless the module names `PREFIX`**, then `/api/v1/<PREFIX>/` (the example app: `PREFIX = "widgets"` → `/api/v1/widgets/`; OpenAPI at `/api/v1/docs`). **An app never spells the version segment**; moving to `v2` is a change to `config/urls.py`, not a sweep of every app. Auth default on the `NinjaAPI` is `apps.accounts.auth.API_AUTH` (`SessionAuth` + `ApiTokenAuth`); **every route carries an explicit `auth=` — on its router or on the route — never `auth=None` outside the `rules.yaml` allow-list.** Lists are `@paginate`d through the one seam, `apps.core.api.CursorPagination` — cursors, not page numbers (ADR core-18, `apps/core/api/pagination.py`); the envelope is `{"items", "has_more", "next_cursor", "count"}`, `?cursor=` and `?limit=` are the controls, and **`count` is `null` unless the caller sends `?include_count=true`** (`?page=`/`?page_size=` are gone, not deprecated). Exception handlers live once in `config/api.py`: `ValidationError` → 400, `IntegrityError` → 409, `PermissionDenied` → 403, `DoesNotExist` → 404. **One envelope, always: `{"detail", "code"}` plus `"errors"` when the refusal names fields** (`on_domain_error`) — `code` is what a client branches on, and `architecture.md` is the authority the code agrees with.
- **MCP:** `apps/<x>/mcp.py` exposes `register(server)`; `config/mcp.py` builds the server, discovers and calls each. `config.mcp.TokenAuthMiddleware` resolves the bearer token once (the same `authenticate_token` service as `ApiTokenAuth`) and leaves a `Principal(user, tenant)` on the ASGI scope; a tool reads it with `apps.core.mcp.principal(ctx)` and calls services only.
- **Sockets:** `apps/<x>/consumers.py` exposes `websocket_urlpatterns`; `config/asgi.py` concatenates them under `AuthMiddlewareStack` + a tenant middleware.
- **Workflows:** `apps/<x>/workflows.py` exposes `WORKFLOWS: list[type]`, `apps/<x>/activities.py` exposes `ACTIVITIES: list[callable]`; `config/temporal.py` assembles one worker on task queue `settings.TEMPORAL_TASK_QUEUE` (default `djb-main`, per-worktree suffix from `db.sh`'s branch sanitiser so two worktrees' workers never steal each other's tasks). `workflows.py` imports only stdlib dataclasses/`timedelta`, `temporalio.workflow` and the app's `types.py`; activities are invoked **by name**. A service starts a run with `apps.workflows.services.start_workflow_on_commit(*, workflow, arg, tenant, user=None, org=None, id, task_queue=None)` — `id` required and deterministic, built by the keyword-only `workflow_id(*, tenant, app, noun, key)`; the async `start_workflow(..., client=)` is for callers already on the loop. **`org` is the acting hat the run is started under**: omit it and every activity in the run acts for the whole tenant rather than for the branch that asked. Tenant, user **and org** travel as workflow **headers** (repeated in the memo) via `TenantContextInterceptor` and are restored in activities by `current_tenant()` / `current_org()` / `current_user_id()` / `workflow_context() -> tuple[Tenant | None, str | None, Organization | None]` — **three** values. Activities are plain `def` and run in the worker's `activity_executor=ThreadPoolExecutor`; each calls `close_old_connections()` at both ends.
- **Events:** `apps.events.services.emit(*, name: str, tenant, payload: dict, actor=None)` — **keyword-only, the name included**, because it is a `@service` and house rule 13 refuses a positional parameter at import time. It writes `Event` + `Outbox` atomically with the caller's transaction (`transaction.on_commit` starts the dispatch workflow). Subscribers are data (`WebhookEndpoint` rows per tenant) and the realtime bridge; nothing imports `events` except to `emit`.
- **Permissions and roles:** `apps/<x>/policies.py` exposes `POLICIES` (predicates), `ACTION_PROSE` (the declared verb and the sentence a refused caller reads), optionally `DEFAULT_ROLES` and `RENAMED_PERMISSIONS`; `apps/<x>/roles.py` exposes `ROLES: dict[str, DeclaredRole]`. `core.authz` discovers both walks, derives `<kind>.create/read/update/delete` for every first-party model, and answers `vocabulary()` — computed at import, never stored. **`apps/core/roles.py` is the one PRODUCT-EDITABLE file in `core`**, the way `docs/product/north-star.md` is product-editable: edit it, add roles, delete `admin` if your product has no such person, and a template merge brings it back as an ordinary per-file conflict you adjudicate. Every other file under `apps/core/` is the platform's. Two apps declaring one role key is an `ImproperlyConfigured` at discovery, and `roles` is in `CANONICAL_MODULES`, so a product's own `apps/<x>/roles.py` needs no `quality/rules.yaml` edit.
- **Introspect** carries a section per door: `routes`, `tools`, `consumers`, `workflows`, `activities` — each read from the real discovered registry, never from a list — plus `policies` (the whole vocabulary, one row per key with its kind, verb, `decided_by`, `conforms`, sentence, default roles, predicate and any old names) and `roles` (the declared roles and the size of the collection each resolves to).

## Interfaces

**Gate** — `./scripts/check.sh [--fast|--loop]`
- `--fast`: ruff (lint+format check) · mypy · import-linter · house rules · `makemigrations --check --dry-run` · linear-migrations check · goalpost census (every executable instrument outside `apps/`/`config/` owes a row in `docs/product/instruments.md`; an uncensused one is exit 2) · db-pin (this checkout's .env DATABASE_NAME pin vs the derivation; a disagreement without a `# pinned` marker is exit 1 naming both names). No services needed beyond what mypy/django needs to import settings. Target < 60 s. **Pre-commit runs this.**
- `--loop` **runs on a verifier box**, and refuses (exit 2, above the lease, the lock, the slot and the scope derivation, so nothing is paid) on a machine that is not one — printing the recipe (`verifier_box.sh up --for <rung>` · `loop <id> --log loop-<rung>` · `wait <id> loop-<rung>` · `down <id>`). A box is told by a marker the image carries (`/run/verifier`, which `deploy/verifier/user-data.yaml.in` installs at first boot, or `/etc/djb/image-id`) — never by an environment variable and never by a hostname. The valve is `DJB_LOOP_HERE="<who>: <why>"`, the sanction's own grammar and the sanction's own shape check, and the reason prints in the run's banner and again beside the banked verdict; `--fast` (the pre-commit hook) and `--census` are untouched, and the verifier's clone is untouched by construction because the verifier's one consult already runs on a box. The residual is the sanction valve's, declared: `mkdir /run/verifier` gets past it, exactly as `CI=1` gets past the pipe guard. The ledger ROW does not yet carry the reason — that needs a field in `gate_ledger.sh` and is the follow-up; the transcript carries it today.
- `--loop`: `--fast` + `check --deploy` + the changed-files secret scan + **the always-on leg** (the full-only members the loop can afford, at every scope including an empty one, announced between the secret scan and pytest so a cheap red lands before the pytest slot is taken). Two derivation sources, one leg, two printed lists. **DECLARED** — every drive under `scripts/tests/` carrying `# census: cross-app <reason>` at column zero in its first 40 lines, read through `loop_scope__declared_censuses`, which is the same reader and the same grammar the pytest door's marked modules go through; it runs whatever its price, because a census quantifies over the whole tree and a scope has not narrowed what it is about. **MEASURED** — every full-only member (a leg announced below the `--loop` block, or a drive the selftest leg registers) whose seconds in `scripts/gate_member_durations.json` are under 10 and whose unit declares no `network` need. The population is DERIVED from that committed measurement and never typed: the file is rewritten by `./scripts/check.sh --store-durations` (the whole gate, run to be timed; it banks nothing, because a tracked file written during a run moves the tree that run would have vouched for) and committed as the measurement it is. Every exclusion prints its reason, a member the file names that the gate does not have is exit 2, and a member whose live seconds cross the floor is ANNOUNCED at every full run and LEAVES at the next measurement. **The full-only LEGS are named and not run**: their bodies are defined below the `--loop` block's own exit, so the leg cannot call them — printed with that reason rather than dropped, and two of the cheap three (`temporal-census`, `own-tree-census`) are before-and-after differences about a finished suite, which is not a property a `--loop` has. Each member is consulted against its banked drive verdict FIRST, through `gate_ledger.sh`'s own `drive_key`/`drive_ledger_lookup` — one key grammar shared with the selftest leg, so a member banked by either is reused by the other — and prints `REUSED from drive-v1:<key> (banked <date>)` on a hit; a member the leg cannot key RUNS with the reason printed, and only a green banks. The digest of both inputs joins `LOOP_SCOPE_CANONICAL` as `alwayson=`, so a banked loop row never vouches for members it did not run. + ONE pytest pass over the derived test tier (fast tier + the rung's own app in full, the tier choice printed every run; a shared-test-infra change runs the full suite; Postgres + Redis up; Temporal tests use the SDK's time-skipping test environment, not the dev server). **The builder's per-rung gate.** When the ledger misses on `tree` alone, **the banked row's head is an ancestor of HEAD** (`git merge-base --is-ancestor`, so the delta is a walk forward and never a divergence), and the whole delta since that head is under `docs/`, the pytest pass alone is REUSED from that banked verdict and every other leg still runs — refused, and measured in full, if the banked head is not an ancestor, if any changed `docs/` path is spelled in a module under `apps/` (derived per path at run time, never listed; wider than "a test reads it", and fail-closed: the first hit wins, it need not be a test, and a docstring mention refuses), if the working tree is not clean, **if the banked row's own `tree=` is not its head's committed tree** (a `--loop` verdict is keyed on the MEASURED working tree, which is routinely dirty, so a bank can name a head whose committed bytes nothing ever measured), or on any belt but `--loop`; the row it banks says `reuse=<the tree it rests on>`. The `--loop` key's environment fingerprint is `.env` (minus the deriver-declared keys) + the installed-distribution census + **the EFFECTIVE value of every name the suite reads from the environment** (process env over `.env`, `read_env(overwrite=False)`'s own precedence; the names come from `quality/partition.py::suite_environment_names()`, which is also what the full gate's bent-environment check stands on, and `scripts/gate_ledger.sh` keeps no list of its own) + HEAD + the merge-base with `main`. **The environment is brought to the lockfile BEFORE that key is derived** — `loop_env_sync` (`uv sync --frozen`, printed with its seconds and uv's own summary, skipped by `DJB_LOOP_NO_SYNC`, and never a refusal because a checkout with no `uv` is a checkout whose legs are about to say so): the census the key carries has to be the environment the legs ran in, and the gate's own first `uv run` used to be what installed, one leg AFTER the key — so a completely green `--loop` on a machine whose image predated a lockfile change banked nothing, with `git status` clean beside it. When the end-of-run key does not re-derive, the refusal now NAMES the half that moved and, for the environment, the component (`loop_key_moved`).
- full (no arg): `--loop` + **the platform-partition leg** (self-tests its canaries, computes the two-part skip key — the input closure's hash plus a digest of every discovered population — consults the partition ledger, and SAYS which of the two happened; when a green verdict is banked for the key, both pytest passes run only the product's own tests plus the four always-run frozen nets, and the verdict re-banks only after two green whole-suite passes under an unbent environment. `quality/partition.yaml` is the lockfile, `docs/product/partition-closure.md` is the design and the authority. `--loop` is untouched) + second pytest pass + canary self-test (every canary must fire; every negative must stay silent; **every** shell drive under `scripts/tests/` runs in this leg — `test_backup_restore.sh` was the first, and `test_gate_explain.sh`, `test_drive_preamble.sh` and `test_pipefail_readers.sh` the most recent to join. The list is not written down anywhere, on purpose: each drive is registered at its own `# >>> drive: <name> >>>` sentinel in `scripts/check.sh`, and `scripts/tests/test_drive_preamble.sh::case_every_drive_under_tests_is_invoked_by_the_gate` censuses that set against the directory, so a drive that ships unwired is a red rather than a promise. `deploy/tests/` is the declared gap and the leg prints it — **one entry lighter**: `deploy/tests/test_stage.sh` sources `drive_preamble.sh`, so the stated blocker does not apply to it, and it is registered at its own sentinel like every other member. The exclusion from the printed gap is DERIVED from check.sh's own column-zero invocation lines, never typed, so the block goes on naming every sibling that is still unrun and stops naming the one that is not. **The leg runs EVERY drive before it decides**: it is one function, `selftest_drives_leg`, nothing between the drives exits, each prints `drive <name>: exit <rc> (<n>s)`, and the leg's exit is composed at the end — 2 if the engine's own selftest or any drive could not look, else 1 naming every red drive on one line, else 0; `scripts/tests/test_selftest_leg.sh` drives that composition over a scratch drive set) + anything e2e a product adds. Records a verdict in the ledger keyed on `git rev-parse HEAD^{tree}`, with the leg set it ran; a row whose legs do not COVER the set `check.sh`'s own `FULL_LEGS` declares is not honoured (a checkout with no `scripts/check.sh` declares none and compares nothing — the declared gap). **Pre-push consults the ledger for the TREE OF EVERY REF BEING PUSHED, read from stdin** — not for the local working tree, which is what let a green-banked `main` push an unmeasured branch under its verdict; when a pushed tree has no verdict and is not this checkout's tree the hook REFUSES and names both, because a full run here would measure something nobody is pushing (`scripts/pm_push.sh` is the shape that always agrees: a `pm-push` worktree detached to the SHA). **A measured-green push passes in ~2 s.** **The wall is one full gate per push to a FORGE, and a VERIFIER BOX is exempt from the measurement by declaration plus probe** — `DJB_PUSH_DESTINATION=verifier-box` AND a remote that is `scripts/verifier_box.sh`'s own `…/.vouch-<pid>/probe.git`, both conditions, so the declaration alone can never open `origin` — because the box's own run IS the measurement; the exemption is from the measurement and never from the identity check, nothing is banked on the way out, and the hook prints one sentinel line (`pre-push: wall <verdict-word> <tree>`) on every run so a caller can tell a wall that passed a tree from a checkout that has no wall at all.
- `--pr --base <sha>`: the **full gate with its two pytest passes narrowed** to the scope of `<sha>...HEAD` — same exclusive lease, same slot, same legs in the same order, same sanction rules, and the organ tier NOT applied (every test the change can reach runs, organ-reaching or not). It **banks nothing**: no full verdict row and no partition row, because a narrowed run vouches for no tree. Exit 2, never a smaller run: no `--base`, a base git cannot resolve, a base that is not an ancestor of HEAD, a dirty tree, an app label the declarations cannot account for, or an always-on floor unmet — all of them above the lease. **Reader: FULFILLED.** This repository's own `.github/workflows/ci.yml` calls it — every `legs` row inherits `--pr --base ${{ github.event.pull_request.base.sha }}` on a `pull_request` and nothing on a push to `main`, so a proposed change is graded at the scope of what it can reach and `main` is graded whole. It composes with `--leg <unit> --shard k/N`: the scope narrows the collection and the split partitions what is left. The consumer's `CI-PR-1` calls it the same way from their own `ci.yml`. A human under a typed sanction is no longer this mode's only caller.
- `--leg <unit> [--shard k/N] [--store-durations]`: **one unit** of the full gate — its legs announced and run in the full gate's order, nothing else announced and nothing else run, under the full gate's exit contract. It takes **no machine lease and no checkout lock**, **records no verdict** (no full row, no partition row, no loop row) and **needs no sanction**: a unit is a targeted drive, the way `--loop` and `--census` are (rung-execution §3). A unit whose legs run a suite takes **one pytest slot**, exactly as `--loop` does. The unit names are `--list-legs`'s and an unknown one is exit 2 pointing there; `--leg` with no unit is exit 2. **`--shard k/N`** (1-based) runs the k-th of N parts of a unit the listing calls `N-capable` and is exit 2 on a `shards: 0` unit, on `k>N`, `k<1`, `N<1`, a non-integer, a missing pair, and outside a unit run; `1/1` is the whole unit and carries no split flags at all (so it needs no plugin). A shard forces the platform partition to **measure** and banks nothing anywhere, and a shard that **collects zero tests is exit 2** — a part nobody ran is neither a green part nor a red suite. **`--store-durations`** rewrites `scripts/pytest_durations.json` (the file the split balances by) from one pass, runs no second pass and banks nothing; it is refused with `--shard` and on a unit that runs no suite. It composes with `--pr --base <sha>`: the scope narrows and the split partitions what is left. `DJB_GATE_PYTEST_SEED=<n>` types the seed both passes carry — every shard of one run must split the same collection order — and an unparsable value is exit 2, never a minted fallback.
- `--list-legs`: the full gate's legs, grouped into the **units** one runner can be handed, one tab-separated line each — `<unit>` · `<needs>` · `<shards>` · `<composed-of>` — exit 0. No venv, no database, no docker, no network, no lease, no lock, no slot; it reads `scripts/check.sh` and prints. It refuses (exit 2) rather than print a table it cannot vouch for: a leg announced at column zero that `FULL_LEGS` does not name, a leg in two units, a leg in no unit, a unit with no `needs` declaration.
- Exit: **0 clean · 1 violations · 2 enforcement broken** (dead canary, unbound scope/floor, consistency failure, negative-corpus hit, unknown flag). 2 outranks a pass. A mistyped flag is exit 2, never a silent full run.

**The units, and the one command that is the authority.** The table below is a
copy for a reader; `./scripts/check.sh --list-legs` is what anything that acts
on it must ask, and `scripts/tests/test_list_legs.sh::case_the_build_contract_table_equals_the_listing`
asserts the two are byte-identical line for line, so a copy that drifts is a
red rather than a reading. `needs` is a **declaration**: the gate is what
refuses a unit whose organ is missing, at the leg, and nothing reads this field
to decide whether to bring a stack up. `shards` is `0` (indivisible) or
`N-capable` (the unit's body takes a `k/N`). A unit that shards by a registered
population names that population in `composed-of` after its legs — `selftest`
names its leg and then every drive the leg walks, in the order it walks them,
so a reader can see what one shard holds; that order is derived from
`scripts/check.sh`'s own `./scripts/tests/test_<name>.sh` invocation lines and
is never typed.

| unit | needs | shards | composed-of |
|---|---|---|---|
| `static` | db | 0 | ruff,mypy,import-linter,djb-checks,house-rules,migrations,goalpost-census,queue-index,db-pin,archaeology,adr-census,dangling-docs,loop-names,ci-env,deploy-check,fe,collectstatic |
| `supply-chain` | network | 0 | supply-chain |
| `pytest-x2` | db,redis,temporal,minio,meilisearch | N-capable | temporal-census,partition,pytest-x2,own-tree-census |
| `selftest` | db,docker,temporal | N-capable | selftest,backup_restore,sweep,pm_merge,pm_fold,rung_tidy,pm_push,secrets_scan,secrets_baseline_guard,setup_env,scripts_census,archaeology_loop,fe_leg,db_pin,loop_tier,loop_scope,fast_censuses,loop_ledger,rung_start,db_template,serve_port,runbook_recipes,gate_lease,verify_start,db_zsh,publish,queue_index,test_impact,loop_metrics,gate_explain,drive_preamble,pipefail_readers,list_legs,shard_census,verifier_image,verifier_box,selftest_leg,stage |
| `full-house-rules` | none | 0 | full-house-rules |

`secrets`, `always-on` and `pytest` are **not** in the table: all three are
announced inside the `--loop` block, which the full path skips entirely, so a
unit naming one of them would promise a runner something the full gate never
runs. `always-on` is the sharpest case of that rule rather than an exception to
it: every one of its members is already a leg or a drive the full gate runs
under its own name, so a unit holding `always-on` would run another unit's
members a second time, under a name no verdict row carries. `fe` was one of those
three until 2026-09-15 and now sits on the full path, in `static` — a tri-state
leg that prints `skip` is still a leg that ran, and a leg the full gate never
announces is one no verdict row names.

**A drive's own verdict, and the row that carries it.** The selftest leg
consults the verdict ledger before it runs a drive, and a banked drive is not
re-driven. The key is **not** the measured tree — an `apps/`-only rung moves that
and would re-key everything — it is what the drive **declares it drives**: one
`# drives: <path> [<path>…]` line in the drive's first forty lines
(checkout-relative paths or globs), plus the blob shas of every declared path in
the measured tree, plus the bytes of the drive file and of the
`drive_preamble.sh` beside it, plus **the machine's own claim** — which is the
IMAGE ID on a verifier box (`/etc/djb/image-id`, written at boot by the launch
seam from the `$image` `verifier_box.sh` already holds, digested as
`image <ami>`) and `bash --version`/`git --version`/`uname -sr` everywhere else.
The image is the stronger claim: two boxes cut from one image agree in every way
the key cares about, so a row banked on one is honoured by the other, while a
row banked on a laptop can never be honoured on a box. A machine file that
EXISTS and cannot be read is **could-not-look**, never the host digest — that
fallback would be a Mac row and a box row colliding under one label.
The declaration is **cross-checked by derivation**: every checkout path the
drive's body spells must be covered by a declared one — the three narrowings of
"spells" are argued in `scripts/gate_ledger.sh`'s own header — and a drive whose
key cannot be decided (no marker · a declared path that expands to nothing · a
spelled path the marker does not cover) is **exit 2, could-not-look**, never a
silent reuse and never a silent run.

The row is a **new kind in the one ledger** (`djb-gate-verdicts`,
`gate_ledger_path`, shared across worktrees), never a second file:

```
v1 <key> drive <date> <name> exit=0 took=<s> tree=<MEASURED_START> parts=<path>:<12 hex>,…
```

The `parts=` label for the machine stays `machine:` on a box exactly as on a
laptop — `drive_moved_component` knows it by name — and WHICH machine it is is
the fifth field of `drive_key`'s answer, which the leg prints beside every
REUSED and every miss as `machine=image:<ami>` or `machine=host:<12 hex>`.

Field 3 is `drive`, and `gate_ledger_lookup` matches ` <tree> full ` — so no
drive row can ever be honoured as a full verdict, including one whose key IS a
tree sha (`test_loop_ledger.sh::case_a_drive_row_is_never_a_full_verdict` plants
exactly that). Only a **green** banks; a red, a could-not-look and a
`DJB_GATE_LEGS_DRY` run bank nothing. `parts=` is the attributor's evidence, not
a key: it is what lets a miss print `miss: <path> moved since <old key>` rather
than only that something moved. The valve is `DJB_SELFTEST_NO_REUSE=1`, which
runs every drive, says so in the banner, **and still banks** — a drive row is
keyed on its inputs, so a forced green is strictly newer evidence for the same
key; it is the answer to a machine change the claim above does not see (docker,
a Postgres image, a CLI upgrade — and, on a box, anything `setup.sh` changed
after the bake). Driven by
`test_selftest_leg.sh` (the reuse, the refusals, the shard, the valve, the
ingest and the image half) and
`test_loop_ledger.sh::case_the_machine_half_is_the_image_on_a_box_and_the_host_elsewhere`
and
`test_drive_preamble.sh::case_every_registered_drive_declares_what_it_drives`
(no shipped drive is in any of the three undecidable states).
**The house-rules engine banks one of these rows too, keyed from outside
itself**: it has no file under `scripts/tests/`, so the leg synthesizes a drive
file whose `# drives:` line is the exact cover of `python -m quality.gate
--selftest-inputs` — the engine's own answer about which bytes on this tree can
change its verdict — and hands it to the same `drive_key`, so a green canary
self-test banks a `drive` row named `house-rules-engine`, a byte moved in any
listed path refuses the reuse and names itself, and a listing the engine will
not print is could-not-look rather than a silent run.

**Drive rows TRAVEL, and only drive rows do.** Because the machine half is the
image, a row is worth carrying between machines of one image — and the ledger
lives in `.git/`, which no push moves, so a fresh box arrived with an empty one
and re-drove every drive. `scripts/verifier_box.sh` is the carrier, in three
places: `cmd_push` sends this checkout's `drive` rows (and no other kind — a
`full` or a `loop` row would be a verdict the box could reuse for a measurement
it never made) by **scp**, to `~/verify/<rung>/ledger.in`; `cmd_loop` and
`cmd_leg` prepend one idempotent whole-line ingest (`grep -qxF`, so a row
written twice is one row) to the command line that runs the gate over there;
`cmd_harvest` brings the box's `drive` rows **at the harvested tree** home
beside the loop row, once each, and says how many. It is **scp and not a ref**:
a shallow mirror sends one ref per `git push` (measured 5/5), so a fourth ref is
a fourth round trip over the tunnel for text that is not a tree. A carrier that
fails is a **note, never a refusal** — the cost is a re-drive, and a push that
worked is not thrown away for a cache that did not. **A bank's shards come home
too**, through a fourth door: `harvest <id> <name>` needs a banked LOOP row and
a shard runs `--leg`, which banks none by design, so `harvest-drives <id>
<tree>` reaches the same `harvest_drive_rows` with the tree named instead of
read out of a verdict, and `pm_push.sh --bank --on-boxes` calls it once per
shard box **after the row is banked and before the boxes go down, on a green
bank only** — a red bank's shards are not a cache anybody should reuse. Without
it every bank re-drove every drive the wave before had already driven, because
the Mac's ledger held nothing keyed to the boxes' image and `cmd_push` had
nothing image-keyed to send out. Driven by
`test_verifier_box.sh::case_push_sends_only_the_drive_rows` and
`::case_harvest_brings_the_drive_rows_of_the_banked_tree`, and by
`test_selftest_leg.sh::case_an_ingested_row_reuses_on_the_same_image` (the real
`box_ledger_ingest`, then the leg reusing what it carried).

**What the `--loop` scope costs, declared.** `--loop` runs the fast tier narrowed to the active rung's scope: its touched apps in full, the reverse-transitive `depends_on` closure of those apps at the fast tier, the test trees of any app whose only changed files are under `apps/<x>/tests/` (plus the modules that import those test packages), and the always-on cross-app set. So a red that **only a deselected app's test would show — a coupling that is not an import** (an event name, a registry token, a template path, a settings key, a fixture resolved by name at runtime) lands on main and is caught by the full gate at push, within hours, never on a deploy. The belts: the always-on set runs at every scope including an empty one; a change to shared test infrastructure or to `config/**` runs FULL; the full gate on main runs two whole-suite passes (`pm_push.sh --bank`, and CI's shards, each two-pass within itself — see the sharded shape's declared blind spot below). `scripts/loop_tier.sh` prints the same sentence as a note on every tests-only run rather than leaving it written down only here.

**And what the MAP costs on top of it, declared.** When the test-impact map (below) has SEEN every file the active rung changed, `--loop` runs the tests the map records against those files — plus the always-on cross-app set, plus the modules the rung edited and the censuses the declarations seeded — and the closure scope above is derived, printed, and NOT what runs (`loop_scope__impact` in `scripts/loop_tier.sh`; the flags are `--djb-impact-select` and one `--djb-changed` per changed file, and `--djb-scope=` is not passed at all). The map's sha is LAST in `LOOP_SCOPE_CANONICAL` as `map=`, so a verdict banked under one map is never reused under another; `loop_ledger_key` is untouched. **Five ways it stands down, each printed on the run's own `scope   map:` line**: a changed file the map has never recorded (every template, fixture, migration, `.env` and brand-new module, by construction — coverage sees executed Python lines and nothing else), an absent or unreadable map, a map measured on a tree this checkout's history cannot account for, a seeded census module the map holds no test from, and the typed valve `DJB_LOOP_NO_IMPACT` (which keys itself `map=bypassed`, so the wider run is never handed the narrower one's row). Each of the five is the closure scope above, which is a slower run and never a wrong one. **What it does NOT narrow**: `--loop --mine` (a claim about one app, and a selection reaching into a dependant of it would be a third thing wearing the flag's name) and `--pr` (it grades a whole proposed change); both still carry `map=` in the key. **The declared hole, bounded rather than closed**: a test the map attributes to a file it no longer executes — or does not attribute to one it does — is not selected, and nothing in the loop can see that. What bounds it is the map's printed AGE, the never-seen fallback, `apps/conftest.py`'s orphan refusal (a selected nodeid the collection does not hold is a usage error, never a quiet subset) and the wave's bank, which runs the whole suite twice. **An age that cannot be verified is not staleness**: a depth-1 verifier mirror holds no tree older than the carried fork point, so the age prints `unverifiable` and the selection stands — reading an undecidable question as stale would un-narrow every run on the machine the loop is measured on. Driven by `scripts/tests/test_loop_scope.sh` (nine cases: the seen leaf file, the five never-seen plants, the root file, the removed entry and the dropped-test hole, the absent and unreadable maps, the two maps that are two keys, the valve, and `--mine`).

**What the SHARDED shape costs, declared.** CI hands each runner one unit, and the `pytest-x2` unit is split `k/N` (`--leg pytest-x2 --shard k/N`). Each shard still runs **two passes over its own group under one seed**, so the idempotency claim the second pass earns — *pass 1 left nothing behind* — narrows to **WITHIN a shard**: a test that leaks state which only a test in a *different* group would trip on is invisible to that run. It is not invisible for long. Group membership is a function of the seed, and CI mints a fresh seed per run (`DJB_GATE_PYTEST_SEED`, derived once and handed to every row), so a cross-shard leak co-shards with probability ≈ 1/N per run and surfaces as a red pass 2 within a few runs rather than never. The **unsharded whole-suite two-pass belt is the local `pm_push.sh --bank` with no `--on-boxes`**, which is unchanged and runs both passes over the whole collection on one machine. `--bank --on-boxes N` splits `pytest-x2` across boxes by the same `k/N`, so it **INHERITS this narrowing rather than closing it** — and the row it composes says so in its own `shards=` field, which is the only place a reader afterwards can tell a sharded bank from an unsharded one. **The bank closes it since ADR gate-1's 2026-09-18 amendment**: the pytest shards run one pass and the acceptance box's whole-suite two passes under one seed are the leak proof, composed into the row's `leak-proof=` field, and a row that ran one pass without it is not honoured. A nightly unsharded CI run is priced out (a fourth run kind on a private repository's billed minutes); the trigger to buy it is a red on main's bank that a sharded CI run had passed.

**The bank on boxes, and the ONE row it composes.** `./scripts/pm_push.sh --bank --on-boxes N` is the third wired ritual form beside `pm_merge.sh --bank` and `pm_push.sh --bank`: it folds, reads `./scripts/check.sh --list-legs`, and runs **one `--leg` per verifier box** — the indivisible units one box each, `pytest-x2` split P ways and the last shardable unit S ways, N = 3 + P + S over today's five units, **derived from that listing and never typed** (`N < 5` is refused, and so is any N short of the units the listing actually declares). **This Mac measures nothing**: it takes no machine-wide lease and no pytest slot, so a builder's `--loop` keeps its slot throughout a bank. Every shard's log and exit status are fetched and **composed here**, and the composition refuses rather than judges — exit **2** with NO row for a shard that exited 2, a shard whose status or log never came back, a box reclaimed mid-flight, a shard whose printed tree is not the key, or a union of `composed-of:` that does not equal the listing's own leg set and cover `FULL_LEGS`; exit **1** naming each red shard, also with no row. **The row has one writer** — `gate_ledger_record` — and one grammar, the ordinary full row with the sanction saying how it was earned:

```
v1 <post-fold tree> full <utc> <FULL_LEGS, with pytest-x2 as pytest-x2/1 on a one-pass bank> caller=pm-bank sanction=push-wall boxes=<N> shards=<label,…> waited=0 took=<slowest pytest shard> leak-proof=acceptance:<box id> rc=0
```

so `scripts/githooks/pre-push` honours it through exactly the lookup it already does, `waited=0` is the honest answer (this bank queued for nothing), and a row whose legs field is short of `FULL_LEGS` is still not honoured. **The member grammar is `<leg>[/<passes>]` and the `leak-proof=` field is appended last**, both since ADR gate-1's amendment: a shard planned at `--passes 1` names `pytest-x2/1` in its own `composed-of:` and in the row, the field names the acceptance box that ran the whole-suite two-pass proof and the status it exited, and `gate_ledger_lookup` covers `pytest-x2/1` only where that field is present and green — for that unit alone, because the proof is a pytest run and vouches for pytest. An absent suffix still means two passes and every row written before the field existed parses exactly as it did; the composition compares the union of `composed-of:` against the listing with the pass count taken OFF, because the count is a property of the run and never of the unit. The plan decides it before any box is launched — one pass per suite shard exactly when an acceptance checkout could be read, two for every one of them when it could not, and never a mixture — and a shard whose banner disagrees with its plan line is exit **2** with no row, beside the other ways the plan and the shards can disagree. **A detach that exited 255 is the transport and gets ONE more go**: `up` returns on the SSM agent's `Online` and the SSH tunnel is a few seconds behind it, so a `leg` fired in that window comes back with ssh's own 255 and an EMPTY log — no gate ran — and a whole bank refused with every box up and paid for. The bank waits (`DJB_BANK_DETACH_RETRY_SECONDS`, default 15), prints the wait and the retry, and detaches once more; **any other non-zero is not retried**, because it is the wrapper or the box saying something real and a second detach would risk a second copy of a leg already running. **A shard NEVER falls back to on-demand on its own**: the bank sets `DJB_VERIFIER_BANK_SHARD` around each shard's `up`, which turns `scripts/verifier_box.sh`'s Spot→on-demand fallback into a refusal that prints the Spot code it saw and the on-demand hour it declined to buy — N shards each answering a capacity refusal with an on-demand box is N boxes against a quota an order of magnitude smaller than the Spot one, bought without anybody deciding to; the valve is `DJB_VERIFIER_ON_DEMAND_OK="<reason>"`, the reason prints in the bank's table, and a SINGLE `up` keeps the fallback (printed, with the price) because one box is a decision an operator is standing in front of. The price comes from the Price List API through `DJB_VERIFIER_PRICING_REGION`, which has no default and prints as unknown when unset. **The market each box is actually on is EC2's `InstanceLifecycle`, never the market the launch asked for** — `up` prints it as its own `market` line, `census` carries it as a column, and the bank's shard table keeps it, because afterwards the boxes are gone and the table is all there is to cost the bank from. Every launched box is taken down on green, on red, on exit 2 and on a signal; a `down` that fails names the hand and the bank's own status stands. Driven by `scripts/tests/test_pm_push.sh` (every refusal, the plan against a planted listing, the seven composition plants, the composed row's grammar, the hook honouring it, and the teardown on all three exits) — which stubs the wrapper and asserts the SEAM's argv, `scripts/verifier_box.sh leg <id> --unit U [--shard k/N] [--passes 1] --log leg`, and nothing past it.

**The image, built once, by the bank (ADR deploy-4a, PROPOSED).** After the row is written and before the boxes go down, ONE box — the acceptance box, the one box outside the composed verdict — asserts its own `deploy/provision.sh image-tag` against the tag the row was keyed on, mints a registry token under ITS OWN instance role (`deploy/iam/verifier_bootstrap.sh` prints the `put-role-policy` that grants it, scoped to this namespace's two repositories and carrying no delete), builds `--target web` and `--target worker` and pushes both under `tree-<12hex>`; the bank prints the seconds and the registry's own digests, and `.github/workflows/ci.yml`'s `images` job skips a tag the registry already holds. **Every failure here is printed and the row stands** — no registry coordinate, a tag that is not this tree's, a build or push that failed: an image is downstream of a verdict and never part of one, and CI's job is the fallback that builds what the registry lacks. What the bank pushes is what the box builds natively (`linux/arm64`), which narrows deploy-4 (a)'s two-architecture manifest for a bank-built tag — the owner's to sign with the amendment.

**The test-impact map, and it is a PROJECTION and never truth (principle 9).** `scripts/test_impact.json` is tracked, regenerated per wave the way `scripts/pytest_durations.json` is, and says for every collected test which checkout-relative source files that test EXECUTED. **Its owner is the acceptance run**: `pm_push.sh --bank --on-boxes N` brings up ONE extra box labelled `acceptance`, outside `bank_boxes_plan` and outside the composition, which runs the whole suite twice — pass 1 under `--cov=apps --cov=config --cov-context=test` so every measured line carries the nodeid that executed it, pass 2 plain — and then runs `scripts/test_impact.py write` on the box to invert pass 1's coverage database into the map. The bank **fetches** the file into the working tree, prints `git add scripts/test_impact.json`, and **commits nothing** (a bank takes no commit); the PM commits it as it commits the durations file, and the next bank in that checkout refuses a dirty tree until that has happened, which is the same rule every other derived file lives by. **Its status is printed and composed NOWHERE** — not in `lost`, `red`, `foreign` or `kbad`: a measurement may not refuse a claim every shard passed, so a coverage run that died or a writer that could not look each cost one wave of the map and nothing else, and the loop keeps the closure scope it has today. **The LEAK PROOF beside it is the opposite kind of thing, on the same box and in the same file.** Since ADR gate-1's amendment that box's two whole passes run under ONE seed minted on the box, `-n 16` on both, each under `set +e` writing its own status into `~/verify/<rung>/proof.txt` as `seed=<n> workers=<n> pass1=<rc> pass2=<rc> map=<rc>` — and the bank fetches that file to `<sink>/acceptance.proof` and reads it exactly like a shard's: no box, no file, nothing parsable or no seed is **`lost`** (exit 2, no row, saying that one pass was measured and nothing proved what it left behind), a non-zero `pass1=` or `pass2=` is **`red`** (exit 1, no row, naming the box and its log), and only a green pair reaches the row as `leak-proof=`. **`map=` is the measurement half of that same file and decides nothing** — the two roles separate at the `rc` each one wrote, so a bank whose passes are green and whose map writer died writes the row and prints that the map was not written. Where there can be no acceptance box at all (its checkout path is unreadable) the shards run two passes each and the bank is byte-for-byte the one it was before the amendment. **The census is the map's whole contract**: every collected nodeid is in `tests` or in `unmapped` with a reason in words, never neither, never both, and never an empty list — an empty list reads downstream as "this test touches nothing" and is never selected again, for any change, ever — and a nodeid the collection has and the coverage database has no context for is exit 2 with no file written. **What the map cannot see, declared** (`scripts/test_impact.py`'s header): what a test reaches through a subprocess, and everything that is not Python — templates, fixtures, `.env`, assets read by path — so a reader that SELECTS from the map owes a fallback for a changed file the map has never recorded. Driven by `scripts/tests/test_test_impact.sh` (the census, the two could-not-looks, determinism) and, for the box and the composition, `scripts/tests/test_pm_push.sh`.

**Database** — `scripts/db.sh` derives `DATABASE_NAME` as `djb_<branch>_<8-hex path hash>`, so every checkout — clone or worktree, same branch or not — gets its own database on the one compose Postgres; a `DATABASE_NAME` already in the environment wins over the derivation, and `setup.sh` persists the derived name into `.env` so a bare `manage.py` resolves the same database the scripts do — reconciling a stale pin on every run unless a `# pinned` comment line sits directly above the bare `DATABASE_NAME=<name>` line (the deliberate-pin marker — its own line, never inline, because `environ.read_env` and docker `--env-file` read an inline comment INTO the value; `db.sh` refuses the inline form and prints the disagreement either way). Test DB is `test_` + that name (Django default).

**Compose** — `compose.yaml` pins `name: djangobootstrap`, so every worktree addresses the **one** stack (the organ set is compose.yaml's to enumerate — postgres/redis/temporal/zitadel/mailpit/minio/meilisearch/observability today) rather than a stack per directory; `scripts/setup.sh` reuses a running stack and only starts what is not up. Two worktrees share the containers and never the database.

**Tests** — `pytest-django` + `pytest-asyncio`, pyproject config, `--reuse-db` off by default (honest). Workflow tests run under `temporalio.testing.WorkflowEnvironment.start_time_skipping()`; consumer tests use **`apps.realtime.tests.websocket`** — the in-repo raw-ASGI client, which speaks the websocket protocol to the real application; `channels.testing.WebsocketCommunicator` is deliberately *not* used, because any import under `channels.testing` runs an `__init__` that imports `daphne`, and this repository serves ASGI with uvicorn and does not install it (ruled: keep the client, no daphne dependency). MCP tool tests call the tool functions with a fake context. `scripts/test.sh` exits with pytest's status and is never piped.

**House rules** — `quality/rules.yaml` is the single source of truth: per rule `id · statement · check · doc · scope (derived, never typed) · floors · canaries · negatives · does_not_cover`. `quality/gate.py` runs them; `python -m quality.gate` exits 0/1/2. Canary fixtures live in `quality/canary/<rule-id>/`, negatives in `quality/negative/<rule-id>/`, planted through the real scope at self-test time and removed after.

**Introspection** — `uv run python manage.py introspect` prints JSON: `apps`, `models` (fields, relations, bases), `urls` (name, pattern, the callable), `routes` (pattern, methods, name, `auth`, `paginated` — from the live ninja registry), `tools`, `consumers`, `workflows`, `activities`, and the non-secret `settings`. This is what agents read instead of guessing.

**Skills** — every development brief says: *load `.claude/skills/django-conventions/SKILL.md` before writing code.* The product-manager skill's dispatch-briefs say so too.

## Where a product's edge census lives

A product's edge — the load balancer rules, the reverse proxy's routes, the
prefixes the front door actually answers on — is configuration nobody's app
imports, so a tripwire over it has to run at **every** scope or it is not a
tripwire. **Put it at `apps/test_<edge>.py`: a test module at the `apps/` root,
belonging to no app.** That placement is always-on *by construction* rather than
by a marker anyone can forget — an item whose nodeid names no app can never be
inside any scope, so `--loop`, `--loop --mine` and `--pr` all leave it selected
(`apps/conftest.py`, `_is_always_on` and the `apps_root_modules` floor beside
it), and the floor notices if one of those modules is moved aside. `apps/test_*.py`
is the platform's own mechanism, not a product concept: this repository ships
three such modules, and a product adds its own beside them without touching
`config/`, `pyproject.toml` or the scope derivation.

**`deploy/tests/` is the wrong home for one, and silently so.** pytest collects
only `testpaths = ["apps"]` (`pyproject.toml`), so a Python census under
`deploy/` is never collected by any pytest leg; and the shell drives that do live
there are invoked by **no gate moment** — not `--fast`, not `--loop`, not the
full gate, not CI — which `scripts/check.sh` prints as a declared blind spot at
the end of its selftest-drive leg. A census placed there is green because nothing
ever ran it.

**A fact about an external system is measured by a HAND-RUN INSTRUMENT, never by
a gate leg** (ADR ident-5(a): the suite never dials). `manage.py zitadel_measure`
is the worked example and the shape to copy: a management command that re-asks
every constant the tree took off somebody else's product, prints one line per
fact in a closed vocabulary (`ok` · `DIFFERS` · `could not` · `unmeasured —
<rung>`), exits 0/1/2 on that population, builds and deletes its own victims, and
owes a row in `docs/product/instruments.md` — `*_measure` is in the census's
`CENSUS_COMMANDS` population exactly so that it does. Its suite module
(`apps/accounts/tests/test_zitadel_measure.py`) proves the instrument can FAIL
against a fake and vouches for nothing about the live build, which is the whole
division of labour: the gate holds the reporting, the hand run holds the fact.

## Conventions every layer assumes

- Settings via `environ`/`os.environ` with `.env.example` as the complete list. No secrets in the repo. `config.settings.local` is the default `DJANGO_SETTINGS_MODULE` for `manage.py`; `config.settings.test` for pytest; `production` is what `check --deploy` is run against.
- `AUTH_USER_MODEL = "accounts.User"`, `DEFAULT_AUTO_FIELD` irrelevant because `BaseModel` sets a UUID pk.
- Secrets never in the repo; the Fernet key for `connections` credentials is `CONNECTIONS_ENCRYPTION_KEY` in `.env.example` with a generated dev value and a production-raises-if-missing check.
- Redis: `REDIS_URL`; Temporal: `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE`.
- `apps.<name>` import path; each app's `AppConfig.name = "apps.<name>"`.
- Python 3.12, Django 5.2 LTS, pinned in `pyproject.toml`; `requires-python = ">=3.12"`.
- Commit messages in the repo's register: what changed and why, no counts that will drift.
- **A query pin says which hat it was taken under.** The tenant root is resolved once per `Tenant` instance and `core.middleware.resolve_org` is the only thing that fills the memo — from the hat it resolved, and only when that hat IS the root. So the same door measured under a ROOT hat pays no root read and under a BRANCH hat pays exactly one, once, however many writes the request makes. A pin captured under one and read as a fact about the other is off by one for a reason nothing in the number says: name the hat in the pin's own sentence.
