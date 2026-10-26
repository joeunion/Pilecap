# ADR workflows-2

- **ADR workflows-2 (duplicate start → idempotent-return)** ·
  duplicate start → idempotent-return (docstring wins):
  existing RUNNING row + matching type returns the row, client start
  attempted, WorkflowAlreadyStartedError swallowed (also heals
  row-without-run); type mismatch on live id → Conflict; terminal row →
  Conflict. Revisit: re-run-after-completion = a new key, ruled then.
