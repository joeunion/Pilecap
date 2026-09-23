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
│   │                           #   up/down/pool/census/zones/run/loop/leg/wait/fetch/harvest/push/bake.
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
│   │                           #   THE ZONE AXIS: `zones` prints the security group's VPC's availability zones,
│   │                           #   sorted and de-duplicated from its subnets, one per line — a read, exit 2 when it
│   │                           #   cannot look, and the ONE list a bank spreads across. `up --az Z` resolves that
│   │                           #   zone's subnet and launches into it (`run-instances` has no --availability-zone);
│   │                           #   with no --az the argv is byte-for-byte what it was and no subnet is looked up.
│   │                           #   A Spot `InsufficientInstanceCapacity`/`Unsupported` in the typed zone tries the
│   │                           #   NEXT zone ONCE — printed, still Spot, BEFORE the on-demand market rule — and a
│   │                           #   second refusal reaches that rule unchanged (for a bank shard, the refusal).
│   │                           #   `census` carries each box's `az` so a spread can be read back.
│   │                           #   THE RECLAIM'S OWN WORDS: the launch records the Spot request id beside the key
│   │                           #   (`<box>/spot-request`, absent on on-demand), and a reclaim prints
│   │                           #   `box reclaimed (spot) <id> status <code>: <message>` — `unrecorded` with no id,
│   │                           #   `unreadable` naming ec2:DescribeSpotInstanceRequests when the ops policy's LIVE
│   │                           #   version has not been published yet (the document in deploy/iam/ carries it; the
│   │                           #   publish is the OWNER's hand, and verifier_bootstrap.sh prints the command).
│   │                           #   `down` reads state + StateReason + both tags out of ONE describe: a terminated
│   │                           #   box is `already gone <id> (<reason>)` at exit 0, a refused describe is exit 2
│   │                           #   `could not look at <id>: <the API's line>` with nothing terminated, and only a
│   │                           #   tag that really disagrees is `is not a verifier box`.
│   │                           #   `up` prints `launched <id> az <az>` right after the launch or the warm claim and
│   │                           #   BEFORE the push, so a box that dies at the probe still has a name; the probe
│   │                           #   itself waits out a `TargetNotConnected` session channel to
│   │                           #   DJB_VERIFIER_TUNNEL_WAIT_SECONDS (60, polled 5), printing each wait, and refuses
│   │                           #   past the ceiling exactly as before.
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
├── .claude/agents/                   # the dispatched roles' definitions — a builder's model and tools
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

> **Template-owned, product-owned, shared — per path.** The paragraph above is
> the ownership map *inside one product*; this table is the ownership map
> *between the template and the product built on it*, and the two are different
> questions. A product that edits a template-owned file pays for it at every
> release, forever: the first consumer's fold of v2.1.0 cost 94 merge
> conflicts, 21 of them in `scripts/ quality/ .github/`, twelve commits whose
> whole content was re-applying local edits — and one 1800-line file that
> fast-forwarded byte-identical and took their edits with it, silently, in the
> wrong direction.

| class | paths | at a merge |
|---|---|---|
| **template-owned** — a product edit is a DIVERGENCE, recorded in the product's own `architecture.md` as `divergence: <path> — <reason>` | `scripts/**` less `scripts/local/**` · `quality/**` less `quality/local/**` · `.github/workflows/ci.yml` · `.claude/skills/**` · `.claude/agents/**` · `config/**` · `manage.py` · the platform apps in `quality/partition.yaml` less `apps/core/roles.py` · `CLAUDE.md` · `docs/runbooks/**` · `docs/standards.md` · `docs/product/{build-contract,instruments,partition-closure,publication-manifest,api-editorial-standard,scale-envelope}.md` | fast-forwards; a conflict is the census's business |
| **product-owned, never shipped** — no conflict by construction | `**/local/**` · `*.local.md` · `apps/conftest_local.py` (an exact path, not a glob: a `conftest.py` sibling is collected by pytest BY NAME, so the fixtures drawer cannot leave the package pytest looks in) · `.github/workflows/<not ci.yml>` · the product's own `apps/<x>/**` · the nine ledgers · `north-star.md` · the product's own `architecture.md` · `README.md` · `frontend/**` past the example | untouched |
| **shared, per-file conflict by design** — adjudicated, never a divergence | `apps/core/roles.py` · `apps/core/api/frozen_families.py` · `pyproject.toml` · `uv.lock` · `compose.yaml` · `.env.example` · `quality/budgets.yaml` · `deploy/tests/**` · the three measured files (`scripts/test_impact.json`, `pytest_durations.json`, `gate_member_durations.json`) | one file each, by hand |

> **The default leans toward the PRODUCT, and the table is what the instrument
> reads.** The template-owned row ENUMERATES; anything it does not name is the
> product's. `scripts/divergence_census.sh` is the executable copy of this
> table — it derives the glob classes through the publication bucket rules in
> `scripts/archaeology_lib.sh`, so a new file under an owned glob is classified
> the day it lands with no edit anywhere — and if the two ever disagree, **this
> table wins and the disagreement is a finding**. The drawers in row two are
> the other half of the same decision: a product extends a template directory
> by declaring in its `local/` sibling, which the template never ships
> (`publish.sh` § R0), so there is nothing there to conflict with. House rule
> 60 is the gate's reading of this table, and it is SKIPPED with a printed line
> in the template's own tree, which has no base to compare against because it
> has no template.

> **Every drawer, and the ONE reader that opens it.** A drawer with no reader
> is a promise; a reader with no row here is a seam nobody can find. The fenced
> block below is the list — *what a product wants to extend* → *the drawer* →
> *the reader that discovers it* — and it is fenced because it is meant to be
> read by a rule and not only by a person. Absent, every drawer costs nothing:
> the listing, the transcripts, the censuses and the verdict row are
> byte-identical to a tree that has never heard of one. Malformed, every one of
> them is exit 2 naming the file.

**The table is § "The drawers", below, and it is fenced ```` ```drawers ````
because house rule 60 READS it** — one table, in one place, because a rule
with two texts is a rule that can disagree with itself.

- **`scripts/local/drives/test_<name>.sh`** joins the selftest leg's registered
  drives as a THIRD home beside `scripts/tests/` and
  `deploy/tests/test_stage.sh`, through the one reader all three go through
  (`selftest_registered_drives`; `--with-path` for the callers that must OPEN
  the file rather than name it). A drawer drive is named `local:<name>`
  wherever a drive name is printed — the `composed-of` column, the leg's
  transcript, the shard's own line, the verdict row — so a reader can tell the
  product's members from the template's. **It is not keyed and not banked: a
  drawer drive runs on every gate**, and both consults print that reason rather
  than passing over it silently. The template's drive key is built from a
  `drive_preamble.sh` sitting BESIDE the drive file (`scripts/gate_ledger.sh`),
  which `scripts/tests/` and `deploy/tests/` have and the drawer does not;
  giving a drawer drive a banked verdict is a change to that key, and a rung of
  its own. It must be `+x` and must source
  `scripts/tests/drive_preamble.sh`, which is the same condition the
  `deploy/tests/` gap is declared on and for the same reason: this leg runs
  inside the pre-push hook, where an absolute `GIT_DIR` is exported into every
  child. A name a template drive or a product LEG already carries is exit 2 —
  one label on the verdict row may not mean two members.
- **`scripts/local/env_keys`** is one variable NAME per line (blank lines and
  whole-line `#` comments skipped), and a name there is KEPT when the drive
  preamble scrubs — the inverse of `DRIVE_GATE_VARS`, which is the template
  stripping its own. The kept names also join `DRIVE_INHERITED_VARS`, so the
  workflow-environment census accounts for a product's own CI knobs instead of
  reading each one as "nobody has thought about this yet". A line that is not a
  shell identifier is exit 2 naming the file and the line number; a VALUE never
  appears there, and the shape check is what keeps it out.
- **`docs/product/instruments.local.md`** is the same five-column `Instrument`
  table as `instruments.md`, read beside it by the same census, so a product's
  own executables owe their rows in the product's own file and `instruments.md`
  never needs a product row. A path may be claimed by exactly one of the two,
  and a path in both is exit 2 naming it.
- **`scripts/local/ci/*.sh`** are run, in name order, by ONE optional job in
  `.github/workflows/ci.yml` (`local`, `needs: verdict`) — a product's CI work
  is downstream of the gate's verdict exactly as the image build is, every step
  runs even after a red one, and the first non-zero is the job's. There is no
  `ci.local.yml`: GitHub composes nothing, so a second workflow file would be a
  second copy of the whole setup that nothing keeps in step with this one.
  Absent, the job prints why it did nothing. Work a product wants INSIDE the
  gate is a leg (`scripts/local/legs/`), never a CI step.



## Discovery conventions (what A2 lays; what every later app relies on)

- **Registration:** by discovery, never by editing `config/` or `pyproject.toml`. **`INSTALLED_APPS` is derived from `apps/*/apps.py`** — a package under `apps/` with an `AppConfig` is installed. An app declares what it may import on its own `AppConfig` (`depends_on`); house rule 7 enforces it; `import-linter` keeps only the fixed layer contract (`core` ← `accounts` ← platform ← domain). `config/settings/discovery.py` derives it today.
- **REST:** `apps/<x>/api.py` exposes `router: ninja.Router`; `config/api.py` imports every installed app's `api` module if present and mounts it under the version segment `config/urls.py` owns (`API_PREFIX = "api/v1/"`) at **`/api/v1/<label>/` unless the module names `PREFIX`**, then `/api/v1/<PREFIX>/` (the example app: `PREFIX = "widgets"` → `/api/v1/widgets/`; OpenAPI at `/api/v1/docs`). **An app never spells the version segment**; moving to `v2` is a change to `config/urls.py`, not a sweep of every app. Auth default on the `NinjaAPI` is `apps.accounts.auth.API_AUTH` (`SessionAuth` + `ApiTokenAuth`); **every route carries an explicit `auth=` — on its router or on the route — never `auth=None` outside the `rules.yaml` allow-list.** Lists are `@paginate`d through the one seam, `apps.core.api.CursorPagination` — cursors, not page numbers (ADR core-18, `apps/core/api/pagination.py`); the envelope is `{"items", "has_more", "next_cursor", "count"}`, `?cursor=` and `?limit=` are the controls, and **`count` is `null` unless the caller sends `?include_count=true`** (`?page=`/`?page_size=` are gone, not deprecated). Exception handlers live once in `config/api.py`: `ValidationError` → 400, `IntegrityError` → 409, `PermissionDenied` → 403, `DoesNotExist` → 404. **One envelope, always: `{"detail", "code"}` plus `"errors"` when the refusal names fields** (`on_domain_error`) — `code` is what a client branches on, and `architecture.md` is the authority the code agrees with.
- **MCP:** `apps/<x>/mcp.py` exposes `register(server)`; `config/mcp.py` builds the server, discovers and calls each. `config.mcp.TokenAuthMiddleware` resolves the bearer token once (the same `authenticate_token` service as `ApiTokenAuth`) and leaves a `Principal(user, tenant)` on the ASGI scope; a tool reads it with `apps.core.mcp.principal(ctx)` and calls services only.
- **Sockets:** `apps/<x>/consumers.py` exposes `websocket_urlpatterns`; `config/asgi.py` concatenates them under `AuthMiddlewareStack` + a tenant middleware.
- **Workflows:** `apps/<x>/workflows.py` exposes `WORKFLOWS: list[type]`, `apps/<x>/activities.py` exposes `ACTIVITIES: list[callable]`; `config/temporal.py` assembles one worker on task queue `settings.TEMPORAL_TASK_QUEUE` (default `djb-main`, per-worktree suffix from `db.sh`'s branch sanitiser so two worktrees' workers never steal each other's tasks). `workflows.py` imports only stdlib dataclasses/`timedelta`, `temporalio.workflow` and the app's `types.py`; activities are invoked **by name**. A service starts a run with `apps.workflows.services.start_workflow_on_commit(*, workflow, arg, tenant, user=None, org=None, id, task_queue=None)` — `id` required and deterministic, built by the keyword-only `workflow_id(*, tenant, app, noun, key)`; the async `start_workflow(..., client=)` is for callers already on the loop. **`org` is the acting hat the run is started under**: omit it and every activity in the run acts for the whole tenant rather than for the branch that asked. Tenant, user **and org** travel as workflow **headers** (repeated in the memo) via `TenantContextInterceptor` and are restored in activities by `current_tenant()` / `current_org()` / `current_user_id()` / `workflow_context() -> tuple[Tenant | None, str | None, Organization | None]` — **three** values. Activities are plain `def` and run in the worker's `activity_executor=ThreadPoolExecutor`; each calls `close_old_connections()` at both ends.
- **Events:** `apps.events.services.emit(*, name: str, tenant, payload: dict, actor=None)` — **keyword-only, the name included**, because it is a `@service` and house rule 13 refuses a positional parameter at import time. It writes `Event` + `Outbox` atomically with the caller's transaction (`transaction.on_commit` starts the dispatch workflow). Subscribers are data (`WebhookEndpoint` rows per tenant) and the realtime bridge; nothing imports `events` except to `emit`.
- **Permissions and roles:** `apps/<x>/policies.py` exposes `POLICIES` (predicates), `ACTION_PROSE` (the declared verb and the sentence a refused caller reads), optionally `DEFAULT_ROLES` and `RENAMED_PERMISSIONS`; `apps/<x>/roles.py` exposes `ROLES: dict[str, DeclaredRole]`. `core.authz` discovers both walks, derives `<kind>.create/read/update/delete` for every first-party model, and answers `vocabulary()` — computed at import, never stored. **`apps/core/roles.py` is the one PRODUCT-EDITABLE file in `core`**, the way `docs/product/north-star.md` is product-editable: edit it, add roles, delete `admin` if your product has no such person, and a template merge brings it back as an ordinary per-file conflict you adjudicate. Every other file under `apps/core/` is the platform's. Two apps declaring one role key is an `ImproperlyConfigured` at discovery, and `roles` is in `CANONICAL_MODULES`, so a product's own `apps/<x>/roles.py` needs no `quality/rules.yaml` edit.
- **Product gate legs:** a product grows a leg of its own by DROPPING A FILE, never by editing the gate. `scripts/local/legs/<name>.sh` is executable and carries a versioned header block — `# >>> leg v1 >>>` … `# <<< leg <<<` — whose required fields are `unit:` (`local`, or a new name of the product's own; a unit this gate already declares is exit 2), `needs:` (organs, comma-joined, or `none`; the unit's field is the union of its legs'), `tier:` (`fast`, `loop` or `full` — the cheapest mode that runs it, and every mode above runs it too) and `two-means:` (`broken` or `finding` — what this leg's exit 2 means to the verdict), with `touches:`, `inputs:` and `env:` optional. `check.sh --list-legs` DISCOVERS the drawer and prints one unit row per `unit:`, so **the bank's plan and CI's matrix take a product's legs with no other edit anywhere** (`pm_push.sh` reads the listing; `ci.yml` reads the listing's columns and names no unit); the verdict row names each one as `local:<name>`, because `gate_full_legs` reads the leg set from the LISTING as soon as the drawer holds a leg (with no drawer it reads `check.sh`'s own `FULL_LEGS=` line as it always has, runs no listing at all, and the row is byte-identical — the pre-push hook's consult must cost a lookup and not a gate). One `_provision-<unit>.sh` per unit runs once before that unit's legs. **Absent, the drawer costs nothing** — the listing, the transcripts and the row are byte-identical to a tree that has never heard of it — and **malformed, it is exit 2 at the listing naming the file and the field**, never a silently smaller gate. The template never ships a `scripts/local/` path, so a release can never conflict with one (`scripts/tests/test_local_legs.sh`).
- **Introspect** carries a section per door: `routes`, `tools`, `consumers`, `workflows`, `activities` — each read from the real discovered registry, never from a list — plus `policies` (the whole vocabulary, one row per key with its kind, verb, `decided_by`, `conforms`, sentence, default roles, predicate and any old names) and `roles` (the declared roles and the size of the collection each resolves to).

## The drawers (a product extends by declaring, never by editing)

A template-owned file carries no product edits. Every runnable list the
template ships therefore has a **drawer** beside it — a directory a product
owns outright, read by exactly one function in the template — so a product adds
a leg, a rule, a fold step or a drive without touching a byte the next fold
overwrites. **This block is house rule 60's one reader, and the rule is the block**
(ADR platform-extension-1, as built). Five fields, ` | `-separated:

| field | what it is |
|---|---|
| `live` / `held` | whether the drawer has a reader today, or is a name reserved against a rung that has not landed |
| what a product extends | the concern, in words — and for a `held` row, why it is held |
| the drawer | the product-owned path the reader opens. The template never ships one (`publish.sh` § R0) |
| the reader | `<file>::<symbol>` — **the one** function, constant or job that discovers the drawer |
| the case | `<drive>::<case>` — the case that plants ONE item and proves the reader ran it. `quality/gate.py::drawers_leg` runs exactly these, at `python -m quality.gate --selftest` |

Rule 60 refuses, at exit 2, a drawer literal a template-owned file opens with
no row here, a row whose reader is not in the tree, and a row whose case is not
in its drive — so **adding a drawer means adding a reader AND a case AND this
row**, and deleting any one of the three is a red rather than a quiet hole. A
`held` row writes `—` for both machine fields: the name is reserved (so no
release can ship it and no future rung can take it for something else) and the
rule prints it as held rather than firing on it.

```drawers
live | gate legs | scripts/local/legs/<name>.sh | scripts/check.sh::local_legs_scan | scripts/tests/test_local_legs.sh::case_a_declared_leg_joins_the_listing_as_its_own_unit
live | gate drives | scripts/local/drives/test_<name>.sh | scripts/check.sh::selftest_registered_drives | scripts/tests/test_selftest_leg.sh::case_a_product_drive_in_the_drawer_runs_and_is_named_local
live | house rules | quality/local/<rules.yaml, canary/, negative/, runners/> | quality/gate.py::_read_local | scripts/tests/test_gate_explain.sh::case_a_drawer_rule_is_a_rule_end_to_end
live | fold steps | scripts/local/fold.d/<nn>-<name>.sh | scripts/pm_fold.sh::fold_step_selected | scripts/tests/test_pm_fold.sh::case_a_local_fold_step_runs_and_commits_only_what_it_declared
live | lifecycle classes | scripts/local/lifecycle.d/<name>.sh | scripts/lifecycle.sh::lc_load_local_classes | scripts/tests/test_sweep.sh::case_a_local_lifecycle_class_is_censused_and_verdicted_like_a_built_in
live | drive environment | scripts/local/env_keys | scripts/tests/drive_preamble.sh::DRIVE_LOCAL_ENV_KEYS_FILE | scripts/tests/test_drive_preamble.sh::case_the_product_env_keys_drawer_declares_product_keys_only
live | CI steps | scripts/local/ci/<name>.sh | .github/workflows/ci.yml::local-ci | scripts/tests/test_drive_preamble.sh::case_the_workflows_optional_local_job_runs_the_products_ci_steps
live | instrument census | docs/product/instruments.local.md | scripts/goalpost_scan.py::CENSUS_LOCAL | scripts/tests/test_scripts_census.sh::case_the_product_census_document_is_read_beside_the_templates
live | the template base — the ref a product's divergence census compares against | scripts/local/template-base | scripts/divergence_census.sh::BASE_FROM | scripts/tests/test_divergence_census.sh::case_the_declared_base_is_read_from_the_product_drawer
live | pytest fixtures | apps/conftest_local.py | apps/conftest.py::pytest_plugins | apps/core/tests/test_conftest_local.py::test_the_fixture_drawer
held | wrapper hooks — the contract stands on the rule alone; the first consumer's diffs hold no hook, so the name is reserved under principle 11 rather than built | scripts/local/hooks/<wrapper>.<phase>.sh | — | —
held | verifier bake steps — one consumer's headless-Chromium bake, diff unread; a real walk comes before a codified seam | deploy/verifier/local/bake.d/<name>.sh | — | —
```

**`quality/local/`** holds `rules.yaml` (top-level keys `rule_id_namespace`,
`template_rule_ids_through`, `rules:`, `ratchets:`, `scope_kinds:` — anything
else is exit 2 naming the key and the file), the fixtures its rules plant from
(`quality/local/{canary,negative}/<ns>-<n>/`) and its check-v1 runners
(`quality/local/runners/<name>.py`, reached from a rule's `check:` when the
template's registry does not hold the name). A drawer rule goes through the
whole protocol — consistency, canary, negative, floor, valve, memo — and both
readers tag it `[local]`. `ratchets:` is `rule id → class → count`, the
product-owned home for per-app backlogs, and a class naming an app inside
`quality/partition.yaml`'s `platform_apps` is refused; on a TEMPLATE rule a
class may also name a finding class that rule declares under its own
`ratchets:`, and the drawer's number is added to the template's rather than
replacing it (ADR gate-6, as built). `scope_kinds:` declares a product's own
scope kinds in the shape `quality/rules.yaml` uses — `roots:`, `suffixes:`,
`comment:`, optional `skip_dirs:`/`needs_tree:` — and `SCOPE_KINDS` is the
union, so a product rule may be about a ledger, a doc, a `.env.example` or the
drawer itself. A product kind may not reuse a template kind's name (refused,
naming both files), a root may be any directory **or file** this tree carries,
and a root that names nothing — or that git does not carry — is refused in the
drawer rather than by a later reader. The WALK is the union; the ATTRIBUTION is
not — a `rule-<id>` valve counts only where that rule's own kind reaches, so a
product kind cannot valve, or red, a template rule. **An absent
drawer costs nothing: every number and every listing is byte-identical.**

**`scripts/local/fold.d/<nn>-<name>.sh`** runs after the template's own fold
steps, in name order, and DECLARES the paths it regenerates with the
`derived-tree-paths` sentinel; `fold_is_derived` reads the union of the
template's and the drawer's, so a product's generated file stops reading as
dirty, and a step that writes a path it did not declare is the fold's exit 2
naming the step. **`scripts/local/lifecycle.d/<name>.sh`** is
DECLARATION-ONLY — one `lc_class` call with all its fields, sourced after the
built-ins, so the product's own machinery is censused, verdicted and swept by
the same broom; a command outside the `lc_class` call is exit 2, because a
registry file that can run things is a registry that runs on every census.
**`apps/conftest_local.py`** is the fixtures drawer, and it is an exact path
rather than a glob: pytest collects a `conftest.py` sibling BY NAME, so the
drawer cannot leave the package pytest looks in. `apps/conftest.py` declares
`pytest_plugins` for it iff the module exists (`find_spec`, so a broken drawer
is a loud `ImportError` naming the file, never a silent absence), and a
template fixture of the same name wins.

**The two `held` rows are reserved names, not built drawers.** A held row
costs a product nothing and buys the template two things: `publish.sh` § R0
already refuses to ship the path, and rule 60 prints the row as held instead
of firing on a reader that is not there. `scripts/local/hooks/` is the
wrapper pre/post contract — the first consumer's wrapper diffs turned out to
hold no hook at all (a `set -u` fix, a declaration, a bug fix), so the seam
stands on the rule and not on evidence, and principle 11 says one consumer is
not a shared concept. `deploy/verifier/local/bake.d/` is the same
consumer's headless-Chromium bake step, and that diff is unread too. Each becomes `live` in the
rung that gives it a reader and a case, in one diff with this row.


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
names its leg and then every drive the leg walks, in the order it walks them;
that order is derived from `scripts/check.sh`'s own
`./scripts/tests/test_<name>.sh` invocation lines and is never typed. **Which
shard holds which member is not that order**: the `selftest` unit's `k/N` is a
**duration-balanced partition** (LPT — longest first into the lightest shard)
over the walls recorded in `scripts/gate_member_durations.json`, read through
the always-on leg's own reader, with a member the file does not name taking the
median of the rows that do. It is deterministic for a table and an N, so every
box computes the same assignment; each shard prints its member count, its
predicted seconds, the table it read and that table's machine; and with **no
table at all the split falls back to the index round-robin and says so** — the
file is a hint and its absence means unmeasured, never a refusal. The reason it
is not a round-robin: the drives' walls differ by two orders of magnitude, so
balancing the COUNT balanced nothing (BOXBANK-20's shard 0 drew the engine's own
self-test and every index ≡ 0 member, and the split got WORSE past ten boxes).

| unit | needs | shards | composed-of |
|---|---|---|---|
| `static` | db | 0 | ruff,mypy,import-linter,djb-checks,house-rules,migrations,goalpost-census,queue-index,db-pin,archaeology,adr-census,dangling-docs,loop-names,ci-env,deploy-check,fe,collectstatic |
| `supply-chain` | network | 0 | supply-chain |
| `pytest-x2` | db,redis,temporal,minio,meilisearch | N-capable | temporal-census,partition,pytest-x2,own-tree-census |
| `selftest` | db,docker,temporal | N-capable | selftest,backup_restore,sweep,pm_merge,pm_fold,rung_tidy,pm_push,secrets_scan,secrets_baseline_guard,setup_env,scripts_census,archaeology_loop,fe_leg,db_pin,loop_tier,loop_scope,fast_censuses,loop_ledger,rung_start,db_template,serve_port,runbook_recipes,gate_lease,verify_start,db_zsh,publish,divergence_census,queue_index,test_impact,loop_metrics,gate_explain,drive_preamble,pipefail_readers,list_legs,shard_census,verifier_image,verifier_box,local_legs,selftest_leg,stage |
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

**The bank on boxes, and the ONE row it composes.** `./scripts/pm_push.sh --bank --on-boxes N` is the third wired ritual form beside `pm_merge.sh --bank` and `pm_push.sh --bank`: it folds, reads `./scripts/check.sh --list-legs`, and runs **one `--leg` per verifier box** — the indivisible units one box each, `pytest-x2` split P ways and the last shardable unit S ways, N = 3 + P + S over today's five units, **derived from that listing and never typed** (`N < 5` is refused, and so is any N short of the units the listing actually declares). **This Mac measures nothing**: it takes no machine-wide lease and no pytest slot, so a builder's `--loop` keeps its slot throughout a bank. Every shard's log and exit status are fetched by that shard's own worker and **composed here**, and the composition refuses rather than judges — exit **2** with NO row for a shard that exited 2, a shard whose status or log never came back, a box reclaimed mid-flight, a shard whose printed tree is not the key, or a union of `composed-of:` that does not equal the listing's own leg set and cover `FULL_LEGS`; exit **1** naming each red shard, also with no row. **The row has one writer** — `gate_ledger_record` — and one grammar, the ordinary full row with the sanction saying how it was earned:

```
v1 <post-fold tree> full <utc> <FULL_LEGS, with pytest-x2 as pytest-x2/1 on a one-pass bank> caller=pm-bank sanction=push-wall boxes=<N> shards=<label,…> waited=0 took=<slowest pytest shard> leak-proof=acceptance:<box id> rc=0
```

so `scripts/githooks/pre-push` honours it through exactly the lookup it already does, `waited=0` is the honest answer (this bank queued for nothing), and a row whose legs field is short of `FULL_LEGS` is still not honoured. **The member grammar is `<leg>[/<passes>]` and the `leak-proof=` field is appended last**, both since ADR gate-1's amendment: a shard planned at `--passes 1` names `pytest-x2/1` in its own `composed-of:` and in the row, the field names the acceptance box that ran the whole-suite two-pass proof and the status it exited, and `gate_ledger_lookup` covers `pytest-x2/1` only where that field is present and green — for that unit alone, because the proof is a pytest run and vouches for pytest. An absent suffix still means two passes and every row written before the field existed parses exactly as it did; the composition compares the union of `composed-of:` against the listing with the pass count taken OFF, because the count is a property of the run and never of the unit. The plan decides it before any box is launched — one pass per suite shard exactly when an acceptance checkout could be read, two for every one of them when it could not, and never a mixture — and a shard whose banner disagrees with its plan line is exit **2** with no row, beside the other ways the plan and the shards can disagree. **A detach that exited 255 is the transport and gets ONE more go**: `up` returns on the SSM agent's `Online` and the SSH tunnel is a few seconds behind it, so a `leg` fired in that window comes back with ssh's own 255 and an EMPTY log — no gate ran — and a whole bank refused with every box up and paid for. The bank waits (`DJB_BANK_DETACH_RETRY_SECONDS`, default 15), prints the wait and the retry, and detaches once more; **any other non-zero is not retried**, because it is the wrapper or the box saying something real and a second detach would risk a second copy of a leg already running. **The boxes are spread over the zones the WRAPPER lists**: `verifier_box.sh zones` is read ONCE per bank and the plan's fifth column is `zones[i mod n]` in plan order, the acceptance box taking the next place after the last shard; a ring that cannot be read or comes back empty is exit **2 before a single `up`**, because Spot capacity is a per-availability-zone fact and a bank in one zone is a bank that loses every box to one event. **A RECLAIMED shard is one more box, in the NEXT zone, ONCE** — the old id stays on the teardown list (a reclaimed instance is `already gone` to a `down`, exit 0 and not a refusal) and the new one joins it, the leg is detached again under the same 255 rule, the wait and both fetches are redone, and the table prints `retried-from <old id> (<spot status>)` under that shard's row; the composed ROW gains nothing. A shard reclaimed TWICE is the answer this bank always gave — **LOST, never red** — and so is a retry whose own box would not come up. The acceptance box gets the same one retry, and needs it more than any shard: since ADR gate-1's amendment every pytest shard runs one pass, so a reclaimed ninth box is a bank with no leak proof at all. **A box that LAUNCHED and whose `up` then failed is still taken down**: the launch worker reads the wrapper's `launched <id> az <az>` line and appends it to the teardown list BEFORE it reads `up`'s exit status, because `up`'s tunnel probe dies before the `instance` line is printed and a box named by nothing this script keeps is a box that bills until its own tag expires. **Every bank `up` carries `--ttl 1 --idle 30`** and the header says so (`box lifetime: 1h hard, 30m idle`): the teardown is a trap and no shell covers a SIGKILL, so the box's own ceiling and idle reaper are what a killed bank rests on, and one hour is comfortably above the longest measured leg. **The idle half stays the image's own thirty minutes, and a shorter one is a defect rather than a tighter belt** — the box's idle clock starts when its LEG EXITS, so a pytest shard done at two and a half minutes is idle for as long as the selftest unit keeps running (twenty minutes on a tree where `quality/rules.yaml` moved); at ten it was reaped out from under the bank, and what came back was `box gone (terminated)`: no log, no status, and a leak proof composed as LOST over a tree every shard passed. **Each shard's log and status are fetched BY THE WORKER THAT WAITED ON IT**, the moment its own `wait` returns, and the acceptance box's four files by the worker that ran it — there is no join-then-fetch phase, so nothing is ever asked of a box that has been idle since another unit started. **A red bank NAMES the first failing test and the command that replays it** — the acceptance box's `pass1.log` and `pass2.log` are fetched with the shards' logs, before the teardown, and a red leak proof or a red pytest shard prints `first failing: <nodeid> (<pass 2 | the shard>; <n> FAILED) - replay: ./scripts/test.sh -n 16 --randomly-seed=<seed> <nodeid>` beside the table (`none named` when the log carries no `FAILED` line, which is a pass that died without a summary). The line is printed and composed NOWHERE: a red bank writes no row, and `gate_ledger_record`'s grammar is untouched. **A shard NEVER falls back to on-demand on its own**: the bank sets `DJB_VERIFIER_BANK_SHARD` around each shard's `up`, which turns `scripts/verifier_box.sh`'s Spot→on-demand fallback into a refusal that prints the Spot code it saw and the on-demand hour it declined to buy — N shards each answering a capacity refusal with an on-demand box is N boxes against a quota an order of magnitude smaller than the Spot one, bought without anybody deciding to; the valve is `DJB_VERIFIER_ON_DEMAND_OK="<reason>"`, the reason prints in the bank's table, and a SINGLE `up` keeps the fallback (printed, with the price) because one box is a decision an operator is standing in front of. The price comes from the Price List API through `DJB_VERIFIER_PRICING_REGION`, which has no default and prints as unknown when unset. **The market each box is actually on is EC2's `InstanceLifecycle`, never the market the launch asked for** — `up` prints it as its own `market` line, `census` carries it as a column, and the bank's shard table keeps it, because afterwards the boxes are gone and the table is all there is to cost the bank from. Every launched box is taken down on green, on red, on exit 2 and on a signal; a `down` that fails names the hand and the bank's own status stands. Driven by `scripts/tests/test_pm_push.sh` (every refusal, the plan against a planted listing, the seven composition plants, the composed row's grammar, the hook honouring it, and the teardown on all three exits) — which stubs the wrapper and asserts the SEAM's argv, `scripts/verifier_box.sh leg <id> --unit U [--shard k/N] [--passes 1] --log leg`, and nothing past it.

**The docs-only push path.** A ledger, readouts, queue or ADR-signature commit moves the tree the verdict is keyed on and moved nothing any leg of the gate executes, and it paid a whole bank for that — three sequential banks in the v2.1 tail, 28 minutes for eight of them in one wave. So `pm_push.sh --bank`, **both arms, before a lease, a pytest slot or a single `up`**, asks one question: is every path changed since the nearest ancestor tree carrying an HONOURED full row on the DECLARED LIST? The list is `GATE_DOCS_ONLY_PATHS` in `scripts/gate_ledger.sh` and it is the rule's whole text — `docs/**`, `README.md`, `CLAUDE.md`, `.claude/skills/**`, `scripts/test_impact.json`; **`CHANGELOG.md` and `TEMPLATE_VERSION` are OUT by measurement** (pytest reads both, so a release still pays one bank). **The map is admitted and no longer ARRIVES**: it stays on the list, but since it rides the next bank's fold commit rather than the PM's ledger commit (the map row below) a ledger push's delta does not name it, so the reader derivation stops selecting `scripts/tests/test_pm_push.sh` — 116 s of the 244 s of readers Row 12 measured. The source is followed through a reuse row's `from=`, so the delta is always taken against a tree a gate MEASURED and never against one that inherited. The **readers are derived per path and run on this Mac**, each printed with its seconds: `--leg static` always (adr-census, dangling-docs, goalpost-census, queue-index, archaeology and the house-rules engine all read `docs/`), `--leg full-house-rules` when a path is read literally under `quality/**`, and every drive whose own declaration covers the path — a *literal read* being a quoted value or a YAML `file:` entry, never a backtick or a comment, which is the measured difference between refusing the two commits this exists for and admitting them. A literal read under `apps/**` or `config/**` is a **refusal naming `file:line`**. The row is the ORDINARY full row, written by the one writer, with the legs field and `leak-proof=` **copied from the source row** and the sanction saying how it was earned — `sanction=docs-only from=<M> paths=<n> readers=<csv>` — so `pre-push` honours it through the lookup it already does and nothing in the hook or in `gate_ledger_lookup` changed. **Every other outcome is the full bank and says so**, ending in "full bank": a path off the list, a source row that is not honoured (with the lookup's own note beside it), a reader that exited 2, the typed valve `DJB_BANK_MEASURE=1`. A reader that goes **RED is exit 1** — a red tree, no row, nothing pushed. The declared blind spot is a docs path a module reaches by directory walk, glob or computed name: invisible to all three derivations, and belted by the next push that is not docs-only. Driven by `scripts/tests/test_loop_ledger.sh` (the source chain, the list, the readers) and `scripts/tests/test_pm_push.sh` (both arms, the row's grammar, every refusal, the hook). **What it costs is not written here, because the road prints it**: every run ends in `docs-only reuse of <M> — readers <s> s, total <s> s` with a line per reader above it and the source-walk overhead on its own line, so the cost is measured at each push rather than recorded in a file that cannot notice it changing.

**The image, built once, by the bank (ADR deploy-4a, PROPOSED).** After the row is written and before the boxes go down, ONE box — the acceptance box, the one box outside the composed verdict — asserts its own `deploy/provision.sh image-tag` against the tag the row was keyed on, mints a registry token under ITS OWN instance role (`deploy/iam/verifier_bootstrap.sh` prints the `put-role-policy` that grants it, scoped to this namespace's two repositories and carrying no delete), builds `--target web` and `--target worker` and pushes both under `tree-<12hex>`; the bank prints the seconds and the registry's own digests, and `.github/workflows/ci.yml`'s `images` job skips a tag the registry already holds. **Every failure here is printed and the row stands** — no registry coordinate, a tag that is not this tree's, a build or push that failed: an image is downstream of a verdict and never part of one, and CI's job is the fallback that builds what the registry lacks. What the bank pushes is what the box builds natively (`linux/arm64`), which narrows deploy-4 (a)'s two-architecture manifest for a bank-built tag — the owner's to sign with the amendment.

**The test-impact map, and it is a PROJECTION and never truth (principle 9).** `scripts/test_impact.json` is tracked, regenerated per wave the way `scripts/pytest_durations.json` is, and says for every collected test which checkout-relative source files that test EXECUTED. **Its owner is the acceptance run**: `pm_push.sh --bank --on-boxes N` brings up ONE extra box labelled `acceptance`, outside `bank_boxes_plan` and outside the composition, which runs the whole suite twice — pass 1 under `--cov=apps --cov=config --cov-context=test` so every measured line carries the nodeid that executed it, pass 2 plain — and then runs `scripts/test_impact.py write` on the box to invert pass 1's coverage database into the map. The bank **fetches** the file into the working tree and **commits nothing** (a bank takes no commit); **the NEXT bank's FOLD commits it**, because `scripts/test_impact.json` is on `scripts/pm_fold.sh`'s typed derived list and is the one entry there that clause 1 tolerates ALREADY DIRTY — no step of a fold can regenerate a map only a two-pass acceptance run can write, so the fold ABSORBS it rather than regenerating it and says so in its own subject (`fold: acceptance map absorbed`) and on an `absorbed` line at the top of the run. **It left the PM's hands because a hand commit put the map in the next ledger push's delta**, which made `scripts/tests/test_pm_push.sh` (116 s, it declares the map) a derived reader of every docs-only push; a deleted map is still a dirty tree, and the work beside an absorbed path is still refused (`scripts/tests/test_pm_fold.sh`). **Its status is printed and composed NOWHERE** — not in `lost`, `red`, `foreign` or `kbad`: a measurement may not refuse a claim every shard passed, so a coverage run that died or a writer that could not look each cost one wave of the map and nothing else, and the loop keeps the closure scope it has today. **The LEAK PROOF beside it is the opposite kind of thing, on the same box and in the same file.** Since ADR gate-1's amendment that box's two whole passes run under ONE seed minted on the box, `-n 16` on both, each under `set +e` writing its own status into `~/verify/<rung>/proof.txt` as `seed=<n> workers=<n> pass1=<rc> pass2=<rc> map=<rc>` — and the bank fetches that file to `<sink>/acceptance.proof` and reads it exactly like a shard's: no box, no file, nothing parsable or no seed is **`lost`** (exit 2, no row, saying that one pass was measured and nothing proved what it left behind), a non-zero `pass1=` or `pass2=` is **`red`** (exit 1, no row, naming the box and its log), and only a green pair reaches the row as `leak-proof=`. **`map=` is the measurement half of that same file and decides nothing** — the two roles separate at the `rc` each one wrote, so a bank whose passes are green and whose map writer died writes the row and prints that the map was not written. Where there can be no acceptance box at all (its checkout path is unreadable) the shards run two passes each and the bank is byte-for-byte the one it was before the amendment. **The census is the map's whole contract**: every collected nodeid is in `tests` or in `unmapped` with a reason in words, never neither, never both, and never an empty list — an empty list reads downstream as "this test touches nothing" and is never selected again, for any change, ever — and a nodeid the collection has and the coverage database has no context for is exit 2 with no file written. **What the map cannot see, declared** (`scripts/test_impact.py`'s header): what a test reaches through a subprocess, and everything that is not Python — templates, fixtures, `.env`, assets read by path — so a reader that SELECTS from the map owes a fallback for a changed file the map has never recorded. Driven by `scripts/tests/test_test_impact.sh` (the census, the two could-not-looks, determinism) and, for the box and the composition, `scripts/tests/test_pm_push.sh`.

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
is the platform's own mechanism, not a product concept: the count is never
typed here — `apps/conftest.py`'s `apps_root_modules` floor names it and the
directory is the census — and a product adds its own beside them without
touching `config/`, `pyproject.toml` or the scope derivation.

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
