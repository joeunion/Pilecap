# In flight — the black box

> Thin and volatile: which cycle is live, what stage it reached, the dispatch
> ledger. A trimmed snapshot of the live file's shape, never the live file.

## Live state

One line of state above the table, which is not a row.

## Dispatch ledger

States: *dispatching* → *sent* → *returned*; a `sent` row names its agent.

| # | Task | Role · model | State | Sent | Returned | Result |
|---|---|---|---|---|---|---|
| FX-01 | builder (fresh worktree, a brief by path) | a thing, built | returned | 2026-10-05 10:00 | 2026-10-05 11:00 | met; reports/fx/fx-01.md stamps: sent=2026-10-05 10:00 done=2026-10-05 11:00 met=2026-10-05 12:00 |
| V-FX-01 | verifier (fresh, reading-only; no box) | FX-01's criteria against its branch | returned | 2026-10-05 11:05 | 2026-10-05 12:00 | MET; reports/fx/fx-01.md stamps: sent=2026-10-05 11:05 done=2026-10-05 12:00 |
| FX-02 | builder (the same worktree, a second sitting) | the next thing | sent | 2026-10-05 13:00 | — | — |
