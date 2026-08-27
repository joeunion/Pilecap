# In flight — the black box

> Thin and volatile. Which cycle is live, what stage it reached, the dispatch
> ledger. The **plan** is the contract and lives in `cycles/`; this file is the
> status and moves ten times a cycle. A cold PM reads this first, then
> `queue.md`, then the product-manager skill.
> **Status:** skeleton — the empty contract. It fills the moment the first
> cycle opens and is emptied again at every CLOSE, into
`readouts.md` and `docs/product/archive/`.

## Live cycle

*(The cycle's name, one line. Then `Stage:` — where it is right now, in the
PM skill's own vocabulary. Nothing here survives a CLOSE except by moving to
`readouts.md`; closed-cycle tables move to `archive/in-flight-closed.md`.)*

**Stage:** *(no cycle is open)*

## Live dispatch table

| # | Task | Role · model | State | Sent | Returned | Result |
|---|---|---|---|---|---|---|

<!-- worked example — replace with your product's first real entry -->

> ## EXAMPLE — one dispatch row; delete when the first real one lands
>
> | # | Task | Role · model | State | Sent | Returned | Result |
> |---|---|---|---|---|---|---|
> | 1-3 | ORD-1: the tenant leak in the orders list door — rule 8's scope widened to `apps/*/api/**` with a canary in a package route; red-first, both doors | development · opus · worktree | returned — MERGED (← 4f1e0a2) | 2026-03-05 | 2026-03-06 | leak reproduced two-tenant then closed; canary fires; `--loop` exit 0 |
>
> The Result cell is where the rung's evidence lands — the merge sha, the
> gate's exit status, what went red before it went green. A cell that names
> no artifact is a hypothesis wearing a status.

## Friction log

*(One line per friction, every cycle: **class** · what happened · what it
cost. A class that strikes twice earns a guard. Silence here reads as a
frictionless cycle, and there has never been one.)*

## Dispatch ledger states

States: *dispatching* → *sent* → *returned*. Advance to `sent` in the same
action as the call, **and a `sent` row names its agent** — a row that cannot
name its agent is not sent. At CLOSE, sweep the table: any row still at
`dispatching` or `sent` with no live or returned agent behind it is a
finding. **When checking whether the loop is alive, ask the agent list —
never this table.**

Closed-cycle ledgers move out of this file at CLOSE, into
`docs/product/archive/` (one file, `in-flight-closed`), so this one stays
readable cold.
