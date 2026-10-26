# ADR workflows-7

**ADR workflows-7 · a run its owner started, its owner may stop —
and the ledger's third word is witnessed, never asserted.**
*Context*: The run ledger could show you your work and re-run it when it
failed, and had no way to stop one that was running away — the only cancel in
the product was the Temporal CLI, which is not a door. And `WorkflowRun.Status`
had two closing words, so a run somebody deliberately stopped read, months
later, exactly like one that broke; the reconciler lumped Temporal's own
`CANCELED` into `FAILED` for want of anywhere else to put it.
*Decision*: **`cancel_run`** — `POST /api/v1/runs/{run_id}/cancel/` plus the
MCP twin over `contract_of` — with `start_replay`'s four walls in
`start_replay`'s order: tenant (`for_tenant` → `NotFound`), membership
(`require(actor, "workflow_run.cancel", run)`, a named `policies.py` predicate),
ownership (`started_by` null or not the actor's → `NotFound`, never
`Forbidden`, the existence-oracle argument), state (non-RUNNING → `Conflict`
naming the status). The Temporal cancel is dispatched on
`transaction.on_commit(..., robust=True)`, the fifth registration in the tree's
survey. **`Status` gains `CANCELLED`** (one expand-only, choices-only
migration) and **the service stamps no row field at all**: a cancellation is a
*request*, so the door answers with the row as it is — still `running` — and
the contract sentence tells the caller to poll. The row closes as `cancelled`
only when somebody witnessed it, and there are exactly two witnesses:
`workflows._finish`, which now catches a server-originated cancellation
(`asyncio.shield` around the mark, because a cancelled workflow's own task is
already cancelled; `workflow.cancellation_reason()` to tell that from an inner
scope losing a race), and `activities.reconcile_runs`, whose `CLOSED_AS` maps
`CANCELED → cancelled`. A cancelled run does not replay: `start_replay` refuses
it with a `Conflict` of its own naming the status, because a deliberate stop is
not a failure. Audited as `workflows.cancel_run` per door; **no event** — there
is no consumer, and the trigger is recorded rather than the topic shipped.
*Rejected*: operator-wide cancel (ADR workflows-6's ruling stands — signal and
retry-tuning stay operator-only, and cancel is the actor's own for the same
reason replay is); a synchronous row close at the door (the ledger would assert
an outcome because somebody asked for one, and a workflow that ignored the
cancel and completed would leave a `cancelled` row over a `completed` history);
a `workflows.run.cancelled` event (nothing subscribes; the trigger is the first
subscriber). trigger to revisit: the first stuck run whose owner has left the
tenant — the own-run wall means no admin can clear it, which is deliberate
today and is the thing that will make somebody want an operator door.
