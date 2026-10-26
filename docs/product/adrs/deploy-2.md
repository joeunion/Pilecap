# ADR deploy-2

- **ADR deploy-2 (names under one env-backed domain)** · context: the domain ruling makes one
  domain the platform's own surface — rehearsals, warm-up, the production issuer —
  with per-product subdomains later; a real deployment's chosen `.dev` domain is
  HSTS-preloaded, so every name is HTTPS from birth (the shipped default,
  `example.invalid`, is deliberately unresolvable) · decision: the environments-contract table
  in the plan — `<env>.example.invalid` for the app, `auth.` and `o11y.`
  prefixes per env, Temporal UI unexposed, SES identity on the apex with
  MAIL FROM `mail.example.invalid` · rejected: per-service apex names
  (`staging-auth.example.invalid` — flat namespace ages badly), a separate
  zone per env (two zones to keep consistent, $6/yr of nothing),
  exposing the Temporal UI behind auth (one more door to wall; the
  tunnel is the wall) · trigger to revisit: T0's product names land, or
  a second standing environment.
