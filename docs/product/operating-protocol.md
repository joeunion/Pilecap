# Operating protocol — this product's settings on the method

> **Holds:** the product-specific settings of the method — the autonomy dial
> this product runs at, the readout cadence and who receives it, the standing
> practices the owner has adopted for *this* product. State, dated.
> **Must not hold:** the method itself. **The method is
> `.claude/skills/product-manager/SKILL.md`** and its `references/`, and this
> file defers to it on every question of how work is decided or verified. Two
> documents answering the same question is drift with a countdown; this one
> stays short so the skill stays the authority.
> **Order lives in `queue.md`.**
> **Status:** skeleton. Set the dial and the cadence before arming the PM.

## The autonomy dial

Three settings; the difference is only how often the loop pauses, never what
the rules are. At any setting the hard stops (world outside the repo ·
irreversible acts on real data · the ship definition) hold and the readout
happens.

| Setting | The owner sees | Cost of being wrong |
|---|---|---|
| **1 · Supervised** | every commit-sized rung | lowest; slowest |
| **2 · Cycle** | the design gate, then the proving verdict — twice per cycle | one cycle of rework |
| **3 · Wave** | a readout and a demo per wave; only the hard stops interrupt | several cycles of rework; taste drift compounds silently |

**This product runs at:** *(setting · since · who decided)*

## The readout

*(Cadence, and who receives it.)* Five lines, in this order:

1. What the reference user can do now that they could not before.
2. What moved on `pilot-readiness.md`, and what did not.
3. What is blocked, on whom, and what it costs per week of waiting.
4. What the PM got wrong — a design that failed proving, a criterion written
   badly, an estimate that was fantasy.
5. What the PM wants to do next, and what it would drop to do it.

Line 4 is not humility furniture. A readout that never contains it means either
the cycles are too small to be interesting or the proving stage is not real.

## Standing practices adopted for this product

*(Dated, with the owner's words and the measurement that earned each. Method
that is general goes to the skill; only what is specific to this product stays
here.)*

- **2026-08-30 · the checklist readout** ("during your updates print out the
  checklist plan and mark whats done, whats in progress, and whats pending…
  every time" → "make this a standard for the builders PM too"): every PM
  status update prints the cycle checklist with ✅/🔄/⬜ marks. Promoted to
  the PM skill the same day (the general half lives there); this line is the
  product's record of adopting it.

---

> ## EXAMPLE — the one marked worked example this ledger ships with (CLAUDE.md § What this is); a product keeps it beside its own entries and never renames it
>
> **This product runs at:** setting 2 for the first two cycles, then 3 — Joe,
> 2026-03-01: *"everything but taste is machine-checked here; two cycles is
> enough to calibrate."*
>
> **The readout:** weekly, Friday, to Joe, in the repo as a commit to
> `readouts.md` plus five lines in the session.
>
> **Standing practices adopted for this product:**
> - 2026-03-08 — *"the field test drives REST and the MCP tools from an empty
>   database first, the screen second"* — after a seeded fixture hid that
>   `Order.total` was never computed from lines entered through the API.

## The pre-wave reap

Before dispatching a wave, run `./scripts/sweep.sh --roots <the directory
holding clones of this repository>`, read the FOREIGN list, and sweep it with
`--roots <the same directory> --sweep --force-foreign` — `--force-foreign`
without `--roots` is refused (add `--hot-path`/`--perf` only if you also mean
the warm caches). This is the operator's job and it is not in the gate:
FOREIGN is an absence of evidence rather than a finding, and a gate reddened
by a deleted checkout's leftovers teaches people to override the gate. The
gate's `own-tree-census` leg covers each builder's own checkout and says
nothing about the machine. (First run is the owner's explicit step.)

**Read the `stranded:` roll-up first.** The census closes with the
queues NOTHING IS POLLING that no visible checkout owns, each with the
schedules still aimed at it, the open runs piled behind it and how old the
oldest is — and every Temporal row above it now carries the same clocks (when
a schedule last fired, what became of that action, when it fires next, how
deep and how old a queue's backlog is). That is the layer between the
checkouts and the containers, and it has one owner: this sweep, because a
deleted checkout cannot self-clean — the worker's startup self-clean (ADR
platform-lifecycle-1) only ever covers a LIVE checkout's own legacy. A queue
a visible checkout derives is deliberately left out of the roll-up: an idle
own queue has no poller either, and an alarm that is normally true is one
people learn to skip.

## The intent-materialization lens (standing, surveyor + PM)
For every declared intent — a model declaration, a config row, a constant, a generated file, a numbered runbook step — ask: what act makes the world match this, who performs it, at what moment? Classify: **self-reconciling** (converges at a boot/gate/discovery moment that always happens) · **tripwired-but-manual** (drift detected, but detection and action wait on a named human and cadence — or it is the silent class wearing a tripwire) · **silent** (nothing notices until it costs). The fix ladder: the digest-reconcile shape (rule 27 and the search ruling are the precedents; demote the manual command to backstop) → a tripwire at a moment someone MUST look (a gate leg, a boot refusal, pm_triage — never a line that scrolls, which is silence with extra steps) → an argued "manual is correct" (legitimate only for owner-gated destruction and counterparty-owned mints). A note printed every run is not a tripwire; a runbook number is not an automation; an idempotent script nobody's moment invokes is a digest-reconcile missing only its moment — the cheapest class to close.
