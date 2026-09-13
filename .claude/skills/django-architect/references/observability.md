# Observability — what every door and service carries

The long form of `django-architect` § G.

**G2 — What every service, door and workflow carries.** Every door binds
context (`request_id`, `session_id`, `tenant_id`, `user_id`, `correlation_id`,
`causation_id`, `trace_id`) **before** calling a service (**[A7a]**
`core.context`); `@service` opens a span `<app>.<service>`, logs `.called` /
`.failed` with the bound context and writes the **[A7a]**
`core.audit.AuditEntry` — actor (`actor_user`, `actor_token`, `actor_kind` =
human|agent|system), action (the service name), object type + id, door
(rest|mcp|socket|workflow|webhook|admin|shell), outcome, redacted input per
`LOG_KEYS`, and the three ids. `correlation_id` is minted at the door and
never below it; `causation_id` is the immediate parent; both ride every
`Event`, `WorkflowRun`, `Delivery` and `AuditEntry`, the Temporal memo and
`X-Correlation-Id`; `traceparent` propagates into outbound webhook headers.
`AuditEntry` is append-only — the first member of the declared `append_only`
population (§D8) — no update or delete path anywhere. *Enforced:*
house rule **20**; **13** (the decorator is what writes it). *Wrong:* a
service that mints a `correlation_id`; an admin action that updates an
`AuditEntry`. *Right:* the door binds, the service inherits.

**G3 — What the lead specifies per rung.** For every rung: *which events* it
emits (names from `events.py`, with `v`); *which audit actions* must exist
afterwards (service names and expected `door` values — a rung touching MCP
produces `door=mcp` rows); *which metrics matter* (route latency/status for
the new routes, service count/duration/failures, workflow/activity outcomes,
outbox lag, delivery failures) and which one the criterion reads. The shape of
such a criterion: "an `AuditEntry` with `action=issue_invoice, door=rest`
exists for the created row, and none exists for the refused one."
