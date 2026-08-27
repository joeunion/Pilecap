-- "Show me what this request did." ----------------------------------------------
--
-- The whole shape of one business action, in the order it happened, across both
-- processes: the REST door, the @service span it opened, the workflow the
-- service started, the activity the WORKER ran, and the delivery attempt at the
-- end of it. The join key is the correlation_id (apps/core/context.py) — not the
-- trace id, because a chain that crosses a workflow boundary is several traces
-- and one chain.
--
-- Paste a different id and this answers the same question about that chain.
--
SELECT
    l.Timestamp                          AS at,
    l.ServiceName                        AS service,
    l.LogAttributes['door']              AS door,
    l.LogAttributes['event']             AS event,
    t.SpanName                           AS span,
    t.SpanAttributes['temporalWorkflowID'] AS workflow_id
FROM default.otel_logs AS l
LEFT JOIN default.otel_traces AS t ON t.SpanId = l.SpanId
WHERE l.LogAttributes['correlation_id'] = '00000000000000000000000000000000'
ORDER BY at ASC
