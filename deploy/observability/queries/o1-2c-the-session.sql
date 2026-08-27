-- "Show me everything this session did." ---------------------------------------
--
-- WHERE THE session_id COMES FROM, because the answer is not where it looks.
-- `apps.core.middleware.ContextMiddleware` is the OUTERMOST middleware, above
-- Django's `SessionMiddleware`, so `request.session` does not exist at the
-- moment it binds and `context.bind()` drops the `None`. The id is bound one
-- middleware lower, by `TenantMiddleware`, which runs after the session and is
-- the reason REST and admin lines carry one at all. The socket door
-- (`apps/core/asgi_middleware.py`) and the MCP door (`config/mcp.py`) bind
-- their own.
--
-- A request with no session cookie — a token call, a probe — binds nothing,
-- which is the honest answer and not a gap: this query counts the requests
-- that had a session, never invents one for the requests that did not.
--
SELECT
    LogAttributes['session_id']                   AS session_id,
    uniq(LogAttributes['correlation_id'])         AS chains,
    count()                                       AS log_lines,
    min(Timestamp)                                AS first_seen,
    max(Timestamp)                                AS last_seen
FROM default.otel_logs
WHERE LogAttributes['session_id'] != ''
GROUP BY session_id
ORDER BY log_lines DESC
