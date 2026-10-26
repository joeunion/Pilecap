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

## Dispatch ledger

The dispatch ledger is derived: `.venv/bin/python scripts/ledger_derive.py` (briefs → reports → pull requests).

<!-- worked example — replace with your product's first real entry -->

> ## EXAMPLE — the header block a brief opens with, straight after its title (`ledger_derive.BRIEF_FIELDS`)
>
> ```
> rung: ORD-1
> role: builder
> branch: pm/ord-1
> ```
>
> A brief that names no block is a dispatch the derivation cannot see: exit 2, naming the file.

## Friction log

*(One line per friction, every cycle: **class** · what happened · what it
cost. A class that strikes twice earns a guard. Silence here reads as a
frictionless cycle, and there has never been one.)*

## Dispatch ledger states

States: *sent* (the brief's dispatch commit) → *returned* (its report) → the
pull request's own state — printed by `ledger_derive.py`, never typed. A brief
with no header block is a dispatch the derivation cannot see (exit 2). At CLOSE,
`ledger_derive.py --stale --hours N` names every `sent` row with no report and
no pull request activity; **whether the loop is alive is the agent list's to
confirm — never the table's.** Nothing is moved at CLOSE: the derivation is the
history.
