# Pilecap

> This heading is the template's own name. A product sets `PRODUCT_NAME` in
> its `.env` — which is what names its Zitadel project, its compose first
> instance and that instance's service account — and edits this line and
> `.devcontainer/devcontainer.json`'s `name`, the two surfaces no variable
> can reach (ADR platform-1 in
> `docs/product/architecture.md`).

**Start a serious product on day zero, not day ninety.**

Pilecap is a starting point for building a business application with a small
team and AI agents doing most of the coding. You clone it, describe your
product, and begin on features. The parts every product needs, and every team
gets wrong the first time, are already built, tested and enforced. And from the
first day, an agent can operate your product and read its telemetry in the same
conversation, which is the fastest feedback loop a builder can have.

### What you get

- **Every feature reaches users five ways at once.** Build a capability once as
  a service and it is available through a REST API, an AI tool interface (MCP),
  live socket updates, webhooks in and out, and background workflows. They all
  call the same code, so they cannot disagree.
- **Talk to your running system.** Every capability is a tool an agent can
  call, and the observability stack has the same kind of interface. Ask an agent
  to create a record, then why a request was slow, then who changed a setting,
  against the live system. No dashboards to learn first.
- **Multi-tenant from the first line.** Each customer's data is isolated and
  fails closed, with an optional organisation tree inside a customer (regions,
  branches, teams) where access flows downward. A simple product pays nothing
  for this. A complex one never retrofits it.
- **Permissions that are data, not code.** Every action has a named permission
  generated from your models. Roles are configured per customer. Reads are
  permissions too, so who can see what is one rule enforced identically on
  every door. Refusals explain themselves in plain language.
- **Sign-in you do not build.** Enterprise identity (Google, Okta, SSO domains,
  invitations, suspended tenants) is handled and hardened against the usual
  account-takeover mistakes.
- **Events as the nervous system.** Every change emits a versioned event inside
  the transaction. You get outgoing webhooks with signed deliveries, retries,
  dead letters and replay; incoming webhooks with signature checks; live
  updates; and a retained outbox. Integrations cannot silently miss a change.
  Anything that waits or retries is a durable workflow, never a fragile thread.
- **An audit trail you did not write.** Every meaningful act records who,
  acting as what, did what, to which record. Suspensions, erasures, secret
  rotations and permission changes are audited acts, never raw edits.
- **One place to see everything.** Logs, traces and metrics from the web
  process, the worker and every door flow over OpenTelemetry into one sink.
  Every row answers who, under which request, and when.
- **Security as a default.** Credentials for external services are encrypted
  at rest. Secrets are shown once and rotated, never re-read. Every write
  accepts an idempotency key. Rate limits are on per tenant and per user. HIPAA
  is the floor.
- **The boring apps, done once.** Communications behind swappable providers,
  files with versions and signed links, exports as workflows, search with a
  degraded mode, usage metering with thresholds, external connections with
  OAuth. Each respects tenancy and permissions the way your own apps will.
- **Grows with you, without a rebuild.** Scale is measured, not assumed: query
  counts are pinned and re-checked on every commit, hot paths are proven flat as
  data doubles, and a scale envelope records what is proven. Caching is being
  built into the platform (v2.2), permission-aware and invalidated from the
  events it already records, so a builder writes no caching code. A
  hundred-user product pays nothing; a hundred-thousand-user product turns a
  setting on.
- **A quality gate that checks itself.** Dozens of house rules run on every
  change. Each rule proves it can still catch its own failure before it is
  trusted. A dead check is an error, not a pass.
- **A working method for agent teams.** A persistent product manager orders the
  work, builders build in isolated checkouts with their own databases, a
  separate verifier proves every change, and the plans and backlog live in the
  repo so a new session picks up cold. Checks run in minutes, scoped to what
  changed, mirrored in CI, and can run on disposable cloud machines.

### Who it is for

A founder or small team who wants their first product to behave like a mature
platform on the day it ships, and who intends to build it with AI agents doing
the volume of the work under real enforcement rather than trust.

### What it is not

Not a product. It has no screens for your domain and no opinion on what you
sell. It is the system underneath, and the discipline that keeps it sound as
the fifteenth app and the hundred-thousandth user arrive.

## What is here

Two layers, deliberately separate:

- **The system layer** — `.claude/skills/` (the `product-manager` method and
  the `django-conventions` every builder loads), `scripts/` (setup, per-worktree
  database, serve, worker, tests, the loop's scoreboard), `docs/product/`
  (ledger skeletons, each with one marked worked example), `CLAUDE.md`.
  Generic. Rarely changes per product.
- **The project layer** — the Django skeleton a product grows in: Django 5.2
  LTS, Postgres, Redis, Temporal, `uv`, ASGI on uvicorn, a custom `User`
  already swapped in, a `core` app with the project base model, the tenancy
  primitives and the MCP principal, an `accounts` app with the bearer-token
  auth both machine doors share, **django-ninja** with Pydantic schemas
  (discovered routers, OpenAPI at `/api/v1/docs`), Channels, the MCP server
  mounted at `/mcp` (its `ping` tool proves the door), allauth, a `services.py`
  convention, `apps/workflows` (Temporal client, worker, tenant-context
  propagation, the `EchoWorkflow` that proves the wiring), settings split by
  environment, and one example app proving the REST conventions end to end —
  an org-scoped model, services, selectors, schemas, a paginated router under
  `/api/v1/widgets/`, tests with a query pin and the sibling that proves another
  tenant's rows are absent.

**The spine and the enforcement layer are on main** (the order and owners are
in `docs/product/build-contract.md`): the spine apps `events` (outbox, signed
webhook deliveries, the dispatch and housekeeping workflows), `connections`
(encrypted per-tenant credentials, the `httpx` factory) and `realtime` (the
tenant-group socket consumer, and the bridge an event is pushed through); the
example app's MCP tool and its onboarding workflow, so every one of the five
doors has a worked example rather than a description; the organization
hierarchy — a tree per tenant, an acting hat on `X-Org`, roles inheriting
downwards only — with `visible_to` beside `for_tenant` on every scoped read;
and the enforcement layer, `quality/` (the house-rules engine, every rule
carrying planted canaries and a declared blind spot) and `./scripts/check.sh`
(the gate, its verdict ledger and the git hooks). What `queue.md` still holds
is what is next, not what is missing.

## Quickstart, from a fresh clone

```bash
./scripts/setup.sh        # uv sync, compose up (Postgres, Redis, Temporal, Zitadel — one stack, reused if running), database, migrate
uv run python manage.py seed   # a tenant, an owner, a member, and an API token printed once
./scripts/test.sh         # pytest against this worktree's database; exits with pytest's status — never pipe it
./scripts/serve.sh        # uvicorn; it PRINTS the URL to open — add /api/v1/docs to it, and the MCP server is at /mcp
./scripts/worker.sh       # the Temporal worker, in a second terminal; the Temporal UI is at http://127.0.0.1:8233
```

**A clone of a published tag — `git clone --branch v2.1.0 …` — arrives on a
detached HEAD with no local `main`, and `setup.sh`'s first step creates one at
the tag and says so on the line it prints** (the `--loop` scope, the secret
scan's basis and this checkout's database name all read that ref by name; the
step is `ensure_local_main`, and the sentence it prints carries the one-line
move for anyone who wanted the tip instead). **It also prints how long each step
took and a `setup: total` line at the end**, so "the first ten minutes" is a
number this machine measured rather than an estimate.

**`serve.sh` does not serve on 8000, and this README will not tell you a number
it cannot know.** The port is **derived from this checkout** — the same
derivation that gives the checkout its own database, cache prefix, task queue
and bucket — so two clones on one machine never fight over a bind (the
reasoning is in `scripts/serve.sh`'s header). `serve.sh` prints the URL on the
line beginning `serve.sh:`, just above uvicorn's own banner — that is the URL
to open — and `./scripts/serve.sh --print-port` prints the port alone on stdout
for a script to read. `PORT=8100 ./scripts/serve.sh` pins one outright if you
want a fixed number; nothing is derived over a pin.

Expect one more line above it on a fresh clone: `.env.example` ships
`PUBLIC_BASE_URL` on `:8000`, and `serve.sh` says so rather than letting a
browser login come back to a port nothing is serving. It is a note, not an
error, and `.env.example` says which of the two ways to settle it.

`seed` is the line that makes the first five minutes legible: tenancy is on, so
an empty database is a product where **every door correctly returns nothing**,
and there is no way to tell that from a broken one without a tenant, a person
and a token. It refuses to run outside `DEBUG` without `--force`.

The gate is `./scripts/check.sh` — `--loop` per rung (lint, types, house
rules, deploy check, one test pass); no argument is the full gate, which
pre-push runs and records as a verdict keyed on the tree. Exit 0 is clean, 1
is violations, 2 is the enforcement itself being broken — and 2 outranks a
pass. Never pipe it. Its legs are `./scripts/test.sh`, `uv run ruff check .`,
`uv run mypy`, `uv run lint-imports`, `uv run python manage.py makemigrations
--check`, the deploy check and the house-rules engine's self-test — run the
gate rather than the legs, and read its exit status.

### The same quickstart, in a container

`.devcontainer/` is a **room for that script to run in, not another way to run
it**. VS Code's *Reopen in Container*, a GitHub Codespace, or
`devcontainer up --workspace-folder .` gives you the pinned Python 3.12 and the
pinned `uv`, plus a Docker daemon of its own, and then runs
`./scripts/setup.sh` — the same script, called and not copied. When the two
disagree, `setup.sh` is right. The `postCreateCommand` deliberately does not
swallow its exit status: `setup.sh` exits 1 when the Zitadel seed did not
complete, and a create step that goes red there is the honest report.

The daemon is inside the container (`docker-in-docker`) rather than the host's,
because `compose.yaml` publishes every service on `127.0.0.1` and the app reads
`127.0.0.1` to find them — sharing the host's daemon would put the stack in a
different network namespace from the app and need `.env` edits to bridge, which
is the second setup path this avoids. Two consequences worth knowing: the stack
lives on a docker volume keyed to this workspace and invisible to your own
`docker ps`, so deleting that volume (or moving the folder) takes the Postgres
data and the Zitadel PAT with it — a rebuild does not, and `setup.sh` makes both
again either way; and open a **full clone**, not a linked git worktree — a
worktree's `.git` points outside the folder that gets mounted.

Forwarded: 8081 (Zitadel — on 8081 exactly, because `ZITADEL_ISSUER` names that
port), 8233 (Temporal UI), 8025 (Mailpit, once you `docker compose up -d
mailpit` — `setup.sh` does not start it), 5432 (Postgres, for a GUI client),
and 8000 — which is **not** the app's port, only the one a run pinned with
`PORT=8000` would land on. The app's port is derived per checkout (above),
so it is not a number this file can list: VS Code forwards it when
`serve.sh` binds it, and `serve.sh` prints it. The rest of the stack is
consumed inside the container. `.devcontainer/devcontainer.json` says why for
each.

**One known limit, on macOS only.** Docker Desktop's bind mount answers
`access(X_OK)` — `test -x` — with *true* for every file, whatever its mode, so
the gate's instrument-census leg derives the whole tree as instruments and
`./scripts/check.sh` exits 2 inside the container. Nothing else is affected:
`setup.sh`, the app, the tests and the other legs are clean, and the same tree
on a real filesystem in the same container censuses every instrument
correctly. Run the gate on the host until the census reads the mode bit
instead. A Linux host
and a Codespace do not have this.

## Start here

1. `docs/product/architecture.md` — the settled decisions. Do not reopen them.
2. `.claude/skills/product-manager/SKILL.md` — the method. Read before deciding
   what gets built.
3. `.claude/skills/django-conventions/SKILL.md` — how Django is written here.
   Read before writing any.
4. `CLAUDE.md` — mechanisms and invariants. It does not count and it does not
   track.
5. `docs/product/in-flight.md`, then `queue.md` — what is live, and what is
   next, in order.
6. `docs/standards.md` — the method, the standards and the enforcement written
   as a portable account for another team, on any stack: why the agent that
   decides "done" is never the one that built it, what the three-valued gate
   contract buys, and how a miss becomes a mechanism. Companion reading, not a
   binding document — the files above are what binds here.

## Starting a product from this

1. Clone it. **Rename nothing** — the template's paths (`apps.<name>`,
   `config.settings.*`, `scripts/`) are what the skills and the gate know.
   First session in the clone: load `.claude/skills/platform-primer/SKILL.md`
   — the arrival map: what this system is, and which skill to load for the
   work in front of you.
2. Run the quickstart above, then `./scripts/check.sh` — the full gate, green
   on the empty product, is the thing you are starting from.
3. Fill `docs/product/north-star.md` — who you serve, what "shipped" means,
   how you will know. The loop runs toward that and cannot run toward a blank.
   Delete the marked `EXAMPLE` sections as real entries land.
4. Set the autonomy dial and the readout cadence in
   `docs/product/operating-protocol.md`.
5. Record any divergence from the template's defaults — tenancy opt-out, a
   front end, self-hosted Temporal instead of Temporal Cloud — in your
   `architecture.md`, with the reason. The doors are not optional: a product
   that drops one records why.
6. Arm the PM: open a session, say *"you're the PM"*, and let it read
   `in-flight.md` → `queue.md` → the skill. It arms its own watchdog and
   dispatches the first cycle.
