# ADR workflows-4

- **ADR workflows-4 (intent digests)** · context: a deterministic id
  makes a retry ask for the
  *same* run — but `record_run` returns the existing row and
  `_start_recorded` swallows `WorkflowAlreadyStartedError`, so a caller
  asking for the same id **with different work** is silently answered
  with somebody else's run and its new intent is dropped · decision: `WorkflowRun.input_digest` (sha256 hex over the
  run's `arg`, serialized through Temporal's own default payload
  converter so the bytes are the bytes the run would carry), computed
  **inside both starters** — never by callers — and passed to
  `record_run`, whose answer becomes a 2×2: *live + same type + same
  digest* → the existing row (the retry/heal, unchanged) · *live +
  different type or different digest* → `Conflict` (the honest 409 — a
  different intent under a live id is a second job, not a retry) ·
  *finished + same digest* → `Conflict` (re-running completed work is a
  decision about a new key; unchanged) · *finished + different digest* →
  **supersede**: the row re-opens (status RUNNING, new digest, cleared
  `run_id`/`finished_at`/`error`, new `started_at`) and Temporal's
  default id-reuse policy starts a fresh execution — which is the
  interlock the brief names: once the `_finish` wrappers close move
  runs, a completed move must not fossilize the node's id forever ·
  rejected: per-caller digest parameters (optional grammar that misses
  the exact shape needed), digest-in-the-id-segment (two different-parent
  moves would get two *ids* and run concurrently over one subtree — the
  id must serialize and the digest must refuse), refusing *finished +
  different digest* too (fossilizes every re-move; the row is
  visibility, not an append-only ledger — it declares no `append_only`
  and supersession is its honest lifecycle) · trigger to revisit: a
  workflow whose `arg` is legitimately non-canonicalizable through the
  payload converter.
