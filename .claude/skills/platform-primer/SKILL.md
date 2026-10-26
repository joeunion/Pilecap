---
name: platform-primer
description: >-
  Load when ARRIVING — a fresh session in this repository or in a product cloned
  from it, starting a first feature, orienting cold, or walking a human through
  what this system is. It is a map with citations, never a second authority:
  every claim here points at the file that owns it, and when they disagree the
  file wins and the disagreement is a finding. NOT for writing code (load
  django-conventions for that), NOT for deciding shape or writing criteria
  (django-architect), NOT for running the loop (product-manager) — this skill
  tells you which of those to load and when, and repeats none of their content.
---

# The platform, from the front door

You have arrived in a template repository — or a product cloned from one —
built for one thing: **Django products constructed by parallel agents under
enforcement.** This file is the map. It holds no rules of its own; every
sentence resolves to an authority you can open, and the authorities are listed
below. Read this page, then load the skill for the work in front of you and go.

## The mental model, in one page

**Everything is a service.** Every write in the product lives in an app's
`services.py`, decorated `@service` — keyword-only (checked at import time),
one transaction, one trace span, one audit row (`apps/core/service.py`; house
rule 13). Routes, tools, consumers, activities and admin are thin callers.
Nothing else writes; house rule 10 refuses a `.save()` in a door.

**Five doors, one behavior** (`CLAUDE.md` § "The stack, and the doors" holds
the list). REST (`apps/<x>/api.py`), MCP (`apps/<x>/mcp.py`
at `/mcp`), sockets (`apps/<x>/consumers.py`), webhooks (`apps/events`,
`apps/connections`) and workflows (`apps/<x>/workflows.py` + `activities.py`)
all call the same services and selectors and speak the same Pydantic schemas.
A capability on REST is on MCP unless exempted with a reason (rule 17), and
**a disagreement between two doors is a finding**, not a style difference.
Doors are found by discovery — drop the conventionally named file and the
mounts in `config/` find it; a rung never edits `config/` or `pyproject.toml`
to register anything.

**Two scoping axes.** *Records flow down:* every scoped read is
`.for_tenant(tenant)` and, for org-scoped models, `.visible_to(actor_or_org)` —
both halves, fails closed, no superuser exemption (rules 8 and 24;
`apps/core/models.py`). *Configuration flows up:* a branch reads the policy its
ancestors set with `.governing(org)` — nearest ancestor wins — and only models
that declare `InheritedDownward` may be read that way; everything else refuses
upward resolution loudly (`ScopedQuerySet.governing` in `apps/core/models.py`,
and `may_be_named` in `apps/core/authz.py` for the matching reachability rule
on writes). Down for what you own, up for what governs you, nothing sideways.

**Nothing un-happens.** The audit trail is append-only — `append_only = True`
is a declared marker (`apps/core/audit.py`), and no code path updates or
deletes an `AuditEntry` (rule 20). Events are emitted inside the write's
transaction and outlive it. Migrations are expand/contract (rule 22). Anything
that waits or retries is a Temporal workflow — deterministic workflow code,
I/O only in activities (rules 9 and 18) — never a thread or a cron entry.

**Every computed number carries its basis.** A value the server computed
travels as `MeasuredOut{value, basis}` — the formula and the inputs it was
evaluated over — so no screen, export or assistant ever adds the parts up
differently (`apps/core/schemas.py`, ADR core-7). Decimal, never float.

**Refusals are three moves.** A service refuses with `core.exceptions.*`; the
code is registered (unregistered codes refuse themselves at import), and the
wire body's keys are `apps/core/exceptions.py::WIRE_COMMON_KEYS` — what happened, what to
branch on, which fields, what the caller can *do* — composed once in `apps/core/exceptions.py` and
rendered identically by `config/api.py` and the MCP door. Services never speak
HTTP (rule 14).

**The gate argues back, and it is usually right.** `./scripts/check.sh` is not
a linter to appease; it is the enforcement layer, and it has refused a *plan*
that was wrong twice over: rule 16 refused an ADR's own
`Measured`/`MeasuredBasis` names and the classes now carry the `Out` suffix
(the ratified deviation is documented on `MeasuredOut` in
`apps/core/schemas.py`); rule 14's sibling refused a ninja import inside a
service and the better shape — a base encoder plus an equivalence test — was
ratified over the plan's letter. A closed cycle's ledger rows move out of
`docs/product/in-flight.md`, which carries only the live one, into the
closed-cycle archive. When the gate refuses you, your first hypothesis is
that the gate is right.

## The reading order

Two lists, and the split is the whole point. **What you READ is what changes
under you and is small enough to hold; what you KNOW WHERE TO FIND is settled,
large, or answered by a command.** Reading the settled files front to back
before you have a question spends most of an arrival's context before it has
done anything — so this order names five things — one to run, then four to
read — and six to be able to reach.

### READ NOW

In this order, before anything else.

0. **Get it running: `README.md` § "Quickstart, from a fresh clone"** —
   `./scripts/setup.sh` (on a tag clone it creates `main`), then
   `./scripts/check.sh --fast`; nothing below runs before it (README's commands).
0b. **On a product's tree** (`rule_id_namespace:` declared), `apps/`,
   `frontend/`, their derived files and your report are yours, the hook refuses
   the rest (rule 95), and `docs/sdk/reference.md` is the next read: on a
   product the reference is the map; `django-conventions` is the template's
   builders' and is cited by the reference where a rule binds.
1. **`CLAUDE.md`** — the mechanisms and invariants, one page. It does not
   count and does not track; it points at the thing that knows.
2. **`docs/product/in-flight.md`** — what is live *right now*: the cycle, the
   stage, the dispatch ledger. The `## Live state` block at the top is the
   live one; everything below it is the superseded stack, kept for the trail.
   The first read on any cold pickup.
3. **the head of `docs/product/queue.md`** — the bands and the live rows: what
   is next, in order. Every other file defers to it. The head, not the file —
   the tail is the backlog's long trail and each row's detail lives in
   `docs/product/queue-detail.md`.
4. **Two commands, not pages — query the part your job needs.**
   **`uv run python manage.py introspect`** is the schema: the real models,
   routes, tools, consumers, workflows, events and refusal registry, as JSON
   from the live registries; the schema is read, never guessed. **`uv run
   python manage.py roads`** is the mechanisms: every job this platform does
   exactly one way and the road that does it — ask it before writing a
   helper; `roads <job>` prints one, `roads --json` is what a brief cites.
   Both need the venv and `.env`, and `introspect` a migrated database — what
   step 0 provides, and none of it exists in a clone that has not run it.

**In a fresh clone of the template, items 2 and 3 are skeletons** — an empty
live state and a one-row worked example, which is the shape `CLAUDE.md`
§ "What this is" says the ledgers ship in — so "nothing actionable" is the
correct day-one reading, not a broken ledger; a product fills them from its
first cycle, and the product-manager skill is how.

**Re-derive the cost rather than believing a number written here** — the
quickstart section and the first two files are read whole, so only they have a
size:

```bash
awk '/^## Quickstart, from a fresh clone/{p=1;next} p&&/^## /{exit} p' README.md | wc -c
wc -c CLAUDE.md docs/product/in-flight.md
wc -c docs/product/{architecture,queue,misses,build-contract,north-star}.md
```

The third line is the set this order used to open with, front to back. The
ratio between that total and the other two is why this section is two lists
rather than one, and it is a fact about today's tree, not a number this file
keeps.

### KNOW WHERE IT IS

Not read on arrival. Each answers one question: open it when you have that
question, and open the part that answers it.

- **`docs/product/architecture.md`** — *was this already decided, and what was
  rejected?* Settled; do not reopen. It also numbers the house rules, which
  `quality/rules.yaml` states and `quality/gate.py` runs.
- **`docs/product/build-contract.md`** — *where does this file go, and who owns
  it?* The layout, the discovery conventions, the gate's legs and targets.
- **`docs/product/north-star.md`** — *who is this for, and what does shipped
  mean?* A skeleton in the template; the destination in a product.
- **`docs/product/misses.md`** — *has this failure already happened here?* What
  we believed that was false. The distilled version is this skill's
  `references/failure-catalog.md`.
- **`apps/example/`** — *what does a correct app look like?* One org-scoped
  model through every convention and every door. The narrated tour is this
  skill's `references/walkthrough.md`.
- **`docs/product/queue.md` past its head** — *why is nobody working on this?*
  The whole backlog; `docs/product/queue-detail.md` holds each row's detail.

## When to load what

The owner's ruling: **this primer is loaded at the door, once, and then you
move to the skill for your role.** It is never the working reference — it
contains no conventions, no criteria formats, no dispatch contracts, only the
pointers to them.

| You are about to… | Load | Because |
|---|---|---|
| Start a dispatched build rung — before touching the tree at all | `.claude/skills/rung-execution/SKILL.md` | How a rung is *executed* here: step zero (`scripts/rung_start.sh`), the born-to-standard checklist, gate discipline, red-first, when to flag-and-hold, the report contract. **The first load of every development rung** — the product-manager skill's `references/dispatch-briefs.md`, under its Development heading, opens every brief with it, which is why a brief no longer restates any of it. |
| Write or change any Python in `apps/`, `config/` or tests — any build rung, any fix, any migration | `.claude/skills/django-conventions/SKILL.md` | The wrong-form/right-form conventions for this repo's exact stack. **Mandatory for every builder, before the first line** — and loaded *after* `rung-execution`, which is what names it. |
| Decompose a job into rungs, draw the app map, write acceptance criteria, add an app, a door or a workflow | `.claude/skills/django-architect/SKILL.md` | What shape and why — the long form of the architect-tier house rules (its own frontmatter names the range). The lead cites the rules it applied in every criteria set. |
| Decide what gets built, run a cycle, dispatch agents, run a retro | `.claude/skills/product-manager/SKILL.md` (+ its `references/dispatch-briefs.md`) | The method: the loop's stages, the team, the dispatch contracts. The PM writes no production code. |
| Orient a fresh session, start a first feature in a clone, give the tour | this skill | The map; then one of the four above. |

The chain is mandatory, not advisory: a builder that skipped `django-conventions`
is the documented failure mode (plausible-but-wrong Django), and the dispatch
briefs require the load. **A builder loads two, in order — `rung-execution`,
then `django-conventions`** — and skipping the first is its own documented
failure: a rung built against a tree the criteria never saw, because step zero
was a hand step done from memory. One session may wear several hats; it loads
the skill for each hat as it puts the hat on — the primer only ever once, on
arrival.

## The refusal-response protocol — when the gate says no

The gate (`./scripts/check.sh`; engine `python -m quality.gate`) exits **0
clean · 1 violations · 2 enforcement broken**, and 2 outranks a pass. Its
refusal messages are written to teach; your job is the response discipline.

**How to read a refusal:**

1. **Take the rule id from the message** — findings are printed per rule
   (`rule 13: …`, `djb.E013`, a named canary).
2. **Read the rule's one-liner** in `CLAUDE.md` § "The house-rules engine" —
   the starter rules by id, in one breath each.
3. **Open the authority**: the rule's full entry in `quality/rules.yaml` —
   `statement`, `scope`, its exemptions *with their reasons*, and
   `does_not_cover`, the declared blind spot. `docs/product/architecture.md`
   numbers the rules and holds the why. The message text usually already
   contains the fix; the yaml holds the boundary of the rule.

**How to respond:**

- **Never weaken the rule, the scope, a floor or a canary to get green.** A
  gate edit to pass a gate is the one move this system treats as an attack on
  itself. If you believe the rule is wrong, say so in your report — the two
  ratified deviations above both went through a report and a ruling, not an
  edit.
- **The valves are visible and counted, by design.** A per-line
  `# rule-<id>: <reason>` override, an `# authz: <reason>` on a service, a
  `# reach: <reason>` on a write that names a row it could not list — each is
  a sentence a reviewer can disagree with, sitting on the line it excuses, and
  the gate counts and prints every one as a standing section
  (`quality/gate.py`). An override with no real reason is itself a violation.
  Use a valve when the code is right and the rule's scope is wrong *here*;
  never to hide a shape you know is wrong.
- **Ratchets shrink and never grow.** A rule with a measured backlog records
  the count in `quality/rules.yaml`; at the count, findings print as notes;
  one over, everything in the class fails naming the growth. You never raise a
  ratchet; a human commits a lower one after reading the note.
- **When the lexicon is what is wrong** — your service's verb is honest and
  rule 16 does not know it — the fix is a **visible diff**: add the verb to
  the declared lexicon in `quality/rules.yaml`, in the same change, where the
  reviewer sees it. The list grows by visible diff and nothing shrinks it.
  Renaming a right verb to a wrong one to pass is the failure the rule exists
  to prevent.
- **Exit 2 is never routed around.** A dead canary, an unbound scope, an
  unknown flag mean the *enforcement* is broken; fixing the enforcement comes
  before any feature work, and a mistyped flag is exit 2, never a silent full
  run.

## Standing rules an arrival must know

The full list is `CLAUDE.md` § "Standing rules"; these are the ones that bite
in the first hour:

- **Run the form of the gate that is yours, and run it unpiped.** An arrival
  needs three forms of `./scripts/check.sh`, and the usage header at the top
  of `scripts/check.sh` is the authority on every other flag — this is not a
  second list: `--fast` (the static legs, what pre-commit runs; seconds, no
  stack), `--loop` (the per-rung gate — one test pass over the apps you
  touched; what a builder runs at every boundary and what a verifier
  consults), and the bare form with no argument, which is the FULL gate and is
  SANCTIONED: legal from the push wall, from `--bank` in the ritual checkout,
  or under a typed `DJB_GATE_SANCTION="<rung-id>: <reason>"` — the one-line
  form is quoted in `rung-execution` § 3 and the why is
  `scripts/check.sh` § "THE FULL GATE IS SANCTIONED" — and typed unsanctioned
  it exits 2 before taking a lease. Whichever form: run it unpiped, wait, read
  its exit status; if you must capture output, redirect to a `*.log` file. The
  gate detects a piped stdout and exits 2 outright (`scripts/check.sh`).
  Piping through `tail` replaced the exit code once already, and the scar is
  a recurring row in `docs/product/misses.md`. The same discipline goes for
  `./scripts/test.sh` and anything whose exit status you intend to trust.
- **Whoever builds does not decide done.** One other agent verifies, always,
  even for one line, against criteria written before the code existed.
  The verifier reads; it does not re-measure (`product-manager/SKILL.md` § The loop, stage 6).
- **The pre-fix demonstration comes after the fix is committed** — the A11
  discipline: commit the fix, *then* check out the baseline files to
  demonstrate the failure red. Running the demonstration first destroyed a
  lane's uncommitted work once — recorded in `docs/product/misses.md`.
- **Stage explicit paths, never `git add -A`.** Your worktree contains things
  that are not yours to commit.
- **A rung names its app; migrations are made inside the rung;
  `makemigrations --merge` is forbidden.** A merge migration means two agents
  touched one app — a PM ordering failure, surfaced and never patched.
- **Every status claim names its artifact** — a file, a test, an endpoint, a
  click path. A claim with no artifact is a hypothesis wearing a status.
- **Read the schema with `introspect`; never guess it. Ask `roads` before
  writing a helper; a job with a road is called, never re-implemented.**

## The vocabulary

The words below are load-bearing here and mean less elsewhere. The authorities
are `docs/product/architecture.md` (the decisions) and the product-manager
skill (the method); this is the phrasebook.

- **A cycle** is one pass of the loop; **a rung** is one dispatched unit of
  build work, and *a rung names its app* — that phrase is the parallelism
  contract. **A lane** is one rung's worktree running beside others.
- **The doors** are the five entry surfaces (REST, MCP, sockets, webhooks,
  workflows); **the spine** is the platform apps they share (`apps/events`,
  `apps/connections`, `apps/realtime`).
- **The hat** is the acting organization — the `X-Org` header, resolved and
  revalidated per request by `core.middleware.resolve_org`, riding on the
  actor, the workflow headers and the audit row. "Which part of the tenant am
  I acting as right now."
- **A surface** is a host and what it exposes — one product's staff at one
  address and its customers at another, one database and one set of services
  (ADR surfaces-1). The product declares it in an app's `surfaces.py`, the
  environment's `SURFACE_HOSTS` binds a host to it, and every door resolves
  it before the tenant (`manage.py roads resolve_surface`). A product that
  declares none is one total `staff` surface. Not to be confused with
  `SurfaceState`, the face's four states of ONE screen (`fe-conventions` §3) —
  the older word, about a page rather than an address.
- **A realm** is where one tenant's people sign in: an organisation of its own
  at the identity platform, made when the tenant is, with its own login
  policy and providers; the deployment's own people sign in at the **staff
  realm** (ADR ident-13). A person in two tenants is one `User` with one
  subject per realm.
- **The gate** is `./scripts/check.sh`; **a leg** is one of its checks; **the
  ledger** is its verdict store keyed on the tree hash (pre-push reads it).
- **A canary** is a deliberately wrong fixture planted through a rule's real
  scope at self-test time — it must fire or the enforcement is broken (exit
  2). **A negative** is a deliberately legal fixture that must stay silent.
  **A floor** is the minimum population a scope must match, so a rule cannot
  pass by scanning nothing. **A ratchet** is a recorded backlog count that may
  only shrink. **`does_not_cover`** is a rule's declared blind spot.
- **The team** — the roster, what each owns and what each may never do, is
  `docs/product/architecture.md` § "The team"; that table is the authority and
  this is the phrasebook. The **PM** orders work and never writes code;
  **design** owns the shape of the user's screen and never decides what gets
  built; the **engineering lead** decomposes and writes acceptance criteria;
  **development** builds, one builder per rung, in worktrees, and never judges
  its own result; **field test** (the verifier / PROVE) decides done and never
  built it; the **surveyor** reads the system and files what it finds, and
  fixes nothing. Only the PM persists — the rest are dispatched per cycle.
- **N-numbers** are queue items in `docs/product/queue.md`, cited by id
  (`N<id>`).
  **ADRs** (`ADR core-5`, `ADR example-3`) are decision records — context ·
  decision · rejected alternatives — cited from docstrings, plans and this
  map. **They live in two places and there is no index**: an ADR that settles
  a standing decision is written into `docs/product/architecture.md` (search
  for `**ADR <id> ·`); an ADR ruled inside a cycle is written into that
  cycle's plan under `docs/product/cycles/`, and many are only there. Until
  an index exists, `git grep 'ADR <id>'` is how you find one, and the
  docstring that cites it is usually the shortest route to why it exists.
  **Misses rows** live in `docs/product/misses.md`, cited as *section · row*
  (e.g. `Cycle <n> row <n>`, `inherited row i<n>`). **A11** names the over-the-wire
  door-test discipline (and its commit-before-demonstrating rule).
- **The ledgers** are the `docs/product/` files as a set — the state a cold
  session resumes from. They are the truth; a status summary is not.

## Two layers, one clone

The repository is **a system, not a product** (`CLAUDE.md` § "What this is").
The system layer — `.claude/skills/`, `scripts/`, `quality/`, the
`docs/product/` skeletons — is generic and travels to every product. The
project layer — `config/`, `apps/`, `pyproject.toml`, `compose.yaml` — is
what a product grows. If you have arrived in a **product clone**: everything
above still holds, `docs/product/north-star.md` is filled in, `apps/example`
may already be deleted in favor of real apps, and any divergence from the
template's defaults is recorded in the product's own `architecture.md` with
its reason — read that file's divergence notes before assuming a default. A
clone of a **published tag** (`git clone --branch <tag> …`) arrives on a
detached HEAD with no local `main`; `./scripts/setup.sh`'s first step creates
one at the tag and says so on the line it prints, because the `--loop` scope
and this checkout's database name both derive from that ref — `README.md`
§ "Quickstart, from a fresh clone" holds the sentence and names the step.

## Identity and sign-in

**Zitadel is the identity system, and it is one door for every interactive
sign-in.** The local password door is gone — `SOCIALACCOUNT_ONLY` in
`config/settings/base.py`, pinned by
`apps/accounts/tests/test_password_door_retired.py` — and the ruling is
**ADR ident-4** ("session model"), recorded in the ADR home
(`docs/product/architecture.md`): the Django session survives unchanged, allauth is reduced
to RP plumbing, and *the local password form is retired because Zitadel hosts
all interactive auth, passwords included*. The standing decision it sits under
— Zitadel as THE identity system, its config as code through our services — is
the **Auth & identity** row of `docs/product/architecture.md` § "The stack".
The console
is **a window, not a door** (house rule 27): identity configuration is written
through our audited services onto our rows and *materialised* in Zitadel by
one activity; only `apps/accounts/zitadel.py` speaks to the management API,
and only that activity and the `zitadel_*` commands may import it.

What an arriving builder holds in their head:

- **The browser flow** is allauth → Zitadel, one static `openid_connect`
  provider (`ZITADEL_PROVIDER_ID`, `config/settings/base.py`).
  `apps/accounts/adapter.py` is where an assertion becomes a session or a
  refusal page: an unverified address is refused before any row is written, an
  existing account is linked and never duplicated, and the identity join —
  `SsoIdentity` rows with no connection, one per realm a person holds a
  subject in, keyed `(realm, subject)` — is written by exactly one service,
  `services.record_identity`, at sign-in (`User.zitadel_sub` is retired; its
  column waits for a later release's drop). Proof:
  `apps/accounts/tests/test_rp_login.py`.
- **Every tenant has a realm of its own** (ADR ident-13): `create_tenant`
  asks for it through `core.bridge`, `EnsureTenantIdentityHomeWorkflow` makes
  it through the port `apps/accounts/realm.py::IdentityRealm` (Zitadel the
  first adapter, `apps/accounts/realms/zitadel.py`), and `IdentityHome` is
  `pending` — nobody of that tenant can sign in — until the run ends.
  `zitadel_reconcile` homes a tenant that has none; `zitadel_audit` prints
  how many are homed.
- **The MCP door is an OAuth 2.1 resource server** (`apps/accounts/oauth.py`,
  ADR ident-3): a JWT validator — signature, issuer, audience, expiry, and
  the subject must resolve through the identity join — sitting *beside*
  `ApiToken`, which survives and is tried first. A stranger's client
  bootstraps from a 401: `WWW-Authenticate` names the RFC 9728 metadata,
  which names the authorization server. `scripts/oauth_demo.py` is the
  instrument that walks that whole chain against the real instance, holding
  no privilege at all. Proof: `apps/accounts/tests/test_mcp_oauth.py`.
- **A customer's IdP is a row, not a deploy** (ADR ident-6). `SsoDomain`
  routes an address's domain to its tenant's `SsoConnection`;
  `services.sync_identity_config` plus one activity materialise the
  connection as an external IdP *inside* Zitadel. `selectors.get_realm_for_email`
  answers `sso` for **every** address — a claimed domain only adds an
  `idp_hint` that skips the provider picker, and unclaimed, disabled and
  never-heard-of are byte-identical answers. Proof:
  `apps/accounts/tests/test_realm.py`, `test_federation.py`, and
  `test_a9_matrix.py` (the full assertion-handling matrix, row by row).
- **An IdP answers *who*, never *what they may do*.** The one place a role is
  ever read from configuration is `SsoConnection.default_role`, applied to a
  *new* membership only — `services.ensure_membership` never changes an
  existing role.
- **Erasure revokes the identity-platform account too**: `erase_user` starts
  a deterministic workflow that deactivates and unlinks the Zitadel user
  (`services._revoke_identity_platform_access`). The honest gap: a person
  with no tenant anywhere has nowhere to record the run, so their Zitadel
  account survives erasure — a known gap named in `docs/product/queue.md`,
  pinned by test, named rather than papered over.
- **The commands** (`apps/accounts/management/commands/`):
  `manage.py zitadel_seed` — the deployment's project, browser client, MCP
  resource and pre-registered MCP client, idempotently; run by
  `./scripts/setup.sh`; its `--rotate-web-secret` flag is the one
  deliberately non-idempotent thing, for a lost browser-client secret.
  `manage.py zitadel_audit` — the read-only drift tripwire on the console
  rule 27 cannot see: exit 1 on disagreement, changes nothing.
  `manage.py sync_workforce_idp` — the workforce Google door, materialised
  through the same one path as everything else.

What a builder must never do: name `ZITADEL_PAT` outside
`config/settings/` and `apps/accounts/zitadel.py`; reach the management API
from anywhere else; put a management call inside a service's transaction (the
row is written first, the workflow starts on commit); or read a tenant or org
from a token claim — the token contributes WHO, and the tenant and the acting
hat are resolved per request exactly as every other door resolves them
(`apps/accounts/oauth.py`, module docstring).

## What this skill's references hold

- **`references/walkthrough.md`** — one feature end to end on the real
  `apps/example` code: model → policy → service → selector → schema → every
  door → workflow → tests, each step citing the house rule that guards it.
  Read it before your first rung.
- **`references/failure-catalog.md`** — the measured ways agents get this
  platform wrong: tell → fix → the mechanism that now catches it.
