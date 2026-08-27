# Queue — the single ordered backlog

> **Order lives here.** Every other document defers to this one on ordering.
> A row has: what, who holds it, the evidence that it is real, and the band.
> A per-session task list evaporates; anything that must survive gets a row
> here the day it is found.
> **Status:** skeleton. The first row lands the day the first thing is found.

## Bands

Ordering is **risk × proximity to a user**. The non-functional band is drawn
from at every cycle — the *top* 1–2, never the cheapest. Empty means stale,
not clean.

| Band | What sits in it |
|---|---|
| `floor` | the product cannot exist without it |
| `user` | a named user notices it, by name |
| `non-functional` | correctness, safety, durability, cost — drawn top-down |
| `band` | found by a rung and worth surviving the session |

## What a row is

| Column | What it holds |
|---|---|
| `#` | a stable id. **Never reused, never renumbered.** A split keeps both halves traceable (`N7` → `N7` + `N7b`) |
| `What` | the finding, stated as what is false — not as a task |
| `Holder` | a role or a cycle. A row with no holder is a wish |
| `Evidence` | the artifact it was read from: a `file:line`, a report, a wire response. **A row with no evidence is a hypothesis wearing a status** |
| `Band` | one of the bands above |

**A row is struck, never deleted** — `~~12~~` with the merge sha, so the
history of what was believed stays readable. A row moved between sections
keeps its id.

## Live

| # | What | Holder | Evidence | Band |
|---|---|---|---|---|

<!-- worked example — replace with your product's first real entry -->

> ## EXAMPLE — one row of each kind; delete when the first real rows land
>
> | # | What | Holder | Evidence | Band |
> |---|---|---|---|---|
> | 1 | **A clerk at one customer can read another customer's orders.** `list_orders` filters by status only; the tenant resolver sets `request.tenant` and the route never reads it. | cycle 1 | `apps/orders/api.py:41`; reproduced two-tenant, `GET /api/orders/` → 200 with 6 of tenant B's rows; `pilot-readiness.md` R0 | floor |
> | ~~2~~ | ~~**The `orders.create` MCP tool and `POST /api/orders/` disagree on required fields.**~~ **done — merged 4f1e0a2** | — | door-parity test `apps/orders/tests/test_doors_over_the_wire.py` | user |
>
> The first row is what an open row looks like: a falsehood, a holder, an
> artifact anyone can re-read, a band. The second is what a closed one looks
> like — struck with its merge sha, still readable, never deleted.
