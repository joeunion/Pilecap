# Misses — what we believed that was false

> **Order lives in `queue.md`.** A promotion from this log becomes work only
> when it has a row there.
> One line per miss, every cycle. Every entry ends in one of three outcomes —
> **a rule with a canary**, **a line in `design-agreements.md`**, or
> **accepted with a reason**. An entry that ends in none of those is a note,
> and notes rot.
> **Status:** skeleton. The first entry lands at the first CLOSE.

The question is never "how did the cycle go". It is: *what did we believe that
was false, and what would have caught it sooner?*

## The outcome ladder — which level an entry earns

| Level | What it means | Who can write it |
|---|---|---|
| **Level 1** | a house rule with a canary — the belief cannot be held again | the engineering lead, with the rule id |
| **Level 2** | a standing method rule (a skill clause, a brief clause) | the PM |
| **Level 3** | a doctrine line — read by humans, enforced by nobody | the PM |
| **Accepted** | it stays possible, and here is the sentence that defends that | the owner, or the PM citing a ruling |

**A level is not a compliment.** Higher is not better: the deciding factor is
how *settled* the belief is. An unsettled rule enforced at level 1 breaks work
nine tests deep for a reason nobody could have known in advance.

## Inherited, before the first cycle

*(Not misses of this product — misses the method was shaped by, carried here
so the first decomposition can turn them into criteria.)*

| # | We believed | It was false because | Outcome |
|---|---|---|---|

## Cycle 1

| # | We believed | It was false because | Outcome |
|---|---|---|---|

<!-- worked example — replace with your product's first real entry -->

> ## EXAMPLE — one promoted entry; delete when the first real one lands
>
> | # | We believed | It was false because | Outcome |
> |---|---|---|---|
> | 1 | House rule 8 covers every route that reads a scoped model | The rule's scope was derived from `api.py` alone, and the orders routes live in a package (`apps/orders/api/orders.py`) — so a tenant leak sat in a shipped door with the rule green above it | **Level 1**: rule 8's scope reads `apps/*/api.py` *and* `apps/*/api/**`, with a canary planted in a package route that must fire (`quality/rules.yaml`, rule 8) |
>
> That is the shape: the belief stated as a belief, the falsehood stated with
> the artifact that proved it, and an outcome that is a mechanism — not a
> resolution to be more careful.
