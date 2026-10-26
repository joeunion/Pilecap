# ADR core-29

**ADR core-29 · an `AuditEntry` is written once per door call, by the
outermost `@service`.** *Accepted by the owner 2026-10-04; proposed by C-CORE-3 (2026-10-03) from the cycle
plan's line (Q14); amends ADR core-22's population "every write" → "every door
call"; awaiting the owner's signature.* *Decision*: a service marked
`@service(witness=False)` — `events.emit`, `events.record_event`,
`events.enqueue_dispatch`, `workflows.record_run` — writes no row while a
service that writes one is running (`core.service._WITNESSED`); called directly
by a door (`events/receivers.py`, `events/activities.py`, `replay_events`) it is
that door call's one row. Measured: one `archive_widget` over REST wrote five
rows before, one after (`apps/core/tests/test_audit_population.py`). *Rejected*:
one row per `@service` frame (five rows for one archive, the run row's actor
empty); "outermost frame for every service" (it silenced the per-tenant rows a
platform-wide sweep writes under a tenant-less outer row — eighteen tests in
six apps, measured); "writes none, ever" as the plan worded it (two of the four
are called straight from doors, and that call would then leave no row).
*Trigger to revisit*: a fifth platform-internal service, or a door that calls
`emit` or `record_run` directly (the census names it).
