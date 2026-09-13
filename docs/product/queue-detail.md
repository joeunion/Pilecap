# Queue — the single ordered backlog

> **Order lives here.** Every other document defers to this pair on ordering.
> A row has: what, who holds it, the evidence that it is real, and the band.
> A per-session task list evaporates; anything that must survive gets a row
> the day it is found.
>
> **Two files, one truth.** `queue-detail.md` is the RECORD: every row, in
> full, in order, under its own `### N<id>` anchor line. `queue.md` is a
> GENERATED INDEX over it — one line per row, quoting the row's own first 92
> characters — and it is never edited by hand. Add a row to the record,
> anchor first and row second, then regenerate:
>
> ```
> python3 scripts/queue_index.py --index
> ```
>
> `scripts/queue_index.py --check` compares the index against its own
> regeneration and refuses a hand edit (exit 1, naming the line, with the
> remedy). The split exists so there is one truth and one summary of it,
> rather than two truths — which is what a hand-kept index becomes inside a
> session.
>
> **Everything above the first row is carried into the index verbatim**, so
> anything a reader must meet before the rows belongs here rather than there.
> It is not copied; it is the same bytes, in two files.
>
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

| Part | What it holds |
|---|---|
| the id | stable. **Never reused, never renumbered.** A split keeps both halves traceable (`N7` → `N7` + `N7b`), and each half gets its own anchor |
| the finding | stated as what is false — not as a task. The index quotes its first 92 characters verbatim, so the first sentence is what a reader scans |
| `Holder:` | a role or a cycle. A row with no holder is a wish. Where the token is present, the index carries it |
| the evidence | the artifact it was read from: a `file:line`, a report, a wire response. **A row with no evidence is a hypothesis wearing a status** |
| the band | one of the bands above |

**A row is struck, never deleted** — `~~N7~~ CLOSED (…)` with the merge sha,
so the history of what was believed stays readable. A row moved between
sections keeps its id and its anchor.

**Two things this file's shape is load-bearing about.** An anchor sits on the
line immediately before its row; and a row-defining line is either a bullet
whose first bold token is the id, or a table row whose first cell is the id.
Those are the two shapes `scripts/queue_cited.sh` reads, and the generator
replicates them rather than approximating them, so the citation census goes on
reading this ledger unchanged. An id that ends up carrying two row lines (a
row and its own later addendum about the same work) takes `### N7` and
`### N7 (2)`, so the anchor set stays a key.

**Two ratchets sit in the index's generated header**, and both move down by
machine and up only by a human editing the line and writing the reason on it:
a byte ceiling on the index, and a census count of rows over 1,500 characters.
There is no per-row ceiling, on purpose — a refusal that produces `--no-verify`
is worse than a census that produces pruning.

## Live

The two rows below are the worked example. The first is what an open row looks
like: a falsehood, a holder, an artifact anyone can re-read, a band. The second
is what a closed one looks like — struck with its merge sha, still readable,
never deleted. Delete both when the first real rows land, and delete their
anchors with them.

<!-- worked example — replace with your product's first real entry -->

### N1
- **N1 (floor, cycle 1): a clerk at one customer can read another customer's orders.** `list_orders` filters by status only; the tenant resolver sets `request.tenant` and the route never reads it. Evidence: `apps/orders/api.py:41`; reproduced two-tenant, `GET /api/orders/` → 200 with 6 of tenant B's rows; `pilot-readiness.md` R0. Holder: cycle 1
### N2
- **~~N2~~ CLOSED (merged 4f1e0a2, user band): the `orders.create` MCP tool and `POST /api/orders/` disagree on required fields.** Evidence: the door-parity test `apps/orders/tests/test_doors_over_the_wire.py`. Holder: —
