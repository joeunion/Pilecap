# ADR workflows-8

- **ADR workflows-8 (2026-09-23) — a cancelled synchronous activity runs
  to its end, and a stopping worker waits for it** ·
  context: Temporal cancels a sync, threaded activity by raising
  `CancelledError` into its thread (`_ThreadExceptionRaiser`, armed per
  definition unless `no_thread_cancel_exception` is set), and `Worker`
  defaults `graceful_shutdown_timeout` to zero, so every worker stop — a
  SIGTERM, every `async with build_worker(...)` exit in a test — cancelled
  in-flight activities at once; a consumer measured the exception landing
  inside `importlib`'s module lock and hanging an xdist worker for good ·
  decision: every sync `@activity.defn` declares
  `no_thread_cancel_exception=True` (every activity here is idempotent and
  bounded by its `start_to_close_timeout`, so a cancelled one runs to its
  bounded end instead of dying mid-transaction), enforced by a pytest census
  over `discovered_activities()` in `apps/workflows/tests/` that names any
  sync activity without it — a product's own included, since the population
  is discovery; and `build_worker` passes `graceful_shutdown_timeout =
  worker_graceful_shutdown()`, DERIVED as the longest attempt bound any
  discovered workflow's call sites declare (`apps/workflows/client.py`), never
  typed. **One change owned by app `workflows` carries the keyword into the nine
  sibling apps' `activities.py` as a mechanical one-keyword change per
  decorator — no import added, no schema, no migration** (the alternative,
  ten rungs, would freeze every app for a keyword) · rejected: caching the
  two "never cached, deliberately" readers (`apps/events/events.py`,
  `apps/core/authz.py`) — removes one `find_spec` site and leaves the class
  (any import inside any sync activity); a worker-level switch — Temporal has
  none, the flag is per definition; a house rule — the census covers the
  population this cycle · trigger to revisit: a sync activity that must be
  interruptible mid-attempt (it would heartbeat and check cancellation
  itself), or a deployment whose process stop grace is shorter than the
  derived window.
