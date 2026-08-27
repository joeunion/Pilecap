-- The named half · the four rows the criterion asks for, each found in
-- the sink alone by the one id: the Event, the WorkflowRun, the Delivery and the
-- audited service calls (the AuditEntry's log echo — `<app>.<service>.called`,
-- written by apps/core/service.py beside the row it audits).
--
SELECT
    multiIf(
        LogAttributes['event'] = 'events.record_event.called',            '1 · Event',
        LogAttributes['event'] IN ('workflows.record_run.called',
                                   'workflows.record_run_id.called',
                                   'workflows.finish_run.called'),        '2 · WorkflowRun',
        LogAttributes['event'] IN ('events.record_delivery_attempt.called',
                                   'events.delivery.succeeded',
                                   'events.delivery.failed'),             '3 · Delivery',
        endsWith(LogAttributes['event'], '.called'),                      '4 · AuditEntry echo',
        '5 · other'
    )                                AS row_kind,
    ServiceName                      AS service,
    LogAttributes['event']           AS event,
    count()                          AS n
FROM default.otel_logs
WHERE LogAttributes['correlation_id'] = '00000000000000000000000000000000'
GROUP BY row_kind, service, event
ORDER BY row_kind, service, event
