# Architecture — the settled decisions

**Status: standing.** Decisions here
are settled; do not reopen them. Where a product cloned from this template
needs to diverge, it records the divergence in *its own* `architecture.md`
with the reason, so the template's defaults stay legible.

**A template-owned file a product edits is a divergence they record, and the
grammar is one greppable line:** `divergence: <path> — <reason>`, in the
product's own copy of this file, one line per path. Which paths are
template-owned is `docs/product/build-contract.md` § Ownership, per path;
`scripts/divergence_census.sh` is the reader that holds the two together — it
lists every template-owned path whose content is not the declared base's, exits
1 on one this file does not name, and prints the line to add. A divergence is a
decision, not a defect; an UNRECORDED one is a merge conflict with a countdown
on it, and the first consumer paid twelve of them in one fold (ADR
platform-extension-1).

Ruling summary: API layer (ninja) · tenancy on by default, shared
schema · bring your own front end · day-zero stack (Redis, Channels, ASGI, MCP)
· Temporal from the start · services + selectors · audit trail on by default ·
ClickStack as the one sink · UUIDv7 · roles + policies as the authorization
model · admin through services · GitHub Actions as CI · no template-sync
tooling yet · and every item in "The platform the template ships" below.
Nothing in this file is unconfirmed.

## What this is

A template for Django products. It carries the agent team, the method, the
quality gate and the house-rules engine, plus the guardrails that follow from
running parallel agents against one Django schema. **It is not a product, and
it is not a port of one.** The product ledgers ship as skeletons.

## The stack

| Decision | Ruling |
|---|---|
| Framework | Django **5.2 LTS**. Move on the next LTS, not on feature releases. |
| Python | 3.12+ |
| Package manager | `uv` |
| Database | **PostgreSQL**, always — including tests and every worktree. Never SQLite, even locally: the Postgres-specific fields, constraints and query behaviour are part of the contract. |
| Containers | `compose.yaml` with **Postgres, Redis (channel layer + cache), and the Temporal dev server**; the app and the worker run on the host against them. |
| API layer | **django-ninja, Pydantic v2 schemas. Decided.** One contract language across every door: the same schema is the REST response, the MCP tool output, the webhook body and the socket payload. Every route declares `auth=`; every list uses `@paginate`; OpenAPI at `/api/v1/docs` (the API is mounted under `/api/v1/`; `config/urls.py` owns the version segment). DRF was the earlier default and lost once the door set (MCP, webhooks, sockets) made a second schema system inevitable. |
| Auth & identity | **Zitadel is THE identity system — B, all at once ("we're fresh, let's do it right so we pay the cost once"; supersedes the earlier app-is-its-own-IdP approach).** Self-hosted Zitadel (Apache-2.0) in compose from day zero, its config **as code, driven through our services via its management API — the Zitadel console is NOT a door**: an identity-config change that did not go through our audited services did not legitimately happen (house-rule-shaped invariant). Browser login: the app is an OIDC relying party against Zitadel (allauth reduced to RP plumbing). **Workforce**: Google federated through Zitadel, domain-restricted. **Customers**: per-org external IdPs (Okta, Entra, SAML/OIDC) — `SsoConnection` survives as the audited config-of-record whose services re-point from allauth internals to Zitadel's API; home-realm discovery, enforced-SSO, domain claiming, JIT membership keep their A9 wire-proven properties, re-proven against the new engine. **MCP**: OAuth 2.1 with Zitadel as the authorization server; tokens exchanged into the org-bound principal; DCR/consent are Zitadel's. **SCIM**: Zitadel's, maturity verified at the first customer demand (WorkOS stays the named fallback if it falls short). The suite-IdP end-state arrives at day zero instead of at the second product. A fresh clone's `setup.sh` seeds Zitadel — a deliberate DX rung, not an accident. An IdP answers *who*; `Membership`/roles/policies/audit stay ours, unmoved. **Amended 2026-09-15 (owner, DESIGN-I decision A, on P20's evidence: a 21-minute first admin on the hosted page):** ADR ident-4 reads "Zitadel holds every credential and decides what is required; OUR page renders" — the hosted page stops being the front door; lane I-A's sign-in remedies and A1's join at sign-in are the first instances. **Amended 2026-09-30 (owner, identity option B — ADR ident-13):** "Customers: per-org external IdPs" now means a realm per tenant — every tenant signs in at an organisation of its own at Zitadel, made when the tenant is (`EnsureTenantIdentityHomeWorkflow`, recorded on `accounts.IdentityHome`), the platform's one project granted to it, with its own login policy and providers; the deployment's existing organisation is the **staff realm**; a tenant's `enforced` is its realm's login policy. A person is one `User` holding one subject per realm through the identity join (`SsoIdentity` rows with no connection), which replaced `User.zitadel_sub`. The per-tenant operations go through a port we own, `apps/accounts/realm.py::IdentityRealm`, with Zitadel its first adapter (`apps/accounts/realms/zitadel.py`); the deployment-level bootstrap (the seed, the audit, the sign-in seam) stays in `apps/accounts/zitadel.py` and its commands. |
| Custom user model | **Set on day zero**, before the first migration, and boring: `AbstractBaseUser` + `PermissionsMixin`, email as the identifier, no product fields. Own the table; do not design the user. House rule: `auth.User` is never imported; `get_user_model()` / `settings.AUTH_USER_MODEL` only. |
| Base model | Every concrete model inherits `core.models.BaseModel` (**UUIDv7** pk — time-sortable — `created_at`, `updated_at`). House rule. |
| Business logic | **Explicit `services.py` for writes and `selectors.py` for reads, per app. Decided.** Services own writes; routes and schemas are thin; models carry invariants and derived properties, not workflows. **No business logic in signals** — signals are where agents hide logic. House rule. |
| Tenancy | **Shape: shared schema + tenant FK, read through a scoped manager, enforced by a house rule. ON by default; a product opts out. Decided.** The template ships `core.Tenant`, `core.Membership` (user × tenant), the abstract `TenantScopedModel(BaseModel)` with a `tenant` FK, a `ScopedQuerySet.for_tenant(tenant)` manager, and `TenantMiddleware` that resolves `request.tenant` from the user's membership (default membership; an `X-Tenant: <slug>` header may switch to another tenant the user belongs to; no membership → `request.tenant = None` and every scoped read returns nothing — **fails closed, no superuser exemption**). The example app inherits `TenantScopedModel`; every read in views and services is `Model.objects.for_tenant(request.tenant)`; house rule 8 is **enabled** and refuses a bare `.objects` on a scoped model outside the manager. **Opting out** (a genuinely single-tenant product) is recorded in the product's `architecture.md`: models inherit `BaseModel` instead, the middleware is removed, rule 8 is set `enabled: false` with the reason. Schema-per-tenant (django-tenants) is **not** a template option: a product may adopt it only under heavy consideration and only when it is an actual business requirement (e.g. a compliance demand for database-level isolation), recorded with the requirement named. Rationale: the base, the resolver and the rule are the part that is painful to retrofit; shipping them on means the leak-shaped code is refused from the first model. |
| Hierarchy | **A template primitive, on from the start ("this framework needs to support hierarchies efficiently and securely from the start").** Per-tenant `Organization` tree (materialized path, fixed-width segments, indexed prefix scans — no recursion, no tree walks on the read path); **every tenant gets a root node automatically**, so a flat product is a depth-one tree and pays nothing. `Membership` = person × tenant × org × role; `OrgScopedModel(TenantScopedModel)` for networked records; reads are `.for_tenant(t).visible_to(actor)` — **visibility flows down only, fails closed, no exemptions** (upward/sideways inheritance only as an explicit policy with a named reason). Roles inherit down (effective role = best role on the record's ancestor chain, computed over the actor's own memberships). Acting hat via `X-Org`, revalidated per request. **No grant above your own effective role or outside your subtree** (the escalation wall). Re-parenting is a service + workflow, audited, ancestor-admin of both ends only. Aggregates go through the same scope. House rule 24 enforces `visible_to` on org-scoped reads by AST, with canaries. Audit and workflow context carry the acting org. |
| Frontend | **Opinionated default — Next.js/React/TypeScript consuming the GENERATED OpenAPI client. Owner-ratified 2026-09-02, superseding "bring your own"** (which had drifted false against the tree: `frontend/` ships Next 16.3.3/React 19.2.8 since the P16 SCAFFOLD merge, `fe-conventions` is written at those pins, rules 51–53 enforce the layer — the register said none while main shipped one; the drift was caught by the owner's own question). The halves meet ONLY at the OpenAPI document (P16 strategy pillar 1): doors serve it, the client is generated never hand-typed, the byte-pin makes drift loud; the backend never imports or assumes the client. **Bring-your-own remains legal as a recorded product divergence** in the product's own architecture.md — at the cost of the scaffold, fe-conventions and rules 51–53's enforcement, which that product replaces or forgoes. Rejected: keeping "bring your own" settled with `frontend/` demoted to a non-normative example (weakens the JS rules' standing on every product that takes the default); reversing the frontend package (the ratified P16 strategy's frontend half, built and verified). |
| Background work & workflows | **Temporal, from day zero. Decided.** Durable execution for everything that must survive a restart or wait: webhook delivery with backoff, integration syncs, multi-step processes that wait for a human or a signal, schedules. **Activities** call services; **workflow code is deterministic** — a workflow module imports `pilecap.determinism` (and its app's `types.py`), never a clock, randomness or I/O; the ORM, `pilecap`'s root and the apps are the activities' (house rule 9). Local: the Temporal dev server in `compose.yaml`; a `worker` process beside the web process. Production: Temporal Cloud by default, self-hosted as the recorded alternative. **There is no Celery, no beat, no `django.tasks` backend** — Temporal is the one engine for tasks, retries, schedules and workflows. |
| Server | **ASGI by default** (`uvicorn`), because sockets and async endpoints are day-zero. The CRUD core stays on the sync ORM; async where an endpoint is I/O-bound. |
| Sockets | **Django Channels** with the Redis channel layer; one authenticated consumer; services emit events that the realtime bridge pushes. (ADR realtime-2) |
| MCP | The official Python MCP SDK mounted on the ASGI app at `/mcp` (Streamable HTTP). Tools are thin over services; token auth bound to user + tenant. The machine door — same services as REST; a disagreement between doors is a finding. |
| Webhooks & events | `apps/events`: services `emit()` domain events → an **outbox** row → a Temporal workflow fans out: signed outbound webhook deliveries (HMAC, retries, dead-letter) and realtime pushes. Inbound webhooks are verified, stored and handed to a workflow — never processed inline. |
| External connections | `apps/connections`: per-tenant `Connection` (provider, **encrypted credentials** — Fernet, key from env — status), an `httpx` client factory (timeouts, retries, idempotency keys), the OAuth-callback pattern, one inbound-webhook receiver. Providers are product work. |
| Communications | **A template platform app (`apps/comms`) — every product needs it and uses it; it must be easy and consistent; what changes is the provider behind it. Decided.** One door: `comms.send(*, recipient, template, context, channel, tenant, actor)` — nothing else in a product sends anything (house-rule-shaped: the only legal sender). Behind it: a **channel-provider registry** (email built in via the mail path + django-anymail at the ESP edge; SMS/Slack/push as `connections` providers a product enables — swapping a provider is config + a connection, never a code path change). `Message` (per-attempt log: channel, provider id, status queued→sent→delivered→bounced, correlation ids), `MessageTemplate` (per-tenant, versioned, variables schema-validated), `ChannelPreference` + consent (category opt-outs — transactional vs marketing, quiet hours, suppression) **enforced inside `send()`, so no campaign or feature can bypass it**. A `Recipient` concept for people who are not Users (contacts). Delivery, retries and fallback ("push, then email if unread") are Temporal workflows; provider status webhooks arrive through `connections`/`events` and become `comms.message.*` events. **Novu is the recorded escalation** for marketing-grade journeys/digests/inbox UI, as a product divergence with the requirement named — never the default. (ADR comms-9; ADR comms-10; ADR comms-13) |
| Typing | `mypy --strict` + django-stubs, as a blocking gate leg. |
| Hosting | **A product decision, not a template ruling ("leave the hosting decisions to the app builder").** The template ships everything a hosting choice needs and nothing that presumes one: Docker images (web + worker), `/healthz` + `/readyz`, CI, compose for local, `.env.example` as the config manifest, expand/contract migrations. Standing guidance a product starts from, not rules: two stateless containers need no Kubernetes (K8s is an escalation, not a default); prefer managed backing services (Postgres, Redis, Temporal Cloud and ClickHouse Cloud — BAAs already in place); each product records its runtime, IaC flavor and region shape in its own `architecture.md`. **Secrets (standing default): AWS Secrets Manager** (SSM Parameter Store for non-secret config), injected as env vars by the runtime (ECS `secrets:` block or equivalent) — the app reads env only, so the vault is invisible to code; stage and prod are the same mechanism with different ARNs; CI holds no long-lived cloud secrets (OIDC role assumption; test env keeps the published dev values production refuses). Escalations, dated: Vault/OpenBao for multi-cloud or dynamic DB credentials; Doppler-class for Render-tier hosting. |
| Settings | A `settings/` package split by environment; `manage.py check --deploy` clean with warnings treated as failures. |

## The collision point — schema, and how the team is shaped around it

Parallel agents plus a shared schema is the one place the Django and
parallel-agent goals collide. Everything distinctive about this system funnels
into that point:

- **App boundaries are agent boundaries.** A rung names its app. A rung that
  needs two apps is two rungs, or an engineering-lead decision recorded as
  such.
- **Migrations are made inside the rung**, from the models changed there. **`makemigrations --merge` is forbidden in a rung.** A merge
  migration means two agents touched one app — a PM ordering failure,
  surfaced, never patched.
- **`django-linear-migrations`** is on from day zero: one leaf per app,
  `max_migration.txt` per app, so a collision is a git conflict before it is a
  CI failure.
- **Each worktree gets its own Postgres database**, so a rung's gate measures
  its own tree and nothing else. Therefore **parallel backend rungs are legal
  when they are in different apps.** The dispatch brief says so explicitly,
  both halves: different apps may run concurrently; the same app never does.
- **`import-linter`** enforces the app dependency contracts: `core` imports
  nothing above it; domain apps never import each other sideways.

## The doors and the event spine

Every product has the same doors and they all meet in one place:

- **REST** (`apps/<x>/api.py`, ninja routers, discovered and mounted by `config/api.py` at `/api/<label>/`, or at `/api/<PREFIX>/` when the module names `PREFIX`),
- **MCP** (`apps/<x>/mcp.py`, tools discovered and mounted at `/mcp`),
- **Sockets** (`apps/realtime`, one consumer joining the tenant, org-subtree and user groups the bridge's `tenant_group` / `org_group` / `user_group` build — ADR realtime-2, `76c8a7e0b`),
- **Webhooks in/out** (`apps/events`, `apps/connections`),
- **Workflows** (`apps/<x>/workflows.py` + `activities.py`, discovered by the worker).

**Every door calls services; services own writes and `emit()` events; workflows carry anything that must wait or retry.** **Upward calls invert through the bridge**: when a lower layer needs a higher one (`core.mail` starting a workflow; a `core` service emitting an event), it calls `core.bridge.get("<name>")` — a runtime registry that higher apps fill from `AppConfig.ready()` (`workflows.start_on_commit`, `events.emit`, `realtime.push`). An upward *import*, even function-local, is a violation, and none is excepted: `core.mail`'s import of `apps.workflows` went when the bridge landed (`e63d336eb`, rung A3). Absent registration = the bridge raises in production settings and no-ops with a log in local/test — a template without the platform apps still runs. Registration is by **discovery, never by editing `config/` or `pyproject.toml`**: `INSTALLED_APPS` is derived from `apps/*/apps.py`; a new app drops an `api.py`, `mcp.py`, `workflows.py`, `activities.py`, `consumers.py` and the mounts find it; an app declares what it may import on its own `AppConfig` (`depends_on`) and house rule 7 enforces it, with import-linter keeping only the fixed layer contract (`core` ← `accounts` ← `workflows` | `events` | `connections` | `realtime`, pyproject's `layers`); every other app's fence is house rule 7 alone. That is what lets one agent per app run in parallel without touching a shared file. (Ruled after an early alignment review found registration was hand-listed.)

## Service architecture — the architect's rules

The engineering lead **loads `.claude/skills/django-architect/SKILL.md`** before decomposing and cites the rules it applied in every criteria set. The skill is the long form; house rules 11–26 above are the gate-enforceable subset. The lead's two deliverables before any code: **an app map** (nouns, dependency arrows, doors each exposes, workflows each owns) in the product's `architecture.md`, and **an ADR line** (context · decision · rejected alternatives) for every cross-app decision.

Boundaries: an app is one domain noun and its aggregate; dependency direction is `core` ← `accounts` ← platform (`workflows`, `events`, `connections`, `realtime`) ← domain; a domain app never imports another sideways — it emits an event or declares a dependency on its `AppConfig.depends_on` in the same rung; split when the second aggregate appears, never at a size.

Authorization — **both layers, with a clear division**: the door authenticates and resolves the tenant; the service authorizes, object-level, via `core.authz.require(actor, action, obj)`, and every scoped read asks in its selector. **The vocabulary is one shape, `<kind>.<verb>`**: every first-party model is a kind (`authz_kind`, derived from the class name, overridable), every kind carries `create/read/update/delete` by derivation, every other verb is a status transition or compound act declared on a kind in its app's `ACTION_PROSE` with its sentence, and one reserved verb, `tenant.own`, belongs to ownership. **Three layers, one owner each**: `owner`, the one platform role, IS the vocabulary; every other role is declared in an app's `roles.py` with a pattern collection (`apps/core/roles.py` ships `admin` and `member` and is the one product-editable file in `core`); a tenant's data is `core.Role` (custom roles), `core.RolePermission` (include/exclude deltas and custom collections, keyed by role key), `core.Grant` (one person's `allow` or `withhold`, withhold winning). `Membership.role` names a role by key and inherits downward as memberships do. `require` evaluates at the node the object names, answers no to anything outside the vocabulary, and composes `holds AND predicate`. **Nobody hands out what they do not hold and nobody takes back what they do not hold**; the root always keeps one un-withheld owner. Rule 13 proves a service asks for the kind it writes; rule 54 proves the vocabulary derives, the rows name it, and the reads ask.

API contract: `/api/v1/` from day one (`NinjaAPI(version="1")`); additive changes only — a breaking change is a `v2` router beside `v1`, declared by the lead; every list `@paginate` (**cursor**: `?cursor=` and `?limit=` ≤ 200, envelope `{items, has_more, next_cursor, count}`, `count` computed only for `?include_count=true` — ADR core-18, owner-ratified, which retired `page`/`page_size` outright on the licence of the empty consumer register), filters via a `FilterSchema`, `ordering=` from a per-route allow-list, `q=` for search, errors `{detail, code, errors?}` from the single mapper, UUIDs in paths; one schema per shape shared across the doors; an `Out` never exposes another tenant's identifiers.

Concurrency: read-modify-write under `select_for_update` inside the service; no version column by default. Idempotency: `Idempotency-Key` on every write route (stored response replayed, tenant-scoped) and idempotent activities.

## Observability — one sink

**OpenTelemetry over OTLP to ClickStack.** Logs, traces and metrics from the web process, the worker and every door go to the one `OTEL_EXPORTER_OTLP_ENDPOINT`; nothing writes anywhere else. `core/observability.py` is the only configuration point (SDK, resource attributes `service.name` = web|worker, Django/psycopg/Redis/httpx/Channels instrumentation, Temporal `TracingInterceptor`, structlog → JSON with `trace_id`/`span_id`). `core/log.py` is the only logger. The `@service` decorator opens a span `<app>.<service>` and logs `.called`/`.failed` with the bound context; metrics are the OTel ones (route latency/status, service count/duration/failures, workflow/activity outcomes, outbox lag, delivery failures). Local: an OTel collector in compose fanning out to the **ClickStack all-in-one** container behind `--profile observability`; production: ClickStack at the endpoint.

## Traceability — three questions answered on every row

- **Request:** one trace from door → service → event → workflow → webhook (`traceparent` propagated, including into outbound webhook headers).
- **Session:** `session_id` (hashed Django session key · MCP session id · socket connection id) bound into context and set as the OTel `session.id` attribute, so one query reconstructs a session end to end.
- **Business correlation:** `correlation_id` (minted at the door) and `causation_id` (immediate parent) on every `Event`, `WorkflowRun`, `Delivery` and `AuditEntry`, carried in Temporal memo and `X-Correlation-Id` — the join key that survives restarts and days.
- **Audit trail, on by default:** `core.audit.AuditEntry(TenantScopedModel)` written by `@service` on every write — actor (`actor_user`, `actor_token`, `actor_kind` = human|agent|system), action (service name), object type + id, **door** (rest|mcp|socket|workflow|webhook|admin|shell), outcome, redacted input per `LOG_KEYS`, plus the three ids above. Append-only. Archival is a dated residual with a trigger in the product's queue. The column-by-column contract — which AU-3 content element each column answers, the actor semantics per door, the enumerated legitimate absences — is **ADR core-22** below.
- Convention (not gate): tests reference the criterion they prove, `@pytest.mark.criterion("C3")`.

## The platform the template ships

| Area | Ruling |
|---|---|
| Invitations & tenant lifecycle | `core.services.invite_member(email, tenant, role)` → the invited address's first sign-in at the identity platform joins the membership, through `accounts.adapter` (ADR ident-4); `create_tenant / suspend_tenant / close_tenant` as services. **First identity** (ADR ident-9) — a federated deployment: first sign-in through the workforce IdP, then `manage.py bootstrap_tenant --email`; a password-only deployment: `manage.py zitadel_first_admin --email`, open the link it prints and set a password, sign in, then `bootstrap_tenant --email`. `zitadel_first_admin` refuses once any tenant exists, so `invite_member` is the only invitation path from the first member on. |
| Email | Django email backend called **from a workflow activity** (retries); **Mailpit** in compose for dev; a provider via `connections` in production. |
| Rate limiting | ninja throttling per token and per tenant, defaults in settings; MCP tools share the same limiter. (ADR core-19) |
| CORS / CSRF / CSP | `django-cors-headers` with an env allow-list; session auth + CSRF for a same-site front end, token auth for everything else; `django-csp` in production settings. |
| MCP auth | Bearer tokens now; the MCP OAuth 2.1 flow is the recorded upgrade when a third-party client must connect. Sockets gain the same bearer path (N5). |
| File storage | `django-storages`, local default, S3 by env; tenant-prefixed keys; presigned URLs; uploads through a service. The local S3 stand-in is MinIO's last public release, served from the owner's ECR Public mirror by digest and linux/arm64 only, because MinIO archived the project and withdrew every public image (2026-09-24) — `compose.yaml` beside the pin says how CI runs and pulls it. |
| Tenant settings & flags | `Tenant.settings` JSON + `core.flags.is_enabled(tenant, name)`; no third-party flag service. `core.services.update_tenant_settings` merges `values` key by key (a `null` removes a key) and validates only `timezone`; **the keys and their values are NOT schema-validated — a declared gap**: no per-key schema registry exists, so a product that needs typed settings declares the schema in its own service before writing. |
| Events | `v` on every payload; outbox retained; `manage.py replay_events`. |
| Erasure & retention | `accounts.services.erase_user`; audit/outbox archival recorded as dated residuals with triggers. |
| Seed, backup, restore | `manage.py seed` (dev data; the method still drives from zero); `scripts/backup.sh`, `scripts/restore_drill.sh` so the restore tripwire has something to fire. |
| Runtime | `Dockerfile` (web + worker targets); `/healthz` (liveness) and `/readyz` (db, redis, temporal); whitenoise for admin/docs static. |
| Database connections | ADR config-1 |
| CI | **GitHub Actions** runs `./scripts/check.sh` (full) on every PR, against this repository's own `compose.yaml` (`docker compose up -d --wait db redis temporal`), not hand-built service containers — half the gate reaches Postgres and Temporal through `docker compose exec`, so CI runs the gate and CI provides the environment the gate assumes (`.github/workflows/ci.yml` is the authority and names what it excludes). The gate is the only CI. |
| Contracts & DX | Pydantic schemas per socket message type, listed by `introspect`; `scripts/gen_client.sh` (openapi-typescript) optional; `.editorconfig`. |
| i18n | English only by default (`USE_I18N=False`); `Tenant.timezone`/`locale` present for display; a product turns i18n on as a recorded decision. |
| The product's name | ADR platform-1 |
| Template updates | `TEMPLATE_VERSION` + `CHANGELOG.md`; a release is ONE squashed child commit cut by `scripts/publish.sh --release` and tagged, and **products merge the tag** — never cherry-pick — adjudicating what the merge deletes against their local patches (owner ruling 2026-08-30, cycle P17; supersedes the earlier cherry-pick line; root re-cut permanently retired). Trigger unchanged: three products exist → revisit sync tooling. |
| The SDK's version | ADR sdk-1 |
| Left to products | Specific providers, SSO/SAML/SCIM, search beyond Postgres FTS, notifications beyond email, admin theming, PgBouncer, Temporal self-hosting, multi-region. |

## The gate

`scripts/check.sh` with `--fast` / `--loop` / full, a verdict ledger keyed on
the tree hash, `pre-commit` runs fast, `pre-push` consults the ledger. Legs:

`ruff` · `mypy --strict` · `pytest-django` (×1 in `--loop`, ×2 full) ·
`makemigrations --check` · linear-migrations · `check --deploy` · import-linter
· house rules · e2e.

Exit semantics inherited from the house-rules engine: **0 clean · 1 violations
· 2 enforcement broken**, and 2 outranks a pass.

**The suite runs parallel and in random order** (ADR gate-1). Both
pytest legs run `-n auto` — one xdist worker per core, each with its own test
database, because pytest-django suffixes the checkout-derived name
(`test_<DATABASE_NAME>_gw0..gwN`), so worker isolation **nests inside** the
checkout isolation `scripts/db.sh` already gives and two checkouts running
suites concurrently still never meet. pytest-randomly shuffles collection and
prints its seed on every run, so a red order replays with
`--randomly-seed=<seed>`; xdist alone was rejected because it reorders as a
side effect of distribution, which would deliver the same ordering couplings
one at a time, months apart and unattended. The two legs differ in exactly one
way, and it is the point: **`--loop` takes a fresh seed every run** (discovery,
continuously, at the most-attended tier), while **the full gate's `pytest-x2`
feeds ONE seed to both passes** so the collection order and the worker
assignment are identical across the pair — which is what keeps that leg's
meaning intact, since a pass-2 red can then only be state left behind and never
a different order. `-n auto` is applied in the gate legs and deliberately not
in `addopts`: every worker creates and migrates its own database, so a default
would make running one test file pay one database creation per core.

**Amended 2026-09-18 (owner ruling, SIGNED by the owner 2026-09-19 ("sign all three", recorded by the PM)).** *Which principle bends:* 7 — the critical synchronous path
carries no unnecessary dependency — and gate-1's own "two passes on one
machine": under `pm_push.sh --bank --on-boxes N` the sharded `pytest-x2` unit
runs **one** pass (`--passes 1`) and the whole-suite two-pass leak proof runs
on the acceptance box, composed into the row as
`leak-proof=acceptance:<box> rc=0`. *Why the default is insufficient now:* the
second pass on every shard is a within-shard proof (`build-contract.md`
§ SHARDED) that costs a whole pass of box-time per shard, while a whole-suite
two-pass run under one seed already executes on the acceptance box and was
composed nowhere — the bank paid for the stronger proof and banked the weaker
one. *Alternatives:* drop the second pass (rejected — the leak class is real);
run it on the Mac (rejected — the constraint); a provisional row honoured
before the proof (rejected below). *Risk:* the acceptance box's two passes
(≈ 320 s measured) are longer than one sharded pass, so the proof is the
bank's wall at every N; a leak found there after a push would red a tree
already on origin. *Decision:* **the row is not written until the proof is
in** — the push waits on the acceptance box, by construction: the pre-push
wall consults the row, and a row that ran one pass and carries no green
`leak-proof=` field is refused as a missing leg, so a push before the proof
cannot pass the wall and a provisional row would be a green vouching for less
than it says (the one failure the ledger exists to prevent). The cost is that
this change lowers the wall only where the acceptance box's two passes are
faster than a sharded pair; the wall lever is that box's instance class and
`-n`, measured in the cycle's own measurement row. The local `pm_push.sh
--bank` (no `--on-boxes`) is unchanged: two whole passes on one machine.
*Reversal:* `if:` a red `leak-proof` rc is observed on a tree whose sharded
one pass was green AND the acceptance box's two-pass wall exceeds the sharded
two-pass wall by more than one whole pass at the N in use — restore
`--passes 2` in `bank_boxes_plan` (one line) and the field becomes an ignored
extra. trigger to revisit: the first bank at N ≥ 7 where the composed wall
is the acceptance box by more than 60 s — then the proof box's size is the
next rung, not this ADR.

**Amended 2026-09-27 (P23, v2.3.0 — SIGNED by the owner 2026-09-27 ("approval on gate01", recorded by the PM)).** *Which
principle bends:* gate-1's own "two passes on one machine" a second time, and
this ADR's 2026-09-18 amendment's "the row is not written until the proof is
in": on the **CI road** (`pm_push.sh --pr` → the pull request's run →
GitHub's merge → `--ci-verdict` banks the merged tree; a push to main is
refused, MQ-2), the sharded `pytest-x2` unit runs
**one** pass and **no acceptance box runs at all** — the whole-suite two-pass
leak proof under one seed is **the nightly's** (`nightly-proof.yml` (the template's own self-proof: R14 trims it from a product),
`pm_push.sh --proof`, one runner, unsharded, a record `gate_nightly_read`
reads), and the teeth move to the production deploy, which refuses without a
green nightly no older than 24 h. *Why the default is insufficient now:* the
PR run is the ONE measurement a train pays (the owner's ruling 2026-09-26:
"pay the bank once"); an acceptance box inside CI is a fourth run kind on
billed minutes per train, while one nightly measures every tree of the day
once and the class it catches — a leak only a different shard's test trips —
is not a class that must be caught before a push when prod cannot deploy
without it. *Alternatives:* two passes per shard (rejected — a within-shard
proof only, `build-contract.md` § SHARDED); an acceptance box per PR run
(rejected — the cost above, and the wall); no whole-suite pass at all
(rejected — the leak class is real, twice measured). *Risk:* a cross-shard
leak reaches main and is caught within a night rather than before the push;
what bounds it is prod's refusal and `pm_push.sh --bank --leak-proof nightly`
printing the night's form (green, red, older than 24 h, none) at the top of
every bank's transcript — every form honoured report-only there, because the
teeth are at prod. *Decision:* on the CI road the second whole pass is the
nightly's record; a box bank keeps `--leak-proof acceptance` as its default
and the 2026-09-18 amendment's rule for it (a one-pass row with no proof is not
honoured) stands unchanged. *Reversal:* set the deploy-prod job to require
the acceptance form, or restore an acceptance box to the PR workflow (one job,
`ci.yml`); the nightly keeps running either way. trigger to revisit: the
first red nightly on a tree a green PR run pushed to main — then the class is
live at CI scale and the question is whether the PR run buys the proof back.

**The envelope is measured, never vibed** (ADR perf-1). A reusable
seeded-scale harness lives in `perf/` — measurement territory beside
`quality/`, not an app, and outside the suite's `testpaths`, so neither gate
pytest leg ever collects it. `scripts/perf.sh` runs it against a per-checkout
`<derived-name>_perf` database (the per-checkout discipline extended: two
checkouts never share a perf world either) and re-seeds exactly when the spec
changes — the stamp tenant's slug embeds the spec hash. The declared
"production-real scale" volumes live in ONE place, `perf/seed.py::ScaleSpec`,
ratified as the platform's stated envelope, with per-axis ×2 multipliers
(`ScaleSpec.doubled(axis)`) — flatness is proven per axis, never by one giant
double-everything world. Instruments are machine-invariant only (query
counts, EXPLAIN plan shape, flat-under-doubling, cache-hit counts;
`perf/measure.py`); wall-clock is recorded in the measurement docs as
observation for ClickStack and never gated, and the harness refuses — at
import of a measurement module — any assertion phrased in seconds. The
division of labor with the gate: **the harness proves flatness once, the gate
pins the count forever** — a query count flat under doubling is scale-free,
so rule 5's cheap `assertNumQueries` pins inherit the harness's certification
without the gate ever seeding a million rows. Rejected: wall-clock budgets
(normalized was worse than raw), seeding the full spec inside the gate
(minutes per run, paid by every rung forever), synthetic benchmarks (pgbench
measures Postgres, not our queries), CI-machine normalization. trigger to revisit: a
real deployment doubles past any declared axis, or when a hot path stays
query-count-flat while its plan shape degrades in a way EXPLAIN assertions
miss.

**A request opens no transaction; every write's boundary is its `@service`**
(ADR perf-2, 2026-10-21 — SIGNED by the owner 2026-10-22). *Context:* under
`ATOMIC_REQUESTS = True` every web request was one transaction from its first
statement (the bearer-token read) to the view's return — the throttle's Redis
round trip, every selector, the presign, `write_audit` and the response
serialisation all sat inside `BEGIN … COMMIT`, so every non-database call in a
request was an `idle in transaction` session, and the load lockup's capture
read three of them parked on `SAVEPOINT` with the row locks queued behind
(the acceptable-tier options memo, § 7 the lockup). That is engineering
principle 8 violated by construction, and the outer transaction protected
nothing: `@service` already opens the write's own `transaction.atomic()`
(`apps/core/service.py`), the bulk seam opens its own around a batch
(`apps/core/bulk.py`), and the MCP door has always run under no request
transaction while the door-pair tests hold both doors to one answer.
*Decision:* `ATOMIC_REQUESTS = False` (`config/settings/base.py`); a write's
boundary is the `@service` it calls (rule 13 keeps every public write one), and
a route reaches at most one service boundary —
`quality/tests/test_one_service_per_route.py` censuses every mounted route,
counting call sites, with a seam that opens its own atomic counted as one. The
health views keep `non_atomic_requests` as a no-op belt. *Rejected:* keeping
`ATOMIC_REQUESTS` for the single snapshot a route that reads through a selector
and then writes through a service gets between the two (E8 already has the
service re-read its row under `select_for_update`, so the exposure is a
`not_found` race, not a lost write); per-view `non_atomic_requests` on the hot
routes (a second way to say one thing, and every new route born on the wrong
side of it). *Cost:* a request's reads no longer share one snapshot, and
assertNumQueries pins that counted the request's own savepoint pair drop by
two. trigger to revisit: a route found reaching two service boundaries that
must commit together, or a lost-write class the census cannot see (a product
door calling services through a helper outside its module, the admin's own
changelist actions). *Reversal:* one line in `base.py` and the pins back up by
two.

*Owner's signature:* Joe (owner), 2026-10-22 — the ruling of 2026-10-21 13:5x ("`ATOMIC_REQUESTS` off by signed ADR") and "go ahead" on 2026-10-22, landed by the PM in the owner's words, dated; the PM's text argues, the owner approves (principle 20).

**The gate refuses degradation** (ADR gate-2). Context: rule 5 pinned
list endpoints only; the platform's hottest reads (org resolution, subtree
visibility, `governing`, the relay's candidate selection, the audit trail's
page) had no pins, and nothing anywhere noticed when a builder's innocent
filter turned an index lookup into a walk — the frame demands the gate catch
it, not a customer. Decision: **(a)** rule 5's scope widens over a DECLARED
hot-path registry (dotted selector paths as rule-35 config in
`quality/rules.yaml`; `quality/budgets.yaml` gains `hot_path_query_counts`
under the unchanged rising-floor grammar), the counts certified scale-free by
the harness's flatness proofs (perf-1's division of labor) and pinned at gate
scale; **(b)** NEW **rule 35**: each probed registry entry pins its measured
**plan shape** and **the gate asserts sargability** — against the ANALYZEd
probe world (`quality/hotpath_probe.py`; statistics are part of "the world
exists", the seeder's precedent), under `SET enable_seqscan = off`, the
statements the real read issues stay index-served: no Seq Scan of the subject
table, and its scan is a lookup (`Index Cond`), not a walk (`Filter` alone —
a position test). An index NAME is pinned only where a fix's report
authorizes it (the measured `auditentry_tenant_created` and
`auditentry_platform_created`; the only-matching-path cases); an entry whose
measured plan legitimately answers several ways carries NO clause and cites
why (the root/flat hat rightly skips the path index — an unconditional
demand would trip a flat product's only hat; and `governing()` flips at a
benign cost crossover). Born with canaries and the declared blind spots:
planner choice at scale (with the governing()-crossover case and M4 FINDING 1 as the measured
instances) and queries not in the registry; **(c)** NEW **rule 36**: an
org-scoped payload is **never pushed to a bare tenant group** — AST over the
`group_send` call sites, whose whole subject is one decision point
(`bridge.group_for`) and two senders (M4 §8's enumeration), and rule 10's
canary set extends into `consumers.py` (the door found
named-but-never-probed); **(d)** ids 35/36 because 31–34 are assigned to
other rules by landing order. Rejected: wall-clock thresholds in the gate,
EXPLAIN cost-number budgets (planner estimates are version- and
stats-dependent — not machine-invariant), running the full harness in the
gate (perf-1's rejection), a rule over "any slow query" (an open set no
closed question can scope — the registry IS the closed question). trigger to revisit:
the next meta-review's durability triggers, or when a registry entry's
sargability passes while the harness shows the planner refusing the index at
scale (then the entry gains a harness-tier pin and the blind spot narrows).
The assembled goal-post artifact is `docs/product/scale-envelope.md`.

**The canary self-test does not run at merge** (ADR gate-3;
the decomposition drafted it as "ADR gate-4" — gate-3 was the next free
number, and an earlier citation naming gate-4 means this entry).
Context: an earlier fix gave the merge window a hook (`--fast`), and a follow-up asked whether
the canary half belongs in it — the class of defect a merge introduces
includes a plant site the merged tree absorbs, which `--fast` cannot see.
Decision: **no**. `--selftest` measures 44.7s on this tree (135 forms, 94
negatives) against a hook whose whole design constraint is that nobody learns
to work around it, and — the deciding half — it PLANTS INTO THE WORKING TREE
and refuses a tree that is dirty under a plant path, which is precisely what
a post-merge tree may be. The merge window is not left unmeasured: the
absorbed-plant-site defect is now caught by
`apps/core/tests/test_plant_sites.py` (a pytest test, so it binds in `--loop`
and at push) and, when a form does die, by the per-rule self-test floors that
name the rule instead of moving a total nobody reads. Rejected:
arming the selftest in post-merge; a "selftest-lite" that plants a sample (a
sampled canary corpus is a corpus with a hole somebody has to remember).
trigger to revisit: a dead canary is traced to a merge and the delay to push
actually cost work, or when the selftest's wall time falls below ~10s.

**The proof from zero does not run at merge either** (the owner's decision of 2026-10-24).
What bends: the SDK program's
proof from zero (`proof-from-zero.yml` (the template's own self-proof: R14 trims it from a product)) is kept as a nightly and a release-time guarantee instead
of a per-merge one — the `workflow_run` trigger is gone, the 07:53Z schedule proves every tree no
run proved, and `publish.sh --release` dispatches the proof on its source and tags nothing until
the record is green (`quality/djb/rituals/publish.py::Publish.proof`). Why: ≈ 25 runner-minutes
per merged pull request bought a scaffold red known within the hour rather than by the morning,
which nobody reads before the morning, while the tree a product clones is a tag's, proven before
it exists. Rejected: keeping the per-merge proof; proving only on `quality/sdk` or scaffold paths
(the ritual's input list is the honest closure and most platform merges are in it). Trigger to
revisit: one scaffold red found by the nightly that a merge-time proof would have caught before a
product cloned it reopens this.

### Enforcement design ("fold it in")

Reviews are the weakest rung; every architect rule that can move from review
into mechanism does. Four mechanisms, strongest first:

1. **Django system checks** (`core/checks.py`, `@register`-ed) — read the REAL
   registries, not source: model bases, field policies (`FloatField` on money
   names, `_at`/`_on`, `on_delete`, `is_deleted`), admin inherits
   `ServiceModelAdmin`, every route's auth non-None, **door parity by diffing
   introspect's REST and MCP registries**, canonical app file-shape, scoped
   models without write policies. Run on every `manage.py` call and as a gate
   leg.
2. **AST checks** (`quality/checks/`) — undecorated/positional services,
   missing `authz.require` on scoped writes, writes in selectors, querysets
   returned from services, `.save()`/`.delete()`/`objects.create` in doors,
   HTTP vocabulary below the door layer, rule-9 determinism, `emit()` outside
   services, event-name grammar, `print`/bare `logging`, `requests`.
3. **Migration linter** — AST over migration ops: non-nullable `AddField`
   without default; a drop while the tree still references the name;
   `RunPython` without reverse; second leaf; merge migration. Blocks.
4. **Diff-aware checks** (pre-commit + gate, on the change only) — model
   without migration and vice versa; new route without a test naming its
   `url_name`; new list route without a query-budget pin; **a removed or
   type-changed field on an existing `Out` schema blocks as a breaking change
   unless the diff adds a `v2` router**; new service without an audit action;
   event emitted but not declared.

**Warn tier: almost none.** Default is block with a narrow scope, negatives for
known false positives, and per-line override comments (`# rule-13: <reason>`)
that the gate **counts and prints as a standing section** — overrides are
visible and are the surveyor's first lens. The only "warn" shape is a **budget
with a rising floor** (heuristics like service length or `Out`-schema breadth):
the gate fails on growth, never on existence. **No LLM leg in the gate** — the
gate is deterministic on a tree; model judgement lives in the loop's review
stages, made cheaper by `scripts/review_pack.sh`, which emits per-rule diff
slices (touched services, new routes with their tests, migration ops) for the
reviewer.

**The standing section's held number.** Rule 84's frozen `exit2_helper` is
held, never zero, at the v2.5.0 tag and printed as `exit2_helper: 8 (declared:
G8, 2.6 — provision.sh 3 · entrypoint.sh 1 · setup.sh 2 · db.sh 1 ·
gate_ledger.sh 1)`, measured on 70f7537d (`python -m quality.gate --backlog`),
where `gate_ledger.sh` 1 still stands and leaves with its file (`loop_tier.sh`'s
1 left at d10e8cc9, GF-9a); the owner deferred G8, the shell bootstrap family, to
2.6 (v2-5-0-yardstick, 2026-10-01).
`scripts.coordinate` is 0 (rule 89's frozen `coordinate` class).

**Two doctrines from an earlier system's near-miss.** (1) Every
check is phrased as a **closed question over a discoverable population**
("does any module outside X name Y at all"), never recognition of an open set
of spellings — open-set checks get walked past without malice. (2) **Promotion
is governed by settledness, not importance**: an unsettled rule sits at
gate/test level where violations stay visible and the population is
measurable; only a settled rule with enumerable exceptions earns
impossible/refused — a level-1 enforcement of a wrong rule is worse than a
level-3 one. When enforcing into an existing backlog, use a **ratchet**: a
violation count that may only decrease.

What irreducibly stays with review — right shape, wrong content (a `require`
guarding the wrong action, an over-permissive policy, PII in an allowed key, an
unstable idempotency key) — is a `does_not_cover` declaration on the nearest
rule, and the declared blind spots are the surveyor's rotation map.

## Starter house rules (each with canaries, floors, and a declared blind spot)

1. Custom user model is set; `auth.User` is never imported.
2. Every concrete model inherits `BaseModel`.
3. Every API route carries an explicit `auth=` — on its router or on the route — and never `auth=None` outside the allow-list in `rules.yaml`; every list route is `@paginate`d.
4. No business logic in `signals.py` / receivers; services own writes.
5. Query budgets: `assertNumQueries` floors on list endpoints at seeded scale × k.
6. One migration leaf per app; no merge migrations in the tree.
7. App import contracts hold.
8. Every scoped model is read through its scoped manager (`.objects.for_tenant(...)`); a bare `.objects` on a scoped model in api, services, selectors, activities, tools, consumers, admin or config is a violation. On by default; a product that opts out of tenancy disables it with the reason recorded.
9. Workflow code is deterministic: no ORM, no `httpx`/network, no clock, no randomness imported or called inside a `workflows.py`; all of it lives in activities.
10. Every door calls services: MCP tools, socket consumers, API routes, activities, webhook receivers and admin import services/selectors/schemas — never `models` for writes, never `.save()`/`.delete()` directly.
11. Every app has the canonical shape: `models · services · selectors · schemas · api · mcp · workflows + activities · consumers · events · policies · admin · tests`; a different file name for the same job (`utils`, `helpers`, `logic`, `managers` holding business rules) is a violation. `services` may be a package `services/` re-exported whole by its `__init__`; the engine reads both forms (B1; signed by the owner 2026-10-04 — rejected: splitting core into apps; trigger: a second app asking).
12. Reads and writes are separate: `selectors.py` never writes; `services.py` never returns a queryset for display.
13. Every function in `services.py` is decorated `@service` (keyword-only, typed, `tenant`/`actor` for tenant-owned writes, returns an object or dataclass — never `dict`/`None` for a write) and calls `authz.require(actor, action, obj)` before a write to a scoped model (or carries `# authz: <reason>`). A door that contains permission logic is the same violation from the other side. **And a service that asks asks about what it WRITES**: every kind its body writes — resolved by AST through the model registry's `authz_kind` / `authz_kind_of` / `snake_case(ClassName)` — is a kind it required, or the write line carries `# authz-kind: <reason>`; and every key it requires is one the vocabulary holds, written as a literal or a module-level string constant, or the ask carries `# authz-key: <reason>`. A `require` proves only that somebody asked something — `create_widget` guarded by `widget_policy.create` is a perfectly shaped service that authorizes the wrong noun, and every other layer reads as green over it. The mismatch count is a per-app ratchet each Phase-W sweep drives to zero; a service that asks for nothing at all stays the `# authz:` clause's subject, said in the rule's `does_not_cover` rather than left to be inferred from silence.
14. Services raise `core.exceptions.*`; `HttpError`/`Http404`/status codes never appear in `services.py`/`selectors.py`; the one mapper lives in `config/api.py`.
15. Models: `on_delete` explicit (`PROTECT` default; `CASCADE` only for owned children; `SET_NULL` with a reason comment); invariants in `Meta.constraints`; no business logic in `save()`; `TextChoices` for enumerations; **no `FloatField` on money/quantity/rate** (Decimal 19,4 + ISO-4217 currency); `DateTimeField`s end `_at`, `DateField`s `_on`; no `is_deleted` booleans (`archived_at` if a product needs it). **And a secret-shaped field is encrypted at rest**: a field named `secret`, `token`, `password`, `credentials`, `signing_key`, `api_key`, `private_key`, `access_token`, `refresh_token`, `client_secret` — or any of those as a suffix — is an `EncryptedCharField`/`EncryptedJSONField`, or is allow-listed in `quality/rules.yaml` with the reason. A database dump, a replica, a backup and a traceback are four ways a plaintext credential leaves, and one field sitting in the clear beside encrypted neighbours is never a decision somebody made — it is one nobody noticed. A name ending `_hash` is a digest, not a recoverable secret, and is out of the population by construction: encrypting it would protect nothing and would break the unique lookup that authenticates every request.
16. Naming: apps plural nouns; models singular; services are verbs; selectors `get_`/`list_`/`_for_tenant`; events `<app>.<noun>.<past-verb>` declared in the app's `events.py`; schemas `XIn`/`XOut`; booleans `is_`/`has_`.
17. Door parity: a capability on REST is on MCP unless exempted in `rules.yaml` with the reason (introspect registries diffed).
18. Workflow ids are deterministic (`<tenant>:<app>:<noun>:<key>`, via `workflow_id()` — or `platform:<app>:<noun>:<key>` for a run the deployment owns rather than a tenant); **neither starter has a default for `id`** — it is required, keyword, on both `start_workflow` and `start_workflow_on_commit`, because a default turned every caller who forgot it into a caller with no idempotency at all. A four-segment constant bound to a name is the same id as the literal and reads as one; an alias on the import (`as begin_run`) does not make a random id invisible; and the platform module that *defines* the starters is excluded from the callsite scan and pinned instead — the gate asserts the two signatures still ask for the id. A schedule-started run's prefix spelled `system:` (a module-level `*PREFIX` in an app's `activities.py`) is the counted class `system-prefix`, down-only until the purge factory's one prefix takes it to zero.
19. Observability: every log line is structured through `core.log` (no `print`, no bare `logging.getLogger`, no f-string/`%` in a log call); only `core/observability.py` configures OTel/logging; no PII keys outside the app's `LOG_KEYS` allow-list.
20. Traceability: every door binds context (`request_id`, `session_id`, `tenant_id`, `user_id`, `correlation_id`, `causation_id`, `trace_id`) before calling a service; `correlation_id` is never minted below a door. **Append-only is a declared population, not a name** (ADR core-6): a model that declared `append_only = True` may have rows created and nothing anywhere may update or delete one — no `.delete()`, `.update()` or `.bulk_update()` outside the model's own declaring module. `AuditEntry` is the first member; the gate reads the population off the declarations (`core.models.append_only_models`), so a product's witnessed fact or accrual ledger is covered the moment it declares itself, with no edit to `quality/rules.yaml`.
21. Admin: every `ModelAdmin` inherits `core.admin.ServiceModelAdmin` (writes through services, scoped models filtered by acting tenant, `door=admin` in audit); a raw `ModelAdmin` on a scoped model is a violation.
22. Migrations are expand/contract: no non-nullable column without a default in the same migration as its add; no column/table drop in the same deploy as the code that stops using it (the drop is a later rung); migrations run as a release step.
23. Supply chain: `pip-audit` clean, no AGPL/GPL dependency (`pip-licenses`), no secret in the tree (`detect-secrets` against a committed baseline) — all three are gate legs.
24. Every read of an `OrgScopedModel` in a door, service or selector chains `.visible_to(actor)` after `.for_tenant(...)`; a bare tenant-scoped read of an org-scoped model is a violation. **Or `.governing(org)`** — upward *config* resolution, never upward *visibility* (ADR core-3) — and that half is fenced in the same breath: `.governing(...)` is legal only on a model that declared `InheritedDownward`, and a call on an unmarked model is a violation here for the same reason it is a `TypeError` there. Grants above the granter's effective role, or outside their subtree, are refused in the membership service. Re-parenting outside its service is a violation.
25. **`comms.send()` is the only legal sender.** No module under `apps/` imports `django.core.mail` or `apps.core.mail` outside the allow-list in `quality/rules.yaml` — `apps/comms/**` (the transport itself), `apps/core/mail.py` (the platform mailer), `apps/workflows/activities.py` (that mailer's I/O edge) and tests. Consent, quiet hours and suppression are enforced *inside* `send()`, so a feature that reaches for a mail module reaches around all three. The one standing caller — `core.services.invite_member` — is ratcheted at 1 and named for a follow-on rung (ADR comms-2), not exempted.
26. **A service names nothing the actor could not have reached** (ADR core-4). A `@service` that writes an org-scoped row and takes a parameter annotated with an org-scoped model passes it through `core.authz.may_be_named(actor, obj)` — refusing when it is False — or carries `# reach: <reason>` on the parameter. Tenancy cannot catch a reference into a branch the actor holds no membership over, because the row *is* in the tenant; the policy cannot, because the policy is about the verb. The annotation is the declaration the gate reads: which kwargs are FK targets is an open set, and an annotation naming a model in the tree is the closed half of it. Gate-tier and **ratcheted over a measured backlog** (measured before enforced, per app); every `# reach:` is counted and printed, and a bare one is itself a violation.
27. **One door to the identity platform** (ADR ident-2). Identity configuration is written through our audited services onto our rows, and *materialised* in Zitadel by `apply_identity_config` — **the row is the intent, Zitadel is the materialisation, and the console is a window, not a door**. The enforceable half: no module outside `apps/accounts/zitadel.py` names the `ZITADEL_PAT` setting (`config/settings/` excepted — it is where the environment is read), and nothing outside the `quality/rules.yaml` allow-list imports that module at all, except through the rule's own `# rule-27:` valve: the allow-list is the activity, where a management failure is a Temporal retry, plus the `zitadel_*` commands that are the shell door (`python -m quality.gate --explain 27` prints which, and the count moves without this file changing), plus the identity realm port's Zitadel adapter `apps/accounts/realms/zitadel.py` (ADR ident-13), whose callers are the ones the list already admits — an activity or a `zitadel_*` command asking `realms.current()` — so its management calls run under a retry policy or at the shell, never inside a transaction; one more caller asks it for a pure read and makes no call at all — `apps/accounts/selectors.py::get_platform_login_url`, building a sign-in URL from `authorize_params`; and `manage.py zitadel_reconcile` is the one VALVED importer — its reason says it takes `configured()` and `ZitadelError` and writes nothing at all (`apps/accounts/management/commands/zitadel_reconcile.py:198-204`). A service that reached the management API would put external I/O inside its transaction, and a Zitadel hiccup would roll back a legitimate row (C2). The honest half, declared rather than implied: **a check cannot see Zitadel's own console**, so `manage.py zitadel_audit` — read-only, changes nothing — is the runtime tripwire, and `manage.py zitadel_reconcile` asks the services to close what that audit reports, by hand, as a deploy step, with `--dry-run` and the 0/1/2 exits shaped for one. What is deliberately not built is a SCHEDULED run of the reconciler, and that command's own docstring names the trigger for building one (ADR ident-2 amended, below): a drift found in production that nobody in this deployment caused.
28. **Workflows close their runs** (ADR workflows-5). A start writes a `WorkflowRun` row saying `running` — that row is the product's own answer to "what is happening", the one a selector, an admin page or a reconciler can actually read, because nothing here queries Temporal from a selector. So every class in an app's discovered `WORKFLOWS` list either reaches its app's finish seam from `@workflow.run` — **last**, after the work, so a failure after the mark cannot leave a `completed` row for a failed run — or **declares `owns_no_run = True`**, which is the schedule-started population: nobody asked for it through a service and no row exists to close. Two seams are live and both are right (the workflow seam module's `run_to_finish(work)` / `finish_run(status=)`, `apps/core/determinism.py`; the domain apps' `self._finish(status=, error=)` method), so the gate asks for a *reference* to a seam rather than one call shape — and a seam is a name the check DERIVES (a function reaching the finish activity, transitively), never a suffix. Measured before enforced, and ratcheted over what the measurement found. Declared blind spot: the scanner sees the reference, not the path — whether the seam is reached on every branch, and whether an `owns_no_run` declaration is true, are review's and W4's reconciler's.
29. **A role is never granted above the granter**. A `@service` that takes a role-shaped parameter (`role`, `default_role`, `*_role`) and puts it into a role position — a `role=` keyword on a call, or an assignment to a `.role` attribute — calls the escalation wall (`core.services._refuse_escalation`, or `accounts.services._refuse_role_above_the_configurer`, which wraps it) in the same body, or carries `# role-bound: <reason>`, counted and printed exactly as `# reach:` is. **Nobody grants above themselves**, and neither tenancy nor the policy catches a breach: the row *is* in the tenant, and the policy is about the verb, not about the relationship between the role being granted and the granter's own effective one. The honest exception is a path with no granter at all — an identity provider asserted an identity — where the wall short-circuits by design and the ceiling lives where a person actually acted. Measured before enforced. Declared blind spot: the population is name-shaped, so a role smuggled under another name is invisible; the named trigger for tightening is the day role parameters are annotated `Membership.Role` instead of `str`.
30. **A retry clock that nothing reads is a promise nobody keeps** (ADR events-3). A `DateTimeField` matching the retry-clock grammar (`next_attempt_at`, `*_retry_at`, `retry_after_*`) must be **read** by production code outside its own declaring module and outside tests — a filter lookup, an `order_by`, a `values`/`only`, an `F()`. A write is not a read and a docstring is not a read, which is the whole rule: `Outbox.next_attempt_at` was written, indexed over `(status, next_attempt_at)` and documented in three modules while **nothing in production ever queried it**, so a row whose dispatch died held its promise for ever and only a human running `manage.py replay_events` could ever find it. The column was not broken; it was unread, and unread looks exactly like working. Measured before enforced. Declared blind spot: the grammar is the closed half (a fourth spelling of "try later" is outside it), and the rule sees that a reader exists, not that it is reachable.
31. **Every model declares how its data dies** (ADR core-13). Every concrete model in the registry carries a `Lifecycle` declaration — `purged` (with a dotted `purged_by` callable that a `SCHEDULES` `ScheduleDeclaration` chain must actually reach, walked off the registry never guessed from AST), `bounded`, `unbounded`-with-reason, or `append_only`-with-dated-trigger — declared in the owning app's discovered `apps/<x>/lifecycle.py`. Undeclared models are ratcheted per Django `app_label` (measured 32 at birth; measured before enforced) and may only shrink. The tooth: a `purged` declaration whose sweeper no schedule reaches is refused as the poller-that-was-never-built — rule 30's shape, one layer up. Declared blind spots: purge-filter correctness, reason quality, runtime schedule liveness, a reference walk depth-bounded at 2.
33. **One door to the search index** (ADR search-2). Meilisearch is
reached through `apps/search/engine.py` and nowhere else: no module under
`apps/` outside it imports the `meilisearch` client or names `MEILI_URL` /
`MEILI_MASTER_KEY` (`config/settings/` excepted, where the environment is read),
and nothing outside the `rules.yaml` allow-list imports `apps.search.engine` at
all. Rule 27's shape, pointed at a different external system and for a sharper
reason: Zitadel's fence is about a **credential** and a transaction boundary,
this one is about a **wall**. An external index that does not carry the tenant
walls is a probing oracle — type a word, learn whether somebody else's row
contains it — and the walls are injected by exactly one function
(`apps/search/selectors.py::get_search_page`, which resolves the tenant and the acting
hat's visible organization ids in Postgres per request and hands the engine ids
it did not choose). That sentence is only true while there is exactly one way to
reach the engine. And the leak has **no failure mode**: a second client answers
quickly, with more results than the caller was entitled to, and nothing 500s and
nothing goes red — the only tell is a customer seeing a competitor's record in
their picker. Measured before enforced,
ceiling zero, pinned at birth because the fence arrives with the app it fences.
Declared blind spots: a raw `httpx` call to the Meili URL, which imports neither
the client nor either setting (the closed grammar's other side — review's, and
the census's); **the Meilisearch server's own state**, which no check in this
tree can see, and whose answer is a design rather than a check — *the console is
a window, not a door*: index settings are code, and the declaration-digest
startup reconcile re-applies them whenever the digest moves, so a hand-edited
setting is overwritten at the next boot that notices; the credential reached
under a different variable name; any file outside `apps/` and `config/`; and
whether the injection is *correct*, which is a dedicated rung's criteria and its
adversarial probes rather than this check's.

34. *Reserved — assigned to
other rules by landing order (ADR gate-2 d,
confirmed at ratification).*
32. **The first path segment names a resource, never an app** (the owner's
ruling; ADR api-2). No mounted route's first path
segment is an installed app label. Both populations are closed and neither is a
hand-list: the labels come off the **app registry**, so an app added tomorrow is
in scope with no edit to the rule, and the paths come off the **live mount**, so
a `PREFIX` and a route path under an empty one are the same finding rather than
two. `/api/v1/core/organizations/` asked every caller to learn which module of
ours happens to hold a thing in order to type it and then ignore it — and the
leak has **no failure mode**, which is why five cycles of code review walked
past four groups of it: the prefixed route answers exactly as well as the
resource-first one, so nothing 500s, nothing goes red, and the cost lands on a
stranger reading the document months later. One valve, `allowed_label_paths`: a
label with the reason its app's name is also the right resource name, seeded
with `connections`, because A1 names an app as the plural of its aggregate and
the coincidence is the convention working rather than failing. Measured before
enforced, ceiling zero, pinned at birth
— the whole measured backlog paid in the rule's own commit, because the ruling's
trigger is a clock: after the first external consumer, moving a URL is a
versioning event. Declared blind spots: whether a resource *name* is good
(review's, and ADR api-2's three renames were judgement); cross-app
first-segment uniqueness (ninja refuses only exact duplicates); the
trailing-slash half, which is a test rather than a clause because its backlog
was closed in the same rung; plain Django views, which the ninja walk cannot
see; and prose that deep-links an old path, which the mount cannot see at all.
35. **Hot-path plan shapes** (ADR gate-2, P3 E1; measured by M1–M4, corrected
by F1a/F1d, fixed by F1b/F1c/F1f). Every probed entry of the declared
hot-path registry (`quality/rules.yaml` rule 35; counts in
`quality/budgets.yaml::hot_path_query_counts`) stays **index-served** at gate
scale: under `SET enable_seqscan = off`, against an ANALYZEd probe world, the
statements the real read issues — the paginator's page and COUNT separately —
keep their pinned plan shape and their harness-certified statement count.
Plan shapes, never plan text; an index name only where a fix's report
authorizes it. Declared blind spots: planner choice at scale (M1-C, M4
FINDING 1 — the measured instances), and queries not in the registry (the
registry is a closed list; `docs/product/scale-envelope.md` says how an entry
is added).
36. **Socket fan-out discipline, and a tenant that goes dark hangs up** (ADR
gate-2, P3 E1; M4 §8's enumeration; the second class from R4 F2). An org-scoped
**payload** is never pushed to a bare tenant group: every `group_send` under
`apps/` takes its group from `bridge.group_for`'s decision, or carries a
`KICK_TYPE` message — an instruction to hang up, never a payload — to
`user_group` (one person's sockets) or to `tenant_group` (every socket in a
tenant that has been suspended or closed). Exact-shape by design — the whole
subject is one decision point and three call sites. **The second class is the
status writer**: every `@service` assigning a non-`ACTIVE` `Tenant.Status` calls
`close_tenant_sockets_on_commit` in the same body, because a darkened tenant was
refused at the next **handshake** and nowhere else, so every socket already open
went on hearing for the life of the connection while the REST door answered 403
to the same credential — two doors, one question, two answers, and the handshake
refusal is exactly what made it invisible. Declared blind spots: a group name
laundered through a variable; a payload whose org-scoping the AST cannot see; a
status written by `.update()`, a variable, a `setattr` or a data migration (a
bulk suspension is the tests' road, not a shape); a kick registered in a callee
rather than in the service's own body; and whether the kick **arrives**, which is
`close_sockets`' own `robust=True` blind spot inherited whole.
37. **No scoped model orders the whole deployment by time** (ADR core-11).
`BaseModel` shipped `created_at db_index=True` behind
`ordering = ["-created_at"]`, so every model inherited an index over the whole
deployment's timeline while every supported read is tenant-scoped — a page
walked other tenants' entries and discarded them (102,300 foreign rows on one
page; 255,000 on `AuditEntry`). The composite now lives once, in
`TenantScopedModel`'s abstract `Meta`. Three edges over one discovered
population (every concrete `TenantScopedModel` under `apps/`): **coverage** — a
model whose effective default ordering leads on `created_at` carries an index
whose first two columns are `(tenant, created_at)`, which is what catches
Django's `Meta.indexes` shadowing hole (a concrete `indexes` list silently
drops the inherited one); **no blind index** — no leading-time-column
`Meta.Index` without a `condition` excluding tenant rows (the `AuditEntry`
platform-partial shape) or an exemption with its reason; **no blind field
index** — no scoped model's date field carries `db_index=True`, the original
spelling. Reads declarations, never plans: rule 35 and the perf harness own
whether the planner picks it. Declared blind spots: per-route `?ordering=`
columns (`WorkflowRun`'s `-started_at` door is the recorded observation),
expression indexes, indexes made outside Django, and cross-app
`%(class)s_recency` name collisions (loud at migrate, invisible before).
38. **The narrowing key is on the shape**:
**every Out schema of an OrgScopedModel declares `organization_id`**, derived
off the model registry — `OrgScopedModel` subclasses by the same transitive
walk rules 8 and 24 use, located to their app, paired with that app's
`schemas.py` by the naming convention (the stem is the model name or a
CamelCase-word-boundary suffix of it, so `PreferenceOut` reports
`ChannelPreference`). Rule 36 cannot reach this: it is an AST rule over push
call sites, there is one such site and it is generic, so a payload that never
carried the key looks exactly like an org-less one. The fan-out narrows on that
key and nothing else (`events.services._subject_organization` reads the
subject's own read shape), so an `Out` that omits it emits an event no branch
owns and `bridge.group_for` delivers it to every socket in the tenant. The
runtime half fails closed in the same breath: an `organization_id` that does
**not resolve inside the tenant** is refused rather than stamped NULL, so NULL
can only ever mean "the subject has no organization" — the one seam in the
hierarchy that used to fail open now fails closed like `for_tenant(None)` and
`visible_to(None)`. Declared blind spots: a payload built by hand rather than
from the schema; a schema that declares the field and a service that overwrites
it; `Out` classes outside `schemas.py`; and a model with no `Out` at all.

40. **A header is read by its declared name.** Every inbound header read — `request.headers`, `request.META`, and
the `scope["headers"]` walk the socket and MCP doors use — names a module-level
`HEADER`/`*_HEADER` constant, never a literal; the declarations are the
population, derived by the same walk. A second spelling is a fail-open no
compiler sees: `request.headers.get("X-Tenant", "")` beside a renamed
`TENANT_HEADER` reads nothing, `""` is a fine answer to `.strip().lower()`, and
the request is served as though the caller had named no tenant at all. Two
clauses ride with it. **A refusal's `header:` remedy names a header the server
actually reads** — the name after the colon is some declaration's value, and
every destination's kind is one the `Remedy` docstring enumerates, read from
there so a sixth kind is a one-file change (ADR core-5). And **`CORS_ALLOW_HEADERS` is a
census, not a copy**: every declaration an HTTP door reads is in it, lowercased,
because a header the API reads and a browser may not send is a door open on the
server and shut in the client — which is exactly how `X-Org` was unreachable
cross-origin for a stretch, with no error anywhere. Declared blind spots: a
name threaded through two functions; the sending side's header dicts; standard
HTTP vocabulary read off somebody else's response; and whether a remedy's label
is apt.

41. **The OpenAPI document is the contract, complete** (ADR api-1). Every route carries a **title**
and a description **derived from the same docstring its MCP twin renders** — the
**first line is the title**, a short noun or verb phrase with no Markdown, no
full stop and at most `title_max_length` characters (60); everything below it
and above a `---` line is the description, which opens with the sentence;
everything below the divider is the note to the next maintainer and never
reaches the wire — so one capability cannot be explained two ways, and a
navigation sidebar shows names rather than paragraphs. A hand-written
`summary=`/`description=` is a second copy and is refused. **No contract half
carries the mechanical tells of maintainer archaeology** — a queue-row
reference, an underscore-prefixed identifier, `@service`, `manage.py` — because
the reader above the divider is a stranger holding an API key. Every tag an
operation carries is **described and named** by its owning app's `TAGS`
declaration (`Tag(display, description)`), collected by discovery: the wire name
is a slug a client turns into a namespace, and the display name is what a person
reads. **An operation carries exactly one tag** — a renderer lists it under
every tag it has, so a second one is the same operation printed twice in the
navigation, and a nested router's tags accumulate downward, which is where the
second one usually comes from. Every route enumerates the refusal codes it can answer with, and every
enumerated code is one `core.exceptions` registers — the fact and the remedies
on the wire are the registry's own text, never written per route. Every
component schema carries an example, and a field may **declare** a realistic one
(`core.schemas.example`) instead of taking the synthesised shape-grade value;
the count of undeclared fields is a **ratchet** in `rules.yaml`, so the standing
backlog may shrink and never grow and a new field must declare. `X-Tenant`,
`X-Org`, `Idempotency-Key` and `Idempotent-Replayed` are documented on the
operations that read them, from the constants rule 40 already governs. **The
whole standard is derived and applied once** (`apps/core/api/docs.py`,
`config/api.py`), which is what made the ceiling zero at birth affordable: the
measurement it replaced found 51
of 51 summaries were prettified function names, 11 routes had no description at
all, no route documented a header or a refusal, no schema had an example, and
all 36 MCP twins described their capability in words of their own. Five cycles
of review had read every one of them. Declared blind spots: prose quality
(review's, and a field test's docs-as-the-only-guide drive, which is what found the
false bearer-token sentence on invitation-accept and two routes each claiming to
be the only credential-free one); a title's aptness, as against its shape;
the guides/reference split, which is one string with headings in it and a
judgement rather than a check; example quality on both sides — a synthesised
example is always shaped right and never informative, and a declared one is
counted and never judged, so a real customer's name in an example is review's to
catch; a `TAGS` entry left behind after its last route moved, which renders as
an empty heading (a test, not a rule — its canary cannot share the probe app's
`TAGS` with the display-name one); the refusal enumeration is a superset where
`@refuses(...)` has not narrowed it, because it is derived from the door's shape
and not from the services' raise sites; **whether a refusal a route PRINTS can
actually happen there** — the block is prose and nothing compares it to the
service's raise sites, which is exactly how "a duplicate slug answers `conflict`"
survived; and plain Django views are invisible to it.

42. **Every service is reachable through a door** (the owner's ruling of
2026-08-23 — "mechanisms without doors is a miss in the development standard";
P5 WA-1). Every `@service` — and rule 13 already makes every write one — is
called **by name** from a module the mounts discover: `api.py`, `mcp.py`,
`consumers.py`, `activities.py`, `receivers.py` or a management command. So what
counts as a door is not this rule's opinion; it is the same list `config/`
discovers. A service that deliberately has none carries `# door: <reason>` on its
definition, counted and printed like every other valve here. **Reachability is
direct on purpose**: a service reached only through another service is doorless,
because that is the finding — a `create_organization` called by a bootstrap
command still has nothing a person or an agent can call. The census before it was
enforced: 77 services, 50 reachable, **27
doorless** — 13 of them the whole tenancy and hierarchy foundation, reachable only
by somebody holding a Python shell. Ceilings are per app and pinned at that
measurement, and **nothing under `quality/` moves for one to shrink** — a rung
gives its app doors, the count falls in the tree, and the gate says a human may
commit the lower number. That is what lets six builders close the backlog in
parallel without touching one shared file. Declared blind spots: whether a
`# door:` reason is a good one (review's); whether the door is the RIGHT door for
the persona (the field test's); a door mounted an unconventional way; a name
collision in either direction — a door calling a different function of the same
name is a false pass, and a service invoked through `getattr` or a registry is a
false finding; and whether a door that exists authorizes correctly, which is rules
13 and 24's.

43. **There is one outbound signer, and the scheme census holds.** A module under `apps/` that computes an HMAC it
never compares, or writes an `X-Signature*` key into a header dict, is a second
signer and is refused — the declared signer (`apps/events/activities.py`) is the
one place every subscriber's verifier is written against, and two signers do not
disagree on the day the second lands but months later, about a prefix or an
encoding or a timestamp, inside somebody else's integration. The discriminator
between a signer and a verifier is `hmac.compare_digest` rather than a list of
module names, so a product's own inbound receiver is outside the rule the day it
is written. And a scheme is named at **all three of its sites or at none**: the
header the delivery writes, the header the reference receiver reads, and the
header the contract prose documents are one derived population, set-equal — so
the recorded `X-Signature` contraction is one green commit, while dropping a
scheme at two sites of three names the odd one out. The verifier module is
deliberately not one of the three (its bare-HMAC shape survives the contraction
because it also verifies inbound provider deliveries, whose schemes are theirs);
what it owes instead is the subset direction, and a versioned house seam parsing
a scheme no delivery sends is refused. Floors that survive the contraction:
exactly one signer, and never fewer than one scheme. Declared blind spots: a
signer laundered through a helper whose header name is a parameter (rule 40's
data-flow limit); inbound provider schemes; `scripts/`, which signs to drive the
doors from outside; whether the tolerance window is right; and a signer outside
`apps/`.

44. **The library internals we hold are declared, and still exist.**
A module under `apps/` or `config/` that rebinds a **private** attribute on an
object it did not define is holding a seam the library never published — the
shape both of `config/api.py`'s ninja wraps take — and every such name is in
`ninja_internals_we_hold` with the ninja class it belongs to and the reason,
written in the same commit that binds it. The second clause is the one that
earns the rule: every censused name is still defined on the **installed**
django-ninja, read off the package on disk by `find_spec` and AST rather than by
importing it, so an upstream rename is said by the gate before anything is
mounted instead of by a `RuntimeError` from the mount on the machine that ran the
server. The MCP SDK is held too and differently — `mcp_internals_we_hold` names
the public `MCPServer.call_tool` that the ceiling gate below (rule 45) rebinds and the
`Tool.run` whose dressing `TOOL_ERROR_SENTENCE` copies verbatim — neither of
which is a private binding the walk can derive, and both of which break on the
same upgrade. Declared blind spots: a shape change that keeps the name (the wire
tests' — `test_method_refusal.py`, `test_mcp_wall.py`); a wrap laundered through
`setattr`; test modules, deliberately outside the walk, because a rule that
censused them would make the only way to test a wrap be not to; a private read
and not bound; and the MCP half being declared rather than derived, with the
trigger to derive being the first MCP seam that IS a private binding.

45. **Every MCP dispatch surface is ceilinged.**
The machine door answers on three surfaces — `tools/call`, `resources/read`,
`prompts/get` — each with its own dispatch method, its own manager and its own
argument validation, and the token ceiling stands in front of exactly one of
them. Nothing is exposed by that today, because this product registers no
resources and no prompts, and **that is why the rule refuses nothing today**:
rule 30's refusal in the other direction is honoured, and a wall built for a door
nobody has is the same mistake as a retry clock nobody reads. What it refuses is
the **first** registration on a surface whose declared guard marker is called
nowhere — not the second, because the leak arrives with the first. The unguarded
shape is what this rule refuses: the transport validates a call's arguments before the body runs,
so a credential whose ceiling reaches nothing there is answered *about the
request* — the schema of a capability it may not reach — instead of refused. The
census is declared (which surfaces exist, which dispatch method and manager each
hangs off) and the population is derived (whether anything is registered); both
halves are held to the **installed** SDK, so a surface it no longer defines, or a
manager-shaped attribute the census has never heard of, is exit 2 rather than a
pass — a census that cannot see cannot pass. Declared blind spots: marker forgery
(a guard that returns immediately satisfies it — whether the wall *holds* is
`apps/core/tests/test_mcp_wall.py`'s and its resource/prompt twins'); a
registration laundered through `getattr`; a fourth dispatch path with no manager
behind it; and the client-facing surfaces (`sampling`, `elicitation`,
notifications), which are not doors into this product.

46. **Every door pair owes a parity test.** Rule 17
diffs two **registries** and proves a capability exists on both doors. It cannot
see the two doors *disagree* about one capability, and both times they did, the
finding came from a test of one shape and from nothing else: once, REST rendering
by field name while the MCP transport rendered `structuredContent` by alias, one
row and two wires — and once, one consumer, one person, one `X-Org`, two
credentials and two different sets of frames. In each case both registries were complete. So
the population is **derived from the doors that exist**: an app with a REST door
beside an `mcp.py` owes the `(rest, mcp)` pair; an app with a `consumers.py` owes
the `(session, bearer)` pair, because the socket door has no second registry to
diff and the credential is the axis the defect came in on. The answer is
**claimed**: a module-level `DOOR_PAIR = ("rest", "mcp")` in the owning app's
`tests/`, read by AST, and the census is the difference. A marker claiming a pair
the app does not own fires in its own class, ratcheted at zero — a claim is the
only half a person writes, and an honest backlog must never pay for a dishonest
one. Measured before enforced: 8 apps, **7
pairs owed, 2 answered**, and the five-app backlog is ratcheted **per app**, so
the sixth door pair to arrive anywhere is a violation from birth while the five
that predate the rule may shrink and never grow. Declared blind spots: the marker
proves existence, never strength — a hollow parity test passes, and that is
review's; **webhook-out is not in the population** (there is one signer, one body
and one scheme census, so what a subscriber receives is proved by an argument
about one path rather than by comparing two — rule 17's own `does_not_cover` says
the same, and the trigger to derive a pair is the first product rendering an
outbound delivery two ways); a pair answered in another app's tests; and pair
names validated against no vocabulary, so a typo reads as a claim.

47. **A declared refusal reaches the document.**
`config/api.py::_document_operation` turns a route's refusal codes into responses
through `CODE_STATUS.get(code)` guarded by `if status is not None` — and since ADR
core-23 that table is **derived from the refusal registry** (`CODE_STATUSES` in
`apps/core/exceptions.py`, published by `config/api.py`), so a code whose
registration declares no `status=` leaves the published document **without a word** — the route
still refuses that way on the wire, and the `x-refusal-codes` a generated client
switches on has no branch for it. The live instance is
`apps/accounts/api.py::create_token`, which declares `session_required`: real,
registered, and invisible. Nothing before this asked the question — rule 41 asks
whether every declared code is *registered*, and this one is. So for every bound
operation the gate compares the set the route declares with `@refuses(...)` (or
the set the shape derivation produces, plus the authenticated 401) against what
the document carries. A missing code **absent** from `CODE_STATUS` names the
`status=` to declare at the code's own `register_refusal` site (never a table
line — the append path is gone, ADR core-23) and the `if status is not None`
that drops it — the one path this rule
has proven. A missing code **present** in `CODE_STATUS` is reported as an
undiagnosed drop, in those words: a violation that says what it has not
established rather than one that names a cause it guessed. **Production
stays tolerant**: the document is built at import, and a mount that refused to
build it would take the whole API down — rule 44's own note records living
through exactly that — so the gate is the right time. Measured before enforced: 87 operations, 15 registered codes,
11 documented, one live drop, ratcheted at one and handed up because the fix is a
line in `config/api.py`. Declared blind spots: whether a route refuses the way it
says it does (rule 41's own clause on this is that instrument, and the two are
complements); the MCP door's rendering (rules 17 and 46); the wire itself, which
the envelope tests drive; a derived set being a superset by construction; and the
probe measuring the tree as installed, which is why `operations_checked` is a
floor rather than an assumption.

48. **One door to the object store** (ADR files-2; the fence left as
a test pin). The object store is reached through `apps/files/storage.py` and
nowhere else: no module under `apps/` outside it imports `boto3`/`botocore`,
names `AWS_STORAGE_BUCKET_NAME` / `AWS_S3_ENDPOINT_URL` / `AWS_S3_REGION_NAME` /
`AWS_S3_CUSTOM_DOMAIN` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`
(`config/settings/` excepted, where the environment is read), signs a URL
(`generate_presigned_url`, `generate_presigned_post`), reads an object's bytes
(`get_object`, `download_fileobj`, `download_file`), or imports
`django.core.files.storage`. Rule 27's shape a third time, and this argument is
the plainest of the three: **a bucket has no tenancy in it at all.**
`for_tenant` does not reach into a key space and neither does `visible_to`, so
the only things between one customer's document and another's are the key
grammar (`version_key` — primary keys and a version ordinal, never a renamable
slug or a user-supplied filename) and the belt that refuses a key outside the
caller's own prefix (`refuse_foreign_key`). Both live in that one module, and
both are true only while it is the only way to reach a bucket. **The leak has no
failure mode**: a second door answers, with the right bytes, for a key nobody
checked — nothing 500s, nothing goes red — and the tell is a customer fetching a
URL that hands them somebody else's invoice. Four clauses because there are four
ways in and only the first needs the SDK (the client; the bucket, address and
credential; signing; reading bytes) — and a **fifth door** the rule closes
because this tree walked through it: `STORAGES` points `default_storage` at the
same bucket the moment a bucket is named, which is how `apps/exports` wrote its
archives until XPr re-pointed it onto `files.services.store_bytes`. Measured
before enforced: 229 files, 1 seam, 1
allow-listed importer (`apps/core/health.py`, the readiness probe — `core`
cannot import `files`), zero violations, ceiling pinned at birth.
`apps/files/tests/test_storage_fence.py` stays as the app's own census pin and
covered exactly one of the four clauses; that is the gap this closes. Declared
blind spots: a raw HTTPS request to the bucket endpoint; the bucket's own policy
and ACLs, which no check in this tree can see (F5's `storage_audit` is the
partial answer); whether the key grammar is *correct*, which is the seam's tests
and F5's probe; the behavioural storage settings, deliberately outside the
population; writes, covered only transitively through the two import clauses;
tests, outside the walk by construction; and a client obtained legally and then
passed onward, caught at the call and not at the hand-off.

**Amended 2026-09-27 (P24 — proposed by the PM; SIGNED by the owner 2026-09-28, "im ok with all").** *Which
principle bends:* ADR files-2's "no read-the-bytes function on this module"
(`apps/files/storage.py` § HOW BYTES COME BACK OUT), whose stated purpose is
that bytes never travel through Django to a DOOR — a whole document through a
web worker's memory to serve a response. *Why the default is insufficient
now:* the import member (P24 § 2.B.7) validates and applies an uploaded CSV
inside a Temporal ACTIVITY, chunk by chunk, and hands bytes to nothing but its
own parser; the design says "streams the CSV" and the seam had no road for it,
so the rung stopped (the builder refused a `# rule-48:` valve and a presigned
fetch over raw HTTPS — both the second door the rule exists to stop).
*Decision:* the seam module gains ONE server-side stream — `iter_object(*,
tenant, key, chunk)`, `refuse_foreign_key` first, the same `get_object` walk
`sha256_of` already makes, the body closed in `finally` — callable from an
activity and never from a door; rule 48 is unchanged (the read stays inside
the one module); the docstring's paragraph says bytes may reach an activity's
parser and never a response. *Alternatives rejected:* a valve on a second
`get_object` in `apps/djb_imports` (a permission slip for the exact shape the rule
stops); `presign_get` + an HTTP client from the activity (the rule's declared
raw-HTTPS blind spot, worn on purpose); an upload road that bypasses the files
app (a second key grammar). *Risk:* a door that finds `iter_object` and
proxies — bounded by rule 48's population (`apps/*/api.py`, `mcp.py`,
`consumers.py` may not call it; the canary is a door calling it) — that canary
is the files owner's next rider. *Reversal:* delete the one function and the
paragraph; the import member then needs the presigned road and its own
amendment. trigger to revisit: a second server-side consumer of bytes (a
document renderer, a virus scan) — then the seam's stream is the pattern, not
the exception.

49. **The audit row names who and where, always** (ADR core-22; the row
was owed here since the rule landed and is written now — the gap itself is
the evidence for the numbered-list consistency check the queue carries).
Every `@service` in the audited population — every one whose signature
declares a keyword-only tenant — declares `actor: Actor` AND `tenant`, both
required and never defaulted, or its dotted name is on the enumerated-absence
list in `quality/rules.yaml` with its ADR core-22 absence number and ground —
or it is a sweep `core.schedules.daily_purge` reaches with the factory's
declared signature, absence 1 by construction and on no list (ADR core-22,
amended 2026-10-03).
A nullable annotation conforms; a default does not. An allow-list entry
naming no `@service` in the tree is a ghost and fires the list's own
consistency half.

50. **No credential written down in the browser tree** (rule 23's second
population, through the scope-kind seam — the first `kind: js` rule). No
module under `frontend/` binds a credential-shaped name (secret, token,
credential, password, api/private/signing/access key, client secret; `*hash`
excluded) to a quoted literal; the value arrives from the build environment
and the module names it, the way the settings modules already do. Reads
NAMES, never entropy — the declared trade a browser tree forces. On a tree
with no `frontend/` the rule skips, printed, and every floor derives to 0.

54. **The vocabulary is one shape** — one statement, five clauses, one census,
because they are one question asked at five layers: *is the word for a
capability decided in exactly one place?* **(a)** Every first-party concrete
model yields one authorization kind — `authz_kind`, `authz_kind_of`, or
`snake_case(ClassName)` — or opts out with a sentence beside it; four verbs per
kind are the derived keys, and a key an app DECLARES in `ACTION_PROSE` is
classified against them. A declared key that is a second spelling of a derived
one (`gadget.view`, `endpoint.update`), or that names no kind at all, is
non-conforming; the count is a ratchet that may shrink and never grow, and a
rename goes through the app's own `RENAMED_PERMISSIONS`, which keeps the old
word answering. **(b)** A declaration names declared things: a `roles.py` may
not declare the platform's `owner` or a reserved permission as a role, two apps
may not declare one role, and a `DEFAULT_ROLES` entry may not offer a capability
to a role nobody declares — `djb.W054` is the half that reads a deployment's
ROWS at `--deploy`, this is the half that reads the code where the gate can see
it. **(c)** No role by value: outside `apps/core/authz.py` and
`apps/core/models.py`, production code does not ask *what role is this* — not by
the enum, not by rank, not by comparing `.role` to a string. A role is data a
tenant owns, and a rank table is a second opinion about it that no tenant can
edit; a predicate that needs "how much authority" asks
`holds(actor, "<kind>.<verb>", at=…)`, which reads the same three layers the
role editor writes. Ratcheted per app; each sweep drives its own app to zero.
**(d)/(e)** Every public `get_`/`list_` selector whose return annotation names a
model with a kind calls `require(actor, "<that kind>.read", …)`. The classes are
hard since Phase R (PR5, 2026-09-17), because the read sweeps drove every one of
them to zero and "measured before enforced" had been satisfied by then;
`accounts.read` is the one class still ratcheted, at the number the gate prints,
until the sweep behind lane I pays it. Valves, each demanding a
sentence and each counted and printed: `# role-value:`, `# read-open:` (a
machine read with no person behind it), `# read-kind:` (it returns one kind and
is authorized under another). **This half never imports**: every derivation is
AST, because the self-test plants a `models.py`, a `policies.py` and a
`roles.py` into the tree and re-runs the check in the same process, and a cached
`django.setup()` could not see any of them — so the two underivable cases (a
kind claimed by two models, an opt-out with no sentence) are findings here where
`djb.E025` refuses to load at all. *Rejected: five separate rule ids* — one
statement, one census, and the ratchet lines are per clause already. *Rejected:
a hard census at birth* — measured before enforced, which is the blueprint's own
words. The Permify prior art is recorded beside the rule in `quality/rules.yaml`
and is not a dependency: AGPL-3.0 would be refused by rule 23's licence leg.

55. **A tenant-wide kind is asked at a node the caller resolved** (ADR core-4's
sibling). `require`/`allows` on a key whose kind carries no `organization` —
`tenant`, `role`, `grant`, `user`, `api_token`, `identity_branding`,
`sso_connection`, `sso_domain`, `sso_identity`, and the eleven more the
derivation finds — passes the root, an `Organization` parameter, or a row's
`.organization`, or carries `# hat-scoped: <reason>`, counted and printed.
Asked with no node, or with the row itself, `allows` falls back to the acting
hat, where a branch administrator holds `*` — which is how an administrator of
one branch came to administer the whole tenant's identity provider while every
layer read as green. The population is DERIVED by the same two functions rule
13 clause (i) and rule 24 already use, so a model that gains a node leaves this
population on the run it enters rule 24's. And rule 26's population now
includes every model that names its organization through a foreign key
(`Membership`), with reach asked BEFORE capability: a `require` on a parameter
above the `may_be_named` that clears it is this rule's finding, because a
capability answered before reachability is a capability answered about a row
the actor may never have been able to name. **And a READ of a tenant-wide kind asks at the ACTING HAT, under a dated valve,
until v2.2 homes the kind.** Sight is the hat's; configuration is the root's. A
tenant-wide kind is read where the caller is standing — so a member of one
branch holding `*.read` sees the tenant's shared rows — and is still WRITTEN at
a node the caller resolved, so an administrator of one branch reads the tenant's
configuration and cannot change it. That is what three other doors already did
(the socket narrows per hat, `search` asks at the hat, the admin changelist asks
with `obj=None`), and it is a STOPGAP: every such site carries a dated
`hat-scoped` valve, this rule counts it, and the rung that gives the model a
home deletes it (PR5.5, 2026-09-17; the successor is the universal-homing
proposal, 2026-09-17 — every record homed at a node). The rule's statement,
population and valve grammar are unchanged — a read declares itself, it is not
carved out. Declared blind spots: a node laundered through a local; a predicate
that measures the root inside itself; `holds(at=None)`; and the four `core`
read sites, which are a ratchet for the same reason and are swept when their
kinds are homed.

56. **One router for home-realm discovery** (ADR ident-10).
`SsoDomain.objects.for_domain(` is called from the two pre-auth selectors and
`.claim(` from `_apply_domains` and the verify door, and nowhere else; no module
outside those filters `SsoDomain` by `domain=` at all. A second router is a
second answer to a question that has one: two routers can disagree about whose
person an address is — one honouring `verified_at` and one not — and the person
is sent to one identity provider and provisioned into another tenant. Declared
blind spots: a read through a related manager (`connection.domains.filter(...)`)
and raw SQL; and whether the one router honours `verified_at`, which is
`test_domain_claims.py`'s and not a shape any check can see.

57. **One writer of the identity join** (ADR ident-13 — the join keyed
`(realm, subject)`). The join is keyed on the subject, not the address: an
`SsoIdentity` row with no connection, one per realm a person holds a subject
in, is written by `record_identity` and cleared by `unlink_zitadel_identity`,
both `@service` and both audited; `sociallogin.connect(` lives in the adapter,
after the writer has answered. Reads are out of the population by construction —
and pinned there by a negative, because a rule that fenced reads would be a rule
against using the rows it protects. A second writer is how a join between two
identity systems comes to disagree with itself, and the disagreement is an
account takeover with an extra step. Declared blind spot: a write that precedes
a refusal is a census (`test_refusals_write_nothing.py`), not a shape; so are
`setattr`, `bulk_create`, a join row built through another name than
`SsoIdentity`, and `SocialAccount.uid`, which is allauth's own column.

58. **Socket join discipline: nobody names their own group, and nobody mounts
an open socket** (R4 F1; ADR realtime-2's "nobody names their own group" made
enforceable). Every `group_add` under `apps/` takes its group from one of the
bridge's three derived builders — `tenant_group`, `org_group`, `user_group` —
directly or through a name the same scope bound to one; and every entry in a
module-level `websocket_urlpatterns` wraps its application in `token_auth(...)`
and names a consumer extending `TenantEventsConsumer`. The sentence was a
convention for ONE consumer and the review proved what that was worth: a planted
`consumers.py` in `apps/example/` doing `group_add(f"tenant.{query['tenant']}")` and
`accept()`, mounted bare, is discovered by `config/asgi.py` exactly as the real
one is, accepts with **no credential**, and hears that tenant's events — while
rule 36 read only the `group_send` (push) side and rule 46 was answered by one
`DOOR_PAIR` line in a test file, which its own `does_not_cover` says in capitals
proves existence and never strength. Two classes, because closing either alone
still leaves a door: `join` without `mount` is an anonymous subscriber to real
branches, `mount` without `join` is somebody else's tenant read with a valid
credential. Declared blind spots: a derived name laundered out of its scope (a
finding here, so the cost is friction and not a hole — the valve is where such a
site says why); a **late** join, which satisfies this rule completely and is
R4-F4's defect, closed by a population-derived test rather than by a shape; an
**overriding subclass**, which claims inheritance and not behaviour; and a
consumer mounted by any road other than `websocket_urlpatterns`, which this
template does not have.

59. **An org-scoped event carries its branch, and an org-less kind names none**
(R4 F4 and F5; ADR realtime-2a). `events.services._subject_organization` reads
only the payload's **top-level** `organization_id`; absent is NULL, and
`bridge.group_for` reads NULL as tenant-wide. Rule 38 keeps the key on an
org-scoped model's `Out` schema and **nothing certified that an emit site passed
one** — rule 36's own `does_not_cover` named the gap in as many words. The live
instance: `usage.threshold.crossed` sent a `ThresholdCrossingOut` whose top level
had no key while its nested `crossed_by` was an org-scoped `UsageEntryOut`, so a
rival administrator at branch B received a ledger row `GET /usage/` under hat B
never lists. So every `emit(name=<const>, payload=…)` whose noun resolves to an
`OrgScopedModel` kind passes a payload that provably carries the key — a dict
naming it, an expression mentioning a rule-38-certified `Out`, a name the scope
bound to either, or a module-local helper whose returns are one of those (which
is what thirteen honest sites on this tree really write). **The other end is the
`None` mapping**: a noun an app maps to `None` in `EVENT_KINDS` while the app
declares a model whose kind *is* that noun, because `consumers._may_read` answers
True for a `None` kind whatever branch the frame carries — a real row's event
declared org-less bypasses the read set for every connection in the tenant, and
the `ImproperlyConfigured` text `kind_of_event` raises offers exactly that road.
**The static rule ships with its runtime belt** (the two together, never one): 
`emit()` refuses an org-scoped kind with no key and refuses an org-less kind that
names a branch, and `push_event` drops an org-bearing frame on a `None` kind with
`realtime.frame.org_on_orgless_kind` at ERROR. Declared blind spots: a name this
walk cannot resolve (a parameter, an f-string, a table lookup — four such sites,
covered by the runtime belt and not by the scan); a payload assembled across
modules; the **value** rather than the key (a wrong branch is
`_subject_organization`'s refusal, not a shape); and a nested certified `Out`,
which is why the crossing is fixed by giving the **outer** schema the key.

**AMENDMENT — an undecided noun is the gate's refusal, not `emit()`'s. SIGNED by
the owner 2026-09-21.** *What it bends:*
`kind_of_event`'s "it refuses rather than defaulting", for the UNDECIDED case
only — a noun that is no authorization kind and that its app's `EVENT_KINDS`
does not decide. *Why the default was insufficient:* that refusal escaped
`emit()` into the **emitting service's transaction**, so a product that added an
event name and forgot one declaration line lost the **write** the event was
about and its doors answered 500 — availability spent on a missing declaration,
measured by the consumer on `apps/usage` (six `test_services.py` cases red, every
one a rolled-back recording). An undecided noun is a *missing declaration* — this
rule's own subject — and not a *proven disagreement*, and refusing it per emit
both rolls back the product's writes and duplicates a census the gate already
runs. *What changed:* the write **commits**, the `Event` row is written with the
noun undecided, the branch is stamped from the payload's top-level key exactly
as any other event's is, the dispatch is enqueued, and
`events.emit.kind_undecided` is logged at ERROR carrying the remedy. *What stays
closed:* the socket never delivers an undecided frame —
`consumers._may_read` catches the same `ImproperlyConfigured` per frame and
drops it (`realtime.frame.kind_undecided` at ERROR) — and **the two proven
refusals above are untouched**, because those are the two things
`kind_of_event` can prove. *Where the refusal went:* rule 59's third class,
`undecided_noun`, which refuses the tree once per undecided noun **at the
constant's own line and carrying the `EVENT_KINDS` line to paste** (`--explain
59`); its population is every UPPERCASE `<app>.<noun>.<past-verb>` constant in
an app's `events.py`, floored at `declared_names: 12` and pinned equal to the
runtime census by `apps/events/tests/test_emit_undecided.py`. *Rejected:* keeping
the raise and adding a draft command (the write still rolls back, and it is a
second walker); defaulting an undecided noun to `None` (that is F5's defect —
a `None` kind is delivered to every connection in the tenant); a management
command walking the emit sites (`quality.checks` reached from `apps/`, which
`apps/core/tests/test_roles_are_keys.py` rules against). trigger to revisit:
the first product that ships an undecided noun past a red gate — sockets silent
for it, `events.emit.kind_undecided` in the logs and nobody reading them.
*Reversible:* restore the raise in
`_refuse_a_branch_that_disagrees_with_the_name` and disable class 3; the two
proven refusals and every other behaviour are untouched by either direction.
*The fourth class (2026-10-02), `needless-kind-map`:* an `EVENT_KINDS` entry
whose noun is itself an authorization kind is never read — `kind_of_event` asks
the kinds first — so it is a dead decision that reads like a live one; counted,
recorded at the measured count and down-only, the line deleted by its app.

60. **A template-owned file carries no product edits** (ADR
platform-extension-1, and `build-contract.md` § Ownership is the per-path
table). Every template-owned path whose content is not the declared base's is a
divergence, and a divergence is legal exactly when the product's own
`architecture.md` names it — `divergence: <path> — <reason>`, one greppable
line each. **And every template folder that runs a list of things ships with
its `local/` drawer, discovered, never written, never shipped**: a product's
own leg, rule, fold step, drive or instrument row lands in the drawer beside
the template's list rather than inside it, absent is byte-identical behaviour,
and `publish.sh` § R0 refuses a tracked drawer path at exit 2 so a release can
never conflict with one. The check is `scripts/divergence_census.sh` against
the declared base — `DJB_TEMPLATE_BASE`, `scripts/local/template-base`, or the
`template` remote's `v$(TEMPLATE_VERSION)` tag, in that order — and **a tree
with no declared base is SKIPPED with a printed line**, which is the template's
own shape: it has no template. Declared blind spots: the DRAWERS THEMSELVES are
not read here — that a template list actually discovers its `local/` sibling is
each seam's own rung and its own canary, and this rule would be green over a
tree where not one of them did; the base is taken on trust (the census can tell
that the declared ref resolves, never that it is the release this product
merged); a rename reads as a deletion plus an addition; and a divergence inside
a product-owned file is invisible by construction, which is the partition
working rather than a hole.

61. **Every compose image is pinned by the digest of a multi-arch index**
(P23 B-RIDERS; the v2.2.1 hotfix's rider). Every `image:` in `compose.yaml`
and `deploy/compose.yaml` carries `@sha256:<64 hex>` from a registry on the
rule's own declared `allow_registries`, or a `# pin-exception: <reason>` on the
line or in the comment block directly above it; an interpolated reference can
only be valved, and its reason names what resolves it to a digest. A tag is a
pointer somebody else moves — the withdrawal of one broke every clone at once —
and a pin the rule cannot see is a pin nobody re-checks. Declared blind spots:
**whether a pinned digest is an index at all** is a registry question
(`docker buildx imagetools inspect`) a static scan cannot ask — the pinning
change transcribes the inspection per image and every re-pin owes the same
transcript (the re-pin road itself is a P23 design question, not this rule's);
a digest the publisher never published fails at pull, not here; only the two
stacks in the `compose` kind's roots are read (`deploy/observability/alerts/
compose.sink.yaml` is outside it, by declaration); a flow-style image mapping on
one line is unseen; a valve's reason is checked for length only.

62. **An exported credential reaches only the steps that asked for it**
(P23 B-RIDERS; the lead's § 2 (f) — `config/settings/test.py` is the one
authority for the store credential). In a GitHub Actions workflow, every `run:`
step after a credential exporter in the same job (a `uses:` step on the rule's
declared `exporters`) sets each of the rule's `exported_names` in its OWN `env:`
— an empty value is a pin — or carries `# creds: <reason>`. A role assumed for
one pull otherwise rides the job environment into every later step, including
the one that runs the suite. Declared blind spots: an exporter not on the list
(another cloud's login, a composite or reusable workflow, a `run:` step writing
`$GITHUB_ENV`) is not an exporter here — the list grows by a visible diff; a
`uses:` step after an exporter is not judged (the registry login after the role
is the deliberate case); names beyond the declared three are not required
pinned; job-level `env:` does not count because the exporter writes over it;
what a valve claims is taken on its word.

63. **A pattern entry names an instrument that exists, and no face is drawn
with no entry** (P23 B-FE-A + its +1F; the owner's front-end standards ruling of 2026-09-26). Every
entry in the pattern book — `docs/product/design/patterns.md` and a product's
`patterns.local.md` drawer beside it — is in the six-part form (Shape · Words ·
Placement · States · Ruling · Instrument, each opening with its bold label), and
its Instrument paragraph names in backticks at least one repository file that
exists; every row of the book's instrument index resolves; every motion-ledger
row is four fields with a `--motion-<name>` token. **A pattern whose instrument
does not exist cannot fail, so it is not a pattern yet.** And every module under
`frontend/src/screens/` and `frontend/src/components/` declares the section it
draws (`// patterns: §N`, two named forms) in its first twelve lines, naming a
section that is an entry — the scaffold's two screens are the first declarers.
Declared blind spots: **whether the instrument measures what the entry says** —
the check proves the file exists, never that it asserts the pattern (the mirror
pass's and the verifier's question, exactly as `instruments.md`'s census checks
a citation's shape and not its truth); whether every element class a product
draws has an entry is the engineering lead's DECOMPOSE refusal, not this rule's;
a path not in backticks, with no directory segment or no suffix, is not read as
an instrument; the scales (§ 26) and the mirror pass (§ 27) are headings, not
entries, so a face can never declare them. **A product's fold records its pattern-book
findings as ratchet classes, per ADR gate-6** (P24 FE-2): the rule declares
one class per finding class its runner emits — `book`, `entry-form`,
`instrument-unnamed`, `instrument-missing`, `ledger-row`, `face-undeclared`,
`face-section-missing` — each recorded `0` on the template, so a product
folding after the tag records what it finds under its drawer's `ratchets:` and
ratchets it down by territory exactly as rules 64–71 already do; a class the
runner emits that no key covers is the ratchet leg's own dead.

64. **Every size names a type role** (P23 B-FE-A; the generic front-end
instruments are house rules that red a product until it adopts the floor —
owner 2026-09-26). Every `font-size`, `letter-spacing` and `font` shorthand
under `frontend/src/`, in a stylesheet or an inline style literal, names a
`var(--type-…)` role; only the CSS-wide keywords and `letter-spacing: normal`
stand alone; no size, tracking or role is a half pixel. Declared blind spots:
**which role a seat spends** is the book's entry and review's question — any
role satisfies the rule; a value computed at run time (a variable, a ternary,
a `${…}` template) and a style object built by a helper or spread from another
file are not judged; a fallback inside the role passes on the role; CSS nesting
is read flat; `font-weight`, `line-height` and `font-family` are the type roles'
to carry, not this rule's; and **a `.css` finding cannot be valved** (rule 53's
declared seam gap — the remedy there is a role), which holds for 65–69 too.

65. **Every gap is on the spacing scale** (P23 B-FE-A). Every `gap`,
`row-gap`, `column-gap`, `padding` and `margin` — every side and logical twin
of the last two included — under `frontend/src/` is made only of steps: `0`,
`auto`, a CSS-wide keyword, or a `var(--space-…)` token, alone or inside
`calc()`/`min()`/`max()`/`clamp()` beside unitless numbers. Declared blind
spots: which step a seat spends (the book's); geometry that is not spacing —
`inset`, `top`, a width, a height, a border, a radius, `outline-offset`; values
computed at run time; CSS nesting read flat; and **whether the steps themselves
are a scale** — eleven arbitrary `--space-*` values pass this rule, and the
book's § 26 entry and review hold that.

66. **Every motion is on the ledger** (P23 B-FE-A). Every `transition`,
`animation` and their duration, delay and timing-function longhands under
`frontend/src/` names a `var(--motion-…)` token and carries no raw time or
easing outside it; and the `--motion-*` tokens declared under
`frontend/src/tokens/` equal, by name, the rows of every fenced `motion-ledger`
block in the book and the product's drawer — a token off the ledger and a
ledger row with no token are both findings. Declared blind spots: **what moves
and whether it should** — the ledger's rows are the rulings; motion from script
(the Web Animations API, a library, a `requestAnimationFrame` loop) is not a
declaration and is invisible; `@keyframes` bodies are not judged, the animation
naming them is; reduced motion is not checked here — the mirror pass's line 8
captures it rendered; a ledger row with no token is reported at the tokens
layer's first stylesheet.

67. **One focus ring, and the act floor** (P23 B-FE-A). Every pressable under
`frontend/src/` — an `a`, `button`, `summary` or pressable `[role]` a stylesheet
styles or a screen renders as a host element, and every class written on one,
given `cursor: pointer`, or put on one by a screen — has a `:focus-visible` rule
naming the ONE ring token, `var(--focus-ring)`; and every pressable class
consumes `var(--act-min)` in a rule of its own — the act floor's static half.
Declared blind spots: **the measured box** — a class consuming `--act-min` in a
`max-width`, or in a rule the cascade overrides, passes, and whether the target
really measures 44 × 44 at the phone width is a rendered fact (Tier C); which
ring on which ground (a second ring is named in the book and added in the
drawer); pressability from script — an `onClick` on a `div`, a `tabIndex`, a
host element decided at run time, a `className` built by a helper — is not
derived, and `:where(…)`/`:is(…)` are not unpacked, so a ring written only
through them is not credited.

68. **Nothing is disabled** (P23 B-FE-B; the book's § 4, the act vocabulary).
Nothing under `frontend/src/` disables a control: no `disabled` or
`aria-disabled` attribute on a JSX element, no `disabled` key in an object
literal or a props type, no `.disabled =` assignment, no
`setAttribute`/`toggleAttribute` of `disabled`, and no stylesheet selector
naming `:disabled`, `[disabled]` or `[aria-disabled]`. **An act the role may
not take is absent; an act at work says its verb's progressive and stays
pressable; an act that cannot run yet is answered by the server's refusal.**
Declared blind spots: a switch built at run time — a props object assembled by
a helper, a spread carrying `disabled`, an attribute name computed from a
variable; a third-party component that disables itself internally (the rule
reads this tree's source, not a package's); `readonly`/`readOnly` and `inert`
are not judged; JSX text holding an apostrophe can hide the rest of its line
from the shared scanner (its declared trade); whether the absent act, the
progressive and the refusal are actually drawn instead is the book's and the
mirror pass's.

69. **No toast, spinner or shimmer** (P23 B-FE-B; the book's § 17 — an outcome
is a band under the head; loading is still shapes at the content's heights).
In a script: no identifier whose words include `toast`, `toaster`, `snackbar`,
`spinner` or `shimmer` (nor `CircularProgress`, `ActivityIndicator`), no import
from a package that names one or from the named toast and loader libraries, and
no `className` literal from the class family; in a stylesheet: no class
selector and no `@keyframes` name whose words include those, `spin` or
`loader`. Declared blind spots: **the families are words** — a toast or a
spinner under a name carrying none of them (`Notice`, `Busy`, `Progress`, a
library's `Loading`, an `animate-pulse` utility) is not seen, and a name that
happens to carry one for another reason is a finding for the valve; motion from
script and an inline SVG spinner with no family word are invisible; a class
assembled by a helper or a `${…}` part is not read.

70. **One dialog primitive, and its foot carries no dismiss word** (P23
B-FE-B; the book's § 1, the sheet). Only `frontend/src/primitives/dialog.tsx`
draws a dialog — a `<dialog>` element, a `role` of `dialog` or `alertdialog`, a
`createElement("dialog")` anywhere else under `frontend/src/` is a second sheet;
and no dialog foot (the primitive's `foot={…}`, or a `<footer>` in a module that
draws a dialog) carries Close, Cancel, Done or Dismiss in JSX text, a string
literal or a copy key — the sheet's one dismiss is in its head. The primitive
exists and draws a `<dialog>`. Declared blind spots: a dialog from a library
under a component name (`<Modal>`, `<Sheet>`, `<Popover>`) whose host element
is decided inside the package — a product that adopts one names it in the book
and adds the rule in its drawer; a foot spelled another way (acts handed in
through `children`, a `<div>` styled as a foot, a foot built by a helper); a
dismiss word reached through a reference whose key is not named for it
(`COPY.leave` holding "Cancel"); whether the head really carries exactly one
dismiss is the primitive's own test.

71. **The route table names every page** (P23 B-FE-B; the book's § 0).
`frontend/src/kit/routes.ts` carries exactly one row for every route a
`page.*` file under `frontend/src/app/` draws (route groups `(…)`, parallel
slots `@…` and intercepting segments dropped; dynamic segments kept verbatim),
no row for a route no page draws, and every row carries `path`, `job`,
`primarySeat` and `operation` — `null` is an answer, an absent column is not.
Declared blind spots: **whether the operation is real** — the column is read
for its presence, not checked against the served document (the surface that
follows it owns that census); whether the job is true and the seat is where the
act really sits is the book's § 0 entry and the mirror pass's line 1; routes not
drawn by a page (a `route.ts` handler, a rewrite, a redirect, a `pages/`
directory, a `default.*` slot) are outside the population; a row built at run
time is not read — a row is an object literal with a quoted `path:` in the
table file.

72. **Every label is a lexicon row** (P23 B-FE-B; the book's § 21, words on a
surface). `frontend/src/copy/lexicon.ts` declares one `LEXICON` array of
strings with no row twice; and every label a module under `frontend/src/copy/`
writes — a string literal valued under a key named `label`, `act`, `title`,
`heading` or `dismiss`, or a camel-cased key ending in `Label`, `Act`, `Title`
or `Heading` — equals a lexicon row verbatim. Declared blind spots: a label
under another key (`hatAsked`, a column heading named for its column) is
outside the key grammar — a product that wants a key read names it with a
label suffix; a label reached through a reference or composed at run time; a
string inline in a face is outside `frontend/src/copy/` and is
fe-conventions § 5's; **one word per thing is held only as far as the lexicon
goes** — *Remove* beside *Delete* both pass, and the lexicon's own review is
design's; a row nothing spends is not a finding.

73. **No machine token in copy** (P23 B-FE-B). No string literal value in a
module under `frontend/src/copy/` — the lexicon included — carries a machine
token: a snake token (letters and digits joined by `_`), a hex id (thirty-two
hex digits, or a UUID), or a kebab key (a lower-case run of three or more parts
joined by `-` with no small joining word, or ending in a machine suffix — `-id`,
`-uuid`, `-key`, `-slug`, `-url`, `-uri`, `-code`, `-ref`, `-pk` — or a url-name
action — `-list`, `-detail`, `-create`, `-update`, `-delete`). A literal in a
key position and a module specifier are machine words by position and are not
read. Declared blind spots: a two-part kebab key with no machine suffix
(`due-date`) reads as an English compound; camel-cased identifiers
(`invoiceId`) are not tokens here, since a proper name (`iPhone`) has the same
shape; a ternary's first branch is read as a key and skipped; **a token the
server sends** — a refusal's code, a remedy's destination — is rendered
verbatim by design and is the refusal notice's (§ 15), not a copy string;
strings outside `frontend/src/copy/` are fe-conventions § 5's.

74. **A noun that declares a family marker carries the whole road the marker
demands** (P24 B-CORE-1; ADR verbs-1, the family's seam; `apps.core.verbs.ROADS`
is the table). An archivable noun carries a `<noun>-archive` and a
`<noun>-restore` route (each paired on the machine door by rule 17's derivation
from the same url_name), both keys `<noun>.archive` and `<noun>.restore` in the
vocabulary — derived, never typed — every route answering the noun itself (its
detail, its archive, its restore) answering an `Out` that subclasses
`ArchivedOut`, and its list taking `?show=`. Read off the live model registry
and the live ninja mount; nothing is listed. It reports only through the django
system-check leg (`manage.py check --tag djb`), so no comment suppresses it: a
noun that should not carry a road does not declare its marker, and a road the
table demands wrongly is an edit to `apps/core/verbs.py` a reviewer reads. The
family's later markers (`Versioned`, `Movable`, bulk, history) add their roads
to the same table as they land. Declared blind spots: **whether the road
works** — the routes exist, answer the shape and take the parameter; that an
archive hides the row, a restore puts it back and a blocked archive names its
blocker is each adopting noun's own tests (and the golden-copy drive's copied
test); a noun that should adopt a marker and never declares it (the
declaration IS the population); the list route's name (`?show=` is demanded of
`<noun>-list` or its plural; a list mounted under any other url_name is not
seen); a route named right that does the wrong thing (review's); the MCP twin
is rule 17's question, and an app rule 17 exempts is exempt here too.

75. **No model is both append-only and Archivable** (P24 B-CORE-1; ADR
archive-1 — the consumer's `Archivable` adopted verbatim where it could be; the
django-architect skill's D8). A class under `apps/` whose body declares
`append_only = True`, or which names an append-only class as a base, never
also names `Archivable` (or an archivable class) as a base or declares
`archivable = True`; both populations are derived from the tree by class name
to a fixed point. A ledger row is never hidden and never restored — the two
mixins answer different questions about a row's life, and a class carrying both
would let `for_tenant` hide what rule 20 says can never change. The static rule
ships with its runtime belt: `Archivable.__init_subclass__` refuses the pair
and the wrong base order the moment the module is imported. Declared blind
spots: a declaration the AST cannot see (a class built by `type(...)`, a base
bound to another name, an attribute set after the class body — the belt covers
the first two at import, nothing covers a setattr); name resolution is by class
name, not by import, so two modules defining one name are read as their union
(the loud direction; a `# rule-75:` valve is the answer); a model that is a
ledger in spirit and never declares `append_only`; whether a noun should be
archivable at all (the adopting app's decision); files outside `apps/`.

76. **A write to a Versioned model moves `updated_at`** (P24 B-CORE-2; ADR
verbs-1 — the version is derived from `updated_at` in integer microseconds, no
column, no migration, and `require_version` refuses `stale_version` (409, the
remedy `self:reread`, `current_version` in the extra) by comparing the stamp).
Under `apps/` (tests and migrations aside) a `save(update_fields=[...])` on a
name holding a row of a `Versioned` class lists `"updated_at"` in its literal
field list, a queryset `.update(...)` rooted at a `Versioned` class passes
`updated_at=`, and a `.bulk_update(...)` on one lists `"updated_at"`; the
population is derived by class name to a fixed point (rule 75's resolver),
nothing is listed. A write that skips the stamp leaves the version where it
was, so the next reader's `version` is a lie and the save that lost the race
cannot be refused. Valve `# rule-76: <reason>` on the line or the comment block
above it. Declared blind spots: **a field list the AST cannot read** — a
variable, a list built at run time, a `**kwargs` spread into `.update()` — is
never accused (the quiet direction; a service writes a literal); a row held
where the binding is illegible (a dict value, a comprehension target, `self`
inside the model's own methods); a raw SQL `UPDATE`; a clock that steps
backwards between two locked writes (the version is the stamp, and the stamp
is the clock's); name resolution is by class name, as rule 75's; files outside
`apps/`, and every test and migration, are not read.

77. **A noun face's road equals its wire** (P24 FE-2, widened to import and
attach by FE-3; ADR verbs-1; the design's instrument split — the face's Tier A
rules read source text, the fe leg's census reads the rendered face). Every
noun face — a directory under `frontend/src/screens/` — that draws a noun whose
wire (`frontend/openapi.json`) serves a family verb door declares its road
once, in `road.ts`, and the road's verbs equal the noun's verb doors both ways:
no road verb without its door (an act the server would not answer) and no door
the road does not declare (a verb the face forgot). The doors are the
operations whose operationId names the verb and the noun — archive, restore,
move, duplicate and merge (POST), update (PATCH, the versioned Edit), the
history list (GET); import, where the imports app's stage operation takes the
noun as a `kind`; attach, where the noun's own detail answers `tags` — and the
road's `bulk:` list equals the bulk door's discriminator, both ways. A wire
noun with no face is counted and is not red: a capability on REST need not be
on a screen. Runner `quality/runners/js_verb_road.py`; valve `# rule-77:`.
**Its ratchet classes are `wire-missing`, `road-missing`, `road-without-door`
and `door-without-road`, each `0` on the template, and `door-without-road` is
how the face follows the wire by one wave without a valve on the road:** when
the worked noun gains a door before its face is drawn, the example's fold
records the count in `quality/rules.yaml` with the reason and the client
regenerated (the rule reads the committed `frontend/openapi.json`, so a trial
merge measures `0` where the train's fold measures the truth), and the face
rung that draws the verb lowers it to `0` — the worked example recorded `2`
for duplicate and merge and the face that drew them returned it to `0`.
Declared blind spots: **attach without tags** — a noun that takes notes or
files and no tags answers nothing on its detail that says so, and its attach
door is not seen (a road declaring attach for it reds as road-without-door,
the loud direction, and a valve names it); which attach owners a face draws is
not compared, only that the noun takes attachments; an importer whose `kind` is
not the noun's operationId noun is read under its kind; a door named otherwise
(a rename route standing for update, as organizations' does); whether the face
draws what the road says is the face census's — a road is taken at its word;
a road built at run time; an irregular plural read wrong by the bulk noun's
singularising.

78. **A family act is constructed from the verb table and never spelled**
(P24 FE-2; the design's grammar — five seats, one ordered verb table, an act
drawn iff the verb is in the row's `allowed_acts`, absent never disabled).
Under `frontend/src/`: (a) no string-literal `data-act="<verb>"` outside
`frontend/src/kit/verbs.ts`; (b) no permission key `"<noun>.<verb>"` — an
object-less ask — outside the generated client; (c) no one-press verb (one the
same face undoes in one press, whose table row opens no sheet) inside the
dialog primitive as its word, and merge's foot act asked for only in a module
that draws the dialog primitive; (d) no `order:` or `*-reverse` direction in a
stylesheet rule whose selector names `[data-seat`; (e) every width media query
(and `matchMedia` string) is in range syntax, `(width <op> <length>)` with
`<op>` one of `<=`, `<`, `>=`, `>` and the length in rem, px or em (the book's
pair `(width <= 40rem)` / `(width > 40rem)` is the recommended form), naming
the book's one breakpoint or one of the values a product's drawer records in a
fenced `breakpoints` block, one per line, each with its reason — a legacy
`min-`/`max-` query is refused for its FORM and an undeclared width for its
VALUE. Runner
`quality/runners/js_verb_acts.py`; ratchet classes `hand-act`,
`objectless-ask`, `leaving-in-dialog`, `merge-outside-confirm`,
`seat-reordered`, `breakpoint`, each `0`; valve `# rule-78:`, and a finding in
a `.css` file cannot be valved (rule 53's declared seam gap) — the remedy there
is the range query or an unreordered seat. Declared blind spots: **layout is
Tier C** — clause (d) reads a selector that names `[data-seat`; a class on the
seat's element that reorders it, a `grid` placement, an absolute position and
the 44 px box are the rendered drive's; a pill that splits is a rendered fact
no static read sees; an act built at run time (a `data-act` from a variable, a
key composed from parts); clause (c) reads the element between `<Dialog` and
its closing tag in one module, so a one-press act a component from another
module draws inside the dialog is not seen, and a dialog drawn under another
name is rule 70's; a width condition inside a container query, and a
`min-`/`max-` query in a `.css` string built at run time.

79. **One word per verb** (P24 FE-2; ADR verbs-1 — a product renames a verb
once, product-wide, in its lexicon, and never per noun). For every noun whose
wire carries a family verb, the noun's copy module
(`frontend/src/copy/**/<noun>.ts`, the noun in kebab case) spells no other
word for that verb: archive's *Delete · Remove · Trash · Retire · Deactivate ·
Discard · Hide · Unarchive · Recover*, move's *Transfer · Reassign · Relocate*
and merge's *Combine · Dedupe · Consolidate* anywhere in it; duplicate's *Copy
· Clone*, update's *Modify · Update* and history's *Activity · Log · Audit ·
Timeline* as a label or a title. Every word the code's verb table spends — the
product's word for each verb and each verb's way back — and every phrase the
drawer declares in a fenced `verb-words` block is lifted out of a string before
its words are read. Runner `quality/runners/js_verb_words.py`; ratchet class
`synonym`; valve `# rule-79:`. Declared blind spots: a word composed at run
time (a template literal, a string a helper builds) and a word the server
sends (a refusal's sentence, a history row's) are the backend's and rule 73's;
copy outside the noun's module — the lexicon, a shared module, a screen's
inline string — is not a noun's copy and is not read here (rule 72 holds
labels to the lexicon); a noun whose copy module is named otherwise than its
wire noun; a synonym in another language or inflected (*Deleting*); the lists
are the design grammar's, per verb, and grow by visible diff.

80. **The verb table equals the book's** (P24 FE-2; the pattern book § 4's
fenced `verb-table` block is the one declaration). `frontend/src/kit/verbs.ts`'s
`VERB_TABLE` equals the pattern book's verb table (the fenced `verb-table`
block in `docs/product/design/patterns.md`, or a product's whole table in its
drawer's block, which then stands for the book's) row for row: the same verbs
in the same order, and per verb the same place in `record-acts`, the same press
(one · confirm · preview · none), the same weight, and the same presence of
each of the five forms — pressed, busy, state, refused, way back. A ruling
stays a token. Runner `quality/runners/js_verb_table.py`; ratchet classes
`table-missing`, `table-row`, `table-order`, `table-cell`; valve `# rule-80:`.
Declared blind spots: **the words** — the two tables' words are not compared
(a product's word is one lexicon line, rule 72, and a verb's synonyms are rule
79's), only the forms' presence; a row built at run time (spread from another
array) — a row is an object literal in `VERB_TABLE` whose first key is `verb`;
the places a verb may be drawn and its foot word are not in the book's table
and are the face census's; a book row with the wrong number of cells is not
read, and so reads as a missing row.

81. **An archivable noun's archived rows are reached only through its
widenings** (P24 B-CORE-3; ADR archive-1; born from the shape the two
hand-built adopters carried into the family — a hand filter chained after
`for_tenant` answered `[]` with no error once the manager hid archived rows
first, and nothing held it closed). Under `apps/` (tests, migrations and
`apps/core/models.py` — where the widenings themselves live — aside), a
`.filter(...)` or `.exclude(...)` whose keyword names `archived_at` (or an
`archived_at__` lookup), on a queryset rooted at an archivable class, is
refused naming `.archived_only()` and `.including_archived()`; the class is
resolved by name to a fixed point, nothing is listed. Valve `# rule-81:`.
Declared blind spots: a lookup the AST cannot read — a `Q(...)` object, a
`**{...}` spread, a filter built in a helper that is not a queryset-returning
function in the same module; a raw SQL `WHERE archived_at`; a queryset held
where the binding is illegible (rule 76's reading); name resolution by class
name, as rules 75 and 76 read it; a class carrying an `archived_at` column
without declaring `Archivable` is rule 74's bare-column clause, not this
rule's.

82. **A write on an archivable row calls `require_live`** (P24 B-CORE-3; ADR
archive-1 — every write on an archived row other than restore refuses
`archived` with the restore door, and the trap the worked example's first
verification named was the writes a product already had, which no golden copy
reaches). A `@service` in `apps/*/services.py` named for a keyword parameter
annotated by an archivable class — `<verb>_<param>(*, <param>: Noun)`, a write
on that row — calls `require_live(...)` in its body, unless it is the noun's
`archive_<noun>`/`restore_<noun>` pair; the class is resolved by name to a
fixed point (rule 76's resolver). Ratchet class `unguarded_write`: **born at
`2`** for the comms consent verbs, which write the consent ledger and never
the contact, **and lowered to `0` the same day** by the valve that carries
that sentence on each (`# rule-82: writes the consent ledger, never the
contact`). Valve `# rule-82:`. Declared blind spots: a service that takes the
id and reads the row itself — the annotation is the population; a write
through a helper the service calls (the loud direction — a service that calls
`require_live` in the helper is accused, and the valve names the helper); a
service named for something else that writes the row it takes as a reference
(`send(*, recipient)` is read as writing a message, which it does — the name
is the claim); **the population is narrowed on purpose** — the literal reading
(any `@service` taking a keyword parameter annotated by an archivable class)
measured nine on the tree that added the rule, seven of them services that
take the row as a reference and write another row, so the recorded mechanism
is the service named for the row it takes, which measured the two the ratchet
was set on; a write from a service named otherwise is review's; whether
`require_live` is called before the write, or on the right row, is review's;
name resolution by class name.

83. **One app per path, one app per family: no path and no tag key is served
by two apps** (2026-09-29; ADR mounts-1; born from a measurement — django-ninja
1.6.3 refuses nothing on a duplicate: two modules binding one path answer on
the wire with the one discovered first while the published document describes
the other, and a tag carried by two apps is one scope family, one token
ceiling reaching both — and from the class a product meets the day it folds a
release whose platform app mounts where its own noun already does). A Django
system check, `djb.E083`: every mounted path pattern (parameter names erased,
since `/x/{a}/` and `/x/{b}/` are one Django pattern) is bound by one api
module, and every tag key is declared (`TAGS`) or carried (an operation's
tags) by one app — both populations off the live mount and the tag discovery
the scope census reads, never a hand list — and two clauses more, for the two
names the key does not hold (2026-09-30): no display title is carried by the
tag keys of two apps, and no schema class name is defined by two modules (the
classes off every bound operation's request and response models — two classes
of one name leave the document one component, describing the other app's
routes). It reads paths and never prefixes:
seven routers share the root prefix and answer side by side. No valve — one of
the two takes a word of its own, and the finding names both. Declared blind
spots: a literal segment shadowed by another router's parameter segment
(`/x/links/` beside `/x/{id}/` — patterns are compared as strings, not as
match sets); two routes in one module on one path; plain Django views; a
router bound outside discovery; which of the two answers on the wire; and two
apps not yet installed together — before a merge, the fold's collision census
reads the mounts and tags as text, and after it this check reads the
assembled tree.

84. **One road per job: a job named by a marker is named by one marker, and a
copied shape is a counted class** (2026-09-29; ADR roads-1). An AST-and-text
rule in `quality/checks/` (`check: road_uniqueness`), scope kinds `py` and
`sh` and `js`, no Django id: every `@road("<job>", …)` / `ROAD = road(…)` in
importable Python, every `# road: <job> — …` line in shell and every `// road:
<job> — …` line above an exported TypeScript definition under `frontend/src/`
is a marker; two markers
naming one job on one tree are refused, the finding naming both and the remedy
the first — unless exactly one carries the rule's valve `<comment> rule-84:
<reason>` on the line above it (the product's declared second road, counted in
the standing section and printed by `manage.py roads` as `kept`). The same
check counts the unregistered copies by FORM as ratchet classes
(`private_twin`, `exit2_helper`, `discovery_loop`, `reason_literal`,
`hand_url`), recorded at the measured count and down-only (ADR gate-6);
`exit2_helper` is held at the tag with its trigger — `declared: G8, 2.6` (the
owner's deferral, v2-5-0-yardstick, 2026-10-01). Declared blind spots: a job
nobody marked; a road assembled at runtime; a helper that is neither marked nor
one of the counted shapes; two jobs spelled two ways; a marker on an object
that does not do the job; a TypeScript road that is not an exported function,
const or class; a road under a root the walk does not name.
**The shell libraries that stay are G8's (deferred to v2.6 by the owner).** A
wrapper library dies only when `python -m quality.djb.scope consumers <lib>`
prints `code=0`; the seven with code consumers left stay, their surviving
bodies counted by name in GF-9a's report (the build's archive of record, R8):
`gate_ledger.sh` 140 · `gate_refuse.sh` 19 · `gate_lease.sh` 19 ·
`docs_legs.sh` 12 · `archaeology_lib.sh` 9 · `fe_gate.sh` 8 ·
`secrets_scan.sh` 4; `bash_only.sh` (the interpreter guard, no bodies) and
`scripts/tests/drive_preamble.sh` with its drive (the drive drawer's product
drives source it) stay beside them. Trigger to revisit: G8, v2.6.

85. **Every surface declaration is a closed question over the tree — its families declared tags, its roles declared keys (each on one declared surface), its acts verbs of the permission vocabulary or family roads, its screens route-table rows — and every host in `SURFACE_HOSTS` names a declared surface; a door on a host that does not expose it answers `surface_does_not_expose`; every absolute URL the system builds goes through `core.surfaces.absolute_url` with the surface of the role it is for; an undeclared product is one total staff surface** (`djb.E085`, `apps/core/checks.py::check_surfaces`; the flat-baseline pin holds the undeclared shape byte-identical; rule 84's `hand_url` class counts the bypasses).

86. **A door composes no refusal body of its own** (2026-10-02; the refusal
grammar of `core.exceptions`, one composer at both doors). An AST rule in
`quality/checks/` (`check: doors_compose_no_body`): no `HttpError(` and no
`JsonResponse(` call in an `apps/<x>/api.py` or a module of an `apps/<x>/api/`
package, and no `ToolError(` handed a literal sentence in an `apps/<x>/mcp.py`
— a door raises the registered class and `wire_refusal` writes the one body
both doors send. Why: a hand-composed refusal is a second grammar with no code
to branch on, no remedy and a sentence only one door says. The valve is the
generic `# rule-86: <reason>`. Counted per app as `<app>.door-literal`,
recorded at the measured count and down-only. Declared blind spots: a body
composed through a helper defined in another module; a `ToolError` handed a
variable; a refusal returned as another response class.

87. **An event's payload goes through the helper** (2026-10-02; house rule 59's
sibling). An AST rule (`check: event_payloads_through_the_helper`): every
`emit(..., payload=...)` in an `apps/<x>/services.py` passes
`core.schemas.event_payload(...)` — directly, through a same-module function
whose every return is that call, or through a name the enclosing function binds
only to those. Why: the helper is the one place that drops the per-viewer
fields at any depth; a hand `model_dump`, an `exclude=` or a dict literal is a
payload nobody keeps equal to the wire. The valve is `# payload: <reason>`, for
an event with no `Out` to carry. Counted per app as `<app>.hand-payload`,
recorded at the measured count and down-only. Declared blind spots: one hop
and no further (a helper in another module reads as a hand payload — the loud
direction); an emit outside `services.py`; an emit routed through `core.bridge`;
whether the `Out` is the route's.

88. **One discovery walk** (2026-10-02; ADR roads-1's `discover` road). An AST
rule (`check: one_discovery_walk`): no production module under `apps/` or
`config/` calls `importlib.util.find_spec(` or `import_module(f"apps.…")`
outside the discovery road (`apps/core/discovery.py`) and the two readers the
rule's `scope.allow` names with their reasons (the settings' static derivation
of `INSTALLED_APPS`; the scaffolder's question about a label not yet
installed). Why: every reader of "which installed app ships this module" must
agree which apps are installed and what a missing module means. The valve is
the generic `# rule-88: <reason>`. Counted per app as `<app>.own-walk`,
recorded at the measured count and down-only. Declared blind spots: a walk
spelled another way (`pkgutil`, `__import__`, a path glob); tests and the
conftest, which walk on purpose.

89. **No plan coordinate in the code** (2026-10-02). A text rule
(`check: no_plan_coordinates`, kinds `py`, `sh`, `js`): no line under `apps/`,
`quality/`, `scripts/` or `frontend/src/` carries a word of the plans' id
families — a queue row, a defects or roads rung, a survey item or surfaces
rung, a surfaces section, a cycle, a wave's rung, a face rung, a batch rung, a
hygiene item, a race finding, a verifier's finding, a review's high finding —
read as a whole word, never as a variable, a path segment, a shell
declaration, a linter's `noqa:` code or on a `does-not-cover:` line. Why: a coordinate names a document the code does not ship with,
and goes stale the day the plan is archived; a comment says why, never who
asked. The grammar's own readers (the queue instruments, the dated-trigger
census) are exemptions with their reasons; the valve is `<comment>
coordinate: <reason>` for a line whose id is its subject. Counted per owner as
`<owner>.coordinate`, recorded at the measured count and down to zero by the
tag. Declared blind spots: an id outside the families (a cycle-local tag, a
review prefix, a measurement id); a coordinate split across lines; anything
outside the four roots.

90. **The loop key's excluded paths are derived** (2026-10-02; design (B),
condition 2). A text rule (`check: loop_key_exclusions_are_derived`): the
paths the `--loop` verdict's key leaves out — the prose no leg reads — are
computed by `quality/loop_key.py::prose_paths` from what the legs' modules
QUOTE, over the docs-only decider's own candidate list and its `names, never
reads:` grammar (both read from `scripts/gate_ledger.sh`, never retyped);
nothing in `scripts/**` or `quality/**` may type such a list under a name
carrying PROSE, LOOP_KEY or KEY_EXCLU, and a `names, never reads:` line must
name a path its module quotes. A quote is also left out of the reads when its
module — a file directly under `scripts/` that a `static` leg runs as `<module>
--check` — declares the path `measured at the commit:`. The pre-commit hook's
docs-only admission derives those modules from this census and runs each on the
staged bytes; the leg stays in `--fast`. A declaration that names a path its
module does not quote, or sits in a module no `static` leg runs, is a finding
(signed 2026-10-04). Why: a verdict reused across a prose-only
commit is the reuse the ledger exists for, and a typed exclusion is the one
way a stale verdict could be honoured after a leg quietly started reading a
file. The false direction is a wasted re-measure, never a false hit — except
for a path declared `measured at the commit:`, where a commit that skipped the
hook can be reused across until the next `--fast` (the post-merge hook, the
merge's gate, the bank's `static` readers, the PR's run); the stale claim is
bounded to that one leg's verdict. Declared
blind spots: a path a leg reaches by computation, glob or directory walk; a
typed list under another name or built at run time; a `derived-tree-paths`
declaration — the belt for those is main's own loop and the train.

91. **A comment is the contract line** (the owner's comment doctrine). An AST
rule (`check: comment_doctrine`): a docstring or a `#` block is one line; a
further line is an invariant the code cannot express or a why-not, one each;
a decision is cited by id, and a citation-only line, a single `why-not` line,
a `does-not-cover:` line and a marker comment are free. Counted per member in four classes —
`docstring-tail`, `module-tail`, `block-tail`, `narrative` (the rule's phrase
list) — over every app, the modules directly under `apps/`, `config/`,
`quality/`, `scripts/`, `deploy/` and `pilecap/`; recorded at the measured count and
down-only. **The per-member floors of rules 86–89 and 91 live with the
member** (ADR gate-6's classes): an app's in its `AppConfig.ratchet_floors`
keyed `<rule>.<class>`, read statically by the engine; the platform's other
members' in `quality/ratchet_floors.yaml`; a template app with no declaration
is exit 2, and `rules.yaml` keeps the rule and its classes, never a member's
number. Why: fourteen lanes lowering adjacent rows of one shared block is a
conflict per merge; a number in the member's own file is edited by the one
lane that owns it. Declared blind spots: the published route description
(rule 41) is counted past its summary line; an invariant in prose is counted
as a tail; narration the phrase list does not spell; the one free why-not is
read per line, so two in one docstring are both free.

92. **Every on-commit registration is a declared seam**. An AST rule (`check:
on_commit_seams`): every `transaction.on_commit(` call — and the bare
`on_commit(` a module imports from `django.db.transaction` — in a production
module under `apps/` sits inside a function carrying rule 84's `@road(...)`
marker, which every caller then goes through; any other site is a finding
unless it carries `# rule-92: <reason>`. Counted as `undeclared_seam`,
recorded at the measured count and down-only. Why: a hook registered on
commit runs after the write and outside its transaction, so whether it is
`robust` and what it may cancel behind it is a decision, and a security seam
with two registration sites (the socket kick) is a copy waiting to drift.
Declared blind spots: a registration through an alias or a wrapper (the
wrapper's one site is read, its callers are not); whether a seam is `robust`;
test modules.

93. **A field that names a person is declared `personal`**. An AST rule
(`check: personal_fields_declared`, ADR core-30's census): every field an
`*Out` class in an `apps/<x>/schemas.py` declares in its own body whose name
the detector lexicon reads as a person's — its last word `email` or `phone`; a
name ending `_name` or `handle` outside a closed exemption list (`tenant_name`,
`organization_name`, `role_name`, `tag_name`, `app_name`, `file_name`,
`event_name`, `host_name`, `template_name`, `label`, each with its reason in
the entry); a bare `name` on a class whose noun is a person
(`lexicon.person_nouns`) — carries `personal(...)` in its default or a
`not-personal` valve with its reason, on the field's line or above it, counted
as `declared`. Frozen at zero from birth: no backlog class, a finding is a
violation. Why: the strip and `emit`'s refusal act only on what is marked, so
an unmarked person's field is a leak nobody sees. Declared blind spots: a
person under an unlisted name (`handle` alone, `username`, `surname` — review's,
until the lexicon grows the word by a visible diff); the payload half is the
tests' (`apps/core/tests`, `apps/events/tests`); a hand payload under the
`payload` valve and an `event_payload(...)` re-wrapped into a plain dict are
never judged by `emit`; a field declared outside an `*Out` class's own body;
free text.

94. **A product diff pays no platform member**. A derived census (`check:
product_diff_pays_no_platform_member`, read from `python -m quality.djb.scope
product-census`): every product path — a non-platform app's file, `frontend/`,
or a derived file (`scope.PRODUCT_DERIVED`), plus a probe per shape under
`apps/zzz_canary/` — forces nothing, and outside `frontend/` selects only the
gate test modules whose own declaration owns it (a narrowed `drives` or census
`population=` glob, a map row, itself); the loop lane runs neither the selftest
unit nor supply-chain whole. What a diff pays anyway is printed, never
asserted, as `tax: <N> min in <M> member(s) the diff did not own` on the
`--loop` banner and CI's lane. Why: a product builder's change should cost the
product's own tests, and a harness glob that swallowed every app made each one
pay the platform's. Declared blind spots: `frontend/`'s whole-tree readers
(priced, not refused); a platform module a product test imports; a narrow glob
is owned by every path it names; `apps/core`'s per-app tables.

95. **A product commit to the platform or the stack carries its sanction** (`check: system_layer_commits_carry_their_sanction`): on a tree that declares `rule_id_namespace:`, the pre-commit hook refuses a platform path (template-owned, through `divergence.rules_for`) and admits a stack path (`pyproject.toml`, `uv.lock`, `compose.yaml`, `.env.example`, and any `compose.*.yaml` override — derived from the shared set) only under a typed `DJB_LAYER_SANCTION`, which the commit-msg hook records as a `Layer-Sanction:` trailer; the rule names every commit since the base that touched either with no trailer and no fold subject, and every such uncommitted path. Why: a product builder's territory is `apps/`, `frontend/` and their derived files, and the platform arrives by release fold. Declared blind spots: merges; whether the reason is good; edits outside git; the history half's canary is a drive.

96. **A product app imports the SDK only** (`check: product_apps_import_the_sdk_only`): a module under a non-platform app (one `quality/partition.yaml` does not name) — and, on the template, under `apps/example*` — imports `pilecap.*`, its own package, another non-platform app, Django, the stdlib and third-party packages, never `apps.<platform-app>`; each hit names the `pilecap` module that carries the name, and a name the facade lacks prints the same-day valve `# rule-96: pilecap lacks <name> — <job>`, whose counted line is the product's platform-feedback row. Why: the SDK is the one declared import edge, so a product never touches the platform's modules and a move behind the facade never reaches it. Declared blind spots: string and dynamic imports (rule 88's class); copied code (rule 84's); migrations.

97. **The SDK's surface is ratcheted** (`check: sdk_surface_is_ratcheted`): `quality/sdk_surface.json` — derived by `python -m quality.sdk --surface` from every `pilecap` export (kind, source, parameter names and defaults; a model base's per-field `deconstruct()` and Meta digests), the facade's `DEPRECATED` tables and the kit's `surface.json` names — is the tree's, and every name the previous release's surface holds is still exported with a signature every old call binds to, or leaves through a `DEPRECATED` entry served one minor release; on a product's tree the rule prints that the promise is the template's and skips. Why: the SDK's major is the template's (ADR sdk-1), so a name a product imports never vanishes between two releases with nothing printed. Declared blind spots: behaviour under an unchanged signature; a class's methods; TypeScript props; an unfetched tag reads as the first release; the history half's canary is a pytest world.

98. **The harness fits its budget** (the owner's harness size budgets). A file
rule (`check: harness_budget`): `CLAUDE.md` ≤ 150 lines, each skill's `SKILL.md`
≤ 300, each agent definition ≤ 120 — the owner's targets; a file over its
target is counted by its lines over, and the always-loaded set (the guide, the
skills its header names, every frontmatter) by estimated tokens; both recorded
in `quality/ratchet_floors.yaml` and down-only. `--explain 98` prints each
file beside its target and ceiling, and the duplication census — a statement
restated in more than one file, reported, not refused. Why: the comment
doctrine holds code to its contract line and nothing held the harness's own
prose. Declared blind spots: a skill's `references/`; the ledgers; a
restatement in other words.

## App map

What ships, one row per `apps/*/apps.py`: its `depends_on` (house rule 7's ceiling), the door files
it carries, and its side of `quality/partition.yaml`. The block is derived (ADR docs-1) —
`python3 -m quality.docs_derived --write` regenerates it and the `dangling-docs` leg refuses it
stale; routes, tools, workflows and events are `manage.py introspect`'s. The sections below carry
each family's mechanism, never a row. A lead's app-map delta — the apps a cycle adds, before any
code — is written in the cycle's plan as `| app | noun (aggregate) | depends_on | doors exposed |
workflows owned | events emitted / consumed |` rows (django-architect's criteria set); the block
carries the app from the commit that adds its `apps.py`.

<!-- derived: app-map -->
| app | depends_on | door files | partition |
|---|---|---|---|
| `accounts` | `core` | `api.py` · `mcp.py` · `workflows.py` | platform |
| `comms` | `core`, `accounts`, `events`, `workflows`, `connections` | `api.py` · `mcp.py` · `workflows.py` | platform |
| `connections` | `core`, `accounts`, `events` | `api.py` · `workflows.py` | platform |
| `core` | — | `mcp.py` · `workflows.py` | platform |
| `djb_imports` | `core`, `accounts`, `events`, `workflows`, `files` | `api.py` · `mcp.py` · `workflows.py` | platform |
| `djb_notes` | `core`, `accounts`, `events` | `api.py` · `mcp.py` | platform |
| `djb_tags` | `core`, `accounts`, `events` | `api.py` · `mcp.py` | platform |
| `events` | `core`, `accounts`, `workflows` | `api.py` · `mcp.py` · `receivers.py` · `workflows.py` | platform |
| `example` | `core`, `accounts`, `workflows`, `search`, `djb_tags` | `api.py` · `mcp.py` · `workflows.py` | platform · worked example |
| `example_portal` | `core`, `accounts`, `events`, `example` | `api.py` · `mcp.py` | platform · worked example |
| `exports` | `core`, `accounts`, `events`, `files`, `workflows` | `api.py` · `mcp.py` · `workflows.py` | platform |
| `files` | `core`, `accounts`, `events`, `usage`, `workflows` | `api.py` · `mcp.py` · `workflows.py` | platform |
| `realtime` | `core`, `accounts` | `api.py` · `consumers.py` | platform |
| `search` | `core`, `accounts`, `events` | `api.py` · `mcp.py` · `workflows.py` | platform |
| `usage` | `core`, `accounts`, `events` | `api.py` · `mcp.py` | platform |
| `workflows` | `core`, `accounts` | `api.py` · `mcp.py` · `workflows.py` | platform |
<!-- /derived -->

## App map — data portability

**A tenant can take its data and leave.** The mechanism, in the order a reader
needs it:

- **The census is DERIVED** (`apps/exports/census.py`): concrete registry models
  carrying a `tenant`, minus a declared exclusion list where each entry carries
  its reason — a bare exclusion is refused at import, and a table added on
  Thursday is in every archive taken on Friday. A hand-written list of tables is
  the defect the module exists not to be; it is the mirror of the four unlisted
  tables an earlier census found in the other direction.
- **The walk is `for_tenant(t).visible_to(org)`, once per model, and there is no
  second read path.** A tenant-wide export walks under the tenant's **root**,
  whose subtree is the whole tree. So an export of your own organization is
  **free by rule 24** — it reads exactly what every other door already lets you
  read — and the only thing needing a permission is the root's hat, which is
  `accounts.policies.administers_the_whole_tenant`, the same ceiling erasure
  stands behind, reused rather than restated.
- **JSONL per model in one zip, streamed through `.iterator()`, never
  `pg_dump`.** A dump is the deployment's database rather than one tenant's
  rows; it cannot honour `visible_to`, it cannot leave an encrypted column out,
  and it would put every other customer in the file.
- **Encrypted fields are excluded by manifest**, derived off rule 15's own field
  types; a subtree export **skips** the models it cannot narrow, and says which
  and why. An archive that is quietly short a table or a column is
  indistinguishable from a tenant that never had one, and the reader is a
  customer who is leaving and cannot ask.
- **The artifact lands through `apps/files`' storage seam under the version-key
  grammar** (`t/<tenant pk>/f/<file pk>/v/<n>` — XPr re-pointed exports onto
  `store_stream`; the old `core.storage.tenant_prefixed_key` was deleted; the prefix is the whole isolation). The read shape carries a **presigned
  `download_url`** where the backend signs and always a **`download_path`** for
  the authenticated route; `download_url or download_path` is right on both
  kinds of deployment.
- **`Export` is born `purged`** (ADR core-13): thirty days, artifact from storage
  first and then the row, with `purge_exports` and its `ScheduleDeclaration`
  landing in the same commit as the declaration. A copy of everything a customer
  has, kept forever because nobody chose a number, is the largest single
  liability this product can create.
- **The interlock with erasure is a test, not a claim.** ER-1's residue probe is
  re-run against the *extracted archive*
  (`apps/exports/tests/test_archive_privacy.py`): an erased person's identifiers
  appear nowhere in a post-erasure export, and `events.Event` is excluded by name
  because ADO-4's retention argument is about a payload that stays inside the
  deployment and an archive is a file that leaves.

**The storage seam is the files app's** (since `4d9703933`): the archive is filed by
`files.services.store_stream`, addressed by `files.storage.version_key`, signed for by
`files.storage.presign_get` under the files seam's TTL, and referenced by one
`files.FileVersion`.

## App map — the noun-verb family's platform apps (P24; the lead's section)

Three apps shipped with the family — `djb_notes`, `djb_tags` and `djb_imports`, rows in the map
above. Their labels, tables, index names and authorization kinds carry the
template's own `djb_` prefix so that a product's app or model of the same noun
never collides with them — and with the kinds, the url_names, the policy keys
and the MCP tool names derived from them (`djb_note-archive`, `djb_note.create`,
`archive_djb_note`). Their REST mounts and scope families carry the prefix
too (`/api/v1/djb_notes/`, `djb_notes:read` — ADR mounts-1); the attachment
words (`notes`, `tags`, `files`) are the generic words and do not move.

**The three are the family's owners, not nouns of their own.** The mechanism,
in the order a reader needs it:

- **Notes and tags are attach owners; the files app is the third** (its
  `StoredFile` gained the nullable subject pair, expand-only). A row lands
  where ADR attach-1 says, is written only after `core.verbs.resolve_subject`
  has resolved and authorized its subject, and is read only through that
  subject — there is no list of all notes. Each owner declares the `"*"` merge
  repointer in its `merge_repointers.py` under ADR merge-1's contract
  (`move_notes`, `move_tag_links`, `move_attached_files`), and each ships the
  `attach_specimen` hook core's conformance imports. Zero per-noun routes: a
  noun declares `attachments` and the three generic doors serve it.
- **A tag is a tenant-wide word, its link is a placed fact.** Only root
  administrators coin, rename or archive a word (rule 55; reads at the acting
  hat under a dated valve, the stopgap every tenant-wide kind carries while the
  hierarchy gives none of them a home); a link is org-scoped
  and lands by the law above; `create_tag_link` is idempotent and a lost race
  on a tenant-wide subject answers `conflict` with no row.
- **Import is one platform door, never a per-noun upload.** A noun's app
  declares `importers.py` (`IMPORTERS = {"<kind>": Importer(row=…,
  natural_key=…, apply=…)}`) and `apply` calls the noun's own services;
  `create_import` stages a stored CSV against a declared kind, idempotent by
  the document's digest (the same bytes answer the same run); the check
  workflow streams the file through the files seam's one server-side read
  (`iter_object`, ADR files-2 amended) and previews every row without writing
  a noun; the apply workflow writes each row once and a retried activity
  resumes where it stopped — proven by a kill drive that SIGKILLs a worker
  mid-apply; refused rows are skipped and stay listed with their reasons, the
  clean rows apply. `natural_key(*, tenant, actor, row)` resolves under the
  acting hat, so the preview says what the apply will do. `Import` is born
  purged (thirty days, `PurgeImportsWorkflow`); `ImportRow` follows it by
  cascade. Whole-file refusals are `import_invalid` (400) naming their errors.
- **Registration is by discovery**: each app's `apps.py` declares `depends_on`,
  its router tag is its scope family, and its label path is admitted by rule
  32's entry ("the resource IS the app's noun"). The five pinned shared
  surfaces a new platform app touches — rule 32's label paths,
  `FROZEN_FAMILIES`, `quality/partition.yaml`'s `platform_apps` (held closed by
  a `@template_shape` census, so a forgotten platform app is a red and a
  product retires the census with `platform_apps=own`), rule 41's example
  budget rows, and rules 42/54's ratchet class — are the django-architect
  skill's "adding an app" list, each assigned to its file's owner in the wave.

**The roads index is `core`'s, and it is a reader, not a noun** (ADR roads-1): `manage.py roads` /
`roads <job>` / `roads --json`, a reader beside `introspect` with no model and no migration.

## App map — surfaces and identity option B (P26; the lead's section)

**One product, several audiences, one set of records** (ADR surfaces-1,
ADR ident-13, ADR example_portal-1, house rule 85): two apps grow and one is added, read off
`manage.py introspect`, each app's `apps.py`, `surfaces.py` and `roles.py`. The roads the bullets
name are printed by `manage.py roads <job>` — `resolve_surface`, `request_host`, `absolute_url`,
`surface_for_role` — and are not restated here.

- **`core`** — no new noun — `AuditEntry` gains `surface` beside `door` (one expand-only leaf, default `staff`), `Actor` gains `surface`; the declaration `apps/core/surfaces.py` (`Surface`, `ALL`, the implicit total `staff`) is a seam, not a noun · **+ `GET /api/v1/surface/`** (`config.api.surface_view`; unauthenticated, rule 3's allow-list — the face's boot question) · every door resolves the request's surface before its tenant and refuses an unexposed family `surface_does_not_expose`, an unbound host `surface_unknown_host` (both 404) · the URL seam every link the system sends is built by
- **`accounts`** — + `IdentityHome` (tenant 1:1: the realm id and `pending`/`own_org`; one tenant-less row is the staff realm) · `SsoIdentity` widens into the identity join (`realm`, `issuer`; `connection` and `tenant` nullable) · `User.zitadel_sub` retired, the column kept with no reader until a later release drops it · the port `realm.py::IdentityRealm` and its Zitadel adapter `realms/zitadel.py` · REST/MCP unchanged in shape but for `SsoConnectionOut.sync_state` and `409 enforced_without_provider` · shell: `zitadel_seed` (the staff realm, the project check, every surface's browser callback), `zitadel_audit` (a realm section, `n of n tenants homed`; `--tenant`), `zitadel_reconcile` (homes a tenant with no realm) · workflow + `EnsureTenantIdentityHomeWorkflow` · emits `accounts.identity_home.created`
- **`example_portal`** — `PortalRequest` (org-scoped at the customer's hat; kind `portal_request`; names its `Widget` by `PROTECT`) · REST `/api/v1/portal-requests/` (list · submit · retrieve) · MCP `list_portal_requests` / `get_portal_request` / `submit_portal_request` · **declares the `customer` surface** (`surfaces.py`: families `widgets` and `portal_requests`, acts `read`, role `customer`, tenant rule `membership`, screens `/widgets`, `/widgets/[id]`, `/requests`, `/requests/[id]`) and the `customer` role (`roles.py`) · its face is `frontend/src/screens/customer/` + `frontend/src/app/(customer)/` · emits `example_portal.portal_request.submitted`, `example_portal.portal_request.moved`

**What a surface adds** is a clause on its owning app's bullet: the app that
OWNS a surface names it with its declaration's fields, as the portal's bullet
does; an app whose families a surface exposes names nothing (the `widgets`
family is `example`'s). *[2026-09-30, the
screen set:]* the customer face's screens are the four above, as the route
table carries them (`frontend/src/kit/routes.ts`); the design's draft named
`/example/widgets`, which collided with the staff face's worked pages.

## App map — the ingredients (P6–P7; the lead's section, 2026-08-23)

The ingredients are `usage`, `files` and `search`, and `comms` grew SMS, push and engagement reads;
their rows are in the map above and their long-form design record is `adrs-ingredients.md`.

The cross-app arrows are ADRs usage-1, files-2, search-2 and comms-9; the one shared seam is
`usage.services.record_usage`, landed first (P6 wave 0).

### The ADR home

`docs/product/adrs/` is the home of every ADR, one file per id (`<app>-<n>.md`, the id is the
filename), and a new ADR lands there; `adrs-ingredients.md` keeps the ingredients' design record and
no ADR (moved by `cdd8315e7`); this file is the current state — the stack, the doors, the gate and
the house rules in force.

**How bytes come back out is the ratified either/or, applied rather than re-decided**: the files seam always signs — `bucket_name()` refuses a deployment that has named no bucket, so a files object only ever exists where a signing backend is configured — so `download_url` is filled by `presign_get` and a `/download` door over a files object may 302 to it. No `get_stream` ships and none is owed; a backend that cannot sign is an ADR-level change, not a fallback. The bucket a checkout uses is written into `.env` by `scripts/setup.sh` (via `manage.py ensure_bucket`), so `/readyz` carries its `storage` member on a laptop.

**`search` — three facts its map row does not carry.** (a)
**There is no `SearchDocument` model and there will not be one**: the documents
live in Meilisearch, which is a derived view of Postgres and never a source of
record, and the tsvector column the degradation engine reads belongs to the
*adopting* app's model with that app's own migration (R-e). A central projection
table would be the shadow authorization copy ADR search-1 rejected and search-2
did not reinstate — so `search` has no `migrations/` directory, on purpose, and
house rule 31 has nothing to declare here. (b) `depends_on` gained `events` when
the spine tap landed (`2b7caaa2e`, R-b): the app subscribes to each `Searchable`'s `refresh_on`
names and emits `search.engine.degraded/.recovered`. (c) The workflow is the **declaration-digest startup reconcile** rather
than a per-tenant reindex (the owner's ruling of 2026-08-24, `design-agreements.md`,
"Search materializes from its declarations"): each kind's index stores the digest
of the declaration that built it, every worker boot compares them per kind, and
missing-or-different rebuilds through one deterministic, serial, atomically
swapped run while a match does provably nothing. `manage.py search_reindex`
(R-c) is demoted to the manual backstop by that, exactly as the Zitadel console
was. What else landed in R-a: the chokepoint (`search.selectors.get_search_page`, RENAME's name for `selectors.search`, one Postgres
query for the visible-org-id list, per-kind filter shapes, fail-closed on both an
absent tenant and an unresolved hat), the fenced engine (house rule 33), both
doors under the cursor envelope with `SearchPage.engine` on the wire, and the
door-pair parity test — **R-a is where `DOOR_PAIR` is declared**, not R-e,
because the two doors are born here.

**`usage` — the seam is real, not a stub.** `depends_on` carries
`events`, correcting the ADR's own map: usage-1's app-map row was written before
its § "Events / workflow split" ruled `usage.threshold.crossed` IN (owner,
2026-08-22), and an app that emits imports `emit`. What landed: `UsageEntry` born
`append_only` and lifecycle-declared APPEND_ONLY; `record_usage` with the ADR's
signature keyword for keyword, plus `record_correction`, both **door-less with
rule 42's valve** — a client that could record usage could mint its own bill, and
one that could supersede an entry could dispute it into nothing; the meter
vocabulary as a discovered `apps/<x>/meters.py` registry whose grammar is refused
at **boot**; the day-bucketed `MeasuredOut` read, whose basis a reader can
re-add; and the crossing check, which issues **zero** aggregate queries for a
tenant with no thresholds configured. U2 adds the two read doors on top of
`selectors.get_usage` and changes nothing here.

**`files` — the models and the seam.** Two facts from ADR files-2's own § "Events / workflow
split": the sweep is
`SweepPendingUploads` and not `SweepAbandoned`; the events are
`files.file.stored` and `files.file.archived` and not the four-name
created/version_added/archived/purged set (the ADR rejects a
`version_superseded`-shaped event outright — promotion rides `stored`'s payload —
and `purged` cannot be emitted by a purge that v1 excludes). `depends_on` grew past `core, accounts`
as each import landed (`1d97bc305`, F2), because house rule 7 reads that tuple as a ceiling.
What landed: `StoredFile` + `FileVersion` per the ADR's two-model aggregate, both
born lifecycle-declared (UNBOUNDED with the honest archive-is-soft residual, and
BOUNDED off the CASCADE, read from the field); `derive_org_from = "file"` so a
version lands where its document lives; the unique `(file, version)` and unique
`key` constraints that make an overwrite impossible in the schema rather than
discouraged in a service; and `apps/files/storage.py`, the one module that
imports boto3 — presign PUT/GET, head, streamed SHA-256, prefix delete, each
belted by a refusal on any key outside the acting tenant's prefix, all of it
proven against the compose MinIO. **The bucket derives per checkout** by the
`DATABASE_NAME` rule (a name in the environment wins; the derivation is the
checkout's own path hash) and per pytest-xdist worker, so two worktrees sharing
one MinIO never meet. **Key grammar**: F1's `version_key` —
keys carry primary keys and a version ordinal, never a renamable slug or a
user-supplied filename. (The core app's old `storage.py` was superseded by this
grammar and deleted whole, after exports re-pointed onto
`store_stream`; rule 48 is the deletion's enforceable form.)

## The team

Six roles. The PM is the only one that persists; the rest are dispatched per
cycle, do their one job, and go away.

| Role | Model | Owns | Never |
|---|---|---|---|
| **PM** | the session's own | the order of work, the ledgers, the readouts, saying no | writes production code |
| **Design** | `fable` | the shape of the user's screen, held to the settled identity | decides what gets built, or when |
| **Engineering lead** | `fable` | decomposition into rungs, the app map, **the acceptance criteria** | writes the feature it just specified |
| **Development** | `opus` | the code, rung by rung, gate green at each | judges whether the result is good |
| **Field test** | `opus` + browser + machine door | what actually happens when a user drives the build | fixes what it finds |
| **Surveyor** | `fable` | reads the system — code, logs, config, the deployed box — and writes the work it finds into the queue, with evidence | fixes anything · sets priority · trusts a status doc |

Django-specific duties:

- **Engineering lead** owns the app map section of this file for a product, and
  every rung brief names its app and its baseline tree.
- **Development** works in a worktree with its own database, runs `--loop` per
  rung, never runs `--merge`.
- **Surveyor** carries six standing lenses: query counts at seeded scale,
  migration graph health, `check --deploy`, the worker (backlog, failed runs,
  dead letters), the outbox (events that never dispatched), door parity.
- **Every builder loads the `django-conventions` skill** before writing code.
  Its purpose is the documented agent failure mode: plausible-but-wrong ORM
  code and outdated patterns. Current-version APIs, the base model, the
  services convention, `select_related`/`prefetch_related`, no logic in
  signals, how a migration is made inside a rung.
- **Agents read the schema, they do not guess it**: a management command /
  machine door reports the real models, URLs and settings.

## Cycle 0 — "the loop runs green on an empty product"

The bootstrap is itself the first cycle, framed the way the skill frames
everything: a job, with a persona (the PM of the next product), acceptance
criteria written before the code, built by development, proven by someone who
did not build it. Done means:

- a fresh clone runs `./scripts/check.sh` green, with every house rule's
  canaries demonstrably firing;
- the example app proves every convention end to end and a field-test agent
  can drive it through the API from an empty database;
- `docs/product/` skeletons exist, each with one clearly-marked worked example,
  and `loop_health.py` exits 2 on the empty scoreboard, as it should;
- the `product-manager`, `django-conventions` and `django-architect` skills are
  in place and a cold PM can resume from `in-flight.md`.

## What this template is not for (decided 2026-08-19)

The template is optimized for one class: **authenticated, tenant-scoped,
provenance-heavy business systems with long-running processes, built by agent
teams under enforcement.** Every mechanism that makes it excellent there —
audit-per-write, fails-closed tenancy, deterministic workflows, gate
enforcement — is the mechanism that makes it wrong for the classes below. A
product in one of these categories does not clone this template; it gets its
own architecture decision.

1. **High-throughput, low-latency data paths** — telemetry/IoT ingestion,
   clickstream capture at source, bidding, trading, game state, p99 < 20ms.
   The write path is deliberately heavy (transaction + span + log + audit row
   + tenancy resolution) and Postgres is a single writer. The ClickHouse pipe
   is for event *volume beside* the product, not a firehose *as* the product.
2. **CPU-bound compute** — ML training/inference at scale, transcoding,
   scientific compute. The template may *orchestrate* such work (an activity
   calling a GPU service); it must never *contain* it.
3. **Consumer-scale or public-anonymous products** — viral B2C, feed fan-out,
   read-mostly public content. Everything assumes an authenticated actor in a
   tenant; the guardrails give nothing back to anonymous traffic.
4. **Local-first, offline, or real-time collaborative editing** — CRDT/OT
   products invert the server-authoritative, fails-closed shape; the merge
   engine and client-side store are absent and do not retrofit.
5. **Extreme isolation or residency regimes** — contractual per-tenant
   database/physical isolation, per-tenant data residency, multi-region
   active-active, or true event-sourcing (our spine is an outbox, not a
   source-of-truth log). These hit the recorded escalations immediately,
   which means the defaults were wrong for that product on day one.
6. **Things too small for the method** — prototypes, throwaway scripts,
   static sites, single-user tools. The house rules and an audit trail are
   overhead until there is a team whose mistakes they catch and a customer
   whose trust they earn; the engine holds
   <!-- derived: rule-count -->
   96 house rules — `python -m quality.gate --rules` lists them.
   <!-- /derived -->

Fine despite appearances: heavy concurrent I/O (ASGI + Temporal are built for
it), moderate authenticated B2C, heavy background processing, large-file
*orchestration* (presigned URLs, S3).

## Rejected, and why (so a successor does not rebuild them)

- **Seeding the template with a real product.** The template is a system, not a
  product; product state ships as skeletons with one marked example each.
- **The hybrid sign-in door: our page for the password, the identity
  platform's for everything harder.** The obvious compromise, and it is not a
  design that loses on taste — it is one that cannot exist. With login v2
  declared per application, a hand-off from our page to the hosted page is a
  302 straight back to ours: a loop whose only exit is clearing cookies, which
  locked a consumer's owner out of their own deployment for a morning (measured
  by that consumer on the pinned build). So the two doors are a
  WHOLE-DEPLOYMENT switch (`SIGN_IN_DOOR`, ADR ident-9's amendment and design
  I-A §2) and never a per-step fallback: under `ours` a step this page cannot
  ask for reads a sentence and ends the ceremony, and under `hosted` the
  platform draws every screen. trigger to revisit: a build where the hosted
  page honours an inbound hand-off from a login-v2 application — which is a
  fact about somebody else's product, so the measurement kit is where it
  would show up first.
- **django-tenants / schema-per-tenant as a template option.** Slow per-schema
  migrations, tenant context that must be threaded through jobs, admin and
  commands, and not cheaply reversible in either direction. Available to a
  product only as a heavily-considered exception for an actual business
  requirement — never a default.
- **Two API layers.** Drift with a countdown.
- **DRF as the API layer.** Sound for a REST-only product; once MCP, webhooks and sockets each need typed contracts, its serializers become a second schema system beside Pydantic. Ninja's schemas serve every door.
- **Celery (+ beat, + an FSM on a model) for background work and workflows.** A queue with retries; state, resumption and "where is this process" are rebuilt per product. Temporal is that layer, and replaces Celery rather than joining it.
- **DBOS** (durable execution on Postgres alone) — attractive ops profile, but younger and thinner in the field; trigger to revisit: Temporal's operational weight becomes the problem.
- **Processing inbound webhooks inline.** A slow or failing handler loses the event; verify, store, hand to a workflow.
- **SQLite for local/tests.** Hides the Postgres behaviour the product depends on.
- **Fat-model-only business logic.** Agents scatter logic into signals and
  2,000-line models; an explicit services layer is the one that can be
  house-ruled.
