-- The instrument · which of the platform's ids actually reach the sink.
--
-- `mapContains`, not `!= ''`: a bound-then-empty id and an id that was never
-- bound look identical to an equality test, and the difference is the whole
-- question. Each declared id is checked one column each.
--
SELECT
    count()                                                AS log_lines,
    countIf(mapContains(LogAttributes, 'correlation_id'))  AS with_correlation_id,
    countIf(mapContains(LogAttributes, 'causation_id'))    AS with_causation_id,
    countIf(mapContains(LogAttributes, 'request_id'))      AS with_request_id,
    countIf(mapContains(LogAttributes, 'session_id'))      AS with_session_id,
    countIf(mapContains(LogAttributes, 'trace_id'))        AS with_trace_id,
    countIf(mapContains(LogAttributes, 'door'))            AS with_door,
    countIf(mapContains(LogAttributes, 'tenant_id'))       AS with_tenant_id,
    countIf(mapContains(LogAttributes, 'org_id'))          AS with_org_id
FROM default.otel_logs
