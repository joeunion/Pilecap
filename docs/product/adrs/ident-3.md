# ADR ident-3

- **ADR ident-3 (the ApiToken join — the subsumption decision)** · context: MCP OAuth 2.1 subsumes the panel's ApiToken-org rung;
  does ApiToken survive? · decision: **ApiToken survives, for first-party
  machine callers** (seed, `issue_token`, field tests, CI probes); OAuth
  2.1 is the third-party door (assistants, DCR clients). Justification:
  retiring it would put a browser consent dance inside `manage.py seed`
  and every existing wire test — the exact DX the deferral logic
  protects — while costing nothing to keep (one authenticator in an
  ordered list). **Org and tenant binding stay request-time for both
  credentials**: the token (either kind) contributes WHO; tenant resolves
  from memberships/pin + `X-Tenant`, the hat from `X-Org` through
  `resolve_org`, revalidated per request from rows — an issue-time org
  claim would go stale against the tree the way the platform's doctrine
  exists to prevent · rejected: retiring ApiToken now, org-in-token
  claims · trigger to revisit: Zitadel service-user PATs reach
  `issue_token`-grade DX (one command, no browser) → a named retirement
  rung.
