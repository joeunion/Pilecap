# ADR comms-4

- **ADR comms-4 (the seam is produced and consumed together)** · the app
  owns `comms/**` AND the ~40-line connections seam
  (registry + `_hand_off` branch) — seam produced+consumed together (I+).
  Revisit: a second registering app.
  *Amended 2026-10-16 (owner, ruling A on the inbound finding)*: the claimed
  handler runs as `InboundWebhookWorkflow`, one run per receipt started on the
  receipt's commit, never inside the request; a raise is a failed run in the run
  ledger and `handler_failed` on the receipt, so the run ledger is the replay
  (`start_replay`: a run with no starter — a receipt's is the system's — is
  replayed by whoever holds `organization.update` at the tenant's root, the
  house's one admin key; a started run stays its starter's).
