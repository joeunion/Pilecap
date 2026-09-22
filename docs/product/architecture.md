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
| Auth & identity | **Zitadel is THE identity system — B, all at once ("we're fresh, let's do it right so we pay the cost once"; supersedes the earlier app-is-its-own-IdP approach).** Self-hosted Zitadel (Apache-2.0) in compose from day zero, its config **as code, driven through our services via its management API — the Zitadel console is NOT a door**: an identity-config change that did not go through our audited services did not legitimately happen (house-rule-shaped invariant). Browser login: the app is an OIDC relying party against Zitadel (allauth reduced to RP plumbing). **Workforce**: Google federated through Zitadel, domain-restricted. **Customers**: per-org external IdPs (Okta, Entra, SAML/OIDC) — `SsoConnection` survives as the audited config-of-record whose services re-point from allauth internals to Zitadel's API; home-realm discovery, enforced-SSO, domain claiming, JIT membership keep their A9 wire-proven properties, re-proven against the new engine. **MCP**: OAuth 2.1 with Zitadel as the authorization server; tokens exchanged into the org-bound principal; DCR/consent are Zitadel's. **SCIM**: Zitadel's, maturity verified at the first customer demand (WorkOS stays the named fallback if it falls short). The suite-IdP end-state arrives at day zero instead of at the second product. A fresh clone's `setup.sh` seeds Zitadel — a deliberate DX rung, not an accident. An IdP answers *who*; `Membership`/roles/policies/audit stay ours, unmoved. **Amended 2026-09-15 (owner, DESIGN-I decision A, on P20's evidence: a 21-minute first admin on the hosted page):** ADR ident-4 reads "Zitadel holds every credential and decides what is required; OUR page renders" — the hosted page stops being the front door; lane I-A's sign-in remedies and A1's join at sign-in are the first instances. |
| Custom user model | **Set on day zero**, before the first migration, and boring: `AbstractBaseUser` + `PermissionsMixin`, email as the identifier, no product fields. Own the table; do not design the user. House rule: `auth.User` is never imported; `get_user_model()` / `settings.AUTH_USER_MODEL` only. |
| Base model | Every concrete model inherits `core.models.BaseModel` (**UUIDv7** pk — time-sortable — `created_at`, `updated_at`). House rule. |
| Business logic | **Explicit `services.py` for writes and `selectors.py` for reads, per app. Decided.** Services own writes; routes and schemas are thin; models carry invariants and derived properties, not workflows. **No business logic in signals** — signals are where agents hide logic. House rule. |
| Tenancy | **Shape: shared schema + tenant FK, read through a scoped manager, enforced by a house rule. ON by default; a product opts out. Decided.** The template ships `core.Tenant`, `core.Membership` (user × tenant), the abstract `TenantScopedModel(BaseModel)` with a `tenant` FK, a `ScopedQuerySet.for_tenant(tenant)` manager, and `TenantMiddleware` that resolves `request.tenant` from the user's membership (default membership; an `X-Tenant: <slug>` header may switch to another tenant the user belongs to; no membership → `request.tenant = None` and every scoped read returns nothing — **fails closed, no superuser exemption**). The example app inherits `TenantScopedModel`; every read in views and services is `Model.objects.for_tenant(request.tenant)`; house rule 8 is **enabled** and refuses a bare `.objects` on a scoped model outside the manager. **Opting out** (a genuinely single-tenant product) is recorded in the product's `architecture.md`: models inherit `BaseModel` instead, the middleware is removed, rule 8 is set `enabled: false` with the reason. Schema-per-tenant (django-tenants) is **not** a template option: a product may adopt it only under heavy consideration and only when it is an actual business requirement (e.g. a compliance demand for database-level isolation), recorded with the requirement named. Rationale: the base, the resolver and the rule are the part that is painful to retrofit; shipping them on means the leak-shaped code is refused from the first model. |
| Hierarchy | **A template primitive, on from the start ("this framework needs to support hierarchies efficiently and securely from the start").** Per-tenant `Organization` tree (materialized path, fixed-width segments, indexed prefix scans — no recursion, no tree walks on the read path); **every tenant gets a root node automatically**, so a flat product is a depth-one tree and pays nothing. `Membership` = person × tenant × org × role; `OrgScopedModel(TenantScopedModel)` for networked records; reads are `.for_tenant(t).visible_to(actor)` — **visibility flows down only, fails closed, no exemptions** (upward/sideways inheritance only as an explicit policy with a named reason). Roles inherit down (effective role = best role on the record's ancestor chain, computed over the actor's own memberships). Acting hat via `X-Org`, revalidated per request. **No grant above your own effective role or outside your subtree** (the escalation wall). Re-parenting is a service + workflow, audited, ancestor-admin of both ends only. Aggregates go through the same scope. House rule 24 enforces `visible_to` on org-scoped reads by AST, with canaries. Audit and workflow context carry the acting org. |
| Frontend | **Opinionated default — Next.js/React/TypeScript consuming the GENERATED OpenAPI client. Owner-ratified 2026-09-02, superseding "bring your own"** (which had drifted false against the tree: `frontend/` ships Next 16.3.3/React 19.2.8 since the P16 SCAFFOLD merge, `fe-conventions` is written at those pins, rules 51–53 enforce the layer — the register said none while main shipped one; the drift was caught by the owner's own question). The halves meet ONLY at the OpenAPI document (P16 strategy pillar 1): doors serve it, the client is generated never hand-typed, the byte-pin makes drift loud; the backend never imports or assumes the client. **Bring-your-own remains legal as a recorded product divergence** in the product's own architecture.md — at the cost of the scaffold, fe-conventions and rules 51–53's enforcement, which that product replaces or forgoes. Rejected: keeping "bring your own" settled with `frontend/` demoted to a non-normative example (weakens the JS rules' standing on every product that takes the default); reversing the frontend package (the ratified P16 strategy's frontend half, built and verified). |
| Background work & workflows | **Temporal, from day zero. Decided.** Durable execution for everything that must survive a restart or wait: webhook delivery with backoff, integration syncs, multi-step processes that wait for a human or a signal, schedules. **Activities** call services; **workflow code is deterministic** — no ORM, no I/O, no clock, no randomness inside a workflow function (house rule 9). Local: the Temporal dev server in `compose.yaml`; a `worker` process beside the web process. Production: Temporal Cloud by default, self-hosted as the recorded alternative. **There is no Celery, no beat, no `django.tasks` backend** — Temporal is the one engine for tasks, retries, schedules and workflows. |
| Server | **ASGI by default** (`uvicorn`), because sockets and async endpoints are day-zero. The CRUD core stays on the sync ORM; async where an endpoint is I/O-bound. |
| Sockets | **Django Channels** with the Redis channel layer; one authenticated consumer; services emit events that the realtime bridge pushes. **The hierarchy reaches this door (ADR realtime-2):** the socket used to push every fanned event to one group per tenant while REST read the same rows through `visible_to`, so a branch-B seller's socket received branch-A's rows — two doors, one question, two answers. Now `Event` carries the **row's** organization (ADR realtime-2a: it rides the `EventOut` envelope, the one body both the webhook and socket doors are handed, so the fan-out narrows on a field it can see and the spine's bridge signature never changed); an org-bearing event is pushed to `org_group(tenant, org)` and **only** an org-less one to the bare tenant group; and a consumer joins its hat's **subtree** org groups at connect — the socket's half of house rule 24, narrowing *subscriptions* where REST narrows rows, downward-only and failing closed on an unresolved hat. A flat product is a depth-one tree whose root hat joins three constant groups, so the depth-one property is preserved. Every consumer also joins `user_group(user_id)` **FIRST, before either of its reads** (R4 F3 — a narrowing that commits while `connect` is still resolving would otherwise kick into a group the connection has not joined, and the kick is lost), and the bridge name **`realtime.kick`** (shape `KicksUser`) closes that group's sockets — connect-time-only auth is right for a channel that stays open for hours and wrong the moment a token is revoked, so revocation and erasure reach the connection instead of the connection eventually noticing. **Clause (d) has a second primitive: `realtime.kick_tenant`** (shape `KicksTenant`), a `KICK_TYPE` frame on `tenant_group`, because a tenant that is suspended or closed is not a fact about one person — `suspend_tenant` and `close_tenant` register it through `core.services.close_tenant_sockets_on_commit`, and before they did, a darkened tenant was refused at the next handshake and nowhere else while every live socket went on hearing (R4 F2). A **resume** kicks nobody: a widening takes nothing away, which is `kick_if_reads_narrowed`'s asymmetry one level up. **The channel is declaredly lossy and the seam is poll-on-reconnect** (`apps/realtime/bridge.py`'s docstring says it in full): no replay buffer, no cursor, none planned — a reconnecting client re-reads the REST list it cares about and treats a frame as a hint that something changed, and a hat switched mid-connection applies on reconnect. Rejected: **ancestor-chain publish** (cheaper joins, but the fan-out cost rides every emit including the socketless majority, where subtree-join cost rides only connected sockets) — RECORDED, with M4's measured join count at the 1,200-org hat as the trigger to revisit; a `visible_to` query per push (a DB read per event per connection — the N+1 the harness exists to refuse); connect-time-only auth with shorter tokens (narrows the window, closes nothing). |
| MCP | The official Python MCP SDK mounted on the ASGI app at `/mcp` (Streamable HTTP). Tools are thin over services; token auth bound to user + tenant. The machine door — same services as REST; a disagreement between doors is a finding. |
| Webhooks & events | `apps/events`: services `emit()` domain events → an **outbox** row → a Temporal workflow fans out: signed outbound webhook deliveries (HMAC, retries, dead-letter) and realtime pushes. Inbound webhooks are verified, stored and handed to a workflow — never processed inline. |
| External connections | `apps/connections`: per-tenant `Connection` (provider, **encrypted credentials** — Fernet, key from env — status), an `httpx` client factory (timeouts, retries, idempotency keys), the OAuth-callback pattern, one inbound-webhook receiver. Providers are product work. |
| Communications | **A template platform app (`apps/comms`) — every product needs it and uses it; it must be easy and consistent; what changes is the provider behind it. Decided.** One door: `comms.send(*, recipient, template, context, channel, tenant, actor)` — nothing else in a product sends anything (house-rule-shaped: the only legal sender). Behind it: a **channel-provider registry** (email built in via the mail path + django-anymail at the ESP edge; SMS/Slack/push as `connections` providers a product enables — swapping a provider is config + a connection, never a code path change). `Message` (per-attempt log: channel, provider id, status queued→sent→delivered→bounced, correlation ids), `MessageTemplate` (per-tenant, versioned, variables schema-validated), `ChannelPreference` + consent (category opt-outs — transactional vs marketing, quiet hours, suppression) **enforced inside `send()`, so no campaign or feature can bypass it**. A `Recipient` concept for people who are not Users (contacts). Delivery, retries and fallback ("push, then email if unread") are Temporal workflows; provider status webhooks arrive through `connections`/`events` and become `comms.message.*` events. **Novu is the recorded escalation** for marketing-grade journeys/digests/inbox UI, as a product divergence with the requirement named — never the default. **The wall is not a weapon (ADR comms-9, amending comms-8):** a bounce carries a `BounceKind` and only a **hard** one suppresses — `complained` and `rejected` are hard by their event type, an unclassified bounce is hard by the conservative default, and a soft bounce is recorded and acts on nothing; **Amended: complaints are consent news, not delivery news — they suppress without transitioning the message; the soft branch is provider-dependent and declared per adapter.** `complained` still normalises onto `bounced` at the adapter, because *stop mailing this address* is what one suppression rule has to read, but it carries `ProviderStatus.is_complaint` out with it and `record_delivery_status` forks on that above every transition guard: the recipient is suppressed through the same `suppress_recipient`, the fact is announced as `comms.message.complained`, and `Message.status` is left exactly where the provider left it — a complaint by definition follows a delivery, and the collapsed set could only say so by writing `bounced` onto a row that had arrived (`complained@resend.dev` was refused with `Conflict("That message is delivered and can no longer be bounced.")` and suppressed nobody). The settled-row guard itself is untouched: a *bounce* after delivery is still refused. **No column** — the fact is carried by the suppression, the audit row and the event; a `complained_at` waits for a product that must list complaints per message without reading the audit trail, and until then a flood made only of complaints does not open a surge (the tripwire counts the bounce population); the provider message id is **never echoed into the mail we compose**, because it is the key a status webhook suppresses an address against and a forwarded receipt was therefore a weapon; and a **mass-suppression tripwire** (25 addresses per connection per trailing hour) emits `comms.suppression.surged` / `.recovered` on the **transitions only** — the announce-on-transition ruling's first application — without ever halting suppression, since a tripwire that disabled the wall would be the better attack. **A temporal lever delays; only a permanent one kills (ADR comms-10):** at the transport edge the consent recheck forks by the *kind* of lever that refused — suppression and withdrawn consent are facts about the person, so the message dies and the run closes **promptly**, through the finish seam and with no 72h `STATUS_WAIT` behind it (a `WorkflowRun` reading `running` for three days about a message refused in milliseconds was the ledger lying by laziness); quiet hours is a fact about the *clock*, so the run **sleeps to the recipient-local window-open on Temporal's timer and then re-runs the FULL wall** before handing anything over — the deferral is a road back to the wall, not around it, so a suppression landing during the sleep refuses at the second judgement. The deferral is a **designed delay and not a degraded state**: no announcement event, deliberately. Rejected: kill-and-re-enqueue (duplicates the row and restarts the policy), a poller over deferred messages (the run already exists and can wait — anything that waits is a workflow), keeping the 72h wait for refusals. Revisit when deferral volume makes the sleeping-run population itself a cost, at which point one scheduled release workflow per window, as data. **A drop is a judgement, and it says which one (ADR comms-13; decomposed as "comms-10", a number the temporal-lever ruling above already holds — same ADR, next free number):** the status vocabulary on the template-HMAC path is **anymail's normalised shape and nothing else**, because with no Anymail ESP configured there is no translation to read a vendor's raw body with — `{"event_type": …, "message_id": …}` is the door's contract there, and a raw `{"type": "email.bounced", …}` is a language that deployment cannot read. The three ways a status body can produce no status are three findings for three different people, and each now carries **its own log name and its own remedy**: `comms.status.ignored` fires **only** for an event that was read and understood as non-terminal and always prints the word it read (the door working, the run still waiting); `comms.status.untranslatable_body` for a body carrying no vocabulary this deployment can read, naming both ways out — post the normalised event, or set `EMAIL_BACKEND` to an Anymail ESP — which is a **deployment** fault; `comms.status.no_message_id` for a terminal event naming no handle to join on, which is a **provider** fault. One name over three causes is exactly the shape a nameless drop used to take: `ignored` with an empty `event_type` claimed a judgement nobody had made, the message stayed `sent` forever, and the field test spent its first two days on the worker. **The account of a drop is the adapter's, like the status itself** — `ExplainsStatusDrops` is an *optional second protocol* beside `ChannelProvider`, so a product transport that never grows it still never produces a nameless drop (the door falls back to what it can read for itself, and that fallback is driven by a test rather than hoped for). And `scripts/mail_demo.py` **speaks the contract it drives**: it already asked which signature scheme the stack arms, it now asks the same question of the *body* — normalised on `hmac`, raw ESP on `svix` — and leg 4's failure names both indistinguishable causes (read-and-dropped, with the log names to grep; or never-processed) instead of blaming the worker first. Rejected: guessing the ESP from the connection slug (the provider is `EMAIL_BACKEND` and nothing else — comms-12); refusing an unreadable body with 4xx (verify→store→202 is settled in comms-3, and a 4xx would make somebody else's malformed payload our door's problem); valving the comms doorless trio here (ADO-8 — a valve without the paired `quality/rules.yaml` tighten kills rule 42's canary at the merged tree, the a0da0bd class, and the coordinated close is a residual for a rung allowed both files). Revisit when a product's relay cannot normalise: it implements `normalize_status` and `explain_status_drop` on its own adapter, which is what both protocols sit on the seam for. |
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
- **Sockets** (`apps/realtime`, one consumer per tenant group),
- **Webhooks in/out** (`apps/events`, `apps/connections`),
- **Workflows** (`apps/<x>/workflows.py` + `activities.py`, discovered by the worker).

**Every door calls services; services own writes and `emit()` events; workflows carry anything that must wait or retry.** **Upward calls invert through the bridge**: when a lower layer needs a higher one (`core.mail` starting a workflow; a `core` service emitting an event), it calls `core.bridge.get("<name>")` — a runtime registry that higher apps fill from `AppConfig.ready()` (`workflows.start_on_commit`, `events.emit`, `realtime.push`). An upward *import*, even function-local, is a violation (the one `core.mail → apps.workflows` exception recorded in pyproject is temporary and dies when the bridge lands in rung A3). Absent registration = the bridge raises in production settings and no-ops with a log in local/test — a template without the platform apps still runs. Registration is by **discovery, never by editing `config/` or `pyproject.toml`**: `INSTALLED_APPS` is derived from `apps/*/apps.py`; a new app drops an `api.py`, `mcp.py`, `workflows.py`, `activities.py`, `consumers.py` and the mounts find it; an app declares what it may import on its own `AppConfig` (`depends_on`) and house rule 7 enforces it, with import-linter keeping only the fixed layer contract (`core` ← `accounts` ← platform ← domain). That is what lets one agent per app run in parallel without touching a shared file. (Ruled after an early alignment review found registration was hand-listed.)

**ADR workflows-6 · the run ledger gets a read door, and the actor's own runs replay.**
*Context*: the run ledger was reachable only from admin/shell; "the
actor's own runs" was unanswerable because `WorkflowRun` recorded no starter.
*Decision*: `started_by` (nullable FK User, `SET_NULL` — the ledger outlives
its people) written by `record_run` off the user `start_workflow_on_commit`
already threads; list/get `for_tenant`, policy-gated (`workflowrun.read`),
the list defaulting to `mine=true`; **`start_replay`** (the service verb is
`start` — `replay` is not in the lexicon and the wave may not edit it; INT's
re-pin adds `replay` and the rename back is one commit) resets a FAILED run
the actor started to its first workflow task — Temporal re-executes the
recorded input, which rule 9's determinism is what makes legal; same
deterministic id (rule 18); dispatched `on_commit` robust; history expiry
decided from the row's clock (`HISTORY_RETENTION`, a module constant —
promote to a setting when a deployment's namespace retention differs from
the default); signal/retry stay operator (the ruling). *Rejected*: replay as
re-invoke-the-origin-door (the client may no longer know the input; the
ledger is the thing that knows), storing run inputs in the row (two truths),
backfilling `started_by` (a guess wearing a fact — empty means unknown).
*Trigger to revisit*: history-retention shorter than the product's replay
expectations.

**ADR workflows-7 · a run its owner started, its owner may stop —
and the ledger's third word is witnessed, never asserted.**
*Context*: The run ledger could show you your work and re-run it when it
failed, and had no way to stop one that was running away — the only cancel in
the product was the Temporal CLI, which is not a door. And `WorkflowRun.Status`
had two closing words, so a run somebody deliberately stopped read, months
later, exactly like one that broke; the reconciler lumped Temporal's own
`CANCELED` into `FAILED` for want of anywhere else to put it.
*Decision*: **`cancel_run`** — `POST /api/v1/runs/{run_id}/cancel/` plus the
MCP twin over `contract_of` — with `start_replay`'s four walls in
`start_replay`'s order: tenant (`for_tenant` → `NotFound`), membership
(`require(actor, "workflow_run.cancel", run)`, a named `policies.py` predicate),
ownership (`started_by` null or not the actor's → `NotFound`, never
`Forbidden`, the existence-oracle argument), state (non-RUNNING → `Conflict`
naming the status). The Temporal cancel is dispatched on
`transaction.on_commit(..., robust=True)`, the fifth registration in the tree's
survey. **`Status` gains `CANCELLED`** (one expand-only, choices-only
migration) and **the service stamps no row field at all**: a cancellation is a
*request*, so the door answers with the row as it is — still `running` — and
the contract sentence tells the caller to poll. The row closes as `cancelled`
only when somebody witnessed it, and there are exactly two witnesses:
`workflows._finish`, which now catches a server-originated cancellation
(`asyncio.shield` around the mark, because a cancelled workflow's own task is
already cancelled; `workflow.cancellation_reason()` to tell that from an inner
scope losing a race), and `activities.reconcile_runs`, whose `CLOSED_AS` maps
`CANCELED → cancelled`. A cancelled run does not replay: `start_replay` refuses
it with a `Conflict` of its own naming the status, because a deliberate stop is
not a failure. Audited as `workflows.cancel_run` per door; **no event** — there
is no consumer, and the trigger is recorded rather than the topic shipped.
*Rejected*: operator-wide cancel (ADR workflows-6's ruling stands — signal and
retry-tuning stay operator-only, and cancel is the actor's own for the same
reason replay is); a synchronous row close at the door (the ledger would assert
an outcome because somebody asked for one, and a workflow that ignored the
cancel and completed would leave a `cancelled` row over a `completed` history);
a `workflows.run.cancelled` event (nothing subscribes; the trigger is the first
subscriber). *Trigger to revisit*: the first stuck run whose owner has left the
tenant — the own-run wall means no admin can clear it, which is deliberate
today and is the thing that will make somebody want an operator door.

**ADR ident-6 · erasure and deactivation get doors.**
*Context*: `erase_user` and `deactivate_user` were built, tested and
audited, and only a shell reached either — `erase_user` was one of the four
names in accounts' house-rule-42 census, which is the rule's complaint said
about the two most consequential acts in the product. *Decision*: self-serve
(`/users/me/…`) and admin-initiated (`/users/{user_id}/…`) doors over the
EXISTING services, on REST and MCP; **who may erase or deactivate whom is
`policies.py`'s** — `themselves_or_administers_the_whole_tenant`: the person
themselves, or an `admin` or better at the tenant's **root**, the wall stated
in code (C7) and never in a door. `deactivate_user` gained `actor` and
`tenant` — additions, not replacements — because a service that resolves no
actor authorizes nothing and a service that declares no `tenant` is not
audited, so the door could not have been given the wall without breaking C7
from the door side. A broader completeness sweep of the same census remains a separate, unchanged
effort. *Rejected*: waiting for that sweep (doors are ratified now; the
contract does not change when the sweep deepens); erase-by-DELETE on
a user resource (erasure is a service act with an audit row, not a REST
cascade); `me/` twins on MCP (a second pair whose only difference is an
omitted argument is a second place for an agent to guess wrong).
*Trigger to revisit*: the completeness sweep landing — re-run this ADR's door
tests byte-unchanged.

**ADR api-1 · the OpenAPI document is the contract, complete.**
*Context*: the owner read staging's Swagger and ruled the API documentation
standard a prerequisite before any product code lands. A census — measured
before enforced — found 51 of 51 summaries were
prettified function names, 11 routes carried no description at all, not one
route documented a header or a refusal, not one of 57 schemas carried an
example, there was no `tags` section and no overview — and all 36 MCP twins
described their capability in words of their own. Five cycles of code review had
read every one of those routes. *Decision*: every route carries a summary and a
description **derived from the same docstring its MCP twin renders**, so the
doors cannot drift; every tag carries a description declared by the app that owns
it; `X-Tenant`, `X-Org`, `Idempotency-Key` and `Idempotent-Replayed` are
documented once as parameters, with the hierarchy explained; every route's error
responses **enumerate the refusal codes it can raise, with the registry's own
fact and remedy text** (`introspect`'s refusals section is the source); every
schema carries an example; an overview — auth flow, token minting, the MCP
door's address, versioning — opens the document; and the TS client regenerates
clean. It is applied **once and derived**, in `apps/core/api/docs.py` and
`config/api.py`, so a route born in any app carries the whole standard with it.
House rule 41 is the census that keeps it true, ceiling zero, pinned at birth.
*Rejected*: summaries-only (an earlier quick fix the owner superseded);
per-door doc strings (the drift rule 17 exists to refuse, one surface over);
hand-written `summary=`/`description=`/example arguments per route (51 places for
the annotation and the behaviour to part company); doc coverage as review-only
(51 routes and five cycles of review missed it — a census is what holds).
*Trigger to revisit*: a client generator the TS one cannot serve.

*Amended* — **the bar for what goes above the divider**. The
contract half speaks **to the caller, about the wire, in plain language**: what
the operation does, what to send, what comes back, what each refusal means and
what to do about it, written for a developer who has never seen this codebase.
The test is one sentence: **if a stranger with an API key cannot act on it, it
goes below the divider.** Never above it: internal function names, queue-row
numbers, fix history, module comparisons, or house idiom ("the house list
shape", "doors", "the machine door"). Four of those symptoms are *shapes* and
are therefore gated — `N\d+`, an underscore-prefixed identifier, `@service`,
`manage.py` — and the rest is review's, declared as such in rule 41's
`does_not_cover`. The same bar reaches **runtime refusal prose**: `authz.require`
answers with the app's declared `ACTION_PROSE` sentence, never with the internal
action name.

*Amended* — **the contract reads like Stripe's**. The
mechanism was right and the output was not: because `summary` was the
docstring's opening sentence, the rendered navigation was a column of sentences,
some carrying literal `**`. Four elements, all derived, nothing hand-annotated:
**(1) a title is not a sentence.** The docstring's first line is a nav-safe
title — a short noun or verb phrase, no Markdown, no full stop, at most **60
characters** (`docs.TITLE_MAX_LENGTH`, `rules.yaml`'s `title_max_length`, and
this paragraph, which agree by review). It becomes `summary`; the paragraph
below it becomes `description`, and the title is not repeated there. The MCP
twin renders the whole contract half, title line included, so the doors still
cannot drift. **(2) Real examples.** A field declares its own realistic value
with `core.schemas.example(...)`, which the synthesiser prefers over the
shape-grade value it would otherwise derive; the persona arc's schemas were
declared and the rest is a **ratchet** rather than a retroactive fail, so a new
field must declare and an old one may be improved at leisure. **(3) Guides and
reference are separate layers.** The overview is a short shelf of `##` guides —
quickstart, authentication, tenants and organizations, pages and filters,
idempotency, errors, events, versioning — each a concept read once and linked by
anchor, above a reference that stays per-operation. `/llms.txt` demotes those
headings by one when it embeds them. **(4) Tags are named for humans.** `TAGS`
maps a wire name to `Tag(display, description)`; `display` reaches the document
as `x-displayName` and no URL, label or client namespace moves.
**(5) One operation, one section.** An operation carries **exactly one tag**,
and a tag with no operations is deleted rather than left as an empty heading. A
renderer lists an operation under every tag it carries, and ninja *accumulates*
a nested router's tags onto everything beneath it — so `accounts`' mount tag
over three tagged child routers printed all eleven of that app's operations
twice, once in their real section and once under an umbrella that was a copy of
the other three. Gated; the orphan-tag half is a test, and rule 41 says which is
which.
*Also rejected here*: a hand-written `summary=` per route to get titles (the
same second copy this ADR rejected at birth); a title derived by prettifying the
function name (the earlier, replaced approach); examples as a fixtures file beside
the schemas (a second copy of the shape, which is what `add_examples` exists to
avoid); renaming tags to make them readable (it would move every route's
namespace in every generated client to change a label); keeping an umbrella tag
and asking renderers not to duplicate (a document that needs a renderer's
cooperation to be readable is a document with a second contract).

*What the sweep to this bar is, in one line, because a product will do it
again*: **write the caller's sentence, then check it against the service — and
where the service is ambiguous, drive the wire.** Applied across 86 operations
it found six defects in prose five cycles of review had read, and two of them
this time were provable only by calling the endpoint: a duplicate slug
documented as `409 conflict` that is a `400 invalid`, and a last-owner
protection documented into existence that does not exist. Every operation now
closes with the same block — the refusal codes with their status and what the
caller does about each — because a caller who has read one operation should not
have to learn a second grammar to read the next.

**ADR api-2 · resource-first URLs — the first path segment names a
resource, never an app.** *Context*: the owner's ruling (design-agreements.md) —
an app label in a path is **internal taxonomy on the
wire**, the URL twin of the sidebar-tag finding, and it asks every caller to
learn which module of ours happens to serve a thing in order to type it and then
ignore it. A census — measured before enforced —
found 43 of 66 mounted paths under an app label that was not a resource, and 5
paths with no trailing slash. *Decision*: **`PREFIX = ""` for the four platform
groups** (`core`, `comms`, `events`, `workflows`) — each of their routers already
carried its resource as the first segment inside itself, so the flatten is four
lines and not fifty; **three renames, resolving by better names rather than by
prefixes** — `policies` → **`delivery-policies`** (`policies` alone says nothing
on a wire that also has authorization policies), `endpoints` →
**`webhook-endpoints`** (likewise beside OAuth endpoints), `catalogue` →
**`event-types`** (a catalogue is a document, this is a collection, and
`event_type` is the noun its own `url_name` stem already used); **the five
slashless routes gain the slash** (`auth/realm` and the four user actions) —
one convention, no exceptions; **`me/` stays** and action verbs stay POST
subresources. **`url_name`s do not move, anywhere**: they are internal joins —
rule 17 derives the expected MCP tool names from them, rule 3's route-test
clause greps them, and the frozen nets pin them — so **tool names do not change
when paths do** and door parity survives by construction. Enforced by **house
rule 32**, whose two populations are both closed (app labels off the app
registry, paths off the live mount) with **one valve**,
`scope.allowed_label_paths`: a label with its reason, seeded with
`connections`, because A1 names an app as the plural of its aggregate and a
domain app's label legitimately **coincides** with its best resource name. The
valve declares the coincidence instead of refusing it, and the refusal keeps
catching the leak class — `core`, `comms`, `events` and `workflows` are
infrastructure names and never resources. *Rejected*: dual-registration
transition windows (two operations per route in the contract, parity noise —
pre-T0 there is no client to transition); keeping the prefixes with redirect
aliases (the leak persists in the document, and a redirect is dual-serving with
extra steps); renaming the MCP tools to match (nothing derives a tool name from
a path and no consumer exists — recorded residual, trigger: the first external
MCP consumer confused by the noun mismatch). This is a **breaking URL change on
v1**, which E5 normally forbids; the license is the empty consumer register and
the ruling's own sentence — *after the first external consumer this is a
versioning event*. *Trigger to revisit*: that first external consumer.

**ADR events-4 · the spine gets a door, and the signing key is said
once.** *(Paths amended by ADR api-2: the endpoints door is at
`/api/v1/webhook-endpoints/` and the catalogue at `/api/v1/event-types/`; the
shape below is otherwise unchanged.)* *Context*: an owner-ruled prerequisite — the event spine had an
outbox, signed deliveries, retries and dead-lettering from the start and **no
door**: endpoints were managed from the admin and the shell, so nobody outside
this tree could subscribe to anything. *Decision*: endpoints CRUD at
`/api/v1/events/` with MCP twins — **create returns the secret exactly once**,
generated by the server, and `WebhookEndpointOut` (what get, list, update, pause
and resume answer) has **no secret field at all**, so it is a schema with nowhere
to put one rather than a filter somebody remembered; a new
`issue_endpoint_secret` service in the same shape for rotation, which is a
replacement with no overlap window (the old key stops verifying at the next
delivery, which is what rotation is *for* when the old key has leaked); pause and
resume through `deactivate_endpoint`/`resume_endpoint` rather than a settable
`is_active`, so the audit trail names the act; deliveries and dead letters
listed, with `attempts` as the lineage on one row per (endpoint, event); and
dead-letter replay through the existing `enqueue_dispatch` path (ADR events-3's
machinery), which re-runs the whole event's fan-out and is why `X-Event-Id` is on
every delivery. **The catalogue is DERIVED** from the installed apps'
`events.py` declarations — rule 16's population, the same registry `emit`
validates against — so a subscriber picks from what exists, and the census test
pins the door's answer to that population. *Rejected*: a hand-listed catalogue
(wrong the morning after the next app declares an event, and
nothing fails); secret re-read behind a permission (a secret that can be read
again is a secret that leaks twice); per-endpoint delivery replay as a new
workflow (the resume path exists); an endpoint DELETE (`Delivery.endpoint` is
`PROTECT` — deleting the endpoint would quietly take the record of what was sent
to it); a door onto `emit` (a caller who could name a name and a payload could
publish anything to every subscriber the tenant has, signed with the tenant's own
key — it carries the `# door:` reason instead). *Naming, amended at build*: the
service is `issue_endpoint_secret` and not `rotate_endpoint_secret` because
`rotate` is not in rule 16's declared service lexicon and editing `quality/**`
is off-limits to a rung that owns no territory there; `issue` is declared, is what minting a credential is
called elsewhere in this tree, and the "the old one dies now" half is carried by
the docstring and the tests. *Trigger to revisit*: subscriber-defined event
filters, or a subscriber asking for per-event payload schemas in the catalogue
(recorded, not built).

**ADR connections-1 · RESERVED, ruled in code, never written here
(bookkeeping).** The number is cited in code and its ruling lives
in those docstrings, not in this file: `apps/events/receivers.py` (the module
docstring — "the source is a row" — and the narrowed receiver at `:66`, `:113`,
`:243`), `apps/connections/services.py` (`:82`, `:268`, `:438` — the delivery-id
headers and the narrowing that lets the probe offer the row),
`apps/connections/models.py` (`:173`, `:190`), the migration
`apps/connections/migrations/0002_inboundwebhook_delivery_id_and_more.py`, and
the tests `apps/connections/tests/test_api.py` (`:424`, `:564`),
`apps/connections/tests/test_discovery.py:170` and
`apps/events/tests/test_receivers.py:9`. Nothing is reconstructed here — read
those docstrings for the ruling. **The number is reserved**: no future ADR in
the `connections` run may take `connections-1`, which is why `connections-2` was
the next free number when D4 landed.

**ADR connections-2 · the inbound door gets the freshness half, and
it is the scheme we already send.** *Context*: the one
signature-verified inbound receiver (`apps/connections/api.py`) checked an HMAC
over the body bytes and nothing else, so a delivery captured off the wire
verified for as long as the connection's secret lived; `scripts/mail_demo.py`
leg 6 reported the replay question `n/a` because there was nothing in the scheme
to answer it with. An earlier ruling had already closed exactly this on the way *out*
(`X-Signature-V2`, a signed timestamp and a window), which left this door as the
half of the round trip with no clock. *Decision*: the door verifies **the same
exact envelope the outbound signer uses** — `X-Signature-V2: t=<unix seconds>,sha256=<hex HMAC-SHA256
over "<t>.<body>">`, keyed on `connection.webhook_secret` — and **does not
re-implement it**: the tolerance (`SIGNATURE_V2_TOLERANCE`), the element grammar
(`parse_signature_v2`) and the comparison (`signature_v2_matches`) are
`apps.events.receivers`', so one implementation decides for a product that
points this template's webhooks at this template's receiver. **Expand without
downgrade**: a sender that only knows `X-Signature` is untouched, but when
`X-Signature-V2` is present it is the *only* header consulted — a correct
`X-Signature` beside a stale or forged `X-Signature-V2` is refused, because a
scheme a sender can be stepped down from buys nothing (the replayer would simply
drop the header carrying the window). The wire refusal is **unchanged** —
`401 "Invalid signature."`, with digest, staleness, secret and existence all
withheld — and the route's docstring is where an honest sender learns the
grammar, which scheme wins, and the window in minutes (pinned to the constant by
a test). The empty-secret fail-closed clause covers the new scheme, stated in
this door rather than borrowed from over the border. *How the constant is
reached*: a **runtime lookup through the app registry**
(`connections.services._events_attr`), never an import. `import-linter` holds the
platform apps independent of one another, `apps/connections/apps.py` promises
this app keeps working in a tree where `apps/events` never landed, and
`test_nothing_in_this_app_imports_apps_events` enforces both by AST — so the
dispatch brief's "import the constant" is not available, and copying it was the
one thing the brief ruled out. The header *name* is the single literal (a door
cannot ask "is this header present" without one) and a test pins it to the
signer's own constant. *Rejected*: **a per-connection tolerance flag** (a knob
nobody has needed is a knob somebody sets to a year the first time they see a
stale-delivery log line; the promotion trigger is already recorded on the
constant); **a local tolerance constant in `connections`** (two five-minute
numbers agree the day the second is typed and disagree six months later inside
somebody's verifier — the drift this design exists to prevent); **a nonce or
delivery-id cache as the replay control** (it makes replay a storage problem
with a retention window and an eviction policy, refuses nothing older than the
cache, and the `(connection, delivery_id)` dedup we already have is a
*provider's* claim about identity, not a proof of freshness); **fixing it in
`apps/comms`' provider-verifier registry** (that seam is for schemes a *vendor*
decided — an ESP signs the way its vendor signs — and this scheme is ours, so
putting it there would make the house scheme optional and per-provider);
**a static import of `apps.events.receivers`** (above). *Trigger to revisit*:
the contraction of `X-Signature` on this door — dated **2027-02-24** in a comment
beside the v1 branch, or earlier at the first of (a) every provider a product
here receives from sending `X-Signature-V2`, and (b) `scripts/mail_demo.py`
moving off v1, which this ADR deliberately does not touch (follow-on: the
demo's leg 6 gains the replay assertion when it signs v2). *Numbering*:
`connections-2` is the next free number — `connections-1` is cited in
`apps/connections/services.py`, `apps/events/receivers.py` and the connections
tests but was never written into this file, and that gap is left as a hand-up
rather than renumbered here. *(Hand-up closed by the bookkeeping
entry above: the number is reserved and its ruling is cited to the docstrings
that hold it. Nothing renumbered.)*

**ADR ident-7 · scoped API tokens: the credential carries a
ceiling, and the ceiling is derived.** *Context*: the owner's ruling
(design-agreements.md): the platform's
posture is bring-your-own-agent through `/mcp`, so tokens are handed to
third-party agent runtimes as ordinary practice — and today an `ApiToken`
carries the full power of its person. An early persona walkthrough minted exactly such a token and
drove the whole arc on it, which is the practice the ruling names.
*Decision*, in seven parts. **(1) Two filters, never two truths.** A token's
`scopes` are a CEILING checked at the doors; the person's `Membership.role`
and each app's `policies.py` keep deciding underneath, untouched. Effective
capability is the intersection: the ceiling can never grant — a token scoped
`core:write` held by a `member` is still refused by the escalation wall, and
the wall's refusal is the one the caller sees (rule 29's spirit at the
credential layer: nothing a token holds exceeds its person, by construction,
because ∩ never widens). Scopes are read in exactly two seams — the REST door
plumbing and the MCP mount — and **nowhere below**: a service, selector or
policy that consults `token.scopes` is the second permission system this ADR
exists to refuse (the quality batch's rule, id PM-assigned, closes the class).
**(2) The vocabulary is derived, never enumerated.** A scope is
`<family>:<verb-class>`. The family population is the discovered `TAGS` keys —
the same discovery that already builds `INSTALLED_APPS`, the mounts and the
OpenAPI tags section — so a product that adds an app with a tagged router
gets its scopes for free, no registry edited. The verb classes are exactly
two, `read` and `write`. Per REST operation the derivation is total and
unambiguous by machinery that already exists: every operation carries exactly
one tag (the one-tag-per-operation gate clause is what makes this a
function, not a relation) and its method classifies it (GET/HEAD → `read`,
everything else → `write`). Per MCP tool: the tool's REST twin's scope, off
the same introspect registries rule 17 already diffs; a tool with a recorded
parity exemption classifies its own `<nouns>.<verb>` name against the two
declared grammars (selector `get`/`list` → `read`; rule 16's service-verb
lexicon → `write`); a tool or route whose scope cannot be derived is a
finding, never a fallback. **No per-route annotation exists** — there is
nothing to annotate and therefore nothing to drift. **(3) The tag key is now
wire vocabulary.** It sits under the renamable display name exactly as D10
prescribes — immutable key, renamable label — and renaming a key after launch is
a credential-breaking change of the same class as renaming a URL (the
versioning argument). **(4) Enforcement at the doors, both, before the
service runs.** REST: one check in the door plumbing (`config/api.py`'s
territory), after the token resolves and before the view — never in a route.
MCP: inside `core.mcp.tool_call`, the one contextmanager every tool already
enters. The refusal is a NEW registered code, `insufficient_scope`, E9's
grammar at import: the fact names the missing scope in a plain sentence, the
structured remedies name the mint door, and `wire_refusal` composes the one
body both doors send — byte-identical, rule 17's spirit. **An out-of-scope
tool refuses when called and never disappears from `tools/list`** (GitHub's
shape, not Stripe's): the list is the agent's map and each entry's rendered
description carries its derived required scope, so a narrow agent can still
tell its human "mint me `widgets:write` and I can do this" — hiding would
amputate the remedy channel and stand up a second enforcement point that can
disagree with the call-time check; and tool existence is public in
`llms.txt`, so there is no existence oracle to protect (the not-found
collapse protects rows, not the catalogue). Sockets: the bearer socket narrows **per frame** in the bridge — a frame is pushed only if
the ceiling holds `read` on some family of the app that declared the event
(the event name's `<app>` segment, a declared population), the kick group
untouched because a kick is an instruction to hang up, never a payload.
**(5) Compat and the default.** `ApiToken.scopes` lands expand-only (rule
22): a nullable JSON list where **NULL means unscoped** — the full power of
the person, the grandfathered meaning of every pre-scopes row, forever
(expand-only cannot rewrite the meaning of existing rows; revocation is the
remedy for an old broad token). An **empty list is refused at mint** — a
token that can do nothing is a mistake, not a ceiling. For NEW mints the
recommendation — **flagged for owner ratification, with the alternatives
below** — is *required-explicit*: the mint doors (`POST /api/v1/tokens/` and
`manage.py issue_token --scope`) take a scope list with **no default**, and
`*` is the explicit spelling of "no ceiling", so a full-power token is a
choice somebody made out loud. This breaks the mint route's request shape,
a deliberate early break — the only cheap moment — and is
recorded as the E5 exception it is. **(6) Orthogonality, stated.** The tenant
pin (`ApiToken.tenant`), the `X-Org` hat, `visible_to`, `may_be_named` and
the policies are all untouched: pins and hats narrow *which rows*, scopes
narrow *which capability families*, roles and policies decide *whether the
person may* — three narrowings that compose by intersection and never
substitute for each other. Minting is not bounded by role on purpose:
evaluating "which families may this role reach" at mint time would be the
second truth, drifting from the live role the moment it changes — a ceiling
wider than the grant is harmless because the grant still decides. **(7) The
docs are derived** (rule 41's machinery): every operation's published
description carries its required scope, the mint operation documents the
vocabulary off the same discovery, and `llms.txt` tells an agent which
scopes to request per family — zero hand annotations anywhere. *Rejected*:
**policies.py action names as the vocabulary** (a second permission system by
construction — a scope `invoice.void` beside a policy `invoice.void` will be
assumed equivalent and will drift; and reads mostly have no action name, so
half the surface would derive nothing); **service names / rule 42's census**
(internal vocabulary on the wire — the plain-language ruling forbids it; a
service rename becomes a credential break); **per-operation scopes** (the
vocabulary scales with the route count, agents must request dozens, and a
new route lands outside every existing ceiling — family×verb keeps route
growth additive, E5's own shape); **app-label families** (the exact same
finding: internal taxonomy on the wire); **a third `admin` class** (not
derivable — hand classification of which writes are "admin" is the
enumeration this ADR forbids; the privileged surface is already its own
family where it matters, and the role underneath is the real guard);
**hiding out-of-scope tools** (Stripe's shape — see part 4); **default-full
minting** (the path of least resistance re-arms the exact hazard the ruling
names); **default-narrow minting** (some hand-chosen "safe" subset nobody
stated — a default that grants anything is worse than a refusal that demands
a choice); **mint-time role bounding** (part 6). *Trigger to revisit*: the
MCP OAuth 2.1 upgrade (the vocabulary survives as OAuth scopes; the
transport changes); a product wanting per-object grants (that is
roles/policies territory, never scopes); noun-level socket narrowing when
one app's families diverge in sensitivity.

**ADR ident-8 · 2026-09-07 · the sign-in posture is deployment
configuration, materialised through the one identity door.** *Context*: the
hosted login shipped with self-registration allowed, no lockout and public
organisation creation open on every environment (measured live before the
rung: `allowRegister: true`, no `maxPasswordAttempts`, `GET
/admin/v1/restrictions` = `{}`, `/ui/login/register/org` serving a working
form), against ADR ident-4's rejection of open signup. *Decision*: three
settings read from the environment (`ZITADEL_ALLOW_SELF_REGISTRATION`,
`ZITADEL_ALLOW_PUBLIC_ORG_REGISTRATION`, `ZITADEL_MAX_PASSWORD_ATTEMPTS` —
the NIST SP 800-63B ceiling, a product tightens it), materialised by
`zitadel_seed` through full-body `ensure_*` writers on the admin API and
reconciled by `zitadel_audit` (drift is exit 1 naming the remedy); the compose
`DEFAULTINSTANCE_*` keys carry the same values for a fresh instance and are
the belt, never the mechanism — they apply at instance creation only, and the
belt may be tighter than the mechanism but never looser. Every writer declares
the resource's full field set beside itself, read from the running build's
API document, and a census test refuses a body that is a strict subset (the
convention that closed the two partial writers that already existed: the
label policy, five fields short, and the OIDC provider's `usePkce`).
*Rejected*: an intent row plus workflow kind (a runtime door for a value no
runtime persona holds — cost without a reader); compose keys alone (every
existing instance stays open). *Measured at landing*: the instance-level write
closes every org without a policy of its own, which is every org a fresh
clone creates; on the shared laptop instance the org's own login policy had
already been closed by a sibling product, so the door that visibly moved was
public org registration, 200 → 404. *The org-level half, settled 2026-09-07*:
`zitadel_seed` reconciles the credential's own org's login policy **only where
that org has a policy of its own** (`isDefault` absent on the management `GET`)
and leaves an inheriting org inheriting, because creating one would fork a
value into two owners and make every later instance-level change silently not
apply here (first principles 9); `zitadel_audit` judges that org's
`allowRegister` where it is the org's own and defers to the instance verdict
where it is not, so one console edit is one disagreement. Measured on the pinned
build: `PUT /management/v1/policies/login` on an org with no policy of its own
answers `404 Org-M0sif`, so the branch is the API's own shape and not a
preference; and on the shared instance the org's `allowRegister` alone decided
whether `/ui/login/register` served a working registration form or an error
page. *Trigger to revisit*: the first product that wants per-tenant
registration or lockout policy — then the row shape, with the audit comparing
against the row.

**ADR ident-9 · 2026-09-07 · the first identity has a door of its own, and it
shuts behind itself.** *Context*: with self-registration closed (ADR ident-8) a
deployment without a workforce IdP has no way to its first identity but the
Zitadel console or the `FirstInstance` admin — measured from zero on a sibling
product at twenty-one minutes, every step of it read off somebody else's admin
UI; and `bootstrap_tenant` needs a `User` that only a first sign-in can mint.
*Decision*: `manage.py zitadel_first_admin --email <address>` mints a
credential-less Zitadel human and an invitation code through the existing
`accounts/zitadel.py` writers (`ensure_invited_user`, `create_invite_code`,
`invite_url` — no new writer) and prints the hosted set-password link and the
two steps after it: sign in at the product so the adapter mints the `User`, then
`bootstrap_tenant --email`. It writes no row of ours and no audit entry —
nothing of ours changed, and the birth certificate stays `bootstrap_tenant`'s
audited write (ADR core-17). **It refuses once any tenant exists**, so
`core.services.invite_member` through REST and MCP is the only invitation path
from the first member on; it also refuses an unconfigured platform, a loopback
`PUBLIC_BASE_URL` outside DEBUG (the printed steps would be a dead end), and a
`--email` that is not an address. The code is printed once and is in no log line
and no row (`returnCode`, never `sendCode`: house rule 25 gives the product one
sender and Zitadel is not it), the precedent being the client secret
`--rotate-web-secret` prints. A federated deployment needs no command: first
sign-in through the workforce IdP, then `bootstrap_tenant`. *Rejected*: the
product's invitation workflow at zero (it needs a tenant, an actor, a running
worker and a mail path before the first human exists, and lands on the same
undriven hosted last mile); `bootstrap_tenant` creating the Zitadel human
(`core` may not import `accounts.zitadel` — house rules 7 and 27); a
dev-user-shaped account with a password we choose (a credential we transport —
`ensure_human_user`'s own docstring says why not); documenting the console path
only (the wall stays); an option on `zitadel_seed` (that runs on every
`setup.sh`, and a once-on-purpose act with a credential on stdout is its own
command); a `--force` on the tenant-exists refusal (the product has an
invitation door; a force flag is a second one). *Trigger to revisit*: the first
product that federates at birth and never runs this command — then it is
deleted, not kept; or the hosted invite page becomes driveable headlessly, at
which point the command's printed steps can be verified by machine instead of
by a person once.

**ADR ident-10 · 2026-09-15 · a domain claim routes nothing until verified.**
*Context*: R2 (the sign-in surface review) F1 — any tenant admin claimed any
domain and the platform sign-in routed on it: a lockout (a person elsewhere
refused by a foreign claim) and an absorption (a stranger landed in the
claimant), both confirmed over the wire. *Decision*: `SsoDomain.verified_at`,
set only by `verify_sso_domain` (an operator's audited act through
`manage.py verify_sso_domain`, permission `sso_domain.verify`); `for_domain`
honours verified rows only; a claim reserves the name unverified; public mail
providers are refused at the door by a declared knob
(`SSO_REFUSED_MAIL_DOMAINS`) whose list is a courtesy, not the wall.
*Rejected*: DNS TXT verification now (a resolver dependency and a workflow for
a population of zero — the trigger is the first product wanting tenant
self-serve, at which point the same service is the seam the activity calls); a
backfill marking existing claims verified (grandfathers the hole). *Trigger to
revisit*: that self-serve product; or a second verification road, which is
refused as a second writer.

**ADR ident-12 · 2026-09-19 · every Zitadel session the sign-in seam opens,
it closes — except the one a client is about to spend.**
*Context*: two things made this an ADR of ours rather than a comment. First,
the rule itself has been cited in this tree as "ADR ident-10" since rung A3 —
`apps/accounts/signin.py`, `apps/accounts/zitadel.py`, `apps/accounts/views.py`
and `apps/accounts/tests/conftest.py`, eight comment lines — but **ident-10
here is the domain-claim ADR**; the session rule is the CONSUMER's ident-10,
which design I-A §J5 cited with the qualifier and the code dropped. Those
eight citations should read ident-12 and do not yet (A11's territory reached
one of the four files; the correction is booked, not done). This ADR is
**ident-12 and not ident-11** for a second reason worth a line: house rule 57
cites "ADR ident-11" and no ADR of that number is written anywhere in this
file — a dangling citation older than this ADR, booked with the eight above. Second, rung A8
found a case where the rule cannot hold. *Decision*: `apps.accounts.signin`
opens a Session API session per ceremony and closes it at EVERY exit — the
refusals, the outages, the person's *Never mind*, and a second `begin` over a
ceremony already in flight — so a half-authenticated session is never left on
the identity platform for a person who did not finish. `_forget` is the one
place that closes, and every road leaves through it.

**SIGNED by the owner 2026-09-19 ("sign all three", recorded by the PM).** *The amendment*: on the Mode A
road (design C-10), a ceremony that FINALIZED an OIDC auth request leaves its
session open to the platform's own lifetime. *Which principle bends*:
principle 18 (least privilege, minimum necessary lifetime) and this ADR's own
rule. *Why the default is insufficient*: MEASURED on v4.17.1, 2026-09-19 — the
finalize answers a callback URL carrying a code, the CLIENT spends that code
afterwards on its own connection, and Zitadel validates the session the code
was minted against at that moment. With the session closed on our way out the
exchange answers `400 invalid_request "Errors.Session.Terminated"`, so the
person is signed in nowhere and the app that sent them gets an error, after a
sign-in that is perfect from both ends. *Alternatives*: close the session and
have our server exchange the code (a second token road, and the client's own
PKCE verifier is not ours to hold); delay the close behind a timer (a thread
or a workflow for a ten-minute object on somebody else's server, and the
client's timing is not knowable); keep it and accept the risk, which is this.
*The risk*: an authenticated session exists at the identity platform that
nothing of ours will close. *The mitigation, and why the risk is small*: the
session TOKEN is the only handle on it and never leaves the process — the
ceremony holding it is deleted in the same call — and M7 measured that the
browser is left holding a device cookie and no session, so a second authorize
with `prompt=none` answers the sign-in page rather than a code. The session
expires on the instance's own clock. *Reversal*: one argument to `_forget`;
`test_a_finalized_session_is_left_for_the_client_to_spend` and
`test_every_other_road_still_closes_its_session` are the pair that would flip
together. *Trigger to revisit*: a Zitadel build that validates the session at
FINALIZE time instead of at exchange time (the measurement kit's M3 is the
line that would notice), or a deployment whose session lifetime is long
enough that an unclosed one is worth an operator's attention.

**ADR accounts-1 · the invitation provisions the person; there is
no signup door.** *Context*: an early from-zero persona walkthrough had one step with no door at
all. `/accounts/signup/` 404s, the login page rendered a heading
and nothing under it, `bootstrap_tenant`'s advice told an operator to run
`seed` — which makes a tenant and so destroys that command's own precondition —
and the field test ended up at `createsuperuser`: no service, no audit row, no
tenant. The invitation email, meanwhile, carried no link anybody could act on;
it pointed at that formless login and offered a signup that does not exist. It
worked for scripts, because the API hands the token back to the *inviter*, and
was a dead end for every invited human. Rule 42 could not see any of it: it
walks `@service` definitions outward to doors, and **a job with no service is
an absence, not a doorless service** — the census read accounts at zero while
the product had no way to create a person (that blind spot is now declared in
rule 42's `does_not_cover`). *Decision*: **no standalone create-account; the
invitation is the door.** `core.services.invite_member` writes its row and, on
commit, starts `ProvisionInvitedPersonWorkflow` under a deterministic id keyed
on the invitation's primary key. Its first activity makes the person real in
the identity platform through the rule-27 door — Zitadel's v2 `AddHumanUser`
with **no password**, search-then-create idempotent, then `CreateInviteCode`
with `returnCode` — and its second activity is the existing generic
`send_email`, so the message still travels rule 25's one allow-listed sender
and Zitadel mails nobody. The email's primary link is the credential-setting
page, whose shape was measured by fetching it against the pinned build rather
than read off a doc page. A person who already signs in here gets the
sign-in branch instead, because `CreateInviteCode` refuses an initialized user
and that refusal is an ordinary outcome, not a fault. Membership is still ours:
`accounts.adapter.accept_pending_invitations` matches our row at sign-in.
*The tension, named rather than waved past*: **the invite code crosses Temporal
history**, inside the link, for as long as retention says — and `core.mail`'s
own docstring has always said the invitation carries no credential *because* a
bearer token in a payload is a bearer token in history. That reasoning stands
and this is genuinely different in kind: our token authenticates a person to
everything they can reach, for its whole life, silently. The invite code is
single-use, short-lived (three days, measured off Zitadel's own secret
generator, which is also the number the email states), superseded the moment
another is issued, and it opens exactly one screen — the one where somebody
with no password chooses one. It reads nothing and grants no membership. The
rule it does not license: our own credentials still never enter a payload.
*Rejected*: **`sendCode`** and letting Zitadel mail the invitation (a second
sender that knows nothing of consent, quiet hours or suppression — rule 25
bypassed, and wording no test of ours can read); **open signup / Zitadel hosted
registration** (a product may turn it on as *its* choice; the platform will not
ship a door that creates people nobody invited); **a `zitadel_user_id` column
on `Invitation`** (idempotency is search-then-create against the identity
platform, which is the authority — a column would be a second copy of its
answer and a migration this ADR does not need); **rewiring delivery to
`comms.send()` here** (the substance the queue row asked for is that
*we* deliver and Zitadel does not, and that is kept; the `core.mail` →
`comms.send` rewire is ADR comms-2's named follow-on and keeps its own row, so
the rule-25 ratchet stands unchanged at one rather than moving under a rung
that is not about it). *Trigger to revisit*: Zitadel routing `/v2beta` or
moving the login UI off `/ui/login/user/invite` (both are pinned facts here,
measured, and `zitadel_audit` is the tripwire); a product that wants open
registration; the comms rewire landing, which is when the delivery half of this
ADR is restated in comms' terms.

**ADR core-20 · a grant comes from where you sent it: an
invitation records its landing node.** *Context*: the owner's ruling —
"Agree — comes from where you sent it. Don't elevate out of context."
`Invitation` carried no organization at all, so `invite_member` asked both its
authority questions at `root_organization(tenant)` and `accept_invitation`
landed the membership at the root, whatever hat the inviter was wearing. That
was wrong in two directions at once, and a direct measurement against the
tree — rather than argument — showed both: an owner acting under a branch's hat had a grant
land at the ROOT — reaching further than the context it was sent from, with
nothing in the request saying so — and a branch admin, who administers a branch
and nothing above it, was refused outright ("You may not invite people into this
tenant", from a `require` at a root they hold nothing on) and so could not
invite anybody into their own branch. One defect, not two: the landing node was
a constant where it should have been the context. `add_membership` with
`organization` omitted had the identical shape one door over. *Decision*:
`Invitation` is an `OrgScopedModel`; `organization` is the **landing node** —
the acting hat at grant time — written on the row. Every authority question is
asked AT that node: issue (`require(actor, "invitation.create", where)` and
`_refuse_escalation(organization=where)`), supersede, revoke (`may_be_named`
then `require(..., invitation.organization)`), and the reads, which chain
`.visible_to(org)` like every other org-scoped read. The accepted membership
lands exactly there. **An omitted placement is the ACTING HAT and never the
root**, through `_landing_node(...)` — the one seam BOTH grant doors ask, so
`add_membership` and `invite_member` cannot come to mean two things one service
apart; the root survives only where there is nobody acting (`create_tenant`,
`seed`, `accept_invitation`'s own call), because a tenant's first membership is
the whole tenant by definition. Pending uniqueness is per `(tenant,
organization, email)`: two branches may each have a live offer out to one
person, because they are offers of two places, and the tenant-wide form let one
branch silently withdraw another's. **No refusal on any of these paths names a
branch** — the accept conflict names the tenant — because telling not-there from
not-yours apart is how a caller maps a subtree they hold nothing on. The
property that makes the whole change safe, in one sentence: **a caller can only
ever be surprised narrower**; the landing node is always at or below the hat and
there is no input that widens it. A flat product (hat == root) is byte-identical
and that is asserted, not claimed. The migration is expand/contract in rule 22's
order and reversible at every step — constraint off, column nullable, backfill,
required, per-node constraint — and its backfill is a reading of history rather
than a default: every existing row predates placement and already MEANT the
root, so the root is what those rows are written down as. *Rejected*:
**docs-only honesty** (write down that invitations land at the root and call the
surprise documented — the branch admin still cannot invite into their own
branch, and the elevation is still silent); **root-as-default** (an omitted
placement going on meaning the root, which is the elevation itself wearing a
name); **org-in-the-accept-payload** (letting the accepter say where they land —
the placement is not theirs to choose, it was decided by whoever invited them
and bounded by what *they* could reach, and a field a caller can send is a field
an impersonation shape can send; accept stays session-only, ADR core-16
unchanged). *Trigger to revisit*: a product that needs an invitation to land
somewhere the inviter could not reach (a delegated-onboarding shape, refused by
construction today — the way in is a service that names the granter's own
ceiling, never a wider default); the granter-lost-role-before-accept window
becoming a real complaint rather than a declared one (it stays open by design —
refusing at accept hands the invitee a refusal they cannot act on, and it is the
same window `add_membership` already has); or a tenant deep enough that "one
pending offer per address per node" starts reading as a duplicate-invitation bug
rather than as two offers of two places.

**ADR core-21 · the addressing-header law: a header that was SENT
and cannot be honoured refuses; an OMITTED header falls back.** *Context*: the lead's ruling. `X-Tenant` and `X-Org` are **addressing** headers —
they say WHERE a caller is acting, where `Authorization` says WHO — and the
platform said three different things about one unhonourable value. The document
promised every authenticated route that "a tenant you hold no membership in
reads as empty rather than as forbidden"; the token-mint route promised a pinned
token "can only ever act in that tenant, whatever `X-Tenant` a later request
sends"; and the wire answered **401 `unauthenticated`** — "we could not tell who
is making this request" — over a live, unrevoked token belonging to a real
active user, `200 []` for an unpinned one, and the ROOT bill
for an `X-Org` that was sent empty (curl's `X-Org;` form). Three answers to
one question, and the 401's fact was simply false, which E9's grammar refuses.
*Decision*: **the pin promise's substance wins, generalized as the direction
already ruled for `X-Org` and driven green across six hat shapes.** A
SENT addressing header that cannot be honoured for this credential is refused —
authenticated, **then** refused, with the registered code
`addressing_header_not_honoured` at 403. An OMITTED header still falls back to
the default membership, untouched, so a well-behaved client sees no change.
**Sent means sent, empty included**: `""` and whitespace are values a caller put
on the request, not an absence, and the trim-and-lower boundary is declared in
the header's own published description. **Foreign, nonexistent and unreachable
are one byte-identical answer** — the refusal fires because the slug is not one
this credential can act in, never because of what exists, and it names the
header and never the slug, so it is no oracle over the estate. Not-there ≡
not-yours governs resource identifiers; a caller's own addressing header is the
caller's assertion, and refusing it leaks nothing they did not assert. *Where it
lives*: `core.middleware.addressing_refusal` — one function, asked by every
door, after resolution and before anything is read. `resolve_tenant` and
`resolve_org` stay resolution and answer `None`; `authenticate_token` answers WHO
and returns a pinned token's own tenant whatever was asked for, because a door
cannot say "authenticated, then refused" about a credential that failed. The
REST seam is the `_run_checks` wrap that already holds the token ceiling, the
MCP seam is `TokenAuthMiddleware`, and **both compose the same body through
`wire_refusal`**, so the two doors cannot come to disagree. The socket doors
refuse by closing the handshake (`CLOSE_NO_TENANT`), because a websocket
handshake has no body to carry a refusal in. **Zero per-app door edits**: the
population is every authenticated operation, derived, and the published
`x-refusal-codes` follows the same `authenticated` fact the two header
parameters do. *Rejected*: **empty-read** (the other direction — it would reopen
what was already closed and keep the misconfiguration-masking class this platform refuses); **the quiet pin** (a pinned token silently answered as its pin, which is
"somebody else's data under a different name" with extra steps); **two codes,
one per header** (the failure is one failure and a client would write the
handler twice; which header is in `detail`, the half that varies per request);
**echoing the sent slug in the body** (harmless in itself, since it is the
caller's own assertion, but it would make the foreign and the nonexistent
refusal two different bodies and lose the anti-oracle pin); **a per-app guard**
(what `apps/usage` had, and it stripped before it checked — exactly the
defect one app's copy of a platform law produces). *Trigger to revisit*: a door
that must accept an addressing header it cannot honour (none is known); or a
product whose clients genuinely cannot stop sending a stale header, which is a
migration conversation and not a change to the law.

**ADR platform-lifecycle-1 · 2026-08-24 · machinery durability follows the
identity's declared lifetime class.** *Context*: the owner's escalation of
2026-08-24 — a second strike on the same leak, asking for "an elegant,
comprehensive solution instead of band aids". The diagnosis is not a missing
reaper: it is a **lifetime-class mismatch minted at creation**. A Temporal
Schedule is infinitely durable by construction, and every worker keys one to an
identity that is ephemeral by construction — the checkout-path hash inside the
task queue name (`scripts/db.sh`). Durable object, mortal identity, and the
census on the owner's machine measured what that produces: **36 orphaned
schedules and 134 stranded executions** pointed at queues no worker has polled
for weeks. The decisive observation is that each of those schedules only ever
delivered work while its checkout's worker was alive anyway — so in a
checkout-derived environment the durability buys nothing except the leak, while
in a real deployment it buys catch-up across a deploy gap and a missed run that
is a fact rather than a silence. *Decision*, in four parts. **(1) The class is
declared, never derived.** One setting,
`TEMPORAL_MACHINERY_LIFETIME: "deployment" | "process"`: `deployment` is the
current code path bit-for-bit (durable Schedules the server owns) and is what
`config/settings/production.py` declares; `process` creates **no Schedule object
ever**, and is what `local` and `test` declare. In `process` mode the live
worker starts the same sweeps itself — once at startup, which is the catch-up
run, and then on each declaration's existing cadence for as long as it lives —
under the existing deterministic ids, with `TERMINATE_EXISTING` superseding a
stale open run rather than failing or skipping; and worker startup **deletes
this checkout's own** previously-created durable schedules, only `NOT_FOUND`
swallowed and every real deletion logged (`drop_legacy_purge_schedule`'s
reasoning, generalised). Environment is distinguished by declaration and never
by name: there is no branch test, no checkout-name test, no worktree heuristic,
and the seam is scanned for one. **(2) The declaration is data.** An app's
`SCHEDULES` entry is a `core.schedules.ScheduleDeclaration` — an id builder and
a `Schedule` value — and one generic engine (`apps/workflows/client.py`)
consumes it: apps declare *what*, the engine decides *how*, and both classes
read the workflow, its argument, its id and its cadence off the one declared
value so they cannot drift. **(3) The destroy half is a registry** (house rule
20's declared-population logic applied to machinery): every class declares name,
identity grammar, enumerate, liveness evidence, destroy and a warm-cache flag,
behind one entry point with the four-verdict grammar promoted frame-wide from
`db_sweep.sh` — live / IN USE / FOREIGN / REFUSED — and one shared live-checkout
enumerator. An enumerated instance matching the identity grammar that no
declared class claims is **exit 2**: could-not-judge outranks a pass, so
machinery class N+1 fails the day it first exists. **(4) The gate leg is
own-tree only.** The full gate gains a post-suite census over the instances *this
checkout* created; the machine-wide census stays out of the gate and in the PM's
standing pre-wave reap. *Rejected*: **worker-shutdown deletion** (SIGKILL, OOM
and a laptop lid leak it entirely — and in production it would delete a peer
instance's schedules, which is a worse failure than the one it fixes);
**TTLs on schedules** (age is not liveness — a reaper wearing create's clothing,
and it would reap a healthy deployment's quiet sweep); **one shared dev queue**
(the cross-checkout hijack class, re-armed: the last worker to start silently
owns everybody's sweeps); **reap-harder-with-durable-everywhere** (the band-aid
at strike three — a third reaper for a class of object that should not have been
created); **machine-wide red gates** (my verdict coupled to your corpse; FOREIGN
requires an operator by design, and a gate reddened by somebody else's garbage
trains people to override the gate). *Trigger to revisit*: the first
`deployment`-class environment whose queue identities become **per-instance**
(a per-pod suffix, a blue/green pair) — that deployment's identities are
ephemeral and its declaration should change with them; or the
unrecognised-shape exit 2 firing, which means a machinery class exists that
nobody declared.

**ADR platform-extension-1 · a product extends the system layer by DECLARING
beside it, never by editing it.** *PROPOSED 2026-09-21 — the owner chose this
shape; the signature lands at CLOSE.* *Context*: the first
consumer's fold of v2.1.0 cost 94 merge conflicts, 21 of them inside
`scripts/ quality/ .github/`, and twelve commits whose entire content was
re-applying local edits to template-owned files; the worst was silent in the
wrong direction — an 1800-line template file fast-forwarded byte-identical and
took 1826 product lines with it, with no conflict to read. Every one of those
edits was a product-owned CONCERN with no seam to land in. *Decision*: every
extensible template directory has a `local/` sibling the template's own reader
discovers and the template NEVER ships (`publish.sh` § R0, which refuses a
tracked `**/local/**` or `*.local.md` at exit 2) —
`scripts/local/{legs,drives,fold.d,lifecycle.d,hooks}/`, `quality/local/`, and
a `.local.md` sibling beside a template document that carries a per-product
list. A declaration carries a versioned header; ABSENT is byte-identical
behaviour and MALFORMED is exit 2, never a quiet skip. The per-path ownership
classes land in `docs/product/build-contract.md` § Ownership, and an edit to a
template-owned path is a divergence `scripts/divergence_census.sh` refuses
unless the product's own `architecture.md` names it. *Rejected*: a
`pyproject.toml` registry of legs (a shared file no rung may edit, and the
declaration would live away from the thing it declares) · fork-and-rebase
doctrine (it re-pays the conflicts every release, grows with the product's age,
and git's worst case here was the SILENT one) · a `ci.local.yml` (not a GitHub
primitive; a second workflow file is already conflict-free) · a sourced
`check.local.sh` that may redefine functions (a judge, not an instrument —
check-v1's law) · a `template_sync.sh` now (its trigger, three products, has
not fired). *Trigger to revisit*: a second product's fold shows a seam these
six miss, or three products exist.
*AS BUILT 2026-09-21*: house rule 60 carries the decision in three
canary classes, and the fenced `drawers` block in
`docs/product/build-contract.md` is its ONE reader. **(a)** a product edit in a
template-owned path → `scripts/divergence_census.sh`'s exit-1 finding, by path.
**(b)** the table against the tree: a drawer the template's own code opens with
no row, a row whose reader is not here, a row whose case its drive does not
define — each a finding at every gate, the population of drawers DERIVED from
the `local/` paths the code spells rather than typed beside the table. **(c)**
at `--selftest`, one planted item per drawer, run through the drive case the
row names (`--case`, the seam every drive under `scripts/tests/` now carries),
so a reader that opens its drawer and ignores what is in it is exit 2 naming
the drawer and the reader. A `held` row reserves a name for a rung that has not
landed and is printed as held; it becomes a finding the day a template-owned
file opens it.

**ADR platform-lifecycle-2 · one mechanism, one rung, two apps.**
*Context*: the fix changes the `SCHEDULES` seam in `apps/workflows` (which owns the
engine) and in `apps/events` (which is its only other declaring client), and the
schema discipline's default is one app per rung. *Decision*: the exception is
taken deliberately and recorded here — it is **one mechanism**, `apps.workflows`
owns it and `apps.events` is its declaring client, and the two halves are a
single seam whose two sides cannot be typed independently (the shape lives in
`apps/core/schedules.py`, below both, because `import-linter` holds the platform
apps independent of one another). Migrations: zero, so the collision the
discipline exists to prevent is not in play. *Rejected*: **two rungs**, which
would carry the declaration shape in prose across the gap between them and land
a tree in which one app declares against a seam the other has not built yet.
*Trigger to revisit*: a third schedule-declaring app — at which point the seam is
established vocabulary and a change to it is an ordinary one-app rung.


## Service architecture — the architect's rules

The engineering lead **loads `.claude/skills/django-architect/SKILL.md`** before decomposing and cites the rules it applied in every criteria set. The skill is the long form; house rules 11–26 above are the gate-enforceable subset. The lead's two deliverables before any code: **an app map** (nouns, dependency arrows, doors each exposes, workflows each owns) in the product's `architecture.md`, and **an ADR line** (context · decision · rejected alternatives) for every cross-app decision.

Boundaries: an app is one domain noun and its aggregate; dependency direction is `core` ← `accounts` ← platform (`workflows`, `events`, `connections`, `realtime`) ← domain; a domain app never imports another sideways — it emits an event or declares a dependency on its `AppConfig.depends_on` in the same rung; split when the second aggregate appears, never at a size.

Authorization — **both layers, with a clear division**: the door authenticates and resolves the tenant; the service authorizes, object-level, via `core.authz.require(actor, action, obj)`, and every scoped read asks in its selector. **The vocabulary is one shape, `<kind>.<verb>`**: every first-party model is a kind (`authz_kind`, derived from the class name, overridable), every kind carries `create/read/update/delete` by derivation, every other verb is a status transition or compound act declared on a kind in its app's `ACTION_PROSE` with its sentence, and one reserved verb, `tenant.own`, belongs to ownership. **Three layers, one owner each**: `owner`, the one platform role, IS the vocabulary; every other role is declared in an app's `roles.py` with a pattern collection (`apps/core/roles.py` ships `admin` and `member` and is the one product-editable file in `core`); a tenant's data is `core.Role` (custom roles), `core.RolePermission` (include/exclude deltas and custom collections, keyed by role key), `core.Grant` (one person's `allow` or `withhold`, withhold winning). `Membership.role` names a role by key and inherits downward as memberships do. `require` evaluates at the node the object names, answers no to anything outside the vocabulary, and composes `holds AND predicate`. **Nobody hands out what they do not hold and nobody takes back what they do not hold**; the root always keeps one un-withheld owner. Rule 13 proves a service asks for the kind it writes; rule 54 proves the vocabulary derives, the rows name it, and the reads ask.

API contract: `/api/v1/` from day one (`NinjaAPI(version="1")`); additive changes only — a breaking change is a `v2` router beside `v1`, declared by the lead; every list `@paginate` (**cursor**: `?cursor=` and `?limit=` ≤ 200, envelope `{items, has_more, next_cursor, count}`, `count` computed only for `?include_count=true` — ADR core-18, owner-ratified, which retired `page`/`page_size` outright on the licence of the empty consumer register), filters via a `FilterSchema`, `ordering=` from a per-route allow-list, `q=` for search, errors `{detail, code, errors?}` from the single mapper, UUIDs in paths; one schema per shape shared across the doors; an `Out` never exposes another tenant's identifiers.

**The index under that contract — ADR core-11 · context:** `BaseModel` shipped `created_at db_index=True` behind `ordering = ["-created_at"]`, so every concrete model in the tree inherited an index over the whole deployment's timeline while every supported read is tenant-scoped; under `LIMIT` the planner walked that index backwards and discarded other tenants' rows one at a time (an earlier measurement found 102,300 foreign rows examined per page at production-real scale, and 255,000 on `AuditEntry`). ADR core-18 made this *more* load-bearing, not less: the cursor seam extends every ordering with the pk, so a default page's total ordering is `created_at DESC, id ASC` and the signed keyset **is** that tuple — the ordering stopped being a display contract and became the coordinate system every cursor names a position in. **Decision:** `BaseModel` drops the bare index; `TenantScopedModel` declares `models.Index(fields=["tenant", "-created_at"], name="%(class)s_recency")` **once**, in its abstract `Meta`, inherited by `OrgScopedModel`; house rule 37 censuses every concrete scoped model for it, which is what closes Django's `Meta.indexes` shadowing hole (a concrete `indexes` list silently drops the inherited one); a `BaseModel`-only model decides per model and carries a named reader or an explicit none. **Rejected:** the three-column `(tenant, -created_at, id)` — it would serve the total ordering exactly and remove an Incremental Sort, but pays 16 bytes/row forever to sort timestamp groups that are almost always size 1, and does **not** make the keyset continuation sargable, because Django's expanded `_after` OR (`created_at < k OR (created_at = k AND id > k2)`) is the binding constraint and not the column set; `(tenant, organization, -created_at)` on the org-scoped half — killed twice over, since it was proven that no index moves the narrow-hat plan while recency ordering stands, and an org column in the middle breaks the tenant-wide walk for the root hat, which is the only hat a flat product has (architect rule A5: a flat product pays nothing); keeping both indexes (measured: the bare one buys only wrong plans and a per-insert write); per-app opt-in (the default is where the next model gets made). **Trigger to revisit:** a measured read that needs deployment-wide recency; a measured Incremental Sort cost at seeded scale, or a bulk-import path that stamps equal timestamps — either buys the third column then.

**ADR core-12 · unchanged · context:** no index fixes a narrow hat's recency-ordered page while that ordering stands — the lever is `eqjoinsel` over a join against a unique column that can carry no MCV correction (proven three ways), not an access path. **Decision:** the bound is **declared** in `docs/product/scale-envelope.md` with a per-hat rows-examined budget; the one live candidate — hat-scoped pagination, the subtree org-id `ANY` form, off-root only, COUNT first, with its own `(organization, -created_at)` index — is measured by a dedicated rung before any production code lands, and dies by measurement rather than by argument. CORE-11 deliberately did **not** smuggle it in: no index without a proven reader (house rule 30, pointed the other way). **Rejected:** extended statistics (per-table only; a unique join key never carries the MCVs `eqjoinsel` would need), planner hints (unshipped extension; pins plan shape in app code; harms the root hat to help the wide one), changing the list ordering (PM-refused — it is the product contract), keyset pagination as the fix (ADR core-18 landed it and it does not change page one's rows-examined; there is still no measured deep-page finding), denormalizing the org path onto scoped rows (cannot serve range **and** order from one btree, and makes `move_organization` O(subtree rows)). **Trigger to revisit:** Postgres cross-table statistics, or a measured product complaint that outruns the declared budget.

Concurrency: read-modify-write under `select_for_update` inside the service; no version column by default. Idempotency: `Idempotency-Key` on every write route (stored response replayed, tenant-scoped) and idempotent activities.

## Observability — one sink

**OpenTelemetry over OTLP to ClickStack.** Logs, traces and metrics from the web process, the worker and every door go to the one `OTEL_EXPORTER_OTLP_ENDPOINT`; nothing writes anywhere else. `core/observability.py` is the only configuration point (SDK, resource attributes `service.name` = web|worker, Django/psycopg/Redis/httpx/Channels instrumentation, Temporal `TracingInterceptor`, structlog → JSON with `trace_id`/`span_id`). `core/log.py` is the only logger. The `@service` decorator opens a span `<app>.<service>` and logs `.called`/`.failed` with the bound context; metrics are the OTel ones (route latency/status, service count/duration/failures, workflow/activity outcomes, outbox lag, delivery failures). Local: an OTel collector in compose fanning out to the **ClickStack all-in-one** container behind `--profile observability`; production: ClickStack at the endpoint.

## Traceability — three questions answered on every row

- **Request:** one trace from door → service → event → workflow → webhook (`traceparent` propagated, including into outbound webhook headers).
- **Session:** `session_id` (hashed Django session key · MCP session id · socket connection id) bound into context and set as the OTel `session.id` attribute, so one query reconstructs a session end to end.
- **Business correlation:** `correlation_id` (minted at the door) and `causation_id` (immediate parent) on every `Event`, `WorkflowRun`, `Delivery` and `AuditEntry`, carried in Temporal memo and `X-Correlation-Id` — the join key that survives restarts and days.
- **Audit trail, on by default:** `core.audit.AuditEntry(TenantScopedModel)` written by `@service` on every write — actor (`actor_user`, `actor_token`, `actor_kind` = human|agent|system), action (service name), object type + id, **door** (rest|mcp|socket|workflow|webhook|admin|shell), outcome, redacted input per `LOG_KEYS`, plus the three ids above. Append-only. Archival is a dated residual with a trigger in the product's queue. The column-by-column contract — which AU-3 content element each column answers, the actor semantics per door, the enumerated legitimate absences — is **ADR core-22** below.
- Convention (not gate): tests reference the criterion they prove, `@pytest.mark.criterion("C3")`.

**ADR core-22 · the audit row contract: NIST SP 800-53 AU-3 read
onto `AuditEntry`'s existing columns.** *Context*: the compliance reviewer is a
persona the BAAs make real, and an early probe found the trail
answering them by accident of service signature — `actor_user_id` None on every
row, mint rows missing `object_id`, failed calls naming no credential; every
column present, no contract saying what a conforming row is. The contract
vocabulary is **NIST SP 800-53 AU-3, "content of audit records"** — the
standards grounding owner-ratified directly ("agreed with your
recommendation"). AU-3's content elements are questions this table already has
columns for, so the standard is adopted as a **reading discipline, not a
migration: no new column is required**, and AUDIT-2's plumbing changes what the
existing columns are *handed*, never what they are. (Rules read against:
G2/G3 — the columns being contracted; D8/rule 20 — append-only grounds the
no-backfill ruling; E9 — the `error_code` vocabulary; 16 — the `action`
vocabulary.) The model is `apps/core/audit.py`; the one writer is the
`@service` decorator (`apps/core/service.py`); the mapping:

| AU-3 content element | `AuditEntry` column(s) | the reading |
|---|---|---|
| **type of event** | `action` | `<app label>.<service>`, built by the decorator from the function itself — the `@service` population IS the event vocabulary (rule 16's verb grammar), never a free string at a call site |
| **when** | `created_at` | UTC (`USE_TZ`), written once (`auto_now_add` on an append-only row); the recorded moment is itself a protected fact (an idempotent re-call never moves it) |
| **where** | `door` + `tenant` + `acting_org` | `door` ∈ rest·mcp·socket·workflow·webhook·admin·shell, bound into context by the door and read from nowhere else; `tenant` places the row's population — NULL is the declared platform population, ADR core-8 (b), never a loosening; `acting_org` is the hat the door resolved: which part of the tenant the call acted *as* |
| **source** | `request_id` · `session_id` · `correlation_id` · `causation_id` · `trace_id` | `correlation_id` minted at the door and never below (G2); `causation_id` the immediate parent; the join keys that survive restarts and days, riding the workflow headers and the Temporal memo |
| **outcome** | `outcome` + `error_code` | `ok`/`error`; on error the **registered** refusal code — E9's registry is the vocabulary, so every code on a row resolves in `introspect`'s refusals section |
| **identity of associated individuals, subjects, objects** | `actor_user` · `actor_token` · `actor_kind` — and `object_type` + `object_id` + `input` | who acted (the actor half; semantics per door below) and what was acted on (the object half; `input` redacted per `LOG_KEYS`) |

*Actor semantics per door — and there are THREE kinds, closed.* A **session**
call (REST session auth; the admin) is `human`: `actor_user` set, `actor_token`
None — a person clicked. A **bearer** call (REST or MCP; sockets when the
bearer path lands) is `agent`: `actor_user` AND `actor_token` set —
`actor_from_request`'s own doctrine, quoted: "the person authorised the machine
once, months ago, and 'a human clicked this' is not true of it." A
**workflow, schedule or shell** call is `system`: `actor_user` None
**honestly** — `system_actor`'s docstring is the text: "attributing an
overnight reconciliation to whoever happened to trigger the process last week
is how an audit trail becomes fiction." **Ruled: there is no fourth
"workflow" kind.** The `door` column already carries workflow-ness, and the
run rides `correlation_id`/`causation_id`; a fourth kind would split the
`system` population in two for no reader's benefit.

*The legitimate absences* — enumerated so a reviewer meeting a gap knows
whether it is the contract or a defect (five at authoring; absence 1
generalized and self-reports added, absorbing the AUDIT-2b rulings; the conditional admin placeholder that briefly stood as (vi) resolved
**removed** the same day — the L3 check found the seam present, so no absence
ever existed there; AUDIT-3-PRE):

1. **The population altitude.** A sweep acts on a population, not a row,
   and its one audit row is a **declared shape**, never a degenerate one:
   `object_type` = the swept model's label, `object_id` NULL — a blank label
   on a sweep's row is a violation, not a tolerated default (L6). **The
   count's home is the typed `Swept` result and the structured log line in
   the sink (G1) — deliberately NOT the row** (ruled at AUDIT-3-PRE):
   `input` is by contract the service's redacted *arguments* and the seam
   never sees a return value; a count without the row ids verifies nothing
   — the ids were ceded at this altitude on purpose — so putting it on the
   row would buy an unverifiable number at the price of either a
   one-row-class column on an append-only table or a second seam
   convention. Trigger to revisit: a compliance ask that requires the count
   from the trail alone — then the expand-only column, never a second
   valve. `accounts.erase_user` is the founding member: an
   erasure sweeps the person's credentials in one `.update(revoked_at=...)`
   and those deaths are audited as the one erasure row, the correct altitude
   for the action somebody took — "erase this person" — so the per-row
   absence is the contract, not a miss. The sweep services are allow-listed
   **by name** with this ground — today's census:
   `connections.purge_inbound_webhooks`, `events.purge_dispatched_outbox`,
   `events.purge_deliveries`, `exports.purge_exports`,
   `files.purge_pending_versions`, `workflows.purge_finished_runs` —
   and the membership AUDIT-3's rule checks is the list in `rules.yaml`,
   never this prose.
2. **Workflow-driven writes.** A service called from an activity records
   `kind=system`, `actor_user` None. The human cause is upstream at the door
   that started the run, and it is *reachable*, not restated: the causation
   chain joins the system row to the door row where the person is. This
   absence, like 1 and 6, is a **by-name census, never a shape** — the
   members take no `actor` kwarg at all, because machine work has no actor
   to take, and each carries its `# authz: machine-work` valve, held to it
   by AUDIT-2c's MACHINE_WORK census. Today's census (the rule-49 birth
   condition's find, 2026-08-26): `accounts.ensure_membership`,
   `events.enqueue_dispatch`, `events.close_outbox`,
   `events.record_delivery_attempt`, `events.dead_letter_delivery`,
   `workflows.record_run`, `workflows.finish_run` — and the membership the
   rule checks is the list in `rules.yaml`, never this prose.
3. **Platform-token actions.** A credential pinned to no workspace writes
   rows with `tenant` NULL — the declared platform population (ADR core-8
   (b), which this contract cites as the ground and now re-homes the
   citation of). Those rows are absent from every tenant's trail **by
   construction** — `for_tenant` can never see them — and the platform
   question is asked with the platform's own word, `for_platform()`.
4. **The shell door's person.** A management command's row is `door=shell,
   kind=system`, `actor_user` None — and that row IS the contract, not a
   defect: the box's own access audit (ssh) owns *who held the shell*, and
   this table does not duplicate an authority it cannot verify. What the row
   does owe — the door, the tenant acted on — AUDIT-2 threads explicitly
   (`system_actor(tenant=…)`), so the shape is deliberate, never defaulted.
5. **The pre-contract population, declared with its date and NO backfill.**
   Every row written before 2026-08-26 predates this contract — including
   the six live-stage revocation rows with `actor_*` None, and every
   credential death before the revoke ruling below, which was never recorded at all.
   None of it is backfilled, and the ground is structural, not
   preferential: `AuditEntry` is append-only (rule 20; the model's own
   `save()` refuses a second write), and **a backfill is an UPDATE on a
   ledger — forbidden by the very rule that makes the table evidence.** A
   trail whose gaps are dated and declared is evidence; a trail somebody
   helpfully completed is not.
6. **Self-reports.** A service whose subject is the platform's own state —
   the `announce_*` members — names no object: **empty object fields ARE the
   contract**, because there is no row the announcement is about; the
   announcement itself is the fact (L8). Allow-listed
   by name, membership post-L8-check — today's census:
   `example.announce_widget_onboarded`, `search.announce_degraded`,
   `search.announce_recovered` — and AUDIT-3's rule reads the checked list,
   never this prose.

*Outcome semantics — a refusal is filed as claimed (L11, KEEP as
capability).* A refused call's row (`outcome=error`) records the claim **as
the caller claimed it** — that is the capability, not a leak: "what did my
people *attempt*" is a question the compliance reviewer owns, and a trail
that drops refused attempts cannot answer it. No oracle opens: the pk in
`input` is the caller's own bytes returned to the trail, and E9's
`not_found` doctrine already refuses existence confirmation on the wire. Two
pins: the `error_code` on a refusal is the **registered** code, never prose;
and a refusal row carries **no object** — `object_type`/`object_id` stay
empty, because nothing was acted on.

*Two rulings this contract cites where they live, rather than restating.*
The **object convention** (L7) is owned by `core.service._object_of`'s own
docstring — the declared chain is `audit_object` → the first `models.Model`
in a tuple or dataclass result → nothing, and attribute-reading is ruled NOT
the rejected reshaping (the four typed sweep results covered with zero edits
to the types); this ADR points at the seam and renders no second copy. The
**escalation wall's exemption re-key** (L1): the wall's spelling moves from
actor-is-None to `kind == system` — an exemption becomes a named, audited
altitude — one sentence here, cited to the wall's own docstring once
AUDIT-2c lands it.

*SIEM export is a derived mapping, computed at export time from these rows —
never a storage shape.* A product that acquires a SIEM obligation writes an
exporter that walks `AuditEntry` and emits one OCSF event per row: `action` →
the activity / API operation of the OCSF activity class the product selects,
`created_at` → `time`, the actor columns → `actor.user` / `actor.session`,
`door` → the metadata provenance, `outcome` + `error_code` →
`status`/`status_id`, the correlation ids → `metadata.correlation_uid`. The
columns above carry everything such an export needs, so the mapping is a pure
function of the rows and can be written the day it is owed. **CADF and
OCSF-as-storage are rejected, with the ground the owner ratified verbatim
(2026-08-26): this is an internal table under rule 20, not a SIEM feed, and a
storage redesign buys a vocabulary nothing here reads.**

*Provenance, and the id this absorbs.* The revoke ruling
was first published under a sub-label appended to core-8's id — colliding
with core-8's own **(a)** entry (an early finding). **The decision
moves here**: this ADR is its home, the ruling stands unchanged in substance
(moved from `cycles/2026-08-25-cycle-p10-the-true-envelope.md` §MICRO-1's ADR
line, the id rewritten to this one — the only edit), a cross-reference stands
at core-8, and the retired rendering must reach zero in `apps/` and in this
file — **a census by grep, never a site list** (misses P8 #1); archived cycle
files are exempt as history, not guidance. The docstring sweep is AUDIT-2's.
The absorbed ruling: *context*: `revoke_token` was exempted from the audit
population by core-8's declares-tenant rule; a trail recording credential
births and not deaths · *decision*: revoke declares `tenant`
(required), call sites pass `token.tenant`, the service refuses a mismatch;
null-tenant deaths join the platform population beside their births;
already-revoked is an idempotent no-op · *rejected*: the standing
asymmetry (fails the trail's purpose), a defaulted tenant (core-8's own
sync_workforce lesson), Conflict on re-revoke (DELETE is idempotent by HTTP
law; the moment is the fact being protected) · *trigger to revisit*: a second
credential-shaped model wanting the same birth/death pairing.

*Rejected*: **a fourth "workflow" actor kind** (the `door` column carries it;
a split `system` population serves no reader); **a backfill of the
pre-contract population** (an UPDATE on an append-only ledger — structurally
illegal under rule 20, absence 5's ground); **CADF** (a vocabulary nothing
here reads, adopted into storage); **OCSF as the storage shape** (the same
ground — the internal table is rule 20's, the SIEM shape is an export's);
**new columns** (every AU-3 element already lands on an existing column — a
contract that can be met by reading discipline must not be met by schema).
*Trigger to revisit*: the first product with a SIEM export obligation (the
export paragraph becomes a rung), or a compliance ask AU-3 cannot answer from
these columns. *Blind spot, resolved then
narrowed (AUDIT-3-PRE)*: the L3 check found the admin actor seam
**present** — `ServiceModelAdmin.acting()` (`apps/core/admin.py`) builds the
actor from the request and the door stamps `admin` by path — so the
conditional absence that briefly stood in the list above was removed; no
absence ever existed there. What remains declared, narrowed to what the
check actually saw: the seam is only as good as each `call_service` that
uses it. `TenantAdmin.call_service` was found **dropping the actor for
`create_tenant`** — and the rider's fix found the hole deeper than the drop:
`create_tenant` itself was **laundering every caller's identity as
`system_actor`** before the wall ever saw it — the row said the product
acted when a person had. It now takes a required `actor` and forwards it
(AUDIT-3's rider, proven with a failing test written first: an admin-created tenant's row carries the staff
member, `door=admin`), so the admin-seam assertion above is true **without a
counter-example**. And the operator trio (`suspend_tenant` /
`resume_tenant` / `close_tenant`) is reachable from **no door today**: its
`# door:` valve names manage.py and the admin, neither of which exists —
building the operator surface is booked separately, and the valve's stale claim is
corrected in that work.

**ADR core-23 · the refusal registry carries the per-code facts; the replay
boundary is derived from it.** *Context*: `CODE_STATUS` and
the idempotency replay split both needed a per-code fact the refusal registry
already almost carried — and the registry was the only place a new code is
*discovered* rather than appended. *Decision*: `register_refusal` gains
`status=` — **optional, not required**, for three live reasons: rule 47's two
canaries would exit-2 at import if a status were demanded of them;
`invalid_arguments` is a MACHINE-door code with no HTTP status to declare; and
absence-is-a-declaration keeps the drop path reachable. `CODE_STATUS` and
`envelope_codes()` are derived off the registry, and the one-line status joins
each existing registration at its declaring site across apps. The replay
boundary is `boundary == "door"` — **boundary-as-door is doctrine, not
convenience**: a door refusal (bad credential, addressing header, CSRF, rate
limit) is decided in *front* of every service, on material the body
fingerprint does not name, and it ran nothing — the key was never spent.
Remembering one poisons the key for its whole TTL: the client that fixed its
credential and retried got the stale refusal back with `Idempotent-Replayed:
true` and could never reach its write — the exact poisoned-key class, and the 429
rate-limit second instance found in-rung. The door set is the only set
coherent with the middleware's own key-reuse arm, and it is a **closed
question over a discoverable population** — a code registered
`boundary="door"` next month joins by being registered and by nothing else.
*Rejected*: a second code→status registry in `config/api.py` (the append tax
re-created one file over); an envelope column on `IdempotencyRecord` (schema
with no reader; the 5xx drop-the-claim arm already exists); a hand list of
envelope codes (the set is open; the checklist forbids it); the plan's
original *fingerprint framing* of the boundary — the R2 builder found
`invalid_body`/`method_not_allowed` differ between the two framings, which is
this ADR's own revisit-trigger firing in-rung; the ruled `boundary=="door"`
derivation was implemented and ratified. *Deliberate residual*: a domain `403
forbidden` for an actor promoted between two calls still replays — a policy
decision is a decision about this fingerprinted request, made below the
doors; a client that wants the new answer says so with a new key. *Trigger to
revisit*: a code whose replay class differs from its boundary. Long forms:
`apps/core/idempotency.py` (module docstring + `REPLAYABLE_BELOW`),
`apps/core/exceptions.py` (`status` grammar + `envelope_codes`).

**ADR core-24 · one predicate answers "does this route answer the cursor
envelope", and every instrument reads it.** *Context*: three
instruments answered "is this route paginated?" for themselves off two
different private ninja attributes — rule 3's census, the docs derivation and
`introspect` — and all three were wrong about the same three direct-cursor
routes, because every marker they read says "`@paginate` was applied", not
what a caller experiences. The failure that matters is not the wrong column:
it is that fixing one leaves two blind — three private re-derivations of one
fact drift apart silently and nothing fails when they do. *Decision*: one
predicate in `apps/core/api/pagination.py`, beside the envelope it is about,
reads the RESPONSE MODEL; the census, the docs derivation and `introspect`
all read it — sever it and all three go red at once
(`apps/core/tests/test_pagination_seam.py` plants and proves this).
*Rejected*: fixing `introspect` alone (leaves rule 3 and the docs blind — the
carried criterion's exact ban); declaring the blind spot in three places
(three declarations of one fact drift). *Trigger to revisit*: a fourth reader
appears.

**ADR core-25 · the permission vocabulary is one shape, computed from the
model registry, never stored.** *Context*: an administrator could not give
one person one capability below `admin` without a deploy or a fourth role,
and the action names the three role checks composed with were free-floating
strings — a key could name anything, nothing could census them, and no
instrument could say what permissions a deployment had. *Decision*: one
vocabulary shape `<kind>.<verb>` — kinds and the four CRUD verbs **derived**
from the model registry at import (`authz_kind` on the model is the immutable
key under a renamable class name; `authz_kind_of` puts an owned `CASCADE`
child under its aggregate's kind; `authz_kind = None` plus a reason opts a
table out), other verbs **declared** on a kind in the owning app's
`ACTION_PROSE` as one line with its sentence, one **reserved** ownership verb
`tenant.own` that no pattern matches; three layers with one owner each —
`owner` IS the vocabulary, product-declared roles live in `apps/<x>/roles.py`
with pattern collections, tenant data is custom roles, deltas and grants both
ways; `require` composes holds AND predicate at the node the object names; one
hand-out / take-back rule replaces rank; rule 13 proves a service asks for the
kind it writes. Nothing is materialised as rows — Django derives four
permissions per model at `migrate` and this derives four per kind at import,
because a table of permission names is a second owner of a fact the code
already holds, and it goes stale the moment a product adds a model.
*Rejected*: three platform built-in roles; free-floating action names; a
`<app>.<model>.<verb>` three-part key (no collision exists, and one tomorrow is
an import refusal resolved by an explicit `authz_kind` rather than a longer key
for everybody); additive rank-bundles; person × action access lists; a
`Permission` table synced from code; a parallel custom-role table; a rules
engine; allow-only grants; snapshot collections; a foreign key from
`Membership` to a role declaration; per-node role sets resolved through
`governing()` (a tree walk per `require`). *Buy, rejected with the two exits
recorded*: `contrib.auth` + guardian, django-rules, pycasbin, Oso, Cerbos,
Topaz, Zitadel authorizations, SpiceDB, Keto, Auth0 FGA and WorkOS each
contradict either the derived vocabulary or one owner of the membership graph;
**Permify is AGPL-3.0 and house rule 23's licence leg refuses it outright**.
*Trigger to revisit*: **OpenFGA, self-hosted**, when a product needs a
relationship graph beyond the organization path — it would replace the data
half of resolution and keep the vocabulary; **AWS Verified Permissions**, when
a product is AWS-native and wants the decision out of process under a business
associate agreement. Either exit is taken behind `require`, which is the one
function every door already asks. Also revisit at the first product whose
tenants need *conditions* on a grant — time-boxed, approval-gated, "under
$1k" — which is a predicate over data and wants a check registry, not a wider
vocabulary; and at a product measuring O(people) withholds where a per-node
role set would be O(1).

## The platform the template ships

| Area | Ruling |
|---|---|
| Invitations & tenant lifecycle | `core.services.invite_member(email, tenant, role)` → the invited address's first sign-in at the identity platform joins the membership, through `accounts.adapter` (ADR ident-4); `create_tenant / suspend_tenant / close_tenant` as services. **First identity** (ADR ident-9) — a federated deployment: first sign-in through the workforce IdP, then `manage.py bootstrap_tenant --email`; a password-only deployment: `manage.py zitadel_first_admin --email`, open the link it prints and set a password, sign in, then `bootstrap_tenant --email`. `zitadel_first_admin` refuses once any tenant exists, so `invite_member` is the only invitation path from the first member on. |
| Email | Django email backend called **from a workflow activity** (retries); **Mailpit** in compose for dev; a provider via `connections` in production. |
| Rate limiting | ninja throttling per token and per tenant, defaults in settings; MCP tools share the same limiter. **ADR core-19 · context:** 429 was documented but no response header let a client back off before hitting it, and the throttle knows the numbers · **decision:** the `X-RateLimit-*` triple (`X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` as delta-seconds, matching `Retry-After`'s unit — no clock-skew ambiguity), stamped by the one middleware from what the throttle recorded on the request; the headers report the **binding** bucket (least remaining/limit ratio of the credential and tenant buckets) without naming it — which bucket binds is capacity information about the tenant's other credentials · **rejected:** the IETF RateLimit draft (`draft-ietf-httpapi-ratelimit-headers` — still a draft whose field names have churned across revisions; pinning it risks going stale as the draft churns, and adopting the RFC names once published is additive: stamp both through a window), per-bucket header pairs (a client can act on one number), headers on the MCP door (tools speak the refusal grammar; no HTTP header surface) · **trigger to revisit:** the draft becomes an RFC. |
| CORS / CSRF / CSP | `django-cors-headers` with an env allow-list; session auth + CSRF for a same-site front end, token auth for everything else; `django-csp` in production settings. |
| MCP auth | Bearer tokens now; the MCP OAuth 2.1 flow is the recorded upgrade when a third-party client must connect. Sockets gain the same bearer path (N5). |
| File storage | `django-storages`, local default, S3 by env; tenant-prefixed keys; presigned URLs; uploads through a service. |
| Tenant settings & flags | `Tenant.settings` JSON (schema-validated) + `core.flags.is_enabled(tenant, name)`; no third-party flag service. |
| Events | `v` on every payload; outbox retained; `manage.py replay_events`. |
| Erasure & retention | `accounts.services.erase_user`; audit/outbox archival recorded as dated residuals with triggers. |
| Seed, backup, restore | `manage.py seed` (dev data; the method still drives from zero); `scripts/backup.sh`, `scripts/restore_drill.sh` so the restore tripwire has something to fire. |
| Runtime | `Dockerfile` (web + worker targets); `/healthz` (liveness) and `/readyz` (db, redis, temporal); whitenoise for admin/docs static. |
| Database connections | **ADR config-1 · context:** under ASGI each `sync_to_async` thread owns a `DatabaseWrapper` whose connection closes only at the end of a request that thread served, so `CONN_MAX_AGE=60` pinned ~43 persistent connections against ≤4 active — flat across the ladder, unreclaimed 90s after the load stopped — on an instance with `max_connections=79` shared with Temporal and Zitadel; concurrency 1 was already at the slot wall · **decision:** Django 5.2's native psycopg pool (`DATABASES["default"]["OPTIONS"]["pool"]`), settings-only plus the `psycopg[pool]` extra, `CONN_MAX_AGE=0` derived rather than read whenever the pool is on, per-process `max_size` derived from `DJB_SERVICE_NAME` (web 20 / worker 8) and sized against the counted neighbour budget recorded beside the values in `deploy/env.staging.example` · **rejected:** PgBouncer transaction pooling — it forbids server-side cursors, and `.iterator()` is how exports stream chunked JSONL, how search rebuilds walk the corpus and how the workflow sweeps walk tenants, so `DISABLE_SERVER_SIDE_CURSORS` would silently turn every keyset stream into a full buffer; plus a container of surface (image, TLS on both legs, an auth story fighting the per-checkout derived database) that a ≤4-active demand cannot justify. Bare `CONN_MAX_AGE=0` with no pool — it pays a fork plus a TLS handshake per request on a *burstable* instance's CPU — measured at 71.8% of it — and it caps nothing: 32 asgiref threads under burst still open 32 slots · **trigger to revisit:** replicas × processes × `max_size` no longer fitting inside `max_connections` − neighbours − operator headroom — at which point PgBouncer is the next escalation and the `.iterator()` cost above is the bill to plan for · **the tree is the authority:** `config/settings/base.py`, "Connection reuse", carries the same argument beside the values, and `apps/core/tests/test_connection_pool.py` drives real threads against a real Postgres and fails with the measured held count on any tree that assembles no pool. |
| CI | **GitHub Actions** runs `./scripts/check.sh` (full) on every PR, against this repository's own `compose.yaml` (`docker compose up -d --wait db redis temporal`), not hand-built service containers — half the gate reaches Postgres and Temporal through `docker compose exec`, so CI runs the gate and CI provides the environment the gate assumes (`.github/workflows/ci.yml` is the authority and names what it excludes). The gate is the only CI. |
| Contracts & DX | Pydantic schemas per socket message type, listed by `introspect`; `scripts/gen_client.sh` (openapi-typescript) optional; `.editorconfig`. |
| i18n | English only by default (`USE_I18N=False`); `Tenant.timezone`/`locale` present for display; a product turns i18n on as a recorded decision. |
| The product's name | **ADR platform-1 · context:** the repository was renamed to `example.invalid` and the old name was still a literal in seven places — settings, two compose env defaults, `.env.example`, the devcontainer's display name, the README heading — so a product renamed by editing each surface it happened to find, and Zitadel had already materialised the ones it missed · **decision:** ONE canonical env-backed setting, `PRODUCT_NAME` in `config/settings/base.py` (default `"Pilecap"` — the template's own name, so a fresh clone is honest about being the template), and every surface that *shows* or *materialises* a name derives from it: `ZITADEL_PROJECT_NAME` defaults to it, and `compose.yaml` interpolates `${PRODUCT_NAME:-Pilecap}` into the first instance's org name and its service account's display name. A product sets it once in `.env` · **rejected:** hardcoding the name per surface (what was there — every rename is a survey, and the surface you miss is the one a console shows a customer six months later); deriving it from the directory or the git remote (a worktree and a fork are different directories with the same product) · **exception, deliberate:** `compose.yaml`'s `name: djangobootstrap` does NOT derive — it is infrastructure identity, containers and volumes key on it, and changing it orphans a running stack and its data. Neither do the Zitadel *logins* (`ZITADEL_ADMIN_USERNAME`, `ZITADEL_DEV_USER_EMAIL`, `ZITADEL_MACHINE_USERNAME`): they are account identifiers already created, and renaming one is a migration, not a setting · **renaming an instance that already materialised the old name:** teardown + fresh bootstrap (drop the `zitadel` database and the `zitadel_bootstrap` volume, re-run `./scripts/setup.sh`), which re-materialises from these defaults and doubles as the from-zero rebuild test — NOT a rename against the management API. `zitadel_seed` finds-or-creates by name (`accounts.zitadel.ensure_project`), so a changed name on a live instance makes a SECOND project with fresh client ids while `.env`'s `ZITADEL_CLIENT_ID` still points at the old one (owner ruling) · **not covered:** `README.md`'s heading and `.devcontainer/devcontainer.json`'s `name` are text no variable reaches, so a product edits those two by hand; each now says so at the line · **amended 2026-08-26 (owner ruling):** the identity a stranger reads becomes **Pilecap**, so the default value above moves from the template's former name to `"Pilecap"` — the *mechanism* is untouched and is exactly how that rename executed (one setting, derived surfaces, two hand-edited lines). The infrastructure namespace stays: the compose project name quoted in the deliberate exception above, the `DJB_` environment prefix and the `djb_` database prefix are covered by this row's own deliberate exception, because renaming them orphans running stacks and their data, staging included. This supersedes the earlier census recommendation to keep the former name (its leak argument was put to the owner verbatim and overruled) · **wire identifiers are not display identity:** the MCP `serverInfo` name (`config/mcp.py`) and the outbound `User-Agent` tokens (`apps/connections/client.py`, `apps/accounts/zitadel.py`) were renamed as lowercase **literals** and do NOT derive from `PRODUCT_NAME` — a display name may legally carry spaces and mixed case, and a wire token derived from one is malformed the day a product sets it · **trigger to revisit:** a third surface needing the name at *runtime* (an admin site header, an email from-name) — then it reads `settings.PRODUCT_NAME`, and this row is where that is already decided. Read *display* surface there: the wire-identifier clause above is the boundary that trigger stops at. |
| Template updates | `TEMPLATE_VERSION` + `CHANGELOG.md`; a release is ONE squashed child commit cut by `scripts/publish.sh --release` and tagged, and **products merge the tag** — never cherry-pick — adjudicating what the merge deletes against their local patches (owner ruling 2026-08-30, cycle P17; supersedes the earlier cherry-pick line; root re-cut permanently retired). Trigger unchanged: three products exist → revisit sync tooling. |
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
extra. *Trigger to revisit:* the first bank at N ≥ 7 where the composed wall
is the acceptance box by more than 60 s — then the proof box's size is the
next rung, not this ADR.

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
measures Postgres, not our queries), CI-machine normalization. Revisit when a
real deployment doubles past any declared axis, or when a hot path stays
query-count-flat while its plan shape degrades in a way EXPLAIN assertions
miss.

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
closed question can scope — the registry IS the closed question). Revisit at
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
Revisit when a dead canary is traced to a merge and the delay to push
actually cost work, or when the selftest's wall time falls below ~10s.

**ADR gate-5 · PROPOSED · rule ids are two namespaces.** *Proposed 2026-09-21
(P21, team D, rung D1). The owner chose option A in the rule-id ruling of
2026-09-21; the signature that turns this line into "Accepted" is the PM's
ritual at the cycle's CLOSE.* *Context:* house-rule ids were one integer
sequence the template and a product both appended to; a fold merged duplicate
ids and fixture dirs (`canary/54` = theirs + ours), exit 2 at the product's
first gate, renumbered by hand each release. *Decision:* only the
template mints integers; a product declares `rule_id_namespace: <ns>` once and
its rules are `<ns>-<n>` in id, fixture dir, valve and check tag; the engine
refuses any other shape and any fixture file no entry claims. *Rejected:* an
integer range (unrefusable), allocation at publish (renumbers the product), a
second file alone (no grammar, a moved rule still collides). *Trigger:* a
product with two namespaces.

*Amended (rung X3, 2026-09-21): the two keys' HOME is
`quality/local/rules.yaml`, the product's drawer, and the engine refuses either
of them in the template-owned `quality/rules.yaml` with the line that names the
move.* D1 wrote them into `quality/rules.yaml` because the drawer did not exist
yet; a declaration in a file a fold overwrites is a declaration that disappears
at the next release, which is the same failure the namespace itself exists to
end, one file up. Everything else about gate-5 is unchanged — the grammar, the
four spellings, the refusals and the residence split.

*As built (rung D1), the two places the decision above needed one more
sentence, both recorded rather than implied:* **(a)** a shape wall alone cannot
refuse a product that types a bare integer — an integer is the template's legal
shape and nothing else on the tree says which integers the template minted — so
the declaration is two keys, `rule_id_namespace: <ns>` beside
`template_rule_ids_through: <n>` (in `quality/local/rules.yaml`, per the
amendment above), the second being the highest integer the
folded template release had minted. It is `quality/partition.yaml`'s and
`FROZEN_FAMILIES`' pattern (a record of the past, in a diff a human reads), the
template never carries it, and the template's self-test prints the number a
product should record on every run. **(b)** the residence census counts TEMPLATE
ids only (D4), so `selftest_residence_backlog` stays a template fact a product
folds and never retypes, and a product's own rules are counted against zero.

**ADR gate-6 · PROPOSED · an unmeasured class says how to be recorded.**
*Proposed 2026-09-21 (P21, team D, the ratchet rung). The owner chose option B in the
ratchet ruling of 2026-09-21; the signature that turns this line into
"Accepted" is the PM's ritual at the cycle's CLOSE.* *Context:* per-app ratchet
classes name only the template's apps; a product's app had no class and the
hook was unpassable until the product reverse-engineered the grammar.
*Decision:* an app outside the partition with no recorded class is unmeasured —
a violation that prints the exact `ratchets:` line, `recorded-at <sha> [fold]`,
down-only afterwards; partition apps stay zero by absence; ratcheted rules
carry `remedies:` that `--explain` prints. *Rejected:* self-recording (no
hand), note-only (green-because-unrecorded), a template-wide zero for products
(the hook stays unpassable). *Trigger:* F's overlay file.

*Amended (rung X3F, 2026-09-21): the line the unmeasured finding prints is
pasted into `quality/local/rules.yaml` — the product's drawer (P21 EP2) —
under its top-level `ratchets:`, keyed `"<rule id>": {<class>: <n>}`, and every
note that offers a human a number to commit names whichever of the two files
that class's count actually lives in. The decision's `quality/rules.yaml` is
template-owned and a fold overwrites it.* *And the decision's "ratcheted rules
carry `remedies:`" is, as built, rules 54 and 55 only: nine other ratcheted
rules carry none, `--explain` prints the key where it exists, and widening the
population is a rung of its own rather than a sentence here.*

*As built (rung D3), the three places the decision above needed one more
sentence, each recorded rather than implied:* **(a)** a ratchet class is
app-keyed only when the FINDINGS say so — every finding in the class sits under
`apps/<label>/` for the label its key opens with — because `nonconforming` and
`secrets` are class names and a predicate reading the key alone would offer to
record an app nobody has (`unmeasured_app`, `quality/gate.py`); the plan's own
blind spot, that 54's `nonconforming` gets no unmeasured form, is this
derivation's price and is kept. **(b)** an entry recorded at `0` is a
MEASUREMENT and takes the ordinary path; only an ABSENT key is unmeasured, so
the engine reads the recorded key set and not `get(klass, 0)`. **(c)** the
partition is read through `quality/partition.py`, and a lockfile that will not
read shuts the branch rather than emptying the app list — an empty partition
would make every app on the tree a product's and turn one missing file into a
refusal storm; it is exit 2 on its own line instead.

**ADR core-26 · `core` says what happened, through the bridge.** *Accepted
2026-09-15 (P20, P4).* *Context*: `core` emitted no events at all. It sits
BELOW `apps/events` in the layer contract (rule 7), so it may not import the app
that owns the outbox — and the six most consequential writes in the platform
(a role made, renamed, deleted; a role's collection edited; a permission handed
to or taken from one person) were therefore invisible to every webhook
subscriber and every socket, while a widget creation was not. *Decision*:
`apps/core/events.py` declares `core.role.created`, `core.role.updated`,
`core.role.deleted`, `core.membership.updated`, `core.grant.created`,
`core.grant.deleted` — names only, house rule 16's grammar, the noun being the
authorization KIND the row belongs to — and `services.py` publishes each one
through `bridge.get(bridge.EMIT)` **inside the transaction of the write it
describes** (principle 8; the relay is outside it). Payload v1 is flat:
`tenant_id` always, `organization_id` wherever the row belongs to one part of
the tenant (rule 38), then the fact — `role_key`, or `membership_id` +
`permission` + `effect`. *Rejected*: importing `apps.events` from `core` (rule
7 — and the spine apps are removable, so a checkout stripped back to `core` must
still run); emitting from the door (rule 10); shipping the hand-out family with
no events at all (rule 42's class — a write nobody can subscribe to). *The one
collision, named*: `services.KICK_MEMBERSHIP_REVOKED` is the string
`"core.membership.revoked"` — a channel-layer close reason, read by
`apps/realtime` and by nobody else. The two vocabularies share a prefix because
they are about the same rows; no name appears in both, nothing reads both, and
`apps/core/events.py`'s docstring is where that is written down. *Trigger to
revisit*: the first `core.membership.*` event beyond `updated` — a creation or a
revocation published as an event rather than only kicked — at which point the
two lists are close enough together that one of them is renamed.

**ADR core-27 · a read is a permission.** *Accepted 2026-09-15 (P20, Phase R).*
*Context*: through v2.0 a `<kind>.read` key was free to any membership in the
tenant — `allows` step 3 short-circuited it and `visible_to` was the whole read
gate. That answered "which rows" and never "whether this kind at all", so a
role could say nothing about what a person may see, a custom role could not be
narrowed to a subject area, and a `withhold` had no effect on a read.
*Decision*: a `<kind>.read` resolves through the same three layers as every
other key — `owner` holds it (the vocabulary), `admin` holds it (`*`), `member`
holds it (`*.read`), a custom role holds what its collection names, an `allow`
grant adds it and a `withhold` subtracts it. **The check lives in the selector,
once** (§C6), and every door pays it: a `list_` asks at the acting hat
(`obj=None` → `where_of`) before it builds the queryset; a `get_` asks after
the scoped fetch with `obj=row`. **`visible_to`/`for_tenant` still decide WHICH
rows and `require` decides WHETHER this kind, here** (rule 24, BVB-4) — a
selector never filters rows by permission. A `system` actor passes at step 1.
*The grammar* (§C8): outside your subtree → `not_found` (the scoped fetch,
unchanged) · inside it without the key → `forbidden` with
`refusal_sentence("<kind>.read")` · a list without the key → `forbidden`,
because a list has no row to hide. Reach before capability. *Consequences*: a
membership with **no role reads nothing**; a **custom role reads nothing until
its collection names reads**, so the role services accept `"*.read"` as a
pattern and expand it at write time; **the socket narrows per HAT, not per
org** — a connection's read set is the read half of `effective_permissions` at
the acting hat, computed once at connect and checked per frame (a per-org set
would disagree with the REST list, which rule 46 forbids); a write that shrinks
somebody's read set at any node they hold a membership on closes their sockets
on commit (`core.permissions.narrowed`), a widening kicks nobody; the token
echo drops the read half when no read is held; `READ_VERBS` and `is_read()`
remain as deprecated shims read by nothing until v3.0; **a tenant-wide kind — one
whose model names no organization — is READ at the acting hat and WRITTEN at the
root** (PR5.5, 2026-09-17), which is the v2.1 stopgap and is declared as one: it
makes this door agree with the socket, the search and the admin today, every such
site wears a dated `hat-scoped` valve that house rule 55 counts, and universal
homing replaces it in v2.2 by giving those kinds a home (the universal-homing
proposal, 2026-09-17 — every record homed at a node). *A flat product observes
nothing* — the 288-cell census in `apps/core/tests/flat_product_baseline.json`
is the proof, and 0 write cells moved when it was re-derived. *Trigger to
revisit*: the first product that wants per-FAMILY read precision in the token
echo, or the first family-shaped withhold.

**ADR core-28 · a template migration is grafted onto the product's leaf by a
command, never by hand.** *PROPOSED 2026-09-21 (P21, team D, decision D2 —
the owner chose option A; the signature at CLOSE).* *Context*: a product that
added migrations to `core`/`accounts` met each release's numbered ancestors
twice — a leaf fork and, after one fold, ancestors it had renamed — and
reparented by hand under `django-linear-migrations`' refusal.
`rebase_migration` moves exactly ONE migration and cannot see a chain or a
renamed ancestor at all. *Decision*: `manage.py fold_migrations <app>` grafts
the arriving chain from the `max_migration.txt` conflict onto the product's
leaf, resolving a renamed ancestor by stem suffix, refusing an applied
migration or an ambiguous stem; template files stay Django-native; stems are
unique per app by test; a new product is advised to extend template apps from
its own. It subclasses `rebase_migration`'s `Command` rather than replacing it
(principle 2), and the library internals that makes it hold are declared in
house rule 44's `linear_migrations_internals_we_hold`. The direction is the
INVERSE of the library's: `rebase_migration` moves yours onto theirs, the fold
moves theirs onto yours, so the markers are read positionally and the library's
merge-time swap is undone. *Rejected*: named-ancestor spelling in template
migration files (non-native, regenerated away by `makemigrations`, and no fix
for the leaf fork); forbidding product migrations in template apps
(unadoptable by the consumer that exists — it already holds `core` 0018–0023).
*The cross-app gap, declared rather than closed*: a dependency from ANOTHER
app onto a migration the fold renumbered — `("accounts", "0008_identity_branding")`
written in `apps/comms/migrations/…` while the fold made it
`0010_identity_branding` — is left exactly as written. Stem resolution runs
only within the app being folded, because a stem is unique per app and nothing
here is entitled to edit another app's files; Django's own loader then raises
`NodeNotFoundError` naming both ends at the next `migrate` or `manage.py
check`. **Loud, and never wrong** — which is why it is a declared gap and not a
silent one: the operator folds the other app too, or repoints that one
dependency by hand. Closing it (a tree-wide pass that rewrites cross-app
tuples) is queued in `queue.md`, not decided here.
*Reversible*: `git checkout -- <app>/migrations && git clean -f
<app>/migrations` undoes a run (principle 6) — **both halves**, because a
rename leaves the new filename as an UNTRACKED file, so a checkout alone
restores the old chain and leaves the grafted copies beside it — and
`--dry-run` prints the plan before anything moves.
*Refused, not attempted*: a stopped `git rebase`. Under one, HEAD is the
upstream and `MERGE_HEAD` does not exist, so the library's merge-time swap does
not happen and this command's un-swap does not either; the two inversions
cancel and the fold would renumber the PRODUCT's chain onto the template's
leaf, silently. `REBASE_HEAD` is read before the markers are, and the command
exits 2 saying so. *Trigger to revisit*: a squashed
template migration (house rule 6's gap), or a product that wants the fold to
run across every app at once rather than one app at a time.

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
2. **AST checks** (`quality/checks.py`) — undecorated/positional services,
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
11. Every app has the canonical shape: `models · services · selectors · schemas · api · mcp · workflows + activities · consumers · events · policies · admin · tests`; a different file name for the same job (`utils`, `helpers`, `logic`, `managers` holding business rules) is a violation.
12. Reads and writes are separate: `selectors.py` never writes; `services.py` never returns a queryset for display.
13. Every function in `services.py` is decorated `@service` (keyword-only, typed, `tenant`/`actor` for tenant-owned writes, returns an object or dataclass — never `dict`/`None` for a write) and calls `authz.require(actor, action, obj)` before a write to a scoped model (or carries `# authz: <reason>`). A door that contains permission logic is the same violation from the other side. **And a service that asks asks about what it WRITES**: every kind its body writes — resolved by AST through the model registry's `authz_kind` / `authz_kind_of` / `snake_case(ClassName)` — is a kind it required, or the write line carries `# authz-kind: <reason>`; and every key it requires is one the vocabulary holds, written as a literal or a module-level string constant, or the ask carries `# authz-key: <reason>`. A `require` proves only that somebody asked something — `create_widget` guarded by `widget_policy.create` is a perfectly shaped service that authorizes the wrong noun, and every other layer reads as green over it. The mismatch count is a per-app ratchet each Phase-W sweep drives to zero; a service that asks for nothing at all stays the `# authz:` clause's subject, said in the rule's `does_not_cover` rather than left to be inferred from silence.
14. Services raise `core.exceptions.*`; `HttpError`/`Http404`/status codes never appear in `services.py`/`selectors.py`; the one mapper lives in `config/api.py`.
15. Models: `on_delete` explicit (`PROTECT` default; `CASCADE` only for owned children; `SET_NULL` with a reason comment); invariants in `Meta.constraints`; no business logic in `save()`; `TextChoices` for enumerations; **no `FloatField` on money/quantity/rate** (Decimal 19,4 + ISO-4217 currency); `DateTimeField`s end `_at`, `DateField`s `_on`; no `is_deleted` booleans (`archived_at` if a product needs it). **And a secret-shaped field is encrypted at rest**: a field named `secret`, `token`, `password`, `credentials`, `signing_key`, `api_key`, `private_key`, `access_token`, `refresh_token`, `client_secret` — or any of those as a suffix — is an `EncryptedCharField`/`EncryptedJSONField`, or is allow-listed in `quality/rules.yaml` with the reason. A database dump, a replica, a backup and a traceback are four ways a plaintext credential leaves, and one field sitting in the clear beside encrypted neighbours is never a decision somebody made — it is one nobody noticed. A name ending `_hash` is a digest, not a recoverable secret, and is out of the population by construction: encrypting it would protect nothing and would break the unique lookup that authenticates every request.
16. Naming: apps plural nouns; models singular; services are verbs; selectors `get_`/`list_`/`_for_tenant`; events `<app>.<noun>.<past-verb>` declared in the app's `events.py`; schemas `XIn`/`XOut`; booleans `is_`/`has_`.
17. Door parity: a capability on REST is on MCP unless exempted in `rules.yaml` with the reason (introspect registries diffed).
18. Workflow ids are deterministic (`<tenant>:<app>:<noun>:<key>`, via `workflow_id()` — or `platform:<app>:<noun>:<key>` for a run the deployment owns rather than a tenant); **neither starter has a default for `id`** — it is required, keyword, on both `start_workflow` and `start_workflow_on_commit`, because a default turned every caller who forgot it into a caller with no idempotency at all. A four-segment constant bound to a name is the same id as the literal and reads as one; an alias on the import (`as begin_run`) does not make a random id invisible; and the platform module that *defines* the starters is excluded from the callsite scan and pinned instead — the gate asserts the two signatures still ask for the id.
19. Observability: every log line is structured through `core.log` (no `print`, no bare `logging.getLogger`, no f-string/`%` in a log call); only `core/observability.py` configures OTel/logging; no PII keys outside the app's `LOG_KEYS` allow-list.
20. Traceability: every door binds context (`request_id`, `session_id`, `tenant_id`, `user_id`, `correlation_id`, `causation_id`, `trace_id`) before calling a service; `correlation_id` is never minted below a door. **Append-only is a declared population, not a name** (ADR core-6): a model that declared `append_only = True` may have rows created and nothing anywhere may update or delete one — no `.delete()`, `.update()` or `.bulk_update()` outside the model's own declaring module. `AuditEntry` is the first member; the gate reads the population off the declarations (`core.models.append_only_models`), so a product's witnessed fact or accrual ledger is covered the moment it declares itself, with no edit to `quality/rules.yaml`.
21. Admin: every `ModelAdmin` inherits `core.admin.ServiceModelAdmin` (writes through services, scoped models filtered by acting tenant, `door=admin` in audit); a raw `ModelAdmin` on a scoped model is a violation.
22. Migrations are expand/contract: no non-nullable column without a default in the same migration as its add; no column/table drop in the same deploy as the code that stops using it (the drop is a later rung); migrations run as a release step.
23. Supply chain: `pip-audit` clean, no AGPL/GPL dependency (`pip-licenses`), no secret in the tree (`detect-secrets` against a committed baseline) — all three are gate legs.
24. Every read of an `OrgScopedModel` in a door, service or selector chains `.visible_to(actor)` after `.for_tenant(...)`; a bare tenant-scoped read of an org-scoped model is a violation. **Or `.governing(org)`** — upward *config* resolution, never upward *visibility* (ADR core-3) — and that half is fenced in the same breath: `.governing(...)` is legal only on a model that declared `InheritedDownward`, and a call on an unmarked model is a violation here for the same reason it is a `TypeError` there. Grants above the granter's effective role, or outside their subtree, are refused in the membership service. Re-parenting outside its service is a violation.
25. **`comms.send()` is the only legal sender.** No module under `apps/` imports `django.core.mail` or `apps.core.mail` outside the allow-list in `quality/rules.yaml` — `apps/comms/**` (the transport itself), `apps/core/mail.py` (the platform mailer), `apps/workflows/activities.py` (that mailer's I/O edge) and tests. Consent, quiet hours and suppression are enforced *inside* `send()`, so a feature that reaches for a mail module reaches around all three. The one standing caller — `core.services.invite_member` — is ratcheted at 1 and named for a follow-on rung (ADR comms-2), not exempted.
26. **A service names nothing the actor could not have reached** (ADR core-4). A `@service` that writes an org-scoped row and takes a parameter annotated with an org-scoped model passes it through `core.authz.may_be_named(actor, obj)` — refusing when it is False — or carries `# reach: <reason>` on the parameter. Tenancy cannot catch a reference into a branch the actor holds no membership over, because the row *is* in the tenant; the policy cannot, because the policy is about the verb. The annotation is the declaration the gate reads: which kwargs are FK targets is an open set, and an annotation naming a model in the tree is the closed half of it. Gate-tier and **ratcheted over a measured backlog** (measured before enforced, per app); every `# reach:` is counted and printed, and a bare one is itself a violation.
27. **One door to the identity platform** (ADR ident-2). Identity configuration is written through our audited services onto our rows, and *materialised* in Zitadel by `apply_identity_config` — **the row is the intent, Zitadel is the materialisation, and the console is a window, not a door**. The enforceable half: no module outside `apps/accounts/zitadel.py` names the `ZITADEL_PAT` setting (`config/settings/` excepted — it is where the environment is read), and nothing outside the `quality/rules.yaml` allow-list imports that module at all, except through the rule's own `# rule-27:` valve: the allow-list is the activity, where a management failure is a Temporal retry, plus the `zitadel_*` commands that are the shell door (`python -m quality.gate --explain 27` prints which, and the count moves without this file changing), and `manage.py zitadel_reconcile` is the one VALVED importer — its reason says it takes `configured()` and `ZitadelError` and writes nothing at all (`apps/accounts/management/commands/zitadel_reconcile.py:198-204`). A service that reached the management API would put external I/O inside its transaction, and a Zitadel hiccup would roll back a legitimate row (C2). The honest half, declared rather than implied: **a check cannot see Zitadel's own console**, so `manage.py zitadel_audit` — read-only, changes nothing — is the runtime tripwire, and `manage.py zitadel_reconcile` asks the services to close what that audit reports, by hand, as a deploy step, with `--dry-run` and the 0/1/2 exits shaped for one. What is deliberately not built is a SCHEDULED run of the reconciler, and that command's own docstring names the trigger for building one (ADR ident-2 amended, below): a drift found in production that nobody in this deployment caused.
28. **Workflows close their runs** (ADR workflows-5). A start writes a `WorkflowRun` row saying `running` — that row is the product's own answer to "what is happening", the one a selector, an admin page or a reconciler can actually read, because nothing here queries Temporal from a selector. So every class in an app's discovered `WORKFLOWS` list either reaches its app's finish seam from `@workflow.run` — **last**, after the work, so a failure after the mark cannot leave a `completed` row for a failed run — or **declares `owns_no_run = True`**, which is the schedule-started population: nobody asked for it through a service and no row exists to close. Two seams are live and both are right (`apps/workflows/workflows.py`'s module-level `_finish(work)` wrapper; the domain apps' `self._finish(status=, error=)` method), so the gate asks for a *reference* to a `_finish`-named seam rather than one call shape. Measured before enforced, and ratcheted over what the measurement found. Declared blind spot: the scanner sees the reference, not the path — whether the seam is reached on every branch, and whether an `owns_no_run` declaration is true, are review's and W4's reconciler's.
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
(`apps/search/selectors.py::search`, which resolves the tenant and the acting
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

49. **The audit row names who and where, always** (ADR core-22; the row
was owed here since the rule landed and is written now — the gap itself is
the evidence for the numbered-list consistency check the queue carries).
Every `@service` in the audited population — every one whose signature
declares a keyword-only tenant — declares `actor: Actor` AND `tenant`, both
required and never defaulted, or its dotted name is on the enumerated-absence
list in `quality/rules.yaml` with its ADR core-22 absence number and ground.
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

57. **One writer of the identity join** (ADR ident-11). The join is
keyed on the subject, not the address. `User.zitadel_sub` is written by
`record_zitadel_identity` and cleared by `unlink_zitadel_identity`, both
`@service` and both audited; `sociallogin.connect(` lives in the adapter, after
the writer has answered. Reads are out of the population by construction — and
pinned there by a negative, because a rule that fenced reads would be a rule
against using the column it protects. A second writer is how a join between two
identity systems comes to disagree with itself, and the disagreement is an
account takeover with an extra step. Declared blind spot: a write that precedes
a refusal is a census (`test_refusals_write_nothing.py`), not a shape; so are
`setattr`, a `User(...)` constructed with `zitadel_sub=`, and `SocialAccount.uid`,
which is allauth's own column.

58. **Socket join discipline: nobody names their own group, and nobody mounts
an open socket** (R4 F1; ADR realtime-2's "nobody names their own group" made
enforceable). Every `group_add` under `apps/` takes its group from one of the
bridge's three derived builders — `tenant_group`, `org_group`, `user_group` —
directly or through a name the same scope bound to one; and every entry in a
module-level `websocket_urlpatterns` wraps its application in `token_auth(...)`
and names a consumer extending `TenantEventsConsumer`. The sentence was a
convention for ONE consumer and the review proved what that was worth: a planted
`apps/example/consumers.py` doing `group_add(f"tenant.{query['tenant']}")` and
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
`apps/core/tests/test_roles_are_keys.py` rules against). *Trigger to revisit:*
the first product that ships an undecided noun past a red gate — sockets silent
for it, `events.emit.kind_undecided` in the logs and nobody reading them.
*Reversible:* restore the raise in
`_refuse_a_branch_that_disagrees_with_the_name` and disable class 3; the two
proven refusals and every other behaviour are untouched by either direction.

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


## App map — data portability

One app, shipped rather than planned, and its row is here rather than in the
ingredients table below because that table is the P6–P7 **delta**: this one is
on main.

| app | noun (aggregate) | depends_on | doors exposed | workflows owned | events emitted / consumed |
|---|---|---|---|---|---|
| `exports` | `Export` | `core, accounts, events, workflows` | REST `/api/v1/exports/` (list · create · retrieve · download) · MCP `list_exports` / `get_export` / `create_export` / `download_export` | `ExportTenantDataWorkflow`, `PurgeExportsWorkflow` | emits `exports.export.requested/.completed/.failed` |

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

**Trigger to revisit — ING-1's landing**: the storage seam re-points onto the
files app, presign posture inherits files-2's TTLs, the tenant-prefixed key
convention is promoted from this app's local decision to the platform files
seam, and the artifact reference may migrate onto the files app's blob model.

## App map — the ingredients (P6–P7 delta; the lead's section, 2026-08-23)

The template's own apps are described in prose above; this table is the
app-map delta the ingredients add (ADRs in `adrs-ingredients.md`; the
cycle plan is `cycles/2026-08-2X-cycle-p6-p7-the-ingredients.md`). One row
per app; a rung's brief carries its delta to this table.

| app | noun (aggregate) | depends_on | doors exposed | workflows owned | events emitted / consumed |
|---|---|---|---|---|---|
| `usage` | `UsageEntry` (append-only) | `core, accounts, events` | REST `/api/v1/usage/` (read) · MCP `usage.report` — **U2**; **no write door, ever** | none | emits `usage.threshold.crossed` |
| `files` | `StoredFile` (+ `FileVersion`) | `core, accounts` today (**F1**) → `+ events, workflows, usage` at F2 | REST `/api/v1/files/` · MCP `files.*` — **F3** | `FinalizeUpload`, `SweepPendingUploads` — **F2/F4** | emits `files.file.stored`, `files.file.archived` |
| `search` | **none — the app owns no table** | `core, accounts` (R-a) → `+ events, workflows` (R-b) | REST `/api/v1/search/` · MCP `search_query` | `ReconcileSearchIndexes` (the declaration-digest startup reconcile) | consumes each `Searchable`'s declared `refresh_on` names (R-b); emits `search.engine.degraded/.recovered` (R-d) |
| `completions` | `Completion` (+ `Prompt`) | `core, accounts, workflows, usage` | REST `/api/v1/completions/` · MCP `completions.*` | `RunCompletion` | emits `completions.completion.succeeded/.failed` |
| `comms` (grows) | `Message` (+ `MessageEngagement`, `Device`) | unchanged | existing + engagement read; SMS/PUSH channels | existing | emits `comms.message.opened/.clicked` |

ADR lines for the cross-app arrows live in `adrs-ingredients.md` (usage-1,
files-2, search-2, comms-9, the ING-3 ADR); the one shared seam is
`usage.services.record_usage`, landed first (P6 wave 0).

### The ADR home

**This file is the canonical home of every ADR.** It is the truth table's
"what was decided, and why — settled", and it ships in the publication
manifest while `cycles/` is trimmed — an ADR living only in a cycle plan is
a DRAFT until its line lands here, and would otherwise be lost at publish.
`adrs-ingredients.md` ships too and stays the ingredients' long-form record;
its ids are canonical because the file is in the ship-list, not because it
is a second home — a new ADR lands HERE. The index is derived, never
hand-built: the `ADR <app>-<n>` grammar is greppable in this file. **The
census criterion (PUB-1):** every ADR id cited in any ship-list file
resolves inside this file or `adrs-ingredients.md`; a citation resolving
only into `cycles/` is a defect by this ruling.

The three ids that resolved only in `cycles/` at the ruling, moved here
verbatim (provenance noted per entry; the source plans keep their copies as
history — this file governs):

- **ADR core-7 (Measured)** *(an earlier draft of this decision named
  `Measured`/`MeasuredBasis` in prose — the importable symbols are
  `MeasuredOut`/`MeasuredBasisOut`, rule 16's suffix)* · context: the basis contract ("a number the UI never
  computes") was honored over a hundred times in an earlier consuming
  product by convention; the
  architect's diff-guard argument won at the panel · decision: generic
  `Measured` schema in `apps/core/schemas.py` — `value: Decimal`,
  `basis: MeasuredBasis(formula: str, inputs: dict[str, Decimal])` —
  plus conventions/architect entries; **enforcement at criteria-tier,
  honestly**: "any endpoint returning a computed aggregate" is an open set
  no closed question can scope (doctrine 1), so the lead's checklist gains
  the line and the blind spot is declared, not disguised as a rule ·
  rejected: an AST rule recognizing "computed aggregates" (walked past
  without malice — the sibling's six-times lesson) · trigger: a closed
  population emerges (e.g. a declared `*Stats` schema suffix convention)
  → revisit as a rule.
- **ADR ident-3 (the ApiToken join — the subsumption decision)** · context: MCP OAuth 2.1 subsumes the panel's ApiToken-org rung;
  does ApiToken survive? · decision: **ApiToken survives, for first-party
  machine callers** (seed, `issue_token`, field tests, CI probes); OAuth
  2.1 is the third-party door (assistants, DCR clients). Justification:
  retiring it would put a browser consent dance inside `manage.py seed`
  and every existing wire test — the exact DX the deferral logic
  protects — while costing nothing to keep (one authenticator in an
  ordered list). **Org and tenant binding stay request-time for both
  credentials**: the token (either kind) contributes WHO; tenant resolves
  from memberships/pin + `X-Tenant`, the hat from `X-Org` through
  `resolve_org`, revalidated per request from rows — an issue-time org
  claim would go stale against the tree the way the platform's doctrine
  exists to prevent · rejected: retiring ApiToken now, org-in-token
  claims · trigger to retire: Zitadel service-user PATs reach
  `issue_token`-grade DX (one command, no browser) → a named retirement
  rung.
- **ADR example-3 (drop the WidgetOut aliases)** *(Widget gains
  `owner_email`/`organization_slug` model properties, and the parity
  test's key-set is exact)* · context: a
  REST-vs-MCP body divergence traced to serializer aliases · decision:
  drop WidgetOut aliases (comms precedent: model properties); the parity
  test compares WIRE shapes (REST `response.json()` vs MCP
  `structuredContent`). Stated break: MCP clients on dotted keys —
  accepted; REST is the contract (E1) · rejected: keeping the aliases
  with a translation layer (a second contract language) · trigger to
  revisit: none — superseded only by a v2 contract decision.

**Moving decisions out of trimmed history.** A later census found 29 more ids
whose only decision text lived in trim-listed cycle plans — every ship-list
citation of them would dangle at publish. The same rule as the three above:
each moves here with its provenance named; the source plans keep their
copies as history — this file governs. Where a plan interleaved the decision
with cycle narrative, the provenance line says *excerpted* and the decision
text is carried faithfully, never paraphrased. **Four ids were assigned
twice** (core-8, core-9, ident-5 by P0 and P2/P5; deploy-1 by P4 and the P5
standard-then-doors plan): live citations exist for *both* meanings of each,
so both decisions are recorded under the shared id with the collision noted,
rather than renumbered under citations this file does not own. One id
(events-1) has no decision text anywhere in the repo or its history — its
entry below is an erratum, not a decision. gate-4 is not below: it is ADR
gate-3 (§ the gate's own section, above), which records that it was drafted
as "ADR gate-4".

- **ADR comms-1 (comms' dependency arrows)** *(the decision text below was
  interleaved with an app-map row, quoted verbatim)* ·
  decision, verbatim: "depends_on declared now incl. connections; bridge
  rejected (comms sits above the spine; direct import is legal)." The
  app-map row it annotates: comms · Message (+Recipient, MessageTemplate,
  ChannelPreference) · depends_on core,accounts,events,workflows,connections.
- **ADR comms-3 (status webhooks ride connections' receiver)** · status webhooks ride connections' receiver; rejected:
  comms `auth=None` route (2nd rule-3 entry), mounting anymail views
  (vendor door), polling. Revisit: first ESP whose signature isn't
  HMAC-over-body → provider protocol grows `verify()`.
- **ADR comms-4 (the seam is produced and consumed together)** · the app
  owns `comms/**` AND the ~40-line connections seam
  (registry + `_hand_off` branch) — seam produced+consumed together (I+).
  Revisit: a second registering app.
- **ADR comms-5 (the delivery-status wait lands in comms-a)** · wait in comms-a (else every signal
  Conflicts on a finished run — the seam untestable). No-policy send ≡
  one-step policy `escalate_when=none`. The settled-decisions half: after
  sent, `wait_condition` on a delivery_status signal, STATUS_WAIT=72h
  (named guess), completes either way; comms-b generalizes the same wait
  into the step loop.
- **ADR comms-6 (channel kinds ship, vendors are config)** ·
  Channel.SLACK → Channel.CHAT ("chat") — kinds ship, vendors are config.
  Revisit: two chat vendors with different consent semantics.
- **ADR comms-7 (consent re-checks per escalation step)** ·
  consent RE-CHECKS per escalation step — send_step runs the full wall at
  that step's send time; a suppressed step writes its suppressed Message
  and the interpreter proceeds without waiting. Rejected: snapshot at entry
  (mid-chain revocation overridden), consent in the workflow (rules 9/10).
  Revisit trigger: quiet-hours scheduling (defer-until-window) — named
  deferral.
- **ADR comms-11 (SES at the edge the wall already built)** *(narrowed, not
  reopened, by ADR comms-12 below — its decision sentence
  "SES via anymail" became "anymail is the seam"; its rejected list and
  trigger stand)* · context: the Email row says
  provider-in-production via the ESP edge; anymail is already the
  normalization layer (providers.py reads anymail's EventType/RejectReason;
  comms-9's hard/soft fork keys off it); example.invalid's warm-up clock is
  running; the wall's round-trip (bounce → suppress, hard-only) is proven
  so far against fixtures, never against a real provider · decision: SES
  via `django-anymail[amazon-ses]` (boto3 — the one new dependency); domain
  identity `example.invalid`, Easy DKIM, SPF on MAIL FROM `mail.example.invalid`,
  DMARC `p=none` at first observation moving to `p=quarantine` when reports
  are clean (the runbook owns the promotion; the warm-up doctrine: low
  volume, real engagement first); bounce/complaint events via SNS HTTPS
  subscription into the app's existing status-webhook door (the exact seam —
  anymail's tracking view or the connections
  receiver — confirmed at measure-first; SNS signature verification required either
  way); sandbox proves the round-trip with SES simulator addresses before
  production access lands · rejected: SES SMTP relay (no tracking webhooks
  — the wall goes blind), a third-party ESP (a second vendor signup per
  clone against the AWS standing posture), skipping DMARC until a product
  ships (the warm-up clock is the point of doing this now) · trigger to
  revisit: first product with marketing-volume sending (dedicated IP /
  MAIL FROM per product), or SES production access refused (escalate to
  owner with the case).
- **ADR comms-12 (anymail is the seam; the provider is the product's)**
  · context: comms-11 chose SES
  because the template would operate its own sender; the owner ruled the
  template never carries production traffic and a first consuming product
  already sends through Resend, verified for its own domain; the wall reads anymail's
  normalized events (`providers.py:368-400`), which are provider-agnostic
  by construction · decision: the template proves the mechanism
  `comms.send()` → anymail → a real provider → the bounce event back
  through the real receiver, once, against Resend; no provider SDK is
  added (boto3 not added); the provider a product uses is the product's
  setting (`EMAIL_BACKEND`), documented in the runbook as one line per
  supported anymail backend · rejected: SES for the template (an
  account-level review clock and a second vendor the first product will
  not use), a provider-abstraction layer of our own (anymail IS it),
  mail-body PHI enforcement (owner correction: not the platform's concern
  — refused as a rule, a canary or a design-agreement line) · trigger to
  revisit: a product whose provider anymail does not support, or a product
  that needs a BAA its provider will not sign (then that product chooses
  SES and its clocks start).
- **ADR core-8 — TWO decisions share this id**; both stand, both cited in
  the tree, recorded here together rather than renumbered.
  **(a) emit-side datetime normalization** · context: ninja
  renders datetimes through `NinjaJSONEncoder`/`DjangoJSONEncoder`
  (milliseconds); `emit()` stores pydantic's `model_dump(mode="json")`
  (microseconds) — same instant, two strings, template-wide · decision:
  **emit-side normalization**: `emit()` round-trips its payload through
  the exact encoder class the REST door renders with, so `Event.payload`
  == the REST body byte-for-byte and E3's sentence ("webhook clients see
  what a REST client sees") becomes literally true; REST bytes unchanged ·
  rejected: a microsecond renderer in `config/api.py` (changes every
  datetime on the wire; "REST is the contract" — ADR example-3's own
  precedent — and re-pins its byte-identical proofs), per-call-site
  truncation (open set; the next emitter forgets) · trigger: a consumer
  needing sub-millisecond precision → a versioned payload.
  **(b) AuditEntry's platform population** · context: `@service` writes
  the audit row only when
  `tenant is not None` (`apps/core/service.py:229`), so every
  platform-scoped action — a tenantless erasure, the workforce identity
  sync, and other platform-scoped actions besides — is *logged, not audited*: the one
  compliance-shaped trail has a hole exactly where the compliance actions
  are · decision: **mirror ADR workflows-3, shape for shape** —
  `AuditEntry.tenant` becomes nullable (ONE expand migration, the cycle's
  only leaf), **null is a declared population, not a loosening**:
  `for_tenant(...)` keeps failing closed and can never see a platform row
  (every tenant door — admin changelist included — is unchanged by
  construction), `for_platform()` on the manager is the one read path
  (same name, same docstring posture as `WorkflowRun`'s), the `@service`
  decorator becomes the population's one writer (`tenant` kwarg present,
  value None), and `append_only` covers the null rows exactly as before —
  rule 20 unchanged, rule 8 gains its 7th standing platform-population
  override, recorded · rejected: **a sentinel platform tenant**
  (workflows-3's own rejection, and rows of other models would accrete
  onto it), **a separate PlatformAuditEntry model** (two trails; every
  incident reconstruction must union them forever), **status quo** (an
  erasure's revocation with no audit row is the same hole in a different
  place) · trigger to revisit: a third model needs a platform population
  → workflows-3's own trigger fires and the shape generalizes or becomes
  a base. *(The AuditEntry platform-partial index — `condition=Q(tenant__
  isnull=True)`, never a bare tenant-blind index — is this ADR's shape, as
  measured and recorded.)*
  **There is no third sub-label on this id.** A later revoke ruling that
  briefly wore one — colliding with **(a)** above — lives at **ADR
  core-22**, which absorbed and renamed it.
- **ADR core-9 — TWO decisions share this id**; both stand, both cited.
  **(a) `ordered_by` keeps the selector's ordering as tie-breakers**
  · context: `ordered_by` calls `.order_by(wanted)`, which
  **replaces** the queryset's ordering — any door promising a secondary
  sort silently loses it (`list_templates` does; the stale apology comment
  sits at `apps/comms/api.py:296-300`) · decision: `ordered_by` re-applies
  the incoming queryset's existing ordering as tie-breakers after the
  requested field (dropping only a duplicate of the requested field
  itself), so a selector's promise survives the door · rejected:
  allow-list entries as field-tuples (pushes the fix to every route),
  documenting the loss (a promise a client cannot see is broken is not a
  contract) · trigger: a route that must deliberately replace ordering →
  an explicit `replace=True` parameter, then.
  **(b) `PLATFORM_CONTEXT` crosses on the bridge** · context:
  `platform_context()` is the declared accessor a
  platform-run activity may use, but `apps/workflows` sits above
  `apps/accounts`, so a builder working below that layer could not reach
  it and reported rather than smuggled — today the two platform kinds in
  `apps/accounts/activities.py` simply *skip* context resolution,
  asserting nothing; and the `"platform"` segment is now stated three
  times (`workflows/services.py:111` the owner, `core/services.py` and
  `accounts/services.py:723` the pinned repeats) — the queue row's named
  trigger for the bridge constant, fired · decision: the bridge gains
  `PLATFORM_CONTEXT = "workflows.platform_context"` with a
  `ReadsPlatformContext` shape in `SHAPES`; `apps/workflows` registers
  `platform_context` from `ready()` beside its existing names; the
  accounts platform kinds resolve scope through
  `bridge.get(bridge.PLATFORM_CONTEXT)()` and the loud contract travels
  with it — a platform kind invoked under tenant-stamped headers fails
  loudly instead of proceeding cross-scoped. The two segment *constants*
  stay where they are: the bridge carries callables with shapes, not
  values, and both repeats are already pinned against the owner by named
  tests (`test_move_matrix.py`, `test_federation.py`) — a pinned repeat
  is a contract, an unpinned import path is a wish · rejected: importing
  `apps.workflows.context` from accounts (the layer violation the bridge
  exists to invert), a fourth restatement of the behavior locally in
  accounts (the drift this ADR exists to stop), putting the segment string
  itself on the bridge (a constant is not a callable; the SHAPES contract
  has no meaning for it) · trigger to revisit: a second app below the
  platform needs platform scope → the key is already there; nothing to
  decide.
- **ADR core-10 (the org tree's one human door)** *(the recommendation
  was PM-ratified at plan review)* · context: no door reaches `move_organization` — the
  three-move grammar is service-only by deliberate omission
  (`OrganizationAdmin` pins `parent` read-only *against form edits*,
  correctly, since a form write would bypass the wall and the durable
  run); moving one required hand-driving it through a shell, proven twice ·
  decision (RECOMMENDED — PM ratifies at plan review): **an admin
  action** — `move_to_new_parent` on `OrganizationAdmin`, an intermediate
  form whose target-parent choices are `.for_tenant`-scoped, calling
  `move_organization` and rendering refusals through the same
  `wire_refusal`/`messages.error` composer already in place; the read-only
  `parent` field stays read-only (the action is the door; the form field
  is not); the admin door carries no rule-17 parity obligation, so no
  REST/MCP surface is built for a product that does not exist · rejected:
  **ratify service-only** (leaves the one tree-reshaping primitive
  shell-only for every future support human; refusal grammar built for exactly this door goes unexercised by any
  user-initiated write), **a REST endpoint** (rule 17 drags an MCP twin; tenant-facing
  tree management is a product decision — the standing not-yet-real list
  says shop it) · trigger to revisit: the first product whose tenant
  admins reshape their own tree → the REST door then, with its parity
  twin, as that product's rung.
- **ADR core-14 (the append-only runtime belt)** · context: an
  instance-`.save()` tamper on an append-only member drove clean through
  the full gate — rule 20's AST half
  cannot see a bound-name save, and P4's DB grant protects production
  only · decision: `BaseModel`'s `save()`/`delete()` refuse the
  update/delete path for any model in the declared append-only population
  (`AppendOnlyViolation`), population-driven off `APPEND_ONLY_ATTR` at
  zero per-model cost; rule 20's static half learns bound-name instance
  saves (Q1); three belts stated honestly: static (gate) + runtime (this)
  + DB grant (P4, production) · rejected: a per-model mixin (re-opens ADR
  core-6's MRO churn for a property the declaration already carries),
  queryset-level `.update()` interception in the manager (rule 20's
  static half + the DB grant already cover the bulk path; a fourth belt
  at the queryset layer buys marginal coverage for real manager
  complexity — the declared residue) · trigger to revisit: a measured
  bulk-path tamper the two remaining belts miss.
- **ADR core-17 (first-tenant bootstrap)** · context: no runbook step
  creates the first tenant on a real
  environment; seed --force is forbidden there by design (the first
  environment was bootstrapped by hand); an earlier disproof left a
  residue to pin · decision: manage.py
  bootstrap_tenant — a @service-backed command minting exactly one tenant
  + root org + one owner membership for a named workforce email; refuses
  if ANY tenant exists; audits door=shell with tenant=the created tenant
  (the birth certificate); create_tenant stays unaudited ·
  rejected: auditing into the platform population (the row is about a
  tenant that now exists), relaxing seed for production (seed is dev data
  by contract), a web-based first-run wizard (a door with no
  authenticated caller yet — the shell is the honest door at zero) ·
  trigger to revisit: multi-tenant-at-birth products.
- **ADR deploy-1 — TWO decisions share this id**; both stand, both cited
  (`deploy/compose.yaml` cites both meanings on one file).
  **(a) the environment shape** · context: the Deployability pillar needs a real
  environment; the Hosting row ships everything a choice needs and
  presumes none; the ratified band is ~$40–90/mo, teardown-friendly, and
  every self-hostable organ was ruled self-host (ClickStack explicitly;
  Zitadel in the same breath) · decision: one EC2 Graviton box per
  environment running a production compose (web, worker, Caddy TLS,
  Temporal, Zitadel, Redis, otel-collector, ClickStack) + RDS Postgres +
  S3 + Secrets Manager; provision/teardown as plain `aws` CLI scripts in
  `deploy/`; the template's own environments run self-hosted Temporal
  (the Hosting row's recorded alternative, ratified as a
  divergence from "Cloud by default") · rejected: ECS Fargate + ALB + ACM
  (~$50/mo dearer before the first container, splits the compose into
  task definitions, and teardown-friendly it is not), Kubernetes (the
  row's own words: an escalation, not a default), Postgres-in-compose for
  the environments (forfeits the managed-snapshot half of the backup
  posture B1 drills), an IaC framework (a toolchain tax at one box per
  env; the runbook must be performable by a stranger with aws-cli and
  ssh) · trigger to revisit: a second standing environment, a real
  product's traffic, or the box's memory headroom measured under 20% at
  V1.
  **(b) the Postgres major pinned at 18** · context:
  RDS runs 18.3, every pinned client 16.10, pg_dump refuses
  cross-major, and provision.sh lets AWS's default decide · decision: the
  template targets Postgres 18 (the reasoning: the live instance is
  the fact on the ground; client moves are cheap; pg_dump 18 reads 16
  worlds; EOL runway) — compose.yaml postgres:18, deploy/compose.yaml
  postgres:18.6 (latest 18.x minor), provision.sh --engine-version 18 +
  --auto-minor-version-upgrade · rejected: pin 16.10 + rebuild RDS
  (owner-approval infra act to buy a shorter-lived major), no pin (the
  finding itself) · trigger to revisit: a stack component
  (Zitadel/Temporal) refusing 18 — the rung's own stop-and-report.
- **ADR deploy-2 (names under one env-backed domain)** · context: the domain ruling makes one
  domain the platform's own surface — rehearsals, warm-up, the production issuer —
  with per-product subdomains later; a real deployment's chosen `.dev` domain is
  HSTS-preloaded, so every name is HTTPS from birth (the shipped default,
  `example.invalid`, is deliberately unresolvable) · decision: the environments-contract table
  in the plan — `<env>.example.invalid` for the app, `auth.` and `o11y.`
  prefixes per env, Temporal UI unexposed, SES identity on the apex with
  MAIL FROM `mail.example.invalid` · rejected: per-service apex names
  (`staging-auth.example.invalid` — flat namespace ages badly), a separate
  zone per env (two zones to keep consistent, $6/yr of nothing),
  exposing the Temporal UI behind auth (one more door to wall; the
  tunnel is the wall) · trigger to revisit: T0's product names land, or
  a second standing environment.
- **ADR deploy-3 (secrets are generated, materialized, and refused)**
  · context: the standing default is Secrets Manager
  injected as env — the app reads env only; guards.py refuses published
  SECRET_KEY / Fernet values but declares its boundary: DATABASE_PASSWORD
  unfenced and four compose-only values it structurally cannot see,
  with the belt assigned to "the first production deploy" · decision: (a) secrets generated by script straight into Secrets
  Manager, per-env prefix, no human in the path; (b)
  `deploy/entrypoint.sh` materializes them to the container env at start;
  (c) production refuses the published DB password by value (S1 —
  guards.py gains the check, the same shape as its siblings); (d)
  `deploy/assert_not_published.sh` refuses the four compose-only
  published values at deploy time, where they ARE in hand — the boundary
  paragraph's own assignment, discharged; (e) D8's belt: the app's DB
  role is revoked UPDATE/DELETE on the `append_only` population, emitted
  from the declarations (`deploy/grants.sql.py`), applied as a release
  step beside migrations · rejected: refusing compose-only values in
  guards.py (a gate standing in an open field — its own words), SSM-only
  (posture over pennies; the standing default names Secrets Manager for
  secrets), baking secrets into images (a registry is a backup someone
  forgets), Vault/OpenBao (the recorded escalation, unfired) · trigger to
  revisit: multi-cloud, dynamic DB credentials, or the first
  secret-rotation requirement with a deadline.
- **ADR deploy-3a (one JSON secret per environment)** · context: the cost
  table priced "~8 secrets × $0.40"; `provision.sh secrets-put` stores
  one JSON object under `<namespace>/<env>/env` · decision: one secret per
  environment, the manifest's names as keys; the cost table's Secrets
  Manager line becomes **~$0.40/mo** · rejected: one secret per value
  (eight fetches at start, eight rotations to coordinate, the same blast
  radius — the box's role reads the prefix either way) · trigger to
  revisit: per-value rotation with different cadences, or a second
  consumer that may read one value and not the rest.
- **ADR deploy-3b (`DATABASE_URL` empty; `PGSSLMODE=require`)** ·
  context: a URL wins over the parts (`base.py`), and a
  URL carrying no TLS parameter silently downgrades RDS to plain TCP ·
  decision: the manifest leaves `DATABASE_URL` empty and sets libpq's
  own `PGSSLMODE=require`, which every consumer (Django, `pg_dump`,
  `psql`) honors without a code path · rejected: `?sslmode=require` on
  the URL (only Django reads it; the backup script would not) · trigger:
  a second database consumer that does not speak libpq.
- **ADR deploy-3d (the belt at the deployment)** — the id
  `deploy/assert_not_published.sh`'s own header uses for clause
  (d) of ADR deploy-3 above; no separate ADR entry was ever written in
  any plan — the id names that clause. The clause, verbatim from deploy-3:
  "`deploy/assert_not_published.sh` refuses the four compose-only
  published values at deploy time, where they ARE in hand — the boundary
  paragraph's own assignment, discharged." The four:
  ZITADEL_MASTERKEY · ZITADEL_DATABASE_PASSWORD · POSTGRES_PASSWORD ·
  ZITADEL_ADMIN_PASSWORD (the script's header is the mechanism's own
  record).
- **ADR deploy-4 (2026-08-31) — build once, promote by digest** ·
  context: **one tree was built three times.** CI built `web` and `worker`
  single-arch, tagged them locally, checked the `USER` line, and let both die
  with the runner — so nothing CI built ever reached a box, and "CI-tested
  image" was a phrase with no referent. `deploy/compose.yaml` carried a
  `build:`, and runbook step 33 built the same tree a **third** time, arm64, on
  the Graviton box: the slowest and least debuggable machine in the system, at
  the moment of a deploy. Three builds of "the same" tree is three chances to
  differ — a base image that moved, a transient mirror, a wheel rebuilt — and
  nothing anywhere could say whether the amd64 thing CI proved and the arm64
  thing the box ran were the same software. · decision: **(a)** the image for a
  tree is built **once**, in CI's images job, `linux/amd64` **and**
  `linux/arm64` in one manifest, pushed to a registry under the derived tree tag
  `tree-<12hex>`; **(b)** that job runs `needs: gate` — a registry tag is a
  promotable artefact and `release.sh` will deploy anything the registry has, so
  an ungated tree must have no tag; **(c)** `deploy/compose.yaml` declares no
  `build:` anywhere and every app image is `${DJB_IMAGE_REGISTRY}/djb-<service>:
  ${DJB_IMAGE_TAG}`, both required and neither defaulted; **(d)** `release.sh`
  resolves the tag to an immutable **digest** before its first act — a tag the
  registry lacks is exit 2 naming the reference, a registry/pin disagreement is
  exit 1 naming both — and pins the released digest into the box's `TREE` marker
  **after** act 6's recreate; **(e)** `TREE`'s grammar becomes line-oriented
  (line 1 the tag, later lines `<key> <value>`) so it can carry that pin, which
  a legacy one-line marker still satisfies; **(f)** **promotion staging→prod is
  neither a re-tag nor a rebuild** — both environments point `DJB_IMAGE_TAG` at
  the same tree, resolve the same digest, and run the same bytes. · rejected:
  **moving environment tags (`:staging`, `:prod`)** — the industry-default shape,
  and it makes "which image is prod running" unanswerable *from the box*, which
  is the exact class of lie the `TREE` mechanism was built to remove; **keeping
  the box build as a fallback for a registry outage** — a fallback that only
  runs on the worst day is a path nothing exercises, and it re-opens the
  divergence the whole ruling closes (the honest trade is stated instead: the
  registry is now a deploy-time dependency, named in `docs/runbooks/deploy.md`
  step 33); **pushing from the laptop** — then the deployed artefact's
  provenance is a person's machine; **content-addressed tags only, no tree tag**
  — a digest a human cannot derive from a checkout makes every runbook step a
  copy-paste of an opaque string. · triggers, and both are cheap to notice:
  **base-image drift between releases** — two trees a month apart resolve
  different base layers and nothing here compares them, so the first product
  that needs reproducible builds re-opens this with a pinned base digest; and
  **a second architecture or a second registry** (a product deploying to
  something other than one ECR account) — `DJB_IMAGE_REGISTRY` is one prefix
  today and that is deliberate, not permanent.
- **ADR deploy-4a — SIGNED by the owner 2026-09-19 ("sign all three", recorded by the PM).** The text below is
  the amendment as the engineering lead wrote it, copied here unchanged for the
  owner to sign; nothing in it is settled until they do, and the builder who
  copied it may not flip this line. *"ADR deploy-4a (2026-09-19, owner) — the
  image is built by the acceptance box of the on-box bank, from the banked
  tree, after the composed verdict row is written and before the boxes go down;
  CI's `images` job keeps `needs: verdict` and skips a tag the registry already
  holds. Which principle: 6 (reversible — the skip is one step; delete it and
  CI builds again) and 7 (the critical path: a stage deploy no longer waits on
  a second full gate on GitHub runners). Why the default is insufficient: the
  CI build sits behind a 30-40 min gate re-run nobody here measures, so
  `pushed → staged ≤ 5 min` is unreachable while it stands. Alternatives: a CI
  job without `needs: verdict` (rejected — an ungated tag is a red tree one
  command from prod, deploy-4 (b)); building on the stage box (rejected in
  deploy-4). Risk: a box with push credentials — mitigated by the OIDC-shaped
  least-privilege role scoped to two repositories and the namespace tag, and
  the invariant that the build starts only after `gate_ledger_record` returned
  0 for the same tree. Reversal: remove the bank step and the skip; CI builds
  as before. Temporary or permanent: permanent, reviewed at the first
  registry/verdict disagreement (the trigger: `image-digest` present for a tree
  with no `full` row)."* · **one thing the signature also decides, surfaced by
  the build and not in the text above:** what the bank pushes is what the box
  can build natively — `linux/arm64` on a Graviton verifier box, measured at 39
  s a service, where deploy-4 (a) says one manifest carrying `linux/amd64` AND
  `linux/arm64`. Building both on the box means QEMU emulation for the half the
  box is not, which is the cost deploy-4a exists to remove; skipping CI's job
  for a bank-built tag therefore leaves that tree's tag single-architecture.
  Every machine this template deploys to today is arm64, so nothing is
  currently broken by it — but it is a narrowing of (a) and it is the owner's
  to accept, refuse, or spend the emulation on.
- **ADR events-1 — ERRATUM, not a decision.** This id is cited exactly
  once, in a fan-out totals note reading "the fan-out's total
  `1 + endpoints_for(t) x 5` — grows with subscribers — ADR events-1's
  fan-out shape", and **no ADR with this id was ever written**: not in
  `cycles/`, not in `archive/`, not anywhere in the repository's git
  history. The shape the citation points at is real and is the events
  spine's built dispatch design — one relay start plus one delivery
  activity per endpoint, in parallel, each with its own retry
  (`apps/events/workflows.py`; the machinery ADR events-3 and ADR
  events-4 describe). Recorded here as an erratum so the citation
  resolves to the truth about itself; no decision text is invented, and
  a future ADR wanting this number should take the next free one
  instead.
- **ADR events-2 (purge schedules namespaced by task queue)** ·
  purge schedule id + workflow id namespaced by task
  queue (`events-purge-expired:<queue>`, `system:events:purge:<queue>`);
  ensure_purge_schedule deletes the legacy global id when present
  (idempotent, logged). Revisit: a deployment wanting one purge across
  queues.
- **ADR ident-1 (Zitadel topology)** · context:
  compose ships one `postgres:16`; Zitadel needs Postgres · decision:
  one pinned Zitadel container + a dedicated `zitadel` **database on our
  existing Postgres service** (created by an init step, isolated by
  database not by instance), masterkey and first-instance config by env,
  and a **FirstInstance machine user whose PAT lands on a shared
  volume/env** — the credential our provider service authenticates the
  management API with · rejected: a second Postgres container (second
  stateful service, port pair, backup story for nothing), Zitadel Cloud
  for dev (the loop must run on a laptop, V3's lesson generalized),
  CockroachDB (Zitadel's other backend; heavier for zero gain) · trigger:
  production deployment → its own managed Postgres, recorded then.
- **ADR ident-2, amended (2026-08-30) — the console's own surfaces
  are observed, not reconciled** · context: `zitadel_audit` compared what
  our *rows* declare, so two classes of configuration no product manages
  through services — the org's **login policy** and the instance's **SMTP
  sender** — sat entirely inside rule 27's declared blind spot. Both were
  changed on the shared development instance by a sibling product and the
  audit still printed "Zitadel agrees with every row." · decision: **read
  them, print them, judge neither.** `zitadel.login_policy()` and
  `zitadel.smtp_configuration()` are GETs in the reads section;
  `zitadel_audit` prints an `observed` section that adds nothing to the
  drift count and cannot move the exit status, and the residual — what a
  clean verdict does *not* cover — now prints **beside the verdict** on
  every run under both verdicts, rather than living in a module docstring
  only a maintainer reads · rejected: **full intent-row machinery** (rule
  27's whole materialisation path — rows, services, an activity — built to
  guard drift only one actor can cause, and that actor is a person in a
  console we would still not be fencing: shop-the-price), and **a report
  line only** (names the blind spot without narrowing it, leaving the two
  changed surfaces invisible to the person reading the report) · trigger:
  **the first product that manages login policy or SMTP through services**
  — at that point an intent row exists, the comparison becomes possible,
  and these two move from observed to reconciled.
- **ADR ident-2, amended (2026-09-17) — the reconciler is BUILT; its
  trigger fired, and the trigger that is still open is SCHEDULING it** ·
  the original declined an auto-repairing reconciler and named its
  trigger, *first observed drift or first production deploy*: both
  happened (a one-field console edit to this deployment's own browser
  application lands a person on raw JSON at the identity platform and
  neither the audit nor the seed noticed; a one-way sync locked an owner
  out of the sibling product for a morning) · decision:
  **`manage.py zitadel_reconcile`** — a second command, not a flag on the
  audit, reading through the audit's own section functions (one read, not
  two), asking only services (the management call stays in the activity,
  house rules 10 and 27), `--dry-run`, exit 0/1/2, and an **ownership
  table in its docstring** naming every identity fact's authority, copy,
  settlement, staleness and repair kind (principle 9); the SMTP sender's
  OWNER is named and counted beside the audit's verdict, still judged by
  nothing · rejected: a `--repair` flag on `zitadel_audit` (a writing path
  inside the one command a deploy step trusts to change nothing) and a
  **Temporal Schedule** around the reconciler · trigger, still open:
  **a drift found in production that nobody in this deployment caused** —
  the command prints that sentence on every run.
- **ADR ident-5 — TWO decisions share this id**; both stand, both cited.
  **(a) test posture for Zitadel** · the settled decision: test posture
  for Zitadel mirrors the posture already settled for Temporal (ADR
  ident-5): the suite, `--loop` and CI never dial
  Zitadel — `config/settings/test.py` points the issuer at a
  must-not-dial address and the RP/JWT paths are proven against an
  in-process stub issuer (signed JWTs, real JWKS shape); only a
  dedicated verification pass drives the real container, and CI stays
  Zitadel-free. Rejected: suite requiring Zitadel up (every gate run
  leaking state into a shared service), mocking at
  the allauth layer (proves our config, not the protocol — the stub
  issuer signs real JWTs so JWKS/audience/expiry paths execute) ·
  trigger: first product CI needing a live-identity e2e leg.
  **(b) what erasure erases, and what survives with reasons** ·
  context: PII was found surviving `erase_user`
  in four tables; the docstring claims completeness it does not have ·
  decision: the sweep extends to allauth `EmailAddress` (rows deleted),
  allauth `SocialAccount` (rows deleted — the identity link is revoked
  Zitadel-side already), `SsoIdentity.email` (redacted to the
  `erased+<uuid>@invalid` form), `Invitation.email` (voided + redacted
  through `core.redact_invitations` — a platform-wide sweep keyed on the
  email, `system`-actor shaped, `# reach:` declared); retained
  populations each carry a written reason: `zitadel_sub` (the
  cross-tenant subject-collision fence — an opaque identifier, not
  contact data; verified against the A9 collision
  tests, stopping and reporting if the truth differs), memberships and
  `AuditEntry` (the docstring's own audit-trail argument),
  `Event`/`Outbox` payloads (declared not rewritten, by ruling) ·
  rejected: deleting allauth rows by cascade from User deletion (the row
  stays — settled), event-payload rewriting (the same ruling) · trigger to
  revisit: the first compliance ask (which also triggers the
  Event/Outbox archival residual).
- **ADR obs-2 (the sink is live, and it speaks)** · context: the
  Observability pillar's pending cell names this pass; the compose
  already ships otel-collector + ClickStack behind
  `--profile observability`; `core/observability.py` is the one
  configuration point; the announce-on-transition ruling gives P4 the
  ALERTING rung consuming degradation events, with hard deps explicitly
  outages (/readyz), not events · decision: staging runs the same
  collector→ClickStack pair as compose does locally, endpoint set by
  env; dashboards/saved searches/alert definitions live in
  `deploy/observability/` as exported config-as-code; alerts are
  ClickStack-native over the sink — the closed alert census: (1) each
  declared transition-event pair (today exactly
  `comms.suppression.surged`/`.recovered`), alert opens on surged,
  closes on recovered — the 1:1 the transitions-only design bought; (2)
  a /readyz probe from the collector's healthcheck receiver (or blackbox
  equivalent in the compose) alerting on N consecutive failures;
  delivery to the owner's Slack webhook; the escalation path documented
  in `docs/runbooks/alerts.md` (who, what they read first, re-ping
  cadence) · rejected: alerting through comms itself (comms is a product
  organ under test — the monitor must not share the patient's failure
  domains; the ruling's "comms can route it" stays open for products,
  with the spine events already there), CloudWatch as a second sink (G1:
  a second sink is where the reconstructing query dies; CloudWatch keeps
  only what AWS emits for free), per-request alerts (the ruling forbids
  them — transitions only), a new house rule for "every circuit alerts"
  (the second-circuit extraction is the ruling's own named trigger; not
  yet) · trigger to revisit: the second runtime circuit lands (extract
  the shared primitive, then consider the rule), or telemetry volume
  outgrows the container (ClickHouse Cloud w/ BAA, the documented
  scale-up). **Amended (the PM's ruling, recorded by the lead), appended
  to the decision sentence:** "Alert lifecycle, corrected: ClickStack
  alerts are windowed counts with
  auto-resolve — they cannot close on an event. So an alert **opens on
  the degradation event** appearing in the sink and **auto-resolves
  after N quiet windows** (N a declared constant in the definition,
  stated in `alerts.md`); the **recovery event is its own notification**
  (one message, the 1:1 the transitions-only design bought, delivered as
  a second alert rather than a close). Two non-event alerts stand beside
  the event pairs: the /readyz probe and the deaf-sink probe, both on
  the prober's own POST because neither can ride the sink. The census
  derivation names the event half by AST and the probe half explicitly."
- **ADR platform-partition-1 (the three cross-app moves the platform
  partition needed)** · at the freeze ·
  **the design and the authority is
  `docs/product/partition-closure.md`**, which ships; this entry is its
  ADR line per the ADR-home rule above, and records only the three
  decisions that reach across apps. · **context:** the partition skips
  the platform's pytest suite under a banked verdict whose key still
  matches everything that suite reads. A driven audit planted a product
  app (`apps/orders/` with a `TAGS` dict) and found **a false red on
  three in-closure tests** — not a stale green but a red a clone cannot
  clear without editing platform files, so the closure hash moves on the
  product's first door and the dividend dies there. The shape is
  general: a platform test that needs a per-member fact about a
  discovered population, sourcing that fact from a central in-closure
  file. · **decision, three moves** — (a) **D1**, the freeze census
  leaves the closure: `FROZEN_FAMILIES` and `SANCTIONED_RENAMES` move
  from `apps/core/api/scopes.py` into `apps/core/api/frozen_families.py`,
  re-exported unchanged, and that one file is the closure's **one
  enumerated exclusion** — it re-enters the skip key through the
  discovery digest's `scope_families` section, so a product's append is
  an out-of-closure edit that still buys an honest re-run; (b) **D2**,
  the two-planes guide's plane assignments move from `docs.py` prose
  onto each family's own `Tag` (`plane`, `plane_note`), and the guide
  renders from the registry — the property the platform already claims
  for the vocabulary, extended to its documentation; (c) **D4**, the
  exports census's hand-pinned assertions scope their quantifier to the
  lockfile's apps (`quality/partition.yaml`), because "pinned" was
  always a property of THIS TREE; the derived-side assertions stay
  global, since a product model must join the archive census and does.
  · **the generalized rule, cited into the architect's checklist:** a
  platform test that needs a per-member fact about a discovered
  population sources it from **the member's own declaration**, never
  from a central in-closure file; a central ledger products must append
  to either lives out-of-closure as a data module that re-enters the key
  through the digest, or the assertion scopes its quantifier to the
  lockfile population. · **rejected:** a `platform = True` marker on
  `AppConfig` (puts the boundary in code the product owns — the
  partition would skip on the product's own say-so); per-app freeze
  ledgers (a vanished app deletes its own memory, and the census exists
  to outlive what it remembers); leaving the plane in prose and widening
  the census test (it would stop asserting the thing it exists to
  assert). · **trigger to revisit:** a second exclusion is wanted — that
  is a design change to `partition-closure.md` §3, not an edit to the
  lockfile.
- **ADR workflows-2 (duplicate start → idempotent-return)** ·
  duplicate start → idempotent-return (docstring wins):
  existing RUNNING row + matching type returns the row, client start
  attempted, WorkflowAlreadyStartedError swallowed (also heals
  row-without-run); type mismatch on live id → Conflict; terminal row →
  Conflict. Revisit: re-run-after-completion = a new key, ruled then.
- **ADR workflows-3 (WorkflowRun scoping)** *(moved
  verbatim from
  `cycles/2026-08-22-cycle-p1-workflows-pay-their-debts.md` §ADRs)* ·
  2026-08-22 · context: `WorkflowRun` is tenant-required, so
  deployment-wide work has no ledger — erasure of a person with no
  tenant *skips identity revocation* and logs
  `accounts.identity.not_revoked` (a real hole pinned by test), and
  workforce identity sync borrows a tenant to get a row · decision:
  **`WorkflowRun` is the platform-wide run ledger** — `tenant` becomes
  nullable (an abstract-base field override; ONE expand migration,
  riding W1's leaf), and **null is a declared population, not a
  loosening**: a platform run's workflow id carries `PLATFORM_SEGMENT`
  (`"platform"`) as its first segment, `check_workflow_id` requires that
  segment iff `tenant is None`, `for_tenant(...)` keeps failing closed
  (it can never see a platform row, so every tenant door — REST, MCP,
  admin via `ServiceModelAdmin.get_queryset` — is unchanged by
  construction), and `for_platform()` is the one read path for the null
  population. `create_tenant` refuses the slug `"platform"`,
  because `SlugField` would otherwise mint a tenant whose runs collide
  with the platform's — the segment must be un-mintable, and a guard at
  tenant creation is the closed question that makes it so · rejected:
  **a system tenant** (a synthetic member of a real population is a lie
  every future query over tenants — billing, counts, admin lists, loops
  — must remember to exclude; and rows of *other* models would accrete
  onto it), **status quo + named gaps** (this is an erasure-compliance
  hole; naming it does not deactivate the Zitadel account) · trigger to
  revisit: a second model needs a platform population → decide then
  whether the nullable-with-declared-population shape generalizes or a
  platform scope becomes a first-class base.
- **ADR workflows-4 (intent digests)** · context: a deterministic id
  makes a retry ask for the
  *same* run — but `record_run` returns the existing row and
  `_start_recorded` swallows `WorkflowAlreadyStartedError`, so a caller
  asking for the same id **with different work** is silently answered
  with somebody else's run and its new intent is dropped · decision: `WorkflowRun.input_digest` (sha256 hex over the
  run's `arg`, serialized through Temporal's own default payload
  converter so the bytes are the bytes the run would carry), computed
  **inside both starters** — never by callers — and passed to
  `record_run`, whose answer becomes a 2×2: *live + same type + same
  digest* → the existing row (the retry/heal, unchanged) · *live +
  different type or different digest* → `Conflict` (the honest 409 — a
  different intent under a live id is a second job, not a retry) ·
  *finished + same digest* → `Conflict` (re-running completed work is a
  decision about a new key; unchanged) · *finished + different digest* →
  **supersede**: the row re-opens (status RUNNING, new digest, cleared
  `run_id`/`finished_at`/`error`, new `started_at`) and Temporal's
  default id-reuse policy starts a fresh execution — which is the
  interlock the brief names: once the `_finish` wrappers close move
  runs, a completed move must not fossilize the node's id forever ·
  rejected: per-caller digest parameters (optional grammar that misses
  the exact shape needed), digest-in-the-id-segment (two different-parent
  moves would get two *ids* and run concurrently over one subtree — the
  id must serialize and the digest must refuse), refusing *finished +
  different digest* too (fossilizes every re-move; the row is
  visibility, not an append-only ledger — it declares no `append_only`
  and supersession is its honest lifecycle) · trigger to revisit: a
  workflow whose `arg` is legitimately non-canonicalizable through the
  payload converter.
- **ADR realtime-3 (door parity for sockets is a test per door pair, not
  a wider rule 17)** · context: rule 17 diffs two *registries* (routes vs tools)
  and proves existence; its own `does_not_cover` says "socket and
  webhook parity (the spine pushes the same envelope by construction)" —
  This is a socket disagreeing with itself across two credentials, a
  *behavioral* parity failure inside one consumer, which no registry
  diff can see even for REST↔MCP (the same `does_not_cover` says so for
  shape) · decision: rule 17's subject stays REST↔MCP; socket parity is
  a **parity test per door pair** in the owning app's tests — session
  socket vs bearer socket on one org-scoped emit, and the
  existing REST-vs-MCP parity test in `example` is the shape's
  precedent; rule 17's `does_not_cover` is amended (one line, granted — this ADR does not edit `quality/**`)
  to stop claiming "by construction" and to name the test · rejected:
  growing rule 17's subject to sockets (there is one consumer and no
  second registry to diff against — a rule with nothing to count is an
  unbound floor by construction, exit 2 forever or a hand list); a new
  rule over "every ASGI middleware that sets `scope['user']` also sets
  `scope['org']`" (two sites today, one of them the fix — a rule born
  with a population of two and a canary that is the bug it just fixed;
  the trigger to revisit is the third site) · trigger to revisit: a
  second consumer, or a third credential path (the OAuth 2.1 socket
  bearer named in architect H), either of which makes a registry diff
  meaningful.

**How bytes come back out is the ratified either/or, applied rather than re-decided**: the files seam always signs — `bucket_name()` refuses a deployment that has named no bucket, so a files object only ever exists where a signing backend is configured — so `download_url` is filled by `presign_get` and a `/download` door over a files object may 302 to it. No `get_stream` ships and none is owed; a backend that cannot sign is an ADR-level change, not a fallback. The bucket a checkout uses is written into `.env` by `scripts/setup.sh` (via `manage.py ensure_bucket`), so `/readyz` carries its `storage` member on a laptop.

**`search`, as at the app-map delta (R-a) — three corrections to its own row above.** (a)
**There is no `SearchDocument` model and there will not be one**: the documents
live in Meilisearch, which is a derived view of Postgres and never a source of
record, and the tsvector column the degradation engine reads belongs to the
*adopting* app's model with that app's own migration (R-e). A central projection
table would be the shadow authorization copy ADR search-1 rejected and search-2
did not reinstate — so `apps/search/migrations/` does not exist, on purpose, and
house rule 31 has nothing to declare here. (b) `depends_on` is `core, accounts`
until the spine tap lands: nothing in this app emits or subscribes yet, and an
app declaring a dependency it does not use is a dependency nobody can later
remove. (c) The workflow is the **declaration-digest startup reconcile** rather
than a per-tenant reindex (the owner's ruling of 2026-08-24, `design-agreements.md`,
"Search materializes from its declarations"): each kind's index stores the digest
of the declaration that built it, every worker boot compares them per kind, and
missing-or-different rebuilds through one deterministic, serial, atomically
swapped run while a match does provably nothing. `manage.py search_reindex`
(R-c) is demoted to the manual backstop by that, exactly as the Zitadel console
was. What else landed in R-a: the chokepoint (`selectors.search`, one Postgres
query for the visible-org-id list, per-kind filter shapes, fail-closed on both an
absent tenant and an unresolved hat), the fenced engine (house rule 33), both
doors under the cursor envelope with `SearchPage.engine` on the wire, and the
door-pair parity test — **R-a is where `DOOR_PAIR` is declared**, not R-e,
because the two doors are born here.

**`usage`, as at the app-map delta (U1) — the seam is real, not a stub.** `depends_on` gains
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

**`files`, as at the app-map delta (F1) — the models and the seam, and the row above was
wrong.** Three corrections, all of them to make this table agree with ADR
files-2's own § "Events / workflow split", which post-dates the row: the sweep is
`SweepPendingUploads` and not `SweepAbandoned`; the events are
`files.file.stored` and `files.file.archived` and not the four-name
created/version_added/archived/purged set (the ADR rejects a
`version_superseded`-shaped event outright — promotion rides `stored`'s payload —
and `purged` cannot be emitted by a purge that v1 excludes); and `depends_on` is
**two apps today**, because a dependency declared before anything imports it is a
permission nobody asked for and house rule 7 reads that tuple as a ceiling.
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
user-supplied filename. (The old `apps/core/storage.py` was superseded by this
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
   static sites, single-user tools. Twenty-six house rules and an audit
   trail are overhead until there is a team whose mistakes they catch and a
   customer whose trust they earn.

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
  locked a consumer's owner out of their own deployment for a morning (their
  N1355, measured on the pinned build). So the two doors are a
  WHOLE-DEPLOYMENT switch (`SIGN_IN_DOOR`, ADR ident-9's amendment and design
  I-A §2) and never a per-step fallback: under `ours` a step this page cannot
  ask for reads a sentence and ends the ceremony, and under `hosted` the
  platform draws every screen. *Trigger to revisit*: a build where the hosted
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
- **DBOS** (durable execution on Postgres alone) — attractive ops profile, but younger and thinner in the field; revisit if Temporal's operational weight becomes the problem.
- **Processing inbound webhooks inline.** A slow or failing handler loses the event; verify, store, hand to a workflow.
- **SQLite for local/tests.** Hides the Postgres behaviour the product depends on.
- **Fat-model-only business logic.** Agents scatter logic into signals and
  2,000-line models; an explicit services layer is the one that can be
  house-ruled.
