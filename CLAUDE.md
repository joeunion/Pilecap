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

## The gate

The gate is `./scripts/check.sh` — `--fast` (pre-commit runs it) · `--loop` (the
builder's per-rung gate) · no argument (full; records a verdict in the ledger
keyed on the tree hash; pre-push consults the ledger and does not re-measure a
green tree). **Exit 0 clean · 1 violations · 2 enforcement broken.** 2 outranks
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

The starter rules, by id as `architecture.md` numbers them (`rules.yaml` is the
text): **1** `auth.User` never imported · **2** every concrete model inherits
`BaseModel` · **3** every route carries an explicit `auth=` — on its router or
on the route — never `auth=None` outside the `rules.yaml` allow-list; every
list route is `@paginate`d · **4** no business logic in signals; services own
writes · **5** query budgets on list endpoints at seeded scale · **6** one
migration leaf per app · **7** app import contracts hold · **8** scoped models
are read through `for_tenant(...)` · **9** workflow code is deterministic — no
ORM, network, clock or randomness in a `workflows.py`; all of it lives in
activities · **10** every door calls services — tools, consumers, routes,
activities and receivers never write to a model directly · **11** every app
keeps the canonical file shape — a `utils`/`helpers`/`logic` file doing a
canonical job is a violation · **12** reads and writes are separate:
`selectors.py` never writes; `services.py` never returns a queryset for
display · **13** every write in `services.py` is `@service` — keyword-only,
audited — and a service that resolves an actor authorizes
(`authz.require` or `# authz: <reason>`); a scoped model's writes have a
`policies.py` entry · **14** HTTP vocabulary never appears below the doors —
services raise `core.exceptions.*`; the one mapper lives in `config/api.py` ·
**15** field policies: no `FloatField` on money or quantity, `DateTimeField`s
end `_at` and `DateField`s `_on`, `on_delete` explicit and never `DO_NOTHING`,
no `is_deleted` booleans, and a secret-shaped field (`secret`/`token`/`credentials`/`signing_key`, `*_hash` excluded) is a declared encrypted type · **16** the naming grammar holds — apps plural, models
singular, services verbs from the declared lexicon, selectors `get_`/`list_`,
schemas suffixed `In/Out/Patch/Filter/Page`, booleans `is_`/`has_`, and events
`<app>.<noun>.<past-verb>`, declared in the app's `events.py`, never a literal
at a call site · **17** door parity: a capability on REST is on MCP unless
exempted in `rules.yaml` with the reason · **18** workflow ids are
deterministic — built by `workflow_id()`, never random — a house-shaped `platform:` constant also passes, and the starters themselves may not grow an id default · **19** structured
logging only, through `core.log` — no `print`, no bare `logging.getLogger`, no
f-string in a log call · **20** append-only is a declared population, not a
name — a model that declares `append_only = True` may have rows created and
nothing anywhere updates or deletes one; `AuditEntry` is the first member and
the gate reads the population off the declarations · **21** every admin on a scoped model
inherits `core.admin.ServiceModelAdmin` · **22** migrations are
expand/contract — no non-nullable `AddField` without a default, no
`RunPython` without a reverse, no drop while the code still references the
name · **23** supply chain clean — `pip-audit`, no AGPL/GPL dependency, no
secret in the tree · **24** an org-scoped model is read
`.for_tenant(t).visible_to(actor_or_org)` — the second half is not optional —
or `.governing(org)`, which is upward config resolution and never upward
visibility, and is legal only on a model that declared `InheritedDownward`;
`Membership.role` is written only by the membership services (the escalation
wall) and `Organization.path`/`.parent` only by the organization services ·
**25** `comms.send()` is the only legal sender — no module under `apps/`
imports a mail module outside the `rules.yaml` allow-list, because consent,
quiet hours and suppression are enforced inside `send()` · **26** a service
names nothing the actor could not have reached — a `@service` that writes an
org-scoped row and takes a parameter annotated with an org-scoped model passes
it through `core.authz.may_be_named`, or carries `# reach: <reason>` on the
parameter, counted and printed. · **27** one door to the identity
platform — identity configuration is written through services onto our rows
and materialised in Zitadel by one activity (**the row is the intent; the
console is a window, not a door**): no module outside `apps/accounts/zitadel.py`
names `ZITADEL_PAT` (`config/settings/` excepted, where the environment is
read) and only that activity and the `zitadel_*` commands import it, because
an external call inside a service's transaction is a hiccup that rolls back a
legitimate row; `manage.py zitadel_audit` is the read-only drift tripwire for
the console, which no check can see. · **28** every workflow class
closes its run row through the finish seam or declares `owns_no_run = True` —
the ledger never lies by omission · **29** a role value that arrives as a
parameter or configuration is bounded against the granter's own ceiling at the
model write — nobody grants above themselves through a config field either ·
**30** a declared retry-clock field (`next_attempt_at` and its shapes) has a
production reader — a schema built for a poller that was never built is how an
outbox strands events silently.

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
