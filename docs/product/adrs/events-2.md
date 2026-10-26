# ADR events-2

- **ADR events-2 (purge schedules namespaced by task queue)** ·
  purge schedule id + workflow id namespaced by task
  queue (`events-purge-expired:<queue>`, `system:events:purge:<queue>`);
  ensure_purge_schedule deletes the legacy global id when present
  (idempotent, logged). Revisit: a deployment wanting one purge across
  queues.
