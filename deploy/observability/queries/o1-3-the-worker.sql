-- "Is the half of the platform that WAITS actually visible?" -------------------
--
-- Every activity the worker container ran, attributed to `worker` and carrying
-- the deterministic workflow id (house rule 18) that joins a span to its run
-- row. If this comes back empty while the app is serving traffic, everything
-- that waits is invisible at the exact moment it matters.
--
SELECT
    Timestamp                              AS at,
    ServiceName                            AS service,
    SpanName                               AS span,
    SpanAttributes['temporalWorkflowID']   AS workflow_id,
    round(Duration / 1e6, 1)               AS ms,
    StatusCode                             AS status
FROM default.otel_traces
WHERE ServiceName = 'worker' AND SpanName LIKE 'RunActivity:%'
ORDER BY at DESC
LIMIT 25
