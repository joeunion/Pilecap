# ADR realtime-4

**ADR realtime-4 · a socket handshake carries a one-time ticket, never the bearer.**

**Context.** A browser WebSocket cannot set a header, so the socket accepted the bearer as
`?token=` in the URL (`apps/realtime/middleware.py`). Every URL a handshake carries reaches two
log sinks. uvicorn logs the handshake line, query included, to stdout. Caddy's access log
(`deploy/Caddyfile`) prints the URL as well. The SDK's live-updates page recorded the leak and
went no further.

**Decision.** Option A, plus the redaction filter that closes the line. (1) A REST door,
`POST /api/v1/socket-tickets/`, takes the bearer in the header and mints a ticket through the
`issue_socket_ticket` service. The ticket is 32 random bytes, cached under its SHA-256 for 60
seconds, bound to the person, the tenant and the token that minted it, and good for one use. The
redeem takes it with the cache delete's boolean, then re-checks that the person and the tenant
are active and the token is unrevoked. A ticket opens no more than its minting credential could.
(2) The socket accepts `?ticket=`. A `?token=` handshake is refused before the value is read,
with `socket_credential_in_url`, whose remedies name the ticket door and the `Authorization`
header. (3) `RedactSocketCredentials`, a stdlib logging filter wired in `config/settings/base.py`,
rewrites a `token=` or `ticket=` value on a `/ws/` line to `[redacted]`. This is the closing seam
until every client has moved. It sits on the `uvicorn.error` logger, because all three uvicorn
websocket implementations log the handshake there; `uvicorn.access` never sees a `/ws/` line. (4) No
MCP twin: the ticket is a browser handshake aid. The exemption is a line in rule 17's exemptions.
A face keeps the session cookie. Built at `fc2f2586e` and `8dfacf35b`.

**Consequences.** A compliant client's bearer never leaves a header, and a URL it sends carries at
most a spent ticket. The blind spot: a stale client that still sends `?token=` is refused, but
Caddy's own JSON access log prints that URL once, unfiltered. No shipped client does this; option
A removes the credential from compliant clients' URLs and the filter covers the server's line, so
Caddy's line is the residue a product with old clients must know. A client that sent `?token=` must mint a
ticket or send the header. 2.5.0 is the first publication of the SDK, so the window for removing
the form is now.

**Rejected.** Option B, a log filter alone (in uvicorn and in Caddy). It leaves a long-lived bearer
in browser history, in a cross-origin Referer and in any proxy log, and it is a second place that
must know the parameter name. A cookie-only socket, because scripts need a credential path that is
not a browser session. A database row for the ticket, because that is a table for a sixty-second
value, and ephemeral state belongs in Redis.

**Trigger to revisit.** A client that cannot call REST before its handshake, or a second
credential that must ride a URL.

*Ruled:* 2026-10-23, option A plus the filter. The lead and the architect both recommended it, and
the PM's reconciliation of the two settled it. Recorded after the build. No owner signature is
required, because this is not an exception to a principle.
