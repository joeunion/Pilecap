-- "What happened to X?" --------------------------------------------------------
--
-- One correlation id, every service call it caused, in both processes and
-- through both doors. This is the query an operator runs first, and the reason
-- house rule 20 forbids minting a correlation id below a door: if a service
-- minted its own, this returns one row instead of twenty.
--
SELECT
    ServiceName                  AS service,
    LogAttributes['door']        AS door,
    LogAttributes['event']       AS event,
    count()                      AS n
FROM default.otel_logs
WHERE LogAttributes['correlation_id'] = '00000000000000000000000000000000'
GROUP BY service, door, event
ORDER BY service, event
