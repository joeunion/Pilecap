# ADR workflows-6

**ADR workflows-6 · the run ledger gets a read door, and the actor's own runs replay.**
*Context*: the run ledger was reachable only from admin/shell; "the
actor's own runs" was unanswerable because `WorkflowRun` recorded no starter.
*Decision*: `started_by` (nullable FK User, `SET_NULL` — the ledger outlives
its people) written by `record_run` off the user `start_workflow_on_commit`
already threads; list/get `for_tenant`, policy-gated (`workflowrun.read`),
the list defaulting to `mine=true`; **`start_replay`** (the service verb is
`start` — `replay` is not in the lexicon and the wave may not edit it; INT's
re-pin adds `replay` and the rename back is one commit) resets a FAILED run
the actor started to its first workflow task — Temporal re-executes the
recorded input, which rule 9's determinism is what makes legal; same
deterministic id (rule 18); dispatched `on_commit` robust; history expiry
decided from the row's clock (`HISTORY_RETENTION`, a module constant —
promote to a setting when a deployment's namespace retention differs from
the default); signal/retry stay operator (the ruling). *Rejected*: replay as
re-invoke-the-origin-door (the client may no longer know the input; the
ledger is the thing that knows), storing run inputs in the row (two truths),
backfilling `started_by` (a guess wearing a fact — empty means unknown).
trigger to revisit: history-retention shorter than the product's replay
expectations.
