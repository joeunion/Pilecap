# ADR events-1

- **ADR events-1 — ERRATUM, not a decision.** This id is cited exactly
  once, in a fan-out totals note reading "the fan-out's total
  `1 + list_endpoints_for(t) x 5` (RENAME's name for `endpoints_for`) — grows with subscribers — ADR events-1's
  fan-out shape", and **no ADR with this id was ever written**: not in
  `cycles/`, not in `archive/`, not anywhere in the repository's git
  history. The shape the citation points at is real and is the events
  spine's built dispatch design — one relay start plus one delivery
  activity per endpoint, in parallel, each with its own retry
  (`apps/events/workflows.py`; the machinery ADR events-3 and ADR
  events-4 describe). Recorded here as an erratum so the citation
  resolves to the truth about itself; no decision text is invented, and
  a future ADR wanting this number should take the next free one
  instead.
