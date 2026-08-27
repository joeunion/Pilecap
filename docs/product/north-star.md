# North star — what we are building, and what "shipped" means

> **Holds:** who the product serves (in order), the reference human, what
> "shipped" means, how we will know, the standing tiebreakers, what we will not
> do. Decisions here are settled the day they are dated; the PM applies them
> and does not reopen them.
> **Must not hold:** a backlog, a status, a feature list, or anything that
> changes weekly. **Order lives in `queue.md`**; every other file defers to it.
> The technical decisions live in `architecture.md`; the taste rulings in
> `design-agreements.md`.
> **Status:** skeleton, apart from the inherited pillar table under *How we
> will know*. Fill this before arming the PM — the loop runs until the ship
> definition below is met, and it cannot run toward a blank.

## The strategy, in the owner's line

*(One quotation, the owner's own words, that the whole product answers to.
Two failures, one system.)*

## Who we serve, in order

*(Numbered. When two users' needs conflict, the lower number wins. Say why
the first one is first — mechanically, not sentimentally.)*

## The reference human

*(One person, named as a role. When two of them conflict, which wins, and what
that means concretely — as testable sentences.)*

## What "shipped" means

*(A table: who · on what · where · sign-in · passing. The loop's terminal
condition. When this is met the PM stops and asks for the next one — a hard
stop, class D.)*

## How we will know

Two registers, one question. **The pillars below are inherited, not an
example** — they are the promises the platform's own mechanisms make, so a
product that clones this repository has already made them and owes a stranger a
way to check each one. **`goal-posts.md` holds one dated verdict per pillar**,
and `python3 scripts/goalpost_scan.py` reads this table as the population: a
pillar here with no row there is exit 2, and that is the correct state for a
product that has not yet audited itself. Amend a promise only with the owner's
ratification — propose it in the cycle report, never edit it unilaterally.

Each pillar states what we promise and how a stranger checks it. The dated
verdict, its proof artifact and its re-trigger live in `goal-posts.md`; the
column below names the standing evidence a verdict is read from.

| Pillar | The promise, plainly | A stranger checks it by | Verdict read from |
|---|---|---|---|
| **Security** | Nobody can give themselves more power, see another tenant's or branch's data, or reach the identity platform around the one door — no matter which legal calls they chain. | An adversarial review that tries to break it and fails; every class ever found is sealed by a rule whose canary fires. | The dated surface-review verdicts; the rules' self-test. |
| **Privacy** | A person can be fully erased (even with no tenant); nobody is messaged against their consent — at queueing, at sending, and after a bounce or complaint; personal data never lands in logs; a departing tenant can take their data out. | Driving erasure, the consent walls, and the log sweep live; exporting a tenant. | The erasure and comms test suites; the comms review verdict. |
| **Auditability** | Every write through every door leaves a row saying who, through which door, and what happened — refusals included. A stranger can reconstruct events from the trail alone. | Writing through all five doors and reading only the audit table. | The verification's door sweep; `apps/core/models.py::AuditEntry`. |
| **Observability** | One id follows a request from the door through services, workflows, and deliveries — and a stranger can answer "what happened to X" from the sink alone. | Tracing one request end-to-end in the telemetry stack. | Rule 19 and the correlation tests; the saved queries under `deploy/observability/`. |
| **Durability** | Kill any part mid-flight — the database, Temporal, Redis — and nothing is silently lost: work heals or the records honestly say it failed. | The chaos drill: killing each organ under load and auditing the aftermath for lies. | The reconciler and relay suites; `scripts/tests/test_backup_restore.sh`. |
| **Performance** | The platform states what scale it is proven to — tenants, tree depth, row counts — and the gate refuses code that degrades a hot path. | Re-running the seeded-scale harness and planting a regression the gate must catch. | `docs/product/scale-envelope.md`; the hot-path rules in `quality/rules.yaml`. |
| **Correctness** | A green gate MEANS it: every rule watches a bound scope, every canary fires when planted, a violation cannot pass silently, and the verdict is earned by an unfiltered run. The most fundamental promise — every other pillar reads through it. | Planting violations and watching the gate refuse; killing a canary and watching exit 2; piping the gate and being refused. | The self-test counts (canaries fired / negatives silent); the verdict ledger (`scripts/gate_ledger.sh`). |
| **Deployability** | A stranger takes a fresh clone to a live URL — TLS, real identity, telemetry, backups that restore — by following the runbook literally, no step failing as written. | Performing the runbook on a clean environment, then restoring a backup onto a second one. | `docs/runbooks/deploy.md` and the dated staging-deploy verdict. |
| **Developer experience** | The 15th builder's first day works: clone, fill the skeletons, first app, first feature through the loop — primer followed literally, generated client in hand, every friction already drained. | The clone rehearsal: a stranger performs day one and ships one feature through one full cycle without editing the system layer. | The primer walkthrough verdicts; `.claude/skills/platform-primer/SKILL.md`. |
| **Upgradability** | A product can take a Django point release or a dependency bump through a documented, tested pattern without fear — and CVEs have a named response path. | Performing one real upgrade through the pattern with the full gate green. | The supply-chain leg in `scripts/check.sh`; the upgrade pattern once performed. |
| **Ingredients** | The platform arrives armed with every top-shelf capability a world-class product experience is made of — storage & documents, search, LLM primitives, delivery tracking & channels, usage metering — each with the same walls, audit, and tenancy as everything else. A product composes; it never hand-rolls a foundation. | The first product's build log: zero foundation capabilities built product-side; each ingredient driven through its doors by a stranger. | The ingredient rungs' verdicts; `apps/{usage,files,search,comms}`. |
| **Velocity** | The loop itself stays fast and honest: cycles close in about a day, the gate tax stays visible and bounded, and speed is recovered by structure — never by thinning proof. | Reading the readouts: cycle durations, the gate-tax figure, the retrospective's guard-latency budget. | `readouts.md` (per-cycle row); `python3 scripts/loop_health.py`. |

**And the product's own measures, beyond the pillars:**

*(A table: measure · bar · read from. Every measure names the artifact it is
read from. A bar the owner has not ruled on is marked **(proposed)**.)*

## Standing tiebreakers

*(Numbered, in order. Applied without asking.)*

## What we will not do

*(Each with the sentence that defends it.)*

---

<!-- worked example — replace with your product's first real entry -->

> ## EXAMPLE — delete when the first real entry lands
>
> **The strategy, in the owner's line.** *"Our customers run their orders on
> spreadsheets and we find out what shipped by asking."* Two failures, one
> system: in the warehouse, nobody knows what is promised; at the top, nobody
> can trust the number.
>
> **Who we serve, in order.** 1 · the order clerk, who enters what a customer
> asked for. 2 · the warehouse lead, who decides what ships today. 3 · the
> owner, who reads the number. The clerk is first because every other screen
> is made of the clerk's keystrokes: no order entered, no number to trust.
>
> **The reference human.** The day-one clerk — the person who has never used
> this product and has a customer on the phone. Testable: every empty state
> proposes the next act; a required field is never one the system already
> knows; a mistake is reversible from the screen it was made on.
>
> **What "shipped" means.** Who: one customer's order desk, three clerks ·
> On what: real orders, real addresses, real money · Where: a live host with
> real authentication and a tested restore · Sign-in: email + password via
> the template's auth · Passing: they enter the week's orders here and not in
> the spreadsheet, by week 3, unprompted.
>
> **How we will know.** Orders entered here vs in the spreadsheet — 100% by
> week 3 — read from the orders table and the clerk's word · Time to a new
> clerk's first order — inside the first session — read from the `created_at`
> of their first `Order` vs their first login · Orders list answers in under a
> second at 5,000 rows — read from the query pin in
> `apps/orders/tests/test_api.py` **(proposed)**.
>
> **Standing tiebreakers.** 1 · the one that removes a clerk's keystroke wins.
> 2 · the one the system can record on its own rather than ask the clerk to type wins. 3 ·
> the one that is configuration rather than code wins. 4 · still tied — ship
> the smaller one and watch a clerk use it.
>
> **What we will not do.** Build an accounting system — the invoice leaves
> here as a PDF and a webhook; the ledger is someone else's. Import from the
> spreadsheet before a clerk has entered ten orders by hand — the import hides
> the class of defect we most need found first.
