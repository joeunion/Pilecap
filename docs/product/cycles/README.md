# Cycle plans — the contracts

> **Holds:** one file per cycle, dated and named for the class it closes
> (`YYYY-MM-DD-<class>.md`): the job, the persona, the rungs with their apps,
> doors and baseline trees, **the acceptance criteria verbatim as the engineering
> lead wrote them before the code existed**, the rejected alternatives, and
> the declared blind spots. Written the moment DECOMPOSE returns. It is the
> only artifact whose loss cannot be repaired by reading the repository.
> **Must not hold:** status. The plan is a contract and must not move; status
> moves ten times a cycle and lives in `in-flight.md`. An edit to a plan's
> criteria is conspicuous in the history by design — that is what makes *"if
> a criterion was wrong, that is a finding against the criteria"* enforceable.
> **Order lives in `queue.md`.** A plan names its queue rows; it does not
> reorder them.

Past plans accumulate here and are what the PATTERN stage reads: *which
criteria turned out to be wrong, and what shape were they?*

`EXAMPLE-cycle-plan.md` is the worked example. Delete it when the first real
plan lands.

## The shape of a plan

```
# Cycle — <the job, in the user's words>
**Type:** feature | debt | nonfunctional · **Framed** <date> · **Queue rows:** …
**Persona:** … · **Job:** … · **Current cost:** … · **Better means:** …
**Debt drawn (band top 1–2):** …
**Misses loaded:** (the misses.md entries touching this area, and which became a criterion)

## Rungs (in order; each lands green alone)
| # | Rung | App | Doors · workflow? | Baseline tree | May run concurrently with |
## Acceptance criteria — verbatim, written before the code
(per rung; each: what observable thing differs if false · the instrument and what it returns when the thing is ABSENT · the "fails on today's code" demonstration, reproducible)
## What must still work (the negatives)
## What these criteria would NOT catch (the declared blind spots)
## Rejected alternatives, and why
## PROVE verdict (appended at stage 6, by the field test — the only section that is written after the code)
```
