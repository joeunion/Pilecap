# Rejected shapes

`django-architect` § J, in full.

## J · Rejected shapes

Each is settled in `architecture.md` ("Rejected, and why", and the stack
table); a brief that proposes one is returned, not argued.

- **Fat models only** — logic scatters into 2,000-line models and signals; an
  explicit services layer is the one that can be house-ruled (rules **4**,
  **13**).
- **Signals for events** — logic nobody finds; `emit()` from the service,
  inside the transaction (rule **4**; §E3).
- **DRF beside ninja** — two API layers drift with a countdown; ninja's
  schemas serve every door (stack table, "API layer").
- **Celery (+ beat, + an FSM on a model)** — a queue with retries; state,
  resumption and "where is this process" rebuilt per product; Temporal
  replaces it rather than joining it (stack table, "Background work &
  workflows").
- **Schema-per-tenant** — not a template option; a heavily-considered
  exception only for a named business requirement (stack table, "Tenancy").
- **Authorization only at the door** — a new door forgets the check; a
  service cannot be called without it (§C7; rule **13**).
- **`dict` across doors** — no contract, no OpenAPI, no parity check; one
  schema per shape (§E1; rule **16**; conv §13).
- **Random workflow ids** — a retried service starts a second run;
  `workflow_id()` (rule **18**; `apps.workflows.services` on main refuses
  anything else).
- **Inbound webhooks processed inline** — a slow or failing handler loses the
  event; verify → store → workflow (stack table, "Webhooks & events").
- **SQLite anywhere** — hides the Postgres behaviour the product depends on
  ("Rejected, and why").
