# Pilecap

> This heading is the template's own name. A product sets `PRODUCT_NAME` in
> its `.env` — which is what names its Zitadel project, its compose first
> instance and that instance's service account — and edits this line and
> `.devcontainer/devcontainer.json`'s `name`, the two surfaces no variable
> can reach (ADR platform-1 in
> `docs/product/architecture.md`).

**Start a serious product on day zero, not day ninety.**

Pilecap is a template for a Django business application built mostly by AI
agents. Build a capability once, as a service, and it reaches your users through
every door: a REST API, a tool interface agents call (MCP), live sockets,
webhooks and background workflows. The tenant boundary and the permissions hold
on all of them. A quality gate that checks itself refuses any change that breaks
that.

## Why this matters when agents write the code

Agents write plausible code that is wrong, and they write a lot of it. So
nothing here trusts the author. A second agent decides when work is done, never
the one that built it. Every house rule proves it can still catch a planted
failure before its verdict counts. And every mechanism has one road, listed by
the tree itself, so a builder cannot quietly invent a second.

## What you get

**Data and access**

- **Tenancy that fails closed.** Every read is scoped to a tenant; a read with
  no tenant returns nothing, and there is no superuser exception.
- **An organisation tree inside each tenant.** Regions, branches or teams, with
  roles that inherit downward only; a flat product is a tree of depth one and
  pays nothing for it.
- **Permissions as data.** Every action, reads included, has a permission
  generated from your models; roles are set per tenant without a deploy, and a
  refusal says what happened and what the caller can do.
- **An identity home per tenant.** Each tenant gets its own realm at the
  identity platform, made when the tenant is, so requiring single sign-on is
  that realm's login policy rather than code you write.
- **Surfaces.** One product serves several audiences on the same records, such
  as staff at one host and customers at another; each host exposes only what
  it declares and admits only its own roles.

**Reach**

- **Five doors from one service.** REST, MCP, sockets, webhooks and workflows
  call the same services and speak the same schemas, so they cannot disagree.
- **The face.** A worked Next.js client over a client generated from the API's
  OpenAPI document is the default front end, and each of its design rules
  names the instrument that measures it.
- **Events inside the transaction.** Outgoing webhooks are signed, retried,
  dead-lettered and replayable; incoming ones are signature-checked. Every
  event is kept so a delivery can be replayed, and a failed dispatch is never
  swept.
- **Durable workflows.** Anything that waits or retries runs as a Temporal
  workflow, never a thread or a cron job.

**Operations**

- **An audit trail you did not write.** Every write records who acted, as
  which part of the tenant, through which door, on which record, and the trail
  is append-only.
- **One telemetry sink.** Logs, traces and metrics from the web process, the
  worker and every door go over OpenTelemetry to one place, and every row
  answers who, under which request, and when.
- **Security by default.** Credentials for outside systems are encrypted at
  rest, tokens and webhook secrets are shown once, every write accepts an
  idempotency key, and rate limits apply per token and per tenant. HIPAA is
  the floor, not the goal.
- **The boring apps, done once.** Communications, files, exports, search,
  usage metering and connections to outside systems.

**Confidence**

- **A gate that checks itself.** `./scripts/check.sh` exits 0 when clean, 1 on
  violations, and 2 when the enforcement itself is broken; 2 outranks a pass,
  so a dead check is never read as green.
- **The roads index.** `uv run python manage.py roads` lists every job the
  platform does exactly one way and the code that does it, and house rule 84
  refuses a second road for the same job.
- **Scale measured, not assumed.** Query counts are pinned in tests, hot paths
  are proven flat as the data doubles, and the backlogs the gate records can
  only go down.

**The method**

- A persistent product manager orders the work and writes no code; builders
  work in isolated checkouts with their own databases; a separate verifier
  decides done.
- The per-change gate runs on disposable cloud machines, and a train of merges
  is measured once, by CI. Plans and backlog live in the repository, so a new
  session picks up cold.

## What it is not

It is not a product: it has no screens for your domain and no opinion on what
you sell. It carries one worked example on a placeholder noun, the Widget —
`apps/example`, the face's one journey (sign in, land on `/welcome`) and the
customer portal in `apps/example_portal` — which a product copies from and then
deletes. The `frontend/` ships no component library; `frontend/README.md` says
so and says why.

## Quickstart, from a fresh clone

```bash
./scripts/setup.sh --help
./scripts/setup.sh
uv run python manage.py declare <ns>
uv run python manage.py seed
./scripts/test.sh
./scripts/serve.sh
./scripts/worker.sh
```

- `setup.sh` starts the services, makes and migrates this checkout's own
  database, configures sign-in, and prints a total. On a tag clone
  (`git clone --branch <tag> …`) there is no local `main`, so it creates one
  first and says so.
- The stack's images are multi-architecture except MinIO, one `linux/arm64`
  manifest on the template owner's ghcr.io mirror, beside Zitadel's image (no
  registry still serves that release's amd64 layers), so an amd64 laptop runs
  it under Docker's arm64 emulation (`docs/sdk/day-zero.md`, "The CPU").
- Every image pulls anonymously: no registry account or login, the MinIO
  mirror included.
- Every clone's compose project is `djangobootstrap`, the name `docker ps`
  shows: ADR platform-1 keeps it as infrastructure identity, because renaming
  it orphans a running stack and its data.
- `declare <ns>` makes the clone a product, before anything is tested
  (`docs/sdk/day-zero.md` step 3, which commits it next): `<ns>` is one
  lowercase word naming your rules. Every clone of a release declares; only the
  template's own repository never does, and on an undeclared clone the
  template's own `quality/tests` refuse in one line naming this step.
- `seed` makes a tenant, an owner, a member and an API token printed once.
- `test.sh` runs the suite and exits with pytest's status; never pipe it.
- `serve.sh` prints the URL to open; the API docs are at `/api/v1/docs`, MCP
  at `/mcp`.
- `worker.sh` runs the Temporal worker, in a second terminal.
- The face's price is Node (`^22.18 || ^24 || ^26`, `frontend/.nvmrc`) and
  pnpm (`packageManager` in `frontend/package.json`). With pnpm on PATH,
  setup's `frontend toolchain` step installs it (`pnpm install
  --frozen-lockfile`); without, the step says so and skips, and the gate's
  `fe` leg is could-not-look on every whole run. Run it in `frontend/` with
  `DJANGO_ORIGIN="http://127.0.0.1:$(../scripts/serve.sh --print-port)" pnpm dev`
  — `DJANGO_ORIGIN` is required; it is where the face proxies `/api/v1/` to.

The port is derived per checkout, so two clones never collide; `serve.sh`
prints it. `seed` exists because tenancy is on: an empty database correctly
returns nothing, which looks exactly like a broken one. It refuses to run
outside `DEBUG` without `--force`.

**In a container.** `.devcontainer/` is a room for `setup.sh` to run in: it
supplies Python, `uv` and a Docker daemon of its own, then calls the same
script. Open a full clone, not a linked git worktree, whose `.git` points
outside the folder that gets mounted.
`.devcontainer/devcontainer.json` explains each forwarded port.

### Starting a product

**[`docs/sdk/day-zero.md`](docs/sdk/day-zero.md) is the whole of it, in order**:
clone a release tag, `./scripts/setup.sh`, `manage.py declare <ns>`, the one
sanctioned full gate, the `template` and `origin` remotes, the first push, then
`north-star.md` — and what a product may write. After it,
[`docs/sdk/the-one-path.md`](docs/sdk/the-one-path.md) is every feature's road.
In your first agent session, load the primer first
(`.claude/skills/platform-primer/SKILL.md`); arm the product manager by saying
*"you're the PM"*.

## Stay current

Taking a release is called a fold: a git merge of the release's tag
(`CHANGELOG.md` § "How a product takes a release"). Before the merge,
`./scripts/divergence_census.sh --against <tag>` lists the template files you
changed and refuses on any name the release would collide with, and the fold
map shows what your rule numbers became; its full form is in the release's
"What a product does at the merge" section of `CHANGELOG.md`. Follow that
section in order.

## Where the truth lives

| Question | Read |
|---|---|
| An agent arriving cold: what is this, what do I load? | `.claude/skills/platform-primer/SKILL.md` |
| The mechanisms and invariants | `CLAUDE.md` |
| A builder: how Django is written here | `.claude/skills/django-conventions/SKILL.md` |
| A builder on the face: how the client is written | `.claude/skills/fe-conventions/SKILL.md` |
| The product manager: how work is decided and verified | `.claude/skills/product-manager/SKILL.md` |
| What was decided, and why | `docs/product/architecture.md` |
| Where a file goes, and who owns it | `docs/product/build-contract.md` |
| What is next, and what is live now | `docs/product/queue.md`, `docs/product/in-flight.md` |
| The method for another team (companion, not binding) | `docs/standards.md` |
