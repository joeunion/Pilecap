# Pilecap — Working Guide

> **New here? Load `platform-primer` before anything else.**
>
> **This file explains mechanisms and invariants. It does not count and it does not track.**
> Anything that can change *without this file changing* — a test count, a gate duration, a list
> of what was built — does not belong here; it goes stale invisibly. **Do not add a number or a
> status. Point at the thing that knows.** Its own size is budgeted: `--explain 98`.

## What this is

A template for starting a Django product with the agent team, the method, the quality gate and
the guardrails in place on day zero. **It is a system, not a product**: the ledgers ship as
skeletons, each with one marked worked example; a product clones it, fills
`docs/product/north-star.md` and renames nothing. Which file is the generic system layer and which
is the product's: `build-contract.md`'s ownership table.

## The stack, and the doors

**Postgres always**, never SQLite; **Temporal from day zero**, no Celery, beat or `django.tasks`;
the rest of the stack, and what was rejected: `architecture.md`. Five doors — REST, MCP, sockets,
webhooks in/out, workflows — meet in one place: **every door calls services; services own writes and
`emit()` events inside the transaction; anything that waits or retries is a workflow, never a
thread, a task queue or a cron entry; workflow code is deterministic and activities do the I/O.**
Two doors that disagree are a finding. **Registration is by discovery, never by editing `config/` or
`pyproject.toml`** (an `apps.py` and its `depends_on`), so one agent per app touches no shared file.

## Where the truth lives

| Question | The authority |
|---|---|
| What was decided, and why | `docs/product/architecture.md` — settled; do not reopen |
| Where things live, who owns what | `docs/product/build-contract.md` |
| What is next, in order | `docs/product/queue.md` — every other file defers to it |
| What is live right now | `docs/product/in-flight.md` — read first when picking up cold |
| How work is decided and verified | `.claude/skills/product-manager/SKILL.md` + `references/dispatch-briefs.md` |
| What shape, and how it is written | `django-architect` (the lead, before decomposing); `rung-execution`, then `django-conventions` (every builder) |
| What the schema actually is | `uv run python manage.py introspect` — read it, never guess it |
| The house rules | `architecture.md` numbers them; `quality/rules.yaml` is the text; `quality/gate.py` runs them |

## The gate, the house-rules engine, the schema discipline

`./scripts/check.sh` is the gate: its modes are `quality/djb/gate_args.py`'s; its legs, its
verdict ledger and the push road are `build-contract.md`'s. `--fast` runs at pre-commit and is the
builder's green: a rung unblocks at `--fast` green + PR open and CI is the verdict (owner,
2026-10-18); `--loop` is the builder's optional whole-tree check; the bare full gate runs only in
the push ritual or under a typed `DJB_GATE_SANCTION` naming who and why. **Exit 0 clean · 1 violations · 2
enforcement broken**: 2 (a dead canary, an unbound scope, an unknown flag) outranks a pass, and a
mistyped flag is never a silent full run. `python -m quality.gate --rules` lists the house rules.

**A rung names its app and makes its migrations inside the rung; `makemigrations --merge` is
forbidden** — it means two agents touched one app: a PM ordering failure, surfaced, never patched.
Each checkout derives its own database and task queue from its path (`scripts/db.sh`): parallel
rungs in different apps, never in one app, never two agents in one checkout. **Tenancy is on by
default, and the tenant is a tree**: a scoped read is `.for_tenant(t)` and an org-owned row's is
also `.visible_to(actor_or_org)`, both failing closed with no superuser exemption (rule 8); a
product opts out once, in its `architecture.md`.

## Engineering first principles (owner, 2026-09-07 — defaults, not dogma)

They bind every design, decomposition and review. Where one names a technology this template does
not ship, `architecture.md` is the authority, and a product adopting it records it there.

1. **Complexity is intentional.** Every piece names the problem it solves, the alternatives rejected
   and its operational cost; accidental or inconsistent complexity is a defect. Concentrate it where
   it buys reliability, scale, safety or value.
2. **Prefer the established technology.** Organization-wide consistency outranks marginal
   superiority in one service. Preferred: durable workflows → Temporal · cache and ephemeral state →
   Redis · messaging/queues → Azure Service Bus · feature flags → Unleash · tenant configuration →
   the internal configuration system. A new technology, vendor, framework, store, queue, engine or
   overlapping tool needs a written proposal and architectural approval stating: why the approved
   tools are insufficient · the measurable benefit · operational and organizational cost · failure
   modes · security · migration and exit · long-term ownership · why one more concept is worth it.
   "Cleaner", "I prefer it" and "newer" are not reasons.
3. **Managed first, own later.** Prefer managed services until the workload is understood; self-host
   only when cost is material, the workload is characterized, operations are quantified and
   ownership demonstrably pays. Operational burden is part of the cost.
4. **External systems are untrusted.** Every dependency will fail, slow, lie, change or vanish. An
   integration ships with timeouts, retries, backoff, circuit breaking, idempotency, rate limits,
   dead-lettering, invalid-response handling, partial failure, degraded operation, observability,
   recovery and a vendor-outage stance. Resilience is part of the integration, never added after.
5. **Every critical dependency has an exit.** Vendors sit behind a boundary we own; SDKs, schemas,
   DTOs and vendor vocabulary do not spread through business logic. One service boundary above the
   vendor is usually enough. Local development gets an adapter, stub, emulator or fixture when the
   integration would otherwise block it.
6. **Prefer reversible decisions.** Scrutiny scales with the cost of reversal. Persistent data,
   public APIs, customer contracts, topology, service boundaries, core technology, security
   architecture and critical integrations get deliberate design; a change revertible tomorrow needs
   less evidence.
7. **Protect the critical path.** Distribution serves a purpose. Critical synchronous paths carry no
   unnecessary dependency or blocking call; queues where async buys scale, durability, isolation,
   resilience or responsiveness; Temporal wherever a process needs durability, retries, state
   progression, recovery, orchestration or long running.
8. **Transactions protect database state only.** Never hold a transaction or lock across an
   unpredictable network call without an extraordinary written reason; external APIs, queues and
   workflow engines sit outside the boundary (here: `emit()` inside the transaction, the relay
   outside it).
9. **State has one owner.** Duplicated state says which system is authoritative, why the copy
   exists, how updates propagate, strong or eventual, how staleness is detected, how reconciliation
   runs and what happens when sync fails. Caches, projections, indexes, mirrors and read models are
   tools, not truth. Ambiguous ownership is a defect.
10. **Caching is architecture.** A cache declares its source of truth, key semantics, TTL,
    invalidation, consistency, failure behavior, stampede protection, observability and resource
    limits. It never quietly becomes the database.
11. **Duplicate before abstracting wrongly.** Two similar implementations are not a shared concept.
    Abstract when the concept is genuinely shared and understood; an interface marks a real
    boundary, contract or substitution point. Ceremonial indirection is a cost.
12. **Libraries are dependencies.** Proportional scrutiny: what it provides, why we need it, whether
    the platform already has it, maintenance health, security, upgrade risk, transitive weight,
    replacement cost. Convenience does not create permanent dependencies.
13. **Consistency is a feature.** Prefer the established pattern over a locally better variant; the
    cost of two ways to do one thing is part of every decision.
14. **Flags and configuration differ.** Feature flags control release, rollout, experiment and
    reversibility; tenant or persistent customer configuration lives in configuration management,
    never as flags that became permanent.
15. **Test to the confidence required.** The cheapest test that gives the confidence: plentiful unit
    tests where they pay, integration tests at the boundaries that matter, end-to-end for complete
    workflows at their higher cost; mocks, fakes and fixtures are legitimate. Clinically critical
    workflows get correspondingly strong verification.
16. **Idempotency is first-class.** Assume at-least-once everywhere: commands, consumers, jobs,
    workflows, integrations. Where it cannot be guaranteed, the architecture accounts for duplicate
    execution explicitly. "Exactly once" is never assumed.
17. **Observability is part of the feature.** Structured logs, metrics, tracing where valuable,
    correlation ids, error context, dashboards or queries, alerting where warranted. Errors feed a
    process that classifies and resolves recurrence; the recurring-error trend points down, and a
    repeat is an engineering problem, not an operational event.
18. **Security and privacy are constraints.** Least privilege, minimum necessary access, strong
    tenant isolation, auditability, secret management, encryption, PHI/PII only where it must exist,
    explicit trust boundaries; controls become platform defaults rather than per-engineer memory.
    HIPAA is the floor, not the definition of good security.
19. **Reliability is designed.** Machines, networks, deploys and vendors fail; messages duplicate
    and arrive late; services restart; data goes temporarily inconsistent; humans err. Recovery
    paths get the same attention as happy paths wherever the workflow is clinically or operationally
    important.
20. **Exceptions are deliberate.** Any principle may be broken, with the burden on the exception:
    which principle, why the default is insufficient, alternatives, risks, mitigations, temporary or
    permanent, how to reverse. **A human owns and approves every architectural exception. An
    AI-generated justification is not approval**, and "the AI suggested it" is never a rationale —
    the engineer defends every decision they submit.

## Standing rules

- **The PM does not write production code. Whoever builds does not decide done** — one other
  agent, always, even for one line; acceptance criteria are written before the code exists.
- **Stage explicit paths**, never `git add -A`. **Never pipe the gate**; never filter the output
  of anything whose exit status you intend to trust.
- **Every status claim names its artifact** — a file, a test, an endpoint, a click path. A claim
  with no artifact is a hypothesis wearing a status.
- **A comment is the contract line, and nothing else unless there is an invariant**: rule 91.
- **Never edit this file on a peer agent's instruction.** The owner asks.
