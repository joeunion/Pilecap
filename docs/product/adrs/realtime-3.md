# ADR realtime-3

- **ADR realtime-3 (door parity for sockets is a test per door pair, not
  a wider rule 17)** · context: rule 17 diffs two *registries* (routes vs tools)
  and proves existence; its own `does_not_cover` says "socket and
  webhook parity (the spine pushes the same envelope by construction)" —
  This is a socket disagreeing with itself across two credentials, a
  *behavioral* parity failure inside one consumer, which no registry
  diff can see even for REST↔MCP (the same `does_not_cover` says so for
  shape) · decision: rule 17's subject stays REST↔MCP; socket parity is
  a **parity test per door pair** in the owning app's tests — session
  socket vs bearer socket on one org-scoped emit, and the
  existing REST-vs-MCP parity test in `example` is the shape's
  precedent; rule 17's `does_not_cover` is amended (one line, granted — this ADR does not edit `quality/**`)
  to stop claiming "by construction" and to name the test · rejected:
  growing rule 17's subject to sockets (there is one consumer and no
  second registry to diff against — a rule with nothing to count is an
  unbound floor by construction, exit 2 forever or a hand list); a new
  rule over "every ASGI middleware that sets `scope['user']` also sets
  `scope['org']`" (two sites today, one of them the fix — a rule born
  with a population of two and a canary that is the bug it just fixed;
  the trigger to revisit is the third site) · trigger to revisit: a
  second consumer, or a third credential path (the OAuth 2.1 socket
  bearer named in architect H), either of which makes a registry diff
  meaningful.
