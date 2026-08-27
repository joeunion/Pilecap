# Readouts — one row per completed cycle

> Filled at CLOSE. `scripts/loop_health.py` evaluates the last two completed
> rows and exits 1 when two or more signals hold, **2 when the scoreboard
> cannot be read**. A blank column counts as a miss, never a zero.
>
> **Every closed cycle owes a ROW, on this table.** A cycle written up only as a
> `##` section below the table is judged by nobody and the reader says the board
> is fine — that is exit 2 with the heading quoted.
>
> **Persona verdict — two things in one cell:** a comparison **token** from
> `{better, same, worse, untested}`, and the verifier's verdict **verbatim**.
> Write `worse — verifier: "…"`, or put the token last as
> `verifier: "…" · token: **untested**`; both are read. The token is checked for
> MEMBERSHIP, never for positivity — `worse` is a legal row that fires the
> persona signal, and a cell with no token (or two) is exit 2, because a reader
> scoring a vocabulary nobody speaks is worse than no reader at all.
>
> **Criteria met / total — LEAD WITH THE FINAL FRACTION.** The cell is scored by
> its **first** `n/m`; everything after it is prose for humans. A cell that opens
> with a mid-cycle count is scored on the mid-cycle count.
>
> **Status:** skeleton. The first row lands at the first CLOSE. The row below
> whose first cell begins `EXAMPLE` is skipped by the reader by design
> (`scripts/loop_health.py:174`) — it is the format, not a cycle.

<!-- worked example — replace with your product's first real entry -->

| Cycle | Closed | Criteria met / total | Persona verdict | Misses promoted to L1/L2 | Debt drawn (band top 1–2) | Overran session? | Debt added (with trigger) |
|---|---|---|---|---|---|---|---|
| EXAMPLE — 1 · the clerk can take an order end to end | 2026-03-09 | 7/7 at CLOSE (the first verification pass read 5/7; the two FAILs — inline customer create, draft status — fixed in-cycle and re-verified on the second) | verifier: "took a complete order from an unknown customer in one request path" · token: **better** | L1: rule 8's scope widened to `apps/*/api/**` (the tenant leak's real cause) · L2: criteria are written before the builder exists, even for a one-line fix | the non-functional band's top two: nightly off-box backup, and the first restore drill | no — opened and closed the same day | N3 (the orders list is 3+N queries; trigger: 2,000 orders in one tenant) · N4 (no rate limit on the token route; trigger: before real users) |

## Cycle sections

*(One `##` heading per closed cycle, below the table, holding what the row
cannot: what was built, what was found, what it cost. Every heading here owes
a row above — a section with no row is judged by nobody, and the reader says
so with exit 2.)*
