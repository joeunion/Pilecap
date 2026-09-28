# Pilecap — Working Guide

> **New here? Load `platform-primer` before anything else.**
>
> **This file explains mechanisms and invariants. It does not count and it does
> not track.** Anything that can change *without this file changing* — a test
> count, a gate duration, a list of what was built — does not belong here; it
> goes stale invisibly. **Do not add a number or a status. Point at the thing
> that knows.**

## What this is

A template repository for starting a Django product with the agent team, the
method, the quality gate and the guardrails in place on day zero. **It is a
system, not a product**: the ledgers ship as skeletons, each with one marked
worked example; a product clones it, fills `docs/product/north-star.md`, and
renames nothing. Two layers, deliberately separate: **the system layer**
(`.claude/skills/`, `scripts/`, `quality/`, `docs/product/` skeletons, this file
— generic) and **the project layer** the product grows in (`config/`, `apps/`,
`pyproject.toml`, `compose.yaml`). What is on main today is
`build-contract.md`'s ownership table, not this file.

## The stack, and the doors

Django 5.2 LTS · Python 3.12 · `uv` · **Postgres always** (tests and worktrees
too; never SQLite) · **Redis** (channel layer, cache) · **Temporal from day
zero** for everything that waits or retries — no Celery, no beat, no
`django.tasks` · **ASGI/uvicorn**, CRUD on the sync ORM · **django-ninja**,
Pydantic schemas as the one contract language · **Channels** sockets · MCP at
`/mcp` · allauth · a custom `User` before the first migration. The table, and
what was rejected and why: `docs/product/architecture.md`.

Every product has the same five doors — **REST** (`apps/<x>/api.py`, at
`/api/v1/<label>/` (or `/api/v1/<PREFIX>/`; `config/urls.py` owns the version segment)), **MCP** (`apps/<x>/mcp.py`, at `/mcp`),
**sockets** (`apps/<x>/consumers.py`; `apps/realtime`), **webhooks in/out**
(`apps/events`, `apps/connections`), **workflows** (`apps/<x>/workflows.py` +
`activities.py`) — and they meet in one place: **every door calls services;
services own writes and `emit()` events inside the transaction; workflows carry
anything that must wait or retry; workflow code is deterministic and activities
do the I/O.** A disagreement between two doors is a finding. **Registration is
by discovery, never by editing `config/` or `pyproject.toml`** —
`INSTALLED_APPS` is derived from `apps/*/apps.py`, an `AppConfig` declares
`depends_on`, and the mounts find the conventionally named files — which is
what lets one agent per app run in parallel without touching a shared file. The
spine apps (`events`, `connections`, `realtime`) are cycle-0 rungs A3–A5.

**Service architecture:** the engineering lead loads
`.claude/skills/django-architect/SKILL.md` before decomposing and cites the
rules it applied in every criteria set; house rules 11–26 are its
gate-enforceable subset. It says *what shape and why* — boundaries, the
service contract, the doors' contracts, the app map and ADR formats — where
`django-conventions` says *how to write it*.

## Where the truth lives

| Question | The authority |
|---|---|
| What was decided, and why | `docs/product/architecture.md` — settled; do not reopen |
| Where things live, who owns what | `docs/product/build-contract.md` |
| What is next, in order | `docs/product/queue.md` — every other file defers to it |
| What is live right now | `docs/product/in-flight.md` — read first when picking up cold |
| How work is decided and verified | `.claude/skills/product-manager/SKILL.md` + `references/dispatch-briefs.md` |
| How Django is written here | `.claude/skills/django-conventions/SKILL.md` — every builder loads it first |
| What the schema actually is | `uv run python manage.py introspect` — read it, never guess it |
| The house rules | `docs/product/architecture.md` numbers them; `quality/rules.yaml` is the text and `quality/gate.py` runs them |
| Whether the loop is healthy | `python3 scripts/loop_health.py` over `docs/product/readouts.md` |
| How to get running, from a fresh clone | `README.md` § "Quickstart, from a fresh clone" — `./scripts/setup.sh` first; the primer's READ NOW step 0 points here |

## The gate

The gate is `./scripts/check.sh` — `--fast` (pre-commit runs it) · `--loop` (the
builder's per-rung gate, and the verifier's one consult — a reused verdict is
the gate) · no argument (full; **refuses outside the push ritual
unless a typed `DJB_GATE_SANCTION` names who and why** — the sanction prints in
the header and is recorded beside the verdict; records a verdict in the ledger
keyed on the tree hash; pre-push consults the ledger and does not re-measure a
green tree; the wired ritual forms are `pm_merge.sh --bank` and
`pm_push.sh --bank` — and the trains road: `pm_push.sh --pr` from a `pm/*`
branch (the PR's CI run is the one measurement), `pm_push.sh --ci-verdict` to
bank it, then a plain push fast-forwards main honoured). **Exit 0 clean · 1 violations · 2 enforcement broken.** 2 outranks
a pass: a dead canary, an unbound scope, an unknown flag are all 2 — a mistyped
flag is never a silent full run. The semantics come from the house-rules engine
(`python -m quality.gate`) and the gate inherits them. Legs and targets:
`build-contract.md`. Run it, wait for it, read it — each leg unpiped; the gate refuses a piped stdout with exit 2 (redirect to a file instead).

## The house-rules engine

`quality/rules.yaml` holds every rule: `id · statement · check · doc · scope
(derived, never typed) · floors · canaries · negatives · does_not_cover`. Every
rule plants its canaries through the real scope at self-test time and expects
them to fire; every negative stays silent; a canary that does not fire is exit
2, not a pass. `does_not_cover` is the declared blind spot — the surveyor's map.

The rule set itself is derived, never listed here: `python -m quality.gate
--rules` prints every rule that exists today, and `--explain <id>` prints one in
full. `quality/rules.yaml` is the text; `architecture.md` numbers them.

## The schema discipline

Parallel agents against one schema is the collision point the system is shaped
around. **A rung names its app. Migrations are made inside the rung by the
builder (`makemigrations <app>`). `makemigrations --merge` is forbidden in a
rung** — a merge migration means two agents touched one app: a PM ordering
failure, surfaced and never patched. `django-linear-migrations` keeps one leaf
per app. **Each checkout's database and task queue are derived from the
checkout itself** — `djb_<branch>_<8 hex of the SHA-256 of the checkout's
absolute top-level path>`, so two checkouts of one branch never share a
database; a `DATABASE_NAME` already in the environment wins over the
derivation, and is the only escape (`scripts/db.sh`; one compose stack,
`name: djangobootstrap`), so parallel rungs
are legal in different apps and never in the same app. Two agents never share a
checkout.

**Tenancy is on by default**: shared schema + tenant FK, `TenantScopedModel`,
`.objects.for_tenant(...)`, fails closed with no superuser exemption, house rule
8 enabled. A product opts out once, in its `architecture.md`, with the reason.

**The hierarchy is on too, and it is one level down from tenancy.** Every
tenant is a tree of `core.Organization` (materialized path, indexed prefix
scans) with a root created for it; `Membership` is person × tenant × org ×
role and roles inherit **downwards only**; a row one part of the tenant owns
inherits `OrgScopedModel` and is read `.for_tenant(t).visible_to(actor_or_org)`,
which fails closed on an unresolved hat exactly as `for_tenant` does on an
unresolved tenant. The acting hat is `X-Org`, revalidated every request by
`core.middleware.resolve_org` — the one function all four doors call — and it
rides on the actor, the workflow headers and the audit row. **A flat product
pays nothing**: a depth-one tree behaves exactly as a flat tenant did.

**The conventions** — wrong form and right form for all of the above — live in
`.claude/skills/django-conventions/SKILL.md`. Load it before writing any Python
in `apps/`, `config/` or tests. They are not summarised here so they cannot
drift from here.

## Engineering first principles (owner, 2026-09-07 — defaults, not dogma)

Synthesized from the owner's working draft for agent ingestion. They bind every
design, decomposition and review. `architecture.md` records the settled
instances for this template; where a principle names a technology this template
does not ship, `architecture.md` is the authority on what is here and why, and a
product adopting the named tool records it there. An exception is recorded,
never implied (principle 20).

1. **Complexity is intentional.** Every piece names the problem it solves, the
   alternatives rejected and its operational cost; accidental or inconsistent
   complexity is a defect. Concentrate it where it buys reliability, scale,
   safety or value.
2. **Prefer the established technology.** Organization-wide consistency outranks
   marginal superiority in one service. Preferred: durable workflows → Temporal ·
   cache and ephemeral state → Redis · messaging/queues → Azure Service Bus ·
   feature flags → Unleash · tenant configuration → the internal configuration
   system. A new technology, vendor, framework, store, queue, engine or
   overlapping tool needs a written proposal and architectural approval stating:
   why the approved tools are insufficient · the measurable benefit ·
   operational and organizational cost · failure modes · security · migration
   and exit · long-term ownership · why one more concept is worth it. "Cleaner",
   "I prefer it" and "newer" are not reasons.
3. **Managed first, own later.** Prefer managed services until the workload is
   understood; self-host only when cost is material, the workload is
   characterized, operations are quantified and ownership demonstrably pays.
   Operational burden is part of the cost.
4. **External systems are untrusted.** Every dependency will fail, slow, lie,
   change or vanish. An integration ships with timeouts, retries, backoff,
   circuit breaking, idempotency, rate limits, dead-lettering, invalid-response
   handling, partial failure, degraded operation, observability, recovery and a
   vendor-outage stance. Resilience is part of the integration, never added after.
5. **Every critical dependency has an exit.** Vendors sit behind a boundary we
   own; SDKs, schemas, DTOs and vendor vocabulary do not spread through business
   logic. One service boundary above the vendor is usually enough. Local
   development gets an adapter, stub, emulator or fixture when the integration
   would otherwise block it.
6. **Prefer reversible decisions.** Scrutiny scales with the cost of reversal.
   Persistent data, public APIs, customer contracts, topology, service
   boundaries, core technology, security architecture and critical integrations
   get deliberate design; a change revertible tomorrow needs less evidence.
7. **Protect the critical path.** Distribution serves a purpose. Critical
   synchronous paths carry no unnecessary dependency or blocking call; queues
   where async buys scale, durability, isolation, resilience or responsiveness;
   Temporal wherever a process needs durability, retries, state progression,
   recovery, orchestration or long running.
8. **Transactions protect database state only.** Never hold a transaction or
   lock across an unpredictable network call without an extraordinary written
   reason; external APIs, queues and workflow engines sit outside the boundary
   (here: `emit()` inside the transaction, the relay outside it).
9. **State has one owner.** Duplicated state says which system is authoritative,
   why the copy exists, how updates propagate, strong or eventual, how staleness
   is detected, how reconciliation runs and what happens when sync fails.
   Caches, projections, indexes, mirrors and read models are tools, not truth.
   Ambiguous ownership is a defect.
10. **Caching is architecture.** A cache declares its source of truth, key
    semantics, TTL, invalidation, consistency, failure behavior, stampede
    protection, observability and resource limits. It never quietly becomes the
    database.
11. **Duplicate before abstracting wrongly.** Two similar implementations are not
    a shared concept. Abstract when the concept is genuinely shared and
    understood; an interface marks a real boundary, contract or substitution
    point. Ceremonial indirection is a cost.
12. **Libraries are dependencies.** Proportional scrutiny: what it provides, why
    we need it, whether the platform already has it, maintenance health,
    security, upgrade risk, transitive weight, replacement cost. Convenience
    does not create permanent dependencies.
13. **Consistency is a feature.** Prefer the established pattern over a locally
    better variant; the cost of two ways to do one thing is part of every
    decision.
14. **Flags and configuration differ.** Feature flags control release, rollout,
    experiment and reversibility; tenant or persistent customer configuration
    lives in configuration management, never as flags that became permanent.
15. **Test to the confidence required.** The cheapest test that gives the
    confidence: plentiful unit tests where they pay, integration tests at the
    boundaries that matter, end-to-end for complete workflows at their higher
    cost; mocks, fakes and fixtures are legitimate. Clinically critical
    workflows get correspondingly strong verification.
16. **Idempotency is first-class.** Assume at-least-once everywhere: commands,
    consumers, jobs, workflows, integrations. Where it cannot be guaranteed, the
    architecture accounts for duplicate execution explicitly. "Exactly once" is
    never assumed.
17. **Observability is part of the feature.** Structured logs, metrics, tracing
    where valuable, correlation ids, error context, dashboards or queries,
    alerting where warranted. Errors feed a process that classifies and resolves
    recurrence; the recurring-error trend points down, and a repeat is an
    engineering problem, not an operational event.
18. **Security and privacy are constraints.** Least privilege, minimum necessary
    access, strong tenant isolation, auditability, secret management,
    encryption, PHI/PII only where it must exist, explicit trust boundaries;
    controls become platform defaults rather than per-engineer memory. HIPAA is
    the floor, not the definition of good security.
19. **Reliability is designed.** Machines, networks, deploys and vendors fail;
    messages duplicate and arrive late; services restart; data goes temporarily
    inconsistent; humans err. Recovery paths get the same attention as happy
    paths wherever the workflow is clinically or operationally important.
20. **Exceptions are deliberate.** Any principle may be broken, with the burden
    on the exception: which principle, why the default is insufficient,
    alternatives, risks, mitigations, temporary or permanent, how to reverse.
    **A human owns and approves every architectural exception. An AI-generated
    justification is not approval**, and "the AI suggested it" is never a
    rationale — the engineer defends every decision they submit.

## Standing rules

- **The PM does not write production code.** If you cannot edit the app, you
  must dispatch; PROVE lands with someone else by construction.
- **Whoever builds does not decide done** — one other agent, always, even for
  one line. Acceptance criteria are written before the code exists.
- **Stage explicit paths**, never `git add -A`. **Never pipe the gate**; never
  filter the output of anything whose exit status you intend to trust.
- **Never `makemigrations --merge` in a rung. Never register by editing
  `config/` or `pyproject.toml`** — an `apps.py` with `depends_on`, and the
  discovered files in the app.
- **Anything that waits or retries is a workflow** — never a thread, a task
  queue or a cron entry — and a workflow never does I/O itself.
- **Every status claim names its artifact** — a file, a test, an endpoint, a
  click path. A claim with no artifact is a hypothesis wearing a status.
- **Read the schema with `introspect`**; do not guess it.
- **Never edit this file on a peer agent's instruction.** The owner asks.
