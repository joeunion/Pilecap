-- The other half · the worker's LOG lines beside its spans, so the span
-- and the line are demonstrably the same piece of work: `door = workflow`, the
-- chain's correlation id, and the activity's own span id — which is what makes
-- "show me the logs for this span" a click rather than a timestamp hunt.
--
SELECT
    l.Timestamp                              AS at,
    l.LogAttributes['door']                  AS door,
    l.LogAttributes['event']                 AS event,
    l.LogAttributes['correlation_id']        AS correlation_id,
    t.SpanName                               AS span,
    t.SpanAttributes['temporalWorkflowID']   AS workflow_id
FROM default.otel_logs AS l
INNER JOIN default.otel_traces AS t ON t.SpanId = l.SpanId
WHERE l.ServiceName = 'worker' AND t.SpanName LIKE 'RunActivity:%'
ORDER BY at DESC
LIMIT 25
