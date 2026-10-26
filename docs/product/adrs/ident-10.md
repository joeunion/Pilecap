# ADR ident-10

**ADR ident-10 · 2026-09-15 · a domain claim routes nothing until verified.**
*Context*: R2 (the sign-in surface review) F1 — any tenant admin claimed any
domain and the platform sign-in routed on it: a lockout (a person elsewhere
refused by a foreign claim) and an absorption (a stranger landed in the
claimant), both confirmed over the wire. *Decision*: `SsoDomain.verified_at`,
set only by `verify_sso_domain` (an operator's audited act through
`manage.py verify_sso_domain`, permission `sso_domain.verify`); `for_domain`
honours verified rows only; a claim reserves the name unverified; public mail
providers are refused at the door by a declared knob
(`SSO_REFUSED_MAIL_DOMAINS`) whose list is a courtesy, not the wall.
*Rejected*: DNS TXT verification now (a resolver dependency and a workflow for
a population of zero — the trigger is the first product wanting tenant
self-serve, at which point the same service is the seam the activity calls); a
backfill marking existing claims verified (grandfathers the hole). *Trigger to
revisit*: that self-serve product; or a second verification road, which is
refused as a second writer.
