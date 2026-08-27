# The scale envelope — what this platform is proven to handle

Assembled per ADR gate-2, from the four measurement passes ADR perf-1
requires. **This is the goal-post artifact the Performance pillar reads from** —
the pillar's "read from" cell is flipped by the PM at CLOSE, not here. It
states, per surface, what the platform is **proven** to handle, in which
world, with which instrument, and where the proof lives. Nothing below is a
number this file invented: every row cites the measurement doc that produced
it, and where this file and a measurement doc disagree, the doc wins and the
disagreement is a finding.

**The division of labor, which is what "re-running" means** (ADR perf-1):
**the harness proves flatness once, the gate pins the count forever.** A query
count proven flat under doubling is scale-free, so `quality/hotpath_probe.py`
re-measures it cheaply on every gate run at gate scale, and rule 35 holds each
entry's plan *shape* the same way. What the gate cannot see — planner choice
at volume, rows examined per statement — is the harness's half: re-running
`./scripts/perf.sh` with the relevant `perf/measure_*.py` module re-proves it
against the declared world. A stranger re-running this file's claims runs the
harness for the rows below and reads the gate for the pins.

## The world these claims are proven in

Declared once, in `perf/seed.py::ScaleSpec` ("a first consuming product's
real-world scale", ADR perf-1), and ratified as the platform's stated
envelope. Spec hash **`df07df482a95`** (the stamp tenant's slug embeds it; a
spec change forces a re-seed; rule 5 compares this line against
`spec_hash(ScaleSpec())` on every gate run, so a spec that moves without this
file moving is a violation and not a silence). Postgres **16.15 (Debian
16.15-1.pgdg13+2)** — plan shapes are server-version-shaped, and a
major-version move re-triggers every plan claim. Measured across four
measurement passes (M1–M4), corrected and re-measured against fixed surfaces
in later passes.

| axis | declared volume |
|---|---|
| tenants | 25 (2 loaded, 23 background — per-tenant cost proven independent of tenant count) |
| organizations per loaded tenant | 1,253 (spine to depth 11 = **12 path segments**; one 200-wide node; 40 regions × 25 partners) |
| memberships per loaded tenant | 3,000 (+ one 12-hat person — `many_hats`) |
| widgets per loaded tenant | 100,000 (heaviest org 5,000) |
| API tokens per loaded tenant | 500 |
| audit rows | 500,000 (245,000 for the loaded tenant; 10,000 platform) |
| events / outbox rows | 400,000 (20,000 pending across the loaded pair) |
| webhook endpoints | 25 (13 the loaded tenant's) |
| deliveries | 100,000 |
| workflow runs | 50,000 (+ 1,000 platform) |
| sockets (runtime axis) | 500 (doubled in-process to 1,000) |

Every pinned count below was re-proven at a **doubled axis** (`--double
<axis>`, a full drop/re-seed/census/measure per tier); flatness under doubling
is what makes the number scale-free. The depth axis **cannot** double —
row 0.

## The verdicts, per surface

Status: **PROVEN** = measured flat/exact in every world run · **CEILING** =
a declared bound, enforced by the platform itself · **BOOKED** = measured,
honest, not fixed — the queue row is named.

### Row 0 — the depth ceiling (the platform's own grammar)

| bound | value | where enforced |
|---|---|---|
| organization tree depth | **12 path segments** (`PATH_MAX_DEPTH = 12`, `apps/core/models.py`) | `child_path` refuses a thirteenth segment; `perf/seed.py` raises `PathOverflow` rather than fake a deeper tree |

Every hierarchy number below is measured **at** this ceiling (the seeded
depth-11 spine is the deepest tree that can exist), and flatness is proven
under org-doubling instead of depth-doubling — a platform that refuses to go
deeper does not need a flatness proof past its own refusal; it needs the
refusal written down, which is this row. Raising the ceiling is a lead
decision that reopens the depth axis and makes this row wrong.

### The hierarchy (M1 — measured before enforced; harness: `perf/measure_hierarchy.py`)

| claim | number | instrument | status |
|---|---|---|---|
| subtree prefix scan, any hat (25 → 2,292 orgs) | 1 query | count + plan (`organization_path_prefix`) | PROVEN |
| `visible_to` page of 50, all five hats (root/region/leaf/wide/spine) | 1 query each; page and COUNT pinned separately | count | PROVEN |
| `governing()` at the depth ceiling, populated chain | 1 query — the ancestor chain is decomposed in Python, no tree walk | count | PROVEN |
| `resolve_org` — default hat / named hat / **refused** hat | 1 / 2 / 2 — refusing costs what granting costs (no timing oracle) | count | PROVEN |
| the 200-wide node's children, page of 50 | 1 query, `core_organization_parent_id`, page AND count | count + plan | PROVEN |
| depth 0 vs depth 11 | identical cost — depth has no term in any read | count + plan | PROVEN |

**Plan-shape truth is per statement** and lives in
`perf/measure_hierarchy.py::PLAN_EXPECTATIONS` (re-cut after M1's original
verdicts were taken on an unsliced queryset with no door issues — the CORRECTION
block in the doc is binding). Do not pin a plan on the paginated page
(generalised), on `governing()`, or on any wide-hat read (the narrow-hat
pagination cost, below).

### Identity and the doors (M3 — measured before enforced; harness: `perf/measure_identity.py`)

| claim | number | instrument | status |
|---|---|---|---|
| token auth, cold / warm (500 → 1,000 tokens) | 2 / 1 queries; 50 uses of one token = 51 queries, exactly 1 UPDATE (the write throttle) | count | PROVEN |
| `resolve_tenant` | 1 query | count | PROVEN |
| the many-hats person (12 → 24 hats) | same 1 / 2 as the one-hat person — the hat count is not a term in the cost | count | PROVEN |
| `GET /api/v1/widgets/` at 100k → 200k rows — session / +`X-Org` / token cold / token warm | **8 / 9 / 7 / 6** queries, full middleware stack | count | PROVEN (8 pinned in apps tests; 9/7/6 recommended pins, M3) |
| JWKS storm — 1,000 OAuth validations | 1 key fetch, 1 `GET /jwks`, 1 discovery document per cache window; 2 queries per validation, 0 writes | cache-hit count | PROVEN |
| the `X-Org` lookup's plan | `slug` in the **Index Cond** — the shape, never the index name (the name flips on statistics; the seeder ANALYZEs and the module's assertion is the seeder's canary) | plan | PROVEN (operational half open: a restore/bulk import sits unanalyzed and nothing in the tree notices) |

### The ledgers (M2 — measured before enforced; harness: `perf/measure_ledgers.py`)

| claim | number | instrument | status |
|---|---|---|---|
| audit append at 500k → 1M rows | 1 INSERT — no read-before-write, nothing consults the ledger's size | count | PROVEN |
| audit page-50, own tenant / platform | 1 query, `auditentry_tenant_created` / `auditentry_platform_created` — **was 255,000 → 510,000 discarded rows before the fix**; nothing discarded after | count + plan | PROVEN (re-measured) |
| `@service`'s audit charge | exactly 1 of `close_outbox`'s 4 statements | count | PROVEN |
| `enqueue_dispatch` (100k → 200k deliveries behind it) | 9 statements, incl. the nested `record_run` and both audit rows | count | PROVEN |
| webhook fan-out (25 → 50 endpoints) | 1 + endpoints × 5 (first attempt 6) — linear in subscribers, constant per subscriber, by design | count | PROVEN |
| relay candidate selection at 20k → 40k pending | 1 query, `outbox_status_next_attempt`, no Seq Scan | count + plan | PROVEN |
| **the relay ceiling** | **500 rows/batch (`RECONCILE_BATCH`), 20 batches/sweep (`RECONCILE_MAX_BATCHES`)** — one activity drains ≤ 4,500 statements (was 180,000 unbounded); oldest promise first; **no immovable head can starve the batch behind it** — the `already_seen` cursor steps past a fault as well as a refusal, where it used to step past `Conflict` alone and one poison row pinned the sweep at a fixed offset | count | CEILING |
| relay residuals | the next sweep re-pays one refused enqueue per **immovable** head row (refusals + faults) — cost ∝ that population, never the pending one; keyset cursor is the recorded trigger if it grows. Second residual, declared and self-healing: `already_seen` over-counts if a stepped-past row leaves the head mid-sweep, skipping that many legitimate rows until the next sweep restarts at zero | count | DECLARED |
| run-ledger sweep (25 → 50 tenants) | 1 query **per tenant** (rule 8's honest price — the total is linear in tenants by design); platform run population seeded and measured | count + plan | PROVEN |
| rule 20's population and refusal | 0 queries at any ledger size | zero-query proof | PROVEN |

### The socket door (M4 — measured before enforced; harness: `perf/measure_realtime.py`)

| claim | number | instrument | status |
|---|---|---|---|
| connect-time subtree resolution | 1 query per connection, **0 per pushed message**, at all six hats in all three worlds; no Sort node; **no `Seq Scan` at any hat in any world** | count + call count + plan | PROVEN (re-measured; plan pin closed — see below) |
| **the trigger number** — groups joined at connect | root hat **1,255** (2,295 at ×2-orgs) · wide hat 203 (403 at ×2-breadth) · **flat product 3, constant** | layer membership delta | PROVEN (the depth-one property measured: "a flat product pays nothing" holds) |
| **the join-ceiling ruling (on M4's delivered number)** | subtree topology **RETAINED**; the rejected ancestor-chain publish would cost **+400,159 sends per tenant-year** on every emit against 1,255 one-off joins on the rarest, widest connection. **Declared observation ceiling: revisit at 10,000 joins per connect** | arithmetic over the seeded paths | CEILING (declared) |
| push fan-out | 1 `group_send` per emit, whatever the topology or population; frames per recipient 1 → 1 at 500 → 1,000 sockets | send/frame counts | PROVEN |
| delivery census | exactly the hats whose subtree holds the branch — 5/500 at S, arithmetic-exact in every world, zero duplicates; the old bare-tenant-group topology delivered 500/500 (**495 wrong-branch frames stopped**) | frame census | PROVEN |
| the kick | 1 send closes all 50 of one person's sockets, 0 collateral | send/close counts | PROVEN |

**HOLD CLOSED — and the answer is form (a), permanently.**
The fix landed `apps/core/migrations/0015_subtree_read_takes_a_tenant_prefix.py`
(`organization_tenant_prefix`, `(tenant_id, path varchar_pattern_ops)`) and
re-measured. The registry entry keeps form (a) — `index_served`, **no index
name** — not as a placeholder but as the pin the evidence authorizes, because
the re-measure closes off form (b) twice over:

1. **Three indexes narrow this read and the planner mixes them within one
   plan** — `organization_tenant_prefix` on one leg of the selector's `OR` and
   `organization_path_prefix` on the other, at the leaf and spine-tip hats. A
   single name is wrong at those hats even where a path index is
   unquestionably serving the read. The "narrowed by one of these" shape lives
   in `perf/measure_realtime.py::narrows_by_a_path_index`, scoped to hats at or
   below 5% of their tenant — the harness's assertion, not the gate's.
2. **No plan pin may sit at a mid-selectivity hat at all.** The measurement covered the S
   wide hat (16% of its tenant) flipping on **ten pages of index bloat** — 18
   pages takes the composite, 28 pages does not, on identical rows and
   identical statistics; eight consecutive `ANALYZE`s and a
   `SET STATISTICS 1000` on `path` moved neither verdict. A `REINDEX`, a bulk
   load or a vacuum would move that pin, so it would measure the physical table
   rather than the code.

What this *did* fix is real and is in the row above: at the x2:orgs wide hat the
plan was reading 200 other tenants' index entries to answer for 201 of its own,
and that number is now **zero** — because the leading `tenant_id` makes a
materialized path unique per tenant, not because a cost crossover moved. What it
did not fix is stated plainly in the doc: at 100% of a tenant the planner still
reads the tenant index and filters, and it is right to. M4 FINDING 1 stands as
the declared blind spot — the plan follows the *tenant's* org count, not the
hat's; selectivity, not shape — and the property that has never moved in any
world in any index state is the one the gate pins: **no `Seq Scan`**.

A second methodological caution belongs on the same shelf
as FINDING 2: **a measurement taken immediately after `CREATE INDEX` flatters
the index.** The pre-landing sweep built its candidate with one statement on a
loaded table (18 pages) while the migration creates it empty and the bulk seed
grows it (28 pages) — the sweep that justifies a fix and the measurement that
records it must be taken on the same physical index.

## Honest bounds — measured, booked, NOT fixed

**The narrow-hat pagination cost — half fixed and measured, half still
declared. Read both halves or the number above is misleading.**

*The cross-tenant half — **FIXED, MEASURED** (ADR core-11).* Every scoped model used to inherit a single-column `created_at`
index behind `-created_at` ordering, so every paginated list walked the
**deployment-wide** recency index and filtered per row: at the declared scale
the wide hat's page examined **202,300 rows to return zero** — ~100k its own
tenant's and **~102,300 other tenants'**. The bare index is now gone from every
model in the tree and `TenantScopedModel` declares
`(tenant, -created_at)` once, abstractly. Re-measured on the same world:
the page is `Index Scan using widget_recency` with
`Index Cond: (tenant_id = …)` — a `Filter` became an `Index Cond`, the scan's
range is the tenant's own slice, and **foreign-tenant rows examined per page is
0.** House rule 37 is the census that keeps it that way, including through
Django's `Meta.indexes` shadowing hole. `AuditEntry` was the one fixed instance
before this (the per-model form) and is now the general case.

*The narrow-hat half — **UNCHANGED, STILL DECLARED** (ADR core-12).* The wide
hat's page still walks its own tenant's whole widget slice — `rows=100172` on
that same index scan — to return zero rows, and the leaf, region and spine hats
are unchanged in shape and cost. An earlier four-shape index sweep, **including the
composite that has now landed**, moved nothing here, because the lever is
`eqjoinsel` — a join-selectivity estimate over a unique column that can carry
no MCV correction — and not an access path. So at a first consuming product's real-world scale a narrow
hat's page one still costs **O(its own tenant's recent writes)**, not O(its own
rows). That is the bound this envelope declares, and CORE-11 did not lift it.

The query count is 1 and flat through all of it, which is exactly why the
envelope must say this in words: **the gate's counting instruments are
structurally blind to both halves.** The live candidate — hat-scoped
pagination, the subtree org-id `ANY` form, off-root only, COUNT first — stays
parked behind its own measurement rung under ADR core-12's trigger: no index
without a proven reader.

**Other declared blind spots, carried from the docs:** wall-clock, throughput
and lock contention are ClickStack's (no criterion or budget speaks in
seconds, structurally refused at import of every measurement module); one
seeded distribution (a different skew is a different plan); single-connection
measurements (no contention measured); the Temporal-side per-stranded-row
`describe_execution` RPC is unbounded and unmeasured (named by M2); what
1,255 `group_add` round trips cost against a **remote** Redis is a
staging-environment question (M4's declared blind spot — the number that would make the
join cost hurt in a way the trade did not anticipate); the write paths of the
hierarchy (`move_organization` is O(subtree) and unmeasured).

## The gate's half, and how an entry is added

Rules 5 + 35 hold the hot-path registry (`quality/rules.yaml`, rule 35;
counts in `quality/budgets.yaml::hot_path_query_counts`); rule 36 holds the
socket fan-out discipline. **The registry is a closed list — an unregistered
hot path is unguarded until someone registers it.** To add an entry: measure
it first through `perf/` (a count flat under the relevant doubled axis, and
an EXPLAIN verdict, recorded in a measurement doc — measured before
enforced), then add the registry entry with its citation, its count in
`budgets.yaml`, a probe in `quality/hotpaths.py` where the read is probeable,
and clauses only as strong as the measurement supports. An entry no doc
measured is refused by rule 5's citation check.

## Re-triggers — when these claims must be re-proven

- **Any change to a registered hot path** (the per-doc re-trigger lists in
  the four measurement docs are the fine grain: selectors, middleware,
  constraints, `Meta.ordering`/indexes of the measured models,
  `perf/seed.py::ScaleSpec`).
- **A real deployment's scale doubling past any axis of the declared spec**
  (ADR perf-1's own trigger — the table above is the envelope; outgrowing it
  re-opens it).
- A **Postgres major version** (every plan claim), a **pyjwt major version**
  (the JWKS claims), `PATH_MAX_DEPTH` moving (row 0 and the whole depth
  argument), the socket door reaching **10,000 joins per connect** (the
  declared ruling above). **The fix has landed and its HOLD is closed**;
  what replaces it as a trigger is the physical state of
  `organization_tenant_prefix` — a `REINDEX`, a restore or a bulk load moves the
  16%-hat verdict on ten pages, so the *module's* narrow-hat assertion is
  re-read after any of those, while the gate's `no Seq Scan` pin is not.

Re-running means: `./scripts/perf.sh --seed-only`, then the affected
`perf/measure_*.py` at S and at the doubled axis the claim names, then
updating the measurement doc and — only then — any registry pin. The gate
re-measures its own half on every run.

### The computable half, as a block a machine reads

Everything above is prose, and prose is where a re-trigger goes to die: a
`paths:` token is a *coupling*, and the reader that resolves it — the
`envelope:` kind in `scripts/goalpost_scan.py` — used to find its paths by
scraping every backticked token out of this section. That worked, and it
worked by accident: reword a sentence, drop a backtick, move an example, and
the coupling changes without anyone having edited a path. A verdict whose
staleness check quietly narrowed is exactly the class the goal-post scan
exists to refuse.

So the paths are DATA now, in the fenced block below, and the reader reads
**only** the block. Editing the prose above cannot change what the scan
computes; **deleting the block is exit 2**, naming this section, rather than a
scan that silently checks nothing.

```re-trigger-paths
# One path or glob per line; `#` starts a comment. Read by
# `scripts/goalpost_scan.py::envelope_globs` — every line must resolve to
# something this tree has, or the scan is exit 2 naming the line.
#
# What belongs here: the files whose change re-opens the ENVELOPE ITSELF — the
# spec the world is seeded from, the harness that seeds and runs it, and the
# measurement modules whose numbers the claims are. The per-claim fine grain
# (a selector, a model's Meta.ordering) belongs to the measurement doc that
# made the claim, not to this list: this is the coupling that says "the
# envelope's own machinery moved", and widening it here would mark every
# performance verdict stale on a day nobody measured anything.
perf/seed.py
scripts/perf.sh
perf/measure_*.py
```

## Per-axis observations for ClickStack (recorded, never gated)

Wall-clock facts the discipline excludes from criteria, kept here so the
observability stack knows what to watch: the pre-fix audit page cost
87–318 ms at 500k rows depending on cache (the fixed instance of the
cross-tenant pagination class); the relay's `OFFSET` discard makes a batch at `already_seen = N` do
N + batch index lookups (∝ the immovable population); the connect burst for
a wide hat is 1,255 `group_add` round trips against the channel layer;
1,000 concurrent JWKS validations at cache expiry are a thundering-herd and
lock-contention question no count can see; sweep duration and deliveries/sec
are throughput, not statement cost. Each of these is an alert candidate, not
a gate candidate.
