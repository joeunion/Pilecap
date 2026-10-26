# ADR workflows-9

- **ADR workflows-9 (2026-09-29) — PROPOSED (the owner signs)** — the run
  row's actor is the caller's actor, passed keyword-only; `record_run` never
  reads the bound context for who. *Rejected*: reading the bound context (five
  audit rows for one write disagree about who — S8-37). trigger to revisit: a
  run recorded from a door that has no actor (a schedule) — that is the system
  actor, named, not an absence. *(Drafted as "workflows-6"; that number is the
  run ledger's read door above, so it takes the next free one.)*
